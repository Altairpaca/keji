"""T6.1 documents 上传服务与视图测试（RED 先行，规格 §9/§10 + security.md §4）。

服务：validate_upload（大小 / 扩展名 / 声明 MIME / 魔数双重校验）、
save_upload（流式 sha256、分片存储键、客户与相册关联、重复抛
DuplicateDocumentError）、软删 / 恢复。
视图：权限矩阵（上传 need can_manage_customers、列表/详情 need
can_view_customers、下载 need can_download_originals）、部分失败收集、
列表筛选与分页、下载 Content-Disposition attachment。
"""

import hashlib
import re
import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Album, Document
from apps.documents.services.files import (
    DuplicateDocumentError,
    restore_document,
    save_upload,
    soft_delete_document,
    validate_upload,
)
from apps.documents.storage import LocalDiskStorage

pytestmark = pytest.mark.django_db

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_bytes(variant: int = 0) -> bytes:
    """最小合法 PNG：前 12 字节满足魔数（签名 + IHDR 段），不同 variant 内容不同。"""
    return PNG_SIG + variant.to_bytes(4, "big") + b"\x00" * 24


def _make_upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def uploader() -> User:
    u = User(
        username="uploader",
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
def plain() -> User:
    u = User(username="plain")
    u.save()
    return u


@pytest.fixture
def customer(uploader: User) -> Customer:
    return create_customer(name="林小明", owner=uploader, created_by=uploader, age_note="约35岁")


@pytest.fixture
def album(customer: Customer) -> Album:
    album: Album = Album.objects.create(name="客户证件", category="id_docs", customer=customer)
    return album


# ---------------------------------------------------------------------------
# 服务：validate_upload
# ---------------------------------------------------------------------------


def test_validate_upload_returns_content_type_and_size() -> None:
    content_type, size = validate_upload(_make_upload("x.png", _png_bytes(), "image/png"))

    assert content_type == "image/png"
    assert size == len(_png_bytes())


def test_validate_upload_office_docx_zip_magic_ok() -> None:
    f = _make_upload(
        "报告.docx",
        b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 8,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    content_type, _ = validate_upload(f)

    assert content_type.startswith("application/vnd.openxmlformats-officedocument")


def test_validate_upload_rejects_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.documents.services.files.MAX_SIZE", 10)

    with pytest.raises(ValueError, match="大小限制"):
        validate_upload(_make_upload("big.png", _png_bytes(), "image/png"))


def test_validate_upload_rejects_magic_mismatch() -> None:
    """文本文件改名 .jpg：声明 MIME / 扩展名符合，但魔数与 PNG 不符 → 拒绝。"""
    f = _make_upload("fake.jpg", b"hello world, this is text not a jpeg!", "image/jpeg")

    with pytest.raises(ValueError, match="文件类型与扩展名不符"):
        validate_upload(f)


def test_validate_upload_rejects_disallowed_extension() -> None:
    """zip / rar / 7z 不在白名单（security.md §4 压缩包风险）。"""
    f = _make_upload("evil.zip", b"PK\x03\x04\x00\x00", "application/zip")

    with pytest.raises(ValueError, match="不支持的文件类型"):
        validate_upload(f)


def test_validate_upload_rejects_declared_mime_not_matching_extension() -> None:
    """扩展名 .png 但声明 MIME 为 text/plain → 拒绝。"""
    f = _make_upload("x.png", _png_bytes(), "text/plain")

    with pytest.raises(ValueError, match="文件类型与扩展名不符"):
        validate_upload(f)


# ---------------------------------------------------------------------------
# 服务：save_upload
# ---------------------------------------------------------------------------


def test_save_upload_writes_document_and_relations(
    uploader: User,
    customer: Customer,
    album: Album,
    isolated_storage: LocalDiskStorage,
) -> None:
    content = _png_bytes(1)

    doc = save_upload(
        file=_make_upload("photo.png", content, "image/png"),
        uploaded_by=uploader,
        title="客户证件照",
        note="身份证正面",
        sensitivity="sensitive",
        customers=[customer],
        albums=[album],
        source="mobile",
    )

    assert doc.original_name == "photo.png"
    assert doc.mime_type == "image/png"
    assert doc.size == len(content)
    assert doc.sha256 == hashlib.sha256(content).hexdigest()
    assert doc.title == "客户证件照"
    assert doc.note == "身份证正面"
    assert doc.sensitivity == "sensitive"
    assert doc.source == "mobile"
    assert doc.uploaded_by == uploader
    assert list(doc.customers.all()) == [customer]
    assert list(doc.albums.all()) == [album]
    # 存储键分片格式（ADR-002/005）
    assert re.fullmatch(r"originals/[0-9a-f]{2}/[0-9a-f-]{36}", doc.storage_key)
    # 物理文件已写入且内容一致
    assert isolated_storage.exists(doc.storage_key)
    assert isolated_storage.open(doc.storage_key).read() == content


def test_save_upload_streams_large_file_hash(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    """约 2MB 内容：流式分块计算 sha256 与写入，不整载内存（人工保证）。"""
    content = PNG_SIG + b"\x00" * (2 * 1024 * 1024)

    doc = save_upload(file=_make_upload("big.png", content, "image/png"), uploaded_by=uploader)

    assert doc.sha256 == hashlib.sha256(content).hexdigest()
    assert doc.size == len(content)
    assert isolated_storage.size(doc.storage_key) == len(content)


def test_save_upload_duplicate_raises(uploader: User, isolated_storage: LocalDiskStorage) -> None:
    save_upload(file=_make_upload("a.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    with pytest.raises(DuplicateDocumentError):
        save_upload(file=_make_upload("b.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    # 只有一条记录、一份物理文件
    assert Document.objects.count() == 1
    shards = list((isolated_storage.root / "originals").iterdir())
    assert len(shards) == 1


def test_save_upload_soft_delete_and_restore(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = save_upload(file=_make_upload("a.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    soft_delete_document(doc)

    assert Document.objects.filter(pk=doc.pk).count() == 0
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True
    # 物理文件不动（T6.4 回收站清理再处理）
    assert isolated_storage.exists(doc.storage_key)

    restore_document(doc)
    assert Document.objects.filter(pk=doc.pk).count() == 1


# ---------------------------------------------------------------------------
# 视图：权限矩阵
# ---------------------------------------------------------------------------


def test_upload_anonymous_redirects_to_login(client: Any) -> None:
    response = client.get(reverse("documents:upload"))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_upload_requires_manage_permission(client: Any, viewer: User, plain: User) -> None:
    client.force_login(viewer)

    assert client.get(reverse("documents:upload")).status_code == 403

    client.force_login(plain)
    assert client.get(reverse("documents:upload")).status_code == 403


def test_upload_get_renders_file_input_with_choosers(
    client: Any, uploader: User, customer: Customer, album: Album
) -> None:
    client.force_login(uploader)

    response = client.get(reverse("documents:upload"))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'type="file"' in content
    assert 'name="files"' in content
    assert "multiple" in content
    assert "capture" in content
    assert customer.name in content
    assert album.name in content


def test_document_list_permissions(client: Any, uploader: User, viewer: User, plain: User) -> None:
    # 未登录 → 重定向登录页
    assert client.get(reverse("documents:document_list")).status_code == 302

    client.force_login(uploader)
    save_upload(file=_make_upload("a.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    client.force_login(plain)
    assert client.get(reverse("documents:document_list")).status_code == 403

    client.force_login(viewer)
    response = client.get(reverse("documents:document_list"))
    assert response.status_code == 200
    assert "a.png" in response.content.decode()


def test_document_detail_permission(client: Any, viewer: User, plain: User, uploader: User) -> None:
    doc = save_upload(file=_make_upload("a.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    client.force_login(plain)
    assert client.get(reverse("documents:document_detail", args=[str(doc.pk)])).status_code == 403

    client.force_login(viewer)
    response = client.get(reverse("documents:document_detail", args=[str(doc.pk)]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "a.png" in content


def test_download_requires_download_permission(
    client: Any, uploader: User, viewer: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = save_upload(file=_make_upload("a.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    # 未登录 → 重定向登录页
    assert client.get(reverse("documents:document_download", args=[str(doc.pk)])).status_code == 302

    # 有查看权限但无下载原文件权限 → 403
    client.force_login(viewer)
    assert client.get(reverse("documents:document_download", args=[str(doc.pk)])).status_code == 403

    # 有下载权限 → 200，attachment 附件下载，内容一致（FileResponse 流式）
    client.force_login(uploader)
    response = client.get(reverse("documents:document_download", args=[str(doc.pk)]))
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert b"".join(response.streaming_content) == _png_bytes()


# ---------------------------------------------------------------------------
# 视图：上传 POST
# ---------------------------------------------------------------------------


def test_upload_post_success(
    client: Any,
    uploader: User,
    customer: Customer,
    album: Album,
    isolated_storage: LocalDiskStorage,
) -> None:
    client.force_login(uploader)
    content = _png_bytes(2)

    response = client.post(
        reverse("documents:upload"),
        {
            "files": _make_upload("photo.png", content, "image/png"),
            "customers": [str(customer.pk)],
            "albums": [str(album.pk)],
            "title": "客户证件照",
            "note": "备注内容",
            "sensitivity": "sensitive",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("documents:upload_result")
    doc = Document.objects.get()
    assert doc.original_name == "photo.png"
    assert doc.sha256 == hashlib.sha256(content).hexdigest()
    assert doc.title == "客户证件照"
    assert doc.note == "备注内容"
    assert doc.sensitivity == "sensitive"
    assert list(doc.customers.all()) == [customer]
    assert list(doc.albums.all()) == [album]
    assert isolated_storage.exists(doc.storage_key)


def test_upload_post_partial_failure_keeps_others(
    client: Any, uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    client.force_login(uploader)
    good = _make_upload("ok.png", _png_bytes(3), "image/png")
    bad = _make_upload("fake.jpg", b"plain text not an image", "image/jpeg")

    response = client.post(reverse("documents:upload"), {"files": [good, bad]})

    assert response.status_code == 302
    # 合法文件入库，失败文件不影响其他
    assert Document.objects.count() == 1
    doc = Document.objects.get()
    assert doc.original_name == "ok.png"
    # 失败提示随重定向展示
    follow = client.get(response.url)
    assert "fake.jpg" in follow.content.decode()
    assert "文件类型与扩展名不符" in follow.content.decode()


def test_upload_post_duplicate_shows_message(
    client: Any, uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    client.force_login(uploader)
    client.post(
        reverse("documents:upload"), {"files": _make_upload("a.png", _png_bytes(), "image/png")}
    )

    response = client.post(
        reverse("documents:upload"), {"files": _make_upload("b.png", _png_bytes(), "image/png")}
    )

    assert response.status_code == 302
    assert Document.objects.count() == 1
    follow = client.get(response.url)
    assert "已存在" in follow.content.decode()


def test_upload_post_without_files_redirects(client: Any, uploader: User) -> None:
    client.force_login(uploader)

    response = client.post(reverse("documents:upload"), {})

    assert response.status_code == 302
    assert Document.objects.count() == 0


# ---------------------------------------------------------------------------
# 视图：列表筛选 / 分页 / 软删隐藏
# ---------------------------------------------------------------------------


def test_document_list_filters(
    client: Any,
    viewer: User,
    uploader: User,
    customer: Customer,
    isolated_storage: LocalDiskStorage,
) -> None:
    client.force_login(viewer)
    save_upload(
        file=_make_upload("cat.png", _png_bytes(4), "image/png"),
        uploaded_by=uploader,
        customers=[customer],
    )
    save_upload(
        file=_make_upload("doc.pdf", b"%PDF-1.4 fake pdf", "application/pdf"),
        uploaded_by=uploader,
    )

    by_customer = client.get(reverse("documents:document_list"), {"customer": str(customer.pk)})
    assert "cat.png" in by_customer.content.decode()
    assert "doc.pdf" not in by_customer.content.decode()

    by_type = client.get(reverse("documents:document_list"), {"type": "image"})
    assert "cat.png" in by_type.content.decode()
    assert "doc.pdf" not in by_type.content.decode()

    by_sensitivity = client.get(reverse("documents:document_list"), {"sensitivity": "normal"})
    assert "doc.pdf" in by_sensitivity.content.decode()


def test_document_list_hides_soft_deleted(
    client: Any, viewer: User, uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    client.force_login(viewer)
    save_upload(file=_make_upload("kept.png", _png_bytes(5), "image/png"), uploaded_by=uploader)
    gone = save_upload(
        file=_make_upload("gone.png", _png_bytes(6), "image/png"), uploaded_by=uploader
    )
    soft_delete_document(gone)

    response = client.get(reverse("documents:document_list"))
    content = response.content.decode()

    assert "kept.png" in content
    assert "gone.png" not in content


def test_document_list_paginates(client: Any, viewer: User, uploader: User) -> None:
    client.force_login(viewer)
    base = timezone.now()
    for i in range(25):
        doc = Document.objects.create(
            original_name=f"f{i:02d}.png",
            storage_key=f"originals/ab/{uuid.uuid4()}",
            mime_type="image/png",
            size=1,
            sha256=hashlib.sha256(str(i).encode()).hexdigest(),
            uploaded_by=uploader,
        )
        # auto_now_add 忽略 create 时显式传入的时间，改用 update 精确设定
        Document.objects.filter(pk=doc.pk).update(created_at=base - timedelta(minutes=i))

    page1 = client.get(reverse("documents:document_list"))
    page2 = client.get(reverse("documents:document_list"), {"page": "2"})

    # -created_at 排序：f00 最新在第一页，f24 最旧在第二页
    assert "f00.png" in page1.content.decode()
    assert "f24.png" not in page1.content.decode()
    assert "f24.png" in page2.content.decode()


def test_document_list_empty_state(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(reverse("documents:document_list"))

    assert response.status_code == 200
    assert "还没有文件" in response.content.decode()
