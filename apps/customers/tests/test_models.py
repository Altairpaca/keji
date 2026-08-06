"""T4.1 customers 模型测试（RED 先行，规格 §6）。

覆盖：必填 name；birth_date/age_note 任意组合；status FK 关联与 SET_NULL；
tags M2M 增删；软删除（objects 隐藏 / all_objects 可见 / restore）；
CustomerStatus 迁移种子 15 个默认状态且顺序正确。
"""

from datetime import date

import pytest
from django.db import IntegrityError

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerStatus, Tag

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


# ---------------------------------------------------------------------------
# __str__ / 基本字段
# ---------------------------------------------------------------------------


def test_customer_str_returns_name(user: User) -> None:
    customer = Customer.objects.create(name="林小明", owner=user, created_by=user)

    assert str(customer) == "林小明"


def test_status_str_returns_name() -> None:
    status = CustomerStatus.objects.create(name="测试状态", sort_order=99)

    assert str(status) == "测试状态"


def test_tag_str_returns_name() -> None:
    tag = Tag.objects.create(name="vip")

    assert str(tag) == "vip"


def test_name_field_required() -> None:
    field = Customer._meta.get_field("name")

    assert field.null is False
    assert field.blank is False
    assert field.db_index is True


def test_missing_name_raises_integrity_error(user: User) -> None:
    # NULL 违反 NOT NULL 约束；空字符串 "" 由服务层 create_customer 拒绝。
    with pytest.raises(IntegrityError):
        Customer.objects.create(name=None, owner=user, created_by=user)


def test_tag_default_color_and_optional_description() -> None:
    tag = Tag.objects.create(name="vip")

    assert tag.color == "#64748b"
    assert tag.description == ""


# ---------------------------------------------------------------------------
# birth_date / age_note 任意组合（模型层不校验，服务层校验至少其一）
# ---------------------------------------------------------------------------


def test_model_allows_birth_age_any_combination(user: User) -> None:
    c1 = Customer.objects.create(name="无信息", owner=user, created_by=user)
    c2 = Customer.objects.create(
        name="仅生日", birth_date=date(1990, 1, 1), owner=user, created_by=user
    )
    c3 = Customer.objects.create(name="仅年龄说明", age_note="约35岁", owner=user, created_by=user)
    c4 = Customer.objects.create(
        name="两者都有",
        birth_date=date(1990, 1, 1),
        age_note="约35岁",
        owner=user,
        created_by=user,
    )

    assert c1.birth_date is None and c1.age_note == ""
    assert c2.birth_date == date(1990, 1, 1) and c2.age_note == ""
    assert c3.birth_date is None and c3.age_note == "约35岁"
    assert c4.birth_date == date(1990, 1, 1) and c4.age_note == "约35岁"
    assert Customer.objects.count() == 4


# ---------------------------------------------------------------------------
# status FK
# ---------------------------------------------------------------------------


def test_status_fk_set_null_on_hard_delete(user: User) -> None:
    status = CustomerStatus.objects.create(name="测试状态", sort_order=99, is_active=True)
    customer = Customer.objects.create(name="林小明", status=status, owner=user, created_by=user)

    assert customer.status == status
    status.hard_delete()
    customer.refresh_from_db()

    assert customer.status is None


def test_status_related_name_customers(user: User) -> None:
    status = CustomerStatus.objects.create(name="测试状态", sort_order=99)
    Customer.objects.create(name="林小明", status=status, owner=user, created_by=user)

    assert set(status.customers.values_list("name", flat=True)) == {"林小明"}


# ---------------------------------------------------------------------------
# tags M2M
# ---------------------------------------------------------------------------


def test_tags_m2m_add_and_remove(user: User) -> None:
    customer = Customer.objects.create(name="林小明", owner=user, created_by=user)
    tag1 = Tag.objects.create(name="vip")
    tag2 = Tag.objects.create(name="老客户")

    customer.tags.add(tag1, tag2)
    assert customer.tags.count() == 2

    customer.tags.remove(tag1)
    assert set(customer.tags.values_list("name", flat=True)) == {"老客户"}
    assert set(tag2.customers.values_list("name", flat=True)) == {"林小明"}


# ---------------------------------------------------------------------------
# 软删除（ADR-006）
# ---------------------------------------------------------------------------


def test_soft_delete_hides_from_objects_visible_in_all_objects(user: User) -> None:
    customer = Customer.objects.create(name="林小明", owner=user, created_by=user)

    customer.soft_delete()

    assert Customer.objects.filter(pk=customer.pk).count() == 0
    assert Customer.all_objects.filter(pk=customer.pk).count() == 1
    assert Customer.all_objects.get(pk=customer.pk).is_deleted is True


def test_restore_brings_back_to_default_manager(user: User) -> None:
    customer = Customer.objects.create(name="林小明", owner=user, created_by=user)
    customer.soft_delete()

    customer.restore()

    assert customer.is_deleted is False
    assert customer.deleted_at is None
    assert Customer.objects.filter(pk=customer.pk).count() == 1


# ---------------------------------------------------------------------------
# CustomerStatus 迁移种子（15 个默认状态，顺序即 sort_order）
# ---------------------------------------------------------------------------


def test_seeded_customer_statuses_count_and_order() -> None:
    expected = [
        "待首次联系",
        "电话未接",
        "已加微信",
        "已联系",
        "等待回复",
        "已预约",
        "已见面",
        "多次失约",
        "暂时无需求",
        "保单服务中",
        "理赔处理中",
        "长期维护",
        "明确拒绝",
        "暂停联系",
        "已结案",
    ]

    statuses = list(CustomerStatus.objects.order_by("sort_order", "name"))

    assert [s.name for s in statuses] == expected
    assert len(statuses) == 15
    assert all(s.is_active for s in statuses)
    assert all(s.is_system for s in statuses)
