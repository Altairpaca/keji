"""客户关系图 JSON 数据视图（规格 §7 / ADR-010，vis-network 消费）。

- GET ``/customers/<uuid>/graph/?depth=2``          全关系网络
- GET ``/customers/<uuid>/referral-graph/?depth=3``  转介绍网络

视图保持薄：只做 HTTP 解析（depth 参数）与 JsonResponse 输出，
图结构由 services.graph 构建。客户不存在返回 404，depth 非法返回 400。
"""

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.customers.services.graph import (
    MAX_DEPTH,
    MIN_DEPTH,
    build_relationship_graph,
    referral_graph,
)


def _depth_from_request(request: HttpRequest, default: int) -> int:
    """解析 ?depth= 参数；缺省用 default，非法（非整数 / 超限）抛 ValueError。"""
    raw = request.GET.get("depth", "").strip()
    if not raw:
        return default
    try:
        depth = int(raw)
    except ValueError as exc:
        raise ValueError("depth 必须是整数") from exc
    if not MIN_DEPTH <= depth <= MAX_DEPTH:
        raise ValueError(f"depth 必须在 {MIN_DEPTH} 到 {MAX_DEPTH} 之间")
    return depth


@require_permission("can_view_customers")
@require_GET
def relationship_graph_data(request: HttpRequest, pk: str) -> JsonResponse:
    """全关系网络图数据（默认 depth=2）。"""
    customer = get_object_or_404(Customer, pk=pk)
    try:
        depth = _depth_from_request(request, default=2)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(build_relationship_graph(customer, max_depth=depth))


@require_permission("can_view_customers")
@require_GET
def referral_graph_data(request: HttpRequest, pk: str) -> JsonResponse:
    """转介绍图数据（默认 depth=3）。"""
    customer = get_object_or_404(Customer, pk=pk)
    try:
        depth = _depth_from_request(request, default=3)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(referral_graph(customer, max_depth=depth))
