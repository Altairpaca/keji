"""policies 缴费提醒服务（T7.3，规格 §11 / §14）。

到期计算模型：
- 缴费批次锚定在 effective_date，按 payment_frequency 每固定月数一期；
- ``last_paid_batch`` 记录最后已缴批次日期（None 表示从未登记缴款）；
- ``next_premium_due`` 给出 ≥ as_of 的第一个批次日（生成式计算）；
- ``premium_due_date`` 给出当前应缴批次（可能已过期，用于列表 / 宽限判断）。

宽限期：应缴批次已过、未标记已缴（status 非 paid_up）且在宽限天数内。
"""

import calendar
import re
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.policies.models import Policy
from apps.policies.services import change_status
from apps.tasks.models import Task
from apps.tasks.services import create_task, find_task_by_source

# 缴费频率 → 每期月数。
FREQ_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "semi_annual": 6,
    "annual": 12,
}

# 参与提醒的保单状态。
ACTIVE_STATUSES = (Policy.Status.ACTIVE, Policy.Status.PAYING)


def _add_months(d: date, months: int) -> date:
    """日期推进 months 个月；月末日期钳制到目标月最后一天。"""
    total = d.year * 12 + (d.month - 1) + months
    year, zero_index = divmod(total, 12)
    month = zero_index + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse_term_months(value: str) -> int | None:
    """解析期限字符串（"20年" / "36月"）为月数；无法解析返回 None（视为不限）。"""
    match = re.fullmatch(r"\s*(\d+)\s*(年|月|个月)\s*", value.strip())
    if match is None:
        return None
    number = int(match.group(1))
    return number * 12 if match.group(2) == "年" else number


def _term_end(policy: Policy) -> date | None:
    """缴费期限截止日（effective_date + 可解析期限）；缺失或不可解析 → None。"""
    if policy.effective_date is None:
        return None
    for raw in (policy.payment_term, policy.coverage_term):
        months = _parse_term_months(raw or "")
        if months is not None:
            return _add_months(policy.effective_date, months)
    return None


def _base_batch(policy: Policy) -> date | None:
    """缴费基准日：最后已缴批次，未缴过则取生效日。"""
    last_paid: date | None = policy.last_paid_batch
    if last_paid is not None:
        return last_paid
    effective: date | None = policy.effective_date
    return effective


def next_premium_due(policy: Policy, *, as_of: date | None = None) -> date | None:
    """下一个批次日：从基准日按月推进到 ≥ as_of；越过缴费期限 → None。

    趸缴 / 无生效日期 → None。推进始终从基准日按整期数计算，以保留原基准日
    （月末日期如 1/31 先钳到 2/29，再回到 3/31，不因中间钳制而漂移）。
    """
    as_of = as_of or timezone.localdate()
    months = FREQ_MONTHS.get(policy.payment_frequency)
    base = _base_batch(policy)
    if base is None or months is None:
        return None
    period = 0
    while _add_months(base, period * months) < as_of:
        period += 1
    cursor = _add_months(base, period * months)
    term_end = _term_end(policy)
    if term_end is not None and cursor >= term_end:
        return None
    return cursor


def premium_due_date(policy: Policy) -> date | None:
    """当前应缴批次：最后已缴批次之后的第一期；从未缴过则为生效日首期。

    可能早于今天（逾期未缴），列表据此标记宽限 / 红色。落在缴费期限终点
    （含）之后的批次视为不存在。
    """
    months = FREQ_MONTHS.get(policy.payment_frequency)
    base = _base_batch(policy)
    if base is None or months is None:
        return None
    due = _add_months(base, months) if policy.last_paid_batch is not None else base
    term_end = _term_end(policy)
    if term_end is not None and due >= term_end:
        return None
    return due


def is_in_grace_period(policy: Policy, *, grace_days: int = 30) -> bool:
    """是否处于缴费宽限期：应缴批次已过、未标记已缴且在宽限天数内。"""
    if policy.status == Policy.Status.PAID_UP:
        return False
    due = premium_due_date(policy)
    if due is None:
        return False
    today: date = timezone.localdate()
    if due >= today:
        return False
    return (today - due).days <= grace_days


def mark_premium_paid(
    policy: Policy, *, paid_date: date | None = None, changed_by: User | None = None
) -> Policy:
    """登记一期保费已缴。

    - 趸缴：状态流转到 paid_up（写状态历史）；
    - 分期：把当前应缴批次（paid_date 显式给定时取之）记入 last_paid_batch，
      下一期顺延一期。
    """
    if policy.payment_frequency == Policy.PaymentFrequency.ONCE:
        with transaction.atomic():
            change_status(
                policy=policy,
                new_status=str(Policy.Status.PAID_UP),
                changed_by=changed_by,
                note="趸缴保费已缴",
            )
        return policy

    due = premium_due_date(policy)
    if due is None:
        raise ValueError("该保单无待缴批次（缺少生效日期或缴费频率不可分期）")
    with transaction.atomic():
        policy.last_paid_batch = paid_date if paid_date is not None else due
        policy.save(update_fields=["last_paid_batch", "updated_at"])
    return policy


def sync_premium_reminder_tasks(policy: Policy, *, created_by: User | None = None) -> Task | None:
    """为保单当前应缴批次同步一条「确认缴费」待办；未完成同批次已存在则跳过。"""
    due = premium_due_date(policy)
    if due is None:
        return None
    source_key = f"policy_due:{policy.pk}:{due.isoformat()}"
    if find_task_by_source(source_key) is not None:
        return None
    return create_task(
        task_type=str(Task.TaskType.CONFIRM_PAYMENT),
        title=f"确认缴费：{policy.insurer} {policy.name}",
        customer=policy.policyholder,
        due_date=due,
        content=f"保单号 {policy.policy_no} 每期保费 {policy.premium_amount}",
        source_key=source_key,
        created_by=created_by,
    )


def sync_all_reminder_tasks(user: User | None = None) -> int:
    """为全部 active / paying 保单同步缴费提醒待办，返回新建数量。"""
    count = 0
    for policy in Policy.objects.filter(status__in=ACTIVE_STATUSES):
        if sync_premium_reminder_tasks(policy, created_by=user) is not None:
            count += 1
    return count


def due_premiums(*, window_days: int = 30, user: User | None = None) -> QuerySet:
    """应缴日在 [today, today+window_days] 的保单（首页「近期需要缴费」队列）。

    队列取「下一个 ≥ today 的批次日」（即 next_premium_due）；逾期未缴的保单
    不进入此窗口（由宽限 / 逾期视图承接）。
    """
    today = timezone.localdate()
    end = today + timedelta(days=window_days)
    queryset = Policy.objects.filter(status__in=ACTIVE_STATUSES).exclude(
        payment_frequency=Policy.PaymentFrequency.ONCE
    )
    if user is not None:
        queryset = queryset.filter(Q(owner=user))
    pks = [
        policy.pk
        for policy in queryset
        if (due := next_premium_due(policy)) is not None and today <= due <= end
    ]
    return Policy.objects.filter(pk__in=pks)
