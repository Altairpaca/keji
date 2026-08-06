"""dashboard 视图：登录后首页。工作队列统计由 T9.2 实现，当前为壳。"""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """首页：今日工作队列与统计（T9.2 实现）。"""
    return render(request, "dashboard/home.html")
