"""业务服务接入审计测试（T10.2，RED 先行，规格 §17 / §18）。

验证各业务服务的审计接入点（用 import 而非 signals）：
- customers.soft_delete_customer / restore_customer：传 actor 后落审计，
  不传时 actor=None 正常（签名向后兼容）；
- policies.change_status：detail 含 from_status / to_status；
- claims.change_claim_status / change_material_status：detail 含状态迁移；
- documents.recycle.permanent_delete_document：document.permanent_delete；
- accounts 用户管理视图：user.create / user.update / user.toggle_active。
"""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.claims.services import (
    change_claim_status,
    change_material_status,
    create_claim,
    create_material,
)
from apps.customers.models import Customer
from apps.customers.services import restore_customer, soft_delete_customer
from apps.documents.services import save_upload, soft_delete_document
from apps.documents.services.recycle import permanent_delete_document
from apps.documents.storage import LocalDiskStorage
from apps.policies.services import change_status, create_policy

pytestmark = pytest.mark.django_db

PNG_SIG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def operator() -> User:
    u = User(username="operator", can_view_audit_logs=True, can_manage_users=True)
    u.save()
    return u


@pytest.fixture
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskStorage:
    """本 app 测试独立的临时存储后端（与 documents/tests/conftest 同构）。"""
    backend = LocalDiskStorage(root=tmp_path)
    monkeypatch.setattr("apps.documents.services.files.default_storage", backend)
    monkeypatch.setattr("apps.documents.services.thumbnails.default_storage", backend)
    monkeypatch.setattr("apps.documents.services.recycle.default_storage", backend)
    return backend


def _make_upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


def _png_bytes() -> bytes:
    return PNG_SIG + b"\x00" * 36


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------


def test_soft_delete_customer_records_audit(operator: User) -> None:
    customer = Customer.objects.create(name="张三")

    soft_delete_customer(customer, actor=operator)

    log = AuditLog.objects.get(action="customer.soft_delete")
    assert log.actor == operator
    assert log.object_pk == str(customer.pk)
    assert log.target_label == "张三"


def test_restore_customer_records_audit(operator: User) -> None:
    customer = Customer.objects.create(name="李四")
    soft_delete_customer(customer, actor=operator)

    restore_customer(customer, actor=operator)

    log = AuditLog.objects.get(action="customer.restore")
    assert log.actor == operator
    assert log.target_label == "李四"


def test_soft_delete_without_actor_allows_null() -> None:
    customer = Customer.objects.create(name="王五")

    soft_delete_customer(customer)

    log = AuditLog.objects.get(action="customer.soft_delete")
    assert log.actor is None


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------


def test_change_status_records_from_to_in_detail(operator: User) -> None:
    customer = Customer.objects.create(name="赵六")
    policy = create_policy(
        insurer="测试保险", name="重疾险", policy_no="P-2026-001", policyholder=customer
    )

    change_status(policy=policy, new_status="lapsed", changed_by=operator)

    log = AuditLog.objects.get(action="policy.change_status")
    assert log.detail == {"from_status": "active", "to_status": "lapsed"}
    assert log.target_label == "P-2026-001"


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


def test_change_claim_status_records_audit(operator: User) -> None:
    customer = Customer.objects.create(name="钱七")
    claim = create_claim(name="意外险理赔", customer=customer, owner=operator)

    change_claim_status(claim=claim, new_status="reported", changed_by=operator)

    log = AuditLog.objects.get(action="claim.change_status")
    assert log.detail == {"from_status": "consultation", "to_status": "reported"}
    assert log.target_label == "意外险理赔"


def test_change_material_status_records_audit(operator: User) -> None:
    customer = Customer.objects.create(name="孙八")
    claim = create_claim(name="医疗险理赔", customer=customer)
    material = create_material(claim=claim, name="病历")

    change_material_status(material=material, new_status="submitted", changed_by=operator)

    log = AuditLog.objects.get(action="claim.material_status")
    assert log.detail == {"from_status": "not_submitted", "to_status": "submitted"}
    assert log.target_label == "病历"


# ---------------------------------------------------------------------------
# documents recycle（§18：永久删除留痕）
# ---------------------------------------------------------------------------


def test_permanent_delete_document_records_audit(
    operator: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = save_upload(
        file=_make_upload("trash.png", _png_bytes(), "image/png"), uploaded_by=operator
    )
    soft_delete_document(doc)
    doc_pk = doc.pk  # delete(force=True) 会把实例 pk 置 None，先留档

    permanent_delete_document(doc, actor=operator)

    log = AuditLog.objects.get(action="document.permanent_delete")
    assert log.actor == operator
    assert log.object_pk == str(doc_pk)


# ---------------------------------------------------------------------------
# accounts 用户管理视图
# ---------------------------------------------------------------------------


def test_user_toggle_active_view_records_audit(client: Client, operator: User) -> None:
    target = User.objects.create(username="target", is_active=True)
    client.force_login(operator)

    response = client.post(reverse("accounts:user_toggle_active", args=[target.pk]), follow=True)

    assert response.status_code == 200
    log = AuditLog.objects.get(action="user.toggle_active")
    assert log.actor == operator
    assert log.target_label == "target"
