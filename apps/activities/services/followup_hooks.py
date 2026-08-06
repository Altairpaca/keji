"""工作事件 / 沟通记录 → 待办自动联动（T5.3，规格 §4.3 / §4.7 / §13）。

设计：不用 signals 跨 app 塞逻辑（AGENTS.md 反模式），由 activities 服务层的
create / update / soft_delete 函数在 save 之后显式调用本模块的钩子函数。

防重复 / 联动依据：Task.source_key（格式 ``event:<pk>`` / ``comm:<pk>``），
业务对象与待办通过来源键一一对应；已完成 / 已取消的待办视为终结，不参与防重。
"""

from datetime import date

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord, WorkEvent
from apps.customers.models import Customer
from apps.tasks.models import Task
from apps.tasks.services import (
    cancel_tasks_by_source,
    create_task,
    find_task_by_source,
    update_task,
)

# WorkEvent.event_type → Task.task_type 映射（key 为 EventType 常量存储值）。
FOLLOWUP_TASK_TYPE: dict[str, str] = {
    "call": "call",
    "wechat": "wechat",
    "meeting": "meeting",
    "followup": "followup",
    "other": "other",
    "first_meeting": "meeting",
    "phone_call": "call",
    "home_visit": "meeting",
    "policy_organize": "policy_organize",
    "material_collection": "prepare_materials",
    "claim_process": "claim_material",
    "customer_activity": "event",
}

# CommunicationRecord.channel → Task.task_type 映射：电话/视频→打电话、
# 微信→发微信、见面类→约见、其余→客户回访。
_COMMUNICATION_TASK_TYPE: dict[str, str] = {
    "phone": "call",
    "video_call": "call",
    "wechat": "wechat",
    "meeting": "meeting",
    "company_activity": "meeting",
    "home_visit": "meeting",
    "customer_visit": "meeting",
    "sms": "followup",
    "other": "followup",
}


def _task_type_for_communication(channel: str) -> str:
    return _COMMUNICATION_TASK_TYPE.get(channel, "followup")


def _ensure_followup_task(
    *,
    source_key: str,
    title: str,
    task_type: str,
    customer: Customer,
    followup_date: date,
    content: str,
    created_by: User | None,
) -> Task:
    """自动联动公共逻辑：同来源未完成待办已存在则更新截止日期，否则新建。"""
    existing = find_task_by_source(source_key)
    if existing is not None:
        if existing.due_date != followup_date:
            update_task(existing, due_date=followup_date)
        return existing
    return create_task(
        title=title,
        task_type=task_type,
        customer=customer,
        due_date=followup_date,
        content=content,
        created_by=created_by,
        source_key=source_key,
    )


def ensure_followup_task_for_event(event: WorkEvent) -> Task | None:
    """事件创建 / 更新后调用：有 next_followup_date 时确保关联待办存在。

    - next_followup_date 为空 → 不建；
    - 同来源未完成待办已存在 → 改其 due_date 后返回（防重复）；
    - 否则新建任务（task_type 按 event_type 映射，content 取 next_step）。
    """
    if event.next_followup_date is None:
        return None
    title = f"跟进：{event.title or event.get_event_type_display()}"
    return _ensure_followup_task(
        source_key=f"event:{event.pk}",
        title=title,
        task_type=FOLLOWUP_TASK_TYPE[event.event_type],
        customer=event.customer,
        followup_date=event.next_followup_date,
        content=event.next_step or "",
        created_by=event.created_by or event.owner,
    )


def ensure_followup_task_for_communication(comm: CommunicationRecord) -> Task | None:
    """沟通记录创建 / 更新后调用：有 next_followup_date 时确保关联待办存在。

    task_type 按 channel 映射；title 取沟通方式中文名 + 客户名；content 取 next_plan。
    """
    if comm.next_followup_date is None:
        return None
    customer_name = comm.customer.name if comm.customer else ""
    title = f"跟进：{comm.get_channel_display()} {customer_name}".rstrip()
    return _ensure_followup_task(
        source_key=f"comm:{comm.pk}",
        title=title,
        task_type=_task_type_for_communication(comm.channel),
        customer=comm.customer,
        followup_date=comm.next_followup_date,
        content=comm.next_plan or "",
        created_by=comm.recorded_by,
    )


def handle_event_saved(event: WorkEvent) -> Task | None:
    """事件保存完成后触发联动（由 activities 服务显式调用，非 signal）。"""
    return ensure_followup_task_for_event(event)


def handle_communication_saved(comm: CommunicationRecord) -> Task | None:
    """沟通记录保存完成后触发联动（由 activities 服务显式调用，非 signal）。"""
    return ensure_followup_task_for_communication(comm)


def handle_event_deleted(event: WorkEvent) -> int:
    """事件软删时联动：取消该来源所有未完成待办。"""
    return cancel_tasks_by_source(f"event:{event.pk}")


def handle_communication_deleted(comm: CommunicationRecord) -> int:
    """沟通记录软删时联动：取消该来源所有未完成待办。"""
    return cancel_tasks_by_source(f"comm:{comm.pk}")
