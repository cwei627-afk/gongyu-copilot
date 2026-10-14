"""Insert a named set of NEW fictional demonstration rows; never refresh old facts.

The named run is idempotent. Reusing an expired run does not make it fresh; choose
a new run label explicitly. Run locally with MOCK_DATA_DIR or inside Mock Docker.
"""
import argparse
import json
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import data_directory
from app.enterprise.seed_demo import seed_demo


def prepare_demo(directory, run_label, now=None):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,40}', run_label):
        raise ValueError('run label must be 1-40 ASCII letters/digits/hyphens')
    directory = Path(directory)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('timezone required')
    state_path = directory / ('delivery-' + run_label + '.json')
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        # Idempotence is deliberate; do not write timestamps or repair source rows.
        return {**state, 'reused': True,
                'fresh': timedelta(0) <= now-datetime.fromisoformat(state['created_at']) < timedelta(hours=6)}
    seed_demo(directory, now)
    definitions = [('NORMAL',1580,.18,150),('HIGH',1610,.18,150),('BOTH',1610,.30,150),
        ('SHORTAGE',1610,.18,50),('ZERO',1610,.18,0),('MISSING',None,.18,150),
        ('NO-RULE',1580,.18,150),('NO-SOP',1610,.18,150),
        ('ERP-CONFLICT',1580,.18,150),('WMS-CONFLICT',1580,.18,150),
        ('VERSION',1580,.18,150),('STALE',1580,.18,150),('MISSING-MES',1580,.18,150)]
    created = now.isoformat()
    records = {}
    for label,temperature,carbon,quantity in definitions:
        heat = 'E2-' + run_label + '-' + label
        order = 'ORDER-' + secrets.token_hex(6)
        batch = 'LOT-' + secrets.token_hex(6)
        grade = '' if label=='MISSING-MES' else 'DEMO-UNKNOWN' if label=='NO-RULE' else 'DEMO-E2-NO-SOP-'+run_label if label=='NO-SOP' else 'DEMO-A'
        link = {'heat_id':heat,'production_order_id':order,'steel_grade':grade,'material_code':'DEMO-ALLOY',
                'batch_id':batch,'expected_erp_revision':2 if label=='VERSION' else 1,'expected_wms_revision':1,
                'source_updated_at':created,'revision':1}
        with sqlite3.connect(directory/'mes.db') as db:
            db.execute('INSERT INTO heats VALUES (?,?,?,?)',(heat,grade,'in_progress',created))
            db.execute('INSERT INTO temperatures VALUES (?,?,?)',(heat,temperature,created))
            db.execute('INSERT INTO chemistry VALUES (?,?,?,?,?)',(heat,carbon,.25,.65,created))
            db.execute('INSERT INTO heat_process_context VALUES (?,?,?,?)',
                (heat,'review','DEMO-LINE-A',(now-timedelta(hours=8)).isoformat()))
            db.execute('INSERT INTO heat_task_links VALUES (?,?)',(heat,json.dumps(link,ensure_ascii=False)))
            if label=='NO-SOP':
                # Copy the EXISTING fictional rule bounds into a distinct source
                # identity/grade, intentionally with no applicable knowledge SOP.
                original=json.loads(db.execute('SELECT rule_json FROM process_rules WHERE rule_id=?',
                    ('DEMO-RULE-A-REVIEW-v1',)).fetchone()[0])
                original.update(rule_id='DEMO-RULE-E2-NO-SOP-'+run_label,steel_grade=grade)
                original['source']['document_name']='虚构E2无配套SOP规则（仅用于拒答验证）'
                db.execute('INSERT INTO process_rules VALUES (?, ?, ?)',
                    (original['rule_id'],'published',json.dumps(original,ensure_ascii=False)))
        common={'source_updated_at':(now-timedelta(hours=7)).isoformat() if label=='STALE' else created,'revision':1}
        erp={'production_order_id':order,'heat_ids':[heat],
             'steel_grade':'UNRELATED-DEMO-GRADE' if label=='ERP-CONFLICT' else grade,
             'planned_quantity':20.,'completed_quantity':5.,'quantity_unit':'t',
             'due_date':(now+timedelta(days=1)).isoformat(),'status':'released','material_code':'DEMO-ALLOY',
             'batch_id':batch,'required_quantity':100.,'material_unit':'kg',**common}
        wms={'batch_id':batch,'material_code':'DEMO-ALLOY','material_name':'完全虚构的E2演示合金',
             'production_order_id':'UNRELATED-DEMO-ORDER' if label=='WMS-CONFLICT' else order,
             'available_quantity':float(quantity),'unit':'kg','warehouse':'DEMO-WH','location':'DEMO-A01',
             'status':'available',**common}
        for system,table,key,record in [('erp','production_orders',order,erp),('wms','inventory_batches',batch,wms)]:
            with sqlite3.connect(directory/(system+'.db')) as db:
                db.execute('INSERT INTO '+table+' VALUES (?,?)',(key,json.dumps(record,ensure_ascii=False)))
        records[label]={'heat_id':heat,'production_order_id':order,'batch_id':batch}
    state={'fictional':True,'existing_rows_unchanged':True,'run_label':run_label,'created_at':created,'records':records}
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    return {**state,'reused':False,'fresh':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-label',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare_demo(data_directory(),args.run_label),ensure_ascii=False))
