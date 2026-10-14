"""Desktop presentation adapter. Frozen workflow evidence gates remain upstream."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from pathlib import Path

from app.copilot import presenter
from app.copilot.contracts import Intent, Query, Route
from app.copilot.gateway import Gateway
from app.copilot.router import route
from app.copilot.transport import ServiceFailure, Transport, http
from app.copilot.question_answers import add_answers
from app.copilot.general_reference import eligible as reference_eligible, validate_packet, product as reference_product
from app.analysis.generation_nodes import strict_json

DISPLAY = re.compile(r'(?<![A-Za-z0-9_-])(?:H|PO|LOT)\d{8}-\d{4,}(?![A-Za-z0-9_-])', re.I)
INTERNAL = re.compile(r'F(?:HEAT|ORDER|LOT)-[A-Za-z0-9.-]+')
CN = {'DEMO-A': '演示钢种A', 'DEMO-LINE-A': '演示产线A', 'endpoint': '终点',
      'review': '待复核', 'frozen': '冻结', **presenter.STATUS}
GROUPS = {'MES': '炉次与生产状态', 'ERP': '生产订单', 'WMS': '物料与库存'}
ROOT = Path(__file__).resolve().parents[2]


def knowledge_transport(original):
    """Only the F2 desktop entry uses the new index; old published paths stay intact."""
    values = dict(original.values)
    path = ROOT / '.env.stage-f2.local'
    local = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                local[key.strip()] = value.strip()
    for kind in ('INTERNAL', 'PUBLIC'):
        # Missing F2 configuration fails explicitly instead of silently using old F.
        values['DIFY_F_' + kind + '_API_KEY'] = local.get('DIFY_F2_' + kind + '_API_KEY', '')
    values['DIFY_E1_API_KEY'] = values['DIFY_F_INTERNAL_API_KEY']
    return Transport(values)


def workspace_route(question, **kwargs):
    selected = route(question, **kwargs)
    # A resolved heat plus a deviation/SOP request belongs to the existing
    # deterministic analysis workflow, not the read-only status Agent.
    # Selection happens after the original safety and entity checks.
    if (selected.intent == Intent.LIVE_ENTERPRISE_QUERY and selected.entity_kind == 'heat'
            and re.search(r'规程|SOP|核对|检查', question, re.I)
            and re.search(r'温度.*(?:偏高|偏低|偏差)|成分.*(?:偏差|不符)', question)):
        return Route(intent=Intent.ANOMALY_ANALYSIS, entity_kind='heat', entity_id=selected.entity_id)
    # Only bounded list criteria. Safety, ambiguity and entity checks keep priority.
    if selected.intent == Intent.CLARIFICATION and selected.reason in ('MISSING_OBJECT','UNCERTAIN_INTENT'):
        match = re.fullmatch(r'(?:请|帮我|查询|查看|列出|看看|有哪些|的|当前|现在|\s)*(冻结|零库存|待检)(?:的|库存|批次|物料|有哪些|记录|\s|？|\?)*', question)
        if match:
            return Route(intent=Intent.LIVE_ENTERPRISE_QUERY, collection='wms',
                         filters={'limit':10,'status':{'冻结':'frozen','零库存':'zero_stock','待检':'quality_hold'}[match[1]]})
    return selected


def normalize_source_entities(question, identities):
    """Accept natural ID placement only after the source resolved its identity.

    The label is routing syntax, not an inferred cross-system relationship.
    Keep every requested entity so the existing ambiguity/safety gates still run.
    """
    labels = {
        'heat': r'heat_id|炉次号?|炉号|号炉',
        'order': r'production_order_id|ERP订单|生产订单|订单号?',
        'batch': r'batch_id|WMS批次|库存批次|批次号?',
    }
    typed = {'heat': '炉次', 'order': 'ERP订单', 'batch': 'WMS批次'}
    by_id = {row['display_id']: row for row in identities}
    conflict = False

    def replace(match):
        nonlocal conflict
        row = by_id[match[0]]
        before, after = question[:match.start()], question[match.end():]
        for kind, pattern in labels.items():
            if kind != row['entity_kind'] and (
                re.search(r'(?:' + pattern + r')\s*[=:：]?\s*[「“"\[]?\s*$', before, re.I)
                or re.match(r'^\s*[」”"\]]?\s*(?:' + pattern + r')', after, re.I)
            ):
                conflict = True
        # Keep an already parseable prefix. Duplicating "生产订单 ERP订单"
        # would make the legacy parser mistake the literal ERP for a second ID.
        existing_prefix = re.search(r'(?:' + labels[row['entity_kind']] + r')\s*[=:：]?\s*$', before, re.I)
        prefix = '' if existing_prefix else typed[row['entity_kind']] + ' '
        return prefix + row['internal_id'] + ' '

    return DISPLAY.sub(replace, question), conflict


def retain_verified_context(service, body, out):
    """A short-lived entity reference, never conversation memory or copied facts."""
    if out.intent == Intent.ANOMALY_ANALYSIS and out.status in ('no_anomaly','review_required','abstain'):
        heats = {s.entity_id for s in out.sources if s.source_type=='MES' and s.entity_id}
        if len(heats)==1:
            out.context_token=service.context.issue({'heat':heats.pop()})
    elif out.intent in (Intent.INTERNAL_KNOWLEDGE,Intent.GENERAL_INDUSTRY_KNOWLEDGE) and out.status in ('answered','abstain'):
        if service.context.verify(body.context_token):
            out.context_token=body.context_token
    return out


def local_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return value
        return parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return value


def readable(value, identities):
    text = str(value)
    for row in identities:
        text = re.sub(r'(?<![A-Za-z0-9_.-])' + re.escape(row['internal_id']) + r'(?![A-Za-z0-9_.-])',
                      lambda _: row['display_id'], text)
    text = CN.get(text, text)
    # Whole tokens only: DEMO-A is also a substring of FDEMO-ALLOY and
    # FDEMO-A19. Display labels must never corrupt material/location identity.
    for raw, label in [('DEMO-LINE-A','演示产线A'),('DEMO-A','演示钢种A')]:
        text = re.sub(r'(?<![A-Za-z0-9_-])' + raw + r'(?![A-Za-z0-9_-])', label, text)
    text = re.sub(r'(?<![A-Za-z0-9_-])DEMO-G(\d{2})(?![A-Za-z0-9_-])', lambda m: '演示钢种' + m[1], text)
    text = re.sub(r'(?<![A-Za-z0-9_-])DEMO-FURNACE-(\d+)(?![A-Za-z0-9_-])', lambda m: m[1] + '号炉', text)
    text = re.sub(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)',
                  lambda m: local_time(m[0]), text)
    return text


class WorkspaceTransport:
    """Per-request recorder; no global result cache or cross-request fact reuse."""
    def __init__(self, original):
        self.original = original
        self.values = getattr(original, 'values', {})
        self.list_result = None
        self.knowledge_result = None

    def workflow(self, kind, inputs):
        if kind in ('E1', 'F_INTERNAL', 'F_PUBLIC') and type(self.original) is Transport:
            raw, meta = knowledge_transport(self.original).workflow(kind, inputs)
            self.knowledge_result = raw
            return raw, {**meta, 'engine': 'F2_PUBLIC' if kind == 'F_PUBLIC' else 'F2_INTERNAL'}
        return self.original.workflow(kind, inputs)

    def source(self, path, params=None):
        value = self.original.source(path, params)
        if path in ('/api/mes/heats', '/api/erp/production-orders', '/api/wms/inventory'):
            self.list_result = value
        return value

    def reference(self, question):
        # Separate fixed, tool-free app; frozen Transport kinds stay unchanged.
        if hasattr(self.original, 'reference'):
            value, meta = self.original.reference(question)
        else:
            local = {}
            path = ROOT / '.env.stage-f2.local'
            if path.exists():
                for line in path.read_text(encoding='utf-8-sig').splitlines():
                    if '=' in line and not line.lstrip().startswith('#'):
                        k, v = line.split('=', 1)
                        local[k.strip()] = v.strip()
            key = local.get('DIFY_GENERAL_REFERENCE_API_KEY')
            if not key:
                raise ServiceFailure('REFERENCE_NOT_CONFIGURED')
            base = self.values.get('DIFY_BASE_URL', 'http://localhost').rstrip('/')
            packet = http(base + '/v1/workflows/run', {'inputs': {'question': question},
                          'response_mode': 'blocking', 'user': 'copilot-model-reference'}, key, timeout=90)
            data = packet['data']
            if data['status'] != 'succeeded':
                raise ServiceFailure('REFERENCE_WORKFLOW_FAILED')
            value = strict_json(data['outputs']['reference_result'])
            meta = {'engine': 'GENERAL_REFERENCE', 'workflow_run_id': data['id'], 'workflow_id': data['workflow_id']}
        return validate_packet(value, question), meta

    def identities(self, identifiers):
        identifiers = list(dict.fromkeys(identifiers))
        if not identifiers:
            return []
        if len(identifiers) > 30:
            raise ServiceFailure('DISPLAY_ID_LIMIT')
        base = self.values.get('COPILOT_SOURCE_BASE', 'http://127.0.0.1:18090').rstrip('/')
        data = http(base + '/api/demo/display-identities', {'identifiers': identifiers}, timeout=15)
        rows = data.get('identities')
        if not isinstance(rows, list) or data.get('fictional') is not True:
            raise ServiceFailure('DISPLAY_ID_SOURCE_INVALID')
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != data.get('content_sha256'):
            raise ServiceFailure('DISPLAY_ID_SOURCE_INVALID')
        for row in rows:
            if (set(row) != {'internal_id', 'display_id', 'entity_kind', 'source_run', 'system'}
                    or not DISPLAY.fullmatch(row['display_id'])
                    or row['entity_kind'] not in ('heat', 'order', 'batch')
                    or row['system'] != {'heat': 'MES', 'order': 'ERP', 'batch': 'WMS'}[row['entity_kind']]
                    or not ({row['internal_id'], row['display_id']} & set(identifiers))):
                raise ServiceFailure('DISPLAY_ID_SOURCE_INVALID')
        if len({r['internal_id'] for r in rows}) != len(rows) or len({r['display_id'] for r in rows}) != len(rows):
            raise ServiceFailure('DISPLAY_ID_CONFLICT')
        return rows


def query(service, body: Query):
    transport = WorkspaceTransport(service.transport)
    adapted = body.model_copy(deep=True)
    try:
        adapted.question = DISPLAY.sub(lambda match: match[0].upper(), adapted.question)
        requested = DISPLAY.findall(adapted.question)
        identities = transport.identities(requested)
        # An unregistered short identifier cannot be converted by guessing.
        if any(item not in {r['display_id'] for r in identities} for item in requested):
            out = presenter.stop(str(uuid4()), Route(intent=Intent.CLARIFICATION), 'clarification', 'DISPLAY_ID_NOT_FOUND')
            out.title, out.summary = '未找到这个业务编号', '源系统未登记该展示编号。请核对编号后重试，尚未进行工艺分析。'
            out.status = 'data_error'
            out.next_actions = ['请从当前炉次、订单或库存列表复制一个有效编号。']
            return add_answers(presentation(out, [], None), body.question)
        adapted.question, conflict = normalize_source_entities(adapted.question, identities)
        if conflict and route(adapted.question).intent != Intent.UNSUPPORTED:
            out = presenter.stop(str(uuid4()), Route(intent=Intent.CLARIFICATION),
                                 'clarification', 'ENTITY_KIND_MISMATCH')
            out.summary = '编号在源系统中的对象类型与问句不一致，请确认要查询炉次、生产订单还是库存批次。'
            out.next_actions = ['请保留正确编号，并核对其对象类型；不会猜测跨系统关联。']
            return add_answers(presentation(out, [], None), body.question)
        # Resolve pronouns only using the existing signed, expiring entity context.
        if service.context.verify(body.context_token):
            adapted.question = re.sub(r'^(?:它|这炉)(?=的|现在|有|对|温度|状态)', '这个炉次', adapted.question)
        child = Gateway(transport=transport, context=service.context, router=workspace_route)
        child.slots = service.slots
        selected = workspace_route(adapted.question)
        if selected.intent == Intent.CLARIFICATION and reference_eligible(body.question):
            return reference_answer(service, transport, body.question)
        out = retain_verified_context(service, body, child.query(adapted))
        # A missing/conflicting process rule does not invalidate a separately
        # requested read-only business query. Keep the two results independent.
        # Never use this path after absence, transport or source validation failure.
        if (out.intent == Intent.ANOMALY_ANALYSIS and out.status == 'data_error'
                and out.technical_meta.get('error_code') in ('RULE_NOT_FOUND', 'RULE_CONFLICT')
                and re.search(r'订单|ERP|库存|WMS', adapted.question, re.I)):
            references = service.context.verify(body.context_token)
            selected = workspace_route(adapted.question, verified_context=(
                {'entity_kind': 'heat', 'entity_id': references['heat']} if 'heat' in references else None))
            if selected.entity_kind != 'heat' or not selected.entity_id:
                raise ServiceFailure('COMPOUND_OBJECT_UNVERIFIED')
            terms = 'ERP订单和WMS库存' if re.search(r'库存|WMS', adapted.question, re.I) else 'ERP订单'
            business = child.query(Query(question=f'查询炉次 {selected.entity_id} 的{terms}'))
            visible = json.dumps({'facts': [f.model_dump() for f in business.facts],
                                  'sources': [s.model_dump() for s in business.sources]}, ensure_ascii=False)
            ids = list(dict.fromkeys(INTERNAL.findall(visible)))
            mappings = transport.identities(ids)
            if set(ids) - {row['internal_id'] for row in mappings}:
                raise ServiceFailure('DISPLAY_ID_SOURCE_MISSING')
            analysis_result = presentation(out, [], None)
            business_result = presentation(business, mappings, None)
            analysis_result['context_token'] = business_result['context_token'] = None
            complete = business.status == 'verified_read_only'
            value = dict(analysis_result)
            value.update(status='partial' if complete else business.status,
                         title='业务查询已完成，工艺判断未完成' if complete else '业务查询和工艺判断均未完成',
                         summary=('所请求的只读业务查询已取得经过核验的业务事实；工艺判断因适用规则缺失或冲突而停止。'
                                  if complete else '业务查询没有取得可信完整结果；工艺判断也未完成，不能据此确认生产异常。'),
                         sub_results=[{'label': '订单与库存查询' if 'WMS' in terms else '生产订单查询', 'result': business_result},
                                      {'label': '工艺异常判断', 'result': analysis_result}],
                         process_steps=['已独立请求工艺分析', '工艺判断已停止',
                                        '已独立请求只读业务查询', '各子结果分别保留来源与状态'])
            # No pseudo-normal result, merged provenance or refreshed context.
            value['context_token'] = None
            value['technical_meta'] = {
                'route': out.intent.value, 'internal_status': value['status'],
                'error_code': 'PARTIAL_RESULT' if complete else 'COMPOUND_INCOMPLETE',
                'sub_result_statuses': {'business_query': business.status, 'process_analysis': out.status},
            }
            return add_answers(value, body.question, business_result, analysis_result)
        visible = json.dumps({'facts': [f.model_dump() for f in out.facts], 'sources': [s.model_dump() for s in out.sources],
                              'summary': out.summary}, ensure_ascii=False)
        identifiers = list(dict.fromkeys(INTERNAL.findall(visible)))
        if transport.list_result and out.status == 'verified_read_only':
            # A single-source list displays its own objects, not unchecked
            # relationship keys. Cross-system validation remains in C/D.
            key = {'MES':'heat_id', 'ERP':'production_order_id', 'WMS':'batch_id'}[transport.list_result['system']]
            for row in transport.list_result['rows']:
                identifiers.append(row[key])
        identities = transport.identities(list(dict.fromkeys(identifiers)))
        if set(identifiers) - {r['internal_id'] for r in identities}:
            raise ServiceFailure('DISPLAY_ID_SOURCE_MISSING')
        value = presentation(out, identities, transport.list_result)
        # Publisher/date fields are copied only from this validated response's citations.
        if transport.knowledge_result and out.status == 'answered':
            trusted = {c['citation_id']: c for c in transport.knowledge_result['citations']}
            for source, visible in zip(out.sources, value['sources']):
                hit = trusted[source.citation_id]
                if any(getattr(source, k) != hit[k] for k in ('document_id','segment_id','version','content_sha256')):
                    raise ServiceFailure('WORKSPACE_CITATION_MISMATCH')
                visible.update({k:hit[k] for k in ('publisher','publication_date','accessed_at')
                                if hit.get(k) and hit[k] != 'not-applicable'})
        if (out.status == 'abstain' and out.intent in (Intent.INTERNAL_KNOWLEDGE, Intent.GENERAL_INDUSTRY_KNOWLEDGE)
                and out.technical_meta.get('error_code') in ('NO_EVIDENCE', 'NO_REVIEWED_DIRECT_SUPPORT', 'INCOMPLETE_DIRECT_SUPPORT')
                and reference_eligible(body.question)):
            reference = reference_answer(service, transport, body.question)
            reference['technical_meta']['formal_evidence_status'] = 'insufficient'
            reference['formal_evidence_notice'] = '没有取得能直接支持此问题的正式资料；下面仅是模型一般讨论，不是企业规程答案。'
            return reference
        return add_answers(value, body.question)
    except (ServiceFailure, ValueError, KeyError, TypeError) as exc:
        out = presenter.stop(str(uuid4()), Route(intent=Intent.CLARIFICATION), 'system_error',
                             exc.code if isinstance(exc, ServiceFailure) else 'WORKSPACE_SOURCE_INVALID')
        return add_answers(presentation(out, [], None), body.question)


def reference_answer(service, transport, question):
    if not service.slots.acquire(blocking=False):
        raise ServiceFailure('GATEWAY_BUSY')
    try:
        value, meta = transport.reference(question)
        return reference_product(value, str(uuid4()), meta)
    finally:
        service.slots.release()


def presentation(out, identities, listing):
    value = out.model_dump(mode='json')
    value['technical_meta']['source_identities'] = identities
    value['technical_meta']['source_fields'] = value['facts']
    value['technical_meta']['citation_sources'] = value['sources']
    # Friendly titles are display aliases for an already returned citation.
    # No source is added and no citation identity is replaced from the registry.
    path = ROOT / 'assets/analysis_demo/dify_source_registry.json'
    registered = json.loads(path.read_text(encoding='utf-8'))['documents'] if path.exists() else []
    value['sources'] = [dict(s) for s in value['sources']]
    for source in value['sources']:
        if source['source_type'] != 'INTERNAL_CONTROLLED':
            continue
        matches = [d for d in registered if all(source.get(k) == d.get(k) for k in
                   ('document_id','segment_id','version','scope','content_sha256','chapter','section','page'))]
        if len(matches) == 1:
            source['label'] = matches[0]['document_name'] + ' · ' + source['version']
    value['groups'], value['table'] = [], None
    for system, title in GROUPS.items():
        facts = [dict(label=f['label'], value=readable(f['value'], identities)) for f in value['facts'] if f['system'] == system]
        if facts and not listing:
            # Duplicate IDs from heat + enterprise-links are one displayed fact.
            unique = list({(f['label'], f['value']): f for f in facts}.values())
            value['groups'].append({'title': title, 'system': system, 'facts': unique})
    if out.intent == Intent.ANOMALY_ANALYSIS and not listing:
        rule_labels = {'本次比较依据','温度','碳含量','硅含量','锰含量'}
        comparisons = []
        for group in value['groups']:
            if group['system'] == 'MES':
                comparisons = [f for f in group['facts'] if f['label'] in rule_labels]
                group['facts'] = [f for f in group['facts'] if f['label'] not in rule_labels]
        if comparisons:
            value['groups'].append({'title':'实测参数与有效规则','system':'MES 规则接口','facts':comparisons})
    if listing and out.status == 'verified_read_only':
        system = listing['system']
        columns = {'MES': [('heat_id','炉次'),('furnace_id','炉号'),('steel_grade','钢种'),('status','状态'),('planned_start_time','计划开始')],
                   'ERP': [('production_order_id','订单'),('status','状态'),('planned_quantity','计划量'),('completed_quantity','完成量'),('quantity_unit','单位')],
                   'WMS': [('batch_id','批次'),('material_name','物料'),('status','状态'),('available_quantity','可用库存'),('unit','单位')]}[system]
        value['table'] = {'system': system, 'columns': [c[1] for c in columns],
                          'rows': [[readable(row.get(key, '未提供'), identities) for key, _ in columns] for row in listing['rows']]}
        value['summary'] = f"已查到 {listing['returned_count']} 条记录。" if listing['returned_count'] else '当前条件下没有匹配记录。'
        value['title'] = {'MES':'炉次查询结果','ERP':'生产订单查询结果','WMS':'库存批次查询结果'}[system]
        value['technical_meta']['total_matching'] = listing['total_matching']
        value['analysis'] = ['记录来自本次' + system + '查询。列表状态为源系统记录，工艺异常需结合有效规则另行分析。']
        value['next_actions'] = ['复制一个编号，可继续查询详细记录。']
    elif out.status == 'verified_read_only':
        value['title'] = '查询结果'
        status = next((f['value'] for f in value['facts'] if f['label'] == '当前状态'), None)
        value['summary'] = f'当前状态为{status}。以下信息来自本次业务系统查询。' if status else '以下为本次查询到的业务记录。'
    elif out.status == 'answered':
        value['title'] = '公开行业参考' if out.intent == Intent.GENERAL_INDUSTRY_KNOWLEDGE else '企业规程说明'
        value['summary'] = ('公开资料可提供一般背景，不代表本企业的生产标准。' if out.intent == Intent.GENERAL_INDUSTRY_KNOWLEDGE
                            else '根据当前有效的企业演示规程，可核对以下事项：')
    elif out.status == 'data_error':
        # Explain verified stop codes; never turn missing rules/data into a
        # process diagnosis or display an unvalidated model explanation.
        reasons = {
            'RULE_NOT_FOUND': (
                '缺少适用的有效工艺规则',
                'MES未提供与该炉次钢种、工艺阶段和适用范围匹配的当前有效规则，无法判断是否存在工艺异常。',
                '可继续查询该炉次的业务记录；工艺分析须先由授权人员确认并提供适用规则。'),
            'RULE_CONFLICT': (
                '适用工艺规则存在冲突',
                '该炉次匹配多个有效规则，系统已停止工艺判断，不能自行选择其中一个。',
                '请由授权人员确认唯一适用规则后再分析。'),
            'STALE_DATA': (
                '生产数据时效不满足分析要求',
                '源数据或测量时间不满足当前有效规则的时效要求，不能用于判断当前工艺状态。',
                '请在MES核对当前阶段及最新测量记录；不会自动刷新历史记录时间。'),
            'MISSING_FIELDS': (
                '源记录缺少必要字段',
                '业务系统返回的必要字段不完整，系统已停止确定性结论；这不是工艺异常判定。',
                '请在源业务系统补齐或核对必要字段后重试。'),
        }
        reason = reasons.get(value['technical_meta'].get('error_code'))
        if reason:
            value['title'], value['summary'], action = reason
            value['next_actions'] = [action]
    for key in ('summary', 'analysis', 'next_actions'):
        value[key] = [readable(v, identities) for v in value[key]] if isinstance(value[key], list) else readable(value[key], identities)
    # UI source rows contain business labels; full source identity remains in technical details.
    value['sources'] = [{k: readable(v, identities) if isinstance(v, str) and k not in ('url', 'effective_date') else v
                         for k, v in s.items() if k in ('source_type', 'label', 'version', 'chapter', 'section', 'page', 'effective_date', 'url', 'entity_id') and v is not None}
                        for s in value['sources']]
    value['facts'] = []
    return value


def health(service):
    """Real read-only checks. A reachable gateway alone cannot make the UI green."""
    checks = {name: 'unavailable' for name in ('MES', 'ERP', 'WMS', '企业知识库', '公开参考库')}
    try:
        source = service.transport.source('/health')
        for name in ('MES', 'ERP', 'WMS'):
            if source.get('status') == 'ok' and source.get('backends', {}).get(name.lower()) == 'ok':
                checks[name] = 'ok'
    except ServiceFailure:
        pass
    def probe(kind, question, intent):
        try:
            raw, meta = WorkspaceTransport(service.transport).workflow(kind, {'question': question})
            verified = presenter.result(str(uuid4()), Route(intent=intent), raw, meta)
            return 'ok' if verified.status == 'answered' and verified.sources else 'unavailable'
        except (ServiceFailure, ValueError, KeyError, TypeError):
            return 'unavailable'
    with ThreadPoolExecutor(max_workers=2) as pool:
        internal = pool.submit(probe, 'F_INTERNAL', '温度偏差时应该检查什么？', Intent.INTERNAL_KNOWLEDGE)
        public = pool.submit(probe, 'F_PUBLIC', '一般来说转炉炼钢一炉需要多久？', Intent.GENERAL_INDUSTRY_KNOWLEDGE)
        checks['企业知识库'], checks['公开参考库'] = internal.result(), public.result()
    return {'status': 'ok' if set(checks.values()) == {'ok'} else 'unavailable', 'services': checks,
            'checked_at': datetime.now(timezone.utc).isoformat()}


def overview(service):
    data = service.overview()
    counts = {}
    for label in ('internal','public'):
        path = ROOT / 'assets/knowledge_f2' / label / 'dify_source_registry.json'
        # Count only successfully indexed/identity-bound registry records.
        docs = json.loads(path.read_text(encoding='utf-8'))['documents'] if path.exists() else []
        counts[label] = (len(docs), sum(d['status']=='active' for d in docs))
    return {**data, 'internal_document_count':counts['internal'][0],
            'internal_current_document_count':counts['internal'][1], 'public_reference_count':counts['public'][0]}
