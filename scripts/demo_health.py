"""Print only service PASS/FAIL and non-sensitive diagnostics; no console session."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler

ROOT=Path(__file__).resolve().parents[1]


def configuration(path):
    result={}
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1);result[key.strip()]=value.strip()
    return {**result,**{k:v for k,v in os.environ.items() if k.startswith(('DIFY_','OLLAMA_'))}}


def fetch(url,payload=None,key=None,timeout=15):
    headers={'Content-Type':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    request=Request(url,headers=headers,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None)
    with build_opener(ProxyHandler({})).open(request,timeout=timeout) as response:
        text=response.read(2_000_000).decode()
        return json.loads(text) if response.headers.get('Content-Type','').startswith('application/json') else text


def check(config_path,live=False,state_path=None):
    cfg=configuration(config_path);rows=[]
    def run(name,action,description=''):
        try:
            action();row={'service':name,'status':'PASS','diagnostic':description}
        except Exception as exc:
            row={'service':name,'status':'FAIL','diagnostic':type(exc).__name__+'; check local configuration/service (values withheld)'}
        rows.append(row);print(name,row['status'],row['diagnostic'],flush=True)
    run('Docker Engine',lambda:subprocess.run(['docker','info','--format','{{.ServerVersion}}'],check=True,capture_output=True))
    def container(name):
        data=json.loads(subprocess.run(['docker','inspect',name],check=True,capture_output=True,text=True,encoding='utf-8').stdout)[0]
        assert data['State']['Running']
        if 'Health' in data['State']:assert data['State']['Health']['Status']=='healthy'
    prefix=cfg.get('DIFY_COMPOSE_PROJECT','dify')
    for name in ('api','web','db_postgres','weaviate','plugin_daemon','sandbox'):
        run('Dify '+name,lambda name=name:container(prefix+'-'+name+'-1'),'running; configured container health where available')
    base=cfg.get('DIFY_BASE_URL','http://localhost').rstrip('/')
    run('Dify Web/API',lambda:fetch(base+'/console/api/setup'))
    run('FastAPI MES/ERP/WMS C',lambda:fetch('http://127.0.0.1:18089/health'),'includes SQLite read checks')
    run('FastAPI read-only gateway D',lambda:fetch('http://127.0.0.1:18090/health'),'includes SQLite read checks')
    ollama=cfg.get('OLLAMA_BASE_URL','http://127.0.0.1:11434').rstrip('/')
    run('Ollama',lambda:fetch(ollama+'/api/ps'))
    def embedding():
        result=fetch(ollama+'/api/embed',{'model':'qwen3-embedding:0.6b','input':'企业演示规程预热'},timeout=180)
        assert result['model']=='qwen3-embedding:0.6b' and len(result['embeddings'])==1 and len(result['embeddings'][0])==1024
    run('Qwen3 Embedding',embedding,'actual model call; 1024 dimensions')
    def catalogue():
        key=cfg.get('DIFY_KNOWLEDGE_API_KEY');dataset=cfg.get('DIFY_DATASET_ID')
        assert key and dataset,'configure independent local credentials'
        result=fetch(base+'/v1/datasets/'+dataset+'/documents?page=1&limit=100',key=key)
        assert result['data'] and all(d['indexing_status']=='completed' for d in result['data'])
    run('Knowledge index',catalogue,'documents completed; retrieval separately checked by live E1')
    for stage in ('C','D','E1'):
        def app(stage=stage):
            key=cfg.get('DIFY_'+stage+'_API_KEY');assert key
            fetch(base+'/v1/parameters',key=key)
        run('Published app '+stage,app,'scoped app API credentials accepted')
    product_base=cfg.get('COPILOT_BASE_URL','http://127.0.0.1:18095').rstrip('/')
    def product_page():
        page=fetch(product_base+'/')
        assert isinstance(page,str) and '工域 Copilot' in page
    run('Unified Frontend',product_page,'built Chinese product page')
    def gateway_health():
        health=fetch(product_base+'/api/copilot/health')
        assert health['status']=='ok'
    run('Copilot Gateway',gateway_health,'actual gateway and source read check')
    def router_health():
        assert fetch(product_base+'/api/copilot/router-health')['status']=='ok'
    run('Intent Router',router_health,'safety and missing-object checks')
    if live:
        state=json.loads(Path(state_path or ROOT/'data/demo-state.json').read_text(encoding='utf-8'))
        for stage,field,expected in [('C','analysis_result','no_anomaly'),('D','query_result','verified_read_only'),('E1','qa_result','answered')]:
            def invoke(stage=stage,field=field,expected=expected):
                inputs={'heat_id':state['C']['records']['NORMAL']['heat_id'],'analysis_request':'all'} if stage=='C' else \
                    {'query':'查询炉次 '+state['D']['records']['NORMAL']['heat_id']+' 的MES状态'} if stage=='D' else \
                    {'question':'温度偏差时规程要求检查什么？'}
                result=fetch(base+'/v1/workflows/run',{'inputs':inputs,'response_mode':'blocking','user':'demo-health'},
                    cfg['DIFY_'+stage+'_API_KEY'],timeout=240)
                assert json.loads(result['data']['outputs'][field])['status']==expected
            run('Live Workflow '+stage,invoke,'actual published API; E1 also verifies retrieval/DeepSeek')
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(ROOT/'.env.demo.local'))
    parser.add_argument('--state');parser.add_argument('--live',action='store_true');parser.add_argument('--json-output')
    args=parser.parse_args();rows=check(args.config,args.live,args.state)
    if args.json_output:Path(args.json_output).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if all(r['status']=='PASS' for r in rows) else 1)
