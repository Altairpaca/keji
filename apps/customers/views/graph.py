"""客户关系图 JSON 数据视图（规格 §7 / ADR-010，vis-network 消费）。

- GET ``/customers/<uuid>/graph/?depth=2``          全关系网络
- GET ``/customers/<uuid>/referral-graph/?depth=3``  转介绍网络

视图保持薄：只做 HTTP 解析（depth 参数）与 JsonResponse 输出，
图结构由 services.graph 构建。客户不存在返回 404，depth 非法返回 400。
"""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.customers.services.graph import (
    MAX_DEPTH,
    MIN_DEPTH,
    RelationshipGraph,
    build_relationship_graph,
    referral_graph,
)


def _relation_labels(data: RelationshipGraph, center_id: str) -> dict[str, str]:
    """以中心客户为基准的关系标签表：邻居 id -> 关系 label（无向边只记一条）。"""
    labels: dict[str, str] = {}
    for edge in data["edges"]:
        if edge["from"] == center_id:
            labels.setdefault(edge["to"], edge["label"])
        elif edge["to"] == center_id:
            labels.setdefault(edge["from"], edge["label"])
    return labels


def _related_customers(center: Customer, data: RelationshipGraph) -> list[tuple[Customer, str]]:
    """图数据中除中心外的相关客户（模型实例 + 与中心的关系标签），手机端单层列表用。

    排序：先按图中 depth 升序，再按姓名，保证近亲在前。
    """
    center_id = str(center.pk)
    labels = _relation_labels(data, center_id)
    depths = {node["id"]: node["depth"] for node in data["nodes"]}
    node_ids = [node["id"] for node in data["nodes"] if node["id"] != center_id]
    related = list(Customer.objects.filter(pk__in=node_ids))
    related.sort(key=lambda c: (depths.get(str(c.pk), MAX_DEPTH + 1), c.name))
    return [(c, labels.get(str(c.pk), "")) for c in related]


@require_permission("can_view_customers")
@require_GET
def relationship_graph_page(request: HttpRequest, pk: str) -> HttpResponse:
    """关系图页面（桌面 vis-network 交互图 + 手机单层列表，同一响应式模板）。"""
    customer = get_object_or_404(Customer, pk=pk)
    data = build_relationship_graph(customer, max_depth=2)
    return render(
        request,
        "customers/relationship_graph.html",
        {
            "customer": customer,
            "center_data": data,
            "related_customers": _related_customers(customer, data),
            "graph_mode": "relationship",
            "graph_title": "关系图",
        },
    )


@require_permission("can_view_customers")
@require_GET
def referral_graph_page(request: HttpRequest, pk: str) -> HttpResponse:
    """转介绍图页面（只沿 介绍人 / 同家庭 关系展开）。"""
    customer = get_object_or_404(Customer, pk=pk)
    data = referral_graph(customer, max_depth=3)
    return render(
        request,
        "customers/relationship_graph.html",
        {
            "customer": customer,
            "center_data": data,
            "related_customers": _related_customers(customer, data),
            "graph_mode": "referral",
            "graph_title": "转介绍图",
        },
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
