"""Opt-in HTTP verification against a freshly built F2 Mock Compose service."""
import hashlib
import json
import os

import httpx
import pytest

pytestmark=pytest.mark.skipif(os.environ.get('RUN_STAGE_F2_E2E')!='1',reason='F2 Compose profile only')
BASE=os.environ.get('API_BASE_URL','http://127.0.0.1:18096')


@pytest.mark.parametrize('path,field,system',[('/api/mes/heats','heat_id','MES'),
    ('/api/erp/production-orders','production_order_id','ERP'),('/api/wms/inventory','batch_id','WMS')])
def test_live_source_owned_short_identity(path,field,system):
    entity=httpx.get(BASE+path,params={'limit':1},timeout=15).json()['rows'][0][field]
    result=httpx.post(BASE+'/api/demo/display-identities',json={'identifiers':[entity]},timeout=15)
    assert result.status_code==200
    data=result.json(); rows=data['identities']
    assert data['fictional'] is True and len(rows)==1 and rows[0]['system']==system
    assert data['content_sha256']==hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    back=httpx.post(BASE+'/api/demo/display-identities',json={'identifiers':[rows[0]['display_id']]},timeout=15).json()
    assert back==data


def test_live_frozen_stock_is_not_available():
    response=httpx.get(BASE+'/api/wms/inventory',params={'status':'frozen'},timeout=15)
    assert response.status_code==200
    body=response.json()
    assert body['total_matching']==8 and all(r['available_quantity']==0 and r['status']=='frozen' for r in body['rows'])


def test_live_unknown_identity_cannot_be_fabricated():
    body=httpx.post(BASE+'/api/demo/display-identities',json={'identifiers':['H20000101-9999']},timeout=15).json()
    assert body['identities']==[]
    assert httpx.put(BASE+'/api/demo/display-identities',json={'identifiers':['X']},timeout=15).status_code==405
    assert httpx.post(BASE+'/api/demo/display-identities',json={'identifiers':['X']*31},timeout=15).status_code==422
