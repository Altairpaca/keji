"""T8.4 理赔材料 ↔ 文档关联测试（RED 先行，规格 §12 材料项关联文件 / §9 一文件多关联）。

服务层覆盖：attach / detach / 幂等跳过 / 替换；upload_material_document 创建文档并
关联（source=claim:<pk>、title=材料名、customers=案件客户）、重复内容抛
DuplicateDocumentError 且不破坏原关联。

视图层覆盖：attach（GET 表单含可选文件 / 无 manage 权限 403 / POST 选已有 /
POST 传新文件 / 重复文件提示且不落第二份）、detach（POST 解除 / 权限 / 405）、
download（200 + attachment 头 + 内容一致 / 无下载权限 403 / 未关联文件 404）。

URL 经 ``pytest.mark.urls`` 固定到测试专用 URLconf（含 claim_detail 桩），
与并行中的 T8.2 各自独立、互不干扰。
"""

from typing import Any

import pytest
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.claims.models import ClaimCase, ClaimMaterial
from apps.claims.services import create_claim, create_material
from apps.claims.services.documents import (
    attach_document_to_material,
    detach_document_from_material,
    upload_material_document,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Document
from apps.documents.services.files import DuplicateDocumentError, save_upload
from apps.documents.storage import LocalDiskStorage

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.claims.tests.test_urlconf")]

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_bytes(variant: int = 0) -> bytes:
    """最小合法 PNG：前 12 字节满足魔数校验，不同 variant 内容不同（SHA-256 不同）。"""
    return PNG_SIG + variant.to_bytes(4, "big") + b"\x00" * 24


def _make_upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> LocalDiskStorage:
    """每个测试独立的临时存储后端，替换相关模块的 default_storage 引用。"""
    backend = LocalDiskStorage(root=tmp_path)
    for module_name in (
        "apps.documents.services.files",
        "apps.documents.services.thumbnails",
        "apps.claims.views_material_docs",
    ):
        monkeypatch.setattr(f"{module_name}.default_storage", backend)
    return backend


@pytest.fixture
def manager() -> User:
    u = User(
        username="manager",
        can_view_customers=True,
        can_manage_customers=True,
        can_download_originals=True,
    )
    u.save()
    return u


@pytest.fixture
def viewer() -> User:
    u = User(username="viewer", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def customer(manager: User) -> Customer:
    return create_customer(name="林小明", owner=manager, created_by=manager, age_note="约35岁")


@pytest.fixture
def claim(customer: Customer) -> ClaimCase:
    return create_claim(name="车险理赔", customer=customer)


@pytest.fixture
def material(claim: ClaimCase) -> ClaimMaterial:
    return create_material(claim=claim, name="理赔申请书")


def _upload_doc(manager: User, name: str) -> Document:
    return save_upload(
        file=_make_upload(name, _png_bytes(sum(name.encode("utf-8")) % 1000), "image/png"),
        uploaded_by=manager,
    )


def _attach_url(claim: ClaimCase, material: ClaimMaterial) -> str:
    url: str = reverse("claims:material_attach_document", args=[str(claim.pk), str(material.pk)])
    return url


def _detach_url(claim: ClaimCase, material: ClaimMaterial) -> str:
    url: str = reverse("claims:material_detach_document", args=[str(claim.pk), str(material.pk)])
    return url


def _download_url(claim: ClaimCase, material: ClaimMaterial) -> str:
    url: str = reverse("claims:material_download", args=[str(claim.pk), str(material.pk)])
    return url


# ---------------------------------------------------------------------------
# 服务：attach / detach / 幂等
# ---------------------------------------------------------------------------


def test_attach_document_to_material(manager: User, material: ClaimMaterial) -> None:
    doc = _upload_doc(manager, "证明.png")

    returned = attach_document_to_material(material=material, document=doc)

    assert returned.pk == material.pk
    material.refresh_from_db()
    assert material.document_id == doc.pk


def test_attach_document_idempotent_when_same_document(
    manager: User, material: ClaimMaterial
) -> None:
    doc = _upload_doc(manager, "证明.png")
    attach_document_to_material(material=material, document=doc)

    returned = attach_document_to_material(material=material, document=doc)

    assert returned.document_id == doc.pk
    assert ClaimMaterial.objects.get(pk=material.pk).document_id == doc.pk


def test_attach_document_replaces_existing(manager: User, material: ClaimMaterial) -> None:
    doc1 = _upload_doc(manager, "一.png")
    doc2 = _upload_doc(manager, "二.png")
    attach_document_to_material(material=material, document=doc1)

    attach_document_to_material(material=material, document=doc2)

    assert ClaimMaterial.objects.get(pk=material.pk).document_id == doc2.pk


def test_detach_document_from_material(manager: User, material: ClaimMaterial) -> None:
    doc = _upload_doc(manager, "证明.png")
    attach_document_to_material(material=material, document=doc)

    detach_document_from_material(material)

    assert ClaimMaterial.objects.get(pk=material.pk).document_id is None


# ---------------------------------------------------------------------------
# 服务：upload_material_document
# ---------------------------------------------------------------------------


def test_upload_material_document_creates_attaches_and_sets_meta(
    manager: User, customer: Customer, claim: ClaimCase, material: ClaimMaterial
) -> None:
    content = _png_bytes(7)

    returned_material, doc = upload_material_document(
        material=material,
        file=_make_upload("理赔证明.png", content, "image/png"),
        uploaded_by=manager,
    )

    assert returned_material.pk == material.pk
    assert doc.original_name == "理赔证明.png"
    assert doc.title == material.name
    assert doc.source == f"claim:{claim.pk}"
    assert doc.uploaded_by_id == manager.pk
    assert list(doc.customers.values_list("pk", flat=True)) == [customer.pk]
    material.refresh_from_db()
    assert material.document_id == doc.pk


def test_upload_material_document_duplicate_raises_and_keeps_first(
    manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    content = _png_bytes(9)
    first = upload_material_document(
        material=material,
        file=_make_upload("理赔证明.png", content, "image/png"),
        uploaded_by=manager,
    )[1]

    with pytest.raises(DuplicateDocumentError):
        upload_material_document(
            material=material,
            file=_make_upload("换个名字.png", content, "image/png"),
            uploaded_by=manager,
        )

    assert Document.objects.count() == 1
    material.refresh_from_db()
    assert material.document_id == first.pk


# ---------------------------------------------------------------------------
# 视图：material_attach_document
# ---------------------------------------------------------------------------


def test_attach_document_get_shows_form_and_available_docs(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    doc = _upload_doc(manager, "既有文件.png")
    client.force_login(manager)

    response = client.get(_attach_url(claim, material))

    assert response.status_code == 200
    body = response.content.decode()
    assert "理赔申请书" in body
    assert "既有文件.png" in body
    assert doc.pk is not None


def test_attach_document_requires_manage_permission(
    client: Any, viewer: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    client.force_login(viewer)

    assert client.get(_attach_url(claim, material)).status_code == 403
    assert client.post(_attach_url(claim, material), {}).status_code == 403


def test_attach_document_post_select_existing(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    doc = _upload_doc(manager, "既有文件.png")
    client.force_login(manager)

    response = client.post(_attach_url(claim, material), {"document": str(doc.pk)})

    assert response.status_code == 302
    assert ClaimMaterial.objects.get(pk=material.pk).document_id == doc.pk


def test_attach_document_post_upload_new_file(
    client: Any,
    manager: User,
    customer: Customer,
    claim: ClaimCase,
    material: ClaimMaterial,
) -> None:
    content = _png_bytes(3)
    client.force_login(manager)

    response = client.post(
        _attach_url(claim, material),
        {"file": _make_upload("新上传.png", content, "image/png")},
    )

    assert response.status_code == 302
    material.refresh_from_db()
    assert material.document is not None
    doc = material.document
    assert doc.source == f"claim:{claim.pk}"
    assert doc.title == "理赔申请书"
    assert list(doc.customers.values_list("pk", flat=True)) == [customer.pk]


def test_attach_document_post_duplicate_file_shows_error_and_keeps_one_document(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    content = _png_bytes(5)
    upload_material_document(
        material=material,
        file=_make_upload("已有.png", content, "image/png"),
        uploaded_by=manager,
    )
    client.force_login(manager)

    response = client.post(
        _attach_url(claim, material),
        {"file": _make_upload("重复.png", content, "image/png")},
    )

    assert response.status_code == 302
    assert Document.objects.count() == 1
    assert any("文件已存在" in str(m) for m in get_messages(response.wsgi_request))


# ---------------------------------------------------------------------------
# 视图：material_detach_document
# ---------------------------------------------------------------------------


def test_detach_document_post(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    doc = _upload_doc(manager, "证明.png")
    attach_document_to_material(material=material, document=doc)
    client.force_login(manager)

    response = client.post(_detach_url(claim, material))

    assert response.status_code == 302
    assert ClaimMaterial.objects.get(pk=material.pk).document_id is None


def test_detach_document_requires_manage_permission(
    client: Any, viewer: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    client.force_login(viewer)

    assert client.post(_detach_url(claim, material)).status_code == 403


def test_detach_document_rejects_get(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    client.force_login(manager)

    assert client.get(_detach_url(claim, material)).status_code == 405


# ---------------------------------------------------------------------------
# 视图：material_download
# ---------------------------------------------------------------------------


def test_download_streams_attached_document(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    content = _png_bytes(11)
    upload_material_document(
        material=material,
        file=_make_upload("receipt.png", content, "image/png"),
        uploaded_by=manager,
    )
    client.force_login(manager)

    response = client.get(_download_url(claim, material))

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert "receipt.png" in response["Content-Disposition"]
    assert response["Content-Type"] == "image/png"
    assert b"".join(response.streaming_content) == content


def test_download_cjk_filename_is_rfc5987_encoded(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    upload_material_document(
        material=material,
        file=_make_upload("报销单据.png", _png_bytes(13), "image/png"),
        uploaded_by=manager,
    )
    client.force_login(manager)

    response = client.get(_download_url(claim, material))

    assert response.status_code == 200
    disposition = response["Content-Disposition"]
    assert "filename*=utf-8''" in disposition
    assert "%E6%8A%A5%E9%94%80" in disposition  # 「报销」percent-encoded


def test_download_requires_download_permission(
    client: Any, viewer: User, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    doc = _upload_doc(manager, "证明.png")
    attach_document_to_material(material=material, document=doc)
    client.force_login(viewer)

    assert client.get(_download_url(claim, material)).status_code == 403


def test_download_404_when_no_document(
    client: Any, manager: User, claim: ClaimCase, material: ClaimMaterial
) -> None:
    client.force_login(manager)

    assert client.get(_download_url(claim, material)).status_code == 404
