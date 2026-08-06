"""T7.1 policies 服务层测试（RED 先行，规格 §4.5 / REQ-POL-001）。

覆盖：create_policy（保单号必填/唯一、无初始历史）；change_status（全部合法迁移
对成功写历史、全部非法迁移对抛 ValueError 且无历史残留、pending 可转任意、终态
受限）；update_policy；soft_delete/restore；get_history 倒序。
"""

import pytest

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.policies.models import Policy, PolicyStatusHistory
from apps.policies.services import (
    change_status,
    create_policy,
    get_history,
    restore_policy,
    soft_delete_policy,
    update_policy,
)
from apps.policies.services.policies import STATUS_TRANSITIONS

pytestmark = pytest.mark.django_db

ALL_STATUSES = [value for value, _label in Policy.Status.choices]

# 全部合法迁移对：直接由迁移表推导，保证表与测试不脱节。
LEGAL_PAIRS = [
    (from_status, to_status)
    for from_status, targets in STATUS_TRANSITIONS.items()
    for to_status in sorted(targets)
]
# 全部非法迁移对：非目标集组合（含自迁移），穷举。
ILLEGAL_PAIRS = [
    (from_status, to_status)
    for from_status in ALL_STATUSES
    for to_status in ALL_STATUSES
    if to_status not in STATUS_TRANSITIONS.get(from_status, set())
]


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


def _base_kwargs(customer: Customer, user: User) -> dict[str, object]:
    return {"insurer": "平安人寿", "name": "金佑人生", "policyholder": customer, "owner": user}


# ---------------------------------------------------------------------------
# STATUS_TRANSITIONS 迁移表
# ---------------------------------------------------------------------------


def test_status_transitions_table_matches_spec() -> None:
    expected: dict[str, set[str]] = {
        "active": {
            "paying",
            "paid_up",
            "lapsed",
            "reinstating",
            "surrendered",
            "terminated",
            "matured",
            "claim_closed",
            "status_pending",
        },
        "paying": {"active", "paid_up", "lapsed", "surrendered", "terminated", "status_pending"},
        "paid_up": {"active", "status_pending"},
        "lapsed": {"reinstating", "terminated", "status_pending"},
        "reinstating": {"active", "lapsed", "status_pending"},
        "surrendered": {"status_pending"},
        "terminated": set(),
        "matured": {"status_pending"},
        "claim_closed": {"active", "status_pending"},
        "status_pending": {
            "active",
            "paying",
            "paid_up",
            "lapsed",
            "reinstating",
            "surrendered",
            "terminated",
            "matured",
            "claim_closed",
        },
    }

    assert expected == STATUS_TRANSITIONS


# ---------------------------------------------------------------------------
# create_policy
# ---------------------------------------------------------------------------


def test_create_policy_requires_policy_no(user: User, customer: Customer) -> None:
    with pytest.raises(ValueError, match="保单号不能为空"):
        create_policy(**_base_kwargs(customer, user))


def test_create_policy_rejects_blank_policy_no(user: User, customer: Customer) -> None:
    with pytest.raises(ValueError, match="保单号不能为空"):
        create_policy(policy_no="   ", **_base_kwargs(customer, user))


def test_create_policy_duplicate_policy_no_raises_value_error(
    user: User, customer: Customer
) -> None:
    create_policy(policy_no="POL-DUP", **_base_kwargs(customer, user))

    with pytest.raises(ValueError, match="保单号已存在"):
        create_policy(policy_no="POL-DUP", **_base_kwargs(customer, user))


def test_create_policy_no_initial_history_and_default_status(
    user: User, customer: Customer
) -> None:
    policy = create_policy(policy_no="POL-001", **_base_kwargs(customer, user))

    assert policy.status == "active"
    assert policy.insurer == "平安人寿"
    assert policy.name == "金佑人生"
    assert PolicyStatusHistory.objects.filter(policy=policy).count() == 0


def test_create_policy_accepts_explicit_status(user: User, customer: Customer) -> None:
    policy = create_policy(
        policy_no="POL-002", status="status_pending", **_base_kwargs(customer, user)
    )

    assert policy.status == "status_pending"
    assert PolicyStatusHistory.objects.filter(policy=policy).count() == 0


# ---------------------------------------------------------------------------
# change_status — 全部合法迁移对
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", LEGAL_PAIRS)
def test_change_status_accepts_every_legal_transition(
    user: User, customer: Customer, from_status: str, to_status: str
) -> None:
    policy = create_policy(
        policy_no=f"POL-L-{from_status}-{to_status}",
        status=from_status,
        **_base_kwargs(customer, user),
    )

    result = change_status(policy=policy, new_status=to_status, changed_by=user, note="合法迁移")

    assert result.status == to_status
    history = list(PolicyStatusHistory.objects.filter(policy=policy))
    assert len(history) == 1
    assert history[0].from_status == from_status
    assert history[0].to_status == to_status
    assert history[0].changed_by == user
    assert history[0].note == "合法迁移"


# ---------------------------------------------------------------------------
# change_status — 全部非法迁移对（事务回滚：无历史残留、状态不变）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", ILLEGAL_PAIRS)
def test_change_status_rejects_every_illegal_transition_without_residue(
    user: User, customer: Customer, from_status: str, to_status: str
) -> None:
    policy = create_policy(
        policy_no=f"POL-I-{from_status}-{to_status}",
        status=from_status,
        **_base_kwargs(customer, user),
    )
    before = PolicyStatusHistory.objects.count()

    with pytest.raises(ValueError, match="非法状态迁移"):
        change_status(policy=policy, new_status=to_status, changed_by=user)

    assert PolicyStatusHistory.objects.count() == before
    policy.refresh_from_db()
    assert policy.status == from_status


def test_change_status_same_status_rejected(user: User, customer: Customer) -> None:
    policy = create_policy(policy_no="POL-SELF", **_base_kwargs(customer, user))

    with pytest.raises(ValueError, match="非法状态迁移"):
        change_status(policy=policy, new_status="active")

    assert policy.status == "active"


def test_status_pending_can_transition_to_every_other_status(
    user: User, customer: Customer
) -> None:
    policy = create_policy(
        policy_no="POL-PEND", status="status_pending", **_base_kwargs(customer, user)
    )

    for target in [s for s in ALL_STATUSES if s != "status_pending"]:
        change_status(policy=policy, new_status=target, changed_by=user)
        assert policy.status == target
        assert PolicyStatusHistory.objects.filter(policy=policy).count() == 1
        PolicyStatusHistory.objects.filter(policy=policy).delete()
        policy.status = "status_pending"
        policy.save(update_fields=["status"])


def test_terminal_terminated_has_no_legal_transitions(user: User, customer: Customer) -> None:
    policy = create_policy(
        policy_no="POL-TERM", status="terminated", **_base_kwargs(customer, user)
    )

    for target in ALL_STATUSES:
        with pytest.raises(ValueError):
            change_status(policy=policy, new_status=target)

    assert policy.status == "terminated"
    assert PolicyStatusHistory.objects.count() == 0


def test_terminal_surrendered_only_to_status_pending(user: User, customer: Customer) -> None:
    policy = create_policy(
        policy_no="POL-SURR", status="surrendered", **_base_kwargs(customer, user)
    )

    with pytest.raises(ValueError):
        change_status(policy=policy, new_status="active")
    assert PolicyStatusHistory.objects.count() == 0

    change_status(policy=policy, new_status="status_pending", changed_by=user)
    assert policy.status == "status_pending"
    assert PolicyStatusHistory.objects.filter(policy=policy).count() == 1


# ---------------------------------------------------------------------------
# change_status — 多次迁移 / get_history 倒序
# ---------------------------------------------------------------------------


def test_change_status_multiple_transitions_write_history_newest_first(
    user: User, customer: Customer
) -> None:
    policy = create_policy(policy_no="POL-MULTI", **_base_kwargs(customer, user))

    change_status(policy=policy, new_status="paying", changed_by=user)
    change_status(policy=policy, new_status="active", changed_by=user)

    assert policy.status == "active"
    history = list(get_history(policy))
    assert len(history) == 2
    assert [(h.from_status, h.to_status) for h in history] == [
        ("paying", "active"),
        ("active", "paying"),
    ]


# ---------------------------------------------------------------------------
# update_policy / soft_delete / restore
# ---------------------------------------------------------------------------


def test_update_policy_partial_update(user: User, customer: Customer) -> None:
    policy = create_policy(policy_no="POL-UP", **_base_kwargs(customer, user))
    created_at = policy.created_at

    updated = update_policy(policy, main_coverage="重疾保障", premium_amount=800)

    assert updated.main_coverage == "重疾保障"
    assert updated.premium_amount == 800
    assert updated.name == "金佑人生"
    assert updated.created_at == created_at
    assert Policy.objects.get(pk=policy.pk).main_coverage == "重疾保障"


def test_update_policy_unknown_field_raises(user: User, customer: Customer) -> None:
    policy = create_policy(policy_no="POL-UP2", **_base_kwargs(customer, user))

    with pytest.raises(ValueError, match="未知字段"):
        update_policy(policy, nonexistent_field="x")


def test_soft_delete_and_restore_via_service(user: User, customer: Customer) -> None:
    policy = create_policy(policy_no="POL-SD", **_base_kwargs(customer, user))

    soft_delete_policy(policy)

    assert Policy.objects.filter(pk=policy.pk).count() == 0
    assert Policy.all_objects.get(pk=policy.pk).is_deleted is True
    assert policy.deleted_at is not None

    restore_policy(policy)

    assert Policy.objects.get(pk=policy.pk).is_deleted is False
    assert policy.deleted_at is None
