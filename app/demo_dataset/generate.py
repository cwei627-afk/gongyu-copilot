"""Fixed seed + explicit snapshot time; insert new source records, never refresh old ones."""
import hashlib
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.enterprise.seed_demo import seed_demo

SEED = 20261003
GRADES = ['DEMO-A'] + [f'DEMO-G{i:02}' for i in range(2, 11)]
MATERIALS = [('SCRAP', '虚构废钢'), ('ALLOY', '虚构合金'), ('LIME', '虚构石灰'),
             ('AUX', '虚构辅料'), ('REFRACTORY', '虚构耐材'), ('PACK', '虚构包装材料'), ('OTHER', '虚构辅助物料')]
SCENARIOS = ['normal', 'temperature_high', 'temperature_low', 'chemistry', 'both', 'missing',
             'duration_review', 'relation_error', 'normal', 'normal', 'normal', 'normal']


def generate(directory, as_of, seed=SEED, *, include_frozen=False):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('explicit timezone required')
    directory = Path(directory)
    run = as_of.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S') + '-' + str(seed)
    if include_frozen:
        run += '-f2'
    state_path = directory / ('stage-f-' + run + '.json')
    if state_path.exists():
        for system, table, count in [('mes', 'demo_heat_details', 400), ('erp', 'demo_order_details', 100), ('wms', 'demo_batch_details', 200)]:
            with sqlite3.connect(directory / (system + '.db')) as db:
                if db.execute(f'SELECT count(*) FROM {table} WHERE run_id=?', [run]).fetchone()[0] != count:
                    raise ValueError('stored run does not match source databases; rebuild in a new directory')
        return {**json.loads(state_path.read_text(encoding='utf-8')), 'reused': True}
    rng = random.Random(seed)
    seed_demo(directory, as_of)
    captured = as_of.isoformat()
    start_day = as_of.astimezone(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=49)
    heat_rows, heat_details, contexts, temperatures, chemistry, links, orders, batches = [], [], [], [], [], [], [], []
    example_ids = {}
    for order_index in range(100):
        order_id = f'FORDER-{run}-{order_index + 1:03}'
        batch_id = f'FLOT-{run}-{order_index + 1:03}-A'
        grade = GRADES[order_index % len(GRADES)]
        # The most recent order also covers the frozen C rule and its real SOP.
        if order_index == 99:
            grade = 'DEMO-A'
        material_code, material_name = MATERIALS[order_index % len(MATERIALS)]
        material_code = 'FDEMO-' + material_code
        heat_ids = []
        day = start_day + timedelta(days=order_index // 2)
        order_status = ['planned', 'released', 'producing', 'partially_completed', 'completed', 'delayed', 'cancelled'][order_index % 7]
        if order_index >= 98:
            order_status = 'producing'
        for sequence in range(4):
            heat_id = f'FHEAT-{run}-{order_index * 4 + sequence + 1:03}'
            heat_ids.append(heat_id)
            scenario = SCENARIOS[(order_index * 4 + sequence) % len(SCENARIOS)]
            if order_index == 99:
                scenario = ['normal', 'temperature_high', 'both', 'missing'][sequence]
            scheduled = day + timedelta(hours=6 + (order_index % 2) * 4, minutes=sequence * 50)
            current_day = order_index >= 98
            if current_day and include_frozen:
                # New F2 snapshots must also be coherent when started after
                # midnight: an in-progress heat cannot start later than as_of.
                elapsed = as_of - day
                scheduled = day + elapsed * ((order_index - 98) * 4 + sequence + 1) / 9
            status = 'in_progress' if current_day else 'cancelled' if order_status == 'cancelled' else 'planned' if order_status == 'planned' else 'completed'
            duration = 95 if scenario == 'duration_review' else 40 + rng.randrange(0, 16)
            end = None if status in ('planned', 'in_progress', 'cancelled') else (scheduled + timedelta(minutes=duration)).isoformat()
            temperature = None if scenario == 'missing' else 1610.0 if scenario in ('temperature_high', 'both') else 1550.0 if scenario == 'temperature_low' else 1580.0
            carbon = .30 if scenario in ('chemistry', 'both') else .18
            # Source snapshot ingestion is new at captured; production dates remain historical.
            measured = captured if current_day else scheduled.isoformat()
            heat_rows.append((heat_id, grade, status, captured))
            temperatures.append((heat_id, temperature, measured))
            chemistry.append((heat_id, carbon, .25, .65, measured))
            stage_start = (as_of - timedelta(hours=1)).isoformat() if current_day else scheduled.isoformat()
            if current_day and include_frozen:
                stage_start = max(scheduled, as_of - timedelta(hours=1)).isoformat()
            contexts.append((heat_id, 'review', 'DEMO-LINE-A', stage_start))
            relation = {'heat_id': heat_id, 'production_order_id': order_id, 'steel_grade': grade,
                        'material_code': material_code, 'batch_id': batch_id, 'expected_erp_revision': 1,
                        'expected_wms_revision': 1, 'source_updated_at': captured, 'revision': 1}
            if scenario == 'relation_error':
                relation['production_order_id'] = 'UNRELATED-FICTIONAL-ORDER'
            links.append((heat_id, json.dumps(relation, ensure_ascii=False)))
            detail = {'heat_id': heat_id, 'furnace_id': 'DEMO-FURNACE-' + str(1 + order_index % 2),
                      'steel_grade': grade, 'production_order_id': relation['production_order_id'],
                      'planned_start_time': scheduled.isoformat(), 'actual_start_time': None if status == 'planned' else scheduled.isoformat(),
                      'end_time': end, 'duration_minutes': duration if end else None, 'temperature': temperature,
                      'chemistry': {'carbon_pct': carbon, 'silicon_pct': .25, 'manganese_pct': .65},
                      'status': status, 'shift': ['白班', '中班', '夜班'][sequence % 3],
                      'material_links': [relation], 'quality_status': 'pending_review' if scenario != 'normal' else 'recorded',
                      'record_status': 'incomplete' if scenario == 'missing' else 'complete',
                      'created_at': scheduled.isoformat(), 'updated_at': captured, 'revision': 1,
                      'demo_scenario': scenario, 'historical_review_flag': scenario != 'normal', 'run_id': run, 'fictional': True}
            heat_details.append((heat_id, run, scheduled.isoformat(), detail['furnace_id'], grade, status, int(scenario != 'normal'), json.dumps(detail, ensure_ascii=False)))
            if order_index == 99:
                example_ids[scenario] = heat_id
        order = {'production_order_id': order_id, 'heat_ids': heat_ids, 'steel_grade': grade,
                 'planned_quantity': 80.0, 'completed_quantity': 80.0 if order_status == 'completed' else 20.0,
                 'quantity_unit': 't', 'due_date': (day + timedelta(days=2)).isoformat(), 'status': order_status,
                 'material_code': material_code, 'batch_id': batch_id, 'required_quantity': 100.0,
                 'material_unit': 'kg', 'source_updated_at': captured, 'revision': 1}
        extra = {'customer_order_id': f'FCUSTOMER-{order_index + 1:03}', 'planned_start': day.isoformat(),
                 'priority': ['normal', 'high', 'low'][order_index % 3], 'created_at': day.isoformat(),
                 'updated_at': captured, 'material_requirement': [{'material_code': material_code, 'batch_id': batch_id, 'quantity': 100.0, 'unit': 'kg'}],
                 'fictional': True, 'run_id': run}
        orders.append((order_id, json.dumps(order, ensure_ascii=False), day.isoformat(), order_status, json.dumps(extra, ensure_ascii=False)))
        for kind in ('A', 'B'):
            identity = batch_id if kind == 'A' else batch_id[:-1] + 'B'
            inventory_state = ['available', 'low_stock', 'zero_stock', 'reserved', 'quality_hold', 'expired'][order_index % 6] if kind == 'B' else 'available'
            if include_frozen and kind == 'B' and order_index % 12 == 5:
                inventory_state = 'frozen'
            quantity = 0.0 if inventory_state == 'zero_stock' else 50.0 if inventory_state == 'low_stock' else 150.0
            if include_frozen and inventory_state in ('frozen', 'quality_hold', 'expired'):
                quantity = 0.0
            batch = {'batch_id': identity, 'material_code': material_code, 'material_name': material_name,
                     'production_order_id': order_id, 'available_quantity': quantity, 'unit': 'kg',
                     'warehouse': 'FDEMO-WH-' + str(1 + order_index % 2), 'location': f'FDEMO-A{order_index % 20:02}',
                     'status': inventory_state, 'source_updated_at': captured, 'revision': 1}
            extra_batch = {'reserved_qty': 100.0 if inventory_state == 'reserved' else 0.0, 'inbound_time': (day - timedelta(days=2)).isoformat(),
                           'supplier': f'虚构供应商{1 + order_index % 5}', 'quality_status': 'pending' if inventory_state == 'quality_hold' else 'recorded',
                           'updated_at': captured, 'fictional': True, 'run_id': run}
            batches.append((identity, json.dumps(batch, ensure_ascii=False), inventory_state, quantity, json.dumps(extra_batch, ensure_ascii=False)))
    with sqlite3.connect(directory / 'mes.db') as db:
        # A single transaction spans the three attached Mock source databases.
        db.execute('ATTACH DATABASE ? AS erp', [str(directory / 'erp.db')])
        db.execute('ATTACH DATABASE ? AS wms', [str(directory / 'wms.db')])
        db.execute('BEGIN')
        db.execute('CREATE TABLE IF NOT EXISTS demo_heat_details (heat_id TEXT PRIMARY KEY, run_id TEXT, production_time TEXT, furnace_id TEXT, steel_grade TEXT, status TEXT, review_flag INTEGER, record_json TEXT)')
        db.executemany('INSERT INTO heats VALUES (?,?,?,?)', heat_rows)
        db.executemany('INSERT INTO temperatures VALUES (?,?,?)', temperatures)
        db.executemany('INSERT INTO chemistry VALUES (?,?,?,?,?)', chemistry)
        db.executemany('INSERT INTO heat_process_context VALUES (?,?,?,?)', contexts)
        db.executemany('INSERT INTO heat_task_links VALUES (?,?)', links)
        db.executemany('INSERT INTO demo_heat_details VALUES (?,?,?,?,?,?,?,?)', heat_details)
        db.execute('CREATE TABLE IF NOT EXISTS erp.demo_order_details (production_order_id TEXT PRIMARY KEY, run_id TEXT, production_time TEXT, status TEXT, record_json TEXT)')
        db.executemany('INSERT INTO erp.production_orders VALUES (?,?)', [(r[0], r[1]) for r in orders])
        db.executemany('INSERT INTO erp.demo_order_details VALUES (?,?,?,?,?)', [(r[0], run, r[2], r[3], r[4]) for r in orders])
        db.execute('CREATE TABLE IF NOT EXISTS wms.demo_batch_details (batch_id TEXT PRIMARY KEY, run_id TEXT, status TEXT, available_quantity REAL, record_json TEXT)')
        db.executemany('INSERT INTO wms.inventory_batches VALUES (?,?)', [(r[0], r[1]) for r in batches])
        db.executemany('INSERT INTO wms.demo_batch_details VALUES (?,?,?,?,?)', [(r[0], run, r[2], r[3], r[4]) for r in batches])
    summary = {'run_id': run, 'seed': seed, 'as_of': captured, 'fictional': True, 'heat_count': 400,
               'order_count': 100, 'batch_count': 200, 'steel_grade_count': len(GRADES), 'furnace_count': 2,
               'date_from': start_day.date().isoformat(), 'date_until': as_of.astimezone(timezone(timedelta(hours=8))).date().isoformat(),
               'review_flag_count': sum(r[6] for r in heat_details), 'examples': example_ids,
               'data_sha256': hashlib.sha256(json.dumps([heat_rows, heat_details, orders, batches], ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    state_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**summary, 'reused': False}
