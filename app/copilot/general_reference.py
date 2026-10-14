"""Unverified model discussion, isolated from business facts and formal evidence.

This is a labelled reference layer, not an entailment verifier. No value here
can become an API fact, a document citation, a rule or an entity context.
Standard library only; the policy and parser also run in the Dify Code node.
"""
import json
import re

from app.analysis.generation_nodes import object_schema, parse_model_text, validate_schema

NOTICE = '模型一般知识 · 未经企业资料或业务系统验证 · 仅供参考'
BOUNDARY = '以下是一般性的讨论，不代表本企业制度、实时事实或生产处置依据；不能用于工艺参数设定、质量放行或设备操作。'
MODEL_SCHEMA = object_schema({
    'decision': {'type': 'string', 'pattern': '^(reference|decline)$'},
    'points': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 800},
               'minItems': 0, 'maxItems': 6},
})

# These checks are a conservative boundary, not a list of supported questions.
# The existing source/evidence router always gets first refusal on real facts.
ENTITY = r'\b(?:H|PO|LOT)\d{8}-\d+\b|F(?:HEAT|ORDER|LOT)-|炉次\s*[=:：]?\s*[A-Za-z0-9]|\d+\s*号炉|(?:这个|该|这|上一|上述)(?:炉次|订单|批次)'
UNSAFE = (r'忽略|跳过.*校验|绕过|伪造|编造|假装|猜测.*(?:数据|库存|状态)|'
          r'不(?:查询|查|用查).*?(?:系统|数据|资料)|修改|写入|扣减|删除|'
          r'调整.*PLC|控制.*设备|PLC|联锁|配方|加料|补吹|停炉|复吹|放行|'
          r'<think>|\[cite:|https?://|SQL|温度.*(?:偏高|偏低|调整|处理)|'
          r'成分.*(?:偏差|调整|处理)|(?:异常|故障).*(?:处理|处置|操作)|'
          r'设备.*(?:操作|启动|停止|修理|维修)|(?:操作|启动|停止).*(?:设备|转炉|连铸)')
SPECIFIC = (r'(?:我们|本厂|我司|本公司|本企业|公司|企业).{0,16}'
            r'(?:标准|规定|制度|现行|实际|当前|目前|库存|生产时间|正常范围|必须|要求)|'
            r'(?:实时|现在|当前|目前|今天|最近).*(?:状态|数量|订单|库存|炉次)|'
            r'(?:查询|查看).*(?:炉次|订单|批次|库存)|炉次|炉号|批次号|订单号')
QUANTITATIVE = (r'\d|多少|多久|几分钟|多长时间|百分比|阈值|范围|上下限|'
                r'温度|含量|成分|库存量|生产时间|吨|千克|公斤|毫克|摄氏|℃|°C|%|'
                r'(?:分钟|小时|秒|天).*(?:以内|以上|以下)|(?:正常|合格).*(?:标准|判定)|'
                r'(?:安全|工艺|质量).*(?:参数|数值|标准|判定)|是否.*异常')
DOMAIN = (r'生产|制造|冶金|炼钢|转炉|连铸|企业|工厂|岗位|班组|交接|沟通|'
          r'协作|管理|记录|追溯|订单|库存|物料|数据|系统|知识|规程|SOP|MES|ERP|WMS|AI|质量|学习')


def eligible(question):
    return (isinstance(question, str) and 4 <= len(question.strip()) <= 2000
            and re.search(DOMAIN, question, re.I) is not None
            and not any(re.search(p, question, re.I) for p in (ENTITY, UNSAFE, SPECIFIC, QUANTITATIVE)))


def validate_reference(question, text, native=None, finish_reason='stop'):
    """Strict syntax/schema and scope checks; never mint a trustworthy source."""
    if not eligible(question):
        raise ValueError('REFERENCE_SCOPE_DENIED')
    if finish_reason not in ('stop', 'end_turn'):
        raise ValueError('REFERENCE_OUTPUT_TRUNCATED')
    model, _ = parse_model_text(text)
    validate_schema(model, MODEL_SCHEMA)
    if native is not None and native != model:
        raise ValueError('REFERENCE_NATIVE_MISMATCH')
    if model['decision'] == 'decline':
        if model['points']:
            raise ValueError('REFERENCE_DECLINE_WITH_ANSWER')
    else:
        if not 2 <= len(model['points']) <= 6:
            raise ValueError('REFERENCE_POINTS_MISSING')
        for point in model['points']:
            # Broad model opinions remain unverified. Explicit numeric standards,
            # false citations, corporate assertions and actions are blocked.
            if any(re.search(p, point, re.I) for p in (
                ENTITY, r'\d|\[cite:|citation[_ -]?id|document[_ -]?id|https?://|<[^>]+>|```',
                r'(?:本企业|本厂|我司|我们公司).*(?:规定|要求|标准|状态)|'
                r'(?:依据|根据).*(?:SOP|规程|系统返回|企业标准)|'
                r'正常范围|工艺参数|阈值|放行|PLC|联锁|补吹|加料|复吹|'
                r'(?:启动|停止|调整|控制).*(?:设备|炉|阀|温度)|'
                r'(?:℃|°C|百分之|千克|公斤|吨|分钟|小时)|'
                r'已(?:查询|确认|核实).*(?:MES|ERP|WMS|炉次|订单|库存)',
            )):
                raise ValueError('REFERENCE_OUTPUT_SCOPE_DENIED')
    return {'schema_version': '1.0', 'status': 'model_reference' if model['decision'] == 'reference' else 'abstain',
            'question': question, 'points': model['points'], 'evidence_verified': False,
            'citations': [], 'data_sources': [], 'automatic_actions': []}


def validate_packet(value, question):
    expected = {'schema_version', 'status', 'question', 'points', 'evidence_verified',
                'citations', 'data_sources', 'automatic_actions'}
    if (not isinstance(value, dict) or set(value) != expected or value['schema_version'] != '1.0'
            or value['question'] != question or value['evidence_verified'] is not False
            or any(value[k] != [] for k in ('citations', 'data_sources', 'automatic_actions'))
            or value['status'] not in ('model_reference', 'abstain')):
        raise ValueError('REFERENCE_PACKET_INVALID')
    decision = 'reference' if value['status'] == 'model_reference' else 'decline'
    return validate_reference(question, json.dumps({'decision': decision, 'points': value['points']}, ensure_ascii=False))


def product(value, request_id, meta):
    return dict(request_id=request_id, status=value['status'], intent='GENERAL_MODEL_REFERENCE',
                title='一般讨论与参考' if value['status'] == 'model_reference' else '这个问题不适合由模型知识回答',
                summary=BOUNDARY if value['status'] == 'model_reference' else '问题可能涉及具体事实、企业制度或生产操作，需要对应系统事实或有效资料。',
                reference_notice=NOTICE, trust_level='MODEL_GENERAL_KNOWLEDGE',
                groups=[], facts=[], analysis=value['points'], sources=[], table=None,
                next_actions=[], human_confirmation='请人工辨别参考内容的适用性；具体生产判断及现场操作仍须由授权人员确认。',
                process_steps=['确认仅为一般非量化讨论', 'DeepSeek生成未核验参考', '结构校验与范围检查；不生成引用或业务事实'],
                technical_meta={**meta, 'evidence_verified': False, 'citations': [], 'data_sources': [], 'automatic_actions': []},
                context_token=None)
