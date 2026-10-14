import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.errors import data_error

Model = TypeVar("Model", bound=BaseModel)
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def data_directory() -> Path:
    return Path(os.environ.get("MOCK_DATA_DIR", DEFAULT_DATA_DIR)).resolve()


@contextmanager
def connect(data_dir: Path, system: str):
    # Read-only: an absent database must fail, never silently create an empty one.
    uri = (data_dir / f"{system}.db").resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def read_record(connection, sql: str, object_id: str, schema: type[Model],
                *, missing_code: str = "OBJECT_NOT_FOUND") -> Model:
    row = connection.execute(sql, (object_id,)).fetchone()
    if row is None:
        raise data_error(missing_code, "业务对象不存在" if missing_code == "OBJECT_NOT_FOUND"
                         else "对象存在，但缺少测量记录")
    values = dict(row)
    missing = [name for name in schema.model_fields
               if values.get(name) is None
               or (isinstance(values.get(name), str) and not values[name].strip())]
    if missing:
        raise data_error("MISSING_FIELDS", "业务数据缺少必要字段", missing)
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors()})
        raise data_error("INVALID_DATA", "业务字段格式无效", fields) from exc


def require_heat(connection, heat_id: str):
    # Only check existence here; unrelated basic fields do not block measurement reads.
    row = connection.execute("SELECT heat_id FROM heats WHERE heat_id = ?", (heat_id,)).fetchone()
    if row is None:
        raise data_error("OBJECT_NOT_FOUND", "MES 炉次不存在")
