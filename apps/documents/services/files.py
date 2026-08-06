"""documents 上传服务（T6.1，规格 §9/§10 + docs/security.md §4）。

上传路径强制执行：大小上限 → 扩展名白名单 → 声明 MIME 与扩展名一致 →
魔数（文件头签名）校验，全过才入库。SHA-256 按 1MB 分块流式计算，不整载
内存（规格 §25）；写库前查重，重复抛 ``DuplicateDocumentError``。
"""

import hashlib
from collections.abc import Iterable
from typing import BinaryIO

from django.conf import settings
from django.db import transaction

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.documents.models import Album, Document
from apps.documents.storage import default_storage, new_storage_key

# 单文件大小上限（默认 100MB，settings.DOCUMENT_MAX_UPLOAD_SIZE 可覆盖）。
MAX_SIZE: int = getattr(settings, "DOCUMENT_MAX_UPLOAD_SIZE", 100 * 1024 * 1024)

CHUNK_SIZE = 1024 * 1024  # 1MB：流式哈希 / 写盘分块，避免整载内存

# 类型白名单（security.md §4）：MIME → 允许的扩展名集合。
MIME_WHITELIST: dict[str, tuple[str, ...]] = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/gif": (".gif",),
    "image/webp": (".webp",),
    "image/heic": (".heic",),
    "image/heif": (".heif",),
    "application/pdf": (".pdf",),
    "application/msword": (".doc",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
    "application/vnd.ms-excel": (".xls",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx",),
    "application/vnd.ms-powerpoint": (".ppt",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (".pptx",),
    "text/csv": (".csv",),
    "video/mp4": (".mp4",),
    "video/quicktime": (".mov",),
    "audio/mpeg": (".mp3",),
    "audio/mp4": (".m4a",),
}

# 压缩包（zip/rar/7z）不在白名单：spec §10 压缩炸弹风险，拒绝上传。
_OFFICE_ZIP_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)
_HEIC_BRANDS = frozenset({"heic", "heix", "heif", "heim", "hevc", "hevx", "mif1", "msf1"})


class DuplicateDocumentError(Exception):
    """同一内容（同 SHA-256）且未删除的文件已存在，跳过重复入库。"""

    def __init__(self, document: Document) -> None:
        self.document = document
        super().__init__(f"文件已存在：{document.original_name}（SHA-256 {document.sha256}）")


def _magic_matches(content_type: str, head: bytes) -> bool:
    """按文件头签名核对真实类型（不信任声明 Content-Type，security.md §4）。"""
    if content_type == "image/jpeg":
        return head[:3] == b"\xff\xd8\xff"
    if content_type == "image/png":
        return head[:8] == b"\x89PNG\r\n\x1a\n"
    if content_type == "image/gif":
        return head[:4] in (b"GIF87a", b"GIF89a")
    if content_type == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if content_type in ("image/heic", "image/heif"):
        brand = head[8:12].decode("latin-1")
        return head[4:8] == b"ftyp" and brand in _HEIC_BRANDS
    if content_type == "application/pdf":
        return head[:4] == b"%PDF"
    if content_type in _OFFICE_ZIP_TYPES:
        return head[:4] == b"PK\x03\x04"
    if content_type == "text/csv":
        return True  # 无可靠魔数，仅扩展名白名单约束
    if content_type in ("video/mp4", "video/quicktime"):
        return head[4:8] == b"ftyp"
    if content_type == "audio/mpeg":
        return head[:3] == b"ID3" or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
    if content_type == "audio/mp4":
        return head[4:8] == b"ftyp" and head[8:12] == b"M4A "
    return False


def validate_upload(file: BinaryIO) -> tuple[str, int]:
    """校验上传文件，返回 (content_type, size)。

    顺序：大小超限 → 扩展名白名单 → 声明 MIME 与扩展名一致 → 魔数。
    任一不满足抛 ``ValueError``；魔数不符统一报「文件类型与扩展名不符」。
    校验前后把流位置复位，便于调用方接着读取。
    """
    size = getattr(file, "size", None)
    if size is None:
        file.seek(0)
        size = 0
        while chunk := file.read(CHUNK_SIZE):
            size += len(chunk)
    if size > MAX_SIZE:
        raise ValueError(f"文件超过大小限制（上限 {MAX_SIZE} 字节）")

    original_name = getattr(file, "name", "") or ""
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    declared = (getattr(file, "content_type", "") or "").lower()
    allowed_mimes = [mime for mime, exts in MIME_WHITELIST.items() if f".{ext}" in exts]
    if not allowed_mimes:
        raise ValueError("不支持的文件类型")
    if declared not in allowed_mimes:
        raise ValueError("文件类型与扩展名不符")

    file.seek(0)
    head = file.read(12)
    file.seek(0)
    if not _magic_matches(declared, head):
        raise ValueError("文件类型与扩展名不符")
    return declared, size


def _hash_stream(file: BinaryIO) -> str:
    """流式计算 SHA-256（1MB 分块），返回后复位流位置。"""
    digest = hashlib.sha256()
    file.seek(0)
    while chunk := file.read(CHUNK_SIZE):
        digest.update(chunk)
    file.seek(0)
    return digest.hexdigest()


def save_upload(
    *,
    file: BinaryIO,
    uploaded_by: User,
    title: str = "",
    note: str = "",
    sensitivity: str = "normal",
    customers: Iterable[Customer] | None = None,
    albums: Iterable[Album] | None = None,
    source: str = "",
) -> Document:
    """校验并落盘上传文件，建 Document 记录（规格 §9 / REQ-DOC-001）。

    流程：校验 → 流式 sha256 → 查重（同 sha256 且未删除 → 抛
    ``DuplicateDocumentError``）→ 写存储 → 事务内建记录与 M2M 关联。
    DB 写失败时清理已写文件，不留残留（security.md §4 临时文件清理）。
    """
    content_type, size = validate_upload(file)
    sha256 = _hash_stream(file)
    existing: Document | None = Document.objects.filter(sha256=sha256).first()
    if existing is not None:
        raise DuplicateDocumentError(existing)

    original_name = (getattr(file, "name", "") or "未命名文件")[:255]
    key = new_storage_key()
    file.seek(0)
    default_storage.save(key, file)

    try:
        with transaction.atomic():
            doc: Document = Document.objects.create(
                original_name=original_name,
                storage_key=key,
                mime_type=content_type,
                size=size,
                sha256=sha256,
                title=title.strip(),
                note=note,
                sensitivity=sensitivity,
                source=source,
                uploaded_by=uploaded_by,
            )
            if customers:
                doc.customers.set(customers)
            if albums:
                doc.albums.set(albums)
        return doc
    except BaseException:
        default_storage.delete(key)
        raise


def soft_delete_document(doc: Document) -> Document:
    """软删文件（ADR-006 第 1 级）：物理文件不动，回收站清理留待 T6.4。"""
    return doc.soft_delete()


def restore_document(doc: Document) -> Document:
    """恢复软删除的文件。"""
    return doc.restore()
