"""T5.2 客户统一时间线测试（RED 先行，规格 §8 / §19）。

覆盖 build_timeline 聚合（工作事件 + 沟通 + 待办 + 文件上传）、occurred_at
倒序、limit 截断、软删隐藏、无数据客户、空 customer 校验、timeline_json
序列化；customer_timeline 视图权限矩阵（匿名 302 / 无权限 403 / 查看 200）
与条目渲染。registry 预留 POLICY_CHANGE / CLAIM_CHANGE 扩展点由
T7.2 / T8 任务补充测试。
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.services import (
    create_communication,
    create_work_event,
    soft_delete_communication,
    soft_delete_work_event,
)
from apps.activities.services.timeline import (
    COMMUNICATION,
    DOCUMENT_UPLOAD,
    TASK,
    WORK_EVENT,
    build_timeline,
    timeline_json,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Document
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(db: None) -> User:
    """查看 + 管理权限的用户。"""
    u = User(username="manager", can_view_customers=True, can_manage_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def viewer(db: None) -> User:
    """仅有查看权限的用户。"""
    u = User(username="viewer", can_view_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def plain(db: None) -> User:
    """无任何权限位的用户。"""
    u = User(username="plain")
    u.save()
    return u


@pytest.fixture
def customer(manager: User) -> Customer:
    return create_customer(name="林小明", owner=manager, created_by=manager, age_note="约35岁")


def _make_document(customer: Customer, *, title: str = "客户证件照") -> Document:
    doc: Document = Document.objects.create(
        original_name="证件照.jpg",
        storage_key=f"timeline-{uuid.uuid4()}",
        mime_type="image/jpeg",
        size=1024,
        sha256="0" * 64,
        title=title,
        note="投保资料",
    )
    doc.customers.add(customer)
    return doc


def _seed_full_customer(customer: Customer) -> None:
    """造 1 客户 + 1 工作事件 + 1 沟通 + 1 文档上传 + 1 待办（时间倒序可判定）。

    工作事件（3 天前）→ 沟通（2 天前）→ 文档上传（已存时间戳）→ 待办（最新）。
    """
    now = timezone.now()
    create_work_event(
        title="电话聊续保",
        customer=customer,
        event_type="phone_call",
        occurred_at=now - timedelta(days=3),
    )
    create_communication(
        customer=customer,
        channel="wechat",
        occurred_at=now - timedelta(days=2),
        content="客户询问重疾费率",
    )
    _make_document(customer)
    Task.objects.create(customer=customer, title="跟进续保", due_date=timezone.localdate())


# ---------------------------------------------------------------------------
# build_timeline 聚合
# ---------------------------------------------------------------------------


def test_build_timeline_aggregates_four_types_in_desc_order(customer: Customer) -> None:
    _seed_full_customer(customer)

    entries = build_timeline(customer)

    assert len(entries) == 4
    # 待办（created_at 最新）→ 文档上传 → 沟通 → 工作事件（最旧）
    assert [entry.type for entry in entries] == [TASK, DOCUMENT_UPLOAD, COMMUNICATION, WORK_EVENT]
    assert entries[0].title == "跟进续保"
    assert entries[1].title == "客户证件照"
    assert entries[2].title == "微信"
    assert entries[3].title == "电话聊续保"
    assert entries[0].customer_pk == str(customer.pk)


def test_build_timeline_respects_limit(customer: Customer) -> None:
    now = timezone.now()
    for i in range(6):
        create_work_event(
            title=f"事件{i}",
            customer=customer,
            event_type="other",
            occurred_at=now - timedelta(days=i),
        )

    entries = build_timeline(customer, limit=3)

    assert len(entries) == 3
    assert [entry.title for entry in entries] == ["事件0", "事件1", "事件2"]


def test_build_timeline_excludes_soft_deleted_entries(customer: Customer) -> None:
    kept = create_work_event(title="保留事件", customer=customer, event_type="other")
    gone_event = create_work_event(title="已删除事件", customer=customer, event_type="other")
    soft_delete_work_event(gone_event)
    gone_comm = create_communication(customer=customer, channel="phone")
    soft_delete_communication(gone_comm)

    entries = build_timeline(customer)

    titles = [entry.title for entry in entries]
    assert kept.title in titles
    assert gone_event.title not in titles
    assert gone_comm.get_channel_display() not in titles


def test_build_timeline_customer_without_data_returns_empty(customer: Customer) -> None:
    assert build_timeline(customer) == []


def test_build_timeline_rejects_none_customer() -> None:
    with pytest.raises(ValueError):
        build_timeline(None)


# ---------------------------------------------------------------------------
# timeline_json 序列化
# ---------------------------------------------------------------------------


def test_timeline_json_serializes_entries(customer: Customer) -> None:
    create_work_event(
        title="电话聊续保",
        customer=customer,
        event_type="phone_call",
        occurred_at=timezone.now(),
    )

    data = timeline_json(customer)

    assert len(data) == 1
    assert data[0]["type"] == WORK_EVENT
    assert data[0]["title"] == "电话聊续保"
    assert data[0]["customer_pk"] == str(customer.pk)
    assert "occurred_at" in data[0]


# ---------------------------------------------------------------------------
# customer_timeline 视图
# ---------------------------------------------------------------------------


def test_customer_timeline_view_anonymous_redirects_to_login(
    client: Any, customer: Customer
) -> None:
    response = client.get(reverse("activities:customer_timeline", args=[str(customer.pk)]))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_customer_timeline_view_plain_user_gets_403(
    client: Any, plain: User, customer: Customer
) -> None:
    client.force_login(plain)

    response = client.get(reverse("activities:customer_timeline", args=[str(customer.pk)]))

    assert response.status_code == 403


def test_customer_timeline_view_returns_entries(
    client: Any, viewer: User, customer: Customer
) -> None:
    client.force_login(viewer)
    create_work_event(title="电话聊续保", customer=customer, event_type="phone_call")

    response = client.get(reverse("activities:customer_timeline", args=[str(customer.pk)]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "电话聊续保" in content
    assert "工作事件" in content


def test_customer_timeline_view_unknown_customer_404(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(reverse("activities:customer_timeline", args=[str(uuid.uuid4())]))

    assert response.status_code == 404
