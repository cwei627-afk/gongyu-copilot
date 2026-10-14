"""Stage E1 deterministic adapters around frozen Stage A/B verification primitives.

Reviewed question aliases and exact source quotes are a finite PoC support map,
not a claim to arbitrary natural-language entailment. No fabricated MES context.
"""
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone

from app.analysis.workflow_nodes import verify_controlled_hit, controlled_fixture_hit, timestamp, metadata_epoch
from app.analysis.generation_nodes import (SOURCE_SCHEMA, TEXT, ID, GenerationError, object_schema,
    validate_schema, strict_json, parse_model_text, stable_id)

QA_POINT = object_schema({'claim_id': ID, 'text': TEXT,
    'citation_ids': {'type': 'array', 'items': ID, 'minItems': 1, 'maxItems': 2}})
QA_SCHEMA = object_schema({'answer': TEXT,
    'supported_points': {'type': 'array', 'items': QA_POINT, 'minItems': 1, 'maxItems': 6},
    'citations': {'type': 'array', 'items': SOURCE_SCHEMA, 'minItems': 1, 'maxItems': 2},
    'applicability': TEXT, 'human_confirmation': TEXT})
QA_BOUNDARY = '仅适用于虚构 DEMO-LINE-A、DEMO-A 钢种的 review 复核阶段；偏差须先由有效 DEMO-RULE-A-REVIEW-v1 确认。本回答不证明任何实际炉次异常，不适用于转炉终点或其他钢种/阶段。'
QA_HUMAN = '只说明企业演示规程原文要求；现场判断和生产操作须由有权限人员人工确认，不执行设备或 PLC 控制。'

QA_ALIASES = {
    'temperature': ['温度偏差时规程要求检查什么', '温度异常时规程要求检查什么',
        'DEMO-A钢种复核阶段温度偏差时规程要求检查什么', '温度不对劲规程让我们核对啥',
        '温度超出标准后有哪些人工核查要求'],
    'chemistry': ['成分偏差时规程要求检查什么', '成分不对劲要核对哪些记录'],
    'roles': ['现行规程对相关岗位的职责有什么要求', '温度和成分偏差分别由谁人工确认'],
    'both': ['温度和成分偏差时规程分别要求检查什么'],
    'partial': ['温度偏差要检查什么以及如何调整设备参数'],
    'missing': ['生产温度记录缺失时应该核查哪些记录'],
}


def qa_normalize(question):
    return re.sub(r'[\s？?，,。.!！：:；;、]', '', question)


def qa_packet(result, state='end', payload=''):
    return {'state': state, 'result': json.dumps(result, ensure_ascii=False, allow_nan=False),
        'payload': payload, 'effective_epoch': timestamp(result['as_of']).timestamp()}


def qa_stop(previous, code, system=False, covered=None):
    result = strict_json(previous) if isinstance(previous, str) else copy.deepcopy(previous)
    result.update(status='system_error' if system else 'abstain', code=code, answer='',
        citations=[], supported_points=[], automatic_actions=[],
        message='系统调用或生成失败，企业规定暂时无法确认。' if system else '没有充分且有效的企业证据，无法确认完整答案；请人工确认或补充适用规程。',
        confirmed_points=covered or [], human_confirmation=QA_HUMAN)
    result.pop('generation', None)
    return qa_packet(result)


def qa_begin(question, request_id, as_of=None):
    result = {'question': question if isinstance(question, str) else '', 'request_id': request_id,
        'as_of': as_of or datetime.now(timezone.utc).isoformat(), 'status': 'pending',
        'code': 'INPUT_VALIDATED', 'citations': [], 'automatic_actions': []}
    try:
        timestamp(result['as_of'])
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128: raise ValueError()
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            return qa_stop(result, 'INVALID_QUESTION')
        if re.search(r'忽略|跳过|行业经验|凭经验|预训练|系统提示|system prompt|ignore|假装|编造|<think>|\[cite:', question, re.I):
            return qa_stop(result, 'UNTRUSTED_QUESTION_INSTRUCTION')
        if re.search(r'PLC|自动执行|写入|直接控制|设备控制参数', question, re.I):
            return qa_stop(result, 'READ_ONLY_KNOWLEDGE_ONLY')
        normalized = qa_normalize(question)
        result['question_kind'] = next((key for key, aliases in QA_ALIASES.items()
            if normalized in [qa_normalize(alias) for alias in aliases]), 'unsupported')
        return qa_packet(result, 'catalog', json.dumps({'model':'qwen3-embedding:0.6b','input':question},ensure_ascii=False))
    except (ValueError, TypeError):
        # Invalid internal time/request binding must not become permissive.
        result['as_of'] = datetime.now(timezone.utc).isoformat()
        return qa_stop(result, 'INVALID_REQUEST_BINDING', True)


def qa_catalog_view(status_code, body, manifest, as_of):
    if status_code != 200: raise GenerationError('KNOWLEDGE_CATALOG_FAILURE')
    catalog = strict_json(body)
    entries = catalog['data']
    if (not isinstance(entries, list) or catalog.get('has_more') is not False
            or catalog.get('page') != 1 or catalog.get('total') != len(entries)):
        raise GenerationError('INCOMPLETE_KNOWLEDGE_CATALOG')
    controlled = {d['document_id']: d for d in manifest['documents']}
    if len(controlled) != len(manifest['documents']): raise ValueError('duplicate registry')
    current, families, signatures, seen = {}, {}, [], set()
    for entry in entries:
        if entry['id'] in seen: raise ValueError('duplicate identity')
        seen.add(entry['id'])
        raw = entry['doc_metadata']
        if not isinstance(raw, list): raise ValueError('metadata missing')
        meta = {item['name']: item['value'] for item in raw}
        if len(meta) != len(raw): raise ValueError('duplicate metadata')
        signatures.append({k: entry.get(k) for k in ('id', 'name', 'enabled', 'archived', 'indexing_status', 'doc_metadata')})
        if entry.get('enabled') is not True or entry.get('archived') is not False: continue
        if meta.get('status') in ('expired', 'revoked', 'inactive', 'future'): continue
        required = ('document_id', 'controlled_document_name', 'source_key', 'status', 'scope', 'version',
            'effective_date', 'effective_from', 'effective_until', 'steel_grade', 'process_stage',
            'rule_id', 'chapter', 'section', 'parameters', 'directions', 'content_sha256')
        if any(meta.get(k) in (None, '') for k in required): raise ValueError('missing metadata')
        start, end = metadata_epoch(meta['effective_from']), metadata_epoch(meta['effective_until'])
        if start >= end or metadata_epoch(meta['effective_date']) != start: raise ValueError('dates')
        if not start <= timestamp(as_of).timestamp() < end: continue
        if meta['status'] != 'active': raise ValueError('status')
        if (meta['scope'], meta['steel_grade'], meta['process_stage']) != ('DEMO-LINE-A', 'DEMO-A', 'review'):
            if entry['id'] in controlled: raise ValueError('controlled scope changed')
            continue
        families.setdefault(meta['controlled_document_name'], []).append(entry['id'])
        current[entry['id']] = (entry, meta)
    if any(len(ids) != 1 for ids in families.values()): raise ValueError('VERSION_CONFLICT')
    for doc_id, (entry, meta) in current.items():
        document = controlled.get(doc_id)
        if not document or entry['indexing_status'] != 'completed': raise ValueError('UNCONTROLLED_CURRENT_SOURCE')
        expected = controlled_fixture_hit(document)['metadata']['doc_metadata']
        if entry['name'] != document['source_file_name'] or any(meta.get(k) != v for k, v in expected.items()):
            raise ValueError('CATALOG_METADATA_MISMATCH')
    fingerprint = hashlib.sha256(json.dumps(sorted(signatures, key=lambda s: s['id']),
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return set(current), fingerprint


def qa_catalog(previous, status_code, body, manifest):
    result = strict_json(previous)
    try:
        _, fingerprint = qa_catalog_view(status_code, body, manifest, result['as_of'])
        result['catalog_fingerprint'] = fingerprint
        return qa_packet(result, 'retrieve')
    except GenerationError as exc: return qa_stop(result, str(exc), True)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return qa_stop(result, 'INVALID_OR_CONFLICTING_CATALOG')


def qa_embedding_health(previous, status_code, body):
    """A real model call prevents swallowed SDK failures becoming 'no evidence'."""
    try:
        if status_code != 200: raise ValueError('embedding transport')
        data = strict_json(body)
        vectors = data['embeddings']
        if data['model'] != 'qwen3-embedding:0.6b' or not isinstance(vectors,list) or len(vectors)!=1:
            raise ValueError('embedding contract')
        vector = vectors[0]
        if not isinstance(vector,list) or len(vector)!=1024 or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):
            raise ValueError('embedding dimension/type')
        return qa_packet(strict_json(previous),'canary')
    except (ValueError,KeyError,TypeError):
        return qa_stop(previous,'EMBEDDING_UNAVAILABLE_OR_INVALID',True)


def qa_retrieval_health(previous, hits, manifest):
    """Independent known-corpus canary, never used as answer evidence/citations."""
    try:
        if not isinstance(hits,list) or not hits: raise ValueError('retrieval unavailable')
        result = strict_json(previous)
        for hit in hits:
            identity = hit['metadata']['document_id']
            docs = [d for d in manifest['documents'] if d['document_id']==identity]
            if len(docs)!=1: raise ValueError('unverified canary')
            source, reason = verify_controlled_hit(hit,docs[0])
            if reason or docs[0]['status']!='active' or not timestamp(docs[0]['effective_from'])<=timestamp(result['as_of'])<timestamp(docs[0]['effective_until']):
                raise ValueError('unverified canary')
        return qa_packet(result,'retrieve')
    except (ValueError,KeyError,TypeError,AttributeError):
        return qa_stop(previous,'KNOWLEDGE_RETRIEVAL_UNAVAILABLE',True)


def qa_plan(kind, documents):
    by_key = {d['chunk_id']: d for d in documents}
    keys = ['temperature'] if kind == 'temperature' else ['chemistry'] if kind == 'chemistry' else ['temperature', 'chemistry'] if kind in ('both', 'roles') else ['temperature'] if kind == 'partial' else []
    plan = []
    for key in keys:
        doc = by_key['DEMO-CHECK-' + key + '-v1']
        quotes = doc['checks'][-1:] if kind == 'roles' else doc['checks']
        for quote in quotes: plan.append((doc['document_id'], quote))
    return plan


def qa_render(points, applicability, human):
    return '\n'.join([p['text'] + ' ' + ' '.join('[cite:' + c + ']' for c in p['citation_ids']) for p in points]
        + [applicability, human])


def qa_evidence(previous, hits, status_code, body, manifest):
    result = strict_json(previous)
    try:
        current, fingerprint = qa_catalog_view(status_code, body, manifest, result['as_of'])
        if fingerprint != result['catalog_fingerprint']: raise ValueError('catalog changed')
        if not isinstance(hits, list): return qa_stop(result, 'INVALID_RETRIEVAL_RESPONSE', True)
        if not hits: return qa_stop(result, 'NO_EVIDENCE')
        verified, source_ids = {}, set()
        for hit in hits:
            identity = hit.get('metadata', {}).get('document_id') if isinstance(hit, dict) else None
            docs = [d for d in manifest['documents'] if d['document_id'] == identity]
            if len(docs) != 1: raise ValueError('uncontrolled retrieval source')
            source, reason = verify_controlled_hit(hit, docs[0])
            if reason or identity not in current or source['segment_id'] in source_ids: raise ValueError(reason or 'inactive/duplicate hit')
            source_ids.add(source['segment_id'])
            verified[identity] = source
        plan = qa_plan(result['question_kind'], manifest['documents'])
        if not plan: return qa_stop(result, 'NO_REVIEWED_DIRECT_SUPPORT')
        covered = [quote for identity, quote in plan if identity in verified and quote in verified[identity]['quote']]
        if len(covered) != len(plan) or result['question_kind'] == 'partial':
            return qa_stop(result, 'INCOMPLETE_DIRECT_SUPPORT', covered=['已有核查要点' ] if covered else [])
        citations, points, by_doc = [], [], {}
        for doc_id, quote in plan:
            source = verified[doc_id]
            if doc_id not in by_doc:
                citation = {k: source[k] for k in SOURCE_SCHEMA['properties'] if k != 'citation_id' and k != 'scope'}
                citation['scope'] = next(h['metadata']['doc_metadata']['scope'] for h in hits if h['metadata']['document_id'] == doc_id)
                citation['citation_id'] = stable_id('cite_', [result['request_id'], source])
                citations.append(citation); by_doc[doc_id] = citation['citation_id']
            points.append({'claim_id': stable_id('qa_', [result['request_id'], doc_id, quote]),
                'text': quote, 'citation_ids': [by_doc[doc_id]]})
        generation = {'answer': qa_render(points, QA_BOUNDARY, QA_HUMAN), 'supported_points': points,
            'citations': citations, 'applicability': QA_BOUNDARY, 'human_confirmation': QA_HUMAN}
        validate_schema(generation, QA_SCHEMA)
        result.update(status='evidence_verified', code='DIRECT_ENTERPRISE_EVIDENCE')
        return qa_packet(result, 'generate', json.dumps(generation, ensure_ascii=False))
    except GenerationError as exc: return qa_stop(result, str(exc), True)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return qa_stop(result, 'UNVERIFIED_OR_INAPPLICABLE_EVIDENCE')


def qa_generation(previous, hits, status_code, body, text, native, finish_reason, reasoning, manifest):
    try:
        rebuilt = qa_evidence(previous, hits, status_code, body, manifest)
        if rebuilt['state'] != 'generate': return rebuilt
        expected = strict_json(rebuilt['payload'])
        if finish_reason not in ('stop', 'end_turn'): return qa_stop(previous, 'GENERATION_TRUNCATED', True)
        output, tagged = parse_model_text(text)
        validate_schema(output, QA_SCHEMA)
        if native is not None:
            validate_schema(native, QA_SCHEMA)
            if native != output: return qa_stop(previous, 'NATIVE_TEXT_MISMATCH', True)
        if not isinstance(reasoning, str): return qa_stop(previous, 'INVALID_REASONING', True)
        if re.search(r'\[cite:|citation_id|cite_[0-9a-f]{32}', reasoning + tagged):
            return qa_stop(previous, 'UNTRUSTED_REASONING_CITATION')
        for key, identifier in [('citations', 'citation_id'), ('supported_points', 'claim_id')]:
            allowed = {item[identifier]: item for item in expected[key]}
            ids = [item[identifier] for item in output[key]]
            if len(set(ids)) != len(ids) or set(ids) != set(allowed): return qa_stop(previous, 'CITATION_OR_CLAIM_COVERAGE')
            if any(item != allowed[item[identifier]] for item in output[key]): return qa_stop(previous, 'GENERATED_EVIDENCE_CHANGED')
        if output['applicability'] != QA_BOUNDARY or output['human_confirmation'] != QA_HUMAN:
            return qa_stop(previous, 'APPLICABILITY_OR_HUMAN_BOUNDARY_CHANGED')
        if output['answer'] != qa_render(output['supported_points'], QA_BOUNDARY, QA_HUMAN):
            return qa_stop(previous, 'ANSWER_EXCEEDS_VERIFIED_EVIDENCE')
        result = strict_json(previous)
        result.update(status='answered', code='VERIFIED_KNOWLEDGE_ANSWER', answer=output['answer'],
            supported_points=copy.deepcopy(output['supported_points']),
            citations=[copy.deepcopy(next(c for c in expected['citations'] if c['citation_id'] == item['citation_id'])) for item in output['citations']],
            applicability=QA_BOUNDARY, human_confirmation=QA_HUMAN, automatic_actions=[])
        return qa_packet(result)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return qa_stop(previous, 'GENERATION_VALIDATION_FAILED', True)
