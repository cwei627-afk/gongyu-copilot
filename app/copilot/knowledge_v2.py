"""Stage F2 bounded topic contracts, not an enumerated question/answer alias table.

Semantic retrieval finds candidates. Deterministic question coverage restricts
which reviewed paragraphs may answer; frozen source and generation checks decide
whether those paragraphs were actually retrieved intact for this request.
"""
import copy
import json
import re
import types
import hashlib
from datetime import datetime, timezone

from app.copilot.knowledge import engine as base_engine, f_begin, f_catalog_view
from app.analysis.generation_nodes import GenerationError, strict_json

FIELDS_V2 = ('source_type', 'department', 'steel_grade_scope', 'url', 'knowledge_domain',
             'document_type', 'applicable_system', 'risk_level', 'parent_process',
             'related_sop', 'applicable_roles', 'publisher', 'publication_date', 'accessed_at')
# Generic request grammar, shared by every topic. It carries no production facts.
REQUEST_WORDS = ('根据', '按照', '请问', '请帮我', '帮我', '能不能', '可以', '应该', '应当', '需要', '必须',
    '我们公司', '本公司', '我们企业', '企业内部', '企业', '公司', '本厂', '我们', '你们', '我想知道', '想了解',
    '一般来说', '一般', '行业公开资料', '行业', '公开资料', '资料', '现行', '正式', '规程', '制度', '规定',
    '有关', '关于', '相关', '分别', '一起', '同时', '告诉我', '说明一下', '解释一下', '简单介绍', '介绍',
    '核对', '核查', '检查', '确认', '管理', '处理', '记录', '留痕', '上报', '职责', '流程', '要点',
    '要求', '原则', '注意事项', '注意', '作用', '含义', '定义', '是什么', '有哪些', '为什么', '如何',
    '怎么办', '怎么做', '怎么', '哪些', '什么', '一下', '说说', '看看', '看什么', '看啥', '核实',
    '和', '与', '及', '或', '的', '了', '呢', '呀', '吗', '啊', '要', '在', '中', '时', '有', '对', '让', '我', '们')


def f2_topics(question):
    value = qa_normalize(question).lower()
    # Numeric values, comparisons with missing company standards and equipment
    # actions are not supported by the management-level topic contracts.
    if re.search(r'多少|多久|几分钟|几度|百分之|调节|调到|设定|加多少|减多少|行业平均|更快|更慢|最优|保证|预测|结论|是否合格', value):
        # Public duration is a separately reviewed reference topic, not a threshold.
        if not (MANIFEST['source_type'] == 'PUBLIC_REFERENCE' and re.fullmatch(r'.*(?:转炉|炼钢).*(?:多久|几分钟).*', value)):
            return []
    candidates = []
    for topic in MANIFEST['topics']:
        for term in topic['terms']:
            needle = qa_normalize(term).lower()
            for match in re.finditer(re.escape(needle), value):
                candidates.append((match.start(), match.end(), topic['id']))
    chosen, occupied = [], set()
    for start, end, identity in sorted(candidates, key=lambda item: item[1]-item[0], reverse=True):
        positions = set(range(start, end))
        if positions & occupied:
            continue
        chosen.append(identity); occupied |= positions
    selected = list(dict.fromkeys(chosen))
    if not 1 <= len(selected) <= 2:
        return []
    remainder = ''.join(ch for index, ch in enumerate(value) if index not in occupied)
    for word in sorted(REQUEST_WORDS, key=len, reverse=True):
        remainder = remainder.replace(word.lower(), '')
    if MANIFEST['source_type'] == 'PUBLIC_REFERENCE' and any(t['id'] in selected and t.get('duration_reference') for t in MANIFEST['topics']):
        for word in ('一炉', '生产', '需要', '多久', '几分钟', '通常'):
            remainder = remainder.replace(word, '')
    # No opaque leftover noun or extra subquestion is silently discarded.
    if re.sub(r'[（）()\-/]', '', remainder):
        return []
    return selected


def f2_begin(question, request_id, as_of=None):
    previous = {'question': question if isinstance(question, str) else '', 'request_id': request_id,
                'as_of': as_of or datetime.now(timezone.utc).isoformat(), 'status': 'pending',
                'code': 'INPUT_VALIDATED', 'citations': [], 'automatic_actions': []}
    try:
        timestamp(previous['as_of'])
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError('request')
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            return qa_stop(previous, 'INVALID_QUESTION')
        if re.search(r'忽略|跳过|凭经验|预训练|系统提示|system prompt|ignore|假装|编造|<think>|\[cite:', question, re.I):
            return qa_stop(previous, 'UNTRUSTED_QUESTION_INSTRUCTION')
        if re.search(r'自动执行|直接控制|设备控制参数|(?:调整|写入|修改).*PLC', question, re.I):
            return qa_stop(previous, 'READ_ONLY_KNOWLEDGE_ONLY')
        topics = f2_topics(question)
        previous['question_kind'] = '|'.join(topics) if topics else 'unsupported'
        previous['source_type'] = MANIFEST['source_type']
        return qa_packet(previous, 'catalog', json.dumps({'model': 'qwen3-embedding:0.6b', 'input': question}, ensure_ascii=False))
    except (ValueError, TypeError):
        previous['as_of'] = datetime.now(timezone.utc).isoformat()
        return qa_stop(previous, 'INVALID_REQUEST_BINDING', True)


def f2_plan(kind, documents):
    keys = kind.split('|')
    topics = {topic['id']: topic for topic in MANIFEST['topics']}
    if not 1 <= len(keys) <= 2 or any(key not in topics for key in keys):
        return []
    plan = []
    for key in keys:
        found = [doc for doc in documents if doc['topic_id'] == key and doc['status'] == 'active']
        if len(found) != 1:
            return []
        plan.extend((found[0]['document_id'], quote) for quote in found[0]['checks'])
    return plan


def f2_catalog_view(status_code, body, manifest, as_of):
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
        if meta['status'] in ('expired', 'retired', 'revoked', 'inactive', 'future'):
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


def f2_merge_catalog(status_one, body_one, status_two, body_two):
    """Two explicit official API pages; no missing/duplicate/changed totals."""
    try:
        if status_one != 200 or status_two != 200:
            raise GenerationError('KNOWLEDGE_CATALOG_FAILURE')
        one, two = strict_json(body_one), strict_json(body_two)
        if (one['page'] != 1 or two['page'] != 2 or one['total'] != two['total']
                or not 100 < one['total'] <= 200 or one['has_more'] is not True
                or two['has_more'] is not False or len(one['data']) != 100
                or len(one['data']) + len(two['data']) != one['total']):
            raise ValueError('incomplete pagination')
        combined = one['data'] + two['data']
        if len({row['id'] for row in combined}) != len(combined):
            raise ValueError('duplicate page identity')
        return {'status_code': 200, 'body': json.dumps({'page': 1, 'total': len(combined), 'has_more': False, 'data': combined}, ensure_ascii=False)}
    except (ValueError, KeyError, TypeError):
        return {'status_code': 503, 'body': '{}'}


def engine(manifest):
    ns = base_engine(manifest)
    ns.update(FIELDS_V2=FIELDS_V2, EXTRA_FIELDS=FIELDS_V2, REQUEST_WORDS=REQUEST_WORDS,
              f_begin=f_begin, f_catalog_view=f_catalog_view)
    # Bind adapters to this isolated namespace, leaving Stage F / E1 untouched.
    for name, fn in [('f_begin', f_begin), ('f_catalog_view', f_catalog_view), ('f2_topics', f2_topics),
                     ('qa_begin', f2_begin), ('qa_plan', f2_plan), ('qa_catalog_view', f2_catalog_view)]:
        ns[name] = types.FunctionType(fn.__code__, ns, name, fn.__defaults__, fn.__closure__)
    for field in FIELDS_V2:
        ns['SOURCE_SCHEMA']['properties'][field] = {'type': 'string'}
        if field not in ns['SOURCE_SCHEMA']['required']:
            ns['SOURCE_SCHEMA']['required'].append(field)
    ns['QA_SCHEMA']['properties']['citations']['items'] = ns['SOURCE_SCHEMA']
    return ns
