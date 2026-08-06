"""dashboard 首页工作队列与统计服务（T9.2，规格 §14）。

build_work_queue 聚合 12 个工作队列，每队列返回展示标题、查看全部链接、
总数与至多 DISPLAY_LIMIT 条的条目（title/link/urgency）；build_stats 汇总
六项统计指标。队列与统计的归属收窄：user 给定且非超管时，任务按
assignee/created_by、其余按 owner（文件按 uploaded_by）过滤。
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet, Sum
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord
from apps.claims.models import ClaimCase
from apps.core.services.settings import get_setting
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.policies.models import Policy
from apps.policies.services import due_premiums
from apps.tasks.models import Task
from apps.tasks.services import overdue_tasks

#: 队列卡片展示条数上限。
DISPLAY_LIMIT = 5

#: 理赔终结状态（不进入「理赔处理中」统计）。
CLAIM_TERMINAL_STATUSES = ("closed", "approved", "partial_paid", "rejected")

#: 等待保险公司回复的理赔状态。
WAITING_INSURER_STATUSES = ("insurer_reviewing", "requested_supplement", "submitted")

#: 客户「等待回复」状态名。
WAITING_REPLY_NAME = "等待回复"

#: 长期未联系阈值（天）。
LONG_NO_CONTACT_DAYS = 30

#: 备份状态设置键（T11 写入）。
LAST_BACKUP_SETTING = "last_backup_at"


def _queue(
    title: str,
    link: str,
    qs: QuerySet,
    *,
    title_of: Callable[[Any], str],
    link_of: Callable[[Any], str],
    urgency: str,
) -> dict[str, Any]:
    """把一条查询结果组装成队列条目：总数 + 前 DISPLAY_LIMIT 条。"""
    total = qs.count()
    items = [_item(title_of(obj), link_of(obj), urgency) for obj in qs[:DISPLAY_LIMIT]]
    return {"title": title, "link": link, "count": total, "items": items}


def _item(title: str, link: str, urgency: str) -> dict[str, str]:
    return {"title": title, "link": link, "urgency": urgency}


def _tasks_for(qs: QuerySet, user: User | None) -> QuerySet:
    """任务队列按用户收窄：本人负责或本人创建。"""
    if user is None or user.is_superuser:
        return qs
    return qs.filter(Q(assignee=user) | Q(created_by=user))


def _scoped(qs: QuerySet, user: User | None, *, field: str = "owner") -> QuerySet:
    """非超管用户按归属字段收窄队列。"""
    if user is None or user.is_superuser:
        return qs
    return qs.filter(**{field: user})


def build_work_queue(user: User | None = None) -> dict[str, dict[str, Any]]:
    """聚合首页 12 个工作队列（规格 §14），键为稳定队列名。"""
    today = timezone.localdate()

    tasks = Task.objects.exclude(status__in=("done", "cancelled"))
    open_tasks = _tasks_for(tasks, user)
    today_due = _queue(
        "今天必须处理",
        reverse("tasks:task_list") + "?status=open",
        open_tasks.filter(due_date=today).order_by("due_date", "created_at"),
        title_of=lambda t: t.title,
        link_of=lambda t: reverse("tasks:task_edit", args=[t.pk]),
        urgency="high",
    )
    overdue = _queue(
        "逾期任务",
        reverse("tasks:task_list") + "?status=overdue",
        overdue_tasks(user).order_by("due_date"),
        title_of=lambda t: t.title,
        link_of=lambda t: reverse("tasks:task_edit", args=[t.pk]),
        urgency="high",
    )

    customers = _scoped(Customer.objects.all(), user)
    waiting_customer = _queue(
        "等待客户回复",
        reverse("customers:customer_list"),
        customers.filter(status__name=WAITING_REPLY_NAME).order_by("-updated_at"),
        title_of=lambda c: c.name,
        link_of=lambda c: reverse("customers:customer_detail", args=[c.pk]),
        urgency="medium",
    )
    this_week_meetings = _queue(
        "本周约见",
        reverse("customers:customer_list"),
        customers.filter(
            next_followup_date__gte=today,
            next_followup_date__lte=today + timedelta(days=7),
        ).order_by("next_followup_date"),
        title_of=lambda c: c.name,
        link_of=lambda c: reverse("customers:customer_detail", args=[c.pk]),
        urgency="medium",
    )
    no_contact_cutoff = today - timedelta(days=LONG_NO_CONTACT_DAYS)
    long_no_contact = _queue(
        "长期未联系",
        reverse("customers:customer_list"),
        customers.filter(last_contact_date__lt=no_contact_cutoff).order_by("last_contact_date"),
        title_of=lambda c: c.name,
        link_of=lambda c: reverse("customers:customer_detail", args=[c.pk]),
        urgency="low",
    )

    claims = _scoped(ClaimCase.objects.all(), user)
    waiting_insurer = _queue(
        "等待保险公司",
        reverse("claims:claim_list"),
        claims.filter(status__in=WAITING_INSURER_STATUSES).order_by("-created_at"),
        title_of=lambda c: c.name,
        link_of=lambda c: reverse("claims:claim_detail", args=[c.pk]),
        urgency="medium",
    )
    claims_missing_materials = _queue(
        "理赔缺少资料",
        reverse("claims:claim_list"),
        claims.filter(materials__status__in=("not_submitted", "needs_supplement"))
        .distinct()
        .order_by("-created_at"),
        title_of=lambda c: c.name,
        link_of=lambda c: reverse("claims:claim_detail", args=[c.pk]),
        urgency="medium",
    )

    premiums_due = _queue(
        "近期需要缴费",
        reverse("policies:policy_list"),
        due_premiums(window_days=30, user=user).order_by("effective_date"),
        title_of=lambda p: f"{p.insurer} {p.name}",
        link_of=lambda p: reverse("policies:policy_detail", args=[p.pk]),
        urgency="medium",
    )

    documents = _scoped(Document.objects.all(), user, field="uploaded_by")
    uncategorized_documents = _queue(
        "未分类文件",
        reverse("documents:document_list"),
        documents.filter(albums__isnull=True).order_by("-created_at"),
        title_of=lambda d: d.original_name,
        link_of=lambda d: reverse("documents:document_detail", args=[d.pk]),
        urgency="low",
    )
    recent_uploads = _queue(
        "最近上传",
        reverse("documents:document_list"),
        documents.filter(created_at__gte=timezone.now() - timedelta(days=7)).order_by(
            "-created_at"
        ),
        title_of=lambda d: d.original_name,
        link_of=lambda d: reverse("documents:document_detail", args=[d.pk]),
        urgency="low",
    )

    backup_status = _backup_status_queue()
    storage_usage = _storage_usage_queue()

    return {
        "today_due": today_due,
        "overdue": overdue,
        "waiting_customer": waiting_customer,
        "waiting_insurer": waiting_insurer,
        "claims_missing_materials": claims_missing_materials,
        "this_week_meetings": this_week_meetings,
        "long_no_contact": long_no_contact,
        "premiums_due": premiums_due,
        "uncategorized_documents": uncategorized_documents,
        "recent_uploads": recent_uploads,
        "backup_status": backup_status,
        "storage_usage": storage_usage,
    }


def _backup_status_queue() -> dict[str, Any]:
    """备份状态队列：未配置时显示占位 badge（T11 接入后展示真实时间）。"""
    last_backup = get_setting(LAST_BACKUP_SETTING, None)
    if last_backup:
        items = [_item(f"上次备份：{last_backup}", reverse("dashboard:home"), "low")]
        badge = ""
    else:
        items = []
        badge = "备份功能待配置"
    return {
        "title": "备份状态",
        "link": reverse("dashboard:home"),
        "count": 1 if last_backup else 0,
        "items": items,
        "badge": badge,
    }


def _storage_usage_queue() -> dict[str, Any]:
    """存储空间队列：Document.size 聚合（MB）。"""
    total_bytes = Document.objects.aggregate(total=Sum("size"))["total"] or 0
    mb = total_bytes / (1024 * 1024)
    return {
        "title": "存储空间",
        "link": reverse("documents:document_list"),
        "count": 1,
        "items": [_item(f"共占用 {mb:.1f} MB", reverse("documents:document_list"), "low")],
    }


def build_stats() -> dict[str, int]:
    """首页统计卡（规格 §14）：六项指标。"""
    now = timezone.localtime()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return {
        "total_customers": Customer.objects.count(),
        "new_customers_month": Customer.objects.filter(created_at__gte=month_start).count(),
        "contacted_month": CommunicationRecord.objects.filter(occurred_at__gte=month_start)
        .values("customer")
        .distinct()
        .count(),
        "claims_active": ClaimCase.objects.exclude(status__in=CLAIM_TERMINAL_STATUSES).count(),
        "policies_pending": Policy.objects.filter(status=Policy.Status.STATUS_PENDING).count(),
        "overdue_tasks": overdue_tasks().count(),
    }
