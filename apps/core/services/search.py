"""跨模型全局搜索（规格 §15 / ADR-003）。

搜索实现用 ORM ``icontains`` + ``Q`` 组合，适合当前数据规模；
``pg_trgm`` 扩展通过数据迁移启用（apps/core/migrations/0002_enable_pg_trgm.py），
作为后续 trigram 索引 / 相关度排序的备选能力。

架构：``ENTITY_SEARCHERS`` 注册表（registry）模式——每个实体一个搜索函数，
新增可搜索实体时只需追加一个函数到列表，``search_all`` 无需改动。
每个搜索函数内部已按 ``LIMIT_PER_ENTITY`` 截断，且默认 manager（objects）
自动过滤软删除对象。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db.models import Q
from django.urls import reverse

from apps.activities.models import CommunicationRecord
from apps.claims.models import ClaimCase
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.policies.models import Policy

LIMIT_PER_ENTITY = 20
_ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class SearchResult:
    """一条搜索结果。``url`` 为空表示该实体暂无独立详情页。"""

    kind: str
    pk: UUID
    title: str
    snippet: str
    url: str
    occurred_at: datetime


def snippet_from(text: str, q: str, radius: int = 30) -> str:
    """截取 ``text`` 中 ``q`` 命中处前后各 ``radius`` 字符的片段，用于列表高亮。

    - 命中时在片段首尾补 ``…``（在文本边界侧省略）；
    - 未命中或文本为空时返回头部截断（不超过 2×radius 字符）；
    - 按字符（code point）切片，不会切坏 UTF-8 中文。
    """
    if not text:
        return ""
    idx = text.lower().find(q.lower())
    if idx == -1:
        return _truncate_head(text, radius * 2)
    start = max(0, idx - radius)
    end = min(len(text), idx + len(q) + radius)
    head = _ELLIPSIS if start > 0 else ""
    tail = _ELLIPSIS if end < len(text) else ""
    return f"{head}{text[start:end]}{tail}"


def _truncate_head(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _ELLIPSIS


def _customer_text(c: Customer) -> str:
    return " ".join(filter(None, [c.name, c.phone, c.wechat_nickname, c.notes]))


def search_customers(q: str, limit: int = LIMIT_PER_ENTITY) -> list[SearchResult]:
    """客户搜索：姓名 / 手机号 / 微信昵称 / 备注 / 标签 / 状态名。"""
    customers = (
        Customer.objects.filter(
            Q(name__icontains=q)
            | Q(phone__icontains=q)
            | Q(wechat_nickname__icontains=q)
            | Q(notes__icontains=q)
            | Q(tags__name__icontains=q)
            | Q(status__name__icontains=q)
        )
        .distinct()
        .select_related("status")[:limit]
    )
    return [
        SearchResult(
            kind="customer",
            pk=c.pk,
            title=c.name,
            snippet=snippet_from(_customer_text(c), q),
            url=reverse("customers:customer_detail", args=[c.pk]),
            occurred_at=c.created_at,
        )
        for c in customers
    ]


def search_policies(q: str, limit: int = LIMIT_PER_ENTITY) -> list[SearchResult]:
    """保单搜索：保单号 / 名称 / 保险公司 / 投保人姓名。"""
    policies = Policy.objects.filter(
        Q(policy_no__icontains=q)
        | Q(name__icontains=q)
        | Q(insurer__icontains=q)
        | Q(policyholder__name__icontains=q)
    ).select_related("policyholder")[:limit]
    return [
        SearchResult(
            kind="policy",
            pk=p.pk,
            title=f"{p.insurer} {p.name}",
            snippet=snippet_from(f"{p.policy_no} {p.remark}".strip(), q),
            url=reverse("policies:policy_detail", args=[p.pk]),
            occurred_at=p.created_at,
        )
        for p in policies
    ]


def search_claims(q: str, limit: int = LIMIT_PER_ENTITY) -> list[SearchResult]:
    """理赔搜索：案件名 / 案件说明 / 关联客户姓名。"""
    claims = ClaimCase.objects.filter(
        Q(name__icontains=q) | Q(description__icontains=q) | Q(customer__name__icontains=q)
    ).select_related("customer")[:limit]
    return [
        SearchResult(
            kind="claim",
            pk=c.pk,
            title=c.name,
            snippet=snippet_from(c.description or "", q),
            url="",
            occurred_at=c.created_at,
        )
        for c in claims
    ]


def search_documents(q: str, limit: int = LIMIT_PER_ENTITY) -> list[SearchResult]:
    """文件搜索：原始文件名 / 标题 / 备注。"""
    documents = Document.objects.filter(
        Q(original_name__icontains=q) | Q(title__icontains=q) | Q(note__icontains=q)
    )[:limit]
    return [
        SearchResult(
            kind="document",
            pk=d.pk,
            title=d.title or d.original_name,
            snippet=snippet_from(" ".join(filter(None, [d.title, d.original_name, d.note])), q),
            url="",
            occurred_at=d.created_at,
        )
        for d in documents
    ]


def search_communications(q: str, limit: int = LIMIT_PER_ENTITY) -> list[SearchResult]:
    """沟通记录搜索：主要内容 / 客户反馈 / 下一步计划 / 关联客户姓名。"""
    communications = CommunicationRecord.objects.filter(
        Q(content__icontains=q)
        | Q(customer_feedback__icontains=q)
        | Q(next_plan__icontains=q)
        | Q(customer__name__icontains=q)
    ).select_related("customer")[:limit]
    return [
        SearchResult(
            kind="communication",
            pk=c.pk,
            title=str(c),
            snippet=snippet_from(
                " ".join(filter(None, [c.content, c.customer_feedback, c.next_plan])), q
            ),
            url="",
            occurred_at=c.occurred_at,
        )
        for c in communications
    ]


#: 搜索注册表：顺序即结果分组顺序（客户→保单→理赔→文件→沟通）。
ENTITY_SEARCHERS: list[Callable[[str], list[SearchResult]]] = [
    search_customers,
    search_policies,
    search_claims,
    search_documents,
    search_communications,
]


def search_all(q: str, *, limit_per_entity: int = LIMIT_PER_ENTITY) -> list[SearchResult]:
    """跨实体全局搜索。``q`` 去首尾空白，空字符串返回 ``[]``。

    结果按 ``ENTITY_SEARCHERS`` 注册顺序拼接（客户→保单→理赔→文件→沟通），
    每个实体最多 ``limit_per_entity`` 条。
    """
    q = q.strip()
    if not q:
        return []
    results: list[SearchResult] = []
    for searcher in ENTITY_SEARCHERS:
        results.extend(searcher(q)[:limit_per_entity])
    return results
