"""T12.1 客户关系图 JSON API 测试（规格 §7 / ADR-010，RED 先行）。

覆盖：
- build_relationship_graph：BFS 层级展开、环防死循环、无向单边 / referrer 有向、
  label / color、软删客户过滤、status 名、is_center 标记、max_depth 校验
- referral_graph：只沿 referrer / same_household 关系展开（转介绍图）
- 视图：200 JSON 结构、无权限 403、不存在 404、depth 参数生效
"""

import uuid

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerStatus
from apps.customers.services.graph import (
    GraphNode,
    RelationshipGraph,
    build_relationship_graph,
    referral_graph,
)
from apps.customers.services.relations import create_relation

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def status(db: None) -> CustomerStatus:
    customer_status: CustomerStatus = CustomerStatus.objects.create(name="潜力客户")
    return customer_status


def make_customer(name: str, user: User, *, status: CustomerStatus | None = None) -> Customer:
    customer: Customer = Customer.objects.create(
        name=name, owner=user, created_by=user, status=status
    )
    return customer


def node_map(data: RelationshipGraph) -> dict[str, GraphNode]:
    nodes = data["nodes"]
    assert isinstance(nodes, list)
    return {str(node["id"]): node for node in nodes}


# ---------------------------------------------------------------------------
# build_relationship_graph：BFS 层级
# ---------------------------------------------------------------------------


def test_chain_depth_expansion(user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    c = make_customer("C", user)
    d = make_customer("D", user)
    create_relation(from_customer=a, to_customer=b, relation_type="referrer")
    create_relation(from_customer=b, to_customer=c, relation_type="referrer")
    create_relation(from_customer=c, to_customer=d, relation_type="referrer")

    depth1 = build_relationship_graph(a, max_depth=1)
    nodes1 = node_map(depth1)
    assert set(nodes1) == {str(a.pk), str(b.pk)}
    assert nodes1[str(b.pk)]["depth"] == 1

    depth2 = build_relationship_graph(a, max_depth=2)
    nodes2 = node_map(depth2)
    assert set(nodes2) == {str(a.pk), str(b.pk), str(c.pk)}
    assert str(d.pk) not in nodes2
    assert nodes2[str(c.pk)]["depth"] == 2


# ---------------------------------------------------------------------------
# 环：不无限循环
# ---------------------------------------------------------------------------


def test_ring_terminates(user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    c = make_customer("C", user)
    create_relation(from_customer=a, to_customer=b, relation_type="spouse")
    create_relation(from_customer=b, to_customer=c, relation_type="spouse")
    create_relation(from_customer=c, to_customer=a, relation_type="spouse")

    data = build_relationship_graph(a, max_depth=5)
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 3


# ---------------------------------------------------------------------------
# 边：无向单边 / referrer 有向 / label / color
# ---------------------------------------------------------------------------


def test_undirected_single_edge(user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    create_relation(from_customer=a, to_customer=b, relation_type="spouse")

    edges = build_relationship_graph(a)["edges"]
    assert len(edges) == 1
    edge = edges[0]
    assert edge["from"] == str(a.pk)
    assert edge["to"] == str(b.pk)
    assert edge["relation_type"] == "spouse"
    assert edge["label"] == "配偶"
    assert edge["color"] == "#e11d48"


def test_referrer_directed_edges_preserved(user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    create_relation(from_customer=a, to_customer=b, relation_type="referrer")
    create_relation(from_customer=b, to_customer=a, relation_type="referrer")

    edges = build_relationship_graph(a)["edges"]
    assert len(edges) == 2
    keys = {(e["from"], e["to"]) for e in edges}
    assert (str(a.pk), str(b.pk)) in keys
    assert (str(b.pk), str(a.pk)) in keys
    assert all(e["label"] == "介绍人" for e in edges)
    assert all(e["color"] == "#f59e0b" for e in edges)


# ---------------------------------------------------------------------------
# 软删过滤 / status / is_center
# ---------------------------------------------------------------------------


def test_soft_deleted_customer_excluded(user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    create_relation(from_customer=a, to_customer=b, relation_type="spouse")
    b.soft_delete()

    data = build_relationship_graph(a, max_depth=2)
    assert set(node_map(data)) == {str(a.pk)}
    assert data["edges"] == []


def test_status_name_and_is_center(user: User, status: CustomerStatus) -> None:
    a = make_customer("A", user, status=status)
    b = make_customer("B", user)  # 无状态
    create_relation(from_customer=a, to_customer=b, relation_type="family")

    nodes = node_map(build_relationship_graph(a))
    center = nodes[str(a.pk)]
    assert center["is_center"] is True
    assert center["status"] == "潜力客户"
    assert center["depth"] == 0
    other = nodes[str(b.pk)]
    assert other["is_center"] is False
    assert other["status"] == ""
    assert other["depth"] == 1


def test_max_depth_validation(user: User) -> None:
    a = make_customer("A", user)
    with pytest.raises(ValueError):
        build_relationship_graph(a, max_depth=0)
    with pytest.raises(ValueError):
        build_relationship_graph(a, max_depth=6)
    data = build_relationship_graph(a)
    assert data["nodes"][0]["depth"] == 0


# ---------------------------------------------------------------------------
# referral_graph：只沿 referrer / same_household 展开
# ---------------------------------------------------------------------------


def test_referral_graph_only_referrer_and_same_household(user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    c = make_customer("C", user)
    d = make_customer("D", user)
    e = make_customer("E", user)
    create_relation(from_customer=a, to_customer=b, relation_type="referrer")
    create_relation(from_customer=b, to_customer=c, relation_type="spouse")  # 不展开
    create_relation(from_customer=b, to_customer=d, relation_type="same_household")
    create_relation(from_customer=d, to_customer=e, relation_type="referrer")

    data = referral_graph(a, max_depth=3)
    nodes = node_map(data)
    assert set(nodes) == {str(a.pk), str(b.pk), str(d.pk), str(e.pk)}
    types = {e["relation_type"] for e in data["edges"]}
    assert types <= {"referrer", "same_household"}


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


def test_view_returns_graph_json(client: Client, user: User, status: CustomerStatus) -> None:
    a = make_customer("A", user, status=status)
    b = make_customer("B", user)
    create_relation(from_customer=a, to_customer=b, relation_type="spouse")
    client.force_login(user)

    resp = client.get(reverse("customers:relationship_graph", kwargs={"pk": a.pk}))
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")
    body = resp.json()
    assert set(body) == {"nodes", "edges"}
    assert len(body["nodes"]) == 2


def test_view_depth_param_effective(client: Client, user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    c = make_customer("C", user)
    create_relation(from_customer=a, to_customer=b, relation_type="referrer")
    create_relation(from_customer=b, to_customer=c, relation_type="referrer")
    client.force_login(user)

    resp = client.get(reverse("customers:relationship_graph", kwargs={"pk": a.pk}), {"depth": "1"})
    assert resp.status_code == 200
    assert {n["id"] for n in resp.json()["nodes"]} == {str(a.pk), str(b.pk)}


def test_view_forbidden_without_permission(client: Client, db: None) -> None:
    u = User(username="noperm")
    u.save()
    c = Customer.objects.create(name="X", owner=u, created_by=u)
    client.force_login(u)

    resp = client.get(reverse("customers:relationship_graph", kwargs={"pk": c.pk}))
    assert resp.status_code == 403


def test_view_404_unknown_customer(client: Client, user: User) -> None:
    client.force_login(user)
    resp = client.get(reverse("customers:relationship_graph", kwargs={"pk": uuid.uuid4()}))
    assert resp.status_code == 404


def test_referral_view(client: Client, user: User) -> None:
    a = make_customer("A", user)
    b = make_customer("B", user)
    create_relation(from_customer=a, to_customer=b, relation_type="referrer")
    client.force_login(user)

    resp = client.get(reverse("customers:referral_graph", kwargs={"pk": a.pk}))
    assert resp.status_code == 200
    body = resp.json()
    assert {n["id"] for n in body["nodes"]} == {str(a.pk), str(b.pk)}
