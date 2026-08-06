"""根 URL 配置。

- "/"           → dashboard 首页（登录保护，未认证跳转登录页）
- "/admin/"     → Django admin（前缀由 settings.ADMIN_URL 控制）
- "/accounts/"  → accounts 应用（登录 / 退出 / 个人页）
- "/activities/" → activities 应用（工作事件 / 沟通记录）
- "/customers/<uuid>/events/new/" → 客户视角新建工作事件快捷路由（代理到 activities）
- "/sw.js" → Service Worker 脚本（根作用域，规格 §4 / ADR-014）
- "/manifest.json" → PWA manifest（application/json）
- "/offline/" → 公开离线错误页（SW 离线回退目标）
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.activities import views as activities_views
from apps.core.views import pwa as pwa_views

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("activities/", include("apps.activities.urls")),
    path("documents/", include("apps.documents.urls")),
    path(
        "customers/<uuid:customer_pk>/events/new/",
        activities_views.work_event_create,
        name="work_event_create_for_customer",
    ),
    path("customers/", include("apps.customers.urls")),
    path("claims/", include("apps.claims.urls")),
    path("policies/", include("apps.policies.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("saved-views/", include("apps.core.urls")),
    path("export/", include("apps.core.urls_exports")),
    path("sw.js", pwa_views.service_worker, name="service_worker"),
    path("manifest.json", pwa_views.manifest, name="manifest"),
    path("offline/", pwa_views.offline_page, name="offline"),
]
