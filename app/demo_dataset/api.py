"""Bounded read-only lists in the Mock systems, separate from frozen API schemas."""
import hashlib
import json
from datetime import date as Date, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.db import connect
from app.errors import data_error
from app.api_docs import error_responses

router = APIRouter()


class ListResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    system: Literal['MES', 'ERP', 'WMS']
    operation_id: str
    rows: list[dict] = Field(max_length=20)
    returned_count: int
    total_matching: int
    limit: int = Field(ge=1, le=20)
    truncated: bool
    source_snapshot_at: str
    content_sha256: str
    fictional: bool


def list_records(request, system, limit=10, date=None, start_time=None, end_time=None,
                 furnace_id=None, steel_grade=None, status=None, review_only=False):
    from app.errors import BackendError
    from app.schemas import ErrorDetail
    allowed = {'mes': {'limit', 'date', 'start_time', 'end_time', 'furnace_id', 'steel_grade', 'status', 'review_only'},
               'erp': {'limit', 'date', 'start_time', 'end_time', 'status'}, 'wms': {'limit', 'status'}}[system]
    if set(request.query_params) - allowed:
        raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='存在不支持的查询参数'))
    if date and (start_time or end_time) or bool(start_time) != bool(end_time):
        raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='日期与完整时间范围二选一'))
    if start_time and (start_time.tzinfo is None or end_time.tzinfo is None or start_time >= end_time or (end_time-start_time).total_seconds() > 60*86400):
        raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='时间范围必须带时区、递增且不超过60天'))
    table = {'mes': 'demo_heat_details', 'erp': 'demo_order_details', 'wms': 'demo_batch_details'}[system]
    key = {'mes': 'heat_id', 'erp': 'production_order_id', 'wms': 'batch_id'}[system]
    with connect(request.app.state.data_dir, system) as db:
        latest = db.execute(f'SELECT run_id FROM {table} ORDER BY run_id DESC LIMIT 1').fetchone()
        if not latest:
            raise data_error('DEMO_DATA_NOT_READY', '演示数据未初始化')
        clauses, params = ['run_id=?'], [latest['run_id']]
        if date:
            if system == 'wms':
                raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='库存列表不支持生产日期'))
            clauses.append('substr(production_time,1,10)=?'); params.append(date.isoformat())
        if start_time:
            if system == 'wms':
                raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='库存列表不支持生产时间范围'))
            clauses += ['julianday(production_time)>=julianday(?)', 'julianday(production_time)<julianday(?)']
            params += [start_time.isoformat(), end_time.isoformat()]
        for name, value in [('furnace_id', furnace_id), ('steel_grade', steel_grade), ('status', status)]:
            if value is not None:
                if system != 'mes' and name != 'status':
                    raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='该系统不支持此筛选条件'))
                clauses.append(name + '=?'); params.append(value)
        if review_only:
            if system != 'mes':
                raise BackendError(422, ErrorDetail(category='request', code='INVALID_PARAMETER', message='仅MES支持历史待复核标记'))
            clauses.append('review_flag=1')
        where = ' AND '.join(clauses)
        total = db.execute(f'SELECT count(*) FROM {table} WHERE {where}', params).fetchone()[0]
        sorting = 'production_time DESC,' + key if system != 'wms' else 'available_quantity ASC,' + key
        records = db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY {sorting} LIMIT ?', params + [limit]).fetchall()
        rows = []
        captured = None
        for record in records:
            extra = json.loads(record['record_json'])
            if system == 'mes':
                values = extra
            else:
                source_table = 'production_orders' if system == 'erp' else 'inventory_batches'
                original = db.execute(f'SELECT record_json FROM {source_table} WHERE {key}=?', (record[key],)).fetchone()
                if not original:
                    raise data_error('INVALID_DATA', '详情缺少对应正式源记录')
                values = {**json.loads(original[0]), **extra}
            if values[key] != record[key] or values.get('fictional') is not True:
                raise data_error('INVALID_DATA', '记录身份或演示范围不一致')
            captured = values.get('updated_at') or values.get('source_updated_at')
            rows.append(values)
        # Even an empty query retains the actual source dataset's snapshot identity.
        if captured is None:
            sample = json.loads(db.execute(f'SELECT record_json FROM {table} WHERE run_id=? LIMIT 1', [latest['run_id']]).fetchone()[0])
            captured = sample['updated_at']
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return ListResponse(request_id=str(uuid4()), system=system.upper(),
                        operation_id='list_' + system + '_records', rows=rows, returned_count=len(rows), total_matching=total,
                        limit=limit, truncated=total > len(rows), source_snapshot_at=captured,
                        content_sha256=hashlib.sha256(canonical.encode()).hexdigest(), fictional=True)


Limit = Annotated[int, Query(ge=1, le=20, description='默认10，最多20；不支持全库导出或任意SQL')]


@router.get('/api/mes/heats', response_model=ListResponse, tags=['MES'], operation_id='list_mes_heats',
            summary='按日期、炉号和状态查询有限炉次列表', responses=error_responses('MES 列表', 'date', 'limit'),
            description='只读正式Mock源数据。默认10、最多20；历史待复核标记不代表当前工艺判断。不存在匹配记录返回空列表，不补造炉次。')
def heats(request: Request, limit: Limit = 10, date: Date | None = None, start_time: datetime | None = None,
          end_time: datetime | None = None, furnace_id: str | None = None, steel_grade: str | None = None,
          status: str | None = None, review_only: bool = False):
    return list_records(request, 'mes', limit, date, start_time, end_time, furnace_id, steel_grade, status, review_only)


@router.get('/api/erp/production-orders', response_model=ListResponse, tags=['ERP'], operation_id='list_erp_production_orders',
            summary='查询指定日期或状态的生产订单列表', responses=error_responses('ERP 列表', 'date', 'limit'),
            description='只读ERP，最多20条；订单关联由实际源字段给出，不能由模型推测。')
def orders(request: Request, limit: Limit = 10, date: Date | None = None, start_time: datetime | None = None,
           end_time: datetime | None = None, status: str | None = None):
    return list_records(request, 'erp', limit, date, start_time, end_time, status=status)


@router.get('/api/wms/inventory', response_model=ListResponse, tags=['WMS'], operation_id='list_wms_inventory_batches',
            summary='查询有限库存批次列表及源状态', responses=error_responses('WMS 列表', 'status', 'limit'),
            description='只读WMS，最多20条；low_stock等是源系统状态，不由LLM定义阈值；quality_hold/expired不作为可领用授权。')
def inventory(request: Request, limit: Limit = 10, status: str | None = None):
    return list_records(request, 'wms', limit, status=status)


@router.get('/api/demo/summary', tags=['Demo'], summary='读取当前虚构演示数据规模和时间范围')
def summary(request: Request):
    result = {'fictional': True, 'systems': {}}
    for system, table in [('mes', 'demo_heat_details'), ('erp', 'demo_order_details'), ('wms', 'demo_batch_details')]:
        with connect(request.app.state.data_dir, system) as db:
            run = db.execute(f'SELECT run_id FROM {table} ORDER BY run_id DESC LIMIT 1').fetchone()
            if not run:
                raise data_error('DEMO_DATA_NOT_READY', '演示数据未初始化')
            result['systems'][system] = {'run_id': run[0], 'count': db.execute(f'SELECT count(*) FROM {table} WHERE run_id=?', [run[0]]).fetchone()[0]}
            if system == 'mes':
                row = db.execute('SELECT min(substr(production_time,1,10)),max(substr(production_time,1,10)),count(DISTINCT steel_grade),count(DISTINCT furnace_id) FROM demo_heat_details WHERE run_id=?', [run[0]]).fetchone()
                result.update(date_from=row[0], date_until=row[1], steel_grade_count=row[2], furnace_count=row[3])
                samples = db.execute("SELECT record_json FROM demo_heat_details WHERE run_id=? AND status='in_progress' AND steel_grade='DEMO-A' ORDER BY heat_id DESC LIMIT 4", [run[0]]).fetchall()
                result['example_heat_ids'] = {record['demo_scenario']: record['heat_id'] for record in (json.loads(s[0]) for s in samples)}
    return result
