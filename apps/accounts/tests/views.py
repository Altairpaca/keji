"""测试专用视图：验证 require_permission 装饰器（仅测试使用，不注册到应用路由）。"""

from django.http import HttpRequest, HttpResponse

from apps.accounts.permissions import require_permission


def _ok_view(request: HttpRequest) -> HttpResponse:
    """测试占位视图：返回固定响应。"""
    return HttpResponse("ok")


# 两个不同权限位的视图，覆盖「有权限 / 无权限 / 超级管理员放行」三态。
customers_view = require_permission("can_view_customers")(_ok_view)
backup_view = require_permission("can_backup")(_ok_view)
