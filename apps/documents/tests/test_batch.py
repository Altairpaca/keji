"""T6.3 文档批量操作测试（RED 先行，规格 §9/§10）。

服务：bulk_move_to_album / bulk_mark_important / bulk_mark_sensitive /
bulk_soft_delete 及相册归置 add/remove_documents_from_album，多行写操作
以事务包裹（服务层）。
视图：bulk_action 权限（can_manage_customers）、四种动作、JSON 计数、
空选择与无效操作防御。
"""

import json
import uuid
from typing import Any

import pytest
from django.conf import settings
from django.urls import reverse

from apps.accounts.models import User
from apps.documents.models import Album, Document
from apps.documents.services.albums import (
    add_documents_to_album,
    remove_documents_from_album,
)
from apps.documents.services.batch import (
    bulk_mark_important,
    bulk_mark_sensitive,
    bulk_move_to_album,
    bulk_soft_delete,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager() -> User:
    u = User(username="manager", can_view_customers=True, can_manage_customers=True)
    u.save()
    return u


@pytest.fixture
def viewer() -> User:
    u = User(username="viewer", can_view_customers=True)
    u.save()
    return u


def _make_doc(manager: User, suffix: str) -> Document:
    doc: Document = Document.objects.create(
        original_name=f"f-{suffix}.png",
        storage_key=f"originals/ab/{suffix}",
        mime_type="image/png",
        size=1,
        sha256=f"{suffix}{'0' * 60}",
        uploaded_by=manager,
    )
    return doc

def _make_album(name: str, category: str = "other") -> Album:
    album: Album = Album.objects.create(name=name, category=category)
    return album


# ---------------------------------------------------------------------------
# 服务：相册归置（albums）
# ---------------------------------------------------------------------------


def test_add_documents_to_album(manager: User) -> None:
    a = _make_doc(manager, "a1")
    b = _make_doc(manager, "b1")
    album = _make_album("客户证件", category="id_docs")

    count = add_documents_to_album(album, [str(a.pk), str(b.pk)])

    assert count == 2
    assert list(album.documents.order_by("original_name")) == [a, b]


def test_remove_documents_from_album(manager: User) -> None:
    a = _make_doc(manager, "a2")
    b = _make_doc(manager, "b2")
    album = _make_album("客户证件")
    album.documents.add(a, b)

    count = remove_documents_from_album(album, [str(a.pk), str(b.pk)])

    assert count == 2
    assert album.documents.count() == 0


def test_albums_ignores_invalid_pks(manager: User) -> None:
    album = _make_album("空相册")
    a = _make_doc(manager, "a2b")

    count = add_documents_to_album(
        album, [str(a.pk), "not-a-uuid", "00000000-0000-0000-0000-000000000000"]
    )

    assert count == 1
    assert list(album.documents.all()) == [a]


# ---------------------------------------------------------------------------
# 服务：batch
# ---------------------------------------------------------------------------


def test_bulk_move_to_album_relocates(manager: User) -> None:
    a = _make_doc(manager, "a3")
    b = _make_doc(manager, "b3")
    old = _make_album("旧相册")
    target = _make_album("目标相册")
    old.documents.add(a, b)

    count = bulk_move_to_album([a.pk, b.pk], target.pk)

    assert count == 2
    assert old.documents.count() == 0
    assert list(target.documents.order_by("original_name")) == [a, b]


def test_bulk_move_to_album_unknown_album_raises(manager: User) -> None:
    a = _make_doc(manager, "a4")

    with pytest.raises(Album.DoesNotExist):
        bulk_move_to_album([a.pk], uuid.uuid4())


def test_bulk_mark_important_sets_and_clears(manager: User) -> None:
    a = _make_doc(manager, "a5")
    b = _make_doc(manager, "b5")

    assert bulk_mark_important([a.pk, b.pk], True) == 2
    assert Document.objects.get(pk=a.pk).is_important is True
    assert Document.objects.get(pk=b.pk).is_important is True

    assert bulk_mark_important([a.pk], False) == 1
    assert Document.objects.get(pk=a.pk).is_important is False


def test_bulk_mark_sensitive_sets_and_clears(manager: User) -> None:
    a = _make_doc(manager, "a6")

    assert bulk_mark_sensitive([a.pk], "sensitive") == 1
    assert Document.objects.get(pk=a.pk).sensitivity == "sensitive"

    assert bulk_mark_sensitive([a.pk], "normal") == 1
    assert Document.objects.get(pk=a.pk).sensitivity == "normal"


def test_bulk_mark_sensitive_invalid_value_raises(manager: User) -> None:
    a = _make_doc(manager, "a7")

    with pytest.raises(ValueError):
        bulk_mark_sensitive([a.pk], "top_secret")


def test_bulk_soft_delete(manager: User) -> None:
    a = _make_doc(manager, "a8")
    b = _make_doc(manager, "b8")

    count = bulk_soft_delete([a.pk, b.pk])

    assert count == 2
    assert Document.objects.count() == 0
    assert Document.all_objects.filter(pk__in=[a.pk, b.pk], is_deleted=True).count() == 2


def test_bulk_empty_selection_returns_zero(manager: User) -> None:
    assert bulk_mark_important([], True) == 0
    assert bulk_soft_delete([]) == 0
    assert bulk_mark_sensitive([], "sensitive") == 0


# ---------------------------------------------------------------------------
# 视图：权限
# ---------------------------------------------------------------------------


def test_bulk_action_anonymous_redirects(client: Any) -> None:
    response = client.post(reverse("documents:bulk_action"), {"action": "delete"})

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_bulk_action_requires_manage_permission(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "delete", "doc_pks": [str(uuid.uuid4())]},
    )

    assert response.status_code == 403


def test_bulk_action_get_not_allowed(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.get(reverse("documents:bulk_action"))

    assert response.status_code == 405


# ---------------------------------------------------------------------------
# 视图：四种动作
# ---------------------------------------------------------------------------


def test_bulk_action_delete(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "vd1")
    b = _make_doc(manager, "vd2")

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "delete", "doc_pks": [str(a.pk), str(b.pk)]},
    )

    assert response.status_code == 302
    assert Document.objects.count() == 0
    assert Document.all_objects.filter(is_deleted=True).count() == 2
    follow = client.get(response.url)
    assert "已处理 2 个文件" in follow.content.decode()


def test_bulk_action_mark_important(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "vi1")

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "important", "value": "1", "doc_pks": [str(a.pk)]},
    )

    assert response.status_code == 302
    assert Document.objects.get(pk=a.pk).is_important is True


def test_bulk_action_mark_sensitive(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "vs1")

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "sensitive", "value": "sensitive", "doc_pks": [str(a.pk)]},
    )

    assert response.status_code == 302
    assert Document.objects.get(pk=a.pk).sensitivity == "sensitive"


def test_bulk_action_move_to_album(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "vm1")
    old = _make_album("旧相册")
    target = _make_album("新相册")
    old.documents.add(a)

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "album", "target_album": str(target.pk), "doc_pks": [str(a.pk)]},
    )

    assert response.status_code == 302
    assert old.documents.count() == 0
    assert target.documents.filter(pk=a.pk).count() == 1


def test_bulk_action_json_count(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "vj1")

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "important", "value": "1", "doc_pks": [str(a.pk)], "format": "json"},
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert json.loads(response.content) == {"count": 1}


# ---------------------------------------------------------------------------
# 视图：防御
# ---------------------------------------------------------------------------


def test_bulk_action_no_selection_warns(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(reverse("documents:bulk_action"), {"action": "delete"})

    assert response.status_code == 302
    follow = client.get(response.url)
    assert "未选择文件" in follow.content.decode()


def test_bulk_action_unknown_action_errors(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "vu1")

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "explode", "doc_pks": [str(a.pk)]},
    )

    assert response.status_code == 302
    follow = client.get(response.url)
    assert "不支持的操作" in follow.content.decode()


def test_bulk_action_album_without_target_errors(client: Any, manager: User) -> None:
    client.force_login(manager)
    a = _make_doc(manager, "va1")

    response = client.post(
        reverse("documents:bulk_action"),
        {"action": "album", "doc_pks": [str(a.pk)]},
    )

    assert response.status_code == 302
    follow = client.get(response.url)
    assert "请选择目标相册" in follow.content.decode()
