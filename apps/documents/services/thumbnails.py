"""缩略图 / 预览派生图服务（T6.2 / ADR-002：原图与派生图分离）。

借鉴 Immich 设计：单次解码、多尺寸派生。派生图只存 webp 一种格式：
- thumb（250×250）供网格 / 列表缩略图卡片；
- preview（1440×1440）供查看器（原图超过 3MB 时降级用 preview，避免大图直出）。
键派生自原图键：``originals/<前2>/<uuid>`` → ``derived/<kind>/<前2>/<uuid>.webp``。

失败语义：非图片 / 无法解码（PIL.UnidentifiedImageError）/ 存储失败一律返回
``("", "")`` 且不抛错，doc.thumb_storage_key 保持空——列表显示类型图标，
缩略图失败绝不影响上传与查看流程。HEIC 在 pillow-heif 可导入时注册解码器。
"""

import io

from django.db.models import QuerySet
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.documents.models import Document
from apps.documents.storage import StorageError, default_storage

# pillow-heif 可选依赖：HEIC / HEIF 解码支持（缺失时这些类型无法解码 → 缩略图留空）。
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

THUMB_SIZES: dict[str, tuple[int, int]] = {
    "thumb": (250, 250),
    "preview": (1440, 1440),
}
THUMB_MIME = "image/webp"
THUMB_QUALITY = 80

# 查看器图片源阈值：原图小于该字节数直接用原图，否则生成 preview。
VIEW_ORIGINAL_LIMIT = 3 * 1024 * 1024

# PIL 解码常见异常集（UnidentifiedImageError 是 OSError/ValueError 子类，一并覆盖）。
_DECODE_ERRORS: tuple[type[BaseException], ...] = (
    UnidentifiedImageError,
    OSError,
    ValueError,
)


def _derived_key(storage_key: str, kind: str) -> str:
    """由原图键派生派生图键：``originals/<前2>/<uuid>`` → ``derived/<kind>/<前2>/<uuid>.webp``。"""
    _prefix, shard, uid = storage_key.split("/")
    return f"derived/{kind}/{shard}/{uid}.webp"


def _render_webp(doc: Document, size: tuple[int, int]) -> io.BytesIO | None:
    """解码原图 → EXIF Orientation 转正 → contain 等比缩放 → 编码 webp 内存流。

    返回可读取的内存流；非图片 / 损坏 / 解码失败返回 None（不抛错）。
    """
    try:
        with default_storage.open(doc.storage_key) as raw, Image.open(raw) as image:
            image: Image.Image = ImageOps.exif_transpose(image)
            image.thumbnail(size)
            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=THUMB_QUALITY)
    except _DECODE_ERRORS:
        return None
    buffer.seek(0)
    return buffer


def generate_thumbnail(doc: Document) -> tuple[str, str]:
    """为图片文档生成 thumb（250×250 webp），写库回填 thumb_storage_key / thumb_mime。

    - 仅处理 ``image/*`` 类型；非图片 / 解码失败 / 存储失败返回 ``("", "")``；
    - 已有缩略图时幂等：直接返回现有键；
    - 写库失败时清理已写派生文件（try/finally）。
    """
    if not doc.mime_type.startswith("image/"):
        return "", ""
    if doc.thumb_storage_key:
        return doc.thumb_storage_key, doc.thumb_mime or THUMB_MIME

    key = _derived_key(doc.storage_key, "thumb")
    buffer = _render_webp(doc, THUMB_SIZES["thumb"])
    if buffer is None:
        return "", ""
    try:
        default_storage.save(key, buffer)
        doc.thumb_storage_key = key
        doc.thumb_mime = THUMB_MIME
        doc.save(update_fields=["thumb_storage_key", "thumb_mime"])
    except (StorageError, OSError):
        # 存储 / 写库失败：清理已写派生文件，保持原图流程不受影响。
        default_storage.delete(key)
        return "", ""
    return key, THUMB_MIME


def generate_preview(doc: Document) -> tuple[str, str]:
    """为图片文档生成 preview（1440×1440 webp），供查看器大图降级。

    幂等：目标键已存在时直接返回。失败返回 ``("", "")``。
    """
    if not doc.mime_type.startswith("image/"):
        return "", ""
    key = _derived_key(doc.storage_key, "preview")
    if default_storage.exists(key):
        return key, THUMB_MIME
    buffer = _render_webp(doc, THUMB_SIZES["preview"])
    if buffer is None:
        return "", ""
    try:
        default_storage.save(key, buffer)
    except StorageError:
        default_storage.delete(key)
        return "", ""
    return key, THUMB_MIME


def resolve_view_source(doc: Document) -> tuple[str, str]:
    """查看器图片源决策：原图 <3MB 直接用原图；否则生成 / 复用 preview。

    返回 ``(storage_key, mime)``；非图片 / 无法解码返回 ``("", "")``。
    """
    if not doc.mime_type.startswith("image/"):
        return "", ""
    if doc.size < VIEW_ORIGINAL_LIMIT:
        return doc.storage_key, doc.mime_type
    key, mime = generate_preview(doc)
    if key:
        return key, mime
    return doc.storage_key, doc.mime_type  # preview 失败退回原图


def ensure_thumbnails_for_document(doc: Document) -> Document:
    """确保图片文档已有 thumb（幂等）：已有 thumb_storage_key 直接跳过。"""
    if not doc.thumb_storage_key:
        generate_thumbnail(doc)
    return doc


def generate_thumbnails_for_queryset(queryset: QuerySet) -> int:
    """批量生成缩略图，返回成功生成数量（失败静默跳过，不影响其他文档）。"""
    count = 0
    for doc in queryset.iterator():
        key, _mime = generate_thumbnail(doc)
        if key:
            count += 1
    return count
