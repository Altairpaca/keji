"""T5.1 activities 模型测试（RED 先行，规格 §4.3 / §4.7）。

覆盖：WorkEvent 字段与默认、__str__、choices、客户 CASCADE、用户 SET_NULL、
软删除；CommunicationRecord 字段与默认、__str__、choices、软删除。
"""

from datetime import date, datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord, WorkEvent
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
# WorkEvent 基本字段与默认
# ---------------------------------------------------------------------------


def test_work_event_str_returns_title(user: User, customer: Customer) -> None:
    event = WorkEvent.objects.create(
        customer=customer, title="首次拜访", event_type="first_meeting", created_by=user
    )

    assert str(event) == "首次拜访"


def test_work_event_requires_customer_and_title(user: User, customer: Customer) -> None:
    # 缺 customer → customer_id 为 NULL 触发非空约束
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkEvent.objects.create(title="无客户事件")
    # 显式传入 title=None → 非空约束
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkEvent.objects.create(customer=customer, title=None)


def test_work_event_defaults(user: User, customer: Customer) -> None:
    event = WorkEvent.objects.create(customer=customer, title="电话沟通", event_type="phone_call")

    assert event.event_type == "phone_call"
    assert event.occurred_at is not None
    assert abs((timezone.now() - event.occurred_at).total_seconds()) < 60
    assert event.summary == ""
    assert event.outcome == ""
    assert event.next_step == ""
    assert event.next_followup_date is None
    assert event.created_by is None
    assert event.owner is None
    assert event.created_at is not None
    assert event.updated_at is not None


def test_work_event_event_type_choices_nine() -> None:
    expected = {
        "first_meeting": "第一次见面",
        "phone_call": "电话沟通",
        "wechat": "微信沟通",
        "policy_organize": "保单整理",
        "material_collection": "资料收集",
        "claim_process": "理赔处理",
        "customer_activity": "客户活动",
        "home_visit": "上门服务",
        "other": "其他工作过程",
    }

    choices = dict(WorkEvent.EventType.choices)

    assert len(choices) == 9
    assert choices == expected


def test_work_event_title_max_length() -> None:
    field = WorkEvent._meta.get_field("title")

    assert field.max_length == 200
    assert field.blank is False
    assert field.null is False


def test_work_event_occurred_at_db_index() -> None:
    assert WorkEvent._meta.get_field("occurred_at").db_index is True


def test_work_event_related_policy_not_present() -> None:
    """related_policy 字段 T7 才连，本任务不得存在。"""
    assert not hasattr(WorkEvent, "related_policy")
    assert not hasattr(WorkEvent._meta, "related_policy")


# ---------------------------------------------------------------------------
# WorkEvent 关联与软删除
# ---------------------------------------------------------------------------


def test_work_event_customer_cascade(user: User, customer: Customer) -> None:
    event = WorkEvent.objects.create(customer=customer, title="上门服务", created_by=user)

    assert set(customer.work_events.all()) == {event}

    customer.hard_delete()

    assert WorkEvent.objects.filter(pk=event.pk).count() == 0


def test_work_event_created_by_owner_set_null(user: User, customer: Customer) -> None:
    event = WorkEvent.objects.create(
        customer=customer, title="资料收集", created_by=user, owner=user
    )

    user.delete()

    event.refresh_from_db()
    assert event.created_by is None
    assert event.owner is None


def test_work_event_soft_delete_hides_and_restore_recovers(user: User, customer: Customer) -> None:
    event = WorkEvent.objects.create(customer=customer, title="保单整理", created_by=user)

    event.soft_delete()

    assert WorkEvent.objects.filter(pk=event.pk).count() == 0
    assert WorkEvent.all_objects.get(pk=event.pk).is_deleted is True

    event.restore()

    assert WorkEvent.objects.get(pk=event.pk).is_deleted is False
    assert event.deleted_at is None


# ---------------------------------------------------------------------------
# CommunicationRecord 基本字段与默认
# ---------------------------------------------------------------------------


def test_communication_str_returns_customer_and_channel_display(
    user: User, customer: Customer
) -> None:
    comm = CommunicationRecord.objects.create(customer=customer, channel="phone")

    assert str(comm) == "林小明 电话"


def test_communication_defaults(user: User, customer: Customer) -> None:
    comm = CommunicationRecord.objects.create(customer=customer, channel="wechat")

    assert comm.occurred_at is not None
    assert abs((timezone.now() - comm.occurred_at).total_seconds()) < 60
    assert comm.quick_result == ""
    assert comm.content == ""
    assert comm.customer_feedback == ""
    assert comm.next_plan == ""
    assert comm.next_followup_date is None
    assert comm.recorded_by is None
    assert comm.created_at is not None
    assert comm.updated_at is not None


def test_communication_channel_choices_nine() -> None:
    expected = {
        "phone": "电话",
        "wechat": "微信",
        "meeting": "见面",
        "company_activity": "公司活动",
        "home_visit": "上门服务",
        "customer_visit": "客户来访",
        "video_call": "视频通话",
        "sms": "短信",
        "other": "其他",
    }

    choices = dict(CommunicationRecord.Channel.choices)

    assert len(choices) == 9
    assert choices == expected


def test_communication_quick_result_choices_ten() -> None:
    expected = {
        "missed": "未接",
        "hung_up": "挂断",
        "power_off": "关机",
        "empty_number": "空号",
        "declined": "接听但拒绝",
        "wants_wechat": "愿意微信联系",
        "wants_meeting": "愿意见面",
        "time_uncertain": "时间不确定",
        "call_later": "要求稍后联系",
        "not_needed": "明确不需要",
    }

    choices = dict(CommunicationRecord.QuickResult.choices)

    assert len(choices) == 10
    assert choices == expected


def test_communication_quick_result_blank_allowed(user: User, customer: Customer) -> None:
    field = CommunicationRecord._meta.get_field("quick_result")

    assert field.blank is True
    assert field.default == ""


def test_communication_occurred_at_db_index() -> None:
    assert CommunicationRecord._meta.get_field("occurred_at").db_index is True


def test_communication_accepts_all_fields(user: User, customer: Customer) -> None:
    comm = CommunicationRecord.objects.create(
        customer=customer,
        channel="phone",
        occurred_at=datetime(2026, 7, 1, 10, 30, tzinfo=timezone.get_current_timezone()),
        quick_result="call_later",
        content="客户想了解重疾险",
        customer_feedback="态度积极",
        next_plan="三天后再次联系",
        next_followup_date=date(2026, 7, 4),
        recorded_by=user,
    )

    assert comm.channel == "phone"
    assert comm.quick_result == "call_later"
    assert comm.content == "客户想了解重疾险"
    assert comm.customer_feedback == "态度积极"
    assert comm.next_plan == "三天后再次联系"
    assert comm.next_followup_date == date(2026, 7, 4)
    assert comm.recorded_by == user


# ---------------------------------------------------------------------------
# CommunicationRecord 关联与软删除
# ---------------------------------------------------------------------------


def test_communication_customer_cascade(user: User, customer: Customer) -> None:
    comm = CommunicationRecord.objects.create(customer=customer, channel="sms")

    assert set(customer.communications.all()) == {comm}

    customer.hard_delete()

    assert CommunicationRecord.objects.filter(pk=comm.pk).count() == 0


def test_communication_recorded_by_set_null(user: User, customer: Customer) -> None:
    comm = CommunicationRecord.objects.create(customer=customer, channel="wechat", recorded_by=user)

    user.delete()

    comm.refresh_from_db()
    assert comm.recorded_by is None


def test_communication_soft_delete_hides_and_restore_recovers(
    user: User, customer: Customer
) -> None:
    comm = CommunicationRecord.objects.create(customer=customer, channel="phone")

    comm.soft_delete()

    assert CommunicationRecord.objects.filter(pk=comm.pk).count() == 0
    assert CommunicationRecord.all_objects.get(pk=comm.pk).is_deleted is True

    comm.restore()

    assert CommunicationRecord.objects.get(pk=comm.pk).is_deleted is False
    assert comm.deleted_at is None
