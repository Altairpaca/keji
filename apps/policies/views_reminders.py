"""policies 缴费提醒视图（T7.3，规格 §11 / §14）。

视图保持薄：列表只做行装配，写操作全部经 services（mark_premium_paid /
sync_premium_reminder_tasks）；权限边界统一走 accounts.require_permission。
"""

import uuid

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.policies.models import Policy
from apps.policies.services.reminders import (
    is_in_grace_period,
    mark_premium_paid,
    premium_due_date,
    sync_premium_reminder_tasks,
)

# 参与缴费提醒的保单状态。
ACTIVE_STATUSES = ("active", "paying")

#: 每页条数（与 policy_list 一致的量级）。
PAGE_SIZE = 20


@require_permission("can_view_customers")
def reminder_list(request: HttpRequest) -> HttpResponse:
    """缴费提醒列表：active / paying 且存在应缴批次的保单，按应缴日排序 + 分页。"""
    today = timezone.localdate()
    policies = (
        Policy.objects.filter(status__in=ACTIVE_STATUSES)
        .select_related("policyholder")
        .order_by("effective_date")
    )
    rows = [
        {
            "policy": policy,
            "due_date": due,
            "grace": is_in_grace_period(policy),
            "overdue": due < today,
        }
        for policy in policies
        if (due := premium_due_date(policy)) is not None
    ]
    rows.sort(key=lambda row: row["due_date"])
    page_obj = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "policies/reminder_list.html", {"page_obj": page_obj, "today": today})


@require_permission("can_manage_customers")
@require_POST
def mark_paid(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """登记当前批次已缴，回提醒列表。"""
    policy = get_object_or_404(Policy, pk=pk)
    try:
        mark_premium_paid(policy, changed_by=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("policies:reminder_list")
    messages.success(request, f"保单「{policy}」已登记缴款")
    return redirect("policies:reminder_list")


@require_permission("can_manage_customers")
@require_POST
def sync_reminder(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """为保单当前应缴批次同步「确认缴费」待办。"""
    policy = get_object_or_404(Policy, pk=pk)
    task = sync_premium_reminder_tasks(policy, created_by=request.user)
    if task is None:
        messages.info(request, f"保单「{policy}」的缴费待办已存在或无可缴批次")
    else:
        messages.success(request, f"已为「{policy}」创建缴费确认待办")
    return redirect("policies:reminder_list")
