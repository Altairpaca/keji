"""导出服务（规格 §16 导出 / §17 can_export_data / §10 敏感导出审计，T9.5）。

- ``export_customers_csv``：筛选后的客户名单 CSV（UTF-8 BOM，Excel 可直接打开）
- ``export_customer_profile``：单客户全字段 + 关联概要 + 最近时间线 5 条
- ``export_customer_timeline``：客户统一时间线 CSV（复用 build_timeline）
- ``export_customer_archive_zip``：客户全部资料 ZIP（档案 + 时间线 + 文档原件）

约定：
- 所有 CSV 均带 UTF-8 BOM（``utf-8-sig``）；
- 导出属敏感操作，视图层在成功后应记录审计事件（T10.2 接入 apps.audit）；
- ZIP 内文件名 / 客户目录名经 ``sanitize_filename`` 去路径分隔符，防目录穿越
  （ADR-005：原始文件名绝不直接进存储键，导出时同理）。
"""

import csv
import io
import re
import zipfile
from collections.abc import Iterable
from datetime import date, datetime

from django.db.models import QuerySet

from apps.activities.services.timeline import TYPE_LABELS, TimelineEntry, build_timeline
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.documents.storage import default_storage

# 客户名单 CSV 列（与规格 §16 导出列一致）。
CUSTOMER_CSV_HEADERS = [
    "姓名",
    "性别",
    "手机号",
    "微信昵称",
    "出生日期",
    "年龄说明",
    "地区",
    "职业",
    "来源",
    "状态",
    "优先级",
    "标签",
    "最后联系",
    "下次跟进",
    "备注",
]


def sanitize_filename(name: str) -> str:
    """去除路径分隔符与首尾空白 / 点，保证 ZIP 内条目路径安全。

    空名回退为「未命名」，避免生成空路径段（ZIP 路径穿越防护）。
    """
    cleaned = re.sub(r"[\\/]", "_", name).strip(" .")
    return cleaned or "未命名"


def _fmt_date(value: date | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _fmt_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _write_csv(rows: Iterable[Iterable[str]]) -> bytes:
    """把行序列写成 UTF-8 BOM CSV 字节。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def export_customers_csv(queryset: QuerySet[Customer]) -> bytes:
    """导出客户名单 CSV：按给定（已筛选）QuerySet 输出全量结果。

    标签多选合并为逗号分隔字符串；空字段输出空串。
    """
    rows: list[list[str]] = [CUSTOMER_CSV_HEADERS]
    for customer in queryset.select_related("status").prefetch_related("tags"):
        rows.append(
            [
                customer.name,
                customer.get_gender_display(),
                customer.phone,
                customer.wechat_nickname,
                _fmt_date(customer.birth_date),
                customer.age_note,
                customer.region,
                customer.occupation,
                customer.source,
                customer.status.name if customer.status else "",
                customer.get_priority_display(),
                ",".join(tag.name for tag in customer.tags.all()),
                _fmt_date(customer.last_contact_date),
                _fmt_date(customer.next_followup_date),
                customer.notes,
            ]
        )
    return _write_csv(rows)


def _timeline_row(entry: TimelineEntry) -> list[str]:
    """时间线条目 → CSV 行（类型用中文标签，时间为 Y-m-d H:i）。"""
    return [
        TYPE_LABELS.get(entry.type, entry.type),
        _fmt_datetime(entry.occurred_at),
        entry.title,
        entry.summary,
    ]


def export_customer_timeline(customer: Customer) -> bytes:
    """导出客户统一时间线 CSV（类型 / 时间 / 标题 / 摘要，按时间倒序）。"""
    rows: list[list[str]] = [["类型", "时间", "标题", "摘要"]]
    for entry in build_timeline(customer):
        rows.append(_timeline_row(entry))
    return _write_csv(rows)


def _profile_field_rows(customer: Customer) -> list[tuple[str, str]]:
    """客户全字段 → (标签, 值) 对。"""
    return [
        ("姓名", customer.name),
        ("性别", customer.get_gender_display()),
        ("出生日期", _fmt_date(customer.birth_date)),
        ("年龄说明", customer.age_note),
        ("手机号", customer.phone),
        ("微信昵称", customer.wechat_nickname),
        ("地区", customer.region),
        ("职业", customer.occupation),
        ("客户来源", customer.source),
        ("原服务人员", customer.previous_agent),
        ("首次接触日期", _fmt_date(customer.first_contact_date)),
        ("最后联系日期", _fmt_date(customer.last_contact_date)),
        ("下次跟进日期", _fmt_date(customer.next_followup_date)),
        ("状态", customer.status.name if customer.status else ""),
        ("优先级", customer.get_priority_display()),
        ("沟通偏好", customer.communication_preference),
        ("婚姻和家庭说明", customer.marital_family_note),
        ("一般备注", customer.notes),
        ("负责人", str(customer.owner) if customer.owner else ""),
        ("创建时间", _fmt_datetime(customer.created_at)),
        ("更新时间", _fmt_datetime(customer.updated_at)),
    ]


def _profile_summary_rows(customer: Customer) -> list[tuple[str, str]]:
    """关联概要：保单 / 理赔 / 待办 / 文档 / 关系数量。"""
    return [
        ("保单数", str(customer.held_policies.count())),
        ("理赔数", str(customer.claims.count())),
        ("待办数", str(customer.tasks.count())),
        ("文档数", str(customer.documents.count())),
        (
            "关系数",
            str(customer.outgoing_relations.count() + customer.incoming_relations.count()),
        ),
    ]


def export_customer_profile(customer: Customer) -> bytes:
    """导出单客户档案摘要 CSV：全字段 + 关联概要 + 最近时间线 5 条。"""
    rows: list[list[str]] = [["字段", "值"]]
    rows.extend([label, value] for label, value in _profile_field_rows(customer))
    rows.append(["# 关联概要", ""])
    rows.extend([label, value] for label, value in _profile_summary_rows(customer))
    rows.append(["# 最近时间线（最多 5 条）", ""])
    rows.append(["类型", "时间", "标题", "摘要"])
    for entry in build_timeline(customer, limit=5):
        rows.append(_timeline_row(entry))
    return _write_csv(rows)


def _unique_zip_name(base: str, seen: set[str]) -> str:
    """ZIP 内同目录重名时追加序号，避免同名文档互相覆盖。"""
    candidate = base
    counter = 2
    while candidate in seen:
        stem, dot, ext = base.rpartition(".")
        candidate = f"{stem}_{counter}{dot}{ext}" if dot else f"{base}_{counter}"
        counter += 1
    seen.add(candidate)
    return candidate


def _document_bytes(doc: Document) -> bytes:
    """读取文档二进制；存储后端缺失时写占位说明而非中断导出。"""
    if default_storage.exists(doc.storage_key):
        return default_storage.open(doc.storage_key).read()
    return f"文件缺失：存储键 {doc.storage_key} 对应的文件不存在于存储后端。\n".encode()


def export_customer_archive_zip(customer: Customer) -> tuple[bytes, str]:
    """打包客户全部资料：``{姓名}/00_客户档案.csv``、``01_时间线.csv``、
    ``02_文档/<原始文件名>``（sanitize 后；缺文件写占位说明）。

    返回 ``(zip 字节, 附件文件名)``，文件名同样 sanitize。
    """
    base = sanitize_filename(customer.name)
    buffer = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base}/00_客户档案.csv", export_customer_profile(customer))
        zf.writestr(f"{base}/01_时间线.csv", export_customer_timeline(customer))
        for doc in customer.documents.all():
            name = _unique_zip_name(sanitize_filename(doc.original_name), seen)
            zf.writestr(f"{base}/02_文档/{name}", _document_bytes(doc))
    return buffer.getvalue(), f"{base}_全部资料.zip"
