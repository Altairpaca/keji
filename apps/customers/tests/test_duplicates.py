"""T4.4 客户重复检测与合并服务测试（RED 先行，规格 §16）。

覆盖：
- find_phone_duplicates：空手机不参与、同号 2+ 成组、软删不计、可传 queryset
- find_name_duplicates：去空格小写归一化后同名成组、软删不计
- merge_customers：tags 并集、关系 from/to 双向改指、owner/created_by 空则继承、
  notes 合并带来源注释、source 软删 target 保留、参数校验、事务回滚
"""

from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerRelation, Tag
from apps.customers.services.duplicates import (
    find_name_duplicates,
    find_phone_duplicates,
    merge_customers,
)
from apps.customers.services.relations import create_relation

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


def make_customer(
    user: User,
    *,
    name: str = "林小明",
    phone: str = "",
    **kwargs: object,
) -> Customer:
    """直建客户（模型层不校验 birth/age），kwargs 覆盖默认 owner/created_by。"""
    data: dict[str, object] = {"name": name, "owner": user, "created_by": user, "phone": phone}
    data.update(kwargs)
    customer: Customer = Customer.objects.create(**data)
    return customer


def make_tag(name: str) -> Tag:
    tag: Tag = Tag.objects.create(name=name)
    return tag


# ---------------------------------------------------------------------------
# find_phone_duplicates
# ---------------------------------------------------------------------------


def test_phone_duplicates_groups_same_phone(user: User) -> None:
    make_customer(user, name="甲", phone="13800138000")
    make_customer(user, name="乙", phone="13800138000")
    make_customer(user, name="丙", phone="13900139000")

    groups = find_phone_duplicates()

    assert len(groups) == 1
    rep, dupes = groups[0]
    assert rep.name == "甲"
    assert [c.name for c in dupes] == ["乙"]


def test_phone_duplicates_blank_phone_not_included(user: User) -> None:
    make_customer(user, name="甲", phone="")
    make_customer(user, name="乙", phone="   ")

    assert find_phone_duplicates() == []


def test_phone_duplicates_single_phone_no_group(user: User) -> None:
    make_customer(user, name="甲", phone="13800138000")
    make_customer(user, name="乙", phone="13900139000")

    assert find_phone_duplicates() == []


def test_phone_duplicates_excludes_soft_deleted(user: User) -> None:
    make_customer(user, name="甲", phone="13800138000")
    gone = make_customer(user, name="乙", phone="13800138000")
    gone.soft_delete()

    assert find_phone_duplicates() == []


def test_phone_duplicates_group_after_soft_delete_still_reported(user: User) -> None:
    keep = make_customer(user, name="甲", phone="13800138000")
    gone = make_customer(user, name="乙", phone="13800138000")
    other = make_customer(user, name="丙", phone="13800138000")
    gone.soft_delete()

    groups = find_phone_duplicates()

    assert len(groups) == 1
    rep, dupes = groups[0]
    assert rep == keep
    assert dupes == [other]


def test_phone_duplicates_accepts_queryset(user: User) -> None:
    make_customer(user, name="甲", phone="13800138000")
    make_customer(user, name="乙", phone="13800138000")

    groups = find_phone_duplicates(queryset=Customer.objects.filter(phone="13900139000"))

    assert groups == []


# ---------------------------------------------------------------------------
# find_name_duplicates
# ---------------------------------------------------------------------------


def test_name_duplicates_group_same_name_ignoring_whitespace(user: User) -> None:
    make_customer(user, name="林小明")
    make_customer(user, name="林 小明")
    make_customer(user, name="王小红")

    groups = find_name_duplicates()

    assert len(groups) == 1
    members = {c.name for c in groups[0][0:1] + tuple(groups[0][1])}
    assert members == {"林小明", "林 小明"}


def test_name_duplicates_group_case_insensitive(user: User) -> None:
    make_customer(user, name="Li Ming")
    make_customer(user, name="li ming")

    groups = find_name_duplicates()

    assert len(groups) == 1


def test_name_duplicates_unique_names_no_group(user: User) -> None:
    make_customer(user, name="林小明")
    make_customer(user, name="王小红")

    assert find_name_duplicates() == []


def test_name_duplicates_excludes_soft_deleted(user: User) -> None:
    make_customer(user, name="林小明")
    gone = make_customer(user, name="林小明")
    gone.soft_delete()

    assert find_name_duplicates() == []


# ---------------------------------------------------------------------------
# merge_customers — 标签并集
# ---------------------------------------------------------------------------


def test_merge_union_of_tags(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁")
    source = make_customer(user, name="乙", age_note="约35岁")
    vip, regular, key = make_tag("vip"), make_tag("老客户"), make_tag("重点")
    target.tags.add(vip, regular)
    source.tags.add(regular, key)

    result = merge_customers(target, source)

    assert result.pk == target.pk
    assert {t.name for t in result.tags.all()} == {"vip", "老客户", "重点"}


# ---------------------------------------------------------------------------
# merge_customers — 关系改指（from/to 双向）
# ---------------------------------------------------------------------------


def test_merge_repoints_relations_from_and_to(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁")
    source = make_customer(user, name="乙", age_note="约35岁")
    other = make_customer(user, name="丙", age_note="约40岁")
    outgoing = create_relation(from_customer=source, to_customer=other, relation_type="spouse")
    incoming = create_relation(from_customer=other, to_customer=source, relation_type="spouse")

    merge_customers(target, source)

    outgoing.refresh_from_db()
    incoming.refresh_from_db()
    assert outgoing.from_customer == target
    assert outgoing.to_customer == other
    assert incoming.from_customer == other
    assert incoming.to_customer == target
    assert CustomerRelation.objects.filter(from_customer=source).count() == 0
    assert CustomerRelation.objects.filter(to_customer=source).count() == 0


# ---------------------------------------------------------------------------
# merge_customers — 归属继承
# ---------------------------------------------------------------------------


def test_merge_inherits_owner_and_created_by_when_target_empty(user: User) -> None:
    boss = User(username="boss")
    boss.save()
    source = make_customer(user, name="乙", age_note="约35岁", owner=boss, created_by=boss)
    target = make_customer(user, name="甲", age_note="约30岁", owner=None, created_by=None)

    result = merge_customers(target, source)

    assert result.owner == boss
    assert result.created_by == boss


def test_merge_keeps_existing_owner(user: User) -> None:
    boss = User(username="boss")
    boss.save()
    target = make_customer(user, name="甲", age_note="约30岁", owner=user)
    source = make_customer(user, name="乙", age_note="约35岁", owner=boss)

    merge_customers(target, source)
    target.refresh_from_db()

    assert target.owner == user


# ---------------------------------------------------------------------------
# merge_customers — 备注合并
# ---------------------------------------------------------------------------


def test_merge_notes_concatenated_with_source_marker(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁", notes="目标备注")
    source = make_customer(user, name="乙", age_note="约35岁", notes="源客户备注")

    result = merge_customers(target, source)

    assert "目标备注" in result.notes
    assert "源客户备注" in result.notes
    assert "乙" in result.notes  # 分隔注释注明来源


def test_merge_notes_source_empty_keeps_target(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁", notes="目标备注")
    source = make_customer(user, name="乙", age_note="约35岁", notes="")

    merge_customers(target, source)

    assert target.notes == "目标备注"


# ---------------------------------------------------------------------------
# merge_customers — 软删 source / 保留 target
# ---------------------------------------------------------------------------


def test_merge_soft_deletes_source_keeps_target(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁")
    source = make_customer(user, name="乙", age_note="约35岁")

    result = merge_customers(target, source)

    assert result.pk == target.pk
    assert result.is_deleted is False
    assert Customer.objects.filter(pk=target.pk).count() == 1
    assert Customer.objects.filter(pk=source.pk).count() == 0
    deleted = Customer.all_objects.get(pk=source.pk)
    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None


# ---------------------------------------------------------------------------
# merge_customers — 参数校验
# ---------------------------------------------------------------------------


def test_merge_same_customer_raises(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁")

    with pytest.raises(ValueError):
        merge_customers(target, target)


def test_merge_deleted_source_raises(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁")
    source = make_customer(user, name="乙", age_note="约35岁")
    source.soft_delete()

    with pytest.raises(ValueError):
        merge_customers(target, source)


def test_merge_deleted_target_raises(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁")
    source = make_customer(user, name="乙", age_note="约35岁")
    target.soft_delete()

    with pytest.raises(ValueError):
        merge_customers(target, source)


# ---------------------------------------------------------------------------
# merge_customers — 事务回滚
# ---------------------------------------------------------------------------


def test_merge_rolls_back_when_relation_repoint_fails(user: User) -> None:
    target = make_customer(user, name="甲", age_note="约30岁", notes="目标备注")
    source = make_customer(user, name="乙", age_note="约35岁")
    source.tags.add(make_tag("vip"))

    with (
        pytest.raises(RuntimeError),
        patch(
            "apps.customers.services.duplicates._repoint_relations",
            side_effect=RuntimeError("boom"),
        ),
    ):
        merge_customers(target, source)

    # 关系改指中途异常 → 事务整体回滚：source 未被软删，tags 未转移
    assert Customer.objects.filter(pk=source.pk).count() == 1
    assert Customer.all_objects.get(pk=source.pk).is_deleted is False
    target.refresh_from_db()
    assert target.tags.count() == 0
    assert target.notes == "目标备注"
