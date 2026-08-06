"""工作事件 / 沟通记录 → 待办自动联动测试（T5.3，规格 §4.3 / §4.7 / §13）。

RED 先行。覆盖：事件/沟通带 next_followup_date 时自动生成待办
（title / task_type / due_date / content）、无 next_followup_date 不生成、
source_key 防重复、改期更新既有待办、软删联动取消待办、取消后重复软删不报错、
find_task_by_source / cancel_tasks_by_source 语义。
"""

from datetime import date

import pytest

from apps.accounts.models import User
from apps.activities.services import (
    create_communication,
    create_work_event,
    soft_delete_communication,
    soft_delete_work_event,
    update_communication,
    update_work_event,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.tasks.models import Task
from apps.tasks.services import cancel_tasks_by_source, complete_task, find_task_by_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


# ---------------------------------------------------------------------------
# WorkEvent → Task
# ---------------------------------------------------------------------------


def test_event_with_followup_creates_task(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="保单整理",
        event_type="policy_organize",
        next_step="月底前提醒续费",
        next_followup_date=date(2026, 7, 20),
        created_by=user,
    )

    tasks = Task.objects.filter(source_key=f"event:{event.pk}")
    assert tasks.count() == 1
    task = tasks.get()
    assert task.title == "跟进：保单整理"
    assert task.task_type == "policy_organize"
    assert task.customer == customer
    assert task.due_date == date(2026, 7, 20)
    assert task.content == "月底前提醒续费"
    assert task.created_by == user
    assert task.status == "open"


def test_event_without_followup_creates_no_task(user: User, customer: Customer) -> None:
    event = create_work_event(customer=customer, title="日常拜访", event_type="home_visit")

    assert not Task.objects.filter(source_key=f"event:{event.pk}").exists()


def test_event_type_maps_to_task_type(user: User, customer: Customer) -> None:
    cases: list[tuple[str, str]] = [
        ("first_meeting", "meeting"),
        ("phone_call", "call"),
        ("wechat", "wechat"),
        ("home_visit", "meeting"),
        ("material_collection", "prepare_materials"),
        ("claim_process", "claim_material"),
        ("customer_activity", "event"),
        ("other", "other"),
    ]
    for event_type, task_type in cases:
        event = create_work_event(
            customer=customer,
            title="t",
            event_type=event_type,
            next_followup_date=date(2026, 7, 10),
        )
        task = Task.objects.get(source_key=f"event:{event.pk}")
        assert task.task_type == task_type


def test_repeated_update_does_not_duplicate_task(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="电话沟通",
        event_type="phone_call",
        next_followup_date=date(2026, 7, 5),
    )

    for _ in range(3):
        update_work_event(event, summary="再次保存")

    assert Task.objects.filter(source_key=f"event:{event.pk}").count() == 1


def test_changing_followup_date_updates_existing_task(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="资料收集",
        event_type="material_collection",
        next_followup_date=date(2026, 7, 5),
    )
    task = Task.objects.get(source_key=f"event:{event.pk}")
    assert task.due_date == date(2026, 7, 5)

    update_work_event(event, next_followup_date=date(2026, 7, 12))

    task.refresh_from_db()
    assert task.due_date == date(2026, 7, 12)
    assert Task.objects.filter(source_key=f"event:{event.pk}").count() == 1


def test_soft_delete_event_cancels_task(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="保单整理",
        event_type="policy_organize",
        next_followup_date=date(2026, 7, 20),
    )
    task = Task.objects.get(source_key=f"event:{event.pk}")
    assert task.status == "open"

    soft_delete_work_event(event)

    task.refresh_from_db()
    assert task.status == "cancelled"
    assert task.cancelled_at is not None


def test_double_soft_delete_event_does_not_error(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="电话沟通",
        event_type="phone_call",
        next_followup_date=date(2026, 7, 5),
    )

    soft_delete_work_event(event)
    soft_delete_work_event(event)

    assert not Task.objects.filter(source_key=f"event:{event.pk}", status="open").exists()


# ---------------------------------------------------------------------------
# CommunicationRecord → Task
# ---------------------------------------------------------------------------


def test_communication_with_followup_creates_task(user: User, customer: Customer) -> None:
    comm = create_communication(
        customer=customer,
        channel="phone",
        next_plan="周四再联系",
        next_followup_date=date(2026, 7, 9),
        recorded_by=user,
    )

    tasks = Task.objects.filter(source_key=f"comm:{comm.pk}")
    assert tasks.count() == 1
    task = tasks.get()
    assert task.task_type == "call"
    assert task.title == "跟进：电话 林小明"
    assert task.customer == customer
    assert task.due_date == date(2026, 7, 9)
    assert task.content == "周四再联系"
    assert task.created_by == user


def test_communication_without_followup_creates_no_task(user: User, customer: Customer) -> None:
    comm = create_communication(customer=customer, channel="wechat", content="聊了续保")

    assert not Task.objects.filter(source_key=f"comm:{comm.pk}").exists()


@pytest.mark.parametrize(
    ("channel", "task_type"),
    [
        ("phone", "call"),
        ("video_call", "call"),
        ("wechat", "wechat"),
        ("meeting", "meeting"),
        ("home_visit", "meeting"),
        ("customer_visit", "meeting"),
        ("sms", "followup"),
        ("other", "followup"),
    ],
)
def test_communication_channel_maps_to_task_type(
    user: User, customer: Customer, channel: str, task_type: str
) -> None:
    comm = create_communication(
        customer=customer, channel=channel, next_followup_date=date(2026, 7, 9)
    )

    task = Task.objects.get(source_key=f"comm:{comm.pk}")
    assert task.task_type == task_type


def test_communication_update_does_not_duplicate(user: User, customer: Customer) -> None:
    comm = create_communication(
        customer=customer, channel="phone", next_followup_date=date(2026, 7, 9)
    )

    update_communication(comm, content="补充内容")
    update_communication(comm, quick_result="call_later")

    assert Task.objects.filter(source_key=f"comm:{comm.pk}").count() == 1


def test_soft_delete_communication_cancels_task(user: User, customer: Customer) -> None:
    comm = create_communication(
        customer=customer, channel="phone", next_followup_date=date(2026, 7, 9)
    )
    task = Task.objects.get(source_key=f"comm:{comm.pk}")

    soft_delete_communication(comm)

    task.refresh_from_db()
    assert task.status == "cancelled"


# ---------------------------------------------------------------------------
# find_task_by_source / cancel_tasks_by_source
# ---------------------------------------------------------------------------


def test_find_task_by_source_only_returns_open_task(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="电话沟通",
        event_type="phone_call",
        next_followup_date=date(2026, 7, 5),
    )
    key = f"event:{event.pk}"

    task = find_task_by_source(key)
    assert task is not None
    assert task.status == "open"

    complete_task(task)
    assert find_task_by_source(key) is None


def test_cancel_tasks_by_source_cancels_open_tasks(user: User, customer: Customer) -> None:
    event = create_work_event(
        customer=customer,
        title="电话沟通",
        event_type="phone_call",
        next_followup_date=date(2026, 7, 5),
    )
    key = f"event:{event.pk}"

    assert cancel_tasks_by_source(key) == 1
    task = Task.objects.get(source_key=key)
    assert task.status == "cancelled"

    assert cancel_tasks_by_source(key) == 0


def test_no_task_for_unknown_source(user: User, customer: Customer) -> None:
    assert find_task_by_source("event:00000000-0000-0000-0000-000000000000") is None
    assert cancel_tasks_by_source("comm:00000000-0000-0000-0000-000000000000") == 0
