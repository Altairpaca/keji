"""T6.4 回收站测试（RED 先行，规格 §18 / ADR-006 三级删除协议）。

服务：list_trashed_documents / permanent_delete_document（事务内删物理文件
+ DB 记录）/ empty_trash（仅清超过 before_days 的已删文档）。
视图：trash_list 列表（can_view_customers）、trash_restore（can_manage_customers）、
trash_permanent_delete / trash_empty（can_permanent_delete）权限矩阵。
管理命令：empty_trash 可执行并清理过期已删文档。
"""

import uuid
from datetime import timedelta
from io import BytesIO
from typing import Any

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.documents.models import Document
from apps.documents.services import restore_document, save_upload, soft_delete_document
from apps.documents.services.recycle import (
    empty_trash,
    list_trashed_documents,
    permanent_delete_document,
)
from apps.documents.storage import LocalDiskStorage
from apps.documents.tests.test_upload import _make_upload, _png_bytes

pytestmark = pytest.mark.django_db


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
def manager() -> User:
    u = User(
        username="manager",
        can_view_customers=True,
        can_manage_customers=True,
        can_permanent_delete=True,
    )
    u.save()
    return u


def _upload_deleted(uploader: User, name: str = "trash.png") -> Document:
    """上传一个真实文件并软删，模拟进入回收站。"""
    doc = save_upload(file=_make_upload(name, _png_bytes(), "image/png"), uploaded_by=uploader)
    soft_delete_document(doc)
    return doc


def _make_thumb(doc: Document, backend: LocalDiskStorage) -> str:
    """为文档造一张缩略图物理文件与 thumb_storage_key。"""
    thumb_key = f"thumbs/ab/{uuid.uuid4()}"
    backend.save(thumb_key, BytesIO(b"thumb-bytes"))
    doc.thumb_storage_key = thumb_key
    doc.save(update_fields=["thumb_storage_key"])
    return thumb_key


# ---------------------------------------------------------------------------
# 服务：list_trashed_documents
# ---------------------------------------------------------------------------


def test_list_trashed_only_returns_deleted(uploader: User) -> None:
    alive = save_upload(
        file=_make_upload("alive.png", _png_bytes(1), "image/png"), uploaded_by=uploader
    )
    trashed = _upload_deleted(uploader)

    result = list_trashed_documents()

    pks = [doc.pk for doc in result]
    assert trashed.pk in pks
    assert alive.pk not in pks
    assert all(doc.is_deleted for doc in result)


def test_soft_deleted_hidden_from_objects_visible_in_all_objects(uploader: User) -> None:
    doc = _upload_deleted(uploader)

    assert Document.objects.filter(pk=doc.pk).count() == 0
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True


def test_restore_brings_doc_back(uploader: User) -> None:
    doc = _upload_deleted(uploader)

    restore_document(doc)

    assert Document.objects.filter(pk=doc.pk).count() == 1
    assert Document.all_objects.get(pk=doc.pk).is_deleted is False
    assert list_trashed_documents().filter(pk=doc.pk).count() == 0


# ---------------------------------------------------------------------------
# 服务：permanent_delete_document
# ---------------------------------------------------------------------------


def test_permanent_delete_removes_row_and_physical_file(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = _upload_deleted(uploader)
    assert isolated_storage.exists(doc.storage_key)

    stats = permanent_delete_document(doc)

    assert stats == {"rows_deleted": 1, "files_deleted": 1}
    assert Document.all_objects.filter(pk=doc.pk).count() == 0
    assert isolated_storage.exists(doc.storage_key) is False


def test_permanent_delete_also_removes_thumbnail(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = _upload_deleted(uploader)
    _make_thumb(doc, isolated_storage)
    assert isolated_storage.exists(doc.thumb_storage_key)

    stats = permanent_delete_document(doc)

    assert stats == {"rows_deleted": 1, "files_deleted": 2}
    assert isolated_storage.exists(doc.storage_key) is False
    assert isolated_storage.exists(doc.thumb_storage_key) is False


def test_permanent_delete_ignores_missing_original_file(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = _upload_deleted(uploader)
    isolated_storage.delete(doc.storage_key)  # 物理文件已丢，仍应正常清 DB

    stats = permanent_delete_document(doc)

    assert stats == {"rows_deleted": 1, "files_deleted": 0}
    assert Document.all_objects.filter(pk=doc.pk).count() == 0


def test_permanent_delete_is_transactional_on_storage_failure(
    uploader: User, isolated_storage: LocalDiskStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """物理文件删除抛错时：DB 记录与审计整体回滚，文档仍在回收站可重试。"""
    doc = _upload_deleted(uploader)
    _make_thumb(doc, isolated_storage)

    def boom(key: str) -> None:
        if key == doc.thumb_storage_key:
            raise RuntimeError("storage boom")
        isolated_storage.delete(key)

    monkeypatch.setattr(isolated_storage, "delete", boom)

    with pytest.raises(RuntimeError):
        permanent_delete_document(doc)

    # 事务回滚：DB 记录仍在回收站（审计 + 真删一起原子化）
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True


# ---------------------------------------------------------------------------
# 服务：empty_trash
# ---------------------------------------------------------------------------


def test_empty_trash_only_purges_older_than_before_days(uploader: User) -> None:
    recent = _upload_deleted(uploader)
    old = _upload_deleted(uploader, name="old.png")
    Document.all_objects.filter(pk=old.pk).update(deleted_at=timezone.now() - timedelta(days=45))

    stats = empty_trash(before_days=30)

    assert stats == {"rows_deleted": 1, "files_deleted": 1}
    assert Document.all_objects.filter(pk=old.pk).count() == 0
    assert Document.all_objects.get(pk=recent.pk).is_deleted is True  # 30 天内不动


def test_empty_trash_before_days_zero_clears_all(
    uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = _upload_deleted(uploader)

    stats = empty_trash(before_days=0)

    assert stats == {"rows_deleted": 1, "files_deleted": 1}
    assert Document.all_objects.filter(pk=doc.pk).count() == 0
    assert isolated_storage.exists(doc.storage_key) is False


def test_empty_trash_skips_active_documents(uploader: User) -> None:
    alive = save_upload(
        file=_make_upload("alive.png", _png_bytes(), "image/png"), uploaded_by=uploader
    )

    stats = empty_trash(before_days=0)

    assert stats == {"rows_deleted": 0, "files_deleted": 0}
    assert Document.objects.get(pk=alive.pk).is_deleted is False


# ---------------------------------------------------------------------------
# 视图：trash_list
# ---------------------------------------------------------------------------


def test_trash_list_requires_view_permission(
    client: Any, viewer: User, plain: User, uploader: User
) -> None:
    _upload_deleted(uploader)

    assert client.get(reverse("documents:trash_list")).status_code == 302  # 未登录

    client.force_login(plain)
    assert client.get(reverse("documents:trash_list")).status_code == 403

    client.force_login(viewer)
    response = client.get(reverse("documents:trash_list"))
    assert response.status_code == 200


def test_trash_list_shows_deleted_docs_and_actions(
    client: Any, manager: User, uploader: User
) -> None:
    doc = _upload_deleted(uploader, name="甲证.png")

    client.force_login(manager)
    content = client.get(reverse("documents:trash_list")).content.decode()

    assert "甲证.png" in content
    assert reverse("documents:trash_restore", args=[str(doc.pk)]) in content
    assert reverse("documents:trash_permanent_delete", args=[str(doc.pk)]) in content
    assert reverse("documents:trash_empty") in content


def test_trash_list_hides_actions_without_permission(
    client: Any, viewer: User, uploader: User
) -> None:
    _upload_deleted(uploader, name="乙证.png")

    client.force_login(viewer)
    content = client.get(reverse("documents:trash_list")).content.decode()

    assert "乙证.png" in content
    assert reverse("documents:trash_empty") not in content


def test_trash_list_hides_active_docs(client: Any, viewer: User, uploader: User) -> None:
    save_upload(file=_make_upload("alive.png", _png_bytes(), "image/png"), uploaded_by=uploader)

    client.force_login(viewer)
    content = client.get(reverse("documents:trash_list")).content.decode()

    assert "alive.png" not in content


# ---------------------------------------------------------------------------
# 视图：trash_restore
# ---------------------------------------------------------------------------


def test_trash_restore_requires_manage_permission(
    client: Any, viewer: User, uploader: User
) -> None:
    doc = _upload_deleted(uploader)

    client.force_login(viewer)
    response = client.post(reverse("documents:trash_restore", args=[str(doc.pk)]))
    assert response.status_code == 403
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True


def test_trash_restore_restores_and_redirects(client: Any, manager: User, uploader: User) -> None:
    doc = _upload_deleted(uploader)

    client.force_login(manager)
    response = client.post(reverse("documents:trash_restore", args=[str(doc.pk)]))

    assert response.status_code == 302
    assert Document.objects.get(pk=doc.pk).is_deleted is False


def test_trash_restore_get_method_not_allowed(client: Any, manager: User, uploader: User) -> None:
    doc = _upload_deleted(uploader)

    client.force_login(manager)
    assert client.get(reverse("documents:trash_restore", args=[str(doc.pk)])).status_code == 405


def test_trash_restore_unknown_pk_404(client: Any, manager: User) -> None:
    client.force_login(manager)
    assert (
        client.post(reverse("documents:trash_restore", args=[str(uuid.uuid4())])).status_code == 404
    )


# ---------------------------------------------------------------------------
# 视图：trash_permanent_delete
# ---------------------------------------------------------------------------


def test_trash_permanent_delete_requires_bit(
    client: Any, manager: User, viewer: User, uploader: User
) -> None:
    doc = _upload_deleted(uploader)

    client.force_login(viewer)
    response = client.post(reverse("documents:trash_permanent_delete", args=[str(doc.pk)]))
    assert response.status_code == 403
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True

    client.force_login(manager)
    response = client.post(reverse("documents:trash_permanent_delete", args=[str(doc.pk)]))
    assert response.status_code == 302
    assert Document.all_objects.filter(pk=doc.pk).count() == 0


def test_trash_permanent_delete_removes_file(
    client: Any, manager: User, uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = _upload_deleted(uploader)
    assert isolated_storage.exists(doc.storage_key)

    client.force_login(manager)
    response = client.post(reverse("documents:trash_permanent_delete", args=[str(doc.pk)]))

    assert response.status_code == 302
    assert isolated_storage.exists(doc.storage_key) is False


# ---------------------------------------------------------------------------
# 视图：trash_empty
# ---------------------------------------------------------------------------


def test_trash_empty_requires_bit(
    client: Any, manager: User, viewer: User, uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    doc = _upload_deleted(uploader)

    client.force_login(viewer)
    response = client.post(reverse("documents:trash_empty"))
    assert response.status_code == 403
    assert Document.all_objects.get(pk=doc.pk).is_deleted is True
    assert isolated_storage.exists(doc.storage_key)

    client.force_login(manager)
    response = client.post(reverse("documents:trash_empty"))
    assert response.status_code == 302
    assert Document.all_objects.filter(pk=doc.pk).count() == 0
    assert isolated_storage.exists(doc.storage_key) is False


def test_trash_empty_clears_all_deleted(
    client: Any, manager: User, uploader: User, isolated_storage: LocalDiskStorage
) -> None:
    docs = [_upload_deleted(uploader, name=f"t{i}.png") for i in range(3)]
    assert all(isolated_storage.exists(doc.storage_key) for doc in docs)

    client.force_login(manager)
    response = client.post(reverse("documents:trash_empty"))

    assert response.status_code == 302
    assert Document.all_objects.filter(is_deleted=True).count() == 0
    assert all(not isolated_storage.exists(doc.storage_key) for doc in docs)


# ---------------------------------------------------------------------------
# 管理命令
# ---------------------------------------------------------------------------


def test_empty_trash_command_purges_expired(uploader: User) -> None:
    old = _upload_deleted(uploader, name="old.png")
    Document.all_objects.filter(pk=old.pk).update(deleted_at=timezone.now() - timedelta(days=45))
    recent = _upload_deleted(uploader, name="recent.png")

    call_command("empty_trash")

    assert Document.all_objects.filter(pk=old.pk).count() == 0
    assert Document.all_objects.get(pk=recent.pk).is_deleted is True


def test_empty_trash_command_outputs_stats(capsys: Any, uploader: User) -> None:
    _upload_deleted(uploader)

    call_command("empty_trash", before_days=0)

    out = capsys.readouterr().out
    assert "1" in out
