"""客户关系图 JSON 数据服务（规格 §7 / ADR-010，vis-network 消费格式）。

- ``build_relationship_graph``：从中心客户 BFS 展开有限层级（默认 2）的全关系网络；
- ``referral_graph``：转介绍图，只沿 介绍人 / same_household 关系展开。

有向存储（from → to）在查询层双向可见（复用 services.relations.get_relations）；
图中无向关系（配偶 / 父母子女 / 家庭 / 同一家庭 / 自定义）同一对客户只输出一条边
（排序键去重，方向取先发现的关系行），referrer 视为有向、保留 from → to 方向。
"""

from collections import deque
from typing import TypedDict

from apps.customers.models import Customer
from apps.customers.services.relations import get_relations

MIN_DEPTH = 1
MAX_DEPTH = 5

RELATION_LABELS: dict[str, str] = {
    "spouse": "配偶",
    "parent_child": "父母子女",
    "family": "家庭成员",
    "referrer": "介绍人",
    "same_household": "同一家庭",
    "custom": "其他",
}

RELATION_COLORS: dict[str, str] = {
    "spouse": "#e11d48",
    "parent_child": "#2563eb",
    "family": "#16a34a",
    "referrer": "#f59e0b",
    "same_household": "#7c3aed",
    "custom": "#64748b",
}

# 无向关系类型：同对客户只输出一条边；referrer 除外（保留方向）。
_UNDIRECTED = frozenset({"spouse", "parent_child", "family", "same_household", "custom"})


class GraphNode(TypedDict):
    id: str
    label: str
    phone: str
    status: str
    is_center: bool
    depth: int


# "from" 为 Python 关键字，故 GraphEdge 用函数式 TypedDict。
GraphEdge = TypedDict(
    "GraphEdge",
    {
        "from": str,
        "to": str,
        "relation_type": str,
        "label": str,
        "color": str,
    },
)


class RelationshipGraph(TypedDict):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _validate_depth(max_depth: int) -> None:
    if not MIN_DEPTH <= max_depth <= MAX_DEPTH:
        raise ValueError(f"max_depth 必须在 {MIN_DEPTH} 到 {MAX_DEPTH} 之间，当前为 {max_depth}")


def _node_data(customer: Customer, depth: int, is_center: bool) -> GraphNode:
    return {
        "id": str(customer.pk),
        "label": customer.name,
        "phone": customer.phone,
        "status": customer.status.name if customer.status else "",
        "is_center": is_center,
        "depth": depth,
    }


def _edge_data(relation_type: str, from_pk: object, to_pk: object) -> GraphEdge:
    return {
        "from": str(from_pk),
        "to": str(to_pk),
        "relation_type": relation_type,
        "label": RELATION_LABELS[relation_type],
        "color": RELATION_COLORS[relation_type],
    }


def _bfs_graph(
    center_customer: Customer,
    *,
    max_depth: int,
    allowed_types: frozenset[str] | None,
) -> RelationshipGraph:
    """BFS 从中心客户展开关系网络；visited 防环、层级受限、只含未删除客户。"""
    _validate_depth(max_depth)

    nodes: list[GraphNode] = [_node_data(center_customer, 0, is_center=True)]
    edges: list[GraphEdge] = []
    seen_nodes: set[int] = {center_customer.pk}
    edge_keys: set[tuple[object, ...]] = set()

    queue: deque[tuple[Customer, int]] = deque([(center_customer, 0)])
    while queue:
        customer, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for relation in get_relations(customer).select_related("from_customer", "to_customer"):
            if allowed_types is not None and relation.relation_type not in allowed_types:
                continue
            if relation.from_customer_id == customer.pk:
                other = relation.to_customer
                from_pk, to_pk = customer.pk, other.pk
            else:
                other = relation.from_customer
                from_pk, to_pk = other.pk, customer.pk
            if other.is_deleted:
                continue
            # 无向关系同对客户只保留一条边；referrer 保留方向。
            if relation.relation_type in _UNDIRECTED:
                edge_key: tuple[object, ...] = tuple(sorted((from_pk, to_pk)))
            else:
                edge_key = (from_pk, to_pk)
            if edge_key in edge_keys:
                continue
            edge_keys.add(edge_key)
            edges.append(_edge_data(relation.relation_type, from_pk, to_pk))
            if other.pk not in seen_nodes:
                seen_nodes.add(other.pk)
                nodes.append(_node_data(other, depth + 1, is_center=False))
                queue.append((other, depth + 1))

    return {"nodes": nodes, "edges": edges}


def build_relationship_graph(center_customer: Customer, *, max_depth: int = 2) -> RelationshipGraph:
    """全关系网络：沿全部关系类型 BFS 展开（center 为 depth 0）。"""
    return _bfs_graph(center_customer, max_depth=max_depth, allowed_types=None)


def referral_graph(center_customer: Customer, *, max_depth: int = 3) -> RelationshipGraph:
    """转介绍图：只沿 介绍人 / 同一家庭 关系展开。"""
    return _bfs_graph(
        center_customer,
        max_depth=max_depth,
        allowed_types=frozenset({"referrer", "same_household"}),
    )
