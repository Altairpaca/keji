"""用户管理测试（仅管理员：is_superuser 或 can_manage_users）。

覆盖：
- 未登录访问全部管理页 → 302 跳登录
- 普通用户访问 → 403（列表/创建/编辑/停用）
- 管理员：列表、创建（含权限位分配与随机密码）、编辑权限位、启用/禁用
- 禁用用户无法登录；管理员不能禁用自己
"""

from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User


@pytest.fixture
def admin_user(db: None) -> User:
    u = User(username="root", email="root@example.com", is_superuser=True)
    u.set_password("admin-pass")
    u.save()
    return u


@pytest.fixture
def plain_user(db: None) -> User:
    u = User(username="plain", email="plain@example.com", is_active=True)
    u.set_password("plain-pass")
    u.save()
    return u


# ---------------------------------------------------------------------------
# 访问控制：未登录 302 / 普通用户 403
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_redirected_to_login_for_all_management_pages(client: Any) -> None:
    target = User(username="victim")
    target.save()

    assert client.get(reverse("accounts:user_list")).status_code == 302
    assert client.get(reverse("accounts:user_create")).status_code == 302
    assert client.get(reverse("accounts:user_edit", args=[target.pk])).status_code == 302
    assert client.post(reverse("accounts:user_toggle_active", args=[target.pk])).status_code == 302


@pytest.mark.django_db
def test_plain_user_forbidden_from_management(client: Any, plain_user: User) -> None:
    client.force_login(plain_user)
    target = User(username="target")
    target.save()

    assert client.get(reverse("accounts:user_list")).status_code == 403
    assert client.get(reverse("accounts:user_create")).status_code == 403
    assert client.get(reverse("accounts:user_edit", args=[target.pk])).status_code == 403
    assert client.post(reverse("accounts:user_toggle_active", args=[target.pk])).status_code == 403


@pytest.mark.django_db
def test_user_with_manage_users_bit_can_access(client: Any, plain_user: User) -> None:
    plain_user.can_manage_users = True
    plain_user.save(update_fields=["can_manage_users"])
    client.force_login(plain_user)

    assert client.get(reverse("accounts:user_list")).status_code == 200


# ---------------------------------------------------------------------------
# 列表 / 创建
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_can_list_users(client: Any, admin_user: User, plain_user: User) -> None:
    client.force_login(admin_user)

    resp = client.get(reverse("accounts:user_list"))

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "root" in content
    assert "plain" in content


@pytest.mark.django_db
def test_admin_can_create_user_with_permission_bits(client: Any, admin_user: User) -> None:
    client.force_login(admin_user)

    resp = client.post(
        reverse("accounts:user_create"),
        {
            "username": "newbie",
            "email": "newbie@example.com",
            "password": "initial-pass-1",
            "is_active": "on",
            "can_view_customers": "on",
            "can_backup": "on",
        },
    )

    assert resp.status_code == 302
    new_user = User.objects.get(username="newbie")
    assert new_user.check_password("initial-pass-1")
    assert new_user.is_active is True
    assert new_user.can_view_customers is True
    assert new_user.can_backup is True
    assert new_user.can_manage_users is False


@pytest.mark.django_db
def test_create_user_without_password_generates_random_and_shows_once(
    client: Any, admin_user: User
) -> None:
    client.force_login(admin_user)

    resp = client.post(
        reverse("accounts:user_create"),
        {"username": "nopass", "email": "", "is_active": "on"},
        follow=True,
    )

    assert resp.status_code == 200
    new_user = User.objects.get(username="nopass")
    assert new_user.has_usable_password()
    assert "初始密码" in resp.content.decode()


# ---------------------------------------------------------------------------
# 编辑 / 启用禁用
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_edit_form_renders_all_permission_bit_checkboxes(
    client: Any, admin_user: User, plain_user: User
) -> None:
    client.force_login(admin_user)

    resp = client.get(reverse("accounts:user_edit", args=[plain_user.pk]))

    assert resp.status_code == 200
    content = resp.content.decode()
    for bit in User.PERMISSION_BITS:
        assert f'name="{bit}"' in content


@pytest.mark.django_db
def test_admin_can_edit_user_permission_bits(
    client: Any, admin_user: User, plain_user: User
) -> None:
    client.force_login(admin_user)

    resp = client.post(
        reverse("accounts:user_edit", args=[plain_user.pk]),
        {
            "username": "plain",
            "email": "plain@example.com",
            "is_active": "on",
            "can_delete_customers": "on",
        },
    )

    assert resp.status_code == 302
    plain_user.refresh_from_db()
    assert plain_user.can_delete_customers is True
    assert plain_user.can_view_customers is False
    assert plain_user.is_active is True


@pytest.mark.django_db
def test_admin_can_disable_and_reenable_user(
    client: Any, admin_user: User, plain_user: User
) -> None:
    client.force_login(admin_user)
    url = reverse("accounts:user_toggle_active", args=[plain_user.pk])

    resp = client.post(url)
    assert resp.status_code == 302
    plain_user.refresh_from_db()
    assert plain_user.is_active is False

    resp = client.post(url)
    assert resp.status_code == 302
    plain_user.refresh_from_db()
    assert plain_user.is_active is True


@pytest.mark.django_db
def test_admin_cannot_disable_self(client: Any, admin_user: User) -> None:
    client.force_login(admin_user)

    resp = client.post(reverse("accounts:user_toggle_active", args=[admin_user.pk]))

    assert resp.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.is_active is True


@pytest.mark.django_db
def test_disabled_user_cannot_login(client: Any, admin_user: User, plain_user: User) -> None:
    plain_user.is_active = False
    plain_user.save(update_fields=["is_active"])

    resp = client.post(
        reverse("accounts:login"),
        {"username": "plain", "password": "plain-pass"},
    )

    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session
