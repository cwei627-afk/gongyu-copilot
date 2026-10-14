from typing import Annotated

from fastapi import Path

# Transport format only: no business ID prefix, enumeration or existence check.
ObjectId = Annotated[str, Path(
    min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$",
    description="1–128 字符，不含空白或控制字符；存在性由业务系统查询确定",
)]

# Metadata differs by business object; the validation constraints stay identical.
HeatId = Annotated[ObjectId, Path(
    description="MES 动态炉次号，必填字符串，例如 H001。1–128 字符，不含空白或控制字符，区分大小写；存在性由 MES 查询确认，不是预定义白名单。",
    examples=["H001"],
)]
MaterialRequestId = Annotated[ObjectId, Path(
    description="ERP 物料申请单号，必填字符串，例如 MR001；不是炉次号或物料编码。1–128 字符，不含空白或控制字符，区分大小写。",
    examples=["MR001"],
)]
MaterialCode = Annotated[ObjectId, Path(
    description="WMS 物料编码，必填字符串，例如 MAT001；不是申请单号。1–128 字符，不含空白或控制字符，区分大小写。",
    examples=["MAT001"],
)]
