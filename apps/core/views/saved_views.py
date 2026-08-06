"""保存视图视图（core，规格 §15）：保存当前筛选 / 列表 / 应用 / 删除。

视图保持薄：数据读写全部经 apps.core.services.saved_views；同名覆盖的
「先查后更」归约在视图层（服务层只提供新增，见其 docstring）。
权限统一走 accounts.require_permission（ADR-004 / ADR-012）。
"""

import json
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import require_permission
from apps.core.models.saved_view import SavedView
from apps.core.services.saved_views import delete_view, list_views, save_view

# 已接入保存视图的列表页（app_label, model_name）→ 列表 URL 名。
_LIST_URL_NAMES: dict[tuple[str, str], str] = {
    ("customers", "customer"): "customers:customer_list",
}


def _is_safe_next(value: str) -> bool:
    """next 仅允许站内相对路径，杜绝开放重定向。"""
    return value.startswith("/") and not value.startswith("//")


@require_permission("can_view_customers")
@require_POST
def save_current_view(request: HttpRequest) -> HttpResponse:
    """保存当前筛选为命名视图；同名（owner+app/model+name）覆盖更新。

    参数：app_label / model_name / name / filters(JSON 字符串) / sorts(可选)。
    返回：带 next 则 redirect 回来源，否则 JSON。
    """
    name = request.POST.get("name", "").strip()
    app_label = request.POST.get("app_label", "").strip()
    model_name = request.POST.get("model_name", "").strip()
    if not (name and app_label and model_name):
        return _bad_request(request, "视图名与应用/模型标识不能为空")

    try:
        filters = json.loads(request.POST.get("filters", "{}") or "{}")
        sorts = json.loads(request.POST.get("sorts", "[]") or "[]")
    except json.JSONDecodeError:
        return _bad_request(request, "筛选条件不是合法 JSON")
    if not isinstance(filters, dict):
        return _bad_request(request, "筛选条件必须是 JSON 对象")
    if not isinstance(sorts, list):
        return _bad_request(request, "排序条件必须是 JSON 数组")

    existing = SavedView.objects.filter(
        owner=request.user, app_label=app_label, model_name=model_name, name=name
    ).first()
    if existing is not None:
        existing.filters = filters
        existing.sorts = sorts
        existing.save(update_fields=["filters", "sorts"])
    else:
        save_view(request.user, name, app_label, model_name, filters, sorts)

    messages.success(request, f"视图「{name}」已保存")
    next_url = request.POST.get("next", "").strip()
    if _is_safe_next(next_url):
        return redirect(next_url)
    return JsonResponse({"ok": True, "name": name})


@require_permission("can_view_customers")
@require_GET
def list_saved_views(request: HttpRequest) -> HttpResponse:
    """按 app/model 列出当前用户的保存视图（JSON，供列表页/HTMX 消费）。"""
    app_label = request.GET.get("app", "").strip()
    model_name = request.GET.get("model", "").strip()
    views = list_views(request.user, app_label, model_name)
    return JsonResponse(
        {
            "views": [
                {
                    "id": str(view.id),
                    "name": view.name,
                    "filters": view.filters,
                    "sorts": view.sorts,
                }
                for view in views
            ]
        }
    )


@require_permission("can_view_customers")
@require_GET
def apply_saved_view(request: HttpRequest, pk: Any) -> HttpResponse:
    """应用保存视图：按 app/model 重定向到对应列表页并带筛选参数。

    filters dict 转 query string：标量键值原样输出，list 值展开为多参数
    （如 tag 多选）。
    """
    view = get_object_or_404(SavedView, pk=pk, owner=request.user)
    url_name = _LIST_URL_NAMES.get((view.app_label, view.model_name))
    if url_name is None:
        raise Http404(f"未找到 {view.app_label}.{view.model_name} 对应的列表页")

    query: list[tuple[str, str]] = []
    for key, value in view.filters.items():
        if isinstance(value, list):
            query.extend((key, str(item)) for item in value)
        elif value is not None and value != "":
            query.append((key, str(value)))

    url = reverse(url_name)
    if query:
        url = f"{url}?{urlencode(query)}"
    return redirect(url)


@require_permission("can_view_customers")
@require_POST
def delete_saved_view(request: HttpRequest, pk: Any) -> HttpResponse:
    """删除保存视图（仅所有者，他人 403）。"""
    view = get_object_or_404(SavedView, pk=pk)
    try:
        delete_view(view, request.user)
    except PermissionError:
        raise PermissionDenied from None
    messages.success(request, f"视图「{view.name}」已删除")
    next_url = request.POST.get("next", "").strip()
    if _is_safe_next(next_url):
        return redirect(next_url)
    return redirect("customers:customer_list")


def _bad_request(request: HttpRequest, message: str) -> HttpResponse:
    """参数/JSON 校验失败：有 next 则带错误信息返回，否则返回 JSON 400。"""
    next_url = request.POST.get("next", "").strip()
    if _is_safe_next(next_url):
        messages.error(request, message)
        return redirect(next_url)
    return JsonResponse({"ok": False, "error": message}, status=400)
