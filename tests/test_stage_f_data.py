"""New fictional source dataset; no remote Dify claims."""
import json
import sqlite3
from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from app.demo_dataset.generate import generate
from app.demo_dataset.api import router
from app.main import create_app

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def data(tmp_path):
    state = generate(tmp_path, NOW)
    application = create_app(tmp_path)
    application.include_router(router)
    return TestClient(application), state, tmp_path


def test_dataset_repeatability_and_old_fixtures(tmp_path):
    first = generate(tmp_path / 'a', NOW)
    repeated = generate(tmp_path / 'a', NOW)
    other = generate(tmp_path / 'b', NOW)
    assert repeated['reused'] and first['data_sha256'] == other['data_sha256']
    with sqlite3.connect(tmp_path / 'a/mes.db') as db:
        before = db.execute("SELECT * FROM heats WHERE heat_id='DEMO-NORMAL'").fetchone()
    generate(tmp_path / 'a', NOW.replace(hour=11))
    with sqlite3.connect(tmp_path / 'a/mes.db') as db:
        assert db.execute("SELECT * FROM heats WHERE heat_id='DEMO-NORMAL'").fetchone() == before


def test_source_relations_are_actual_fields(data):
    _, state, path = data
    with sqlite3.connect(path / 'mes.db') as mes, sqlite3.connect(path / 'erp.db') as erp, sqlite3.connect(path / 'wms.db') as wms:
        for (text,) in mes.execute('SELECT record_json FROM demo_heat_details'):
            record = json.loads(text)
            if record['demo_scenario'] == 'relation_error':
                assert erp.execute('SELECT 1 FROM production_orders WHERE production_order_id=?', [record['production_order_id']]).fetchone() is None
                continue
            order = json.loads(erp.execute('SELECT record_json FROM production_orders WHERE production_order_id=?', [record['production_order_id']]).fetchone()[0])
            batch = json.loads(wms.execute('SELECT record_json FROM inventory_batches WHERE batch_id=?', [order['batch_id']]).fetchone()[0])
            assert record['heat_id'] in order['heat_ids'] and order['steel_grade'] == record['steel_grade']
            assert batch['production_order_id'] == order['production_order_id'] and batch['material_code'] == order['material_code']
    assert (state['heat_count'], state['order_count'], state['batch_count']) == (400, 100, 200)


@pytest.mark.parametrize('path', ['/api/mes/heats', '/api/erp/production-orders', '/api/wms/inventory'])
def test_bounded_lists(data, path):
    client, _, _ = data
    body = client.get(path).json()
    assert body['returned_count'] == 10 and body['truncated'] and body['fictional']
    assert client.get(path, params={'limit': 21}).status_code == 422
    assert client.get(path, params={'limit': 20}).json()['returned_count'] == 20
    assert client.get(path, params={'sql': 'SELECT *'}).status_code == 422
    assert client.post(path, json={}).status_code == 405


@pytest.mark.parametrize('params', [{'date': '2026-10-03'}, {'date': '2026-10-02', 'furnace_id': 'DEMO-FURNACE-2'},
                                 {'start_time': '2026-10-01T00:00:00+08:00', 'end_time': '2026-10-03T00:00:00+08:00'},
                                 {'review_only': True}])
def test_date_filter_uses_source_production_time(data, params):
    response = data[0].get('/api/mes/heats', params=params)
    assert response.status_code == 200
    for row in response.json()['rows']:
        if 'date' in params:
            assert row['planned_start_time'].startswith(params['date'])
        if 'furnace_id' in params:
            assert row['furnace_id'] == params['furnace_id']
        if params.get('review_only'):
            assert row['historical_review_flag'] is True


@pytest.mark.parametrize('path,params', [('/api/erp/production-orders', {'furnace_id': 'x'}),
    ('/api/wms/inventory', {'date': '2026-10-03'}), ('/api/wms/inventory', {'review_only': True}),
    ('/api/mes/heats', {'start_time': '2026-10-01T00:00:00', 'end_time': '2026-10-02T00:00:00'}),
    ('/api/mes/heats', {'start_time': '2026-08-01T00:00:00+08:00', 'end_time': '2026-09-30T12:00:00+08:00'}),
    ('/api/mes/heats', {'date': '2026-10-01', 'start_time': '2026-10-01T00:00:00+08:00'})])
def test_invalid_filters_fail_closed(data, path, params):
    assert data[0].get(path, params=params).status_code == 422


def test_empty_is_empty_not_fake_inventory(data):
    body = data[0].get('/api/wms/inventory', params={'status': 'DOES-NOT-EXIST'}).json()
    assert body['rows'] == [] and body['source_snapshot_at'] == NOW.isoformat()
    info = data[0].get('/api/demo/summary').json()
    assert info['systems']['mes']['count'] == 400 and info['furnace_count'] == 2


def test_reconstruction_checks_missing_source(data):
    _, _, path = data
    with sqlite3.connect(path / 'erp.db') as db:
        db.execute('DELETE FROM demo_order_details WHERE production_order_id=(SELECT production_order_id FROM demo_order_details LIMIT 1)')
    with pytest.raises(ValueError):
        generate(path, NOW)
