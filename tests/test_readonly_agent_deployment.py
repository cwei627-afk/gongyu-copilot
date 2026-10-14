"""Opt-in real Stage D gateway + actual upstream HTTP, no external LLM."""
import json
import os
import uuid
import httpx
import pytest

pytestmark=pytest.mark.skipif(os.environ.get('RUN_DEPLOYMENT_E2E')!='1' or not os.environ.get('AGENT_CONTROL_SECRET'), reason='Stage D Compose only')
BASE=os.environ.get('API_BASE_URL','http://localhost:18090')


@pytest.mark.parametrize('query,steps', [
    ('查询炉次 DEMO-BOTH', [('mes_heat','DEMO-BOTH')]),
    ('查询ERP订单 PO-DEMO-BOTH', [('erp_order','PO-DEMO-BOTH')]),
    ('查询WMS批次 BATCH-DEMO-BOTH 的库存', [('wms_batch','BATCH-DEMO-BOTH')]),
    ('查询炉次 DEMO-BOTH 的ERP订单和WMS库存', [('mes_heat','DEMO-BOTH'),('mes_links','DEMO-BOTH'),('erp_order','PO-DEMO-BOTH'),('wms_batch','BATCH-DEMO-BOTH')])])
def test_live_gateway_paths(query,steps):
    headers={'X-Agent-Control':os.environ['AGENT_CONTROL_SECRET']}
    response=httpx.post(BASE+'/agent/control/begin',headers=headers,json={'query':query,'request_id':str(uuid.uuid4())},timeout=10)
    response.raise_for_status();token=response.json()['capability']
    for op,entity in steps:
        result=httpx.get(BASE+f'/agent/tools/{op}/{entity}',params={'capability':token},timeout=10).json()
        assert result['status']=='verified'
    claims=result['verified_claims']
    output=json.dumps({'selected_claim_ids':[c['claim_id'] for c in claims], 'answer':'\n'.join(c['text'] for c in claims)},ensure_ascii=False)
    final=httpx.post(BASE+'/agent/control/finish',headers=headers,json={'capability':token,'text':output},timeout=10).json()
    assert final['status']=='verified_read_only' and len(final['data_sources'])==len(steps)


def test_live_permission_block():
    headers={'X-Agent-Control':os.environ['AGENT_CONTROL_SECRET']}
    response=httpx.post(BASE+'/agent/control/begin',headers=headers,json={'query':'查询炉次 DEMO-BOTH','request_id':str(uuid.uuid4())},timeout=10).json()
    result=httpx.get(BASE+'/agent/tools/write_plc/DEMO-BOTH',params={'capability':response['capability']},timeout=10).json()
    assert result['code']=='TOOL_NOT_AUTHORIZED' and not result['facts']
