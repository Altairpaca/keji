"""T7.3 policies 缴费提醒测试（RED 先行，规格 §11 / §14 / REQ-POL-001）。

覆盖：
- next_premium_due：按频率从基准日月推进、once / 无生效日 → None、超过缴费期限 → None
- premium_due_date：当前应缴批次（未缴过取生效日首期、已缴过推一期）、越期 → None
- is_in_grace_period：宽限窗口内为真、超期 / 未到期 / paid_up / 趸缴为假
- mark_premium_paid：趸缴 → paid_up 写历史；分期 → last_paid_batch 推进且下次 due 推后；
  无待缴批次 → ValueError
- sync：创建 confirm_payment 待办、幂等（重复不重复建）、完成后可再建、标记已缴后目标批次顺延
- sync_all_reminder_tasks：仅 active/paying 参与，返回新建数
- due_premiums：应缴日在 [today, today+window] 窗口过滤、owner 过滤
- 视图：提醒列表权限矩阵与渲染、mark_paid / sync 权限与流程
"""

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.policies.models import Policy, PolicyStatusHistory
from apps.policies.services import create_policy
from apps.policies.services.reminders import (
    FREQ_MONTHS,
    due_premiums,
    is_in_grace_period,
    mark_premium_paid,
    next_premium_due,
    premium_due_date,
    sync_all_reminder_tasks,
    sync_premium_reminder_tasks,
)
from apps.tasks.models import Task
from apps.tasks.services import complete_task

pytestmark = pytest.mark.django_db

REMINDERS_URL = "/policies/reminders/"


def _mark_url(pk: uuid.UUID) -> str:
    return f"/policies/{pk}/reminders/mark-paid/"


def _sync_url(pk: uuid.UUID) -> str:
    return f"/policies/{pk}/reminders/sync/"


def _freeze_today(d: date) -> Any:
    return patch("django.utils.timezone.localdate", return_value=d)


def _as_maker(user: User) -> Callable[..., Policy]:
    """以指定 user 为 owner 创建保单的工厂。"""

    def _make(policy_no: str, *, customer: Customer, **kwargs: object) -> Policy:
        return create_policy(
            insurer="平安人寿",
            name="金佑人生",
            policy_no=policy_no,
            policyholder=customer,
            owner=user,
            **kwargs,
        )

    return _make


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


@pytest.fixture
def make_policy(db: None) -> Callable[..., Policy]:
    """按需创建保单：owner 取投保客户 owner。"""

    def _make(policy_no: str, *, customer: Customer | None = None, **kwargs: object) -> Policy:
        if customer is None:
            owner = User.objects.create(username=f"owner-{uuid.uuid4().hex[:6]}")
            customer = create_customer(
                name="投保客户", owner=owner, created_by=owner, age_note="约30岁"
            )
        assert customer.owner is not None
        return create_policy(
            insurer="平安人寿",
            name="金佑人生",
            policy_no=policy_no,
            policyholder=customer,
            owner=customer.owner,
            **kwargs,
        )

    return _make


def _annual(
    make_policy: Callable[..., Policy],
    customer: Customer,
    policy_no: str,
    **kwargs: object,
) -> Policy:
    base: dict[str, object] = {
        "customer": customer,
        "effective_date": date(2024, 1, 15),
        "payment_frequency": "annual",
        "premium_amount": Decimal("8000.00"),
    }
    base.update(kwargs)
    return make_policy(policy_no, **base)


def _body(response: Any) -> str:
    return str(response.content.decode())


# ---------------------------------------------------------------------------
# next_premium_due
# ---------------------------------------------------------------------------


def test_next_premium_due_annual_advances_from_effective_date(
    user: User, customer: Customer
) -> None:
    policy = _annual(_as_maker(user), customer, "POL-A1")

    assert next_premium_due(policy, as_of=date(2025, 6, 1)) == date(2026, 1, 15)


def test_next_premium_due_monthly_advances_by_one_month(user: User, customer: Customer) -> None:
    policy = _annual(
        _as_maker(user),
        customer,
        "POL-M1",
        effective_date=date(2024, 1, 31),
        payment_frequency="monthly",
    )

    assert next_premium_due(policy, as_of=date(2024, 2, 1)) == date(2024, 2, 29)
    assert next_premium_due(policy, as_of=date(2024, 3, 15)) == date(2024, 3, 31)


def test_next_premium_due_quarterly_and_semi_annual(user: User, customer: Customer) -> None:
    quarterly = _annual(
        _as_maker(user),
        customer,
        "POL-Q1",
        effective_date=date(2024, 1, 31),
        payment_frequency="quarterly",
    )
    semi = _annual(
        _as_maker(user),
        customer,
        "POL-S1",
        effective_date=date(2024, 1, 15),
        payment_frequency="semi_annual",
    )

    assert next_premium_due(quarterly, as_of=date(2024, 3, 1)) == date(2024, 4, 30)
    assert next_premium_due(semi, as_of=date(2024, 6, 1)) == date(2024, 7, 15)


def test_next_premium_due_uses_last_paid_batch_as_base(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-B1")
    policy.last_paid_batch = date(2025, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    assert next_premium_due(policy, as_of=date(2025, 6, 1)) == date(2026, 1, 15)


def test_next_premium_due_defaults_as_of_to_today(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-D1")

    with _freeze_today(date(2025, 6, 1)):
        assert next_premium_due(policy) == date(2026, 1, 15)


def test_next_premium_due_once_returns_none(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-O1", payment_frequency="once")

    assert next_premium_due(policy, as_of=date(2026, 6, 1)) is None


def test_next_premium_due_without_effective_date_returns_none(
    user: User, customer: Customer
) -> None:
    policy = _annual(_as_maker(user), customer, "POL-N1", effective_date=None)

    assert next_premium_due(policy) is None


def test_next_premium_due_beyond_payment_term_returns_none(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-T1", payment_term="1年")

    assert next_premium_due(policy, as_of=date(2026, 6, 1)) is None


# ---------------------------------------------------------------------------
# premium_due_date
# ---------------------------------------------------------------------------


def test_premium_due_date_first_batch_is_effective_date(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-PD1")

    with _freeze_today(date(2025, 6, 1)):
        assert premium_due_date(policy) == date(2024, 1, 15)


def test_premium_due_date_advances_one_period_after_last_paid(
    user: User, customer: Customer
) -> None:
    policy = _annual(_as_maker(user), customer, "POL-PD2")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2025, 6, 1)):
        assert premium_due_date(policy) == date(2025, 1, 15)


def test_premium_due_date_none_for_once_or_no_effective(user: User, customer: Customer) -> None:
    once = _annual(_as_maker(user), customer, "POL-PD3", payment_frequency="once")
    no_effective = _annual(_as_maker(user), customer, "POL-PD4", effective_date=None)

    with _freeze_today(date(2025, 6, 1)):
        assert premium_due_date(once) is None
        assert premium_due_date(no_effective) is None


def test_premium_due_date_beyond_term_returns_none(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-PD5", payment_term="1年")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2025, 6, 1)):
        assert premium_due_date(policy) is None


# ---------------------------------------------------------------------------
# is_in_grace_period
# ---------------------------------------------------------------------------


def test_is_in_grace_period_true_within_window(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-GR1")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2025, 1, 20)):
        assert is_in_grace_period(policy) is True


def test_is_in_grace_period_false_after_window(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-GR2")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2025, 3, 1)):
        assert is_in_grace_period(policy) is False


def test_is_in_grace_period_false_before_due(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-GR3")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2024, 12, 1)):
        assert is_in_grace_period(policy) is False


def test_is_in_grace_period_false_when_paid_up(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-GR4", status="paid_up")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2025, 1, 20)):
        assert is_in_grace_period(policy) is False


def test_is_in_grace_period_false_when_once(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-GR5", payment_frequency="once")

    with _freeze_today(date(2025, 1, 20)):
        assert is_in_grace_period(policy) is False


def test_freq_months_mapping() -> None:
    assert FREQ_MONTHS == {"monthly": 1, "quarterly": 3, "semi_annual": 6, "annual": 12}


# ---------------------------------------------------------------------------
# mark_premium_paid
# ---------------------------------------------------------------------------


def test_mark_premium_paid_once_sets_paid_up_with_history(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-MP0", payment_frequency="once")

    mark_premium_paid(policy, changed_by=user)

    policy.refresh_from_db()
    assert policy.status == "paid_up"
    assert (
        PolicyStatusHistory.objects.filter(
            policy=policy, to_status="paid_up", changed_by=user
        ).count()
        == 1
    )


def test_mark_premium_paid_installment_sets_last_paid_batch(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-MP1")

    with _freeze_today(date(2024, 2, 1)):
        mark_premium_paid(policy, changed_by=user)

    policy.refresh_from_db()
    assert policy.last_paid_batch == date(2024, 1, 15)
    with _freeze_today(date(2025, 2, 1)):
        assert premium_due_date(policy) == date(2025, 1, 15)


def test_mark_premium_paid_catches_up_next_unpaid_batch(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-MP2")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])

    with _freeze_today(date(2025, 1, 20)):
        mark_premium_paid(policy, changed_by=user)

    policy.refresh_from_db()
    assert policy.last_paid_batch == date(2025, 1, 15)


def test_mark_premium_paid_uses_explicit_paid_date(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-MP3")

    with _freeze_today(date(2024, 2, 1)):
        mark_premium_paid(policy, paid_date=date(2024, 1, 15))

    policy.refresh_from_db()
    assert policy.last_paid_batch == date(2024, 1, 15)


def test_mark_premium_paid_without_due_raises(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-MP4", effective_date=None)

    with pytest.raises(ValueError, match="无待缴批次"):
        mark_premium_paid(policy)


# ---------------------------------------------------------------------------
# sync_premium_reminder_tasks
# ---------------------------------------------------------------------------


def test_sync_creates_confirm_payment_task(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-SYNC1")

    with _freeze_today(date(2025, 6, 1)):
        task = sync_premium_reminder_tasks(policy, created_by=user)

    assert task is not None
    assert task.task_type == "confirm_payment"
    assert task.title == "确认缴费：平安人寿 金佑人生"
    assert task.customer == customer
    assert task.due_date == date(2024, 1, 15)
    assert task.source_key == f"policy_due:{policy.pk}:2024-01-15"
    assert "POL-SYNC1" in task.content
    assert "8000.00" in task.content
    assert task.created_by == user


def test_sync_is_idempotent(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-SYNC2")

    with _freeze_today(date(2025, 6, 1)):
        first = sync_premium_reminder_tasks(policy, created_by=user)
        second = sync_premium_reminder_tasks(policy, created_by=user)

    assert first is not None
    assert second is None
    assert Task.objects.filter(source_key=first.source_key).count() == 1


def test_sync_after_complete_allows_recreate(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-SYNC3")

    with _freeze_today(date(2025, 6, 1)):
        task = sync_premium_reminder_tasks(policy, created_by=user)
    assert task is not None
    complete_task(task)

    with _freeze_today(date(2025, 6, 1)):
        new_task = sync_premium_reminder_tasks(policy, created_by=user)

    assert new_task is not None
    assert new_task.pk != task.pk


def test_sync_after_mark_paid_targets_next_batch(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-SYNC4")

    with _freeze_today(date(2024, 2, 1)):
        first = sync_premium_reminder_tasks(policy, created_by=user)
        mark_premium_paid(policy, changed_by=user)
    with _freeze_today(date(2025, 2, 1)):
        second = sync_premium_reminder_tasks(policy, created_by=user)

    assert first is not None
    assert second is not None
    assert first.source_key == f"policy_due:{policy.pk}:2024-01-15"
    assert second.source_key == f"policy_due:{policy.pk}:2025-01-15"


def test_sync_returns_none_when_no_due(user: User, customer: Customer) -> None:
    policy = _annual(_as_maker(user), customer, "POL-SYNC5", payment_frequency="once")

    assert sync_premium_reminder_tasks(policy) is None


# ---------------------------------------------------------------------------
# sync_all_reminder_tasks
# ---------------------------------------------------------------------------


def test_sync_all_only_considers_active_and_paying(user: User, customer: Customer) -> None:
    _annual(_as_maker(user), customer, "POL-ALL1")
    _annual(_as_maker(user), customer, "POL-ALL2", payment_frequency="monthly")
    _annual(_as_maker(user), customer, "POL-ALL3", payment_frequency="once")
    _annual(_as_maker(user), customer, "POL-ALL4", status="lapsed")

    with _freeze_today(date(2025, 6, 1)):
        count = sync_all_reminder_tasks(user=user)

    assert count == 2


# ---------------------------------------------------------------------------
# due_premiums
# ---------------------------------------------------------------------------


def test_due_premiums_filters_by_window(user: User, customer: Customer) -> None:
    # A：下一应缴 2026-06-15，落在 [2026-06-01, 2026-07-01] 窗口内
    _annual(_as_maker(user), customer, "POL-DU1", effective_date=date(2024, 6, 15))
    # B：下一应缴 2026-01-15，窗口外
    _annual(_as_maker(user), customer, "POL-DU2")
    # C：趸缴，永远排除
    _annual(
        _as_maker(user),
        customer,
        "POL-DU3",
        effective_date=date(2024, 6, 15),
        payment_frequency="once",
    )

    with _freeze_today(date(2026, 6, 1)):
        qs = due_premiums(window_days=30)

    assert set(qs.values_list("policy_no", flat=True)) == {"POL-DU1"}


def test_due_premiums_window_edge_inclusive(user: User, customer: Customer) -> None:
    _annual(_as_maker(user), customer, "POL-DU4", effective_date=date(2024, 6, 1))

    with _freeze_today(date(2026, 6, 1)):
        assert due_premiums(window_days=30).filter(policy_no="POL-DU4").exists()


def test_due_premiums_filters_by_owner(user: User, customer: Customer) -> None:
    _annual(_as_maker(user), customer, "POL-DU5", effective_date=date(2024, 6, 15))
    other_owner = User.objects.create(username="other-owner")
    other_customer = create_customer(
        name="其他客户", owner=other_owner, created_by=other_owner, age_note="约30岁"
    )
    _annual(_as_maker(other_owner), other_customer, "POL-DU6", effective_date=date(2024, 6, 15))

    with _freeze_today(date(2026, 6, 1)):
        qs = due_premiums(window_days=30, user=user)

    assert set(qs.values_list("policy_no", flat=True)) == {"POL-DU5"}


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


@pytest.fixture
def viewer(db: None) -> User:
    u = User(username="viewer", can_view_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def manager(db: None) -> User:
    u = User(
        username="manager",
        can_view_customers=True,
        can_manage_customers=True,
        can_delete_customers=True,
    )
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def plain(db: None) -> User:
    u = User(username="plain")
    u.set_password("pw")
    u.save()
    return u


def test_reminder_list_anonymous_redirects_to_login(client: Any) -> None:
    response = client.get(REMINDERS_URL)

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_reminder_list_plain_user_forbidden(client: Any, plain: User) -> None:
    client.force_login(plain)

    assert client.get(REMINDERS_URL).status_code == 403


def test_reminder_list_renders_due_rows(
    client: Any, manager: User, make_policy: Callable[..., Policy]
) -> None:
    make_policy("POL-RL1", effective_date=date(2026, 6, 15), payment_frequency="annual")
    client.force_login(manager)

    with _freeze_today(date(2026, 6, 1)):
        response = client.get(REMINDERS_URL)

    assert response.status_code == 200
    body = _body(response)
    assert "POL-RL1" in body
    assert "2026-06-15" in body
    assert "标记已缴" in body
    assert "同步待办" in body


def test_reminder_list_hides_actions_for_viewer(
    client: Any, viewer: User, make_policy: Callable[..., Policy]
) -> None:
    make_policy("POL-RL3", effective_date=date(2026, 6, 15), payment_frequency="annual")
    client.force_login(viewer)

    with _freeze_today(date(2026, 6, 1)):
        response = client.get(REMINDERS_URL)

    assert response.status_code == 200
    body = _body(response)
    assert "POL-RL3" in body
    assert "标记已缴" not in body
    assert "同步待办" not in body


def test_reminder_list_marks_overdue_red(
    client: Any, viewer: User, make_policy: Callable[..., Policy]
) -> None:
    policy = make_policy("POL-RL2", effective_date=date(2024, 1, 15), payment_frequency="annual")
    policy.last_paid_batch = date(2024, 1, 15)
    policy.save(update_fields=["last_paid_batch"])
    client.force_login(viewer)

    with _freeze_today(date(2025, 1, 20)):
        response = client.get(REMINDERS_URL)

    assert response.status_code == 200
    assert "宽限期" in _body(response)


def test_mark_paid_requires_manage_permission(
    client: Any, viewer: User, make_policy: Callable[..., Policy]
) -> None:
    policy = make_policy("POL-MPV1", effective_date=date(2024, 1, 15), payment_frequency="annual")
    client.force_login(viewer)

    response = client.post(_mark_url(policy.pk))

    assert response.status_code == 403


def test_mark_paid_flow_updates_last_paid_batch(
    client: Any, manager: User, make_policy: Callable[..., Policy]
) -> None:
    policy = make_policy("POL-MPV2", effective_date=date(2024, 1, 15), payment_frequency="annual")
    client.force_login(manager)

    with _freeze_today(date(2024, 2, 1)):
        response = client.post(_mark_url(policy.pk))

    assert response.status_code == 302
    policy.refresh_from_db()
    assert policy.last_paid_batch == date(2024, 1, 15)


def test_mark_paid_get_method_not_allowed(
    client: Any, manager: User, make_policy: Callable[..., Policy]
) -> None:
    policy = make_policy("POL-MPV3", effective_date=date(2024, 1, 15), payment_frequency="annual")
    client.force_login(manager)

    response = client.get(_mark_url(policy.pk))

    assert response.status_code == 405


def test_sync_reminder_requires_manage_permission(
    client: Any, viewer: User, make_policy: Callable[..., Policy]
) -> None:
    policy = make_policy("POL-SYV1", effective_date=date(2024, 1, 15), payment_frequency="annual")
    client.force_login(viewer)

    response = client.post(_sync_url(policy.pk))

    assert response.status_code == 403


def test_sync_reminder_flow_creates_task(
    client: Any, manager: User, make_policy: Callable[..., Policy]
) -> None:
    policy = make_policy("POL-SYV2", effective_date=date(2024, 1, 15), payment_frequency="annual")
    client.force_login(manager)

    with _freeze_today(date(2025, 6, 1)):
        response = client.post(_sync_url(policy.pk))

    assert response.status_code == 302
    assert Task.objects.filter(source_key=f"policy_due:{policy.pk}:2024-01-15").exists()


def test_sync_reminder_unknown_policy_404(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(_sync_url(uuid.uuid4()))

    assert response.status_code == 404
