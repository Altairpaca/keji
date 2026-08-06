"""审计日志查看视图（规格 §17，权限位 can_view_audit_logs，T10.2）。

只读列表：时间 / 用户 / 动作 / 对象 / 结果 / IP + 分页，支持 action 下拉与
q 文本筛选。视图保持薄，不承载任何写操作。
"""

from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.permissions import require_permission
from apps.audit.models import AuditLog

#: 每页条数（与 customer_list 一致的量级）。
PAGE_SIZE = 25


@require_permission("can_view_audit_logs")
def audit_list(request: HttpRequest) -> HttpResponse:
    """分页表格 + action 下拉筛选 + q 文本搜索。"""
    queryset: QuerySet[AuditLog] = AuditLog.objects.select_related("actor").order_by("-created_at")

    action = request.GET.get("action", "").strip()
    q = request.GET.get("q", "").strip()
    if action:
        queryset = queryset.filter(action=action)
    if q:
        queryset = queryset.filter(
            Q(action__icontains=q)
            | Q(target_label__icontains=q)
            | Q(object_type__icontains=q)
            | Q(actor__username__icontains=q)
        )

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    # action 下拉候选：只列实际出现过的动作，按字典序。
    action_choices = list(
        AuditLog.objects.order_by("action").values_list("action", flat=True).distinct()
    )

    extra_parts: list[tuple[str, str]] = []
    if action:
        extra_parts.append(("action", action))
    if q:
        extra_parts.append(("q", q))
    extra_query = "&" + urlencode(extra_parts) if extra_parts else ""

    return render(
        request,
        "audit/audit_list.html",
        {
            "page_obj": page_obj,
            "action_choices": action_choices,
            "current_action": action,
            "q": q,
            "extra_query": extra_query,
        },
    )
