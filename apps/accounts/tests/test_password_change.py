"""密码修改测试：PasswordChangeView（旧密码校验 + 新密码生效）。"""

from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User

NEW_PASSWORD = "new-password-123"


@pytest.fixture
def user(db: None) -> User:
    u = User(username="alice")
    u.set_password("old-password")
    u.save()
    return u


@pytest.mark.django_db
def test_password_change_requires_login(client: Any) -> None:
    resp = client.get(reverse("accounts:password_change"))

    assert resp.status_code == 302
    assert reverse("accounts:login") in resp.url


@pytest.mark.django_db
def test_password_change_page_renders_three_fields(client: Any, user: User) -> None:
    client.force_login(user)

    resp = client.get(reverse("accounts:password_change"))

    assert resp.status_code == 200
    fields = set(resp.context["form"].fields)
    assert {"old_password", "new_password1", "new_password2"} <= fields


@pytest.mark.django_db
def test_password_change_flow_swaps_password(client: Any, user: User) -> None:
    client.force_login(user)

    resp = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": "old-password",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert resp.status_code == 302
    assert resp.url == reverse("accounts:login")
    user.refresh_from_db()
    assert user.check_password("old-password") is False
    assert user.check_password(NEW_PASSWORD) is True


@pytest.mark.django_db
def test_wrong_old_password_is_rejected(client: Any, user: User) -> None:
    client.force_login(user)

    resp = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": "wrong-password",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert resp.status_code == 200
    assert "old_password" in resp.context["form"].errors
    user.refresh_from_db()
    assert user.check_password("old-password") is True
