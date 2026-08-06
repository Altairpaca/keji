"""T5.1 activities 视图测试（RED 先行，规格 §4.3 / §4.7）。

覆盖：权限矩阵（匿名重定向 / 查看 need can_view_customers / 写 need
can_manage_customers）、创建后写入正确、编辑 / 软删、列表筛选与分页。
"""

from datetime import date, datetime
from typing import Any

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord, WorkEvent
from apps.activities.services import (
    create_communication,
    create_work_event,
    soft_delete_work_event,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer

pytestmark = pytest.mark.django_db


@pytest.fixture
def viewer(db: None) -> User:
    """仅有查看权限的普通用户。"""
    u = User(username="viewer", can_view_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def manager(db: None) -> User:
    """查看 + 管理权限的用户。"""
    u = User(username="manager", can_view_customers=True, can_manage_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def plain(db: None) -> User:
    """无任何权限位的普通用户。"""
    u = User(username="plain")
    u.save()
    return u


@pytest.fixture
def customer(manager: User) -> Customer:
    return create_customer(name="林小明", owner=manager, created_by=manager, age_note="约35岁")


@pytest.fixture
def second_customer(manager: User) -> Customer:
    return create_customer(name="王秀英", owner=manager, created_by=manager, age_note="约40岁")


# ---------------------------------------------------------------------------
# 权限矩阵
# ---------------------------------------------------------------------------


def test_event_list_anonymous_redirects_to_login(client: Any) -> None:
    response = client.get(reverse("activities:event_list"))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_event_list_plain_user_without_permission_gets_403(client: Any, plain: User) -> None:
    client.force_login(plain)

    response = client.get(reverse("activities:event_list"))

    assert response.status_code == 403


def test_event_list_viewer_allowed(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(reverse("activities:event_list"))

    assert response.status_code == 200


def test_write_views_require_manage_permission(
    client: Any, viewer: User, customer: Customer
) -> None:
    client.force_login(viewer)

    assert client.get(reverse("activities:work_event_create")).status_code == 403
    assert client.get(reverse("activities:communication_create")).status_code == 403
    assert client.post(reverse("activities:communication_quick"), data={}).status_code == 403


def test_write_views_manager_allowed(client: Any, manager: User) -> None:
    client.force_login(manager)

    assert client.get(reverse("activities:work_event_create")).status_code == 200
    assert client.get(reverse("activities:communication_create")).status_code == 200


def test_write_views_anonymous_redirected(client: Any) -> None:
    assert client.get(reverse("activities:work_event_create")).status_code == 302
    assert client.get(reverse("activities:communication_create")).status_code == 302


def test_convenience_customer_event_route_requires_manage(
    client: Any, viewer: User, customer: Customer
) -> None:
    client.force_login(viewer)

    response = client.get(reverse("work_event_create_for_customer", args=[str(customer.pk)]))

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 工作事件创建 / 编辑 / 删除
# ---------------------------------------------------------------------------


def test_work_event_create_preselects_customer(
    client: Any, manager: User, customer: Customer
) -> None:
    client.force_login(manager)

    response = client.get(reverse("activities:work_event_create"), {"customer": str(customer.pk)})

    assert response.status_code == 200
    assert customer.name in response.content.decode()


def test_work_event_create_writes_correct_fields(
    client: Any, manager: User, customer: Customer
) -> None:
    client.force_login(manager)

    response = client.post(
        reverse("activities:work_event_create"),
        {
            "customer": str(customer.pk),
            "event_type": "phone_call",
            "title": "沟通续保意向",
            "occurred_at": "2026-07-05T10:00",
            "summary": "客户表示考虑续保",
            "outcome": "两周内给答复",
            "next_step": "7/20 跟进",
            "next_followup_date": "2026-07-20",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("activities:event_list")
    event = WorkEvent.objects.get()
    assert event.customer == customer
    assert event.event_type == "phone_call"
    assert event.title == "沟通续保意向"
    assert event.summary == "客户表示考虑续保"
    assert event.outcome == "两周内给答复"
    assert event.next_step == "7/20 跟进"
    assert event.next_followup_date == date(2026, 7, 20)
    assert event.created_by == manager
    assert event.owner == manager


def test_work_event_create_via_customer_route(
    client: Any, manager: User, customer: Customer
) -> None:
    client.force_login(manager)

    response = client.post(
        reverse("work_event_create_for_customer", args=[str(customer.pk)]),
        {
            "customer": str(customer.pk),
            "event_type": "home_visit",
            "title": "上门送资料",
            "occurred_at": "2026-07-06T15:30",
        },
    )

    assert response.status_code == 302
    event = WorkEvent.objects.get()
    assert event.customer == customer
    assert event.event_type == "home_visit"
    assert timezone.localtime(event.occurred_at).strftime("%Y-%m-%dT%H:%M") == "2026-07-06T15:30"


def test_work_event_create_invalid_form_rerenders(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(reverse("activities:work_event_create"), {"title": ""})

    assert response.status_code == 200
    assert WorkEvent.objects.count() == 0


def test_work_event_edit_updates_fields(client: Any, manager: User, customer: Customer) -> None:
    client.force_login(manager)
    event = create_work_event(title="首次见面", customer=customer, event_type="first_meeting")

    response = client.post(
        reverse("activities:work_event_edit", args=[str(event.pk)]),
        {
            "customer": str(customer.pk),
            "event_type": "wechat",
            "title": "微信沟通",
            "occurred_at": "2026-07-07T09:00",
            "outcome": "约好下次见面",
        },
    )

    assert response.status_code == 302
    event.refresh_from_db()
    assert event.title == "微信沟通"
    assert event.event_type == "wechat"
    assert event.outcome == "约好下次见面"


def test_work_event_delete_soft_deletes(client: Any, manager: User, customer: Customer) -> None:
    client.force_login(manager)
    event = create_work_event(title="资料收集", customer=customer)

    response = client.post(reverse("activities:work_event_delete", args=[str(event.pk)]))

    assert response.status_code == 302
    assert response.url == reverse("activities:event_list")
    assert WorkEvent.objects.filter(pk=event.pk).count() == 0
    assert WorkEvent.all_objects.get(pk=event.pk).is_deleted is True


# ---------------------------------------------------------------------------
# 沟通记录创建 / 快捷表单 / 编辑 / 删除
# ---------------------------------------------------------------------------


def test_communication_create_writes_correct_fields(
    client: Any, manager: User, customer: Customer
) -> None:
    client.force_login(manager)

    response = client.post(
        reverse("activities:communication_create"),
        {
            "customer": str(customer.pk),
            "channel": "phone",
            "occurred_at": "2026-07-08T11:00",
            "quick_result": "call_later",
            "content": "客户询问重疾费率",
            "customer_feedback": "语气友善",
            "next_plan": "周四再联系",
            "next_followup_date": "2026-07-09",
        },
    )

    assert response.status_code == 302
    comm = CommunicationRecord.objects.get()
    assert comm.customer == customer
    assert comm.channel == "phone"
    assert comm.quick_result == "call_later"
    assert comm.content == "客户询问重疾费率"
    assert comm.customer_feedback == "语气友善"
    assert comm.next_plan == "周四再联系"
    assert comm.next_followup_date == date(2026, 7, 9)
    assert comm.recorded_by == manager


def test_communication_quick_htmx_creates_record(
    client: Any, manager: User, customer: Customer
) -> None:
    client.force_login(manager)

    response = client.post(
        reverse("activities:communication_quick"),
        {
            "customer": str(customer.pk),
            "channel": "phone",
            "occurred_at": "2026-07-08T12:00",
            "quick_result": "missed",
            "next_plan": "下午再拨一次",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    comm = CommunicationRecord.objects.get()
    assert comm.channel == "phone"
    assert comm.quick_result == "missed"
    assert comm.recorded_by == manager
    assert "下午再拨一次" in response.content.decode()


def test_communication_quick_invalid_form_rerenders_partial(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(
        reverse("activities:communication_quick"),
        {"channel": "phone"},  # 缺 customer
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert CommunicationRecord.objects.count() == 0


def test_communication_edit_updates_fields(client: Any, manager: User, customer: Customer) -> None:
    client.force_login(manager)
    comm = create_communication(customer=customer, channel="wechat")

    response = client.post(
        reverse("activities:communication_edit", args=[str(comm.pk)]),
        {
            "customer": str(customer.pk),
            "channel": "phone",
            "occurred_at": "2026-07-10T10:00",
            "quick_result": "wants_meeting",
            "content": "改约当面沟通",
        },
    )

    assert response.status_code == 302
    comm.refresh_from_db()
    assert comm.channel == "phone"
    assert comm.quick_result == "wants_meeting"
    assert comm.content == "改约当面沟通"


def test_communication_delete_soft_deletes(client: Any, manager: User, customer: Customer) -> None:
    client.force_login(manager)
    comm = create_communication(customer=customer, channel="sms")

    response = client.post(reverse("activities:communication_delete", args=[str(comm.pk)]))

    assert response.status_code == 302
    assert CommunicationRecord.objects.filter(pk=comm.pk).count() == 0
    assert CommunicationRecord.all_objects.get(pk=comm.pk).is_deleted is True


# ---------------------------------------------------------------------------
# 列表筛选 / 分页 / 软删隐藏
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_events(manager: User, customer: Customer, second_customer: Customer) -> None:
    create_work_event(
        customer=customer,
        title="电话聊续保",
        event_type="phone_call",
        occurred_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.get_current_timezone()),
    )
    create_work_event(
        customer=second_customer,
        title="上门拜访",
        event_type="home_visit",
        occurred_at=datetime(2026, 7, 2, 11, 0, tzinfo=timezone.get_current_timezone()),
    )
    create_work_event(
        customer=customer,
        title="整理保单",
        event_type="policy_organize",
        occurred_at=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.get_current_timezone()),
    )


def test_event_list_orders_by_occurred_at_desc(
    client: Any, viewer: User, mixed_events: None
) -> None:
    client.force_login(viewer)

    response = client.get(reverse("activities:event_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert content.index("整理保单") < content.index("上门拜访") < content.index("电话聊续保")


def test_event_list_filters_by_type(client: Any, viewer: User, mixed_events: None) -> None:
    client.force_login(viewer)

    response = client.get(reverse("activities:event_list"), {"type": "phone_call"})
    content = response.content.decode()

    assert "电话聊续保" in content
    assert "上门拜访" not in content
    assert "整理保单" not in content


def test_event_list_filters_by_customer(
    client: Any, viewer: User, mixed_events: None, customer: Customer
) -> None:
    client.force_login(viewer)

    response = client.get(reverse("activities:event_list"), {"customer": str(customer.pk)})
    content = response.content.decode()

    assert "电话聊续保" in content
    assert "整理保单" in content
    assert "上门拜访" not in content


def test_event_list_hides_soft_deleted(client: Any, viewer: User, customer: Customer) -> None:
    client.force_login(viewer)
    kept = create_work_event(title="保留事件", customer=customer)
    gone = create_work_event(title="已删除事件", customer=customer)
    soft_delete_work_event(gone)

    response = client.get(reverse("activities:event_list"))
    content = response.content.decode()

    assert kept.title in content
    assert gone.title not in content


def test_event_list_paginates(client: Any, viewer: User, customer: Customer) -> None:
    client.force_login(viewer)
    for i in range(21):
        create_work_event(title=f"事件{i:02d}", customer=customer, event_type="other")

    page1 = client.get(reverse("activities:event_list"))
    page2 = client.get(reverse("activities:event_list"), {"page": "2"})

    # -occurred_at 排序：事件20 最新在第一页，事件00 最旧在第二页
    assert "事件20" in page1.content.decode()
    assert "事件00" not in page1.content.decode()
    assert "事件00" in page2.content.decode()
