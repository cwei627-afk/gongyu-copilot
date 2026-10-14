"""Source-owned display identifiers. Provisioning writes; HTTP resolution is read-only."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.db import connect
from app.errors import data_error

router = APIRouter()
SYSTEMS = {
    'mes': ('demo_heat_details', 'heat_id', 'heat', 'H'),
    'erp': ('demo_order_details', 'production_order_id', 'order', 'PO'),
    'wms': ('demo_batch_details', 'batch_id', 'batch', 'LOT'),
}


def provision(directory: Path):
    """Assign once from source records; never replace an existing mapping on restart."""
    counts = {}
    for system, (table, key, kind, prefix) in SYSTEMS.items():
        with sqlite3.connect(directory / (system + '.db')) as db:
            db.execute('CREATE TABLE IF NOT EXISTS display_identities ('
                       'internal_id TEXT PRIMARY KEY, display_id TEXT UNIQUE NOT NULL, '
                       'entity_kind TEXT NOT NULL, source_run TEXT NOT NULL)')
            rows = db.execute(f'SELECT {key},run_id,record_json FROM {table} ORDER BY run_id,{key}').fetchall()
            for internal_id, run, body in rows:
                if db.execute('SELECT 1 FROM display_identities WHERE internal_id=?', [internal_id]).fetchone():
                    continue
                record = json.loads(body)
                timestamp = record.get('planned_start_time') or record.get('planned_start') or record.get('inbound_time') or record['updated_at']
                date = str(timestamp)[:10].replace('-', '')
                if not re.fullmatch(r'\d{8}', date):
                    raise ValueError('invalid source date for display identity')
                stem = prefix + date + '-'
                previous = db.execute('SELECT display_id FROM display_identities WHERE display_id LIKE ?', [stem + '%']).fetchall()
                sequence = max((int(row[0].split('-')[-1]) for row in previous), default=0) + 1
                db.execute('INSERT INTO display_identities VALUES (?,?,?,?)',
                           [internal_id, stem + f'{sequence:04d}', kind, run])
            counts[system] = db.execute('SELECT count(*) FROM display_identities').fetchone()[0]
    return counts


class DisplayRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identifiers: list[str] = Field(min_length=1, max_length=30)


@router.post('/api/demo/display-identities', summary='从业务源解析已登记的展示编号（只读）')
def identities(body: DisplayRequest, request: Request):
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', item) for item in body.identifiers):
        raise data_error('INVALID_DATA', '编号格式无效')
    results = []
    for system, (table, key, kind, _) in SYSTEMS.items():
        with connect(request.app.state.data_dir, system) as db:
            for identifier in dict.fromkeys(body.identifiers):
                row = db.execute('SELECT * FROM display_identities WHERE internal_id=? OR display_id=?',
                                 [identifier, identifier]).fetchone()
                if row is None:
                    continue
                source = db.execute(f'SELECT run_id FROM {table} WHERE {key}=?', [row['internal_id']]).fetchone()
                if source is None or source[0] != row['source_run'] or row['entity_kind'] != kind:
                    raise data_error('INVALID_DATA', '展示编号与源对象身份不一致')
                results.append(dict(row) | {'system': system.upper()})
    unique = {}
    for result in results:
        previous = unique.get(result['internal_id'])
        if previous is not None and previous != result:
            raise data_error('INVALID_DATA', '业务编号存在跨系统身份冲突')
        unique[result['internal_id']] = result
    results = list(unique.values())
    digest = hashlib.sha256(json.dumps(results, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode()).hexdigest()
    return {'identities': results, 'content_sha256': digest, 'fictional': True}
