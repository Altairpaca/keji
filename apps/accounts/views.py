"""accounts 视图：个人页等轻量视图；登录 / 退出由 django.contrib.auth 提供。"""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """「我的」页：用户名 / 角色 / 权限位展示（权限位由 T3.x 实现）。"""
    return render(request, "accounts/profile.html")
