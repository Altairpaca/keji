"""accounts 路由：登录（限流）/ 退出 / 个人页 / 改密 / 用户管理。"""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from apps.accounts import views
from apps.accounts.forms import KejiPasswordChangeForm

app_name = "accounts"

urlpatterns = [
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path(
        "password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            form_class=KejiPasswordChangeForm,
            success_url=reverse_lazy("accounts:login"),
        ),
        name="password_change",
    ),
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<uuid:pk>/edit/", views.user_edit, name="user_edit"),
    path(
        "users/<uuid:pk>/toggle-active/",
        views.user_toggle_active,
        name="user_toggle_active",
    ),
]
