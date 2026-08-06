"""首页视图测试（T9.2，规格 §14）。

覆盖：匿名重定向登录、无权限 403、有权限渲染队列卡与统计卡。
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import CommunicationRecord
from apps.customers.models import Customer
from apps.tasks.models import Task

User = get_user_model()


@pytest.mark.django_db
def test_home_redirects_anonymous_user_to_login(client: Client) -> None:
    resp = client.get(reverse("dashboard:home"))
    assert resp.status_code == 302
    assert resp.url == reverse("accounts:login")


@pytest.mark.django_db
def test_home_forbidden_without_permission(client: Client) -> None:
    User.objects.create_user(username="plain", password="pw123456")
    assert client.login(username="plain", password="pw123456")
    resp = client.get(reverse("dashboard:home"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_home_renders_queue_cards_for_viewer(client: Client) -> None:
    User.objects.create_user(username="viewer", password="pw123456", can_view_customers=True)
    assert client.login(username="viewer", password="pw123456")
    resp = client.get(reverse("dashboard:home"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "工作队列" in body
    assert "今天必须处理" in body
    assert "逾期任务" in body
    assert "客户总数" in body


@pytest.mark.django_db
def test_home_shows_queue_item_titles(client: Client) -> None:
    viewer = User.objects.create_user(
        username="viewer", password="pw123456", can_view_customers=True
    )
    assert client.login(username="viewer", password="pw123456")

    customer = Customer.objects.create(name="林小明", age_note="约35岁")
    CommunicationRecord.objects.create(customer=customer, channel="phone", content="跟进")
    Task.objects.create(
        title="今日回访林小明",
        due_date=timezone.localdate(),
        status=Task.Status.OPEN,
        assignee=viewer,
        created_by=viewer,
    )

    resp = client.get(reverse("dashboard:home"))
    assert resp.status_code == 200
    assert "今日回访林小明" in resp.content.decode()
