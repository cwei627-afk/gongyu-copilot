"""Compatible expansion of E1; frozen hit and generation validators remain untouched."""
import copy
import hashlib
import json
import re
import types
from datetime import datetime, timezone

from app.knowledge_qa import nodes as original
from app.analysis.workflow_nodes import controlled_fixture_hit, verify_controlled_hit, timestamp, metadata_epoch
from app.analysis.generation_nodes import GenerationError, strict_json


EXTRA_FIELDS = ('source_type', 'department', 'steel_grade_scope', 'url')


def f_begin(question, request_id, as_of=None):
    result = {'question': question if isinstance(question, str) else '', 'request_id': request_id,
              'as_of': as_of or datetime.now(timezone.utc).isoformat(), 'status': 'pending',
              'code': 'INPUT_VALIDATED', 'citations': [], 'automatic_actions': []}
    try:
        timestamp(result['as_of'])
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError('request')
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            return qa_stop(result, 'INVALID_QUESTION')
        if re.search(r'忽略|跳过|凭经验|预训练|系统提示|system prompt|ignore|假装|编造|<think>|\[cite:', question, re.I):
            return qa_stop(result, 'UNTRUSTED_QUESTION_INSTRUCTION')
        if re.search(r'PLC|自动执行|写入|直接控制|设备控制参数', question, re.I):
            return qa_stop(result, 'READ_ONLY_KNOWLEDGE_ONLY')
        normalized = qa_normalize(question)
        matches = [q for q in MANIFEST['questions'] if normalized in
                   [qa_normalize(alias) for alias in [q['question']] + q.get('aliases', [])]]
        if len(matches) > 1:
            return qa_stop(result, 'AMBIGUOUS_REVIEWED_QUESTION')
        result['question_kind'] = matches[0]['id'] if matches else 'unsupported'
        result['source_type'] = MANIFEST['source_type']
        return qa_packet(result, 'catalog', json.dumps({'model': 'qwen3-embedding:0.6b', 'input': question}, ensure_ascii=False))
    except (ValueError, TypeError):
        result['as_of'] = datetime.now(timezone.utc).isoformat()
        return qa_stop(result, 'INVALID_REQUEST_BINDING', True)


def f_verify(hit, document):
    source, reason = _frozen_verify(hit, document)
    if reason:
        return source, reason
    metadata = hit['metadata']['doc_metadata']
    if any(metadata.get(k) != document.get(k) for k in EXTRA_FIELDS):
        return None, 'SOURCE_TRUST_LAYER_MISMATCH'
    if metadata['source_type'] != MANIFEST['source_type']:
        return None, 'SOURCE_TRUST_LAYER_MISMATCH'
    # These values come directly from the verified retrieval hit, never an LLM.
    source.update({key: metadata[key] for key in EXTRA_FIELDS})
    return source, None


def f_catalog_view(status_code, body, manifest, as_of):
    if status_code != 200:
        raise GenerationError('KNOWLEDGE_CATALOG_FAILURE')
    catalog = strict_json(body)
    entries = catalog['data']
    if not isinstance(entries, list) or catalog.get('has_more') is not False or catalog.get('page') != 1 or catalog.get('total') != len(entries):
        raise GenerationError('INCOMPLETE_KNOWLEDGE_CATALOG')
    controlled = {d['document_id']: d for d in manifest['documents']}
    if len(controlled) != len(manifest['documents']) or set(controlled) != {e['id'] for e in entries}:
        raise ValueError('catalog membership differs from controlled index')
    current, families, signatures, seen = set(), {}, [], set()
    for entry in entries:
        if entry['id'] in seen:
            raise ValueError('duplicate identity')
        seen.add(entry['id'])
        raw = entry['doc_metadata']
        if not isinstance(raw, list):
            raise ValueError('missing metadata')
        meta = {item['name']: item['value'] for item in raw}
        if len(meta) != len(raw):
            raise ValueError('duplicate metadata')
        document = controlled[entry['id']]
        expected = controlled_fixture_hit(document)['metadata']['doc_metadata']
        expected.update({k: document[k] for k in EXTRA_FIELDS})
        if entry['name'] != document['source_file_name'] or any(meta.get(k) != value for k, value in expected.items()):
            raise ValueError('catalog metadata changed or missing')
        signatures.append({k: entry.get(k) for k in ('id', 'name', 'enabled', 'archived', 'indexing_status', 'doc_metadata')})
        start, end = metadata_epoch(meta['effective_from']), metadata_epoch(meta['effective_until'])
        if start >= end or metadata_epoch(meta['effective_date']) != start:
            raise ValueError('invalid dates')
        if entry.get('enabled') is not True or entry.get('archived') is not False:
            continue
        if meta['status'] in ('expired', 'revoked', 'inactive', 'future'):
            continue
        if meta['status'] != 'active' or entry['indexing_status'] != 'completed':
            raise ValueError('source unavailable')
        if not start <= timestamp(as_of).timestamp() < end:
            continue
        if meta['source_type'] != manifest['source_type']:
            raise ValueError('wrong trust layer')
        families.setdefault(meta['controlled_document_name'], []).append(entry['id'])
        current.add(entry['id'])
    if any(len(ids) != 1 for ids in families.values()):
        raise ValueError('VERSION_CONFLICT')
    fingerprint = hashlib.sha256(json.dumps(sorted(signatures, key=lambda s: s['id']), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return current, fingerprint


def f_plan(kind, documents):
    questions = [q for q in MANIFEST['questions'] if q['id'] == kind]
    if len(questions) != 1 or questions[0].get('expected') != 'answered':
        return []
    by_key = {d['chunk_id']: d for d in documents if d['status'] == 'active'}
    return [(by_key[key]['document_id'], quote) for key in questions[0]['source_keys'] for quote in by_key[key]['checks']]


def engine(manifest):
    """Bind inherited functions to an isolated namespace, with no global mutation."""
    ns = dict(original.__dict__)
    ns.update(MANIFEST=manifest, _frozen_verify=verify_controlled_hit, EXTRA_FIELDS=EXTRA_FIELDS)
    internal = manifest['source_type'] == 'INTERNAL_CONTROLLED'
    ns['QA_BOUNDARY'] = ('仅适用于本PoC虚构企业的管理与人工复核资料；不证明任何具体炉次异常，也不定义未提供的工艺参数。' if internal else
                        '以下为公开行业资料参考，不代表本演示企业的正式生产节拍、操作规程或制度标准。')
    ns['QA_HUMAN'] = '生产判断及现场操作须由有权限人员人工确认；本系统只读，不执行设备或PLC控制。'
    source_schema = copy.deepcopy(original.SOURCE_SCHEMA)
    source_schema['properties'].update({k: {'type': 'string'} for k in EXTRA_FIELDS})
    source_schema['properties']['display_name'] = {'type': 'string'}
    source_schema['required'] += list(EXTRA_FIELDS) + ['display_name']
    ns['SOURCE_SCHEMA'] = source_schema
    schema = copy.deepcopy(original.QA_SCHEMA)
    schema['properties']['citations']['items'] = source_schema
    ns['QA_SCHEMA'] = schema
    bindings = {name: value for name, value in original.__dict__.items() if name.startswith('qa_') and callable(value)}
    bindings.update(qa_begin=f_begin, qa_catalog_view=f_catalog_view, qa_plan=f_plan, verify_controlled_hit=f_verify)
    for name, fn in bindings.items():
        ns[name] = types.FunctionType(fn.__code__, ns, name, fn.__defaults__, fn.__closure__)
    return ns
