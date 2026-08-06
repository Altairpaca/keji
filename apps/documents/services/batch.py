"""文档批量操作服务（T6.3，规格 §9/§10）。

视图只做参数解析，业务与事务边界在本层：涉及多行写操作一律
``transaction.atomic()``。统一返回实际处理数量，空选择返回 0。
"""

import uuid
from collections.abc import Iterable

from django.db import transaction

from apps.documents.models import Album, Document


def bulk_move_to_album(doc_pks: Iterable[uuid.UUID], album_pk: uuid.UUID) -> int:
    """把一组文档移动到目标相册（清空原相册归属后加入），返回处理数量。

    「移动」语义：目标相册成为唯一归属相册。相册不存在抛
    ``Album.DoesNotExist``；空选择返回 0。
    """
    docs = list(Document.objects.filter(pk__in=list(doc_pks)))
    if not docs:
        return 0
    album = Album.objects.get(pk=album_pk)
    with transaction.atomic():
        for doc in docs:
            doc.albums.set([album])
    return len(docs)


def bulk_mark_important(doc_pks: Iterable[uuid.UUID], value: bool) -> int:
    """批量设置 / 取消重要标记，返回处理数量。"""
    docs = list(Document.objects.filter(pk__in=list(doc_pks)))
    if not docs:
        return 0
    with transaction.atomic():
        Document.objects.filter(pk__in=[d.pk for d in docs]).update(is_important=value)
    return len(docs)


def bulk_mark_sensitive(doc_pks: Iterable[uuid.UUID], value: str) -> int:
    """批量设置敏感级别（normal / sensitive / highly_sensitive）。

    非法级别抛 ``ValueError``；级别为 normal 即取消敏感标记。
    """
    if value not in Document.Sensitivity.values:
        raise ValueError("无效的敏感级别")
    docs = list(Document.objects.filter(pk__in=list(doc_pks)))
    if not docs:
        return 0
    with transaction.atomic():
        Document.objects.filter(pk__in=[d.pk for d in docs]).update(sensitivity=value)
    return len(docs)


def bulk_soft_delete(doc_pks: Iterable[uuid.UUID]) -> int:
    """批量软删文件（ADR-006 第 1 级），物理文件不动，返回处理数量。"""
    docs = list(Document.objects.filter(pk__in=list(doc_pks)))
    if not docs:
        return 0
    with transaction.atomic():
        for doc in docs:
            doc.soft_delete()
    return len(docs)
