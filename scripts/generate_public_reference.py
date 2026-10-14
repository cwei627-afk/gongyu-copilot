"""Short original paraphrases of primary public sources; not company standards."""
import json
from pathlib import Path
from generate_knowledge_corpus import document

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ('F-PUBLIC-01', '转炉时间公开参考摘要', 'World Steel Association',
     'https://worldsteel.org/about-steel/steel-story/', None,
     ['worldsteel的历史介绍列举现代转炉可将最多350吨铁料在不足40分钟内转为钢的例子。',
      '这个公开例子不是所有钢种和工厂的完整生产周期，不能作为本演示企业的合格时长标准。'],
     ['一般来说转炉炼钢一炉需要多久？', '公开资料如何描述现代转炉的炼钢时间？']),
    ('F-PUBLIC-02', '炼钢路线与回收公开参考摘要', 'World Steel Association',
     'https://worldsteel.org/about-steel/what-is%20steel/', None,
     ['worldsteel介绍高炉—转炉和电弧炉两类主要炼钢路线；路线的原料与供能方式存在差别。',
      '电弧炉主要使用回收钢和电力，按工厂条件也可使用直接还原铁或铁水。',
      '钢可以反复回收利用；这些一般性介绍不提供本企业任何炉次状态或物料配方。'],
     ['行业中主要有哪些炼钢路线？', '一般电弧炉主要使用什么原料和能源？', '公开资料中电弧炉可以用直接还原铁吗？', '行业中钢可以重复回收吗？']),
    ('F-PUBLIC-03', '钢铁制造流程公开参考摘要', 'World Steel Association',
     'https://worldsteel.org/wp-content/uploads/steelmaking-process.pdf', None,
     ['worldsteel流程图展示原料准备、炼铁、炼钢、精炼、连铸、热轧和后续精整等生产环节。',
      '图中连铸位于炼钢和精炼之后、热轧之前，示意产品包含方坯和板坯等半成品。',
      '流程图将炉渣列为副产品，并示意水泥与骨料等用途；不代表任何具体炉渣批次获得使用许可。'],
     ['公开资料中钢铁制造有哪些环节？', '行业流程图中连铸位于哪个阶段？', '公开资料中炉渣有哪些示意用途？']),
    ('F-PUBLIC-04', 'MES作用与系统协同公开案例摘要', '国家市场监督管理总局计量司',
     'https://www.samr.gov.cn/jls/zt/jlfwzxqy/qyal/art/2023/art_28a057a295d14e99a5acd959f59d1c2a.html', '2020-09-08',
     ['市场监管总局的公开案例把MES描述为面向车间执行层的生产信息化管理系统，涉及生产、质量和制造数据等管理。',
      '案例说明实时信息采集与反馈有助于制造过程透明化，并介绍MES、ERP和PLM的信息协同。',
      '该案例来自特种计算机制造，不是钢厂内部SOP，也不能证明本演示企业某个对象的数据或绩效。'],
     ['行业中MES的作用是什么？', '公开制造业案例中MES和ERP如何协同？']),
]


def main():
    folder = ROOT / 'assets/public_reference'; (folder / 'documents').mkdir(parents=True, exist_ok=True)
    docs, records, questions = [], [], []
    for code, title, publisher, url, published, checks, qs in SOURCES:
        text = title + '\n\n来源类型：公开行业参考。以下为经核对的简短中文改述，不是原文转载，不代表企业制度。\n\n' + '\n\n'.join(checks)
        text += '\n\n原始公开来源：' + url + '\n访问日期：2026-10-03。适用边界：仅供一般行业知识参考；不用于企业规则和设备控制。'
        doc = document(code, title, qs[0], publisher, checks, 'PUBLIC_REFERENCE', version='2026-10-03', content=text)
        doc.update(url=url, chapter='公开资料改述摘要', section='主题要点', questions=qs)
        docs.append(doc)
        records.append({'title': title, 'publisher': publisher, 'url': url, 'accessed_at': '2026-10-03',
                        'publication_date': published, 'source_type': 'PUBLIC_REFERENCE',
                        'copyright_or_access_note': '无需登录的官方公开页面或流程图；保留原站权利，仅索引简短原创中文改述，不复制全文。',
                        'content_sha256': doc['content_sha256'], 'hash_basis': 'indexed_original_chinese_summary', 'source_key': code})
        (folder / 'documents' / doc['source_file_name']).write_text(text, encoding='utf-8')
        questions += [{'id': f'F-PUBLIC-Q{len(questions)+i+1:02}', 'question': q, 'source_keys': [code], 'expected': 'answered'} for i, q in enumerate(qs)]
    (folder / 'corpus.json').write_text(json.dumps({'source_type': 'PUBLIC_REFERENCE', 'documents': docs}, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'questions.json').write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'source_registry.json').write_text(json.dumps({'sources': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Public primary sources:', len(docs), 'reviewed questions:', len(questions))


if __name__ == '__main__':
    main()
