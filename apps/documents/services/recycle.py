"""documents 回收站服务（T6.4，规格 §18 / ADR-006 三级删除协议）。

第 1 级软删 / 第 2 级恢复由 ``SoftDeleteModel`` 与 ``files.restore_document`` 承担；
本模块实现第 3 级（管理员永久删除）与 GC 批量清理：

- ``list_trashed_documents``：回收站列表（all_objects 中 is_deleted=True）；
- ``permanent_delete_document``：事务内删物理文件（原图 + 缩略图）再真删 DB 记录；
- ``empty_trash``：批量永久删除超过 ``before_days`` 天未恢复的已删文档（GC）。

存储删除失败时整笔事务回滚，不留「记录没了但文件还在 / 文件没了但记录还在」
的半状态。
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.documents.models import Document
from apps.documents.storage import default_storage

#: 默认回收站保留天数：超过此天数且未恢复的已删文档由 GC 命令批量清理。
DEFAULT_RETENTION_DAYS = 30


def list_trashed_documents() -> QuerySet[Document]:
    """返回回收站中的已删文档（按删除时间倒序，最新删除在前）。"""
    return Document.all_objects.filter(is_deleted=True).order_by("-deleted_at")


def _record_audit(event_type: str, *, document: Document, actor: object | None) -> None:
    """审计钩子（T10.2 接入 audit app 前为 stub）。

    规格 §18 要求永久删除留痕。audit app 尚未建模，此处仅占位：
    后续由 apps/audit/services.py 的 ``record_audit`` 替换实现。
    """
    # TODO(T10.2): 接入 apps.audit 审计日志后，在此落一条
    #  `event_type="document.permanent_delete", actor, metadata={"storage_key": ...}`。
    del event_type, document, actor


def permanent_delete_document(doc: Document, *, actor: object | None = None) -> dict[str, int]:
    """永久删除单个已删文档（ADR-006 第 3 级，管理员触发）。

    事务内：先删原图物理文件，再删缩略图物理文件，最后真删 DB 记录。
    任一物理删除抛错则整体回滚，DB 记录与文件保持一致。
    返回 ``{"rows_deleted": n, "files_deleted": n}`` 统计。
    """
    storage_key = doc.storage_key
    thumb_key = doc.thumb_storage_key
    with transaction.atomic():
        _record_audit("document.permanent_delete", document=doc, actor=actor)
        files_deleted = 0
        if default_storage.exists(storage_key):
            default_storage.delete(storage_key)
            files_deleted += 1
        if thumb_key and default_storage.exists(thumb_key):
            default_storage.delete(thumb_key)
            files_deleted += 1
        rows_deleted = doc.delete(force=True)[0]
    return {"rows_deleted": rows_deleted, "files_deleted": files_deleted}


def empty_trash(
    *,
    before_days: int = DEFAULT_RETENTION_DAYS,
    actor: object | None = None,
) -> dict[str, int]:
    """GC：批量永久删除超过 ``before_days`` 天未恢复的已删文档。

    - ``before_days=0`` 清空回收站全部内容；
    - 单个文档永久删除失败（存储异常）不影响其他文档继续处理；
    - 返回 ``{"rows_deleted": n, "files_deleted": n}`` 全量统计。
    """
    cutoff = timezone.now() - timedelta(days=before_days)
    trashed = list_trashed_documents().filter(deleted_at__lt=cutoff)
    stats = {"rows_deleted": 0, "files_deleted": 0}
    for doc in trashed:
        try:
            one = permanent_delete_document(doc, actor=actor)
        except Exception:
            # 单文档清理失败：跳过继续，避免一条坏文件阻塞整批 GC。
            continue
        stats["rows_deleted"] += one["rows_deleted"]
        stats["files_deleted"] += one["files_deleted"]
    return stats
