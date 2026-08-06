"""首页工作队列与统计服务测试（T9.2，规格 §14）。

覆盖：12 个队列各自在有数据时非空且计数正确、展示条数上限、用户归属收窄、
统计卡各指标计数、备份占位状态。
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord
from apps.claims.models import ClaimCase, ClaimMaterial
from apps.customers.models import Customer, CustomerStatus
from apps.dashboard.services.queue import build_stats, build_work_queue
from apps.documents.models import Album, Document
from apps.policies.models import Policy
from apps.tasks.models import Task

#: build_work_queue 应返回的全部队列键（规格 §14 首页 12 队列）。
QUEUE_KEYS = {
    "today_due",
    "overdue",
    "waiting_customer",
    "waiting_insurer",
    "claims_missing_materials",
    "this_week_meetings",
    "long_no_contact",
    "premiums_due",
    "uncategorized_documents",
    "recent_uploads",
    "backup_status",
    "storage_usage",
}


@pytest.fixture
def owner(db: None) -> User:
    user = User.objects.create_user(username="owner", password="pw")
    assert isinstance(user, User)
    return user


@pytest.fixture
def waiting_reply(db: None) -> CustomerStatus:
    status, _ = CustomerStatus.objects.get_or_create(name="等待回复")
    assert isinstance(status, CustomerStatus)
    return status


def _backdate(obj: Any, days: int) -> None:
    """把对象 created_at 回拨 days 天（created_at 为 auto_now_add）。"""
    cls = obj.__class__
    cls.objects.filter(pk=obj.pk).update(created_at=timezone.now() - timedelta(days=days))


def test_work_queue_has_all_twelve_keys(db: None, owner: User) -> None:
    queue = build_work_queue()
    assert set(queue) == QUEUE_KEYS


def test_work_queue_populates_each_data_queue(
    db: None, owner: User, waiting_reply: CustomerStatus
) -> None:
    today = timezone.localdate()

    # 等待回复客户（队列 3）
    waiting_customer = Customer.objects.create(name="王等待", status=waiting_reply, age_note="30岁")
    # 本周约见客户（队列 6）
    meeting_customer = Customer.objects.create(
        name="李约见", next_followup_date=today + timedelta(days=2), age_note="30岁"
    )
    # 长期未联系客户（队列 7）
    Customer.objects.create(
        name="张久未", last_contact_date=today - timedelta(days=31), age_note="30岁"
    )
    # 今日任务（队列 1）
    Task.objects.create(title="今日必办", due_date=today, status=Task.Status.OPEN)
    # 逾期任务（队列 2）
    Task.objects.create(
        title="逾期事项", due_date=today - timedelta(days=1), status=Task.Status.OPEN
    )
    # 保险公司审核中理赔（队列 4）
    ClaimCase.objects.create(name="住院理赔", customer=waiting_customer, status="insurer_reviewing")
    # 理赔缺料（队列 5）
    claim_missing = ClaimCase.objects.create(
        name="门诊理赔", customer=meeting_customer, status="collecting_materials"
    )
    ClaimMaterial.objects.create(claim=claim_missing, name="身份证", status="not_submitted")
    # 近期缴费保单（队列 8）
    Policy.objects.create(
        insurer="平安",
        name="医疗险",
        policy_no="P-001",
        policyholder=waiting_customer,
        effective_date=today,
        payment_frequency="annual",
        premium_amount="500",
        status=Policy.Status.ACTIVE,
    )
    # 未分类文件（10 天前，仅进未分类队列，不进最近上传）
    uncat_doc = Document.objects.create(
        original_name="旧发票.jpg",
        storage_key="k-uncat",
        mime_type="image/jpeg",
        size=1000,
        sha256="a" * 64,
    )
    _backdate(uncat_doc, days=10)
    # 最近上传文件（带相册，仅进最近上传队列）
    recent_doc = Document.objects.create(
        original_name="新照片.jpg",
        storage_key="k-recent",
        mime_type="image/jpeg",
        size=2000,
        sha256="b" * 64,
    )
    recent_doc.albums.add(Album.objects.create(name="家庭相册"))

    queue = build_work_queue()

    assert queue["today_due"]["count"] == 1
    assert queue["today_due"]["items"][0]["title"] == "今日必办"
    assert queue["overdue"]["count"] == 1
    assert queue["overdue"]["items"][0]["title"] == "逾期事项"
    assert queue["waiting_customer"]["count"] == 1
    assert queue["waiting_customer"]["items"][0]["title"] == "王等待"
    assert queue["waiting_insurer"]["count"] == 1
    assert queue["waiting_insurer"]["items"][0]["title"] == "住院理赔"
    assert queue["claims_missing_materials"]["count"] == 1
    assert queue["claims_missing_materials"]["items"][0]["title"] == "门诊理赔"
    assert queue["this_week_meetings"]["count"] == 1
    assert queue["this_week_meetings"]["items"][0]["title"] == "李约见"
    assert queue["long_no_contact"]["count"] == 1
    assert queue["long_no_contact"]["items"][0]["title"] == "张久未"
    assert queue["premiums_due"]["count"] == 1
    assert queue["uncategorized_documents"]["count"] == 1
    assert queue["uncategorized_documents"]["items"][0]["title"] == "旧发票.jpg"
    assert queue["recent_uploads"]["count"] == 1
    assert queue["recent_uploads"]["items"][0]["title"] == "新照片.jpg"
    assert queue["storage_usage"]["count"] == 1


def test_work_queue_limits_items_to_five(db: None, owner: User) -> None:
    today = timezone.localdate()
    for i in range(6):
        Task.objects.create(title=f"任务{i}", due_date=today, status=Task.Status.OPEN)

    queue = build_work_queue()

    assert queue["today_due"]["count"] == 6
    assert len(queue["today_due"]["items"]) == 5


def test_work_queue_scopes_by_user(db: None, owner: User) -> None:
    today = timezone.localdate()
    other = User.objects.create_user(username="other", password="pw")
    Task.objects.create(
        title="别人的",
        due_date=today,
        status=Task.Status.OPEN,
        assignee=other,
        created_by=other,
    )
    Task.objects.create(
        title="我的",
        due_date=today,
        status=Task.Status.OPEN,
        assignee=owner,
        created_by=owner,
    )

    queue = build_work_queue(user=owner)

    assert queue["today_due"]["count"] == 1
    assert queue["today_due"]["items"][0]["title"] == "我的"


def test_backup_status_placeholder_when_unset(db: None, owner: User) -> None:
    queue = build_work_queue()

    assert queue["backup_status"]["count"] == 0
    assert queue["backup_status"]["badge"] == "备份功能待配置"


def test_build_stats_counts(db: None, owner: User) -> None:
    today = timezone.localdate()
    now = timezone.now()

    for i in range(3):
        Customer.objects.create(name=f"客户{i}", age_note="30岁")
    # 上月客户（不计本月新增）
    old = Customer.objects.create(name="老客户", age_note="30岁")
    Customer.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=40))
    # 本月沟通：同一客户两条，去重计数
    c1 = Customer.objects.create(name="本月沟通", age_note="30岁")
    CommunicationRecord.objects.create(customer=c1, channel="phone", content="你好")
    CommunicationRecord.objects.create(customer=c1, channel="wechat", content="再聊")
    # 理赔：1 处理中 + 1 已结案（终态不计）
    ClaimCase.objects.create(name="处理中", customer=c1, status="insurer_reviewing")
    ClaimCase.objects.create(name="已结案", customer=c1, status="closed")
    # 保单待核实
    Policy.objects.create(
        insurer="平安",
        name="待核实",
        policy_no="P-002",
        policyholder=c1,
        effective_date=today,
        status=Policy.Status.STATUS_PENDING,
    )
    # 逾期任务
    Task.objects.create(title="逾期", due_date=today - timedelta(days=1), status=Task.Status.OPEN)

    stats = build_stats()

    assert stats["total_customers"] == 5
    assert stats["new_customers_month"] == 4
    assert stats["contacted_month"] == 1
    assert stats["claims_active"] == 1
    assert stats["policies_pending"] == 1
    assert stats["overdue_tasks"] == 1
