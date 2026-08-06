"""根 URL 配置。

- "/"           → dashboard 首页（登录保护，未认证跳转登录页）
- "/admin/"     → Django admin（前缀由 settings.ADMIN_URL 控制）
- "/accounts/"  → accounts 应用（登录 / 退出 / 个人页）
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
]
