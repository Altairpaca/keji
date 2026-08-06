"""activities 服务层：工作事件 / 沟通记录 创建、更新、软删、恢复（T5.1）。

视图保持薄，写操作一律经本模块进出；涉及多模型写操作时在服务层声明
transaction.atomic 事务边界。
"""

from django.db import transaction
from django.utils import timezone

from apps.activities.models import CommunicationRecord, WorkEvent
from apps.activities.services.followup_hooks import (
    ensure_followup_task_for_communication,
    ensure_followup_task_for_event,
    handle_communication_deleted,
    handle_event_deleted,
)
from apps.customers.models import Customer


def create_work_event(*, customer: Customer | None, title: str, **kwargs: object) -> WorkEvent:
    """创建工作事件：customer 与 title 必填；occurred_at 缺省取当前时间。

    创建后自动联动：若设置了 next_followup_date，同事务内生成关联待办。
    """
    if customer is None:
        raise ValueError("工作事件必须关联客户")
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("工作事件标题不能为空")
    occurred_at = kwargs.pop("occurred_at", None)
    if occurred_at is None:
        occurred_at = timezone.now()
    with transaction.atomic():
        event: WorkEvent = WorkEvent.objects.create(
            customer=customer,
            title=cleaned_title,
            occurred_at=occurred_at,
            **kwargs,
        )
        ensure_followup_task_for_event(event)
    return event


def update_work_event(event: WorkEvent, **fields: object) -> WorkEvent:
    """部分更新并保存；未知字段拒绝，避免拼写错误静默失效。

    保存后自动联动：next_followup_date 变更会同步到关联待办。
    """
    for field, value in fields.items():
        if not hasattr(event, field):
            raise ValueError(f"未知字段：{field}")
        setattr(event, field, value)
    event.save()
    ensure_followup_task_for_event(event)
    return event


def soft_delete_work_event(event: WorkEvent) -> WorkEvent:
    """软删除工作事件（ADR-006 第 1 级），并取消该事件关联的未完成待办。"""
    result = event.soft_delete()
    handle_event_deleted(event)
    return result


def restore_work_event(event: WorkEvent) -> WorkEvent:
    """恢复软删除的工作事件。"""
    return event.restore()


def _validate_quick_result(quick_result: object) -> None:
    """quick_result 为 None / 空串合法；非空必须是合法枚举值。"""
    if quick_result is None or quick_result == "":
        return
    if not isinstance(quick_result, str):
        raise ValueError(f"无效的快捷结果：{quick_result}")
    if quick_result not in CommunicationRecord.QuickResult.values:
        raise ValueError(f"无效的快捷结果：{quick_result}")


def create_communication(*, customer: Customer | None, **kwargs: object) -> CommunicationRecord:
    """创建沟通记录：customer 必填；occurred_at 缺省取当前时间；
    quick_result 非空时必须为合法枚举值。

    创建后自动联动：若设置了 next_followup_date，同事务内生成关联待办。
    """
    if customer is None:
        raise ValueError("沟通记录必须关联客户")
    _validate_quick_result(kwargs.get("quick_result"))
    occurred_at = kwargs.pop("occurred_at", None)
    if occurred_at is None:
        occurred_at = timezone.now()
    with transaction.atomic():
        comm: CommunicationRecord = CommunicationRecord.objects.create(
            customer=customer,
            occurred_at=occurred_at,
            **kwargs,
        )
        ensure_followup_task_for_communication(comm)
    return comm


def update_communication(
    communication: CommunicationRecord, **fields: object
) -> CommunicationRecord:
    """部分更新并保存；未知字段拒绝；quick_result 非空必须合法。

    保存后自动联动：next_followup_date 变更会同步到关联待办。
    """
    if "quick_result" in fields:
        _validate_quick_result(fields["quick_result"])
    for field, value in fields.items():
        if not hasattr(communication, field):
            raise ValueError(f"未知字段：{field}")
        setattr(communication, field, value)
    communication.save()
    ensure_followup_task_for_communication(communication)
    return communication


def soft_delete_communication(communication: CommunicationRecord) -> CommunicationRecord:
    """软删除沟通记录（ADR-006 第 1 级），并取消关联的未完成待办。"""
    result = communication.soft_delete()
    handle_communication_deleted(communication)
    return result


def restore_communication(communication: CommunicationRecord) -> CommunicationRecord:
    """恢复软删除的沟通记录。"""
    return communication.restore()
