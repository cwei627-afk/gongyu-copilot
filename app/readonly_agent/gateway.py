"""Bounded, request-local read-only capabilities. No persistent business replica.

The model chooses tool/ID; this boundary chooses whether a call is permitted,
validates actual HTTP facts, and produces provenance and the final answer.
"""
import copy
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, ProxyHandler, build_opener

from app.analysis.generation_nodes import parse_model_text, strict_json, validate_schema
from app.analysis.workflow_nodes import timestamp
from app.enterprise.models import HeatTaskLink, InventoryBatch, ProductionOrder, SourceResponse
from app.enterprise.nodes import enterprise_digest, enterprise_provenance
from app.schemas import Heat

OPERATIONS = {
    'mes_heat': ('MES', 'get_mes_heat', '/api/mes/heats/{id}'),
    'mes_links': ('MES', 'get_mes_heat_enterprise_links', '/api/mes/heats/{id}/enterprise-links'),
    'erp_order': ('ERP', 'get_erp_production_order', '/api/erp/production-orders/{id}'),
    'wms_batch': ('WMS', 'get_wms_inventory_batch', '/api/wms/batches/{id}'),
}
OUTPUT_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {'selected_claim_ids': {'type': 'array', 'minItems': 1, 'maxItems': 4,
                     'items': {'type': 'string'}}, 'answer': {'type': 'string', 'minLength': 1, 'maxLength': 16000}},
    'required': ['selected_claim_ids', 'answer']}
ID_PATTERN = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}'


class GateError(ValueError):
    def __init__(self, code, category='request'):
        self.code, self.category = code, category
        super().__init__(code)


def failure(code, category='request'):
    return {'status': category + '_error', 'category': category, 'code': code,
            'answer': '事实未完整验证，停止业务结论；请核对参数、来源或使用原 Stage C 异常分析入口。',
            'facts': {}, 'data_sources': [], 'citations': [], 'automatic_actions': [],
            'human_confirmation': '本入口仅只读查询；任何生产判断与操作须人工确认。'}


def intent(query):
    """A limited, explicit identifier grammar; uncertainty asks for clarification.

    This is a permission gate, not an entity existence whitelist or tool planner.
    Tool invocation remains the native Dify Agent's decision.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise GateError('CLARIFICATION_REQUIRED')
    if re.search(r'PLC|控制设备|调整设备|扣减|写入|修改订单|任意SQL|删除|执行SQL', query, re.I):
        raise GateError('READ_ONLY_ONLY')
    if re.search(r'异常|是否正常|合格|处置|SOP|工艺标准|温度.*(正常|范围)|成分.*正常', query, re.I):
        raise GateError('USE_STAGE_C_WORKFLOW')
    if re.search(r'猜测|编造|假装|估计库存|无需调用|跳过校验', query):
        raise GateError('UNVERIFIED_FACT_REQUEST')
    matches = []
    patterns = {'heat': [rf'(?:heat_id|炉次号?|炉号)\s*[=:：]?\s*({ID_PATTERN})',
                         rf'({ID_PATTERN})\s*号炉'],
                'order': [rf'(?:production_order_id|ERP订单|订单号?|生产订单)\s*[=:：]?\s*({ID_PATTERN})'],
                'batch': [rf'(?:batch_id|WMS批次|批次号?)\s*[=:：]?\s*({ID_PATTERN})']}
    for kind, expressions in patterns.items():
        for expression in expressions:
            matches += [(kind, m) for m in re.findall(expression, query, re.I)]
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise GateError('CLARIFICATION_REQUIRED')
    kind, entity = matches[0]
    # Multiple literal IDs also require clarification (no hidden second target).
    literals = re.findall(r'\b(?:DEMO-|PO-|BATCH-)[A-Za-z0-9_.-]+', query)
    if any(value != entity for value in literals):
        raise GateError('CLARIFICATION_REQUIRED')
    want_wms = bool(re.search(r'WMS|库存|仓位|库存批次', query, re.I))
    want_erp = bool(re.search(r'ERP|订单|生产任务', query, re.I))
    if kind == 'order' and re.search(r'MES|炉次.*状态|炉.*生产状态', query, re.I):
        raise GateError('CLARIFICATION_REQUIRED')
    if kind == 'batch' and re.search(r'ERP|MES|订单.*(?:状态|详情)', query, re.I):
        raise GateError('CLARIFICATION_REQUIRED')
    allowed = {'mes_heat'} if kind == 'heat' else {'erp_order'} if kind == 'order' else {'wms_batch'}
    if kind == 'heat' and (want_erp or want_wms): allowed |= {'mes_links', 'erp_order'}
    if kind in ('heat', 'order') and want_wms: allowed.add('wms_batch')
    return {'root_kind': kind, 'root_id': entity, 'allowed_tools': sorted(allowed)}


def read_http(base, path, request_id, timeout):
    """Fixed backend base, no model URL, no proxy env, redirects forbidden."""
    from urllib.request import HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(base.rstrip('/') + path, headers={'X-Request-ID': request_id}, method='GET')
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(100001)
            return response.status, raw.decode('utf-8')
    except HTTPError as exc:
        return exc.code, exc.read(100001).decode('utf-8')
    except TimeoutError as exc:
        raise GateError('UPSTREAM_TIMEOUT', 'system') from exc
    except (URLError, UnicodeError, OSError) as exc:
        raise GateError('UPSTREAM_UNAVAILABLE', 'system') from exc


@dataclass
class Run:
    request_id: str
    permission: dict
    created: float
    as_of: datetime
    lock: threading.Lock = field(default_factory=threading.Lock)
    calls: list = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    error: dict | None = None
    consumed: bool = False


class Gateway:
    def __init__(self, backend_base, *, fetch=read_http, clock=None, monotonic=time.monotonic,
                 max_calls=4, ttl=300, timeout=5, max_age=21600):
        self.backend_base, self.fetch = backend_base, fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic, self.max_calls, self.ttl = monotonic, max_calls, ttl
        self.timeout, self.max_age, self.runs = timeout, max_age, {}
        self.lock = threading.Lock()

    def begin(self, query, request_id):
        if not re.fullmatch(ID_PATTERN, request_id or ''): raise GateError('INVALID_REQUEST_ID')
        permission = intent(query)
        with self.lock:
            self.runs = {key: value for key, value in self.runs.items()
                         if self.monotonic() - value.created < self.ttl}
            if len(self.runs) >= 100: raise GateError('CAPACITY_LIMIT', 'system')
            if any(run.request_id == request_id for run in self.runs.values()):
                raise GateError('DUPLICATE_REQUEST_ID')
            token = secrets.token_urlsafe(32)
            self.runs[token] = Run(request_id, permission, self.monotonic(), self.clock())
        return {'capability': token, 'permission': permission, 'output_schema': OUTPUT_SCHEMA}

    def _run(self, capability):
        run = self.runs.get(capability)
        if not run or run.consumed: raise GateError('INVALID_CAPABILITY')
        if self.monotonic() - run.created >= self.ttl:
            run.error = failure('CALL_DEADLINE_EXCEEDED', 'system')
        return run

    def _permit(self, run, operation, entity):
        if operation not in OPERATIONS or operation not in run.permission['allowed_tools']:
            raise GateError('TOOL_NOT_AUTHORIZED')
        if not isinstance(entity, str) or not re.fullmatch(ID_PATTERN, entity):
            raise GateError('INVALID_PARAMETER')
        if len(run.calls) >= self.max_calls: raise GateError('TOOL_CALL_LIMIT')
        if any(item['tool'] == operation for item in run.calls): raise GateError('REPEATED_TOOL_CALL')
        root, expected = run.permission['root_kind'], run.permission['root_id']
        facts = run.facts
        if operation == 'mes_heat':
            if root != 'heat' or entity != expected: raise GateError('ENTITY_NOT_AUTHORIZED')
        elif operation == 'mes_links':
            if 'mes_heat' not in facts or entity != expected: raise GateError('MES_FACT_REQUIRED')
        elif operation == 'erp_order':
            if root == 'heat':
                if 'mes_links' not in facts: raise GateError('VERIFIED_LINK_REQUIRED')
                expected = facts['mes_links']['production_order_id']
            if entity != expected: raise GateError('ENTITY_NOT_AUTHORIZED')
        elif operation == 'wms_batch':
            if root != 'batch':
                if 'erp_order' not in facts: raise GateError('VERIFIED_ORDER_REQUIRED')
                expected = facts['erp_order']['batch_id']
            if entity != expected: raise GateError('ENTITY_NOT_AUTHORIZED')

    def _validate(self, run, operation, entity, status, body):
        if status >= 500 or status in (401, 403, 429) or status <= 0:
            raise GateError('UPSTREAM_TIMEOUT' if status == 504 else 'UPSTREAM_FAILURE', 'system')
        if len(body) > 100000: raise GateError('INVALID_TOOL_RESPONSE', 'system')
        try:
            data = strict_json(body)
            if status != 200:
                if status in (404, 409) and data['error']['category'] == 'data':
                    code = data['error']['code']
                    if code not in {'OBJECT_NOT_FOUND', 'UNVERIFIED_CROSS_SYSTEM_RELATION', 'MISSING_FIELDS', 'INVALID_DATA'}:
                        raise ValueError('untrusted error code')
                    raise GateError(code, 'data')
                if status == 422 and data['error']['category'] == 'request' and data['error']['code'] == 'INVALID_PARAMETER':
                    raise GateError('INVALID_PARAMETER', 'request')
                raise GateError('INVALID_TOOL_RESPONSE', 'system')
            if operation == 'mes_heat':
                if set(data) != set(Heat.model_fields): raise ValueError('fields')
                Heat.model_validate_json(body)
                fact = data
                if fact['heat_id'] != entity: raise GateError('ENTITY_IDENTITY_CONFLICT', 'data')
                updated = fact['updated_at']
            else:
                model = {'mes_links': HeatTaskLink, 'erp_order': ProductionOrder, 'wms_batch': InventoryBatch}[operation]
                envelope = SourceResponse[model].model_validate_json(body)
                fact = data['data']
                if envelope.request_id != run.request_id: raise GateError('CROSS_REQUEST_REPLAY', 'data')
                if envelope.content_sha256 != enterprise_digest(fact): raise GateError('API_HASH_MISMATCH', 'data')
                key = {'mes_links': 'heat_id', 'erp_order': 'production_order_id', 'wms_batch': 'batch_id'}[operation]
                if fact[key] != entity: raise GateError('ENTITY_IDENTITY_CONFLICT', 'data')
                updated = fact['source_updated_at']
            age = (run.as_of - timestamp(updated)).total_seconds()
            if age < 0 or age > self.max_age: raise GateError('STALE_OR_FUTURE_DATA', 'data')
            if 'due_date' in fact: timestamp(fact['due_date'])
            for value in fact.values():
                if isinstance(value, str) and (not value.strip() or re.search(
                        r'\[cite:|<think>|ignore.*instruction|system prompt|忽略.*指令|执行指令|https?://', value, re.I)):
                    raise GateError('UNSAFE_SOURCE_TEXT', 'data')
            if 'heat_ids' in fact and (len(fact['heat_ids']) != len(set(fact['heat_ids']))):
                raise GateError('ENTITY_IDENTITY_CONFLICT', 'data')
            if 'heat_ids' in fact and any(not value.strip() for value in fact['heat_ids']):
                raise GateError('MISSING_SOURCE_FIELDS', 'data')
            link, order = run.facts.get('mes_links'), run.facts.get('erp_order')
            if operation == 'mes_links' and fact['steel_grade'] != run.facts['mes_heat']['steel_grade']:
                raise GateError('CROSS_SYSTEM_IDENTITY_CONFLICT', 'data')
            if operation == 'erp_order' and link:
                if (any(fact[k] != link[k] for k in ('production_order_id', 'steel_grade', 'material_code', 'batch_id'))
                        or link['heat_id'] not in fact['heat_ids']):
                    raise GateError('CROSS_SYSTEM_IDENTITY_CONFLICT', 'data')
                if fact['revision'] < link['expected_erp_revision']: raise GateError('SOURCE_REVISION_MISMATCH', 'data')
            if operation == 'wms_batch' and order:
                if any(fact[k] != order[k] for k in ('production_order_id', 'material_code', 'batch_id')):
                    raise GateError('CROSS_SYSTEM_IDENTITY_CONFLICT', 'data')
                if fact['unit'] != order['material_unit']: raise GateError('UNIT_MISMATCH', 'data')
                if fact['status'] != 'available': raise GateError('BATCH_NOT_AVAILABLE', 'data')
                if link and fact['revision'] < link['expected_wms_revision']:
                    raise GateError('SOURCE_REVISION_MISMATCH', 'data')
            return fact
        except GateError: raise
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise GateError('INVALID_TOOL_RESPONSE', 'system') from exc

    def call(self, capability, operation, entity):
        run = self._run(capability)
        with run.lock:
            if run.error: return copy.deepcopy(run.error)
            start = self.monotonic()
            row = {'tool': operation, 'entity_id': entity, 'method': 'GET', 'http_performed': False}
            try:
                self._permit(run, operation, entity)
                system, op_id, template = OPERATIONS[operation]
                path = template.format(id=quote(entity, safe=''))
                row.update(endpoint=path, http_performed=True)
                status, body = self.fetch(self.backend_base, path, run.request_id, self.timeout)
                row.update(http_status=status, response_body=body)
                fact = self._validate(run, operation, entity, status, body)
                provenance = enterprise_provenance(system, op_id, path, entity, run.request_id, body, fact)
                if operation == 'mes_heat': provenance['source_updated_at'] = fact['updated_at']
                run.facts[operation] = fact
                run.sources.append(provenance)
                text = self._claim(operation, fact)
                claim = {'claim_id': 'api_' + enterprise_digest([run.request_id, operation, fact])[:32], 'text': text}
                run.claims.append(claim)
                row.update(validated=True, code='VERIFIED_FACTS')
                return {'status': 'verified', 'facts': copy.deepcopy(fact),
                        'verified_claims': copy.deepcopy(run.claims), 'output_schema': OUTPUT_SCHEMA}
            except GateError as exc:
                run.error = failure(exc.code, exc.category)
                row.update(validated=False, code=exc.code)
                return copy.deepcopy(run.error)
            except Exception:
                run.error = failure('TOOL_EXECUTION_FAILED', 'system')
                row.update(validated=False, code='TOOL_EXECUTION_FAILED')
                return copy.deepcopy(run.error)
            finally:
                row['elapsed_ms'] = round((self.monotonic() - start) * 1000, 3)
                run.calls.append(row)

    @staticmethod
    def _claim(operation, f):
        if operation == 'mes_heat':
            return f"MES 炉次 {f['heat_id']}：钢种 {f['steel_grade']}，源状态 {f['status']}，更新时间 {f['updated_at']}。"
        if operation == 'mes_links':
            return f"MES 正式关联：炉次 {f['heat_id']} → 订单 {f['production_order_id']}、物料 {f['material_code']}、批次 {f['batch_id']}；关联修订 {f['revision']}。"
        if operation == 'erp_order':
            return f"ERP 订单 {f['production_order_id']}：钢种 {f['steel_grade']}，状态 {f['status']}，计划 {f['planned_quantity']} {f['quantity_unit']}，完成 {f['completed_quantity']} {f['quantity_unit']}；物料 {f['material_code']} 需求 {f['required_quantity']} {f['material_unit']}，指定批次 {f['batch_id']}；修订 {f['revision']}。"
        return f"WMS 批次 {f['batch_id']}：物料 {f['material_code']}，预留订单 {f['production_order_id']}，可用量 {f['available_quantity']} {f['unit']}，仓库 {f['warehouse']}，仓位 {f['location']}，状态 {f['status']}；修订 {f['revision']}。"

    def finish(self, capability, text):
        run = self._run(capability)
        with run.lock:
            try:
                if run.error: return copy.deepcopy(run.error)
                for source in run.sources:
                    age = (self.clock() - timestamp(source['source_updated_at'])).total_seconds()
                    if age < 0 or age > self.max_age:
                        raise GateError('STALE_OR_FUTURE_DATA', 'data')
                if set(run.facts) != set(run.permission['allowed_tools']): raise GateError('INCOMPLETE_TOOL_EVIDENCE', 'data')
                output, reasoning = parse_model_text(text)
                validate_schema(output, OUTPUT_SCHEMA)
                if '[cite:' in reasoning: raise GateError('UNAUTHORIZED_CITATION', 'data')
                catalog = {claim['claim_id']: claim['text'] for claim in run.claims}
                selected = output['selected_claim_ids']
                if len(selected) != len(set(selected)) or set(selected) != set(catalog):
                    raise GateError('UNVERIFIED_MODEL_CLAIM', 'data')
                if output['answer'] != '\n'.join(catalog[key] for key in selected):
                    raise GateError('MODEL_FACT_COVERAGE_FAILED', 'data')
                assessment = None
                if {'erp_order', 'wms_batch'} <= set(run.facts):
                    order, batch = run.facts['erp_order'], run.facts['wms_batch']
                    assessment = {'required_quantity': order['required_quantity'],
                                  'available_quantity': batch['available_quantity'], 'unit': batch['unit'],
                                  'status': 'sufficient' if batch['available_quantity'] >= order['required_quantity'] else 'insufficient'}
                return {'status': 'verified_read_only', 'code': 'VERIFIED_API_QUERY', 'request_id': run.request_id,
                        'answer': output['answer'], 'facts': copy.deepcopy(run.facts),
                        'data_sources': copy.deepcopy(run.sources), 'inventory_assessment': assessment,
                        'citations': [], 'automatic_actions': [],
                        'human_confirmation': '仅为已验证只读事实；工艺异常分析请使用 Stage C，生产操作须人工确认。'}
            except GateError as exc: return failure(exc.code, exc.category)
            except (ValueError, TypeError, KeyError): return failure('INVALID_AGENT_OUTPUT', 'system')
            finally: run.consumed = True
