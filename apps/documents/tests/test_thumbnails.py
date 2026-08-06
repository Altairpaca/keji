"""T6.2 documents 缩略图服务测试（RED 先行，ADR-002 派生图分离）。

服务：generate_thumbnail（仅图片、webp 250、EXIF 转正、幂等）、
generate_preview（1440 供查看器）、ensure_thumbnails_for_document、
generate_thumbnails_for_queryset、resolve_view_source（原图 <3MB 用原图）。
失败语义：非图片 / 损坏文件一律返回 ("", "") 且不抛错，不影响上传流程。
"""

import hashlib
import io
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import User
from apps.documents.models import Document
from apps.documents.services.files import save_upload
from apps.documents.services.thumbnails import (
    THUMB_SIZES,
    ensure_thumbnails_for_document,
    generate_preview,
    generate_thumbnail,
    generate_thumbnails_for_queryset,
    resolve_view_source,
)
from apps.documents.storage import LocalDiskStorage

pytestmark = pytest.mark.django_db


def _jpeg_bytes(
    width: int = 800, height: int = 600, color: tuple[int, int, int] = (200, 30, 30)
) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG")
    return buf.getvalue()


def _jpeg_with_orientation(orientation: int) -> bytes:
    """带 EXIF Orientation 标签的 JPEG（400x200 横图）。"""
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = orientation
    Image.new("RGB", (400, 200), (10, 200, 10)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _jpeg_upload(name: str = "photo.jpg", content: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content or _jpeg_bytes(), "image/jpeg")


def _direct_doc(
    storage: LocalDiskStorage,
    content: bytes,
    mime: str = "image/jpeg",
    name: str = "photo.jpg",
    *,
    size: int | None = None,
) -> Document:
    """绕过 save_upload 直接建 Document（不自动生成缩略图），返回文档。"""
    uid = str(uuid.uuid4())
    key = f"originals/{uid[:2]}/{uid}"
    storage.save(key, io.BytesIO(content))
    doc: Document = Document.objects.create(
        original_name=name,
        storage_key=key,
        mime_type=mime,
        size=size or len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    return doc


@pytest.fixture
def uploader() -> User:
    u = User(username="thumb-uploader")
    u.save()
    return u


# ---------------------------------------------------------------------------
# generate_thumbnail
# ---------------------------------------------------------------------------


def test_generate_thumbnail_image_produces_webp(
    isolated_storage: LocalDiskStorage,
) -> None:
    doc = _direct_doc(isolated_storage, _jpeg_bytes(800, 600))

    key, mime = generate_thumbnail(doc)

    assert key.startswith("derived/thumb/")
    assert key.endswith(".webp")
    assert mime == "image/webp"
    assert isolated_storage.exists(key)
    assert doc.thumb_storage_key == key
    assert doc.thumb_mime == "image/webp"
    # 尺寸不超过 250，且等比 contain 保真
    with isolated_storage.open(key) as raw:
        thumb = Image.open(raw)
        assert thumb.format == "WEBP"
        assert thumb.size[0] <= THUMB_SIZES["thumb"][0]
        assert thumb.size[1] <= THUMB_SIZES["thumb"][1]
        # 等比 contain 保真：宽高比与原图一致（800:600 = 4:3）
        assert round(thumb.size[0] / thumb.size[1], 2) == round(800 / 600, 2)


def test_generate_thumbnail_applies_exif_orientation(isolated_storage: LocalDiskStorage) -> None:
    """EXIF Orientation=6：400x200 横图应转正为竖图（高 > 宽）。"""
    doc = _direct_doc(isolated_storage, _jpeg_with_orientation(6))

    key, _mime = generate_thumbnail(doc)

    with isolated_storage.open(key) as raw:
        thumb = Image.open(raw)
        assert thumb.size[1] > thumb.size[0]


def test_generate_thumbnail_non_image_returns_blank(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, b"%PDF-1.4 fake pdf", mime="application/pdf", name="a.pdf")

    key, mime = generate_thumbnail(doc)

    assert key == ""
    assert mime == ""
    assert doc.thumb_storage_key == ""


def test_generate_thumbnail_corrupt_image_returns_blank(isolated_storage: LocalDiskStorage) -> None:
    """损坏文件：有合法 JPEG 魔数但内容不可解码 → 留空不抛错。"""
    doc = _direct_doc(isolated_storage, b"\xff\xd8\xff" + b"\x00" * 200)

    key, _mime = generate_thumbnail(doc)

    assert key == ""
    assert doc.thumb_storage_key == ""


def test_generate_thumbnail_idempotent(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, _jpeg_bytes())

    first_key, _mime = generate_thumbnail(doc)
    second_key, _mime2 = generate_thumbnail(doc)

    assert first_key == second_key == doc.thumb_storage_key
    assert isolated_storage.exists(first_key)


# ---------------------------------------------------------------------------
# ensure_thumbnails_for_document / generate_thumbnails_for_queryset
# ---------------------------------------------------------------------------


def test_ensure_thumbnails_skips_when_already_set(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, _jpeg_bytes())
    doc.thumb_storage_key = "derived/thumb/aa/1.webp"
    doc.save(update_fields=["thumb_storage_key"])

    ensure_thumbnails_for_document(doc)

    assert doc.thumb_storage_key == "derived/thumb/aa/1.webp"
    assert not isolated_storage.exists("derived/thumb/aa/1.webp")


def test_save_upload_generates_thumbnail(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    """上传真实图片后自动生成缩略图（files.py 内部调用 ensure）。"""
    doc = save_upload(file=_jpeg_upload(), uploaded_by=uploader)

    assert doc.thumb_storage_key.startswith("derived/thumb/")
    assert isolated_storage.exists(doc.thumb_storage_key)


def test_generate_thumbnails_for_queryset(isolated_storage: LocalDiskStorage) -> None:
    image_a = _direct_doc(isolated_storage, _jpeg_bytes(1, color=(1, 2, 3)))
    image_b = _direct_doc(isolated_storage, _jpeg_bytes(2, color=(4, 5, 6)))
    pdf = _direct_doc(isolated_storage, b"%PDF-1.4", mime="application/pdf", name="a.pdf")

    count = generate_thumbnails_for_queryset(Document.objects.all())

    assert count == 2
    assert Document.objects.get(pk=image_a.pk).thumb_storage_key
    assert Document.objects.get(pk=image_b.pk).thumb_storage_key
    assert pdf.thumb_storage_key == ""


# ---------------------------------------------------------------------------
# generate_preview / resolve_view_source
# ---------------------------------------------------------------------------


def test_generate_preview_produces_large_webp(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, _jpeg_bytes(3000, 2000))

    key, mime = generate_preview(doc)

    assert key.startswith("derived/preview/")
    assert mime == "image/webp"
    assert isolated_storage.exists(key)
    with isolated_storage.open(key) as raw:
        preview = Image.open(raw)
        assert preview.size[0] <= THUMB_SIZES["preview"][0]
        assert preview.size[1] <= THUMB_SIZES["preview"][1]


def test_resolve_view_source_small_image_uses_original(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, _jpeg_bytes(600, 400))

    key, mime = resolve_view_source(doc)

    assert key == doc.storage_key
    assert mime == "image/jpeg"


def test_resolve_view_source_large_image_uses_preview(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, _jpeg_bytes(800, 600))
    # 强制视为大图（原图 ≥ 3MB）
    Document.objects.filter(pk=doc.pk).update(size=5 * 1024 * 1024)
    doc.refresh_from_db()

    key, mime = resolve_view_source(doc)

    assert key.startswith("derived/preview/")
    assert mime == "image/webp"
    assert isolated_storage.exists(key)


def test_resolve_view_source_non_image_returns_blank(isolated_storage: LocalDiskStorage) -> None:
    doc = _direct_doc(isolated_storage, b"%PDF-1.4", mime="application/pdf", name="a.pdf")

    key, mime = resolve_view_source(doc)

    assert key == ""
    assert mime == ""
