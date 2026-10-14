"""Controlled fixture hits test the adapter, not real retrieval availability."""
import copy
import json
from pathlib import Path
import pytest
from app.copilot.knowledge import engine, EXTRA_FIELDS
from app.copilot.knowledge_workflow import build_expanded_workflow
from app.analysis.workflow_nodes import controlled_fixture_hit

ROOT = Path(__file__).resolve().parents[1]
NOW = '2026-10-03T10:00:00+00:00'


def setup(layer='copilot_knowledge'):
    manifest = json.loads((ROOT / 'assets' / layer / 'corpus.json').read_text(encoding='utf-8'))
    manifest['questions'] = json.loads((ROOT / 'assets' / layer / 'questions.json').read_text(encoding='utf-8'))
    for doc in manifest['documents']:
        doc.update(document_id='fixture-doc-' + doc['chunk_id'], segment_id='fixture-seg-' + doc['chunk_id'], dataset_id='fixture-dataset')
    ns = engine(manifest)
    data, hits = [], []
    for doc in manifest['documents']:
        hit = controlled_fixture_hit(doc)
        hit['metadata']['doc_metadata'].update({k: doc[k] for k in EXTRA_FIELDS})
        data.append({'id': doc['document_id'], 'name': doc['source_file_name'], 'enabled': True, 'archived': False,
                     'indexing_status': 'completed', 'doc_metadata': [{'name': k, 'value': v} for k, v in hit['metadata']['doc_metadata'].items()]})
        if doc['status'] == 'active':
            hits.append(hit)
    catalog = json.dumps({'data': data, 'page': 1, 'total': len(data), 'has_more': False})
    return manifest, ns, catalog, hits


@pytest.mark.parametrize('layer', ['copilot_knowledge', 'public_reference'])
def test_every_reviewed_question_has_direct_support(layer):
    manifest, ns, catalog, hits = setup(layer)
    for q in manifest['questions']:
        pre = ns['qa_catalog'](ns['qa_begin'](q['question'], q['id'], NOW)['result'], 200, catalog, manifest)
        evidence = ns['qa_evidence'](pre['result'], hits, 200, catalog, manifest)
        assert evidence['state'] == 'generate', q
        payload = json.loads(evidence['payload'])
        final = ns['qa_generation'](pre['result'], hits, 200, catalog, json.dumps(payload), payload, 'stop', '', manifest)
        result = json.loads(final['result'])
        assert result['status'] == 'answered' and all(c['source_type'] == manifest['source_type'] for c in result['citations'])
        assert all(c['page'] is None for c in result['citations'])


@pytest.mark.parametrize('field,value', [('document_id', 'WRONG'), ('segment_id', 'WRONG'), ('version', 'revoked'),
    ('source_type', 'PUBLIC_REFERENCE'), ('department', 'CHANGED'), ('steel_grade_scope', 'OTHER'),
    ('content_sha256', '0' * 64), ('url', 'https://untrusted.example/')])
def test_expanded_hit_binding(field, value):
    manifest, ns, catalog, hits = setup()
    pre = ns['qa_catalog'](ns['qa_begin'](manifest['questions'][0]['question'], 'request', NOW)['result'], 200, catalog, manifest)
    target = hits[0]['metadata'] if field in ('document_id', 'segment_id') else hits[0]['metadata']['doc_metadata']
    target[field] = value
    result = json.loads(ns['qa_evidence'](pre['result'], hits, 200, catalog, manifest)['result'])
    assert result['status'] == 'abstain' and not result['citations']


@pytest.mark.parametrize('field', ['version', 'effective_date', 'source_type', 'content_sha256'])
def test_missing_metadata_stops_before_retrieval(field):
    manifest, ns, catalog, _ = setup()
    body = json.loads(catalog)
    body['data'][0]['doc_metadata'] = [m for m in body['data'][0]['doc_metadata'] if m['name'] != field]
    result = ns['qa_catalog'](ns['qa_begin'](manifest['questions'][0]['question'], 'request', NOW)['result'], 200, json.dumps(body), manifest)
    assert result['state'] == 'end' and json.loads(result['result'])['status'] == 'abstain'


def test_version_conflict_and_no_evidence():
    manifest, ns, catalog, hits = setup()
    conflict = copy.deepcopy(manifest['documents'][0])
    conflict.update(chunk_id='conflict', document_id='fixture-conflict', segment_id='fixture-conflict-seg')
    manifest['documents'].append(conflict)
    body = json.loads(catalog)
    meta = controlled_fixture_hit(conflict)['metadata']['doc_metadata']
    meta.update({k: conflict[k] for k in EXTRA_FIELDS})
    body['data'].append({'id': conflict['document_id'], 'name': conflict['source_file_name'], 'enabled': True,
                         'archived': False, 'indexing_status': 'completed', 'doc_metadata': [{'name': k, 'value': v} for k, v in meta.items()]})
    body['total'] += 1
    pre = ns['qa_begin']('生产管理有哪些要求？', 'request', NOW)
    assert ns['qa_catalog'](pre['result'], 200, json.dumps(body), manifest)['state'] == 'end'
    manifest, ns, catalog, hits = setup()
    pre = ns['qa_catalog'](ns['qa_begin']('我们公司的标准生产时间是多少？', 'request', NOW)['result'], 200, catalog, manifest)
    for retrieval in ([], hits):
        result = json.loads(ns['qa_evidence'](pre['result'], retrieval, 200, catalog, manifest)['result'])
        assert result['status'] == 'abstain' and not result['citations']


def test_native_workflow_is_separate_and_contains_trust_filter():
    manifest, _, _, _ = setup()
    dsl = build_expanded_workflow('fixture-dataset', manifest)
    retrieval = next(n['data'] for n in dsl['workflow']['graph']['nodes'] if n['id'] == 'retrieval')
    assert {'name': 'source_type', 'id': 'source_type', 'comparison_operator': 'is', 'value': 'INTERNAL_CONTROLLED'} in retrieval['metadata_filtering_conditions']['conditions']
    validate = next(n['data'] for n in dsl['workflow']['graph']['nodes'] if n['id'] == 'validate')
    compile(validate['code'], '<inline>', 'exec')
    assert not dsl['workflow']['environment_variables'][0]['value']
