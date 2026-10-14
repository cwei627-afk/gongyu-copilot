"""F2 isolated native retrieval graph with complete official catalog pagination."""
import ast
import copy
from pathlib import Path

from app.copilot.knowledge_workflow import build_expanded_workflow
from app.copilot.knowledge_v2 import engine, FIELDS_V2, REQUEST_WORDS


def build_workflow(dataset_id, manifest):
    dsl = build_expanded_workflow(dataset_id, manifest)
    ns = engine(manifest)
    text = Path(__file__).with_name('knowledge_v2.py').read_text(encoding='utf-8')
    snippets = [ast.get_source_segment(text, node) for node in ast.parse(text).body
                if isinstance(node, ast.FunctionDef) and node.name.startswith('f2_')]
    extension = '\n' + '\n\n'.join(snippets)
    extension += '\nEXTRA_FIELDS=' + repr(FIELDS_V2) + '\nREQUEST_WORDS=' + repr(REQUEST_WORDS)
    extension += '\nqa_begin=f2_begin\nqa_plan=f2_plan\nqa_catalog_view=f2_catalog_view\n'
    extension += '\nSOURCE_SCHEMA=' + repr(ns['SOURCE_SCHEMA']) + '\nQA_SCHEMA=' + repr(ns['QA_SCHEMA']) + '\n'
    graph = dsl['workflow']['graph']
    for node in graph['nodes']:
        data = node['data']
        data['desc'] = 'F2 隔离索引 / 主题范围门禁 / 冻结来源与生成校验'
        if data['type'] == 'code' and node['id'] != 'canary_query':
            split = data['code'].rfind('def main(')
            data['code'] = data['code'][:split] + extension + data['code'][split:]
        if data['type'] == 'knowledge-retrieval':
            data['metadata_filtering_conditions']['conditions'] = [c for c in data['metadata_filtering_conditions']['conditions'] if c['name'] != 'process_stage']
        if node['id'] == 'deepseek':
            data['structured_output']['schema'] = ns['QA_SCHEMA']
    # Each phase reads both pages before checking the full catalog. Page bodies
    # stay HTTP inputs; do not emit a huge concatenated Code-node string.
    if len(manifest['documents']) > 100:
        for first, consumer in [('catalog_http', 'catalog_check'), ('catalog_recheck', 'evidence'), ('catalog_final', 'generation_validate')]:
            one = next(n for n in graph['nodes'] if n['id'] == first)
            two = copy.deepcopy(one)
            two['id'] = first + '_page2'
            two['data']['url'] = two['data']['url'].replace('page=1', 'page=2')
            two['data']['title'] = '完整目录 / 第2页'
            two['position']['y'] += 140
            two['positionAbsolute']['y'] += 140
            graph['nodes'].append(two)
            edge = next(e for e in graph['edges'] if e['source'] == first and e['target'] == consumer)
            edge['target'], edge['id'] = two['id'], first + '-' + two['id']
            edge['data']['targetType'] = 'http-request'
            graph['edges'].append({'id': two['id'] + '-' + consumer, 'type': 'custom', 'source': two['id'], 'target': consumer,
                'sourceHandle': 'source', 'targetHandle': 'target', 'data': {'sourceType': 'http-request', 'targetType': 'code', 'isInIteration': False, 'isInLoop': False}})
            code = next(n['data'] for n in graph['nodes'] if n['id'] == consumer)
            code['variables'] += [{'variable': 'status_two', 'value_selector': [two['id'], 'status_code']},
                                  {'variable': 'body_two', 'value_selector': [two['id'], 'body']}]
            location = code['code'].rfind('def main(')
            head, main = code['code'][:location], code['code'][location:]
            main = main.replace('):\n', ', status_two, body_two):\n', 1)
            main = main.replace('    return ', '    merged = f2_merge_catalog(status_code,body,status_two,body_two)\n    status_code, body = merged["status_code"], merged["body"]\n    return ', 1)
            code['code'] = head + main
    # Controlled concept expansion helps semantic retrieval without granting an
    # LLM authority over evidence or identities; original question is retained.
    terms = {t['id']: ' '.join(t['terms'][:2]) for t in manifest['topics']}
    expand = {'id': 'topic_query', 'type': 'custom', 'position': {'x': 1200, 'y': 160}, 'positionAbsolute': {'x': 1200, 'y': 160},
              'width': 244, 'height': 100, 'sourcePosition': 'right', 'targetPosition': 'left',
              'data': {'type': 'code', 'title': '受控主题扩展 / 原问题保留', 'desc': '只帮助检索，不授予回答权限', 'selected': False,
                       'code_language': 'python3', 'code': 'import json\nTERMS=' + repr(terms) + '\ndef main(previous):\n    p=json.loads(previous)\n    names=[TERMS[k] for k in p["question_kind"].split("|") if k in TERMS]\n    return {"query":" ".join(names)+" "+p["question"]}\n',
                       'variables': [{'variable': 'previous', 'value_selector': ['catalog_check', 'result']}],
                       'outputs': {'query': {'type': 'string', 'children': None}}}}
    graph['nodes'].append(expand)
    edge = next(e for e in graph['edges'] if e['target'] == 'retrieval' and e['source'] == 'canary_branch')
    edge['target'], edge['id'], edge['data']['targetType'] = 'topic_query', 'canary_branch-topic_query', 'code'
    graph['edges'].append({'id': 'topic_query-retrieval', 'type': 'custom', 'source': 'topic_query', 'target': 'retrieval',
                          'sourceHandle': 'source', 'targetHandle': 'target', 'data': {'sourceType': 'code', 'targetType': 'knowledge-retrieval', 'isInIteration': False, 'isInLoop': False}})
    next(n['data'] for n in graph['nodes'] if n['id'] == 'retrieval')['query_variable_selector'] = ['topic_query', 'query']
    dsl['app']['name'] = '工域 Copilot · 企业知识' if manifest['source_type'] == 'INTERNAL_CONTROLLED' else '工域 Copilot · 行业参考'
    dsl['app']['description'] = 'F2独立知识入口；Qwen1024原生检索、完整分页版本门禁、真实hit引用、受控主题覆盖、DeepSeek结构化输出及后验。'
    return dsl
