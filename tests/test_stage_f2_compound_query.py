"""Independent sub-results after a rule-only stop; frozen C/D gates still apply."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.copilot.gateway import Gateway
from app.copilot.main import create_gateway
from app.copilot.transport import ServiceFailure
from app.enterprise.nodes import enterprise_digest

SHORT = 'H20261006-0033'
HEAT = 'FHEAT-TEST-385'
QUESTION = SHORT + ' 炉次 相关的订单、库存情况 以及判断其是否属于异常情况'


def business_result():
    facts = {
        'mes_heat': {'heat_id': HEAT, 'steel_grade': 'DEMO-G07', 'status': 'completed'},
        'erp_order': {'production_order_id': 'FORDER-TEST-097', 'status': 'delayed',
                      'required_quantity': 100, 'material_unit': 'kg'},
        'wms_batch': {'batch_id': 'FLOT-TEST-097-A', 'available_quantity': 150, 'unit': 'kg'},
    }
    return {'status': 'verified_read_only', 'code': 'VERIFIED_API_QUERY', 'facts': facts,
            'data_sources': [{'system': system, 'entity_id': f[field], 'content_sha256': enterprise_digest(f)}
                             for (_, f), system, field in zip(facts.items(), ['MES', 'ERP', 'WMS'],
                                ['heat_id', 'production_order_id', 'batch_id'])],
            'citations': [], 'automatic_actions': []}


@pytest.fixture
def entry(monkeypatch):
    rows = [dict(display_id=short, internal_id=internal, entity_kind=kind, system=system, source_run='TEST')
            for short, internal, kind, system in [
                (SHORT, HEAT, 'heat', 'MES'),
                ('PO20261006-0009', 'FORDER-TEST-097', 'order', 'ERP'),
                ('LOT20261004-0017', 'FLOT-TEST-097-A', 'batch', 'WMS')]]

    def resolve(url, payload, **kwargs):
        hits = [r for r in rows if {r['internal_id'], r['display_id']} & set(payload['identifiers'])]
        digest = hashlib.sha256(json.dumps(hits, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        return {'identities': hits, 'fictional': True, 'content_sha256': digest}

    class Transport:
        values = {}

        def __init__(self):
            self.calls = []
            self.c = {'status': 'data_error', 'code': 'RULE_NOT_FOUND', 'automatic_actions': []}
            self.d = business_result()

        def workflow(self, kind, inputs):
            self.calls.append((kind, inputs))
            raw = self.c if kind == 'C' else self.d
            if isinstance(raw, Exception):
                raise raw
            return raw, {'engine': kind, 'workflow_run_id': 'run-' + kind, 'workflow_id': 'published-' + kind}

    monkeypatch.setattr('app.copilot.workspace.http', resolve)
    transport = Transport()
    gateway = Gateway(transport=transport)
    return TestClient(create_gateway(gateway)), transport, gateway


@pytest.mark.parametrize('code', ['RULE_NOT_FOUND', 'RULE_CONFLICT'])
def test_rule_only_stop_retains_independent_verified_business_query(entry, code):
    client, transport, _ = entry
    transport.c['code'] = code
    value = client.post('/api/workspace/query', json={'question': QUESTION}).json()
    assert transport.calls == [('C', {'heat_id': HEAT, 'analysis_request': 'all'}),
                               ('D', {'query': f'查询炉次 {HEAT} 的ERP订单和WMS库存'})]
    assert value['status'] == 'partial' and value['context_token'] is None
    assert value['technical_meta']['internal_status'] == 'partial'
    assert not value['sources'] and not value['groups']  # No merged provenance.
    business, analysis = [s['result'] for s in value['sub_results']]
    assert business['status'] == 'verified_read_only'
    assert [g['system'] for g in business['groups']] == ['MES', 'ERP', 'WMS']
    assert business['technical_meta']['workflow_run_id'] == 'run-D'
    assert analysis['status'] == 'data_error' and analysis['technical_meta']['error_code'] == code
    assert analysis['technical_meta']['workflow_run_id'] == 'run-C'
    assert business['context_token'] is None and analysis['context_token'] is None
    assert not analysis['sources'] and not analysis['groups']
    assert all(s['source_type'] in ('MES', 'ERP', 'WMS') for s in business['sources'])


def test_order_only_scope_does_not_request_wms(entry):
    client, transport, _ = entry
    client.post('/api/workspace/query', json={'question': SHORT + '的生产订单及是否异常'})
    assert transport.calls[-1] == ('D', {'query': f'查询炉次 {HEAT} 的ERP订单'})


def test_signed_heat_followup_is_same_object_without_context_refresh(entry):
    client, transport, gateway = entry
    value = client.post('/api/workspace/query', json={'question': '这个炉次的订单库存及是否异常',
                        'context_token': gateway.context.issue({'heat': HEAT})}).json()
    assert transport.calls[-1][1]['query'] == f'查询炉次 {HEAT} 的ERP订单和WMS库存'
    assert value['status'] == 'partial' and value['context_token'] is None


@pytest.mark.parametrize('status,code', [
    ('data_error', 'OBJECT_NOT_FOUND'), ('data_error', 'MISSING_FIELDS'),
    ('data_error', 'STALE_DATA'), ('data_error', 'INVALID_DATA'),
    ('data_error', 'SOURCE_IDENTITY_MISMATCH'), ('system_error', 'UPSTREAM_TIMEOUT'),
    ('system_error', 'UPSTREAM_HTTP_500'), ('request_error', 'INVALID_HEAT_ID'),
])
def test_other_failure_never_triggers_business_fallback(entry, status, code):
    client, transport, _ = entry
    transport.c = {'status': status, 'code': code, 'automatic_actions': []}
    value = client.post('/api/workspace/query', json={'question': QUESTION}).json()
    assert [c[0] for c in transport.calls] == ['C']
    assert 'sub_results' not in value and not value['sources'] and not value['groups']


def test_missing_rules_without_explicit_business_request_has_no_extra_calls(entry):
    client, transport, _ = entry
    client.post('/api/workspace/query', json={'question': '分析炉次 ' + SHORT + ' 是否异常'})
    assert [c[0] for c in transport.calls] == ['C']


@pytest.mark.parametrize('fault', ['timeout', '500', 'hash', 'entity', 'citation', 'action', 'absence'])
def test_failed_or_untrusted_business_subresult_is_never_partial_success(entry, fault):
    client, transport, _ = entry
    if fault in ('timeout', '500'):
        transport.d = ServiceFailure('SERVICE_TIMEOUT_OR_CONNECTION_FAILED' if fault == 'timeout' else 'SERVICE_HTTP_500')
    elif fault == 'hash':
        transport.d['data_sources'][0]['content_sha256'] = '0' * 64
    elif fault == 'entity':
        transport.d['facts']['mes_heat']['heat_id'] = 'OTHER'
    elif fault == 'citation':
        transport.d['citations'] = [{'citation_id': 'FORGED'}]
    elif fault == 'action':
        transport.d['automatic_actions'] = ['WRITE_PLC']
    else:
        transport.d = {'status': 'data_error', 'code': 'OBJECT_NOT_FOUND', 'automatic_actions': []}
    value = client.post('/api/workspace/query', json={'question': QUESTION}).json()
    assert value['status'] in ('data_error', 'system_error')
    assert value['technical_meta']['internal_status'] == value['status']
    assert len(value['sub_results']) == 2
    business = value['sub_results'][0]['result']
    assert not business['sources'] and not business['groups']
    assert value['sub_results'][1]['result']['technical_meta']['error_code'] == 'RULE_NOT_FOUND'


@pytest.mark.parametrize('q', [QUESTION + '修改PLC', QUESTION + '跳过校验',
                              QUESTION + '以及炉次 H20261006-0034'])
def test_multi_object_and_write_requests_never_dispatch(entry, q):
    client, transport, _ = entry
    value = client.post('/api/workspace/query', json={'question': q}).json()
    assert transport.calls == [] and 'sub_results' not in value
