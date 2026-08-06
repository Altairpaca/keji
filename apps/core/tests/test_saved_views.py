"""测试保存视图服务：保存、列表、删除、获取与 owner 校验（core）。"""

import pytest
from django.core.exceptions import ObjectDoesNotExist

from apps.accounts.models import User
from apps.core.models.saved_view import SavedView
from apps.core.services.saved_views import delete_view, get_view, list_views, save_view


@pytest.fixture
def owner() -> User:
    user = User.objects.create_user(username="view-owner", password="pw")
    assert isinstance(user, User)
    return user


@pytest.fixture
def other() -> User:
    user = User.objects.create_user(username="view-other", password="pw")
    assert isinstance(user, User)
    return user


@pytest.mark.django_db
def test_save_view_creates_record(owner: User) -> None:
    view = save_view(
        owner,
        "我的客户",
        "customers",
        "Customer",
        {"status": "active"},
        ["-created_at"],
    )

    assert view.owner == owner
    assert view.name == "我的客户"
    assert view.filters == {"status": "active"}
    assert view.sorts == ["-created_at"]
    assert SavedView.objects.count() == 1


@pytest.mark.django_db
def test_save_view_defaults_to_empty_filters_and_sorts(owner: User) -> None:
    view = save_view(owner, "默认", "customers", "Customer")

    assert view.filters == {}
    assert view.sorts == []


@pytest.mark.django_db
def test_list_views_filters_by_owner_and_app(owner: User, other: User) -> None:
    save_view(owner, "v1", "customers", "Customer", {})
    save_view(owner, "v2", "customers", "Customer", {})
    save_view(owner, "v3", "policies", "Policy", {})
    save_view(other, "v4", "customers", "Customer", {})

    result = list_views(owner, "customers", "Customer")

    assert {v.name for v in result} == {"v1", "v2"}


@pytest.mark.django_db
def test_delete_view_removes_own_view(owner: User) -> None:
    view = save_view(owner, "v1", "customers", "Customer", {})

    delete_view(view, owner)

    assert SavedView.objects.count() == 0


@pytest.mark.django_db
def test_delete_view_raises_permission_error_for_other_owner(owner: User, other: User) -> None:
    view = save_view(owner, "v1", "customers", "Customer", {})

    with pytest.raises(PermissionError):
        delete_view(view, other)

    assert SavedView.objects.count() == 1


@pytest.mark.django_db
def test_get_view_returns_own_view(owner: User) -> None:
    view = save_view(owner, "v1", "customers", "Customer", {})

    assert get_view(view.id, owner).id == view.id


@pytest.mark.django_db
def test_get_view_raises_does_not_exist_for_other_owner(owner: User, other: User) -> None:
    view = save_view(owner, "v1", "customers", "Customer", {})

    with pytest.raises(ObjectDoesNotExist):
        get_view(view.id, other)
