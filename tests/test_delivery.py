"""Meaningful delivery regression: idempotence, stale facts and isolated source data."""
import json
import sqlite3
from datetime import datetime,timedelta,timezone

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from scripts.prepare_demo import prepare_demo

NOW=datetime(2026,10,2,2,tzinfo=timezone.utc)


def test_named_run_does_not_refresh_or_modify_old_rows(tmp_path):
    first=prepare_demo(tmp_path,'test-one',NOW)
    before={p.name:p.read_bytes() for p in tmp_path.glob('*.db')}
    second=prepare_demo(tmp_path,'test-one',NOW+timedelta(hours=7))
    assert second['records']==first['records'] and second['created_at']==first['created_at']
    assert second['reused'] and not second['fresh']
    assert before=={p.name:p.read_bytes() for p in tmp_path.glob('*.db')}


def test_another_run_keeps_existing_object_facts(tmp_path):
    first=prepare_demo(tmp_path,'first',NOW)
    heat=first['records']['NORMAL']['heat_id']
    with sqlite3.connect(tmp_path/'mes.db') as db:before=db.execute('SELECT * FROM heats WHERE heat_id=?',(heat,)).fetchone()
    second=prepare_demo(tmp_path,'second',NOW+timedelta(hours=1))
    with sqlite3.connect(tmp_path/'mes.db') as db:after=db.execute('SELECT * FROM heats WHERE heat_id=?',(heat,)).fetchone()
    assert before==after
    assert first['records']['NORMAL']!=second['records']['NORMAL']
    client=TestClient(create_app(tmp_path,analysis_clock=lambda:NOW+timedelta(hours=1)))
    for state in (first,second):
        response=client.get('/api/mes/heats/'+state['records']['NO-SOP']['heat_id']+'/analysis-context')
        assert response.status_code==200  # Independent runs must not create rule-version conflicts.


@pytest.mark.parametrize('label',['../escape','space value','a'*41,'','x/y'])
def test_rejects_unsafe_run_labels(tmp_path,label):
    with pytest.raises(ValueError):prepare_demo(tmp_path,label,NOW)
    assert not list(tmp_path.iterdir())


def test_facts_and_rule_are_separate_and_no_sop_fixture_does_not_change_old_rule(tmp_path):
    state=prepare_demo(tmp_path,'facts',NOW)
    with sqlite3.connect(tmp_path/'mes.db') as db:
        original=json.loads(db.execute('SELECT rule_json FROM process_rules WHERE rule_id=?',('DEMO-RULE-A-REVIEW-v1',)).fetchone()[0])
        added=json.loads(db.execute('SELECT rule_json FROM process_rules WHERE rule_id=?',('DEMO-RULE-E2-NO-SOP-facts',)).fetchone()[0])
    assert added['limits']==original['limits'] and added['steel_grade']!=original['steel_grade']
    client=TestClient(create_app(tmp_path,analysis_clock=lambda:NOW))
    for label,status in [('NORMAL',200),('HIGH',200),('NO-SOP',200),('MISSING',409),('NO-RULE',409)]:
        response=client.get('/api/mes/heats/'+state['records'][label]['heat_id']+'/analysis-context')
        assert response.status_code==status
    assert state['records']['NORMAL']['production_order_id'].startswith('ORDER-')
    assert state['records']['NORMAL']['heat_id'] not in state['records']['NORMAL']['production_order_id']
    assert client.get('/api/mes/heats/'+state['records']['MISSING-MES']['heat_id']).status_code==409


@pytest.mark.parametrize('label,quantity',[('NORMAL',150),('SHORTAGE',50),('ZERO',0)])
def test_quantity_zero_is_real_source_value(tmp_path,label,quantity):
    state=prepare_demo(tmp_path,'inventory',NOW)
    response=TestClient(create_app(tmp_path)).get('/api/wms/batches/'+state['records'][label]['batch_id'])
    assert response.status_code==200
    assert response.json()['data']['available_quantity']==quantity
