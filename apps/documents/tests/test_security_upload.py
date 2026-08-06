"""上传安全测试（security.md §4 + 规格 §10 文件安全清单全项）。

覆盖清单：
- 伪造扩展名：文本改名 .jpg / .pdf（魔数不符）→ ValueError
- 可执行 / 脚本内容拒绝：.exe / .html / .svg（白名单外，XSS 风险）→ ValueError
- 超大文件：monkeypatch 缩小 MAX_SIZE 后拒绝
- 路径穿越：存储键含 ``../`` 拒绝；original_name 含 ``../`` 不影响物理键（UUID）
- MIME 白名单外 content_type 拒绝
- 并发同内容上传：advisory 锁串行化查重+入库，一个成功一个 DuplicateDocumentError
- 中断清理：save_upload 中途抛异常 → storage 无残留（临时文件清理）
- 重复提交：同文件两次 POST → 第二次去重提示（ADR-009）
"""

import threading
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.documents.models import Document
from apps.documents.services.files import (
    DuplicateDocumentError,
    save_upload,
    validate_upload,
)
from apps.documents.storage import LocalDiskStorage, StorageKeyError

pytestmark = pytest.mark.django_db

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_bytes(variant: int = 0) -> bytes:
    """最小合法 PNG：前 12 字节满足魔数（签名 + IHDR 段），不同 variant 内容不同。"""
    return PNG_SIG + variant.to_bytes(4, "big") + b"\x00" * 24


def _make_upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.fixture
def uploader() -> User:
    u = User(username="sec-uploader", can_manage_customers=True)
    u.save()
    return u


def _storage_files(storage: LocalDiskStorage) -> list[str]:
    """存储根目录下的全部相对键（用于断言无残留）。"""
    return [
        str(path.relative_to(storage.root)) for path in storage.root.rglob("*") if path.is_file()
    ]


# ---------------------------------------------------------------------------
# 伪造扩展名 / 魔数校验
# ---------------------------------------------------------------------------


def test_fake_jpg_rejected_by_magic() -> None:
    """文本文件改名 .jpg：扩展名与声明 MIME 均符合白名单，但魔数不符 → 拒绝。"""
    f = _make_upload("photo.jpg", b"hello world, plain text", "image/jpeg")

    with pytest.raises(ValueError, match="文件类型与扩展名不符"):
        validate_upload(f)


def test_fake_pdf_rejected_by_magic() -> None:
    """文本文件改名 .pdf：缺少 %PDF 文件头签名 → 拒绝。"""
    f = _make_upload("report.pdf", b"definitely not a real pdf file", "application/pdf")

    with pytest.raises(ValueError, match="文件类型与扩展名不符"):
        validate_upload(f)


# ---------------------------------------------------------------------------
# 可执行 / 脚本内容拒绝（白名单外，XSS 风险，规格 §10）
# ---------------------------------------------------------------------------


def test_executable_extension_rejected() -> None:
    f = _make_upload("installer.exe", b"MZ\x90\x00", "application/octet-stream")

    with pytest.raises(ValueError, match="不支持的文件类型"):
        validate_upload(f)


def test_html_rejected_xss_risk() -> None:
    f = _make_upload("page.html", b"<script>alert(1)</script>", "text/html")

    with pytest.raises(ValueError, match="不支持的文件类型"):
        validate_upload(f)


def test_svg_rejected_xss_risk() -> None:
    """SVG 不在白名单（内嵌脚本风险，security.md §4 / 规格 §10）。"""
    f = _make_upload(
        "vector.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        "image/svg+xml",
    )

    with pytest.raises(ValueError, match="不支持的文件类型"):
        validate_upload(f)


# ---------------------------------------------------------------------------
# 超大文件
# ---------------------------------------------------------------------------


def test_oversized_file_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.documents.services.files.MAX_SIZE", 8)

    with pytest.raises(ValueError, match="大小限制"):
        validate_upload(_make_upload("big.png", _png_bytes(1), "image/png"))


# ---------------------------------------------------------------------------
# MIME 白名单外 content_type
# ---------------------------------------------------------------------------


def test_declared_mime_outside_whitelist_rejected() -> None:
    """扩展名 .png 但声明 content_type 在 MIME 白名单外 → 拒绝。"""
    f = _make_upload("x.png", _png_bytes(2), "application/octet-stream")

    with pytest.raises(ValueError, match="文件类型与扩展名不符"):
        validate_upload(f)


def test_mime_whitelisted_but_extension_missing_rejected() -> None:
    """MIME 合法但扩展名不在该 MIME 的允许集合 → 拒绝。"""
    f = _make_upload("x.jpg", b"\xff\xd8\xff" + b"\x00" * 12, "image/png")

    with pytest.raises(ValueError, match="文件类型与扩展名不符"):
        validate_upload(f)


# ---------------------------------------------------------------------------
# 路径穿越（security.md §4：存储键一律 UUID，存储层拒绝 ../）
# ---------------------------------------------------------------------------


def test_storage_key_traversal_rejected() -> None:
    """存储键含 ../ 直接拒绝（本地磁盘存储层 _safe_join）。"""
    from apps.documents.services.files import default_storage as storage

    with pytest.raises(StorageKeyError):
        storage.save("../evil.txt", _make_upload("e.txt", b"x", "text/plain"))


def test_absolute_storage_key_rejected() -> None:
    from apps.documents.services.files import default_storage as storage

    with pytest.raises(StorageKeyError):
        storage.save("/etc/passwd", _make_upload("e.txt", b"x", "text/plain"))


def test_original_name_traversal_does_not_affect_storage_key(
    uploader: User,
) -> None:
    """original_name 含 ../../ 不影响物理键：Django UploadedFile 已 basename 规范化，
    存储键一律 UUID（ADR-005），穿越文件名无法改写落盘位置。"""
    doc = save_upload(
        file=_make_upload("../../etc/secret.png", _png_bytes(3), "image/png"),
        uploaded_by=uploader,
    )

    # Django UploadedFile 剥掉目录组件（"anything else is dangerous"），只剩文件名
    assert doc.original_name == "secret.png"
    # 物理键为 UUID 分片，与原始文件名无关
    assert doc.storage_key.startswith("originals/")
    from apps.documents.services.files import default_storage as storage

    assert storage.exists(doc.storage_key)


# ---------------------------------------------------------------------------
# 并发 / 重复提交（security.md §4：SHA-256 唯一约束 + 事务内查重）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_content_upload_one_succeeds_one_duplicate(
    uploader: User,
    isolated_storage: LocalDiskStorage,
) -> None:
    """两个线程同时上传同一内容：一个成功，一个抛 DuplicateDocumentError。

    并发竞态由 save_upload 内的事务级 advisory 锁（键=sha256 前缀）串行化：
    后到者重查见既有记录 → DuplicateDocumentError，并清理自己已写的文件。
    transaction=True：测试数据直接提交，工作线程的独立连接才能看到
    uploader 用户（否则外层事务不可见 → FK 失败）。
    """
    content = _png_bytes(9)
    barrier = threading.Barrier(2)
    outcomes: list[Document | Exception] = []

    def _upload() -> None:
        barrier.wait()
        try:
            doc = save_upload(
                file=_make_upload("same.png", content, "image/png"),
                uploaded_by=uploader,
            )
            outcomes.append(doc)
        except Exception as exc:  # noqa: BLE001 —— 收集任意结果供断言
            outcomes.append(exc)
        finally:
            from django.db import connection

            connection.close()  # 线程连接用完即关，避免 DB teardown 报占用

    threads = [threading.Thread(target=_upload) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    docs = [o for o in outcomes if isinstance(o, Document)]
    errors = [o for o in outcomes if isinstance(o, Exception)]

    assert len(docs) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], DuplicateDocumentError)
    # 库内只有一条记录、物理原图只落一份（冲突方已清理临时文件）
    assert Document.objects.count() == 1
    assert len(_storage_files(isolated_storage)) == 1


def test_repeat_upload_post_deduplicates(
    client: Any,
    uploader: User,
) -> None:
    """同一文件两次 POST：第二次跳过入库，提示已存在（ADR-009）。"""
    client.force_login(uploader)
    content = _png_bytes(7)

    first = client.post(
        reverse("documents:upload"),
        {"files": _make_upload("a.png", content, "image/png")},
    )
    second = client.post(
        reverse("documents:upload"),
        {"files": _make_upload("b.png", content, "image/png")},
    )

    assert first.status_code == 302
    assert second.status_code == 302
    assert Document.objects.count() == 1
    follow = client.get(second.url)
    assert "已存在" in follow.content.decode()


# ---------------------------------------------------------------------------
# 中断清理（security.md §4：校验/写入失败即清理，不留残留）
# ---------------------------------------------------------------------------


def test_save_upload_failure_leaves_no_storage_residue(
    uploader: User,
    monkeypatch: pytest.MonkeyPatch,
    isolated_storage: LocalDiskStorage,
) -> None:
    """save_upload 中途（入库）抛异常 → 已写入的物理文件被清理。"""

    def _boom(*args: Any, **kwargs: Any) -> Document:
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(Document.objects, "create", _boom)

    with pytest.raises(RuntimeError):
        save_upload(
            file=_make_upload("photo.png", _png_bytes(5), "image/png"),
            uploaded_by=uploader,
        )

    # 存储根目录无任何残留文件、库内无记录
    assert _storage_files(isolated_storage) == []
    assert Document.objects.count() == 0
