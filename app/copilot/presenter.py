"""Deterministic product wording; raw model answers and internal reasoning stay hidden."""
import hashlib
import json
import re
from datetime import datetime, timezone
from app.copilot.contracts import ProductResponse, Fact, Source, Intent
from app.demo_dataset.api import ListResponse
from app.enterprise.nodes import enterprise_digest
from app.analysis.generation_nodes import strict_json
from app.analysis.workflow_nodes import timestamp

HUMAN = '生产判断及现场操作须由授权人员人工确认。本系统仅提供只读查询和辅助分析，不控制设备。'
ENGINE_FIELDS = ('workflow_run_id', 'workflow_id', 'engine')


def engine_details(meta):
    return {k: meta[k] for k in ENGINE_FIELDS if k in meta and isinstance(meta[k], str)}
STATUS = {'planned': '计划中', 'released': '已下达', 'producing': '生产中', 'in_progress': '生产中',
          'completed': '已完成', 'partially_completed': '部分完成', 'delayed': '延期', 'cancelled': '已取消',
          'available': '可用', 'low_stock': '低库存', 'zero_stock': '零库存', 'reserved': '已预留',
          'quality_hold': '质量待检', 'expired': '已过期', 'review': '复核阶段'}
LABELS = {'heat_id': '炉次', 'steel_grade': '钢种', 'status': '当前状态', 'production_order_id': '生产订单',
          'batch_id': '库存批次', 'material_name': '物料', 'material_code': '物料编码', 'warehouse': '仓库', 'location': '仓位',
          'updated_at': '记录更新时间', 'source_updated_at': '来源更新时间', 'revision': '来源修订', 'due_date': '订单交期'}


def stop(request_id, route, status='clarification', code='', engine=None):
    if status == 'unsupported':
        title = '本系统仅提供只读辅助'
        summary = '不能执行设备控制、业务写入，也不能跳过来源核验或凭经验编造数据。实际操作须由授权人员确认执行。'
        actions = ['请改为查询明确对象、适用企业规程或有依据的辅助分析。']
    elif status == 'system_error':
        title = '系统暂时无法完成查询'
        summary = '当前服务调用或结果验证失败，事实状态仍未知；这不表示对象不存在，也不表示发生生产异常。'
        actions = ['请稍后重试，或前往MES、ERP、WMS核对对应事实。']
    else:
        title = '还需要补充查询条件'
        summary = '请提供明确炉次号、生产订单号或库存批次号；知识问题请说明适用资料或问题范围。'
        if code == 'MAX_RECORDS_EXCEEDED':
            summary = '每次最多查询20条记录，请缩小时间范围或返回数量。'
        actions = ['例如：查询炉次 100235 当前状态，或查询今天有哪些炉次。']
    return ProductResponse(request_id=request_id, intent=route.intent, status=status, title=title, summary=summary,
        next_actions=actions, human_confirmation=HUMAN, process_steps=['已识别问题范围', '已停止后续推断'],
        technical_meta={'route': route.intent.value, 'internal_status': status, 'error_code': code, **engine_details(engine or {})})


def fact_rows(values, system):
    rows = [Fact(label=LABELS[k], value=STATUS.get(str(v), str(v)), system=system) for k, v in values.items() if k in LABELS and v is not None]
    for field, unit, label in [('planned_quantity', 'quantity_unit', '订单计划量'), ('completed_quantity', 'quantity_unit', '订单完成量'),
                               ('required_quantity', 'material_unit', '物料需求'), ('available_quantity', 'unit', '可用库存')]:
        if field in values and values[field] is not None:
            rows.append(Fact(label=label, value=str(values[field]) + ' ' + values.get(unit, ''), system=system))
    return rows


def api_sources(rows):
    out = []
    for p in rows:
        if p['system'] not in ('MES', 'ERP', 'WMS') or not re.fullmatch('[0-9a-f]{64}', p['content_sha256']):
            raise ValueError('invalid API provenance')
        label = p['system'] + ' ' + p['entity_id']
        if not any(s.label == label for s in out):
            out.append(Source(source_type=p['system'], label=label, entity_id=p['entity_id'], content_sha256=p['content_sha256']))
    return out


def document_sources(citations, source_type='INTERNAL_CONTROLLED'):
    out = []
    for c in citations:
        if not all(c.get(k) for k in ('document_id', 'segment_id', 'version', 'content_sha256', 'citation_id', 'scope')) or not re.fullmatch('[0-9a-f]{64}', c['content_sha256']):
            raise ValueError('missing verified citation identity')
        layer = c.get('source_type', source_type)
        if layer != source_type:
            raise ValueError('wrong trust layer')
        out.append(Source(source_type=layer, label=c.get('display_name', c['document_name']) + ' · ' + c['version'],
            **{k: c[k] for k in ('document_name', 'version', 'chapter', 'section', 'page', 'effective_date', 'scope', 'citation_id', 'document_id', 'segment_id', 'content_sha256')},
            url=c.get('url') if c.get('url', '').startswith('https://') else None))
    return out


def result(request_id, route, raw, meta):
    if raw.get('automatic_actions'):
        raise ValueError('unexpected automatic actions')
    status = raw['status']
    technical = {'route': route.intent.value, 'internal_status': status, 'error_code': raw.get('code'), **engine_details(meta)}
    if status in ('system_error', 'request_error'):
        return stop(request_id, route, 'system_error' if status == 'system_error' else 'clarification', raw.get('code', ''), meta)
    if status == 'data_error':
        absent = raw.get('code') == 'OBJECT_NOT_FOUND'
        return ProductResponse(request_id=request_id, intent=route.intent, status='data_error',
            title='未找到对应生产对象' if absent else '当前数据无法用于确认结论',
            summary=('源系统未返回对象 ' + str(route.entity_id) + ' 的有效记录，系统已停止后续推断。' if absent else
                     '数据存在缺项、过期、版本或关联问题，系统已停止确定性业务结论；这不是工艺异常判定。'),
            next_actions=['请核对对象编号、原始记录、来源版本和跨系统关联。'], human_confirmation=HUMAN,
            process_steps=['已识别查询对象', '已停止后续推断'], technical_meta=technical)
    base = ProductResponse(request_id=request_id, intent=route.intent, status=status, title='', summary='', human_confirmation=HUMAN, technical_meta=technical)
    if route.intent == Intent.LIVE_ENTERPRISE_QUERY:
        if status != 'verified_read_only' or raw.get('citations') != [] or not raw.get('data_sources'):
            raise ValueError('not verified business output')
        operations = {'mes_heat': 'MES', 'mes_links': 'MES', 'erp_order': 'ERP', 'wms_batch': 'WMS'}
        facts = raw['facts']
        root_operation, root_field = {'heat': ('mes_heat', 'heat_id'), 'order': ('erp_order', 'production_order_id'),
                                      'batch': ('wms_batch', 'batch_id')}[route.entity_kind]
        if facts.get(root_operation, {}).get(root_field) != route.entity_id:
            raise ValueError('query object mismatch')
        for operation, f in facts.items():
            if operation not in operations:
                raise ValueError('unknown fact operation')
            entity_field = 'heat_id' if operation.startswith('mes_') else 'production_order_id' if operation == 'erp_order' else 'batch_id'
            matching = [p for p in raw['data_sources'] if p['system'] == operations[operation]
                        and p['entity_id'] == f.get(entity_field) and p['content_sha256'] == enterprise_digest(f)]
            if not matching:
                raise ValueError('fact provenance mismatch')
            base.facts += fact_rows(f, operations[operation])
        base.title = '已取得生产系统事实'
        base.summary = '查询结果来自已验证的企业系统记录。'
        base.sources = api_sources(raw['data_sources'])
        base.process_steps = ['已确认查询对象'] + ['已查询并核对' + s for s in dict.fromkeys(operations[o] for o in facts)] + ['已验证返回数据']
        systems = list(dict.fromkeys(operations[o] for o in facts))
        base.analysis = [('已查询系统间的身份、关联、单位和来源修订通过原只读规则核验。' if len(systems) > 1 else
                          '本次仅核对' + systems[0] + '返回的事实，没有查询其他系统。') + '查询事实不构成工艺判断或操作授权。']
    elif route.intent == Intent.ANOMALY_ANALYSIS:
        if raw.get('heat_id') != route.entity_id or status not in ('no_anomaly', 'abstain', 'review_required'):
            raise ValueError('analysis binding failed')
        used = raw.get('data_used', {})
        base.facts = fact_rows(used.get('heat', {}), 'MES')
        rule = used.get('rule', {})
        if used.get('process_stage'):
            base.facts.append(Fact(label='工艺阶段', value=STATUS.get(used['process_stage'], used['process_stage']), system='MES'))
        if rule.get('rule_id'):
            source = rule['source']
            base.facts.append(Fact(label='本次比较依据', value=source['document_name'] + ' · ' + source['version'], system='MES'))
            for field, group, label in [('temperature_c', 'temperature', '温度'), ('carbon_pct', 'chemistry', '碳含量'),
                                        ('silicon_pct', 'chemistry', '硅含量'), ('manganese_pct', 'chemistry', '锰含量')]:
                actual = used.get(group, {}).get(field)
                limit = rule.get('limits', {}).get(field)
                if actual is not None and limit:
                    base.facts.append(Fact(label=label, value=f"实测 {actual} {limit['unit']}；规则 {limit['minimum']}～{limit['maximum']} {limit['unit']}", system='MES'))
        base.sources = api_sources(raw.get('data_sources', []))
        base.process_steps = ['已查询MES炉次信息']
        trace = raw.get('trace', [])
        if 'compare_effective_limits' in trace:
            base.process_steps.append('已核对有效工艺规则')
        for name in ('erp', 'wms'):
            part = raw.get('enterprise_evidence', {}).get(name, {})
            if part.get('verified') is True:
                base.facts += fact_rows(part['facts'], name.upper())
                base.process_steps.append('已核对' + name.upper() + '记录')
        if status == 'no_anomaly':
            if raw.get('process_anomaly_confirmed') is not False:
                raise ValueError('normal flag mismatch')
            base.title, base.summary = '当前规则下未发现参数异常', '本次有效生产数据与对应规则比较通过；这不代表所有质量事项均已确认。'
        else:
            if raw.get('process_anomaly_confirmed') is not True:
                raise ValueError('no confirmed anomaly')
            parameters = {'temperature_c': '温度', 'carbon_pct': '碳含量', 'silicon_pct': '硅含量', 'manganese_pct': '锰含量'}
            for f in raw['anomaly_facts']:
                base.analysis.append(f"{parameters[f['parameter']]}实测 {f['actual']} {f['unit']}，当前有效规则范围 {f['minimum']}～{f['maximum']} {f['unit']}，{'高于上限' if f['direction']=='high' else '低于下限'}。")
            if status == 'abstain':
                base.title, base.summary = '已确认参数偏差，规程依据不足', '异常事实来自MES有效规则比较；企业证据未完整覆盖问题，系统不生成确定性处置建议。'
                if raw.get('sources') or raw.get('suggested_checks'):
                    raise ValueError('abstain contains recommendations')
                base.next_actions = ['请由工艺或质量人员补充当前适用规程并人工确认。']
            else:
                if not raw.get('generation') or not raw.get('sources'):
                    raise ValueError('unverified generation')
                base.title, base.summary = '发现参数偏差，请人工复核', '实际参数违反本次有效规则。以下检查项来自已验证的企业演示规程，不能自动执行生产处置。'
                base.sources += document_sources(raw['generation']['citations'])
                base.next_actions = [r['text'] for r in raw['generation']['check_recommendations']]
                base.process_steps += ['已检索并验证企业规程', '已核验辅助分析依据']
        if not any(s.source_type == 'MES' and s.entity_id == route.entity_id for s in base.sources):
            raise ValueError('missing analysis source receipt')
    else:
        public = route.intent == Intent.GENERAL_INDUSTRY_KNOWLEDGE
        if status == 'abstain':
            if raw.get('citations') or raw.get('answer'):
                raise ValueError('abstain contains answer')
            base.title = '公开参考不足，暂时无法确认' if public else '当前企业资料不足，无法确认答案'
            base.summary = '未找到经过核验且能够直接支持完整问题的资料，系统没有使用模型经验补造结论。'
            base.next_actions = ['请补充可验证的公开资料。' if public else '请补充适用企业规程、SOP或受控标准，并请相关人员确认。']
            base.process_steps = ['已识别知识范围', '已完成证据门禁，停止确定性回答']
        elif status == 'answered':
            if not raw.get('supported_points') or not raw.get('citations'):
                raise ValueError('unsupported answer')
            base.title = '公开行业参考' if public else '企业规程核对结果'
            base.summary = '以下为公开行业资料参考，不代表本演示企业的正式标准。' if public else '以下要点来自本次检索并验证的企业演示资料。'
            base.sources = document_sources(raw['citations'], 'PUBLIC_REFERENCE' if public else 'INTERNAL_CONTROLLED')
            allowed = {s.citation_id for s in base.sources}
            if any(not p['citation_ids'] or set(p['citation_ids']) - allowed for p in raw['supported_points']):
                raise ValueError('unbound answer citation')
            base.analysis = [p['text'] for p in raw['supported_points']] + [raw['applicability']]
            base.next_actions = ['需要现场应用时，请核对适用范围并由对应岗位人工确认。']
            base.process_steps = ['已识别知识范围', '已检索适用资料', '已验证来源与有效版本', '已核验回答依据']
        else:
            raise ValueError('unknown knowledge status')
    assessment = raw.get('inventory_assessment')
    if assessment:
        base.analysis.append(f"该任务指定批次需求 {assessment['required_quantity']} {assessment['unit']}，可用 {assessment['available_quantity']} {assessment['unit']}，账面数量{'足够' if assessment['status']=='sufficient' else '不足'}。这不是领用或放行授权。")
    if not base.next_actions:
        base.next_actions = ['需要生产处置时，请联系对应岗位核对并人工确认。']
    technical['api_provenance'] = [{k: p.get(k) for k in ('system', 'operation_id', 'entity_id', 'request_id', 'revision', 'source_updated_at', 'content_sha256')} for p in raw.get('data_sources', [])]
    technical['citation_ids'] = [s.citation_id for s in base.sources if s.citation_id]
    base.technical_meta.update(technical)
    return base


def collection(request_id, route, raw):
    data = ListResponse.model_validate(raw)
    expected_system = {'mes': 'MES', 'erp': 'ERP', 'wms': 'WMS'}[route.collection]
    canonical = json.dumps(data.rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if data.system != expected_system or data.returned_count != len(data.rows) or data.limit != route.filters.get('limit', 10) or data.content_sha256 != hashlib.sha256(canonical.encode()).hexdigest():
        raise ValueError('invalid bounded source result')
    age = (datetime.now(timezone.utc) - timestamp(data.source_snapshot_at)).total_seconds()
    if not 0 <= age <= 21600:
        raise ValueError('stale or future source snapshot')
    facts = []
    for row in data.rows:
        if row.get('fictional') is not True:
            raise ValueError('source trust scope mismatch')
        if route.collection == 'mes':
            value = f"{row['steel_grade']} · {STATUS.get(row['status'],row['status'])} · {row['planned_start_time']}"
            if row['historical_review_flag']:
                value += ' · 历史待复核标记'
            facts.append(Fact(label=row['heat_id'], value=value, system='MES'))
        elif route.collection == 'erp':
            facts.append(Fact(label=row['production_order_id'], value=f"{STATUS.get(row['status'],row['status'])} · 完成 {row['completed_quantity']}/{row['planned_quantity']} {row['quantity_unit']}", system='ERP'))
        else:
            facts.append(Fact(label=row['batch_id'], value=f"{row['material_name']} · 可用 {row['available_quantity']} {row['unit']} · {STATUS.get(row['status'],row['status'])}", system='WMS'))
    return ProductResponse(request_id=request_id, intent=route.intent, status='verified_read_only', title='已取得有限查询结果',
        summary=f'共匹配 {data.total_matching} 条记录，本次显示 {data.returned_count} 条。' + ('请缩小条件查看其余记录。' if data.truncated else ''),
        facts=facts, analysis=['列表来自Mock业务系统。历史待复核标记是源记录，不等于当前炉次工艺异常判定。'],
        sources=[Source(source_type=data.system, label=data.system + ' 有限记录列表', content_sha256=data.content_sha256)],
        next_actions=['可复制列表中的编号继续查询具体对象；每次最多20条。'], human_confirmation=HUMAN,
        process_steps=['已解析查询条件', '已查询' + data.system + '记录', '已验证列表数量和来源'],
        technical_meta={'route': route.intent.value, 'engine': 'bounded_source_query', 'source_request_id': data.request_id,
                        'operation_id': data.operation_id, 'source_snapshot_at': data.source_snapshot_at, 'content_sha256': data.content_sha256})
