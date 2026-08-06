"""core 全局搜索测试（RED 先行，规格 §15 / ADR-003）。

覆盖：
- ``search_all``：空 q、逐实体命中（客户/保单/理赔/文件/沟通）、跨实体顺序、软删过滤、limit
- ``snippet_from``：中文安全、命中片段带省略号
- ``global_search`` 视图：200 分组渲染、无权限 403、空态
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord
from apps.claims.models import ClaimCase
from apps.core.services.search import search_all, snippet_from
from apps.customers.models import Customer, CustomerStatus, Tag
from apps.documents.models import Document
from apps.policies.models import Policy

pytestmark = pytest.mark.django_db

MakeCustomer = Callable[..., Customer]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def viewer(db: None) -> User:
    u = User(username="search-viewer", can_view_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def plain(db: None) -> User:
    u = User(username="search-plain")
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def make_customer(db: None) -> MakeCustomer:
    """按需创建客户，可注入任意字段（name 默认张伟）。"""

    def _make(**kwargs: object) -> Customer:
        kwargs.setdefault("name", "张伟")
        c: Customer = Customer.objects.create(**kwargs)
        return c

    return _make


@pytest.fixture
def make_policy(db: None) -> Callable[..., Policy]:
    def _make(customer: Customer, **kwargs: object) -> Policy:
        kwargs.setdefault("policy_no", f"P-{uuid.uuid4().hex[:8]}")
        kwargs.setdefault("name", "重疾险")
        kwargs.setdefault("insurer", "平安人寿")
        p: Policy = Policy.objects.create(policyholder=customer, **kwargs)
        return p

    return _make


@pytest.fixture
def make_claim(db: None) -> Callable[..., ClaimCase]:
    def _make(customer: Customer, **kwargs: object) -> ClaimCase:
        kwargs.setdefault("name", "医疗理赔")
        c: ClaimCase = ClaimCase.objects.create(customer=customer, **kwargs)
        return c

    return _make


@pytest.fixture
def make_document(db: None) -> Callable[..., Document]:
    def _make(**kwargs: object) -> Document:
        kwargs.setdefault("original_name", f"scan-{uuid.uuid4().hex[:8]}.png")
        kwargs.setdefault("storage_key", f"originals/ab/{uuid.uuid4()}")
        kwargs.setdefault("mime_type", "image/png")
        kwargs.setdefault("size", 10)
        d: Document = Document.objects.create(**kwargs)
        return d

    return _make


@pytest.fixture
def make_communication(db: None) -> Callable[..., CommunicationRecord]:
    def _make(customer: Customer, **kwargs: object) -> CommunicationRecord:
        kwargs.setdefault("channel", "phone")
        c: CommunicationRecord = CommunicationRecord.objects.create(customer=customer, **kwargs)
        return c

    return _make


# ---------------------------------------------------------------------------
# search_all：空 q 与 snippet
# ---------------------------------------------------------------------------


def test_search_all_empty_q_returns_empty() -> None:
    assert search_all("") == []
    assert search_all("   ") == []


def test_snippet_from_empty_text_returns_empty() -> None:
    assert snippet_from("", "张三") == ""


def test_snippet_from_centers_on_hit_with_ellipsis() -> None:
    text = "前" * 40 + "张三" + "后" * 40
    sn = snippet_from(text, "张三")
    assert "张三" in sn
    assert sn.startswith("…")
    assert sn.endswith("…")


def test_snippet_from_chinese_safe() -> None:
    text = "中" * 200
    sn = snippet_from(text, "中")
    assert "�" not in sn


def test_snippet_from_not_found_returns_head() -> None:
    text = "abcdefghij" * 10
    sn = snippet_from(text, "zzz")
    assert sn.startswith("abcd")
    assert len(sn) < len(text)


# ---------------------------------------------------------------------------
# search_all：客户命中
# ---------------------------------------------------------------------------


def test_customer_match_by_name(make_customer: MakeCustomer) -> None:
    c = make_customer(name="张伟")
    results = search_all("张伟")
    assert len(results) == 1
    r = results[0]
    assert r.kind == "customer"
    assert r.pk == c.pk
    assert r.title == "张伟"
    assert r.url == reverse("customers:customer_detail", args=[c.pk])
    assert r.occurred_at == c.created_at


def test_customer_match_by_phone(make_customer: MakeCustomer) -> None:
    c = make_customer(name="李静", phone="13800138000")
    results = search_all("13800138000")
    assert len(results) == 1
    assert results[0].pk == c.pk
    assert results[0].kind == "customer"


def test_customer_match_by_wechat(make_customer: MakeCustomer) -> None:
    c = make_customer(name="李静", wechat_nickname="lijing_2026")
    results = search_all("lijing")
    assert len(results) == 1
    assert results[0].pk == c.pk


def test_customer_match_by_tag(make_customer: MakeCustomer) -> None:
    c = make_customer(name="李静")
    tag = Tag.objects.create(name="高净值")
    c.tags.add(tag)
    results = search_all("高净值")
    assert len(results) == 1
    assert results[0].pk == c.pk


def test_customer_match_by_status(make_customer: MakeCustomer) -> None:
    c = make_customer(name="李静")
    c.status = CustomerStatus.objects.create(name="重点跟进")
    c.save(update_fields=["status"])
    results = search_all("重点跟进")
    assert len(results) == 1
    assert results[0].pk == c.pk


def test_customer_match_by_notes(make_customer: MakeCustomer) -> None:
    c = make_customer(name="李静", notes="喜欢分红型保险产品")
    results = search_all("分红")
    assert len(results) == 1
    r = results[0]
    assert r.pk == c.pk
    assert "分红" in r.snippet


def test_customer_search_distinct_on_tag_join(make_customer: MakeCustomer) -> None:
    c = make_customer(name="李静")
    c.tags.add(Tag.objects.create(name="vip"))
    c.tags.add(Tag.objects.create(name="重点"))
    results = search_all("vip")
    assert len(results) == 1
    assert results[0].pk == c.pk


# ---------------------------------------------------------------------------
# search_all：保单 / 理赔 / 文件 / 沟通命中
# ---------------------------------------------------------------------------


def test_policy_match_by_policy_no(
    make_customer: MakeCustomer, make_policy: Callable[..., Policy]
) -> None:
    c = make_customer(name="林小明")
    p = make_policy(c, policy_no="P-2026-0001", name="重疾险", insurer="平安人寿")
    results = search_all("P-2026")
    assert len(results) == 1
    r = results[0]
    assert r.kind == "policy"
    assert r.pk == p.pk
    assert r.url == reverse("policies:policy_detail", args=[p.pk])


def test_policy_match_by_name(
    make_customer: MakeCustomer, make_policy: Callable[..., Policy]
) -> None:
    c = make_customer(name="林小明")
    p = make_policy(c, name="百万医疗险")
    results = search_all("百万医疗")
    assert len(results) == 1
    assert results[0].pk == p.pk


def test_policy_match_by_insurer(
    make_customer: MakeCustomer, make_policy: Callable[..., Policy]
) -> None:
    c = make_customer(name="林小明")
    p = make_policy(c, insurer="平安人寿")
    results = search_all("平安人寿")
    assert len(results) == 1
    assert results[0].pk == p.pk


def test_policy_match_by_policyholder_name(
    make_customer: MakeCustomer, make_policy: Callable[..., Policy]
) -> None:
    c = make_customer(name="王芳")
    p = make_policy(c, name="寿险")
    results = search_all("王芳")
    assert any(r.kind == "policy" and r.pk == p.pk for r in results)


def test_claim_match_by_name(
    make_customer: MakeCustomer, make_claim: Callable[..., ClaimCase]
) -> None:
    c = make_customer(name="林小明")
    claim = make_claim(c, name="张伟-医疗理赔")
    results = search_all("医疗理赔")
    assert len(results) == 1
    r = results[0]
    assert r.kind == "claim"
    assert r.pk == claim.pk
    assert r.title == "张伟-医疗理赔"
    assert r.url == ""


def test_claim_match_by_description(
    make_customer: MakeCustomer, make_claim: Callable[..., ClaimCase]
) -> None:
    c = make_customer(name="林小明")
    claim = make_claim(c, description="车祸住院产生的费用")
    results = search_all("车祸")
    assert len(results) == 1
    assert results[0].pk == claim.pk
    assert "车祸" in results[0].snippet


def test_claim_match_by_customer_name(
    make_customer: MakeCustomer, make_claim: Callable[..., ClaimCase]
) -> None:
    c = make_customer(name="王芳")
    claim = make_claim(c, name="住院理赔")
    results = search_all("王芳")
    assert any(r.kind == "claim" and r.pk == claim.pk for r in results)


def test_document_match_by_original_name(make_document: Callable[..., Document]) -> None:
    d = make_document(
        original_name="张伟-身份证正反面.png", title="证件照", note="客户身份证扫描件"
    )
    results = search_all("身份证")
    assert len(results) == 1
    r = results[0]
    assert r.kind == "document"
    assert r.pk == d.pk
    assert r.url == ""


def test_document_match_by_title(make_document: Callable[..., Document]) -> None:
    d = make_document(title="体检报告")
    results = search_all("体检报告")
    assert len(results) == 1
    assert results[0].pk == d.pk
    assert results[0].title == "体检报告"


def test_document_match_by_note(make_document: Callable[..., Document]) -> None:
    d = make_document(note="客户投保时提供的房产证明")
    results = search_all("房产")
    assert len(results) == 1
    assert results[0].pk == d.pk


def test_communication_match_by_content(
    make_customer: MakeCustomer, make_communication: Callable[..., CommunicationRecord]
) -> None:
    c = make_customer(name="林小明")
    comm = make_communication(c, channel="phone", content="详细讨论了重疾险保障")
    results = search_all("重疾险")
    assert len(results) == 1
    r = results[0]
    assert r.kind == "communication"
    assert r.pk == comm.pk
    assert r.occurred_at == comm.occurred_at


def test_communication_match_by_feedback(
    make_customer: MakeCustomer, make_communication: Callable[..., CommunicationRecord]
) -> None:
    c = make_customer(name="林小明")
    comm = make_communication(c, channel="wechat", customer_feedback="对方案很感兴趣")
    results = search_all("很感兴趣")
    assert len(results) == 1
    assert results[0].pk == comm.pk


def test_communication_match_by_next_plan(
    make_customer: MakeCustomer, make_communication: Callable[..., CommunicationRecord]
) -> None:
    c = make_customer(name="林小明")
    comm = make_communication(c, next_plan="下周安排上门拜访")
    results = search_all("上门拜访")
    assert len(results) == 1
    assert results[0].pk == comm.pk


def test_communication_match_by_customer_name(
    make_customer: MakeCustomer, make_communication: Callable[..., CommunicationRecord]
) -> None:
    c = make_customer(name="王芳")
    comm = make_communication(c, content="电话寒暄")
    results = search_all("王芳")
    assert any(r.kind == "communication" and r.pk == comm.pk for r in results)


# ---------------------------------------------------------------------------
# search_all：跨实体 / 顺序 / limit / 软删
# ---------------------------------------------------------------------------


def test_cross_entity_search_fixed_order(
    make_customer: MakeCustomer, make_policy: Callable[..., Policy]
) -> None:
    make_customer(name="张伟")
    c = make_customer(name="其他")
    make_policy(c, name="张伟专属保单")
    results = search_all("张伟")
    kinds = [r.kind for r in results]
    assert kinds == ["customer", "policy"]


def test_search_all_respects_limit_per_entity(make_customer: MakeCustomer) -> None:
    for i in range(25):
        make_customer(name=f"张伟{i}")
    assert len(search_all("张伟")) == 20
    assert len(search_all("张伟", limit_per_entity=5)) == 5


def test_soft_deleted_objects_excluded(make_customer: MakeCustomer) -> None:
    c = make_customer(name="张伟")
    c.delete()
    assert search_all("张伟") == []


def test_soft_deleted_policy_excluded(
    make_customer: MakeCustomer, make_policy: Callable[..., Policy]
) -> None:
    c = make_customer(name="林小明")
    p = make_policy(c, name="张伟专属保单")
    p.delete()
    results = search_all("张伟专属")
    assert results == []


# ---------------------------------------------------------------------------
# global_search 视图
# ---------------------------------------------------------------------------


def test_global_search_view_renders_groups(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    make_customer(name="张伟", notes="喜欢分红险")
    client.force_login(viewer)
    resp = client.get(reverse("dashboard:search"), {"q": "分红"})
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "客户" in content
    assert "张伟" in content


def test_global_search_view_denied_for_plain_user(client: Any, plain: User) -> None:
    client.force_login(plain)
    resp = client.get(reverse("dashboard:search"), {"q": "张伟"})
    assert resp.status_code == 403


def test_global_search_view_empty_q_shows_empty_state(client: Any, viewer: User) -> None:
    client.force_login(viewer)
    resp = client.get(reverse("dashboard:search"), {"q": ""})
    assert resp.status_code == 200
    assert "没有找到" in resp.content.decode()


def test_global_search_view_no_hits_shows_empty_state(client: Any, viewer: User) -> None:
    client.force_login(viewer)
    resp = client.get(reverse("dashboard:search"), {"q": "完全不存在的内容"})
    assert resp.status_code == 200
    assert "没有找到" in resp.content.decode()
