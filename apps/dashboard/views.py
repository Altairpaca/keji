"""dashboard 视图：登录后首页与全局搜索（规格 §15 / ADR-003）。"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.permissions import require_permission
from apps.core.services.search import SearchResult, search_all
from apps.dashboard.services.queue import build_stats, build_work_queue

#: 结果分组标题（按 ENTITY_SEARCHERS 固定顺序渲染）。
_GROUP_LABELS: dict[str, str] = {
    "customer": "客户",
    "policy": "保单",
    "claim": "理赔",
    "document": "文件",
    "communication": "沟通记录",
}


@require_permission("can_view_customers")
def home(request: HttpRequest) -> HttpResponse:
    """首页：今日工作队列与统计（T9.2 实现）。"""
    user = request.user
    context = {
        "queue": build_work_queue(user),
        "stats": build_stats(),
        # 无完整管理权限时模板显示受限提示（只读视图）。
        "restricted": not user.has_bit("can_manage_customers"),
    }
    return render(request, "dashboard/home.html", context)


@require_permission("can_view_customers")
def global_search(request: HttpRequest) -> HttpResponse:
    """全局搜索：跨客户 / 保单 / 理赔 / 文件 / 沟通，按实体分组渲染结果页。"""
    q = request.GET.get("q", "").strip()
    results = search_all(q)
    grouped: dict[str, list[SearchResult]] = {}
    for result in results:
        grouped.setdefault(result.kind, []).append(result)
    groups = [
        {"kind": kind, "label": _GROUP_LABELS[kind], "results": items}
        for kind, items in grouped.items()
    ]
    return render(request, "dashboard/search.html", {"q": q, "groups": groups})
