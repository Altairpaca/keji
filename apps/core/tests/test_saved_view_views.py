"""测试保存视图视图（规格 §15）：保存 / 列表 / 应用 / 删除 + 权限矩阵（core）。"""

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models.saved_view import SavedView


@pytest.fixture
def viewer() -> User:
    u = User(username="sv-viewer", can_view_customers=True)
    u.save()
    assert isinstance(u, User)
    return u


@pytest.fixture
def other() -> User:
    u = User(username="sv-other", can_view_customers=True)
    u.save()
    assert isinstance(u, User)
    return u


@pytest.fixture
def plain() -> User:
    u = User(username="sv-plain")
    u.save()
    assert isinstance(u, User)
    return u


def _save_post(client: Any, viewer: User, name: str, filters: Mapping[str, object]) -> None:
    client.force_login(viewer)
    client.post(
        reverse("core:saved_view_save"),
        {
            "app_label": "customers",
            "model_name": "customer",
            "name": name,
            "filters": json.dumps(filters, ensure_ascii=False),
        },
    )


@pytest.mark.django_db
def test_save_view_persists_and_visible_in_list(client: Any, viewer: User) -> None:
    _save_post(client, viewer, "张客户", {"q": "张"})

    client.force_login(viewer)
    response = client.get(
        reverse("core:saved_view_list"), {"app": "customers", "model": "customer"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert [v["name"] for v in payload["views"]] == ["张客户"]
    assert payload["views"][0]["filters"] == {"q": "张"}
    assert SavedView.objects.count() == 1


@pytest.mark.django_db
def test_save_view_same_name_overwrites(client: Any, viewer: User) -> None:
    _save_post(client, viewer, "重点客户", {"status": "old"})
    _save_post(client, viewer, "重点客户", {"q": "新", "status": "new"})

    view = SavedView.objects.get(name="重点客户")
    assert SavedView.objects.count() == 1
    assert view.filters == {"q": "新", "status": "new"}


@pytest.mark.django_db
def test_apply_view_redirects_to_customer_list_with_filters(client: Any, viewer: User) -> None:
    _save_post(client, viewer, "张状态", {"q": "张", "status": "st-123", "tag": ["t1", "t2"]})

    client.force_login(viewer)
    view = SavedView.objects.get()
    response = client.get(reverse("core:saved_view_apply", args=[str(view.id)]))

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == reverse("customers:customer_list")
    params = parse_qs(location.query)
    assert params["q"] == ["张"]
    assert params["status"] == ["st-123"]
    assert params["tag"] == ["t1", "t2"]


@pytest.mark.django_db
def test_delete_view_removes_view(client: Any, viewer: User) -> None:
    _save_post(client, viewer, "待删", {"q": "删"})

    client.force_login(viewer)
    view = SavedView.objects.get()
    response = client.post(reverse("core:saved_view_delete", args=[str(view.id)]))

    assert response.status_code == 302
    assert SavedView.objects.count() == 0


@pytest.mark.django_db
def test_delete_other_users_view_forbidden(client: Any, viewer: User, other: User) -> None:
    _save_post(client, viewer, "他人视图", {"q": "私"})

    client.force_login(other)
    view = SavedView.objects.get()
    response = client.post(reverse("core:saved_view_delete", args=[str(view.id)]))

    assert response.status_code == 403
    assert SavedView.objects.count() == 1


@pytest.mark.django_db
def test_apply_other_users_view_not_found(client: Any, viewer: User, other: User) -> None:
    _save_post(client, viewer, "私有视图", {"q": "私"})

    client.force_login(other)
    view = SavedView.objects.get()
    response = client.get(reverse("core:saved_view_apply", args=[str(view.id)]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_anonymous_redirected_to_login(client: Any) -> None:
    response = client.get(reverse("core:saved_view_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.headers["Location"]


@pytest.mark.django_db
def test_requires_view_customers_permission(client: Any, plain: User) -> None:
    client.force_login(plain)
    assert client.get(reverse("core:saved_view_list")).status_code == 403
    assert client.post(reverse("core:saved_view_save"), {"name": "x"}).status_code == 403


@pytest.mark.django_db
def test_filters_json_roundtrip(client: Any, viewer: User) -> None:
    filters: Mapping[str, object] = {"q": "李", "status": "st-9", "tag": ["a", "b"]}
    _save_post(client, viewer, "往返", filters)

    view = SavedView.objects.get()
    assert view.filters == filters

    client.force_login(viewer)
    response = client.get(
        reverse("core:saved_view_list"), {"app": "customers", "model": "customer"}
    )

    assert response.status_code == 200
    assert response.json()["views"][0]["filters"] == filters
