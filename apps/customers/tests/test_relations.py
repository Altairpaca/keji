"""T4.3 客户关系 模型 + 服务层测试（RED 先行，规格 §7 / REQ-REL-001）。

覆盖：
- 模型：字段默认值、__str__、软删除行为、唯一约束
- 服务 create_relation：from≠to 校验、custom 必须有 label、重复活跃关系拒绝、
  软删后可重建、非法输入无残留
- get_relations：双向可见、排除自己循环、排除已删除
- related_customers：去重、排除已删除客户
- delete_relation / restore_relation 软删语义
"""

import pytest
from django.db import IntegrityError

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerRelation
from apps.customers.services.relations import (
    create_relation,
    delete_relation,
    get_relations,
    related_customers,
    restore_relation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    c: Customer = Customer.objects.create(name="林小明", owner=user, created_by=user)
    return c


def make_customer(name: str, user: User) -> Customer:
    customer: Customer = Customer.objects.create(name=name, owner=user, created_by=user)
    return customer


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------


def test_relation_type_choices_six(customer: Customer, user: User) -> None:
    assert set(CustomerRelation.RelationType.values) == {
        "spouse",
        "parent_child",
        "family",
        "referrer",
        "same_household",
        "custom",
    }


def test_str_format(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)

    relation = create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    assert str(relation) == "林小明 → 王小红 (配偶)"


def test_soft_delete_hides_from_default_manager(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    relation = create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    delete_relation(relation)

    assert CustomerRelation.objects.filter(pk=relation.pk).count() == 0
    assert CustomerRelation.all_objects.get(pk=relation.pk).is_deleted is True
    assert CustomerRelation.all_objects.get(pk=relation.pk).deleted_at is not None


def test_restore_relation_recovers(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    relation = create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    delete_relation(relation)

    restored = restore_relation(relation)

    assert restored.is_deleted is False
    assert restored.deleted_at is None
    assert CustomerRelation.objects.filter(pk=relation.pk).count() == 1


def test_unique_constraint_active_relations(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    # 绕过服务层直接写库：同 from/to/type 未删除时唯一约束触发。
    with pytest.raises(IntegrityError):
        CustomerRelation.objects.create(
            from_customer=customer, to_customer=other, relation_type="spouse"
        )


def test_unique_constraint_allows_different_type(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    # 不同类型不冲突。
    relation = create_relation(from_customer=customer, to_customer=other, relation_type="referrer")

    assert relation.pk is not None


def test_unique_constraint_does_not_cover_deleted(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    first = create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    delete_relation(first)

    # 软删后允许重建同 from/to/type。
    second = create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    assert second.pk != first.pk
    assert CustomerRelation.all_objects.filter(pk=first.pk).count() == 1
    assert CustomerRelation.objects.count() == 1


# ---------------------------------------------------------------------------
# create_relation 校验
# ---------------------------------------------------------------------------


def test_create_relation_happy_path(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)

    relation = create_relation(
        from_customer=customer,
        to_customer=other,
        relation_type="referrer",
        note="介绍过李总",
    )

    assert relation.from_customer == customer
    assert relation.to_customer == other
    assert relation.relation_type == "referrer"
    assert relation.note == "介绍过李总"
    assert relation.custom_label == ""


def test_create_relation_rejects_self_loop(customer: Customer, user: User) -> None:
    with pytest.raises(ValueError):
        create_relation(from_customer=customer, to_customer=customer, relation_type="spouse")


def test_create_relation_self_loop_leaves_no_residue(customer: Customer, user: User) -> None:
    before = CustomerRelation.objects.count()

    with pytest.raises(ValueError):
        create_relation(from_customer=customer, to_customer=customer, relation_type="spouse")

    assert CustomerRelation.objects.count() == before


def test_create_relation_custom_requires_label(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)

    with pytest.raises(ValueError):
        create_relation(from_customer=customer, to_customer=other, relation_type="custom")

    with pytest.raises(ValueError):
        create_relation(
            from_customer=customer,
            to_customer=other,
            relation_type="custom",
            custom_label="   ",
        )


def test_create_relation_custom_strips_label(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)

    relation = create_relation(
        from_customer=customer,
        to_customer=other,
        relation_type="custom",
        custom_label=" 大学同学 ",
    )

    assert relation.custom_label == "大学同学"


def test_create_relation_non_custom_accepts_blank_label(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)

    relation = create_relation(from_customer=customer, to_customer=other, relation_type="family")

    assert relation.custom_label == ""


def test_create_relation_rejects_unknown_type(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)

    with pytest.raises(ValueError):
        create_relation(from_customer=customer, to_customer=other, relation_type="cousin")


def test_create_relation_rejects_duplicate_active(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    with pytest.raises(ValueError):
        create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    assert CustomerRelation.objects.count() == 1


def test_create_relation_duplicate_leaves_no_residue(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    before = CustomerRelation.objects.count()

    with pytest.raises(ValueError):
        create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    assert CustomerRelation.objects.count() == before


# ---------------------------------------------------------------------------
# get_relations 双向可见
# ---------------------------------------------------------------------------


def test_get_relations_returns_both_directions(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    from_customer_view = get_relations(customer)
    to_customer_view = get_relations(other)

    assert from_customer_view.count() == 1
    assert to_customer_view.count() == 1
    assert list(from_customer_view) == list(to_customer_view)


def test_get_relations_no_auto_reverse_record(customer: Customer, user: User) -> None:
    """单向存储：不自动创建反向记录，反向靠查询。"""
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")

    assert CustomerRelation.objects.count() == 1


def test_get_relations_excludes_self_loop(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    # 直接写库造一条自循环（服务层禁止，但 DB 允许时查询要兜底）。
    CustomerRelation.objects.create(
        from_customer=customer, to_customer=customer, relation_type="family"
    )

    relations = get_relations(customer)

    assert relations.count() == 1
    assert relations[0].to_customer == other


def test_get_relations_excludes_deleted(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    kept = create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    gone = create_relation(from_customer=other, to_customer=customer, relation_type="referrer")
    delete_relation(gone)

    assert set(get_relations(customer).values_list("pk", flat=True)) == {kept.pk}


# ---------------------------------------------------------------------------
# related_customers 去重
# ---------------------------------------------------------------------------


def test_related_customers_dedupes(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    create_relation(from_customer=customer, to_customer=other, relation_type="referrer")

    related = related_customers(customer)

    assert list(related.values_list("name", flat=True)) == ["王小红"]


def test_related_customers_both_directions(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    third = make_customer("李大同", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    create_relation(from_customer=third, to_customer=customer, relation_type="referrer")

    related = related_customers(customer)

    assert set(related.values_list("name", flat=True)) == {"王小红", "李大同"}


def test_related_customers_excludes_deleted_customer(customer: Customer, user: User) -> None:
    other = make_customer("王小红", user)
    create_relation(from_customer=customer, to_customer=other, relation_type="spouse")
    other.soft_delete()

    assert related_customers(customer).count() == 0
