"""T6.2 documents 图片查看器视图测试（RED 先行，ADR-002）。

viewer（/documents/<uuid>/view/）：图片内联 <img>、大图降级 preview、
PDF/Office 类型图标 + 下载链接、敏感级别 blur、元数据行；需 can_view_customers。
document_thumb / document_image：派生图字节内联输出，无缩略图 / 非图片 404。
"""

import io
import uuid
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.documents.models import Document
from apps.documents.services.files import save_upload
from apps.documents.storage import LocalDiskStorage

pytestmark = pytest.mark.django_db


def _jpeg_bytes(width: int = 600, height: int = 400) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (30, 100, 200)).save(buf, "JPEG")
    return buf.getvalue()


def _jpeg_upload(name: str = "photo.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _jpeg_bytes(), "image/jpeg")


@pytest.fixture
def uploader() -> User:
    u = User(
        username="viewer-uploader",
        can_view_customers=True,
        can_manage_customers=True,
        can_download_originals=True,
    )
    u.save()
    return u


@pytest.fixture
def viewer() -> User:
    u = User(username="plain-viewer", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def plain() -> User:
    u = User(username="no-view")
    u.save()
    return u


@pytest.fixture
def image_doc(uploader: User, isolated_storage: LocalDiskStorage) -> Document:
    return save_upload(file=_jpeg_upload(), uploaded_by=uploader)


@pytest.fixture
def pdf_doc(uploader: User) -> Document:
    return save_upload(
        file=SimpleUploadedFile("合同.pdf", b"%PDF-1.4 fake pdf", "application/pdf"),
        uploaded_by=uploader,
    )


# ---------------------------------------------------------------------------
# viewer
# ---------------------------------------------------------------------------


def test_viewer_image_renders_inline_img(client: Any, viewer: User, image_doc: Document) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:viewer", args=[str(image_doc.pk)]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<img" in content
    assert reverse("documents:document_image", args=[str(image_doc.pk)]) in content
    # 元数据行：原始文件名
    assert image_doc.original_name in content


def test_viewer_large_image_shows_preview_note(
    client: Any, viewer: User, image_doc: Document
) -> None:
    Document.objects.filter(pk=image_doc.pk).update(size=5 * 1024 * 1024)

    client.force_login(viewer)
    response = client.get(reverse("documents:viewer", args=[str(image_doc.pk)]))

    assert response.status_code == 200
    assert "预览" in response.content.decode()


def test_viewer_sensitive_image_has_blur_class(
    client: Any, viewer: User, image_doc: Document
) -> None:
    Document.objects.filter(pk=image_doc.pk).update(sensitivity="sensitive")

    client.force_login(viewer)
    response = client.get(reverse("documents:viewer", args=[str(image_doc.pk)]))

    assert response.status_code == 200
    assert "blur" in response.content.decode()


def test_viewer_pdf_shows_download_link(client: Any, uploader: User, pdf_doc: Document) -> None:
    client.force_login(uploader)

    response = client.get(reverse("documents:viewer", args=[str(pdf_doc.pk)]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "点击下载" in content
    assert reverse("documents:document_download", args=[str(pdf_doc.pk)]) in content
    assert "合同.pdf" in content


def test_viewer_requires_view_permission(client: Any, plain: User, image_doc: Document) -> None:
    assert client.get(reverse("documents:viewer", args=[str(image_doc.pk)])).status_code == 302

    client.force_login(plain)
    assert client.get(reverse("documents:viewer", args=[str(image_doc.pk)])).status_code == 403


def test_viewer_missing_document_404(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:viewer", args=[str(uuid.uuid4())]))

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# document_thumb / document_image
# ---------------------------------------------------------------------------


def test_document_thumb_serves_webp(client: Any, viewer: User, image_doc: Document) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:document_thumb", args=[str(image_doc.pk)]))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    data = b"".join(response.streaming_content)
    assert data[:4] == b"RIFF"  # WEBP 容器魔数


def test_document_thumb_404_without_thumb(client: Any, viewer: User, pdf_doc: Document) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:document_thumb", args=[str(pdf_doc.pk)]))

    assert response.status_code == 404


def test_document_thumb_requires_view_permission(
    client: Any, plain: User, image_doc: Document
) -> None:
    client.force_login(plain)

    response = client.get(reverse("documents:document_thumb", args=[str(image_doc.pk)]))

    assert response.status_code == 403


def test_document_image_serves_original_for_small(
    client: Any, viewer: User, image_doc: Document
) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:document_image", args=[str(image_doc.pk)]))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert b"".join(response.streaming_content) == _jpeg_bytes()


def test_document_image_serves_preview_for_large(
    client: Any, viewer: User, image_doc: Document
) -> None:
    Document.objects.filter(pk=image_doc.pk).update(size=5 * 1024 * 1024)

    client.force_login(viewer)
    response = client.get(reverse("documents:document_image", args=[str(image_doc.pk)]))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"


def test_document_image_404_for_non_image(client: Any, viewer: User, pdf_doc: Document) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:document_image", args=[str(pdf_doc.pk)]))

    assert response.status_code == 404
