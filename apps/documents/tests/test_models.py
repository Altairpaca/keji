"""T6.1 documents 模型测试（RED 先行，规格 §9 / data-model.md documents 节）。

覆盖：Album 默认类别与自定义类别扩展、全局相册（customer 为空）；
Document 全量字段默认值、软删 / 恢复（ADR-006）、客户与相册 M2M 关联。
"""

import pytest

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import ALBUM_CATEGORIES, Album, Document

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    u = User(username="uploader")
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


def _make_doc(user: User, **overrides: object) -> Document:
    base: dict[str, object] = {
        "original_name": "照片.jpg",
        "storage_key": "originals/ab/9c5b94e0-2f09-4c1f-8f3e-000000000000",
        "mime_type": "image/jpeg",
        "size": 1024,
        "sha256": "a" * 64,
        "uploaded_by": user,
    }
    base.update(overrides)
    doc: Document = Document.objects.create(**base)
    return doc


# ---------------------------------------------------------------------------
# Album
# ---------------------------------------------------------------------------


def test_album_categories_contains_ten_defaults() -> None:
    values = [value for value, _label in ALBUM_CATEGORIES]
    assert values == [
        "id_docs",
        "policy_docs",
        "claim_docs",
        "hospital_docs",
        "chat_screenshots",
        "meeting_photos",
        "event_photos",
        "signature_docs",
        "payment_receipts",
        "other",
    ]


def test_album_fields_defaults_and_str(customer: Customer) -> None:
    album = Album.objects.create(name="证件", category="id_docs", customer=customer)

    assert album.category == "id_docs"
    assert album.custom_category == ""
    assert album.description == ""
    assert album.customer == customer
    assert album.is_deleted is False
    assert str(album) == "证件"


def test_album_global_without_customer() -> None:
    album = Album.objects.create(name="全局相册", category="other")

    assert album.customer is None


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def test_document_field_defaults(user: User) -> None:
    doc = _make_doc(user)

    assert doc.original_name == "照片.jpg"
    assert doc.mime_type == "image/jpeg"
    assert doc.size == 1024
    assert doc.sha256 == "a" * 64
    assert doc.taken_at is None
    assert doc.title == ""
    assert doc.note == ""
    assert doc.sensitivity == "normal"
    assert doc.is_important is False
    assert doc.check_status == "unchecked"
    assert doc.source == ""
    assert doc.uploaded_by == user
    assert doc.thumb_storage_key == ""
    assert doc.thumb_mime == ""
    assert doc.customers.count() == 0
    assert doc.albums.count() == 0
    assert str(doc) == "照片.jpg"


def test_document_sensitivity_and_check_status_choices(user: User) -> None:
    doc = _make_doc(user, sensitivity="highly_sensitive", check_status="needs_supplement")

    assert doc.sensitivity == "highly_sensitive"
    assert doc.check_status == "needs_supplement"


def test_document_soft_delete_and_restore(user: User) -> None:
    doc = _make_doc(user)

    doc.soft_delete()

    assert Document.objects.filter(pk=doc.pk).count() == 0
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True
    assert Document.all_objects.get(pk=doc.pk).deleted_at is not None

    doc.restore()

    assert Document.objects.filter(pk=doc.pk).count() == 1
    assert Document.all_objects.get(pk=doc.pk).deleted_at is None


def test_document_m2m_customers_and_albums(user: User, customer: Customer) -> None:
    second = create_customer(name="王秀英", owner=user, created_by=user, age_note="约40岁")
    album = Album.objects.create(name="客户证件", category="id_docs", customer=customer)
    doc = _make_doc(
        user,
        original_name="身份证.jpg",
        storage_key="originals/ab/9c5b94e0-2f09-4c1f-8f3e-000000000001",
    )

    doc.customers.add(customer, second)
    doc.albums.add(album)

    # 按 name 升序：林（0x6797）在 王（0x738B）之前
    assert list(doc.customers.order_by("name")) == [customer, second]
    assert list(doc.albums.all()) == [album]
    # 反向 related_name 关联可用
    assert customer.documents.filter(pk=doc.pk).count() == 1
    assert album.documents.filter(pk=doc.pk).count() == 1
