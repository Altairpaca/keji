"""客户统一时间线聚合服务（规格 §8 / §19，T5.2）。

把工作事件、沟通记录、待办、文件上传等条目按 ``occurred_at`` 倒序聚合，
供客户详情页中栏首屏（"上次发生什么"）与后续 HTMX 分页加载使用。

条目类型经 ``_TIMELINE_SOURCES`` registry（类型 → 查询函数）注册：
T7.2（保单状态变化）与 T8（理赔状态变化）只需向 registry 追加查询函数
即可并入时间线，本任务先以空实现占位（返回空列表，不报错）。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from apps.activities.models import CommunicationRecord, WorkEvent
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.tasks.models import Task

# 条目类型常量。
WORK_EVENT = "work_event"
COMMUNICATION = "communication"
TASK = "task"
DOCUMENT_UPLOAD = "document_upload"
POLICY_CHANGE = "policy_change"  # 预留：T7.2 保单状态变化
CLAIM_CHANGE = "claim_change"  # 预留：T8 理赔状态变化

# 条目类型 → 展示徽标文案 / 徽标样式（模板渲染用）。
TYPE_LABELS: dict[str, str] = {
    WORK_EVENT: "工作事件",
    COMMUNICATION: "沟通记录",
    TASK: "待办",
    DOCUMENT_UPLOAD: "文件上传",
    POLICY_CHANGE: "保单变更",
    CLAIM_CHANGE: "理赔变更",
}

TYPE_BADGE: dict[str, str] = {
    WORK_EVENT: "badge-brand",
    COMMUNICATION: "badge-neutral",
    TASK: "badge-warning",
    DOCUMENT_UPLOAD: "badge-accent",
    POLICY_CHANGE: "badge-success",
    CLAIM_CHANGE: "badge-danger",
}


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """时间线条目（不可变值对象）。type 为条目类型常量，url 可选。"""

    type: str
    occurred_at: datetime
    title: str
    summary: str = ""
    url: str | None = None
    customer_pk: str | None = None


def _work_event_entries(customer: Customer, limit: int) -> list[TimelineEntry]:
    events = (
        WorkEvent.objects.select_related("customer")
        .filter(customer=customer)
        .order_by("-occurred_at")[:limit]
    )
    return [
        TimelineEntry(
            type=WORK_EVENT,
            occurred_at=event.occurred_at,
            title=event.title,
            summary=event.summary,
            customer_pk=str(customer.pk),
        )
        for event in events
    ]


def _communication_entries(customer: Customer, limit: int) -> list[TimelineEntry]:
    communications = (
        CommunicationRecord.objects.select_related("customer")
        .filter(customer=customer)
        .order_by("-occurred_at")[:limit]
    )
    return [
        TimelineEntry(
            type=COMMUNICATION,
            occurred_at=communication.occurred_at,
            title=communication.get_channel_display(),
            summary=(
                communication.content
                or (
                    f"快捷结果：{communication.get_quick_result_display()}"
                    if communication.quick_result
                    else ""
                )
            ),
            customer_pk=str(customer.pk),
        )
        for communication in communications
    ]


def _task_entries(customer: Customer, limit: int) -> list[TimelineEntry]:
    tasks = (
        Task.objects.select_related("customer")
        .filter(customer=customer)
        .order_by("-created_at")[:limit]
    )
    return [
        TimelineEntry(
            type=TASK,
            occurred_at=task.created_at,
            title=task.title,
            summary=task.content or f"截止：{task.due_date}",
            customer_pk=str(customer.pk),
        )
        for task in tasks
    ]


def _document_upload_entries(customer: Customer, limit: int) -> list[TimelineEntry]:
    documents = Document.objects.filter(customers=customer).order_by("-created_at")[:limit]
    return [
        TimelineEntry(
            type=DOCUMENT_UPLOAD,
            occurred_at=document.created_at,
            title=document.title or document.original_name,
            summary=document.note,
            customer_pk=str(customer.pk),
        )
        for document in documents
    ]


def _noop(_customer: Customer, _limit: int) -> list[TimelineEntry]:
    """预留条目类型的空数据源（T7.2 / T8 实现后替换为真实查询）。"""
    return []


# 条目类型 → 查询函数 registry。T7.2 / T8 追加 POLICY_CHANGE / CLAIM_CHANGE
# 的真实查询函数即可并入时间线，无需改动 build_timeline。
_TIMELINE_SOURCES: dict[str, Callable[[Customer, int], list[TimelineEntry]]] = {
    WORK_EVENT: _work_event_entries,
    COMMUNICATION: _communication_entries,
    TASK: _task_entries,
    DOCUMENT_UPLOAD: _document_upload_entries,
    POLICY_CHANGE: _noop,
    CLAIM_CHANGE: _noop,
}


def build_timeline(customer: Customer | None, *, limit: int = 50) -> list[TimelineEntry]:
    """聚合客户统一时间线：按 occurred_at 倒序，最多 limit 条。

    数据源经 ``_TIMELINE_SOURCES`` registry 注册：每个数据源最多取
    ``limit`` 条再整体合并排序，保证跨类型全局 Top-N 正确。
    """
    if customer is None:
        raise ValueError("customer 不能为空")
    if limit <= 0:
        return []
    entries: list[TimelineEntry] = []
    for collector in _TIMELINE_SOURCES.values():
        entries.extend(collector(customer, limit))
    entries.sort(key=lambda entry: entry.occurred_at, reverse=True)
    return entries[:limit]


def _entry_to_dict(entry: TimelineEntry) -> dict[str, object]:
    """条目序列化为 JSON 兼容 dict（occurred_at 转 ISO 字符串）。"""
    return {
        "type": entry.type,
        "occurred_at": entry.occurred_at.isoformat(),
        "title": entry.title,
        "summary": entry.summary,
        "url": entry.url,
        "customer_pk": entry.customer_pk,
    }


def timeline_json(customer: Customer | None) -> list[dict[str, object]]:
    """序列化时间线为 list[dict]（供未来 HTMX 分页加载 / API 使用）。"""
    return [_entry_to_dict(entry) for entry in build_timeline(customer)]


def timeline_items(customer: Customer | None, *, limit: int = 50) -> list[dict[str, object]]:
    """视图与模板标签共用的展示结构：在条目基础上附加 label / badge_class。

    occurred_at 保留 datetime 对象，模板可直接套用 ``|date`` 过滤器。
    """
    items: list[dict[str, object]] = []
    for entry in build_timeline(customer, limit=limit):
        items.append(
            {
                "type": entry.type,
                "occurred_at": entry.occurred_at,
                "title": entry.title,
                "summary": entry.summary,
                "url": entry.url,
                "customer_pk": entry.customer_pk,
                "label": TYPE_LABELS[entry.type],
                "badge_class": TYPE_BADGE[entry.type],
            }
        )
    return items
