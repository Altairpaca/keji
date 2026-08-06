"""tasks 服务层：待办创建、更新、完成/取消、软删、快速跟进（规格 §13 / §14）。

视图保持薄，业务逻辑全部经本模块进出；多写操作（快速跟进同时更新任务与客户）
在服务层声明 transaction.atomic 事务边界。
"""

from datetime import date, time, timedelta

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.tasks.models import QUICK_FOLLOWUP_DAYS, Task

# 终结状态：is_overdue / 逾期列表的排除集合。
_TERMINAL_STATUSES = ("done", "cancelled")


def create_task(
    *,
    title: str,
    task_type: str = "followup",
    customer: Customer | None = None,
    due_date: date,
    due_time: time | None = None,
    priority: str = "中",
    content: str = "",
    remark: str = "",
    assignee: User | None = None,
    created_by: User | None = None,
) -> Task:
    """创建待办：title 非空校验；customer / assignee / created_by 允许为空。"""
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("待办标题不能为空")

    with transaction.atomic():
        task: Task = Task.objects.create(
            title=cleaned_title,
            task_type=task_type,
            customer=customer,
            due_date=due_date,
            due_time=due_time,
            priority=priority,
            content=content,
            remark=remark,
            assignee=assignee,
            created_by=created_by,
        )
    return task


def update_task(task: Task, **fields: object) -> Task:
    """部分更新并保存；未知字段拒绝；status 流转自动补时间戳。"""
    for field, value in fields.items():
        if not hasattr(task, field):
            raise ValueError(f"未知字段：{field}")
        setattr(task, field, value)
    if task.status == Task.Status.DONE and task.completed_at is None:
        task.completed_at = timezone.now()
    if task.status == Task.Status.CANCELLED and task.cancelled_at is None:
        task.cancelled_at = timezone.now()
    task.save()
    return task


def complete_task(task: Task) -> Task:
    """标记完成：status=done + completed_at。"""
    return update_task(task, status=Task.Status.DONE)


def cancel_task(task: Task) -> Task:
    """标记取消：status=cancelled + cancelled_at。"""
    return update_task(task, status=Task.Status.CANCELLED)


def soft_delete_task(task: Task) -> Task:
    """软删除待办（ADR-006，可恢复）。"""
    return task.soft_delete()


def restore_task(task: Task) -> Task:
    """恢复软删除的待办。"""
    return task.restore()


def set_quick_followup(
    *,
    customer: Customer,
    days: int,
    assignee: User | None = None,
    created_by: User | None = None,
) -> Task:
    """为客户设置快速回访：建 followup 任务并顺延客户下次跟进日期。

    只接受 7/15/30/90 天档位；任务创建与客户日期更新在同一事务内。
    """
    if days not in QUICK_FOLLOWUP_DAYS.values():
        raise ValueError("快速跟进天数必须是 7 / 15 / 30 / 90")
    due = timezone.localdate() + timedelta(days=days)

    with transaction.atomic():
        task = create_task(
            task_type="followup",
            title=f"{customer.name} 客户回访",
            customer=customer,
            due_date=due,
            assignee=assignee,
            created_by=created_by,
        )
        customer.next_followup_date = due
        customer.save(update_fields=["next_followup_date", "updated_at"])
    return task


def overdue_tasks(user: User | None = None) -> QuerySet:
    """逾期待办：截止早于今天且未完成/未取消；user 给定时限本人相关。"""
    queryset = Task.objects.filter(due_date__lt=timezone.localdate()).exclude(
        status__in=_TERMINAL_STATUSES
    )
    if user is not None:
        queryset = queryset.filter(Q(assignee=user) | Q(created_by=user))
    return queryset


def tasks_due_between(start: date, end: date) -> QuerySet:
    """截止日期在 [start, end] 区间内且未完成/未取消的待办。"""
    return Task.objects.filter(due_date__gte=start, due_date__lte=end).exclude(
        status__in=_TERMINAL_STATUSES
    )
