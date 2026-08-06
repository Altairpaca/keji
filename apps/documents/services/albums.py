"""相册管理服务（T6.2/6.3，规格 §9 / REQ-DOC-002）。

相册生命周期：创建 / 更新 / 软删 / 恢复；文档归置：批量加入 / 移出相册。
视图保持薄：多写操作全部经本层，事务边界由服务函数声明（transaction.atomic）。
非法 pk（非 UUID / 不存在）静默忽略，不影响整批操作。
"""

import uuid
from collections.abc import Iterable

from django.db import transaction

from apps.customers.models import Customer
from apps.documents.models import ALBUM_CATEGORIES, Album, Document

# 合法类别集合（REQ-DOC-002 默认 10 类），create_album 校验用。
_VALID_CATEGORIES: frozenset[str] = frozenset(value for value, _label in ALBUM_CATEGORIES)


def create_album(
    *,
    name: str,
    category: str = "other",
    customer: Customer | None = None,
    description: str = "",
    created_by: object | None = None,
    **extra: object,
) -> Album:
    """创建相册：name 去首尾空白必填，category 须在默认类别内。"""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("相册名称不能为空")
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"相册类别不合法：{category}")
    with transaction.atomic():
        album: Album = Album.objects.create(
            name=cleaned_name,
            category=category,
            customer=customer,
            description=description,
            created_by=created_by,
            **extra,
        )
    return album


def update_album(album: Album, **fields: object) -> Album:
    """部分更新并保存；未知字段拒绝，避免拼写错误静默失效。"""
    for field, value in fields.items():
        if not hasattr(album, field):
            raise ValueError(f"未知字段：{field}")
        setattr(album, field, value)
    album.save()
    return album


def soft_delete_album(album: Album) -> Album:
    """软删相册（ADR-006 第 1 级）；M2M 关联保留（文档本身不删）。"""
    return album.soft_delete()


def restore_album(album: Album) -> Album:
    """恢复软删除的相册。"""
    return album.restore()


def _resolve_doc_ids(doc_pks: Iterable[uuid.UUID | str]) -> list[uuid.UUID]:
    """解析文档主键（UUID 或字符串），非法值静默忽略（避免 500）。"""
    ids: list[uuid.UUID] = []
    for pk in doc_pks:
        if isinstance(pk, uuid.UUID):
            ids.append(pk)
            continue
        try:
            ids.append(uuid.UUID(str(pk)))
        except ValueError:
            continue
    return ids


def add_documents_to_album(album: Album, doc_pks: Iterable[uuid.UUID | str]) -> int:
    """把 doc_pks 指向的未删除文档加入相册，返回实际加入数量。

    空选择返回 0；非法 pk 静默忽略。
    """
    docs = list(Document.objects.filter(pk__in=_resolve_doc_ids(doc_pks)))
    if not docs:
        return 0
    with transaction.atomic():
        for doc in docs:
            doc.albums.add(album)
    return len(docs)


def remove_documents_from_album(album: Album, doc_pks: Iterable[uuid.UUID | str]) -> int:
    """把 doc_pks 指向的文档从相册移除，返回实际移除数量。

    空选择返回 0；非法 pk 静默忽略。
    """
    docs = list(Document.objects.filter(pk__in=_resolve_doc_ids(doc_pks)))
    if not docs:
        return 0
    with transaction.atomic():
        for doc in docs:
            doc.albums.remove(album)
    return len(docs)
