"""Every requested business facet has an answer, including explicit unknowns."""
import pytest
from app.copilot.question_answers import add_answers

QUESTION='H20261006-0033 炉次相关的订单、库存情况以及判断其是否属于异常情况'


def result(status='data_error'):
    return dict(status=status,summary='缺少适用规则。',analysis=[],groups=[],next_actions=[],sources=[])


def test_three_parts_and_legacy_analysis_use_only_provided_verified_groups():
    business=result('verified_read_only')
    business['groups']=[dict(system='ERP',facts=[dict(label='生产订单',value='PO20261006-0009'),dict(label='当前状态',value='延期')]),
                        dict(system='WMS',facts=[dict(label='库存批次',value='LOT20261004-0017'),dict(label='可用库存',value='150 kg')])]
    value=add_answers(result('partial'),QUESTION,business,result())
    assert len(value['question_answers'])==len(value['analysis'])==3
    assert 'PO20261006-0009' in value['analysis'][0] and '延期' in value['analysis'][0]
    assert '150 kg' in value['analysis'][1]
    assert '尚不能确认正常或异常' in value['analysis'][2]
    assert value['sources']==[]


@pytest.mark.parametrize('status',['system_error','data_error','abstain','clarification','unsupported'])
def test_failed_query_answers_each_part_without_invented_values(status):
    value=add_answers(result(status),QUESTION)
    assert len(value['question_answers'])==3
    assert all(a['status']==status for a in value['question_answers'])
    assert '没有取得' in value['analysis'][0] and '没有取得' in value['analysis'][1]
    assert '150' not in str(value)


def test_order_only_plus_analysis_returns_two_answers():
    value=add_answers(result(),'查订单及是否异常')
    assert [a['question'] for a in value['question_answers']]==['生产订单','工艺异常判断']


def test_single_request_does_not_get_extra_questions():
    assert 'question_answers' not in add_answers(result(),'查询炉次当前状态')


def test_confirmed_parameter_anomaly_with_missing_sop_is_not_denied():
    value=result('abstain'); value['summary']='已确认参数偏差，企业规程不足，不能给出处置建议。'
    value['groups']=[dict(title='实测参数与有效规则',system='MES 规则接口',facts=[])]
    value['analysis']=['温度实测高于本次有效规则上限。','该任务指定批次需求一项已核验。']
    add_answers(value,QUESTION)
    assert '尚不能确认正常或异常' not in value['question_answers'][-1]['answer']
    assert '该任务指定批次需求' not in value['question_answers'][-1]['answer']
