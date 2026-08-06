"""T5.1 activities 服务层测试（RED 先行，规格 §4.3 / §4.7）。

覆盖：create_work_event（customer/title 必填、occurred_at 默认、全字段写入）、
update_work_event（部分更新、未知字段拒绝）、soft_delete/restore_work_event；
create_communication（customer 必填、occurred_at 默认、quick_result 合法值）、
update_communication、soft_delete/restore_communication。
"""

from datetime import date, datetime

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord, WorkEvent
from apps.activities.services import (
    create_communication,
    create_work_event,
    restore_communication,
    restore_work_event,
    soft_delete_communication,
    soft_delete_work_event,
    update_communication,
    update_work_event,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer

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
# create_work_event
# ---------------------------------------------------------------------------


def test_create_work_event_requires_customer(user: User) -> None:
    with pytest.raises(ValueError):
        create_work_event(title="拜访", customer=None)


def test_create_work_event_requires_non_empty_title(user: User, customer: Customer) -> None:
    with pytest.raises(ValueError):
        create_work_event(title="   ", customer=customer)


def test_create_work_event_defaults_occurred_at(user: User, customer: Customer) -> None:
    before = timezone.now()

    event = create_work_event(
        title="电话沟通", customer=customer, event_type="phone_call", created_by=user
    )

    assert event.occurred_at is not None
    assert before <= event.occurred_at <= timezone.now()
    assert event.title == "电话沟通"
    assert event.event_type == "phone_call"
    assert event.created_by == user
    assert event.owner is None
    assert event.summary == ""


def test_create_work_event_accepts_all_fields(user: User, customer: Customer) -> None:
    occurred = datetime(2026, 7, 2, 9, 30, tzinfo=timezone.get_current_timezone())

    event = create_work_event(
        customer=customer,
        title="保单整理",
        event_type="policy_organize",
        occurred_at=occurred,
        summary="整理全部有效保单",
        outcome="发现两份待续费",
        next_step="月底前提醒续费",
        next_followup_date=date(2026, 7, 20),
        created_by=user,
        owner=user,
    )

    assert event.occurred_at == occurred
    assert event.summary == "整理全部有效保单"
    assert event.outcome == "发现两份待续费"
    assert event.next_step == "月底前提醒续费"
    assert event.next_followup_date == date(2026, 7, 20)
    assert event.owner == user
    assert event.created_at is not None


def test_create_work_event_validation_failure_leaves_no_residue(
    user: User, customer: Customer
) -> None:
    before = WorkEvent.objects.count()

    with pytest.raises(ValueError):
        create_work_event(title="", customer=customer)

    assert WorkEvent.objects.count() == before


# ---------------------------------------------------------------------------
# update_work_event
# ---------------------------------------------------------------------------


def test_update_work_event_partial_update(user: User, customer: Customer) -> None:
    event = create_work_event(title="首次见面", customer=customer, event_type="first_meeting")
    created_at = event.created_at

    updated = update_work_event(event, outcome="对方有意向", next_followup_date=date(2026, 7, 10))

    assert updated.outcome == "对方有意向"
    assert updated.next_followup_date == date(2026, 7, 10)
    assert updated.title == "首次见面"
    assert updated.created_at == created_at
    assert updated.updated_at >= created_at
    fresh = WorkEvent.objects.get(pk=event.pk)
    assert fresh.outcome == "对方有意向"


def test_update_work_event_unknown_field_raises(user: User, customer: Customer) -> None:
    event = create_work_event(title="电话沟通", customer=customer, event_type="phone_call")

    with pytest.raises(ValueError):
        update_work_event(event, nonexistent_field="x")


# ---------------------------------------------------------------------------
# soft_delete / restore work_event
# ---------------------------------------------------------------------------


def test_soft_delete_work_event_hides_and_restore_recovers(user: User, customer: Customer) -> None:
    event = create_work_event(title="资料收集", customer=customer)

    soft_delete_work_event(event)

    assert WorkEvent.objects.filter(pk=event.pk).count() == 0
    assert WorkEvent.all_objects.get(pk=event.pk).is_deleted is True
    assert event.deleted_at is not None

    restore_work_event(event)

    assert WorkEvent.objects.get(pk=event.pk).is_deleted is False
    assert event.deleted_at is None


# ---------------------------------------------------------------------------
# create_communication
# ---------------------------------------------------------------------------


def test_create_communication_requires_customer(user: User) -> None:
    with pytest.raises(ValueError):
        create_communication(customer=None, channel="phone")


def test_create_communication_defaults_occurred_at(user: User, customer: Customer) -> None:
    before = timezone.now()

    comm = create_communication(
        customer=customer, channel="wechat", content="微信语音聊了续保", recorded_by=user
    )

    assert comm.occurred_at is not None
    assert before <= comm.occurred_at <= timezone.now()
    assert comm.channel == "wechat"
    assert comm.content == "微信语音聊了续保"
    assert comm.quick_result == ""
    assert comm.recorded_by == user


def test_create_communication_accepts_all_fields(user: User, customer: Customer) -> None:
    occurred = datetime(2026, 7, 3, 14, 0, tzinfo=timezone.get_current_timezone())

    comm = create_communication(
        customer=customer,
        channel="phone",
        occurred_at=occurred,
        quick_result="call_later",
        content="讨论重疾方案",
        customer_feedback="需要和家人商量",
        next_plan="周四再联系",
        next_followup_date=date(2026, 7, 9),
        recorded_by=user,
    )

    assert comm.occurred_at == occurred
    assert comm.quick_result == "call_later"
    assert comm.customer_feedback == "需要和家人商量"
    assert comm.next_plan == "周四再联系"
    assert comm.next_followup_date == date(2026, 7, 9)
    assert comm.recorded_by == user


def test_create_communication_rejects_invalid_quick_result(user: User, customer: Customer) -> None:
    before = CommunicationRecord.objects.count()

    with pytest.raises(ValueError):
        create_communication(customer=customer, channel="phone", quick_result="bogus")

    assert CommunicationRecord.objects.count() == before


def test_create_communication_accepts_blank_quick_result(user: User, customer: Customer) -> None:
    comm = create_communication(customer=customer, channel="sms", quick_result="")

    assert comm.quick_result == ""


# ---------------------------------------------------------------------------
# update_communication
# ---------------------------------------------------------------------------


def test_update_communication_partial_update(user: User, customer: Customer) -> None:
    comm = create_communication(customer=customer, channel="phone")
    created_at = comm.created_at

    updated = update_communication(
        comm, quick_result="wants_meeting", next_followup_date=date(2026, 7, 15)
    )

    assert updated.quick_result == "wants_meeting"
    assert updated.next_followup_date == date(2026, 7, 15)
    assert updated.channel == "phone"
    assert updated.created_at == created_at
    assert updated.updated_at >= created_at
    fresh = CommunicationRecord.objects.get(pk=comm.pk)
    assert fresh.quick_result == "wants_meeting"


def test_update_communication_rejects_invalid_quick_result(user: User, customer: Customer) -> None:
    comm = create_communication(customer=customer, channel="phone")

    with pytest.raises(ValueError):
        update_communication(comm, quick_result="nonsense")

    fresh = CommunicationRecord.objects.get(pk=comm.pk)
    assert fresh.quick_result == ""


def test_update_communication_unknown_field_raises(user: User, customer: Customer) -> None:
    comm = create_communication(customer=customer, channel="phone")

    with pytest.raises(ValueError):
        update_communication(comm, nonexistent_field="x")


# ---------------------------------------------------------------------------
# soft_delete / restore communication
# ---------------------------------------------------------------------------


def test_soft_delete_communication_hides_and_restore_recovers(
    user: User, customer: Customer
) -> None:
    comm = create_communication(customer=customer, channel="meeting")

    soft_delete_communication(comm)

    assert CommunicationRecord.objects.filter(pk=comm.pk).count() == 0
    assert CommunicationRecord.all_objects.get(pk=comm.pk).is_deleted is True
    assert comm.deleted_at is not None

    restore_communication(comm)

    assert CommunicationRecord.objects.get(pk=comm.pk).is_deleted is False
    assert comm.deleted_at is None
