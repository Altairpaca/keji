"""accounts 路由。完整登录视图由后续里程碑实现。"""

from django.urls import path
from django.views.generic import TemplateView

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        TemplateView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
]
