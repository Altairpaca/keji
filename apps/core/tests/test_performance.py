"""性能回归测试（规格 §25：避免 N+1、分页、索引、缓存、查询效率）。

用 CaptureQueriesContext 对关键列表视图做查询数上限断言，防止未来改动重新
引入 N+1；分页断言保证分页器生效；首页统计卡断言 60s 缓存生效；索引断言
锁住高频筛选字段的 db_index（缺失会重新变慢）。

查询数上限取「实测值 + 余量」：随数据量增长查询数应保持不变（分页 + 预取），
若断言失败说明有改动引入了 N+1。
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.claims.models import ClaimCase, ClaimMaterial
from apps.customers.models import Customer, CustomerStatus, Tag
from apps.documents.models import Document
from apps.policies.models import Policy
from apps.tasks.models import Task

#: 造数规模：超过单页 PAGE_SIZE，验证分页生效且查询数不随数据量增长。
BULK = 25
#: 每案件材料数：混合缺失 / 已提交，验证缺料计数不触发 N+1。
MATERIALS_PER_CLAIM = 4


@pytest.fixture(autouse=True)
def _isolated_cache() -> Iterator[None]:
    """清空缓存，避免首页统计卡缓存跨测试串扰（LocMemCache 进程内共享）。"""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def viewer(db: None) -> User:
    user = User.objects.create_user(
        username="perf-viewer", password="pw123456", can_view_customers=True
    )
    assert isinstance(user, User)
    return user


def _login(user: User) -> Client:
    client = Client()
    assert client.login(username=user.username, password="pw123456")
    return client


def _query_count(client: Client, url: str) -> int:
    """发 GET 请求并统计执行 SQL 条数（响应必须 200）。"""
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url)
        assert resp.status_code == 200, f"GET {url} → {resp.status_code}"
    return len(ctx.captured_queries)


# ---------------------------------------------------------------------------
# 查询数上限（N+1 哨兵）
# ---------------------------------------------------------------------------


def test_customer_list_query_count_stays_bounded(db: None, viewer: User) -> None:
    status = CustomerStatus.objects.create(name="活跃", is_active=True)
    tag = Tag.objects.create(name="高净值")
    for i in range(BULK):
        customer = Customer.objects.create(
            name=f"客户{i:02d}", status=status, next_followup_date=timezone.localdate()
        )
        customer.tags.add(tag)

    client = _login(viewer)
    assert _query_count(client, reverse("customers:customer_list")) <= 10
    assert _query_count(client, reverse("customers:customer_list") + "?page=2") <= 10


def test_task_list_query_count_stays_bounded(db: None, viewer: User) -> None:
    customer = Customer.objects.create(name="任务客户")
    for i in range(BULK):
        Task.objects.create(
            title=f"待办{i:02d}",
            due_date=timezone.localdate() + timedelta(days=i % 5),
            customer=customer,
            assignee=viewer,
            created_by=viewer,
        )

    client = _login(viewer)
    assert _query_count(client, reverse("tasks:task_list")) <= 8


def test_claim_list_query_count_no_n1_for_missing_materials(
    db: None, viewer: User
) -> None:
    customer = Customer.objects.create(name="理赔客户")
    statuses = ["not_submitted", "needs_supplement", "submitted", "checked"]
    for i in range(BULK):
        claim = ClaimCase.objects.create(name=f"案件{i:02d}", customer=customer)
        for j in range(MATERIALS_PER_CLAIM):
            ClaimMaterial.objects.create(claim=claim, name=f"材料{j}", status=statuses[j])

    client = _login(viewer)
    # 缺料计数走 annotate：若逐行 missing_materials().count() 将出现 25×N 查询。
    assert _query_count(client, reverse("claims:claim_list")) <= 8


def test_policy_list_query_count_stays_bounded(db: None, viewer: User) -> None:
    customer = Customer.objects.create(name="保单客户")
    for i in range(BULK):
        Policy.objects.create(
            insurer="测试保司",
            name=f"保单{i:02d}",
            policy_no=f"POL-PERF-{i:02d}",
            policyholder=customer,
            status=Policy.Status.ACTIVE,
        )

    client = _login(viewer)
    assert _query_count(client, reverse("policies:policy_list")) <= 8


# ---------------------------------------------------------------------------
# 分页
# ---------------------------------------------------------------------------


def test_list_pagination_second_page_has_content(db: None, viewer: User) -> None:
    for i in range(BULK):
        Task.objects.create(
            title=f"分页待办{i:02d}",
            due_date=timezone.localdate(),
            assignee=viewer,
            created_by=viewer,
        )

    client = _login(viewer)
    page1 = client.get(reverse("tasks:task_list"), {"page": 1})
    assert page1.status_code == 200
    # 同 due_date 时按 created_at 排序：第 1 页 20 条 = 分页待办00..19。
    assert "分页待办00" in page1.content.decode()
    assert "分页待办19" in page1.content.decode()
    assert "分页待办20" not in page1.content.decode()
    # 25 条 > 每页 20 条，第二页仍有内容（而不是空页）。
    page2 = client.get(reverse("tasks:task_list"), {"page": 2})
    assert page2.status_code == 200
    assert "分页待办20" in page2.content.decode()
    assert "分页待办24" in page2.content.decode()


# ---------------------------------------------------------------------------
# 首页统计卡缓存（60s）
# ---------------------------------------------------------------------------


def test_dashboard_stats_served_from_cache(db: None, viewer: User) -> None:
    for i in range(BULK):
        Task.objects.create(
            title=f"统计待办{i:02d}",
            due_date=timezone.localdate(),
            assignee=viewer,
            created_by=viewer,
        )

    client = _login(viewer)
    url = reverse("dashboard:home")
    first = _query_count(client, url)
    second = _query_count(client, url)
    # 第二次请求时 build_stats 的六项聚合命中 60s 缓存，查询数应下降。
    assert second < first, f"统计卡未缓存：首次 {first} 条 SQL，二次 {second} 条"


# ---------------------------------------------------------------------------
# 索引（高频筛选字段必须有 db_index）
# ---------------------------------------------------------------------------


def test_high_frequency_status_fields_are_db_indexed() -> None:
    for model, field in [(Task, "status"), (ClaimCase, "status"), (Policy, "status")]:
        assert model._meta.get_field(field).db_index, f"{model.__name__}.{field} 缺 db_index"


def test_customer_followup_and_document_sha256_indexed() -> None:
    assert Customer._meta.get_field("next_followup_date").db_index
    assert Customer._meta.get_field("status").db_index  # FK 自动索引
    assert Document._meta.get_field("sha256").db_index


def test_task_due_date_and_audit_action_indexed() -> None:
    assert Task._meta.get_field("due_date").db_index
    assert AuditLog._meta.get_field("action").db_index
