"""T4.1 customers 服务层测试（RED 先行，规格 §6）。

覆盖：create_customer（默认状态、显式状态、字段校验、非法输入无残留）、
update_customer（部分更新、未知字段拒绝）、soft_delete/restore_customer、
assign_tags（get_or_create + 替换 + 空名跳过）、find_duplicates。
"""

from datetime import date

import pytest

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerStatus, Tag
from apps.customers.services import (
    assign_tags,
    create_customer,
    find_duplicates,
    restore_customer,
    soft_delete_customer,
    update_customer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


# ---------------------------------------------------------------------------
# create_customer
# ---------------------------------------------------------------------------


def test_create_customer_defaults_to_min_sort_order_active_status(user: User) -> None:
    customer = create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")

    assert customer.status is not None
    assert customer.status.name == "待首次联系"


def test_create_customer_default_skips_inactive_status(user: User) -> None:
    CustomerStatus.objects.all().update(is_active=False)
    low_inactive = CustomerStatus.objects.create(name="低序停用", sort_order=1, is_active=False)
    high_active = CustomerStatus.objects.create(name="高序启用", sort_order=5, is_active=True)

    customer = create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")

    assert customer.status == high_active
    assert customer.status != low_inactive


def test_create_customer_accepts_explicit_status(user: User) -> None:
    status = CustomerStatus.objects.get(name="已结案")

    customer = create_customer(
        name="林小明", owner=user, created_by=user, age_note="约35岁", status=status
    )

    assert customer.status == status


def test_create_customer_accepts_all_fields(user: User) -> None:
    status = CustomerStatus.objects.get(name="保单服务中")

    customer = create_customer(
        name="林小明",
        owner=user,
        created_by=user,
        gender="男",
        birth_date=date(1990, 1, 1),
        phone="13800138000",
        wechat_nickname="xiaoming",
        region="台北市",
        occupation="工程师",
        marital_family_note="已婚，育有一子",
        source="朋友介绍",
        previous_agent="王姐",
        first_contact_date=date(2026, 1, 1),
        last_contact_date=date(2026, 7, 1),
        next_followup_date=date(2026, 8, 1),
        status=status,
        priority="高",
        communication_preference="微信",
        notes="偏好晚间联系",
    )

    assert customer.name == "林小明"
    assert customer.owner == user
    assert customer.created_by == user
    assert customer.gender == "男"
    assert customer.birth_date == date(1990, 1, 1)
    assert customer.phone == "13800138000"
    assert customer.wechat_nickname == "xiaoming"
    assert customer.region == "台北市"
    assert customer.occupation == "工程师"
    assert customer.marital_family_note == "已婚，育有一子"
    assert customer.source == "朋友介绍"
    assert customer.previous_agent == "王姐"
    assert customer.first_contact_date == date(2026, 1, 1)
    assert customer.last_contact_date == date(2026, 7, 1)
    assert customer.next_followup_date == date(2026, 8, 1)
    assert customer.status == status
    assert customer.priority == "高"
    assert customer.communication_preference == "微信"
    assert customer.notes == "偏好晚间联系"
    assert customer.created_at is not None
    assert customer.updated_at is not None


def test_create_customer_requires_non_empty_name(user: User) -> None:
    with pytest.raises(ValueError):
        create_customer(name="   ", owner=user, created_by=user, age_note="约35岁")


def test_create_customer_requires_birth_date_or_age_note(user: User) -> None:
    with pytest.raises(ValueError):
        create_customer(name="林小明", owner=user, created_by=user)


def test_create_customer_invalid_input_leaves_no_residue(user: User) -> None:
    before = Customer.objects.count()

    with pytest.raises(ValueError):
        create_customer(name="", owner=user, created_by=user, age_note="约35岁")

    assert Customer.objects.count() == before


def test_create_customer_missing_birth_age_leaves_no_residue(user: User) -> None:
    before = Customer.objects.count()

    with pytest.raises(ValueError):
        create_customer(name="林小明", owner=user, created_by=user)

    assert Customer.objects.count() == before


# ---------------------------------------------------------------------------
# update_customer
# ---------------------------------------------------------------------------


def test_update_customer_partial_update(user: User) -> None:
    customer = create_customer(
        name="林小明",
        owner=user,
        created_by=user,
        age_note="约35岁",
        next_followup_date=None,
    )
    created_at = customer.created_at

    updated = update_customer(customer, next_followup_date=date(2026, 8, 15))

    assert updated.next_followup_date == date(2026, 8, 15)
    assert updated.name == "林小明"  # 未改动字段保留
    assert updated.age_note == "约35岁"
    assert updated.created_at == created_at
    assert updated.updated_at > created_at
    fresh = Customer.objects.get(pk=customer.pk)
    assert fresh.next_followup_date == date(2026, 8, 15)


def test_update_customer_unknown_field_raises(user: User) -> None:
    customer = create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")

    with pytest.raises(ValueError):
        update_customer(customer, nonexistent_field="x")


# ---------------------------------------------------------------------------
# soft_delete / restore
# ---------------------------------------------------------------------------


def test_soft_delete_customer_hides_and_restore_customer_recovers(user: User) -> None:
    customer = create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")

    soft_delete_customer(customer)

    deleted = Customer.all_objects.get(pk=customer.pk)
    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None
    assert Customer.objects.filter(pk=customer.pk).count() == 0

    restore_customer(customer)

    restored = Customer.objects.get(pk=customer.pk)
    assert restored.is_deleted is False
    assert restored.deleted_at is None
    assert Customer.objects.count() == 1


# ---------------------------------------------------------------------------
# assign_tags
# ---------------------------------------------------------------------------


def test_assign_tags_get_or_create_and_replace(user: User) -> None:
    customer = create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")

    assign_tags(customer, ["vip", "老客户"])
    assert {t.name for t in customer.tags.all()} == {"vip", "老客户"}

    assign_tags(customer, ["vip", "重点客户"])
    assert {t.name for t in customer.tags.all()} == {"vip", "重点客户"}
    assert Tag.objects.count() == 3  # get_or_create 不重复创建


def test_assign_tags_skips_blank_and_trims(user: User) -> None:
    customer = create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")

    assign_tags(customer, [" vip ", "", "   ", "长期客户"])

    assert {t.name for t in customer.tags.all()} == {"vip", "长期客户"}


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------


def test_find_duplicates_matches_same_phone(user: User) -> None:
    create_customer(name="甲", owner=user, created_by=user, phone="13800138000", age_note="约30岁")
    create_customer(name="乙", owner=user, created_by=user, phone="13800138000", age_note="约40岁")
    create_customer(name="丙", owner=user, created_by=user, phone="13900139000", age_note="约50岁")

    dupes = find_duplicates("13800138000")

    assert set(dupes.values_list("name", flat=True)) == {"甲", "乙"}


def test_find_duplicates_excludes_soft_deleted(user: User) -> None:
    first = create_customer(
        name="甲", owner=user, created_by=user, phone="13800138000", age_note="约30岁"
    )
    second = create_customer(
        name="乙", owner=user, created_by=user, phone="13800138000", age_note="约40岁"
    )
    soft_delete_customer(second)

    dupes = find_duplicates("13800138000")

    assert list(dupes.values_list("name", flat=True)) == ["甲"]
    assert first.is_deleted is False


def test_find_duplicates_blank_phone_returns_empty(user: User) -> None:
    create_customer(name="甲", owner=user, created_by=user, phone="", age_note="约30岁")

    assert find_duplicates("").count() == 0
    assert find_duplicates("   ").count() == 0
