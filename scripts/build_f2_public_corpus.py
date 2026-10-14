"""Short attributed paraphrases; no downloaded full articles or private material."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets/knowledge_f2/public'
ACCESSED = '2026-10-05'


def build():
    template = json.loads((ROOT / 'assets/public_reference/corpus.json').read_text(encoding='utf-8'))['documents'][0]
    docs, topics, registry = [], [], []
    for line in (DEST / 'sources.tsv').read_text(encoding='utf-8').splitlines():
        title, terms, publisher, url, published, kind, *points = line.split('|')
        # Publisher explicitly excludes AI use; do not ingest its material.
        if publisher == 'ISO':
            continue
        identity = f'P{len(docs)+1:02d}'
        topic = {'id': identity, 'name': title, 'terms': terms.split(';')}
        if title == '转炉时间':
            topic['duration_reference'] = True
        topics.append(topic)
        name = title + '公开参考摘要'
        doc = {**template, 'chunk_id': 'GY-PUBLIC-' + identity, 'topic_id': identity,
               'topic_name': title, 'source_file_name': 'GY-PUBLIC-' + identity + '.md',
               'document_name': name, 'version': ACCESSED, 'effective_date': ACCESSED,
               'effective_from': ACCESSED+'T00:00:00+00:00', 'effective_until':'2030-01-01T00:00:00+00:00',
               'department': publisher, 'publisher': publisher, 'publication_date': published or '未标注',
               'accessed_at': ACCESSED, 'url': url, 'checks': points,
               'knowledge_domain': title, 'document_type': kind, 'applicable_system':'行业参考',
               'risk_level':'非企业标准', 'parent_process':'公开行业背景查询',
               'related_sop':'不适用；不得替代企业SOP', 'applicable_roles':'一般知识查询人员'}
        doc.pop('questions', None)
        doc['content'] = '\n\n'.join([
            name,
            '公开行业参考；以下为有限中文改述，不是原文转载。企业适用边界由本项目明确标注，不冒充发布机构的企业规则。',
            '发布机构：'+publisher+'；原文发布日期：'+(published or '未标注')+'；访问日期：'+ACCESSED+'。',
            '## 主题要点', *points,
            '原始公开来源：'+url,
            '适用边界：仅供一般行业背景理解，不提供本企业实时事实、工艺合格范围或现场设备操作授权。',
            '摘要版本与有效区间表示本项目的收录状态，不表示原始出版物的发布或法定生效时间。'])
        doc['content_sha256'] = hashlib.sha256(doc['content'].encode()).hexdigest()
        docs.append(doc)
        registry.append({'id':identity, 'title':title, 'publisher':publisher, 'url':url,
            'publication_date':published or None, 'accessed_at':ACCESSED, 'type':kind, 'topic':title,
            'summary':points, 'copyright':'保留原作者权利；只保存短篇中文改述与出处，不转载全文。',
            'content_sha256':doc['content_sha256']})
    questions = [{'id':f'F2-P-{i+1:03d}', 'question':'公开资料中'+t['terms'][0]+'有哪些要点？',
                  'expected':'answered', 'topic_ids':[t['id']], 'kind':'direct'} for i,t in enumerate(topics)]
    for topic in topics[:50-len(questions)]:
        questions.append({'id':f'F2-P-{len(questions)+1:03d}', 'question':'一般来说'+topic['terms'][-1]+'是什么？',
                          'expected':'answered', 'topic_ids':[topic['id']], 'kind':'paraphrase'})
    questions[0]['question'] = '一般来说转炉炼钢一炉需要多久？'
    corpus = {'source_type':'PUBLIC_REFERENCE', 'documents':docs, 'topics':topics, 'questions':questions[:1]}
    for doc in docs:
        (DEST/doc['source_file_name']).write_text(doc['content'],encoding='utf-8')
    for filename,value in [('corpus.json',corpus),('questions.json',questions),('source_registry.json',registry)]:
        (DEST/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'documents':len(docs),'questions':len(questions),'publishers':sorted({d['publisher'] for d in docs})},ensure_ascii=False))


if __name__ == '__main__':
    build()
