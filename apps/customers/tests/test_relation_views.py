"""T4.3 客户关系 视图测试（RED 先行，规格 §7）。

覆盖权限矩阵：匿名 302 → 登录页、无权限 403、有权限 200；
创建成功双向可见；非法输入（自环）重渲染表单且无残留；删除软删。
"""

from typing import Any

import pytest
from django.conf import settings
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerRelation
from apps.customers.services.relations import create_relation

pytestmark = pytest.mark.django_db


@pytest.fixture
def viewer(db: None) -> User:
    """仅拥有查看权限的用户。"""
    u = User(username="viewer", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def manager(db: None) -> User:
    """查看 + 管理权限的用户。"""
    u = User(username="manager", can_view_customers=True, can_manage_customers=True)
    u.save()
    return u


@pytest.fixture
def plain_user(db: None) -> User:
    """无任何客户权限的用户。"""
    u = User(username="plain")
    u.save()
    return u


@pytest.fixture
def customers(manager: User) -> list[Customer]:
    a = Customer.objects.create(name="林小明", owner=manager, created_by=manager)
    b = Customer.objects.create(name="王小红", owner=manager, created_by=manager)
    return [a, b]


def list_url(customer: Customer) -> str:
    return str(reverse("customers:relation_list", args=[customer.pk]))


def create_url(customer: Customer) -> str:
    return str(reverse("customers:relation_create", args=[customer.pk]))


def delete_url(relation: CustomerRelation) -> str:
    return str(reverse("customers:relation_delete", args=[relation.from_customer_id, relation.pk]))


# ---------------------------------------------------------------------------
# 权限矩阵
# ---------------------------------------------------------------------------


def test_relation_list_anonymous_redirects_to_login(client: Any, customers: list[Customer]) -> None:
    response = client.get(list_url(customers[0]))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_relation_list_without_permission_403(
    client: Any, plain_user: User, customers: list[Customer]
) -> None:
    client.force_login(plain_user)

    response = client.get(list_url(customers[0]))

    assert response.status_code == 403


def test_relation_list_with_permission_200(
    client: Any, viewer: User, customers: list[Customer]
) -> None:
    client.force_login(viewer)

    response = client.get(list_url(customers[0]))

    assert response.status_code == 200


def test_relation_create_anonymous_redirects(client: Any, customers: list[Customer]) -> None:
    response = client.get(create_url(customers[0]))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_relation_create_without_permission_403(
    client: Any, viewer: User, customers: list[Customer]
) -> None:
    # viewer 仅有查看权限，创建需 can_manage_customers。
    client.force_login(viewer)

    response = client.get(create_url(customers[0]))

    assert response.status_code == 403


def test_relation_create_with_permission_get_200(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)

    response = client.get(create_url(customers[0]))

    assert response.status_code == 200


def test_relation_delete_anonymous_redirects(client: Any, customers: list[Customer]) -> None:
    relation = create_relation(
        from_customer=customers[0], to_customer=customers[1], relation_type="spouse"
    )

    response = client.post(delete_url(relation))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_relation_delete_without_permission_403(
    client: Any, viewer: User, customers: list[Customer]
) -> None:
    client.force_login(viewer)
    relation = create_relation(
        from_customer=customers[0], to_customer=customers[1], relation_type="spouse"
    )

    response = client.post(delete_url(relation))

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------


def test_relation_create_post_creates_and_visible_both_sides(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)

    response = client.post(
        create_url(customers[0]),
        {"to_customer": customers[1].pk, "relation_type": "spouse", "note": "夫妻"},
    )

    assert response.status_code == 302
    assert response.url == list_url(customers[0])
    relation = CustomerRelation.objects.get()
    assert relation.from_customer == customers[0]
    assert relation.to_customer == customers[1]
    # 双向可见：对方的列表页也渲染这条关系。
    assert "王小红" in client.get(list_url(customers[0])).content.decode()
    assert "林小明" in client.get(list_url(customers[1])).content.decode()


def test_relation_create_post_self_loop_rejected(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)

    response = client.post(
        create_url(customers[0]),
        {"to_customer": customers[0].pk, "relation_type": "spouse"},
    )

    assert response.status_code == 200  # 表单错误重渲染
    assert CustomerRelation.objects.count() == 0


def test_relation_create_post_custom_requires_label(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)

    response = client.post(
        create_url(customers[0]),
        {"to_customer": customers[1].pk, "relation_type": "custom", "custom_label": ""},
    )

    assert response.status_code == 200
    assert CustomerRelation.objects.count() == 0


def test_relation_create_post_custom_with_label_succeeds(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)

    response = client.post(
        create_url(customers[0]),
        {
            "to_customer": customers[1].pk,
            "relation_type": "custom",
            "custom_label": "大学同学",
        },
    )

    assert response.status_code == 302
    assert CustomerRelation.objects.get().custom_label == "大学同学"


def test_relation_create_post_duplicate_rejected(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    create_relation(from_customer=customers[0], to_customer=customers[1], relation_type="spouse")
    client.force_login(manager)

    response = client.post(
        create_url(customers[0]),
        {"to_customer": customers[1].pk, "relation_type": "spouse"},
    )

    assert response.status_code == 200
    assert CustomerRelation.objects.count() == 1


# ---------------------------------------------------------------------------
# 删除（软删）
# ---------------------------------------------------------------------------


def test_relation_delete_post_soft_deletes(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)
    relation = create_relation(
        from_customer=customers[0], to_customer=customers[1], relation_type="spouse"
    )

    response = client.post(delete_url(relation))

    assert response.status_code == 302
    assert response.url == list_url(customers[0])
    assert CustomerRelation.objects.count() == 0
    assert CustomerRelation.all_objects.get(pk=relation.pk).is_deleted is True


def test_relation_delete_get_not_allowed(
    client: Any, manager: User, customers: list[Customer]
) -> None:
    client.force_login(manager)
    relation = create_relation(
        from_customer=customers[0], to_customer=customers[1], relation_type="spouse"
    )

    response = client.get(delete_url(relation))

    assert response.status_code == 405
    assert CustomerRelation.objects.count() == 1
