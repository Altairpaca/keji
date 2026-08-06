"""PWA 视图：manifest、Service Worker 与离线错误页（规格 §4，ADR-014）。

- /manifest.json：读取 static/manifest.json 输出（保证 application/json，与部署方式无关）
- /sw.js：以 Django 视图返回，作用域为根路径，可接管全站导航。
- /offline/：公开离线错误页，无登录要求（SW 离线回退目标）。
"""

from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.template.loader import render_to_string


def manifest(request: HttpRequest) -> HttpResponse:
    """返回 PWA manifest（application/json）。"""
    found = finders.find("manifest.json")
    if found is None:
        return HttpResponseNotFound()
    return HttpResponse(
        Path(found).read_text(encoding="utf-8"),
        content_type="application/json",
    )


def service_worker(request: HttpRequest) -> HttpResponse:
    """返回 Service Worker 脚本（application/javascript）。"""
    body = render_to_string("core/sw.js", request=request)
    return HttpResponse(body, content_type="application/javascript")


def offline_page(request: HttpRequest) -> HttpResponse:
    """离线错误页：提示离线并提供重试入口。"""
    return render(request, "core/offline.html")
