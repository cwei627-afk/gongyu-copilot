"""Generate a separate native Dify QA adapter; original E1 graph is not changed."""
import ast
import json
from pathlib import Path
from app.knowledge_qa.workflow import build_qa_workflow, inline_source
from app.copilot.knowledge import engine, EXTRA_FIELDS


def build_expanded_workflow(dataset_id, manifest):
    dsl = build_qa_workflow(dataset_id, manifest)
    ns = engine(manifest)
    local = Path(__file__).with_name('knowledge.py').read_text(encoding='utf-8')
    tree = ast.parse(local)
    snippets = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith('f_'):
            snippets.append(ast.get_source_segment(local, node))
    shared = inline_source() + '\n_frozen_verify=verify_controlled_hit\n' + '\n\n'.join(snippets)
    shared += '\nEXTRA_FIELDS=' + repr(EXTRA_FIELDS) + '\nMANIFEST=' + repr(manifest)
    for key in ('QA_BOUNDARY', 'QA_HUMAN', 'SOURCE_SCHEMA', 'QA_SCHEMA'):
        shared += '\n' + key + '=' + repr(ns[key])
    shared += '\nqa_begin=f_begin\nqa_catalog_view=f_catalog_view\nqa_plan=f_plan\nverify_controlled_hit=f_verify\n'
    for node in dsl['workflow']['graph']['nodes']:
        data = node['data']
        data['desc'] = '独立扩容兼容层；冻结身份校验和生成后验'
        if data['type'] == 'code' and node['id'] != 'canary_query':
            data['code'] = shared + '\n' + data['code'][data['code'].rfind('def main('):]
        if node['id'] == 'canary_query':
            data['code'] = "def main():\n    return {'query':" + repr(manifest['questions'][0]['question']) + '}\n'
        if data['type'] == 'knowledge-retrieval':
            conditions = data['metadata_filtering_conditions']['conditions']
            values = {'scope': manifest['documents'][0]['scope'], 'steel_grade': 'DEMO-ALL', 'process_stage': 'management'}
            for condition in conditions:
                if condition['name'] in values:
                    condition['value'] = values[condition['name']]
            conditions.append({'id': 'source_type', 'name': 'source_type', 'comparison_operator': 'is', 'value': manifest['source_type']})
        if node['id'] == 'deepseek':
            data['structured_output']['schema'] = ns['QA_SCHEMA']
    internal = manifest['source_type'] == 'INTERNAL_CONTROLLED'
    dsl['app']['name'] = '制造业Copilot-企业受控知识扩容' if internal else '制造业Copilot-公开行业参考'
    dsl['app']['description'] = '隔离知识索引；真实Qwen检索和来源绑定；正文直接支持；生成后校验；只读人工确认。'
    return dsl
