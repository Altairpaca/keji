"""accounts 视图：个人页 / 限流登录 / 用户管理（仅管理员）。

登录限流（缓存实现）见 services/rate_limit.py；权限边界一律走
``require_permission`` 服务端装饰器（ADR-004 / ADR-012），模板只做展示性隐藏。
"""

import secrets
import uuid
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import UserCreateForm, UserEditForm
from apps.accounts.models import User
from apps.accounts.permissions import require_permission
from apps.accounts.services.rate_limit import (
    check_login_allowed,
    clear_login_failures,
    record_login_failure,
)
from apps.audit.services import record_audit


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """「我的」页：用户名 / 角色 / 权限位展示。"""
    return render(request, "accounts/profile.html")


def _client_ip(request: HttpRequest) -> str:
    """取客户端 IP：反代下取 X-Forwarded-For 首段，否则 REMOTE_ADDR。"""
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", ""))
    if forwarded:
        return forwarded.split(",")[0].strip()
    return str(request.META.get("REMOTE_ADDR", ""))


class RateLimitedLoginView(LoginView):
    """带登录限流的 LoginView：进入查锁，失败计数，成功清零。"""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    lock_message = "尝试次数过多，请 15 分钟后再试"

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        username = request.POST.get("username", "") if request.method == "POST" else ""
        allowed, _remaining = check_login_allowed(_client_ip(request), username)
        if not allowed:
            return self._render_locked(request)
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form: Any) -> HttpResponse:
        username = form.cleaned_data.get("username", "")
        record_login_failure(_client_ip(self.request), username)
        return super().form_invalid(form)

    def form_valid(self, form: Any) -> HttpResponse:
        username = form.cleaned_data.get("username", "")
        clear_login_failures(_client_ip(self.request), username)
        return super().form_valid(form)

    def _render_locked(self, request: HttpRequest) -> HttpResponse:
        form = self.get_form()
        form.add_error(None, self.lock_message)
        return self.render_to_response(self.get_context_data(form=form))


# ---------------------------------------------------------------------------
# 用户管理（仅管理员：is_superuser 或 can_manage_users）
# ---------------------------------------------------------------------------


@require_permission("can_manage_users")
def user_list(request: HttpRequest) -> HttpResponse:
    """全部用户列表：用户名 / 角色 / 权限位摘要 / 状态。"""
    rows = [
        {
            "user": user,
            "role": "管理员" if user.is_superuser else "普通用户",
            "enabled_bits": [
                User._meta.get_field(bit).verbose_name
                for bit in User.PERMISSION_BITS
                if user.has_bit(bit)
            ],
        }
        for user in User.objects.order_by("-is_superuser", "username")
    ]
    return render(request, "accounts/user_list.html", {"rows": rows})


@require_permission("can_manage_users")
def user_create(request: HttpRequest) -> HttpResponse:
    """创建用户：表单可填初始密码，留空生成随机密码并在消息中显示一次。"""
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        password = form.cleaned_data.get("password") or secrets.token_urlsafe(12)
        user.set_password(password)
        user.save()
        # 审计（规格 §17 / T10.2）：初始密码绝不进审计 detail。
        record_audit(
            actor=request.user,
            action="user.create",
            object_type=user._meta.label_lower,
            object_pk=str(user.pk),
            target_label=user.username,
            request=request,
        )
        if form.cleaned_data.get("password"):
            messages.success(request, f"用户 {user.username} 已创建")
        else:
            messages.success(
                request, f"已创建用户 {user.username}，初始密码：{password}（仅本次显示）"
            )
        return redirect("accounts:user_list")
    return render(
        request,
        "accounts/user_form.html",
        {
            "form": form,
            "title": "创建用户",
            "permission_bit_fields": [form[bit] for bit in User.PERMISSION_BITS],
        },
    )


@require_permission("can_manage_users")
def user_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑用户：账号字段 + 角色 / 状态 + 11 个权限位复选框。"""
    user = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"用户 {user.username} 已更新")
        record_audit(
            actor=request.user,
            action="user.update",
            object_type=user._meta.label_lower,
            object_pk=str(user.pk),
            target_label=user.username,
            request=request,
        )
        return redirect("accounts:user_list")
    return render(
        request,
        "accounts/user_form.html",
        {
            "form": form,
            "title": f"编辑用户 {user.username}",
            "permission_bit_fields": [form[bit] for bit in User.PERMISSION_BITS],
        },
    )


@require_permission("can_manage_users")
@require_POST
def user_toggle_active(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """启用 / 禁用用户；不允许禁用当前登录账号（避免把自己锁在外面）。"""
    user = get_object_or_404(User, pk=pk)
    if user == request.user and user.is_active:
        messages.error(request, "不能禁用当前登录账号")
        return redirect("accounts:user_list")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    action = "已启用" if user.is_active else "已禁用"
    record_audit(
        actor=request.user,
        action="user.toggle_active",
        object_type=user._meta.label_lower,
        object_pk=str(user.pk),
        target_label=user.username,
        detail={"is_active": user.is_active},
        request=request,
    )
    messages.success(request, f"用户 {user.username} {action}")
    return redirect("accounts:user_list")
