"""模板标签：``{% has_perm "can_view_customers" %}``。

展示性权限判断（ADR-004）：模板只做入口隐藏，安全校验在服务端装饰器。

用法：
- ``{% has_perm "can_view_customers" %}`` — 取 ``request.user``
- ``{% has_perm "can_backup" some_user %}`` — 显式指定 user 对象
"""

from typing import Any

from django import template

from apps.accounts.permissions import has_permission

register = template.Library()


@register.simple_tag(takes_context=True)
def has_perm(context: dict[str, Any], bit_name: str, user: Any | None = None) -> bool:
    """返回 user（默认 request.user）是否拥有 ``bit_name`` 权限位。"""
    if user is None:
        user = context["request"].user
    return has_permission(user, bit_name)
