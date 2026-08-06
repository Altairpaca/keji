"""服务端权限校验工具（ADR-004 / ADR-012）。

- ``require_permission(bit_name)``：视图装饰器，未登录重定向登录页，
  已登录但无权限抛 ``PermissionDenied``（Django 渲染为 403）。
- ``has_permission(user, bit_name)``：帮助函数，内部调 ``user.has_bit``。

模板层的 ``has_perm`` 标签只做展示性隐藏；安全边界一律在服务端装饰器。
"""

from collections.abc import Callable
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.shortcuts import redirect

from apps.accounts.models import User

# 视图可调用对象签名（Django 未提供 py.typed，参数在调用点动态注入）。
ViewFunc = Callable[..., HttpResponseBase]


def has_permission(user: User, bit_name: str) -> bool:
    """判断 user 是否拥有 ``bit_name`` 权限位；匿名用户恒为 False。"""
    if not user.is_authenticated:
        return False
    return user.has_bit(bit_name)


def require_permission(bit_name: str) -> Callable[[ViewFunc], ViewFunc]:
    """视图装饰器：强制校验当前请求用户拥有 ``bit_name`` 权限位。

    - 未登录 → 重定向 ``settings.LOGIN_URL``；
    - 已登录但无权限 → 抛 ``PermissionDenied``（403）；
    - 超级管理员恒放行（由 ``User.has_bit`` 覆盖）。

    兼容函数视图与类视图：CBV 使用
    ``@method_decorator(require_permission(...), name="dispatch")``。
    """

    def decorator(view_func: ViewFunc) -> ViewFunc:
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
            user: User = request.user
            if not has_permission(user, bit_name):
                if not user.is_authenticated:
                    return redirect(settings.LOGIN_URL)
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
