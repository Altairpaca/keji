"""T8.1 claims 模型测试（RED 先行，规格 §12）。

覆盖：三个模型字段默认值与 __str__、相关名、软删与恢复、
模板 (claim_type, name) 唯一约束（软删豁免）、默认模板种子。
"""

import uuid

import pytest
from django.db import IntegrityError

from apps.accounts.models import User
from apps.claims.models import ClaimCase, ClaimMaterial, ClaimMaterialTemplate
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Document
from apps.policies.services import create_policy

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


@pytest.fixture
def case(user: User, customer: Customer) -> ClaimCase:
    c: ClaimCase = ClaimCase.objects.create(name="林小明-医疗理赔", customer=customer, owner=user)
    return c


@pytest.fixture
def document(db: None) -> Document:
    d: Document = Document.objects.create(
        original_name="诊断证明.pdf",
        storage_key=f"key-{uuid.uuid4().hex}",
        mime_type="application/pdf",
        size=1024,
        sha256="a" * 64,
    )
    return d


# ---------------------------------------------------------------------------
# ClaimCase
# ---------------------------------------------------------------------------


def test_claim_case_defaults_and_str(case: ClaimCase) -> None:
    assert case.status == "consultation"
    assert case.claim_type == "other"
    assert case.policy is None
    assert case.estimated_amount is None
    assert case.actual_paid_amount is None
    assert case.closed_at is None
    assert str(case) == "林小明-医疗理赔"


def test_claim_case_related_names(user: User, customer: Customer, case: ClaimCase) -> None:
    policy = create_policy(
        policy_no="POL-CLAIM-1",
        insurer="平安人寿",
        name="金佑人生",
        policyholder=customer,
        owner=user,
    )
    case.policy = policy
    case.save(update_fields=["policy"])

    assert list(customer.claims.all()) == [case]
    assert list(policy.claims.all()) == [case]
    assert list(user.claims.all()) == [case]


def test_claim_case_soft_delete_and_restore(case: ClaimCase) -> None:
    case.soft_delete()

    assert ClaimCase.objects.filter(pk=case.pk).count() == 0
    assert ClaimCase.all_objects.get(pk=case.pk).is_deleted is True
    assert case.deleted_at is not None

    case.restore()

    assert ClaimCase.objects.get(pk=case.pk).is_deleted is False
    assert case.deleted_at is None


# ---------------------------------------------------------------------------
# ClaimMaterial
# ---------------------------------------------------------------------------


def test_claim_material_defaults_and_str(case: ClaimCase) -> None:
    material = ClaimMaterial.objects.create(claim=case, name="诊断证明")

    assert material.is_required is True
    assert material.status == "not_submitted"
    assert material.document is None
    assert material.checked_by is None
    assert material.checked_at is None
    assert str(material) == "林小明-医疗理赔: 诊断证明"
    assert list(case.materials.all()) == [material]


def test_claim_material_document_related_name(case: ClaimCase, document: Document) -> None:
    material = ClaimMaterial.objects.create(claim=case, name="诊断证明", document=document)

    assert list(document.claim_materials.all()) == [material]


def test_claim_material_soft_delete(case: ClaimCase) -> None:
    material = ClaimMaterial.objects.create(claim=case, name="诊断证明")
    material.soft_delete()

    assert ClaimMaterial.objects.filter(pk=material.pk).count() == 0
    assert ClaimMaterial.all_objects.get(pk=material.pk).is_deleted is True


# ---------------------------------------------------------------------------
# ClaimMaterialTemplate
# ---------------------------------------------------------------------------


def test_claim_material_template_defaults_and_str() -> None:
    template = ClaimMaterialTemplate.objects.create(name="测试-理赔申请书", claim_type="medical")

    assert template.is_required is True
    assert template.sort_order == 0
    assert str(template) == "测试-理赔申请书"


def test_claim_material_template_unique_constraint() -> None:
    ClaimMaterialTemplate.objects.create(name="测试-唯一材料", claim_type="medical")

    with pytest.raises(IntegrityError):
        ClaimMaterialTemplate.objects.create(name="测试-唯一材料", claim_type="medical")


def test_claim_material_template_soft_deleted_allows_duplicate() -> None:
    first = ClaimMaterialTemplate.objects.create(name="测试-软删材料", claim_type="medical")
    first.soft_delete()

    second = ClaimMaterialTemplate.objects.create(name="测试-软删材料", claim_type="medical")

    assert second.pk != first.pk
    assert (
        ClaimMaterialTemplate.objects.filter(name="测试-软删材料", claim_type="medical").count()
        == 1
    )


# ---------------------------------------------------------------------------
# 默认模板种子（数据迁移）
# ---------------------------------------------------------------------------


def test_seed_medical_templates_are_complete() -> None:
    medical = ClaimMaterialTemplate.objects.filter(claim_type="medical", is_required=True)
    names = set(medical.values_list("name", flat=True))

    assert medical.count() >= 5
    assert {"理赔申请书", "诊断证明", "医疗费用发票", "费用清单", "病历资料"} <= names
