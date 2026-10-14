"""Build fictional controlled documents from individually authored topic records.

The evaluation questions are not a runtime answer whitelist. They are stored
separately; runtime consumes topic scope and real, identity-bound retrieval hits.
"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets/knowledge_f2/internal'
NOTICE = '本文件为工域 Copilot PoC 使用的虚构企业资料，不代表任何真实企业。'
DOMAINS = {
    'A': ('炼钢生产基础', '生产调度', 'production', 'MES,ERP', '班长,调度,计划人员', '生产组织总流程',
          '生产组织把订单安排、现场执行和班组交接连接起来。核对时必须分清计划事件与实际事件，尚未完成的专业确认不能被归入已完成任务。跨班次事项由接收岗位明确接续，计划改变也不能改写过去已经发生的生产事实。'),
    'B': ('转炉工艺', '炼钢工艺', 'converter', 'MES', '操作工,工艺员,班长', '转炉任务复核流程',
          '转炉资料用于说明生产记录和专业复核要求，不是一张可直接执行的设备操作卡。每条测量和报告都必须定位到具体炉次与阶段；相同钢种也可能因阶段和文件生效时间不同而使用不同目标。本文不提供供氧、枪位、加料或温控设定值。'),
    'C': ('精炼', '精炼工艺', 'refining', 'MES', '精炼班长,工艺员,质量人员', '精炼工序协同流程',
          '精炼环节需要接收前序事实并向后序传递可核查记录。LF、RH和VD的任务目的及记录不能互相替代，同一炉次经过多个工序也不意味着其数据可以混用。各工序完成情况、报告有效性和质量结论应保持独立。'),
    'D': ('连铸', '连铸工艺', 'casting', 'MES', '连铸班长,工艺员,质量人员', '连铸交接与追溯流程',
          '连铸核对具有浇次、炉次、机流与铸坯多层对象关系。只有正式系统关联才能连接这些对象，计划排列与实际生产顺序应区别记录。解释异常时须限定时间区间及对象范围，不能把一个局部事件扩展到整个浇次。'),
    'E': ('原料与辅料', '物料管理', 'materials', 'ERP,WMS', '物料员,仓储人员,质量人员', '材料接收与领用流程',
          '材料管理同时依赖物料身份、数量和质量状态。到货、验收、可用、预留、领用是不同业务事实；同一编码的不同批次仍可能具有不同限制。数量比较前必须确认单位，替代材料需要适用当前任务的明确授权。'),
    'F': ('MES', '生产信息管理', 'mes', 'MES', '生产记录员,IT人员,工艺员', 'MES数据治理流程',
          'MES是炉次及现场执行记录的事实来源。业务标识应由源系统建档产生，AI不能靠预生成编号列表判断存在性。事件时间、记录时间与同步时间各有含义，缺项或系统故障应明确表达，数据补录不能伪装成实时采集。'),
    'G': ('ERP', '生产计划', 'erp', 'ERP,MES', '计划人员,调度,订单责任人', '订单生命周期流程',
          'ERP维护生产任务的计划、数量、交期和修订。订单计划不是现场实时事实，联合查询必须通过明确关联到MES或WMS。审批中的修改不等于已经生效的订单；新旧修订混用可能导致数量与关系不一致，应先停止综合判断。'),
    'H': ('WMS', '仓储管理', 'wms', 'WMS,ERP', '仓储人员,物料员', '仓储收发与库存流程',
          'WMS中的库存量要连同批次、单位、位置和限制状态解释。冻结、待检、已预留、账面数量与可用量不可混为一谈；账面有量不构成出库批准。出入库、解冻和盘点调整属于原业务系统授权操作，不由问答页面代办。'),
    'I': ('质量管理', '质量管理', 'quality', 'MES,WMS', '质量人员,实验室人员,工艺员', '检验与质量确认流程',
          '质量链路要求样品、报告与业务对象可追溯。复验不应抹去原结果，报告更正应说明替代关系；数据缺失与正式不合格结论需要区分。工序结束、库存入账和质量放行各有不同证据，不能相互代替。'),
    'J': ('安全生产', '安全管理', 'safety', 'MES', '安全人员,班长,授权作业人员', '安全许可与上报流程',
          '本领域仅提供制度、流程、职责与记录核对级资料，不提供危险工业控制步骤。现场应按本单位真实有效的预案、许可和专业指挥处置。页面上的摘要、检索结果及模型文字既不是作业许可，也不能替代隔离、联锁或现场安全措施。'),
    'K': ('设备与维护', '设备管理', 'maintenance', 'MES,WMS', '设备人员,班长,调度', '设备维护协调流程',
          '设备记录用于连接异常现象、维护任务、许可和验收，不应从单一报警猜测根因。维护申请、实际作业完成、专业验收和生产恢复是独立节点。备件适配与现场操作须由设备责任岗位按正式资料确认。'),
    'L': ('IT与OT', '信息技术', 'it_ot', 'MES,ERP,WMS', 'IT人员,接口责任人,业务数据责任人', '系统事件与变更流程',
          '技术故障先按系统可用性和数据有效性定位。接口成功、网络连通与业务事实正确是不同验证目标。日志以请求身份关联且必须脱敏；恢复服务后重新核对对象、修订和时效，不能从进程启动就宣称业务完全恢复。'),
    'M': ('AI Copilot', 'AI应用管理', 'copilot', 'MES,ERP,WMS', '系统使用人员,知识管理员,业务审核人', '辅助查询治理流程',
          'Copilot是已有企业系统之上的只读交互层。事实、正式规则与公开行业背景有不同来源责任，不能相互补造。检索到相似文字不等于支持问题；来源身份、有效版本、内容完整性及生成后引用覆盖都必须通过检查。'),
    'N': ('岗位职责', '组织管理', 'roles', 'MES,ERP,WMS', '操作工,工艺员,班长,调度,质量,仓储,计划,IT,设备,管理人员', '岗位协同与授权流程',
          '岗位协作以实际授权和专业责任为界。知晓信息、接收待办、完成核对与批准处置是不同责任行为，不能因系统账号可访问就推定具有现场操作权。跨专业冲突应明确牵头与接收岗位，并保留尚待确认的事项。'),
}


def body(doc, context, case):
    checks = doc['checks']
    return '\n\n'.join([
        doc['document_name'], NOTICE,
        f"文件版本：{doc['version']}；生命周期：{doc['status']}；生效日期：{doc['effective_date']}。",
        '## 一、目的与适用范围', f"{doc['department']}在“{doc['topic_name']}”事项中使用本{doc['document_type']}。"
        f"适用系统：{doc['applicable_system']}；父流程：《{doc['parent_process']}》。",
        context,
        '## 二、责任岗位', doc['applicable_roles'] + '。各岗位仅确认其授权范围内的记录。',
        '## 三、核对要求', *[f'{i+1}. {text}' for i, text in enumerate(checks)],
        '## 四、虚构核对案例与异常分支', case,
        '## 五、记录与关联', '记录本次对象、来源修订、已核实项、待确认项及接收岗位。关联文件：'
        + doc['related_sop'] + '。关联名称不等于本次已取得有效依据。',
        '## 六、附则', '仅供演示和人工核对，不授予现场操作权限。历史、撤销及未来版本不支持当前结论。',
    ])


def build():
    docs, topics = [], []
    cases = dict(line.split('|', 1) for line in (DEST / 'cases.tsv').read_text(encoding='utf-8').splitlines())
    types = dict(zip('ABCDEFGHIJKLMN', [
        '生产管理制度', '工序核对SOP', '工序交接规范', '追溯核对SOP', '物料验收与交接规范',
        '数据管理规范', '订单管理制度', '仓储业务核对SOP', '质量管理规范', '安全职责与记录制度',
        '维护协同规范', '信息系统服务规程', '辅助查询使用规范', '岗位职责规范']))
    counters = {}
    for line in (DEST / 'topics.tsv').read_text(encoding='utf-8-sig').splitlines():
        domain, title, raw_terms, *checks = line.split('|')
        if len(checks) != 3:
            raise ValueError('each authored topic needs three distinct reviewed points')
        counters[domain] = counters.get(domain, 0) + 1
        identity = domain + f'{counters[domain]:02d}'
        knowledge_domain, department, stage, systems, roles, parent, context = DOMAINS[domain]
        terms = raw_terms.split(';')
        topics.append({'id': identity, 'name': title, 'terms': terms})
        doc = dict(chunk_id='GY-' + identity + '-v1', topic_id=identity, topic_name=title,
                   source_file_name='GY-' + identity + '-v1.md', document_name='工域' + title + '核对规程',
                   version='1.0', status='active', effective_date='2026-01-01', effective_from='2026-01-01T00:00:00+00:00',
                   effective_until='2030-01-01T00:00:00+00:00', scope='GY-FICTIONAL-ENTERPRISE', department=department,
                   process_stage=stage, steel_grade='DEMO-ALL', steel_grade_scope='DEMO-ALL', rule_id='GY-MANAGEMENT-ONLY',
                   parameters=['knowledge'], directions=['reference'], chapter='第三章', section='核对要求', page=None,
                   checks=checks, source_type='INTERNAL_CONTROLLED', url='not-applicable', knowledge_domain=knowledge_domain,
                   document_type=types[domain], applicable_system=systems, risk_level='人工确认', parent_process=parent,
                   related_sop='工域' + ('交接班' if domain in 'ABCD' else '质量放行' if domain in 'EHI' else '错误反馈') + '核对规程',
                   applicable_roles=roles, publisher='工域虚构企业', publication_date='2026-01-01', accessed_at='not-applicable')
        doc['content'] = body(doc, context, cases[identity])
        doc['content_sha256'] = hashlib.sha256(doc['content'].encode()).hexdigest()
        docs.append(doc)
    for index, original in enumerate(d for d in docs[:] if d['topic_id'].endswith(('01','02'))):
        doc = copy.deepcopy(original)
        status = ('retired', 'revoked', 'future')[index % 3]
        doc.update(status=status, version={'retired':'0.9','revoked':'0.8','future':'2.0'}[status])
        if status == 'future':
            doc.update(effective_date='2035-01-01', effective_from='2035-01-01T00:00:00+00:00', effective_until='2040-01-01T00:00:00+00:00')
        else:
            doc.update(effective_date='2025-01-01', effective_from='2025-01-01T00:00:00+00:00', effective_until='2026-01-01T00:00:00+00:00')
        doc['publication_date'] = doc['effective_date']
        doc['chunk_id'] = 'GY-' + doc['topic_id'] + '-' + status
        doc['source_file_name'] = doc['chunk_id'] + '.md'
        doc['content'] = body(doc, DOMAINS[doc['topic_id'][0]][-1], cases[doc['topic_id']])
        doc['content_sha256'] = hashlib.sha256(doc['content'].encode()).hexdigest()
        docs.append(doc)
    questions = []
    def question(text, sources, kind):
        questions.append({'id': f'F2-I-{len(questions)+1:03d}', 'question': text, 'expected': 'answered', 'topic_ids': sources, 'kind': kind})
    for topic in topics:
        question('企业' + topic['terms'][0] + '有哪些核对要求？', [topic['id']], 'direct')
    for topic in topics[:56]:
        question('请问我们公司' + topic['terms'][-1] + '应该检查什么？', [topic['id']], 'colloquial')
    for topic in topics[72:88]:
        question('帮我说说' + topic['terms'][-1] + '的管理要点。', [topic['id']], 'paraphrase')
    for index in range(16):
        a, b = topics[index*2], topics[index*2+1]
        question('企业' + a['terms'][0] + '与' + b['terms'][0] + '分别有哪些要求？', [a['id'],b['id']], 'cross_document')
    unsupported = [{'id': f'F2-U-{i+1:03d}', 'question': text, 'expected': 'abstain'} for i, text in enumerate(
        [f'公司{t["name"]}的标准数值是多少？' for t in topics[:25]] +
        [f'企业{t["name"]}有哪些要求，以及今年利润是多少？' for t in topics[25:50]])]
    for doc in docs:
        (DEST / doc['source_file_name']).write_text(doc['content'], encoding='utf-8')
    corpus = {'source_type':'INTERNAL_CONTROLLED', 'notice':NOTICE, 'documents':docs, 'topics':topics,
              'questions':[questions[0]]}
    for name, value in [('corpus.json',corpus),('questions.json',questions),('unsupported_questions.json',unsupported)]:
        (DEST / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'documents':len(docs),'active':len(topics),'domains':len(counters),'characters':sum(len(d['content']) for d in docs),
                      'min_characters':min(len(d['content']) for d in docs),'questions':len(questions),'unsupported':len(unsupported)},ensure_ascii=False))


if __name__ == '__main__':
    build()
