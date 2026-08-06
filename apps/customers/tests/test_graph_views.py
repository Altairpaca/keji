"""T12.2 客户关系图页面测试（规格 §7 / ADR-010，RED 先行）。

覆盖 relationship_graph_page / referral_graph_page 两个 HTML 页面视图：
- 200 且包含 vis-network 本地脚本引用、graph-canvas 画布容器
- 手机端单层列表容器存在（lg:hidden 响应式切换）
- 无权限 403、匿名 302、不存在 404
"""

import uuid

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerStatus
from apps.customers.services.relations import create_relation

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def status(db: None) -> CustomerStatus:
    # 用非种子名（种子含 15 个默认状态，见 0002_seed_customer_status）
    customer_status: CustomerStatus = CustomerStatus.objects.create(name="高意向客户")
    return customer_status


def make_customer(name: str, user: User, *, status: CustomerStatus | None = None) -> Customer:
    customer: Customer = Customer.objects.create(
        name=name, owner=user, created_by=user, status=status
    )
    return customer


def make_pair(user: User, status: CustomerStatus) -> tuple[Customer, Customer]:
    a = make_customer("中心客户甲", user, status=status)
    b = make_customer("相关客户乙", user)
    create_relation(from_customer=a, to_customer=b, relation_type="spouse")
    return a, b


# ---------------------------------------------------------------------------
# relationship_graph_page（GET /customers/<uuid>/graph-page/）
# ---------------------------------------------------------------------------


def test_graph_page_renders(client: Client, user: User, status: CustomerStatus) -> None:
    a, _ = make_pair(user, status)
    client.force_login(user)

    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": a.pk}))

    assert resp.status_code == 200
    # 本地化 vis-network（无 CDN）：script 引用 + 画布容器
    assert b"vis-network.min.js" in resp.content
    assert b'id="graph-canvas"' in resp.content
    # 手机端单层列表容器（响应式：桌面画布 / 手机列表）
    assert b"lg:hidden" in resp.content


def test_graph_page_embeds_initial_data(client: Client, user: User, status: CustomerStatus) -> None:
    a, b = make_pair(user, status)
    client.force_login(user)

    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": a.pk}))

    assert resp.status_code == 200
    # json_script 注入初始图数据：中心 + 1 个邻居，且手机列表含相关客户名
    assert b"graph-data" in resp.content
    assert str(a.pk).encode() in resp.content
    assert str(b.pk).encode() in resp.content
    assert "相关客户乙".encode() in resp.content


def test_graph_page_mobile_list_has_relation_label(
    client: Client, user: User, status: CustomerStatus
) -> None:
    a, _ = make_pair(user, status)
    client.force_login(user)

    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": a.pk}))

    assert resp.status_code == 200
    assert "配偶".encode() in resp.content  # 列表项显示关系标签


def test_graph_page_empty_state(client: Client, user: User, status: CustomerStatus) -> None:
    a = make_customer("孤家寡人", user, status=status)
    client.force_login(user)

    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": a.pk}))

    assert resp.status_code == 200
    assert "暂无关系".encode() in resp.content
    assert b'id="graph-canvas"' not in resp.content


def test_graph_page_forbidden_without_permission(client: Client, db: None) -> None:
    u = User(username="noperm")
    u.save()
    c = Customer.objects.create(name="X", owner=u, created_by=u)
    client.force_login(u)

    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": c.pk}))
    assert resp.status_code == 403


def test_graph_page_anonymous_redirects(client: Client, user: User) -> None:
    a = make_customer("A", user)
    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": a.pk}))
    assert resp.status_code == 302


def test_graph_page_404_unknown_customer(client: Client, user: User) -> None:
    client.force_login(user)
    resp = client.get(reverse("customers:relationship_graph_page", kwargs={"pk": uuid.uuid4()}))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# referral_graph_page（GET /customers/<uuid>/referral-page/）
# ---------------------------------------------------------------------------


def test_referral_page_renders(client: Client, user: User, status: CustomerStatus) -> None:
    a = make_customer("转介绍中心", user, status=status)
    b = make_customer("转介绍下线", user)
    c = make_customer("配偶不在图内", user)
    create_relation(from_customer=a, to_customer=b, relation_type="referrer")
    create_relation(from_customer=a, to_customer=c, relation_type="spouse")  # 转介绍图不含
    client.force_login(user)

    resp = client.get(reverse("customers:referral_graph_page", kwargs={"pk": a.pk}))

    assert resp.status_code == 200
    assert b"vis-network.min.js" in resp.content
    assert b'id="graph-canvas"' in resp.content
    assert b"lg:hidden" in resp.content
    # 转介绍页数据源：referral-graph API + 转介绍图标题
    assert b"referral-graph" in resp.content
    assert "转介绍图".encode() in resp.content
    # 单层列表只含转介绍相关客户（配偶 c 不出现）
    assert "转介绍下线".encode() in resp.content
    assert "配偶不在图内".encode() not in resp.content


def test_referral_page_forbidden_without_permission(client: Client, db: None) -> None:
    u = User(username="noperm")
    u.save()
    c = Customer.objects.create(name="X", owner=u, created_by=u)
    client.force_login(u)

    resp = client.get(reverse("customers:referral_graph_page", kwargs={"pk": c.pk}))
    assert resp.status_code == 403


def test_referral_page_anonymous_redirects(client: Client, user: User) -> None:
    a = make_customer("A", user)
    resp = client.get(reverse("customers:referral_graph_page", kwargs={"pk": a.pk}))
    assert resp.status_code == 302
