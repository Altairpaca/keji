"""客户 CSV 批量导入服务（T4.5 / 规格 §16）。

流程：
1. ``parse_csv``：字节 → 行字典（UTF-8 BOM / GBK 容错，列名归一）；
2. ``validate_row``：单行业务校验，返回错误列表；
3. ``preview_rows``：只统计不落库（预览页用）；
4. ``import_customers``：全量校验 → 整体事务内创建全部（任一行未预知异常
   整体回滚并抛 ``ImportError``），返回逐行报告。

用标准库 ``csv`` 实现，不引入 openpyxl 等新依赖（Excel 支持留待后续）。
"""

import csv
import io
from datetime import datetime
from typing import TypedDict

from django.db import transaction

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services.customers import assign_tags, create_customer, find_duplicates

#: 导入模板列名（* 表示必填）。解析时列名归一（去星号、全角括号转半角）。
IMPORT_COLUMNS: list[str] = [
    "姓名*",
    "性别",
    "手机号",
    "微信昵称",
    "出生日期(YYYY-MM-DD)",
    "年龄说明",
    "地区",
    "职业",
    "备注",
    "标签(逗号分隔)",
]

#: 模板列名 → Customer 模型字段（行键先经 _normalize_key 归一）。
_FIELD_MAP: dict[str, str] = {
    "性别": "gender",
    "手机号": "phone",
    "微信昵称": "wechat_nickname",
    "出生日期(YYYY-MM-DD)": "birth_date",
    "年龄说明": "age_note",
    "地区": "region",
    "职业": "occupation",
    "备注": "notes",
}

_VALID_GENDERS = {"男", "女", "未知"}

_DATE_FORMAT = "%Y-%m-%d"

#: 手机号允许的字符（宽松校验：数字、+、-、空格、括号）。
_PHONE_STRIP_CHARS = set("+- ()")


class ImportRowResult(TypedDict):
    """单行导入结果（失败 / 跳过共用）。"""

    line_no: int | None
    name: str
    reason: str


class ImportReport(TypedDict):
    """整体导入报告。"""

    imported: int
    skipped: list[ImportRowResult]
    failed: list[ImportRowResult]


class ValidRow(TypedDict):
    line_no: int
    row: dict[str, str]


class InvalidRow(ValidRow):
    errors: list[str]


class PreviewReport(TypedDict):
    total: int
    valid_rows: list[ValidRow]
    invalid_rows: list[InvalidRow]


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------


def template_csv_bytes() -> bytes:
    """生成带 UTF-8 BOM 的模板 CSV 字节（含表头，供下载）。"""
    output = io.StringIO()
    csv.writer(output).writerow(IMPORT_COLUMNS)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def _decode(file_content: bytes) -> str:
    """字节解码：优先 UTF-8（含 BOM），失败回退 GBK。"""
    if file_content.startswith(b"\xef\xbb\xbf"):
        return file_content.decode("utf-8-sig")
    try:
        return file_content.decode("utf-8")
    except UnicodeDecodeError:
        return file_content.decode("gbk", errors="replace")


def _normalize_key(key: str) -> str:
    """列名归一：去首尾空白、去必填星号、全角括号转半角。"""
    return key.strip().rstrip("*").strip().replace("（", "(").replace("）", ")")


def parse_csv(file_content: bytes) -> list[dict[str, str]]:
    """解析 CSV 字节为行字典列表（键为归一化后的列名，值 strip 过）。"""
    reader = csv.DictReader(io.StringIO(_decode(file_content)))
    rows: list[dict[str, str]] = []
    for raw in reader:
        row: dict[str, str] = {}
        for key, value in raw.items():
            if key is None:
                continue
            normalized_key = _normalize_key(key)
            if not normalized_key:
                continue
            row[normalized_key] = str(value or "").strip()
        if not row or all(not value for value in row.values()):
            continue  # 空行 / 全空行跳过
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# 单行校验
# ---------------------------------------------------------------------------


def validate_row(row: dict[str, str], line_no: int) -> list[str]:
    """校验单行，返回错误列表（空表示合法）。``line_no`` 用于报告定位。"""
    errors: list[str] = []

    name = (row.get("姓名") or "").strip()
    if not name:
        errors.append("姓名不能为空")

    birth = (row.get("出生日期(YYYY-MM-DD)") or "").strip()
    if birth:
        try:
            datetime.strptime(birth, _DATE_FORMAT)
        except ValueError:
            errors.append("出生日期格式应为 YYYY-MM-DD")

    phone = (row.get("手机号") or "").strip()
    if phone:
        digits = [ch for ch in phone if ch not in _PHONE_STRIP_CHARS]
        if len(digits) < 5 or not all(ch.isdigit() for ch in digits):
            errors.append("手机号格式不正确")

    return errors


# ---------------------------------------------------------------------------
# 预览（不落库）
# ---------------------------------------------------------------------------


def preview_rows(content: bytes) -> PreviewReport:
    """解析并校验全部行，返回统计与逐行明细（不写数据库）。"""
    rows = parse_csv(content)
    valid_rows: list[ValidRow] = []
    invalid_rows: list[InvalidRow] = []
    for line_no, row in enumerate(rows, start=2):
        errors = validate_row(row, line_no)
        item: ValidRow = {"line_no": line_no, "row": row}
        if errors:
            invalid_rows.append({**item, "errors": errors})
        else:
            valid_rows.append(item)
    return {
        "total": len(rows),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
    }


# ---------------------------------------------------------------------------
# 导入（整体事务）
# ---------------------------------------------------------------------------


def _clean_gender(raw: str | None) -> str:
    """性别清洗：空值 → 未知；非法值归一为未知，避免脏数据落库。"""
    value = (raw or "").strip()
    return value if value in _VALID_GENDERS else "未知"


def _split_tags(raw: str | None) -> list[str]:
    """按半角/全角逗号拆分标签名，空串返回空列表。"""
    value = (raw or "").strip()
    if not value:
        return []
    return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]


def _row_to_kwargs(row: dict[str, str]) -> dict[str, object]:
    """行字典 → create_customer 关键字参数（不含 name/owner/created_by）。"""
    birth_raw = (row.get("出生日期(YYYY-MM-DD)") or "").strip()
    kwargs: dict[str, object] = {
        "birth_date": datetime.strptime(birth_raw, _DATE_FORMAT).date() if birth_raw else None,
    }
    for column, field in _FIELD_MAP.items():
        if field == "birth_date":
            continue  # 已在上面单独处理
        kwargs[field] = row.get(column) or ""
    kwargs["gender"] = _clean_gender(str(kwargs.get("gender") or ""))
    return kwargs


def import_customers(
    *,
    content: bytes,
    owner: User,
    created_by: User,
    dry_run: bool = False,
) -> ImportReport:
    """批量导入客户（规格 §16：事务处理 + 逐行报告）。

    校验阶段任一错行 → 整体拒绝（``imported=0``，失败明细进 ``failed``，不落库）；
    全部通过 → 单一事务内创建全部，重复手机号跳过；创建期未预知异常（如出生日期
    与年龄说明双缺触发 create_customer 的 ValueError）→ 整体回滚并抛 ``ImportError``。
    ``dry_run=True`` 时事务提交前回滚，用于试算。
    """
    rows = parse_csv(content)
    failed: list[ImportRowResult] = []
    skipped: list[ImportRowResult] = []
    imported = 0

    # 阶段 1：全量校验，任一错行整体拒绝
    for line_no, row in enumerate(rows, start=2):
        errors = validate_row(row, line_no)
        if errors:
            failed.append(
                {
                    "line_no": line_no,
                    "name": row.get("姓名", ""),
                    "reason": "；".join(errors),
                }
            )
    if failed:
        return {"imported": imported, "skipped": skipped, "failed": failed}

    # 阶段 2：整体事务内创建全部
    with transaction.atomic():
        for line_no, row in enumerate(rows, start=2):
            phone = (row.get("手机号") or "").strip()
            if phone and find_duplicates(phone).exists():
                skipped.append(
                    {
                        "line_no": line_no,
                        "name": row.get("姓名", ""),
                        "reason": "手机号重复",
                    }
                )
                continue
            try:
                customer: Customer = create_customer(
                    name=row["姓名"],
                    owner=owner,
                    created_by=created_by,
                    **_row_to_kwargs(row),
                )
                tag_names = _split_tags(row.get("标签(逗号分隔)"))
                if tag_names:
                    assign_tags(customer, tag_names)
                imported += 1
            except ValueError as exc:
                raise ImportError(
                    f"第 {line_no} 行「{row.get('姓名', '')}」导入失败：{exc}；已整体回滚"
                ) from exc
        if dry_run:
            transaction.set_rollback(True)

    return {"imported": imported, "skipped": skipped, "failed": failed}
