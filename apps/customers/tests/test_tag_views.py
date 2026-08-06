"""T4.4 标签管理视图 + 重复检测/合并视图测试（RED 先行）。

覆盖：
- 标签权限矩阵：普通用户无 can_manage_enums 时增删改 403、列表可见；管理员全通
- 标签 CRUD：创建（成功 / 重名表单错误 / color 输入类型）、编辑、软删（保留客户、M2M 断开）
- 重复检测视图：duplicate_list 需 can_manage_customers、merge 全流程
"""

from typing import Any

import pytest
from django.conf import settings
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer, Tag

pytestmark = pytest.mark.django_db


@pytest.fixture
def viewer(db: None) -> User:
    """有查看权限、无标签/客户管理权限的普通用户。"""
    u = User(username="viewer", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def tag_manager(db: None) -> User:
    """标签管理权限用户。"""
    u = User(username="tag_manager", can_view_customers=True, can_manage_enums=True)
    u.save()
    return u


@pytest.fixture
def dupe_manager(db: None) -> User:
    """客户管理权限用户（重复检测/合并）。"""
    u = User(username="dupe_manager", can_view_customers=True, can_manage_customers=True)
    u.save()
    return u


@pytest.fixture
def admin(db: None) -> User:
    u = User(username="admin", is_superuser=True)
    u.save()
    return u


@pytest.fixture
def agent(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


def login(client: Any, user: User) -> None:
    client.force_login(user)


def make_customer(user: User, name: str, **kwargs: object) -> Customer:
    data: dict[str, object] = {"name": name, "owner": user, "created_by": user}
    data.update(kwargs)
    customer: Customer = Customer.objects.create(**data)
    return customer


# ---------------------------------------------------------------------------
# tag_list 权限
# ---------------------------------------------------------------------------


def test_tag_list_requires_login(client: Any) -> None:
    response = client.get(reverse("customers:tag_list"))

    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)


def test_tag_list_403_without_view_permission(client: Any, db: None) -> None:
    u = User(username="nope")
    u.save()
    login(client, u)

    assert client.get(reverse("customers:tag_list")).status_code == 403


def test_tag_list_visible_to_viewer(client: Any, viewer: User) -> None:
    Tag.objects.create(name="vip", color="#ef4444", description="重点")
    login(client, viewer)

    response = client.get(reverse("customers:tag_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "vip" in content


# ---------------------------------------------------------------------------
# 标签权限矩阵：无 can_manage_enums → 增删改 403
# ---------------------------------------------------------------------------


def test_tag_create_requires_manage_enums(client: Any, viewer: User) -> None:
    login(client, viewer)

    assert client.get(reverse("customers:tag_create")).status_code == 403
    assert client.post(reverse("customers:tag_create"), {"name": "vip"}).status_code == 403
    assert Tag.objects.count() == 0


def test_tag_edit_requires_manage_enums(client: Any, viewer: User) -> None:
    tag = Tag.objects.create(name="vip")
    login(client, viewer)

    assert client.get(reverse("customers:tag_edit", args=[tag.pk])).status_code == 403
    assert (
        client.post(reverse("customers:tag_edit", args=[tag.pk]), {"name": "x"}).status_code == 403
    )


def test_tag_delete_requires_manage_enums(client: Any, viewer: User) -> None:
    tag = Tag.objects.create(name="vip")
    login(client, viewer)

    response = client.post(reverse("customers:tag_delete", args=[tag.pk]))

    assert response.status_code == 403
    assert Tag.all_objects.get(pk=tag.pk).is_deleted is False


# ---------------------------------------------------------------------------
# 标签 CRUD
# ---------------------------------------------------------------------------


def test_tag_create_form_renders_color_input(client: Any, tag_manager: User) -> None:
    login(client, tag_manager)

    response = client.get(reverse("customers:tag_create"))

    assert response.status_code == 200
    assert b'type="color"' in response.content


def test_tag_create_success_redirects_to_list(client: Any, tag_manager: User) -> None:
    login(client, tag_manager)

    response = client.post(
        reverse("customers:tag_create"),
        {"name": "vip", "color": "#ef4444", "description": "重点客户"},
    )

    assert response.status_code == 302
    assert response.url == reverse("customers:tag_list")
    tag = Tag.objects.get(name="vip")
    assert tag.color == "#ef4444"
    assert tag.description == "重点客户"


def test_tag_create_blank_name_keeps_form(client: Any, tag_manager: User) -> None:
    login(client, tag_manager)

    response = client.post(reverse("customers:tag_create"), {"name": "  ", "color": "#ef4444"})

    assert response.status_code == 200
    assert Tag.objects.count() == 0


def test_tag_create_duplicate_name_shows_error(client: Any, tag_manager: User) -> None:
    Tag.objects.create(name="vip")
    login(client, tag_manager)

    response = client.post(reverse("customers:tag_create"), {"name": "vip", "color": "#ef4444"})

    assert response.status_code == 200
    assert Tag.objects.count() == 1


def test_tag_edit_updates_and_redirects(client: Any, tag_manager: User) -> None:
    tag = Tag.objects.create(name="vip", color="#ef4444")
    login(client, tag_manager)

    response = client.post(
        reverse("customers:tag_edit", args=[tag.pk]),
        {"name": "重点", "color": "#3b82f6", "description": "已更新"},
    )

    assert response.status_code == 302
    assert response.url == reverse("customers:tag_list")
    tag.refresh_from_db()
    assert tag.name == "重点"
    assert tag.color == "#3b82f6"


def test_tag_edit_duplicate_name_shows_error(client: Any, tag_manager: User) -> None:
    Tag.objects.create(name="vip")
    other = Tag.objects.create(name="老客户")
    login(client, tag_manager)

    response = client.post(reverse("customers:tag_edit", args=[other.pk]), {"name": "vip"})

    assert response.status_code == 200
    assert Tag.objects.get(pk=other.pk).name == "老客户"


def test_tag_delete_soft_deletes_and_keeps_customer(
    client: Any, tag_manager: User, agent: User
) -> None:
    tag = Tag.objects.create(name="vip")
    customer = make_customer(agent, "林小明")
    customer.tags.add(tag)
    login(client, tag_manager)

    response = client.post(reverse("customers:tag_delete", args=[tag.pk]))

    assert response.status_code == 302
    assert response.url == reverse("customers:tag_list")
    assert Tag.all_objects.get(pk=tag.pk).is_deleted is True
    # 客户保留，M2M 自动断开
    assert Customer.objects.get(pk=customer.pk).is_deleted is False
    assert customer.tags.count() == 0


def test_tag_delete_get_method_405(client: Any, tag_manager: User) -> None:
    tag = Tag.objects.create(name="vip")
    login(client, tag_manager)

    assert client.get(reverse("customers:tag_delete", args=[tag.pk])).status_code == 405


def test_tag_list_shows_customer_count(client: Any, tag_manager: User, agent: User) -> None:
    tag = Tag.objects.create(name="vip")
    c1 = make_customer(agent, "甲")
    c2 = make_customer(agent, "乙")
    c1.tags.add(tag)
    c2.tags.add(tag)
    login(client, tag_manager)

    response = client.get(reverse("customers:tag_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "vip" in content
    assert "2" in content


# ---------------------------------------------------------------------------
# 管理员全通
# ---------------------------------------------------------------------------


def test_admin_can_do_all_tag_operations(client: Any, admin: User) -> None:
    tag = Tag.objects.create(name="vip")
    login(client, admin)

    assert client.get(reverse("customers:tag_list")).status_code == 200
    assert client.get(reverse("customers:tag_create")).status_code == 200
    assert client.get(reverse("customers:tag_edit", args=[tag.pk])).status_code == 200
    assert (
        client.post(
            reverse("customers:tag_edit", args=[tag.pk]),
            {"name": "重点", "color": "#ef4444"},
        ).status_code
        == 302
    )
    assert client.post(reverse("customers:tag_delete", args=[tag.pk])).status_code == 302
    assert Tag.all_objects.get(pk=tag.pk).is_deleted is True


# ---------------------------------------------------------------------------
# 重复检测与合并视图
# ---------------------------------------------------------------------------


def test_duplicate_list_requires_manage_customers(client: Any, viewer: User) -> None:
    login(client, viewer)

    assert client.get(reverse("customers:duplicate_list")).status_code == 403


def test_duplicate_list_shows_phone_group(client: Any, dupe_manager: User, agent: User) -> None:
    make_customer(agent, "甲", phone="13800138000")
    make_customer(agent, "乙", phone="13800138000")
    login(client, dupe_manager)

    response = client.get(reverse("customers:duplicate_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "甲" in content
    assert "乙" in content


def test_merge_confirm_requires_manage_customers(client: Any, viewer: User) -> None:
    login(client, viewer)

    assert client.get(reverse("customers:merge_confirm")).status_code == 403


def test_merge_flow_merges_source_into_target(client: Any, dupe_manager: User, agent: User) -> None:
    target = make_customer(agent, "甲", phone="13800138000")
    source = make_customer(agent, "乙", phone="13800138000")
    login(client, dupe_manager)

    confirm = client.get(
        reverse("customers:merge_confirm"),
        {"target": target.pk, "source": source.pk},
    )

    assert confirm.status_code == 200
    assert "甲".encode() in confirm.content
    assert "乙".encode() in confirm.content

    response = client.post(
        reverse("customers:merge_do"),
        {"target": target.pk, "source": source.pk},
    )

    assert response.status_code == 302
    assert response.url == reverse("customers:customer_detail", args=[target.pk])
    assert Customer.objects.filter(pk=source.pk).count() == 0
    assert Customer.all_objects.get(pk=source.pk).is_deleted is True
    assert Customer.objects.get(pk=target.pk).name == "甲"


def test_merge_do_requires_manage_customers(client: Any, viewer: User) -> None:
    login(client, viewer)

    assert (
        client.post(reverse("customers:merge_do"), {"target": "x", "source": "y"}).status_code
        == 403
    )
