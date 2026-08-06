"""T7.1 policies 模型测试（RED 先行，规格 §4.5 / REQ-POL-001）。

覆盖：policy_no 唯一；默认状态 active；payment_frequency / premium_amount 默认值；
__str__；投保人/被保险人可同人；related_name 与 CASCADE / SET_NULL；
软删除（objects 隐藏 / all_objects 可见 / restore）；PolicyStatusHistory
append-only（不软删）；状态枚举 10 种。
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, models

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.policies.models import Policy, PolicyStatusHistory

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    customer: Customer = Customer.objects.create(name="林小明", owner=user, created_by=user)
    return customer


def _policy(customer: Customer, user: User, **overrides: object) -> Policy:
    kwargs: dict[str, object] = {
        "insurer": "平安人寿",
        "name": "金佑人生",
        "policy_no": "POL-001",
        "policyholder": customer,
        "owner": user,
    }
    kwargs.update(overrides)
    policy: Policy = Policy.objects.create(**kwargs)
    return policy


# ---------------------------------------------------------------------------
# __str__ / 字段定义
# ---------------------------------------------------------------------------


def test_policy_str_returns_insurer_and_name(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)

    assert str(policy) == "平安人寿 金佑人生"


def test_policy_no_field_unique_and_indexed() -> None:
    field = Policy._meta.get_field("policy_no")

    assert field.max_length == 100
    assert field.unique is True
    assert field.db_index is True
    assert field.blank is False


def test_policy_no_unique_enforced(user: User, customer: Customer) -> None:
    _policy(customer, user, policy_no="POL-UNIQ")

    with pytest.raises(IntegrityError):
        _policy(customer, user, policy_no="POL-UNIQ")


def test_insured_allows_null(user: User, customer: Customer) -> None:
    field = Policy._meta.get_field("insured")

    assert field.null is True
    assert field.blank is True

    policy = _policy(customer, user)

    assert policy.insured is None


def test_premium_amount_is_decimal() -> None:
    field = Policy._meta.get_field("premium_amount")

    assert isinstance(field, models.DecimalField)
    assert field.max_digits == 12
    assert field.decimal_places == 2


# ---------------------------------------------------------------------------
# 默认值 / 枚举
# ---------------------------------------------------------------------------


def test_default_status_is_active(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)

    assert policy.status == "active"


def test_status_has_ten_choices() -> None:
    choices = dict(Policy.Status.choices)

    assert len(choices) == 10
    assert set(choices) == {
        "active",
        "paying",
        "paid_up",
        "lapsed",
        "reinstating",
        "surrendered",
        "terminated",
        "matured",
        "claim_closed",
        "status_pending",
    }


def test_default_payment_frequency_is_annual(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)

    assert policy.payment_frequency == "annual"
    assert policy.premium_amount == Decimal("0")


def test_payment_frequency_five_choices() -> None:
    assert set(dict(Policy.PaymentFrequency.choices)) == {
        "monthly",
        "quarterly",
        "semi_annual",
        "annual",
        "once",
    }


# ---------------------------------------------------------------------------
# 角色关联：投保人 / 被保险人
# ---------------------------------------------------------------------------


def test_policyholder_and_insured_can_be_same_person(user: User, customer: Customer) -> None:
    policy = _policy(customer, user, insured=customer)

    assert policy.policyholder == customer
    assert policy.insured == customer


def test_policyholder_related_name_held_policies(user: User, customer: Customer) -> None:
    _policy(customer, user)

    assert set(customer.held_policies.values_list("policy_no", flat=True)) == {"POL-001"}


def test_insured_related_name_insured_policies(user: User, customer: Customer) -> None:
    other = Customer.objects.create(name="林小保", owner=user, created_by=user)
    _policy(customer, user, insured=other, policy_no="POL-002")

    assert set(other.insured_policies.values_list("policy_no", flat=True)) == {"POL-002"}
    assert customer.insured_policies.count() == 0


def test_owner_related_name_policies(user: User, customer: Customer) -> None:
    _policy(customer, user)

    assert set(user.policies.values_list("policy_no", flat=True)) == {"POL-001"}


def test_policyholder_fk_cascade() -> None:
    field = Policy._meta.get_field("policyholder")

    assert field.remote_field.on_delete == models.CASCADE


def test_insured_fk_set_null() -> None:
    field = Policy._meta.get_field("insured")

    assert field.remote_field.on_delete == models.SET_NULL
    assert field.null is True


# ---------------------------------------------------------------------------
# 软删除（ADR-006）
# ---------------------------------------------------------------------------


def test_policy_soft_delete_hides_and_all_objects_sees(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)

    policy.soft_delete()

    assert Policy.objects.filter(pk=policy.pk).count() == 0
    assert Policy.all_objects.get(pk=policy.pk).is_deleted is True


def test_policy_restore_brings_back(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)
    policy.soft_delete()

    policy.restore()

    assert Policy.objects.get(pk=policy.pk).is_deleted is False
    assert policy.deleted_at is None


# ---------------------------------------------------------------------------
# PolicyStatusHistory（append-only，不软删）
# ---------------------------------------------------------------------------


def test_status_history_is_append_only_no_soft_delete_fields() -> None:
    assert not hasattr(PolicyStatusHistory, "is_deleted")
    assert not hasattr(PolicyStatusHistory, "deleted_at")


def test_status_history_str(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)
    history = PolicyStatusHistory.objects.create(
        policy=policy, from_status="active", to_status="paying", changed_by=user, note="开始缴费"
    )

    assert str(history) == f"{policy.id}: active→paying"


def test_status_history_policy_cascade_on_hard_delete(user: User, customer: Customer) -> None:
    policy = _policy(customer, user)
    PolicyStatusHistory.objects.create(policy=policy, from_status="", to_status="active")

    policy.hard_delete()

    assert PolicyStatusHistory.objects.count() == 0
