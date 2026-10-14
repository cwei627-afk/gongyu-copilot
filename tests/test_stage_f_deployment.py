"""Opt-in actual HTTP against an isolated Stage F Compose source adapter."""
import os
import httpx
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('RUN_STAGE_F_E2E') != '1', reason='Stage F Compose profile only')
BASE = os.environ.get('API_BASE_URL', 'http://localhost:18096')


@pytest.mark.parametrize('path,count', [('/api/mes/heats', 400), ('/api/erp/production-orders', 100), ('/api/wms/inventory', 200)])
def test_live_bounded_source(path, count):
    response = httpx.get(BASE + path, timeout=15)
    assert response.status_code == 200
    body = response.json()
    assert body['total_matching'] == count and body['returned_count'] == 10 and body['fictional']
    assert httpx.get(BASE + path, params={'limit': 21}, timeout=15).status_code == 422
    assert httpx.post(BASE + path, timeout=15).status_code == 405


def test_live_unknown_filter_rejected():
    assert httpx.get(BASE + '/api/wms/inventory', params={'sql': 'SELECT *'}, timeout=15).status_code == 422


def test_live_demo_summary_is_source_owned():
    body = httpx.get(BASE + '/api/demo/summary', timeout=15).json()
    assert body['fictional'] and body['systems']['mes']['count'] == 400
    assert body['steel_grade_count'] == 10 and body['furnace_count'] == 2
