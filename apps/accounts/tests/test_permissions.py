"""T3.1 权限位框架测试（ADR-004 / ADR-012）。

覆盖：
- has_bit：普通用户各权限位默认 False；开启后 True；superuser 恒 True（含覆盖关掉的字段）
- PERMISSION_BITS：严格 11 个且都是 User 真实字段
- has_permission 帮助函数（含匿名用户）
- require_permission 装饰器：未登录重定向登录、已登录无权限 403、有权限 200、superuser 放行
- has_perm 模板标签：默认 request.user、显式 user 参数、superuser、匿名
"""

from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template import Context, Template

from apps.accounts.models import User
from apps.accounts.permissions import has_permission, require_permission

pytestmark = pytest.mark.urls("apps.accounts.tests.urls")

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def plain_user(db: None) -> User:
    """无任何权限位的普通用户。"""
    user = User(username="plain")
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def super_user(db: None) -> User:
    """超级管理员。"""
    user = User(username="root", email="root@example.com", is_superuser=True)
    user.set_password("pw")
    user.save()
    return user


# ---------------------------------------------------------------------------
# has_bit
# ---------------------------------------------------------------------------


def test_permission_bits_exactly_eleven_real_fields() -> None:
    assert len(User.PERMISSION_BITS) == 11
    for bit in User.PERMISSION_BITS:
        assert hasattr(User, bit)


@pytest.mark.django_db
def test_has_bit_defaults_false_for_plain_user(plain_user: User) -> None:
    for bit in User.PERMISSION_BITS:
        assert plain_user.has_bit(bit) is False


@pytest.mark.django_db
def test_has_bit_true_after_field_enabled(plain_user: User) -> None:
    plain_user.can_view_customers = True

    assert plain_user.has_bit("can_view_customers") is True
    assert plain_user.has_bit("can_backup") is False


@pytest.mark.django_db
def test_has_bit_superuser_true_regardless_of_fields(super_user: User) -> None:
    for bit in User.PERMISSION_BITS:
        assert super_user.has_bit(bit) is True


@pytest.mark.django_db
def test_has_bit_superuser_overrides_disabled_field(super_user: User) -> None:
    super_user.can_view_customers = False
    super_user.save(update_fields=["can_view_customers"])

    assert super_user.has_bit("can_view_customers") is True


# ---------------------------------------------------------------------------
# has_permission 帮助函数
# ---------------------------------------------------------------------------


def test_has_permission_delegates_to_has_bit() -> None:
    user = User(username="plain")

    assert has_permission(user, "can_view_customers") is False

    user.can_view_customers = True
    assert has_permission(user, "can_view_customers") is True


def test_has_permission_anonymous_false() -> None:
    assert has_permission(AnonymousUser(), "can_view_customers") is False


def test_has_permission_superuser_true() -> None:
    user = User(username="root", is_superuser=True)

    assert has_permission(user, "can_backup") is True


# ---------------------------------------------------------------------------
# require_permission 装饰器（函数视图，RequestFactory 直测）
# ---------------------------------------------------------------------------


def test_require_permission_redirects_anonymous(rf: Any) -> None:
    request = rf.get("/")
    request.user = AnonymousUser()
    view = require_permission("can_view_customers")(lambda r: HttpResponse("ok"))

    response = view(request)

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_require_permission_raises_permission_denied(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="plain")
    view = require_permission("can_view_customers")(lambda r: HttpResponse("ok"))

    with pytest.raises(PermissionDenied):
        view(request)


def test_require_permission_allows_user_with_bit(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="granted", can_view_customers=True)
    view = require_permission("can_view_customers")(lambda r: HttpResponse("ok"))

    response = view(request)

    assert response.status_code == 200


def test_require_permission_allows_superuser_without_bits(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="root", is_superuser=True)
    view = require_permission("can_backup")(lambda r: HttpResponse("ok"))

    response = view(request)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# require_permission 装饰器（HTTP 全链路，pytest.mark.urls 覆盖 ROOT_URLCONF）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_http_anonymous_redirected_to_login(client: Any) -> None:
    response = client.get("/perm-check/customers/")

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


@pytest.mark.django_db
def test_http_plain_user_without_permission_gets_403(client: Any, plain_user: User) -> None:
    client.force_login(plain_user)

    response = client.get("/perm-check/backup/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_http_plain_user_with_permission_gets_200(client: Any, plain_user: User) -> None:
    plain_user.can_backup = True
    plain_user.save(update_fields=["can_backup"])
    client.force_login(plain_user)

    response = client.get("/perm-check/backup/")

    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
def test_http_superuser_without_field_allowed(client: Any, super_user: User) -> None:
    client.force_login(super_user)

    response = client.get("/perm-check/backup/")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# has_perm 模板标签
# ---------------------------------------------------------------------------

_TPL_REQUEST_USER = (
    "{% load perm_tags %}"
    "{% has_perm 'can_view_customers' as granted %}"
    "{% if granted %}yes{% else %}no{% endif %}"
)


def test_has_perm_tag_uses_request_user(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="plain")

    output = Template(_TPL_REQUEST_USER).render(Context({"request": request}))

    assert output.strip() == "no"


def test_has_perm_tag_true_when_field_enabled(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="granted", can_view_customers=True)

    output = Template(_TPL_REQUEST_USER).render(Context({"request": request}))

    assert output.strip() == "yes"


def test_has_perm_tag_superuser_true(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="root", is_superuser=True)

    output = Template(_TPL_REQUEST_USER).render(Context({"request": request}))

    assert output.strip() == "yes"


def test_has_perm_tag_anonymous_false(rf: Any) -> None:
    request = rf.get("/")
    request.user = AnonymousUser()

    output = Template(_TPL_REQUEST_USER).render(Context({"request": request}))

    assert output.strip() == "no"


def test_has_perm_tag_accepts_explicit_user(rf: Any) -> None:
    request = rf.get("/")
    request.user = User(username="other")
    granted = User(username="granted", can_backup=True)
    tpl = (
        "{% load perm_tags %}"
        "{% has_perm 'can_backup' granted as ok %}"
        "{% if ok %}yes{% else %}no{% endif %}"
    )

    output = Template(tpl).render(Context({"request": request, "granted": granted}))

    assert output.strip() == "yes"
