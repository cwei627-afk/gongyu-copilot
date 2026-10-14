"""F2 controlled fixture tests, explicitly distinct from Dify live validation."""
import copy
import json
from pathlib import Path

import pytest

from app.analysis.workflow_nodes import controlled_fixture_hit
from app.copilot.knowledge_v2 import engine, FIELDS_V2, f2_merge_catalog
from app.copilot.knowledge_workflow_v2 import build_workflow

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'assets/knowledge_f2/internal'
QUESTIONS = json.loads((CORPUS / 'questions.json').read_text(encoding='utf-8'))
UNSUPPORTED = json.loads((CORPUS / 'unsupported_questions.json').read_text(encoding='utf-8'))
NOW = '2026-10-05T06:00:00+00:00'


@pytest.fixture(scope='module')
def index():
    manifest = json.loads((CORPUS / 'corpus.json').read_text(encoding='utf-8'))
    entries, hits = [], {}
    for doc in manifest['documents']:
        doc.update(document_id='f2-doc-' + doc['chunk_id'], segment_id='f2-seg-' + doc['chunk_id'], dataset_id='f2-fixture')
        hit = controlled_fixture_hit(doc)
        hit['metadata']['doc_metadata'].update({k: doc[k] for k in FIELDS_V2})
        entries.append({'id':doc['document_id'], 'name':doc['source_file_name'], 'enabled':True, 'archived':False,
                        'indexing_status':'completed', 'doc_metadata':[{'name':k,'value':v} for k,v in hit['metadata']['doc_metadata'].items()]})
        if doc['status'] == 'active':
            hits[doc['topic_id']] = hit
    body = json.dumps({'page':1,'data':entries,'total':len(entries),'has_more':False},ensure_ascii=False)
    return manifest, engine(manifest), body, hits


def pre(index, question):
    manifest, ns, body, _ = index
    return ns['qa_catalog'](ns['qa_begin'](question,'f2-fixture-request',NOW)['result'],200,body,manifest)


@pytest.mark.parametrize('question', QUESTIONS, ids=[q['id'] for q in QUESTIONS])
def test_reviewed_question_needs_actual_hits(index, question):
    manifest, ns, body, hits = index
    previous = pre(index,question['question'])
    selected = [hits[key] for key in question['topic_ids']]
    evidence = ns['qa_evidence'](previous['result'],selected,200,body,manifest)
    assert evidence['state']=='generate', json.loads(evidence['result'])
    payload = json.loads(evidence['payload'])
    result = json.loads(ns['qa_generation'](previous['result'],selected,200,body,json.dumps(payload),payload,'stop','',manifest)['result'])
    assert result['status']=='answered' and len(result['citations'])==len(question['topic_ids'])
    assert {c['document_id'] for c in result['citations']}=={h['metadata']['document_id'] for h in selected}
    assert all(c['source_type']=='INTERNAL_CONTROLLED' and c['page'] is None for c in result['citations'])


@pytest.mark.parametrize('question', UNSUPPORTED, ids=[q['id'] for q in UNSUPPORTED])
def test_unsupported_or_partial_question_abstains_despite_similar_hits(index,question):
    manifest, ns, body, hits = index
    previous = pre(index,question['question'])
    result = json.loads(ns['qa_evidence'](previous['result'],list(hits.values())[:8],200,body,manifest)['result'])
    assert result['status']=='abstain' and not result['citations'] and not result['answer']


@pytest.mark.parametrize('field,value',[('document_id','WRONG'),('segment_id','WRONG'),('version','revoked'),
    ('scope','OTHER'),('content_sha256','0'*64),('source_type','PUBLIC_REFERENCE'),('knowledge_domain','OTHER'),
    ('department','OTHER'),('applicable_system','OTHER'),('publisher','OTHER')])
def test_frozen_source_binding_extended_metadata(index,field,value):
    manifest, ns, body, hits = index
    hit=copy.deepcopy(hits['A01'])
    target=hit['metadata'] if field in ('document_id','segment_id') else hit['metadata']['doc_metadata']
    target[field]=value
    result=json.loads(ns['qa_evidence'](pre(index,QUESTIONS[0]['question'])['result'],[hit],200,body,manifest)['result'])
    assert result['status']=='abstain' and not result['citations']


@pytest.mark.parametrize('status',['retired','revoked','future'])
def test_inactive_hit_cannot_support_same_topic(index,status):
    manifest, ns, body, _ = index
    doc=next(d for d in manifest['documents'] if d['status']==status)
    hit=controlled_fixture_hit(doc)
    hit['metadata']['doc_metadata'].update({k:doc[k] for k in FIELDS_V2})
    question='企业'+doc['topic_name']+'有哪些核对要求？'
    result=json.loads(ns['qa_evidence'](pre(index,question)['result'],[hit],200,body,manifest)['result'])
    assert result['status']=='abstain' and not result['citations']


def test_question_list_not_used_for_runtime_answer_permission(index):
    manifest, _, _, _ = index
    other=copy.deepcopy(manifest)
    other['questions']=[]
    ns=engine(other)
    assert ns['f2_topics']('请帮我说说企业交接班的核实要求呀？')==['A07']
    assert ns['f2_topics']('交接班的要求和火星炉的维修方法是什么？')==[]


def test_full_catalog_pagination_and_fail_closed(index):
    entries=json.loads(index[2])['data']
    one={'page':1,'total':len(entries),'has_more':True,'data':entries[:100]}
    two={'page':2,'total':len(entries),'has_more':False,'data':entries[100:]}
    merged=f2_merge_catalog(200,json.dumps(one),200,json.dumps(two))
    assert merged['status_code']==200 and len(json.loads(merged['body'])['data'])==140
    for mutation in ('missing','duplicate','total','page','status'):
        changed=copy.deepcopy(two)
        if mutation=='missing': changed['data'].pop()
        if mutation=='duplicate': changed['data'][0]=one['data'][0]
        if mutation=='total': changed['total']+=1
        if mutation=='page': changed['page']=3
        assert f2_merge_catalog(200,json.dumps(one),500 if mutation=='status' else 200,json.dumps(changed))['status_code']==503


def test_workflow_three_full_catalog_checks_and_topic_expansion(index):
    dsl=build_workflow('f2-fixture',index[0])
    nodes=dsl['workflow']['graph']['nodes']
    assert len([n for n in nodes if n['id'].endswith('_page2')])==3
    assert next(n['data'] for n in nodes if n['id']=='retrieval')['query_variable_selector']==['topic_query','query']
    for node in nodes:
        if node['data']['type']=='code': compile(node['data']['code'],'<F2 DSL>','exec')
    assert dsl['workflow']['environment_variables'][0]['value']==''


PUBLIC = ROOT / 'assets/knowledge_f2/public'
PUBLIC_QUESTIONS = json.loads((PUBLIC / 'questions.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def public_index():
    manifest=json.loads((PUBLIC/'corpus.json').read_text(encoding='utf-8'))
    entries,hits=[],{}
    for doc in manifest['documents']:
        doc.update(document_id='pub-doc-'+doc['chunk_id'], segment_id='pub-seg-'+doc['chunk_id'],dataset_id='pub-fixture')
        hit=controlled_fixture_hit(doc)
        hit['metadata']['doc_metadata'].update({k:doc[k] for k in FIELDS_V2})
        entries.append({'id':doc['document_id'],'name':doc['source_file_name'],'enabled':True,'archived':False,
                        'indexing_status':'completed','doc_metadata':[{'name':k,'value':v} for k,v in hit['metadata']['doc_metadata'].items()]})
        hits[doc['topic_id']]=hit
    return manifest,engine(manifest),json.dumps({'page':1,'data':entries,'total':len(entries),'has_more':False}),hits


@pytest.mark.parametrize('question',PUBLIC_QUESTIONS,ids=[q['id'] for q in PUBLIC_QUESTIONS])
def test_public_questions_verified_hit_only(public_index,question):
    manifest,ns,body,hits=public_index
    previous=pre(public_index,question['question'])
    selected=[hits[k] for k in question['topic_ids']]
    evidence=ns['qa_evidence'](previous['result'],selected,200,body,manifest)
    assert evidence['state']=='generate',json.loads(evidence['result'])
    payload=json.loads(evidence['payload'])
    final=json.loads(ns['qa_generation'](previous['result'],selected,200,body,json.dumps(payload),payload,'stop','',manifest)['result'])
    assert final['status']=='answered' and final['citations']
    assert all(c['source_type']=='PUBLIC_REFERENCE' and c['url'].startswith('https://') for c in final['citations'])


def test_public_reference_cannot_answer_company_threshold(public_index):
    manifest,ns,body,hits=public_index
    previous=pre(public_index,'我们公司的转炉炼钢标准时长是多少？')
    result=json.loads(ns['qa_evidence'](previous['result'],list(hits.values()),200,body,manifest)['result'])
    assert result['status']=='abstain' and not result['citations']
