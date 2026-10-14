"""Independent native Dify RAG Workflow, reusing frozen verification source."""
import ast
import json
from pathlib import Path
from app.knowledge_qa.nodes import QA_SCHEMA


def inline_source():
    root = Path(__file__).resolve().parents[1]
    local = (root / 'knowledge_qa/nodes.py').read_text(encoding='utf-8')
    lines = local.splitlines(keepends=True)
    for node in reversed(ast.parse(local).body):
        if isinstance(node, ast.ImportFrom) and node.module.startswith('app.'):
            del lines[node.lineno-1:node.end_lineno]
    return ((root / 'analysis/workflow_nodes.py').read_text(encoding='utf-8') + '\n'
        + (root / 'analysis/generation_nodes.py').read_text(encoding='utf-8') + '\n' + ''.join(lines))


def build_qa_workflow(dataset_id, manifest, knowledge_url='http://api:5001/v1'):
    nodes, edges = [], []
    shared = inline_source() + '\nMANIFEST=' + repr(manifest) + '\n'
    def add(identity, kind, title, **data):
        pos = {'x': len(nodes)*280, 'y': 0}
        nodes.append({'id': identity, 'type': 'custom', 'position': pos, 'positionAbsolute': pos,
            'width': 244, 'height': 100, 'sourcePosition': 'right', 'targetPosition': 'left',
            'data': {'type': kind, 'title': title, 'desc': 'Stage E1', 'selected': False, **data}})
    def edge(a, b, handle='source'):
        types = {n['id']: n['data']['type'] for n in nodes}
        edges.append({'id': a+'-'+handle+'-'+b, 'type': 'custom', 'source': a, 'target': b,
            'sourceHandle': handle, 'targetHandle': 'target', 'data': {'sourceType': types[a],
                'targetType': types[b], 'isInIteration': False, 'isInLoop': False}})
    def code(identity, title, call, variables):
        add(identity, 'code', title, code_language='python3',
            code=shared+'\ndef main('+', '.join(variables)+'):\n    return '+call+'\n',
            variables=[{'variable': k, 'value_selector': v} for k,v in variables.items()],
            outputs={k: {'type': t, 'children': None} for k,t in
                [('state','string'),('result','string'),('payload','string'),('effective_epoch','number')]})
    def branch(identity, previous, state):
        add(identity, 'if-else', '仅门禁通过继续', cases=[{'case_id': 'true', 'logical_operator': 'and',
            'conditions': [{'id': identity+'-gate', 'variable_selector': [previous,'state'],
                'comparison_operator': 'is', 'value': state, 'varType': 'string'}]}])
    def end(identity, previous):
        add(identity, 'end', '仅返回经过验证的知识答案',
            outputs=[{'variable':'qa_result','value_selector':[previous,'result'],'value_type':'string'}])
    def catalog(identity):
        add(identity, 'http-request', '正式完整目录 / 有效版本', method='get',
            url=knowledge_url+f'/datasets/{dataset_id}/documents?page=1&limit=100',
            headers='Authorization:Bearer {{#env.KNOWLEDGE_API_KEY#}}', params='', variables=[],
            authorization={'type':'no-auth','config':None}, body={'type':'none','data':[]},
            ssl_verify=True, timeout={'connect':5,'read':15,'write':5},
            retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':100})
    add('start','start','企业知识问题（无需炉次号）',variables=[{'variable':'question','label':'知识问题',
        'type':'paragraph','required':True,'max_length':1000,'options':[]}])
    code('validate','输入范围与请求身份', 'qa_begin(question,request_id)',
        {'question':['start','question'],'request_id':['sys','workflow_run_id']})
    branch('input_branch','validate','catalog'); end('input_end','validate')
    catalog('catalog_http')
    code('catalog_check','真实目录版本门禁','qa_catalog(previous,status_code,body,MANIFEST)',
        {'previous':['validate','result'],'status_code':['catalog_http','status_code'],'body':['catalog_http','body']})
    branch('catalog_branch','catalog_check','retrieve'); end('catalog_end','catalog_check')
    add('embedding_http','http-request','实际 Qwen Embedding 健康门禁',method='post',
        url='http://host.docker.internal:11434/api/embed',headers='Content-Type:application/json',params='',variables=[],
        authorization={'type':'no-auth','config':None},body={'type':'json','data':[{'id':'embedding-body','type':'text','key':'','value':'{{#validate.payload#}}'}]},
        ssl_verify=True,timeout={'connect':5,'read':60,'write':5},
        retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':100})
    code('embedding_check','模型身份 / 1024维 / 有限数值', 'qa_embedding_health(previous,status_code,body)',
        {'previous':['catalog_check','result'],'status_code':['embedding_http','status_code'],'body':['embedding_http','body']})
    branch('embedding_branch','embedding_check','canary');end('embedding_end','embedding_check')
    conditions = [{'id': name,'name':name,'comparison_operator':'is','value': value} for name,value in
        [('status','active'),('scope','DEMO-LINE-A'),('steel_grade','DEMO-A'),('process_stage','review')]]
    conditions += [{'id':name,'name':name,'comparison_operator':op,'value':'{{#validate.effective_epoch#}}'}
        for name,op in [('effective_from','≤'),('effective_until','>')]]
    conditions += [{'id': name,'name':name,'comparison_operator':'not empty','value':None}
        for name in ['document_id','version','effective_date','chapter','section','content_sha256']]
    add('retrieval','knowledge-retrieval','Qwen 原生检索 / 当前有效 metadata',
        query_variable_selector=['start','question'],query_attachment_selector=[],dataset_ids=[dataset_id],
        retrieval_mode='multiple',multiple_retrieval_config={'top_k':8,'score_threshold':None,
            'reranking_enable':False,'reranking_mode':'reranking_model'},
        metadata_filtering_mode='manual',metadata_filtering_conditions={'logical_operator':'and','conditions':conditions},
        error_strategy='fail-branch',retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':100})
    canary=next(n for n in nodes if n['id']=='retrieval')
    data={k:v for k,v in canary['data'].items() if k not in ('type','title','desc','selected')}
    data=json.loads(json.dumps(data));data['query_variable_selector']=['canary_query','query']
    add('canary','knowledge-retrieval','检索健康探针：不得用于回答或 Citation',**data)
    add('canary_query','code','固定受控知识检索探针',code_language='python3',
        code="def main():\n    return {'query':'DEMO-A review 核对温度采集记录与测量时间及成分报告'}\n",variables=[],
        outputs={'query':{'type':'string','children':None}})
    code('canary_check','探针来源身份和有效性','qa_retrieval_health(previous,hits,MANIFEST)',
        {'previous':['catalog_check','result'],'hits':['canary','result']})
    branch('canary_branch','canary_check','retrieve');end('canary_end','canary_check')
    catalog('catalog_recheck')
    code('evidence','真实来源 + 正文直接支持 + 完整覆盖',
        'qa_evidence(previous,hits,status_code,body,MANIFEST)',
        {'previous':['catalog_check','result'],'hits':['retrieval','result'],
            'status_code':['catalog_recheck','status_code'],'body':['catalog_recheck','body']})
    branch('evidence_branch','evidence','generate'); end('abstain_end','evidence')
    add('deepseek','llm','仅已验证知识原文的结构化组织',
        model={'provider':'langgenius/deepseek/deepseek','name':'deepseek-flash','mode':'chat',
            'completion_params':{'thinking':False,'temperature':0.1,'max_tokens':8192,'response_format':'json_object'}},
        prompt_template=[{'role':'system','text':'你只整理通过企业证据门禁的原文。输出严格JSON，全部字段与材料逐字一致，保持列表原顺序。直接复制输入的answer字段，不合并行、不替换换行、不改写。每一条supported_points原文加对应[cite:citation_id]占一行，任意两条之间必须是换行符；最后applicability和human_confirmation各占一行。JSON字符串内换行必须编码为\\n，不能替换为空格。保留全部supported_points/citations和原文/ID/metadata/hash。禁止增加行业知识、制度、设备参数、来源或动作。不要think、Markdown或JSON外解释。'},
            {'role':'user','text':'仅组织以下可信材料，返回JSON：\n{{#evidence.payload#}}'}],
        context={'enabled':False,'variable_selector':[]},vision={'enabled':False},
        structured_output_enabled=True,structured_output={'schema':QA_SCHEMA},reasoning_format='separated',
        error_strategy='fail-branch',retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':100})
    catalog('catalog_final')
    code('generation_validate','JSON + 事实/条件 + hit绑定 Citation 后验',
        'qa_generation(previous,hits,status_code,body,text,native,finish_reason,reasoning,MANIFEST)',
        {'previous':['catalog_check','result'],'hits':['retrieval','result'],
            'status_code':['catalog_final','status_code'],'body':['catalog_final','body'],
            'text':['deepseek','text'],'native':['deepseek','structured_output'],
            'finish_reason':['deepseek','finish_reason'],'reasoning':['deepseek','reasoning_content']})
    end('answer_end','generation_validate')
    for origin,previous,code_value in [('retrieval','catalog_check','RETRIEVAL_FAILED'),('canary','catalog_check','RETRIEVAL_FAILED'),('deepseek','evidence','PROVIDER_FAILED')]:
        code(origin+'_failure','系统失败，不是假无知识',f'qa_stop(previous,{code_value!r},True)',{'previous':[previous,'result']})
        end(origin+'_failure_end',origin+'_failure')
        edge(origin,origin+'_failure','fail-branch');edge(origin+'_failure',origin+'_failure_end')
    for a,b,h in [('start','validate','source'),('validate','input_branch','source'),
        ('input_branch','input_end','false'),('input_branch','catalog_http','true'),('catalog_http','catalog_check','source'),
        ('catalog_check','catalog_branch','source'),('catalog_branch','catalog_end','false'),('catalog_branch','embedding_http','true'),
        ('embedding_http','embedding_check','source'),('embedding_check','embedding_branch','source'),('embedding_branch','embedding_end','false'),
        ('embedding_branch','canary_query','true'),('canary_query','canary','source'),('canary','canary_check','source'),
        ('canary_check','canary_branch','source'),('canary_branch','canary_end','false'),('canary_branch','retrieval','true'),
        ('retrieval','catalog_recheck','source'),('catalog_recheck','evidence','source'),('evidence','evidence_branch','source'),
        ('evidence_branch','abstain_end','false'),('evidence_branch','deepseek','true'),('deepseek','catalog_final','source'),
        ('catalog_final','generation_validate','source'),('generation_validate','answer_end','source')]: edge(a,b,h)
    return {'version':'0.7.0','kind':'app','dependencies':[],
        'app':{'name':'制造业Copilot-StageE1-企业知识问答','mode':'workflow','icon':'📚','icon_background':'#E4FBCC',
            'description':'独立单轮有限RAG；真实Qwen检索、Evidence First、DeepSeek、来源/生成后验；人工确认。','use_icon_as_answer_icon':False},
        'workflow':{'conversation_variables':[], 'environment_variables':[{'id':'3edc8a00-30d0-4000-8000-000000000005',
            'name':'KNOWLEDGE_API_KEY','value':'','value_type':'secret','selector':['env','KNOWLEDGE_API_KEY']}],
            'features':{'file_upload':{'enabled':False},'retriever_resource':{'enabled':False}},
            'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':0,'y':0,'zoom':0.4}}}}
