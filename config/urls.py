"""根 URL 配置。

- "/"           → 未认证时的登录跳转占位（后续由 dashboard 首页替换）
- "/admin/"     → Django admin（前缀由 settings.ADMIN_URL 控制）
- "/accounts/"  → accounts 应用（登录占位页，完整登录逻辑后续里程碑实现）
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="accounts:login", permanent=False),
        name="home",
    ),
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
]
