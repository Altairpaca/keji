"""T8.1 claims 服务层测试（RED 先行，规格 §12）。

覆盖：状态迁移表与规格一致；全部合法/非法迁移对；closed 终态与 closed_at
联动；材料 6 态迁移与 checked 核对人写入/清空；create/update/软删；
missing_materials；instantiate_template 幂等与跳过已有；completion_ratio。
"""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.claims.models import ClaimCase, ClaimMaterialTemplate
from apps.claims.services import (
    CLAIM_STATUS_TRANSITIONS,
    MATERIAL_STATUS_TRANSITIONS,
    change_claim_status,
    change_material_status,
    create_claim,
    create_material,
    instantiate_template,
    material_completion_ratio,
    missing_materials,
    restore_claim,
    soft_delete_claim,
    update_claim,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.policies.services import create_policy

pytestmark = pytest.mark.django_db

ALL_CLAIM_STATUSES: list[str] = sorted(CLAIM_STATUS_TRANSITIONS)
ALL_MATERIAL_STATUSES: list[str] = sorted(MATERIAL_STATUS_TRANSITIONS)

# 全部合法迁移对：直接由迁移表推导，保证表与测试不脱节。
LEGAL_CLAIM_PAIRS: list[tuple[str, str]] = [
    (from_status, to_status)
    for from_status, targets in CLAIM_STATUS_TRANSITIONS.items()
    for to_status in sorted(targets)
]
# 每个状态至少一个非法迁移：取不在合法目标集里的首个状态。
ILLEGAL_CLAIM_PAIRS: list[tuple[str, str]] = [
    (
        from_status,
        next(to for to in ALL_CLAIM_STATUSES if to not in CLAIM_STATUS_TRANSITIONS[from_status]),
    )
    for from_status in ALL_CLAIM_STATUSES
]
LEGAL_MATERIAL_PAIRS: list[tuple[str, str]] = [
    (from_status, to_status)
    for from_status, targets in MATERIAL_STATUS_TRANSITIONS.items()
    for to_status in sorted(targets)
]
ILLEGAL_MATERIAL_PAIRS: list[tuple[str, str]] = [
    (
        from_status,
        next(
            to for to in ALL_MATERIAL_STATUSES if to not in MATERIAL_STATUS_TRANSITIONS[from_status]
        ),
    )
    for from_status in ALL_MATERIAL_STATUSES
]


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


@pytest.fixture
def claim(user: User, customer: Customer) -> ClaimCase:
    return create_claim(name="林小明-医疗理赔", customer=customer, owner=user)


def _templates(*names: str, claim_type: str = "medical") -> None:
    """创建测试模板：先清空该类型种子模板，避免与实例化断言冲突。"""
    ClaimMaterialTemplate.objects.filter(claim_type=claim_type).delete()
    for sort_order, name in enumerate(names):
        ClaimMaterialTemplate.objects.create(
            name=name, claim_type=claim_type, sort_order=sort_order
        )


# ---------------------------------------------------------------------------
# 状态迁移表与规格一致
# ---------------------------------------------------------------------------


def test_claim_status_transitions_table_matches_spec() -> None:
    expected: dict[str, set[str]] = {
        "consultation": {"waiting_materials", "collecting_materials", "reported", "closed"},
        "waiting_materials": {
            "collecting_materials",
            "materials_incomplete",
            "submitted",
            "closed",
        },
        "collecting_materials": {
            "waiting_materials",
            "materials_pending_review",
            "materials_incomplete",
            "submitted",
            "closed",
        },
        "materials_pending_review": {"collecting_materials", "submitted", "requested_supplement"},
        "materials_incomplete": {"collecting_materials", "waiting_materials", "closed"},
        "reported": {"submitted", "insurer_reviewing", "closed"},
        "submitted": {
            "insurer_reviewing",
            "requested_supplement",
            "approved",
            "partial_paid",
            "rejected",
            "closed",
        },
        "insurer_reviewing": {
            "submitted",
            "requested_supplement",
            "approved",
            "partial_paid",
            "rejected",
            "closed",
        },
        "requested_supplement": {"collecting_materials", "submitted", "closed"},
        "approved": {"partial_paid", "closed"},
        "partial_paid": {"approved", "closed"},
        "rejected": {"disputing", "closed"},
        "disputing": {"submitted", "rejected", "closed"},
        "closed": set(),
    }

    assert expected == CLAIM_STATUS_TRANSITIONS


def test_material_status_transitions_table_matches_spec() -> None:
    expected: dict[str, set[str]] = {
        "not_submitted": {"submitted", "not_applicable"},
        "submitted": {"pending_review", "needs_supplement", "checked", "not_applicable"},
        "pending_review": {"checked", "needs_supplement", "submitted", "not_applicable"},
        "checked": {"needs_supplement"},
        "needs_supplement": {"submitted", "not_applicable"},
        "not_applicable": {"submitted"},
    }

    assert expected == MATERIAL_STATUS_TRANSITIONS


# ---------------------------------------------------------------------------
# create_claim
# ---------------------------------------------------------------------------


def test_create_claim_requires_name(user: User, customer: Customer) -> None:
    with pytest.raises(ValueError, match="名称不能为空"):
        create_claim(name="   ", customer=customer)


def test_create_claim_requires_customer(user: User) -> None:
    with pytest.raises(ValueError, match="客户不能为空"):
        create_claim(name="林小明-医疗理赔", customer=None)


def test_create_claim_defaults(claim: ClaimCase) -> None:
    assert claim.status == "consultation"
    assert claim.claim_type == "other"
    assert claim.policy is None
    assert claim.closed_at is None
    assert claim.materials.count() == 0


def test_create_claim_with_full_fields(user: User, customer: Customer) -> None:
    policy = create_policy(
        policy_no="POL-CLAIM-2",
        insurer="平安人寿",
        name="金佑人生",
        policyholder=customer,
        owner=user,
    )

    c = create_claim(
        name="意外理赔",
        customer=customer,
        policy=policy,
        claim_type="accident",
        incident_date=date(2026, 5, 1),
        report_date=date(2026, 5, 3),
        owner=user,
        description="骑车摔伤",
    )

    assert c.policy == policy
    assert c.claim_type == "accident"
    assert c.incident_date == date(2026, 5, 1)
    assert c.report_date == date(2026, 5, 3)
    assert c.owner == user
    assert c.description == "骑车摔伤"


# ---------------------------------------------------------------------------
# change_claim_status — 全部合法/非法迁移对
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", LEGAL_CLAIM_PAIRS)
def test_change_claim_status_accepts_every_legal_transition(
    user: User, customer: Customer, from_status: str, to_status: str
) -> None:
    c = create_claim(name=f"合法-{from_status}-{to_status}", customer=customer, owner=user)
    c.status = from_status
    c.save(update_fields=["status"])

    result = change_claim_status(claim=c, new_status=to_status, changed_by=user)

    assert result.status == to_status


@pytest.mark.parametrize("from_status,to_status", ILLEGAL_CLAIM_PAIRS)
def test_change_claim_status_rejects_every_illegal_transition(
    user: User, customer: Customer, from_status: str, to_status: str
) -> None:
    c = create_claim(name=f"非法-{from_status}-{to_status}", customer=customer, owner=user)
    c.status = from_status
    c.save(update_fields=["status"])

    with pytest.raises(ValueError, match="非法状态迁移"):
        change_claim_status(claim=c, new_status=to_status, changed_by=user)

    c.refresh_from_db()
    assert c.status == from_status


def test_closed_is_terminal(user: User, customer: Customer) -> None:
    c = create_claim(name="结案案", customer=customer, owner=user)
    c.status = "closed"
    c.save(update_fields=["status"])

    for target in ALL_CLAIM_STATUSES:
        with pytest.raises(ValueError, match="非法状态迁移"):
            change_claim_status(claim=c, new_status=target)

    assert c.status == "closed"


def test_change_claim_status_to_closed_sets_closed_at(user: User, customer: Customer) -> None:
    c = create_claim(name="结案案", customer=customer, owner=user)

    change_claim_status(claim=c, new_status="closed", changed_by=user)

    assert c.status == "closed"
    assert c.closed_at is not None


def test_change_claim_status_non_closed_keeps_closed_at_none(
    user: User, customer: Customer
) -> None:
    c = create_claim(name="进行中", customer=customer, owner=user)

    change_claim_status(claim=c, new_status="waiting_materials", changed_by=user)

    assert c.closed_at is None


# ---------------------------------------------------------------------------
# update_claim / soft_delete / restore
# ---------------------------------------------------------------------------


def test_update_claim_partial_update(claim: ClaimCase) -> None:
    updated = update_claim(claim, description="补充说明", estimated_amount=Decimal("1200.00"))

    assert updated.description == "补充说明"
    assert updated.estimated_amount == Decimal("1200.00")
    assert updated.name == "林小明-医疗理赔"


def test_update_claim_unknown_field_raises(claim: ClaimCase) -> None:
    with pytest.raises(ValueError, match="未知字段"):
        update_claim(claim, nonexistent_field="x")


def test_soft_delete_and_restore_claim(user: User, customer: Customer) -> None:
    c = create_claim(name="软删案", customer=customer, owner=user)

    soft_delete_claim(c)

    assert ClaimCase.objects.filter(pk=c.pk).count() == 0
    assert ClaimCase.all_objects.get(pk=c.pk).is_deleted is True

    restore_claim(c)

    assert ClaimCase.objects.get(pk=c.pk).is_deleted is False


# ---------------------------------------------------------------------------
# create_material
# ---------------------------------------------------------------------------


def test_create_material_defaults(claim: ClaimCase) -> None:
    material = create_material(claim=claim, name="诊断证明")

    assert material.claim == claim
    assert material.is_required is True
    assert material.status == "not_submitted"


def test_create_material_duplicate_name_raises(claim: ClaimCase) -> None:
    create_material(claim=claim, name="诊断证明")

    with pytest.raises(ValueError, match="材料已存在"):
        create_material(claim=claim, name="诊断证明")


def test_create_material_allows_same_name_after_soft_delete(claim: ClaimCase) -> None:
    first = create_material(claim=claim, name="诊断证明")
    first.soft_delete()

    second = create_material(claim=claim, name="诊断证明")

    assert second.pk != first.pk


# ---------------------------------------------------------------------------
# change_material_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", LEGAL_MATERIAL_PAIRS)
def test_change_material_status_accepts_every_legal_transition(
    claim: ClaimCase, user: User, from_status: str, to_status: str
) -> None:
    material = create_material(claim=claim, name=f"材料-{from_status}-{to_status}")
    material.status = from_status
    material.save(update_fields=["status"])

    result = change_material_status(material=material, new_status=to_status, changed_by=user)

    assert result.status == to_status


@pytest.mark.parametrize("from_status,to_status", ILLEGAL_MATERIAL_PAIRS)
def test_change_material_status_rejects_every_illegal_transition(
    claim: ClaimCase, user: User, from_status: str, to_status: str
) -> None:
    material = create_material(claim=claim, name=f"材料非法-{from_status}-{to_status}")
    material.status = from_status
    material.save(update_fields=["status"])

    with pytest.raises(ValueError, match="非法状态迁移"):
        change_material_status(material=material, new_status=to_status, changed_by=user)

    material.refresh_from_db()
    assert material.status == from_status


def test_change_material_status_to_checked_records_checker(claim: ClaimCase, user: User) -> None:
    material = create_material(claim=claim, name="诊断证明")
    change_material_status(material=material, new_status="submitted", changed_by=user)
    change_material_status(material=material, new_status="pending_review", changed_by=user)

    change_material_status(material=material, new_status="checked", changed_by=user)

    assert material.checked_by == user
    assert material.checked_at is not None


def test_change_material_status_leaving_checked_clears_checker(
    claim: ClaimCase, user: User
) -> None:
    material = create_material(claim=claim, name="诊断证明")
    material.status = "checked"
    material.checked_by = user
    material.checked_at = timezone.now()
    material.save()

    change_material_status(material=material, new_status="needs_supplement", changed_by=user)

    assert material.checked_by is None
    assert material.checked_at is None


# ---------------------------------------------------------------------------
# missing_materials / material_completion_ratio
# ---------------------------------------------------------------------------


def test_missing_materials_returns_not_submitted_and_needs_supplement(
    claim: ClaimCase,
) -> None:
    submitted = create_material(claim=claim, name="理赔申请书")
    submitted.status = "submitted"
    submitted.save(update_fields=["status"])
    create_material(claim=claim, name="诊断证明")  # not_submitted
    needs = create_material(claim=claim, name="费用清单")
    needs.status = "needs_supplement"
    needs.save(update_fields=["status"])
    checked = create_material(claim=claim, name="身份证件")
    checked.status = "checked"
    checked.save(update_fields=["status"])

    missing = set(missing_materials(claim).values_list("name", flat=True))

    assert missing == {"诊断证明", "费用清单"}


def test_completion_ratio_zero_materials(claim: ClaimCase) -> None:
    assert material_completion_ratio(claim) == 0.0


def test_completion_ratio_counts_checked_and_not_applicable(claim: ClaimCase) -> None:
    checked = create_material(claim=claim, name="身份证件")
    checked.status = "checked"
    checked.save(update_fields=["status"])
    na = create_material(claim=claim, name="不适用项")
    na.status = "not_applicable"
    na.save(update_fields=["status"])
    create_material(claim=claim, name="未提交项")

    assert material_completion_ratio(claim) == 2 / 3


def test_completion_ratio_all_done_is_one(claim: ClaimCase) -> None:
    for name in ["材料A", "材料B"]:
        m = create_material(claim=claim, name=name)
        m.status = "checked"
        m.save(update_fields=["status"])

    assert material_completion_ratio(claim) == 1.0


# ---------------------------------------------------------------------------
# instantiate_template
# ---------------------------------------------------------------------------


def test_instantiate_template_creates_materials_from_claim_type(claim: ClaimCase) -> None:
    _templates("测试-理赔申请书", "测试-诊断证明")
    claim.claim_type = "medical"
    claim.save(update_fields=["claim_type"])

    created = instantiate_template(claim=claim)

    assert len(created) == 2
    assert sorted(claim.materials.values_list("name", flat=True)) == [
        "测试-理赔申请书",
        "测试-诊断证明",
    ]
    assert claim.materials.get(name="测试-理赔申请书").is_required is True


def test_instantiate_template_is_idempotent(claim: ClaimCase) -> None:
    _templates("测试-理赔申请书", "测试-诊断证明")
    claim.claim_type = "medical"
    claim.save(update_fields=["claim_type"])

    first = instantiate_template(claim=claim)
    second = instantiate_template(claim=claim)

    assert len(first) == 2
    assert len(second) == 0
    assert claim.materials.count() == 2


def test_instantiate_template_skips_existing_material(claim: ClaimCase) -> None:
    create_material(claim=claim, name="测试-诊断证明")
    _templates("测试-理赔申请书", "测试-诊断证明")
    claim.claim_type = "medical"
    claim.save(update_fields=["claim_type"])

    instantiate_template(claim=claim)

    assert claim.materials.count() == 2


def test_instantiate_template_with_explicit_template(claim: ClaimCase) -> None:
    template = ClaimMaterialTemplate.objects.create(
        name="测试-事故证明", claim_type="accident", sort_order=0
    )

    created = instantiate_template(claim=claim, template=template)

    assert len(created) == 1
    assert claim.materials.get().name == "测试-事故证明"
