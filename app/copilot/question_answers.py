"""Answer each requested business facet using the already verified child result."""
import re


def requested_parts(question):
    if not re.search(r'异常|是否正常|工艺分析|分析炉次', question):
        return []
    parts = []
    if re.search(r'订单|ERP', question, re.I): parts.append(('ERP', '生产订单'))
    if re.search(r'库存|WMS', question, re.I): parts.append(('WMS', '库存情况'))
    return parts + [('ANALYSIS', '工艺异常判断')] if parts else []


def add_answers(parent, question, business=None, analysis=None):
    parts = requested_parts(question)
    if not parts: return parent
    business, analysis = business or parent, analysis or parent
    answers = []
    for system, label in parts:
        if system == 'ANALYSIS':
            text = analysis['summary']
            confirmed_comparison = any(g.get('title') == '实测参数与有效规则' for g in analysis.get('groups', []))
            if analysis['status'] in ('data_error','system_error','clarification','unsupported') or (analysis['status']=='abstain' and not confirmed_comparison):
                text = '尚不能确认正常或异常。' + text
            else:
                text += ' ' + ' '.join(p for p in analysis.get('analysis', []) if '该任务指定批次需求' not in p)
            status = analysis['status']
        else:
            groups = [g for g in business.get('groups', []) if g['system'] == system]
            if groups:
                text = '；'.join(f['label'] + '：' + f['value'] for g in groups for f in g['facts']) + '。'
                if system == 'WMS': text += ' ' + ' '.join(p for p in business.get('analysis', []) if '该任务指定批次需求' in p)
                status = 'verified_read_only'
            else:
                text = '没有取得经过核验的' + label + '结果。' + business['summary']
                status = business['status']
        answers.append(dict(question=label, status=status, answer=text.strip()))
    parent['question_answers'] = answers
    # Legacy clients also render analysis: do not hide facts behind a new field.
    parent['analysis'] = [str(i+1) + '. ' + a['question'] + '：' + a['answer'] for i,a in enumerate(answers)]
    parent['next_actions'] = [s for s in parent.get('next_actions', []) if '可继续查询该炉次的业务记录' not in s]
    return parent
