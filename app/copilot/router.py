"""Deterministic safety + closed intent classification; uncertainty asks the user."""
import re
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.analysis.generation_nodes import strict_json, validate_schema
from app.copilot.contracts import Intent, Route

ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}'
PATTERNS = {
    'heat': [rf'(?:heat_id|炉次号?|炉号)\s*[=:：]?\s*({ID})', rf'({ID})\s*号炉'],
    'order': [rf'(?:production_order_id|ERP订单|订单号?|生产订单)\s*[=:：]?\s*({ID})'],
    'batch': [rf'(?:batch_id|WMS批次|批次号?)\s*[=:：]?\s*({ID})'],
}
CLASSIFIER_SCHEMA = {'type': 'object', 'additionalProperties': False,
                     'properties': {'intent': {'type': 'string', 'enum': [i.value for i in Intent]},
                                    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}},
                     'required': ['intent', 'confidence']}


def classify_output(text, explicit_entity=False):
    """Optional classifier boundary. Never accepts entities, answers, prompts or sources."""
    try:
        value = strict_json(text)
        validate_schema(value, CLASSIFIER_SCHEMA)
        if value['confidence'] < .85:
            return Intent.CLARIFICATION
        result = Intent(value['intent'])
        if result in (Intent.LIVE_ENTERPRISE_QUERY, Intent.ANOMALY_ANALYSIS) and not explicit_entity:
            return Intent.CLARIFICATION
        return result
    except (ValueError, TypeError, KeyError):
        return Intent.CLARIFICATION


def temporal_filters(question, now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=8)))
    filters = {'limit': 10}
    count = re.search(r'最近\s*(\d+)\s*炉|(?:前|最多|返回|查询)\s*(\d+)\s*(?:条|个)', question)
    if count:
        number = int(next(group for group in count.groups() if group))
        if not 1 <= number <= 20:
            raise ValueError('MAX_RECORDS_EXCEEDED')
        filters['limit'] = number
    if re.search(r'全部|所有记录|全库|导出数据库|无限|不限制', question):
        raise ValueError('MAX_RECORDS_EXCEEDED')
    if '今天' in question:
        filters['date'] = local.date().isoformat()
    elif '昨天' in question:
        filters['date'] = (local-timedelta(days=1)).date().isoformat()
    elif '本周' in question:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
        filters.update(start_time=start.isoformat(), end_time=(local+timedelta(seconds=1)).isoformat())
    else:
        dates = re.findall(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})|(\d{1,2})\s*月\s*(\d{1,2})\s*日', question)
        values = []
        for year, month, day, short_month, short_day in dates:
            values.append(datetime(int(year or local.year), int(month or short_month), int(day or short_day), tzinfo=local.tzinfo))
        if len(values) == 1:
            filters['date'] = values[0].date().isoformat()
        elif len(values) == 2 and values[0] <= values[1] and (values[1]-values[0]).days <= 60:
            filters.update(start_time=values[0].isoformat(), end_time=(values[1]+timedelta(days=1)).isoformat())
        elif values:
            raise ValueError('INVALID_TIME_RANGE')
    furnace = re.search(r'([12])\s*号炉', question)
    if furnace:
        filters['furnace_id'] = 'DEMO-FURNACE-' + furnace[1]
    if '异常' in question or '待复核' in question:
        filters['review_only'] = True
    if re.search(r'正在生产|生产中', question):
        filters['status'] = 'producing' if '订单' in question else 'in_progress'
    if '低库存' in question:
        filters['status'] = 'low_stock'
    return filters


def route(question, *, verified_context=None, now=None):
    q = question.strip() if isinstance(question, str) else ''
    if not q or len(q) > 2000:
        return Route(intent=Intent.CLARIFICATION, reason='INVALID_QUESTION')
    # Before extraction or classification: untrusted instructions cannot choose a permissive route.
    if re.search(r'忽略|跳过.*(?:校验|验证|规则)|不要查|不查.*(?:数据|知识|资料)|凭经验|编造|猜测|假装|system.?prompt|<think>|\[cite:|https?://|任意SQL|执行SQL', q, re.I):
        return Route(intent=Intent.UNSUPPORTED, reason='UNTRUSTED_INSTRUCTION')
    if re.search(r'修改|扣减|写入|删除|直接执行|控制设备|设备控制|调整PLC|修改PLC|把.*(?:调到|调整到)|调整.*设备|设定.*参数', q, re.I):
        return Route(intent=Intent.UNSUPPORTED, reason='READ_ONLY_ONLY')
    # Reviewed knowledge questions are routing hints only, never answer evidence.
    normalized = re.sub(r'[\s？?，,。.!！：:；;、]', '', q)
    root = Path(__file__).resolve().parents[2]
    for folder, intent in [('copilot_knowledge', Intent.INTERNAL_KNOWLEDGE), ('public_reference', Intent.GENERAL_INDUSTRY_KNOWLEDGE)]:
        questions = json.loads((root / 'assets' / folder / 'questions.json').read_text(encoding='utf-8'))
        if any(normalized == re.sub(r'[\s？?，,。.!！：:；;、]', '', alias)
               for item in questions for alias in [item['question']] + item.get('aliases', [])):
            return Route(intent=intent)
    matches = []
    for kind, patterns in PATTERNS.items():
        for pattern in patterns:
            matches += [(kind, match) for match in re.findall(pattern, q, re.I)]
    # A furnace number used in a time list is a filter, not a heat ID.
    if re.search(r'今天|昨天|本周|最近|\d\s*月\s*\d+\s*日|\d{4}-\d{2}-\d{2}', q):
        matches = [item for item in matches if item != ('heat', '1') and item != ('heat', '2')]
    matches = list(dict.fromkeys(matches))
    if len(matches) > 1:
        return Route(intent=Intent.CLARIFICATION, reason='AMBIGUOUS_OBJECT')
    if not matches and re.search(r'这个炉次|该炉次|这个订单|该订单|对应物料|对应库存', q) and verified_context:
        kind = 'order' if re.search(r'这个订单|该订单', q) else verified_context['entity_kind']
        if kind == verified_context['entity_kind']:
            matches = [(kind, verified_context['entity_id'])]
    if matches:
        kind, entity = matches[0]
        analysis = bool(re.search(r'分析|异常|为什么|是否正常|是否符合|风险|偏差原因|应该核查', q))
        if analysis:
            return Route(intent=Intent.ANOMALY_ANALYSIS if kind == 'heat' else Intent.CLARIFICATION,
                         entity_kind=kind, entity_id=entity, reason='' if kind == 'heat' else 'ANALYSIS_REQUIRES_HEAT')
        terms = 'ERP订单和WMS库存' if re.search(r'库存|WMS', q, re.I) and kind != 'batch' else 'ERP订单' if re.search(r'订单|ERP', q, re.I) and kind == 'heat' else 'MES状态' if kind == 'heat' else ''
        label = {'heat': '炉次', 'order': 'ERP订单', 'batch': 'WMS批次'}[kind]
        canonical = f'查询{label} {entity} ' + ('的' + terms if terms else '的库存' if kind == 'batch' else '的详情')
        if kind == 'order' and re.search(r'库存|WMS', q, re.I):
            canonical = f'查询ERP订单 {entity} 的WMS库存'
        return Route(intent=Intent.LIVE_ENTERPRISE_QUERY, entity_kind=kind, entity_id=entity, canonical_query=canonical)
    if re.search(r'今天|昨天|本周|最近\s*\d+\s*炉|\d\s*月\s*\d+\s*日|\d{4}-\d{2}-\d{2}|低库存|时间范围', q) and re.search(r'炉次|号炉|炉|订单|库存|物料', q):
        try:
            collection = 'wms' if re.search(r'库存|物料', q) else 'erp' if '订单' in q else 'mes'
            filters = temporal_filters(q, now)
            if collection == 'wms':
                filters = {k: v for k, v in filters.items() if k in ('limit', 'status')}
            return Route(intent=Intent.LIVE_ENTERPRISE_QUERY, collection=collection, filters=filters)
        except ValueError as exc:
            return Route(intent=Intent.CLARIFICATION, reason=str(exc))
    if re.search(r'公司|本厂|我们|企业|规程|SOP|制度|现行|岗位|交接班|上报|标准生产|记录缺失|温度偏差|成分偏差', q, re.I):
        return Route(intent=Intent.INTERNAL_KNOWLEDGE)
    if re.search(r'一般|行业|公开资料|通常|转炉炼钢|MES.*作用|电炉|连铸', q, re.I):
        return Route(intent=Intent.GENERAL_INDUSTRY_KNOWLEDGE)
    if re.search(r'生产状态|生产情况|现在怎么样|目前怎么样|库存|订单|炉次|分析', q):
        return Route(intent=Intent.CLARIFICATION, reason='MISSING_OBJECT')
    return Route(intent=Intent.CLARIFICATION, reason='UNCERTAIN_INTENT')
