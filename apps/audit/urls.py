"""audit 路由：审计日志查看（只读）。"""

from django.urls import path

from apps.audit import views

app_name = "audit"

urlpatterns = [
    path("", views.audit_list, name="list"),
]
