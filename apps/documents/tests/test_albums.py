"""T6.2 documents 相册服务与视图测试（RED 先行，REQ-DOC-002）。

服务：create_album（name/category 校验）、update_album（未知字段拒绝）、
soft_delete_album / restore_album、add_documents_to_album /
remove_documents_from_album（非法 pk 静默忽略）。
视图：列表（can_view_customers）、增删改（can_manage_customers）、详情网格。
"""

import uuid
from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Album, Document
from apps.documents.services.albums import (
    add_documents_to_album,
    create_album,
    remove_documents_from_album,
    restore_album,
    soft_delete_album,
    update_album,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager() -> User:
    u = User(username="album-manager", can_manage_customers=True, can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def viewer() -> User:
    u = User(username="album-viewer", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def plain() -> User:
    u = User(username="album-plain")
    u.save()
    return u


@pytest.fixture
def customer(manager: User) -> Customer:
    return create_customer(name="李娜", owner=manager, created_by=manager, age_note="约38岁")


def _make_doc(name: str = "a.pdf") -> Document:
    doc: Document = Document.objects.create(
        original_name=name,
        storage_key=f"originals/ab/{uuid.uuid4()}",
        mime_type="application/pdf",
        size=10,
        sha256=uuid.uuid4().hex,
    )
    return doc


# ---------------------------------------------------------------------------
# 服务：create_album / update_album
# ---------------------------------------------------------------------------


def test_create_album_persists(manager: User, customer: Customer) -> None:
    album = create_album(
        name="  客户证件  ",
        category="id_docs",
        customer=customer,
        description="证件拍照归档",
        created_by=manager,
    )

    assert album.name == "客户证件"
    assert album.category == "id_docs"
    assert album.customer == customer
    assert album.description == "证件拍照归档"
    assert album.created_by == manager
    assert Album.objects.filter(pk=album.pk).exists()


def test_create_album_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="相册名称不能为空"):
        create_album(name="   ")


def test_create_album_rejects_invalid_category() -> None:
    with pytest.raises(ValueError, match="类别"):
        create_album(name="未知类", category="nope")


def test_create_album_defaults_to_other() -> None:
    album = create_album(name="杂项")

    assert album.category == "other"


def test_update_album_updates_fields(manager: User) -> None:
    album = create_album(name="旧名", created_by=manager)

    updated = update_album(album, name="新名", description="新说明")

    assert updated.name == "新名"
    assert updated.description == "新说明"


def test_update_album_rejects_unknown_field() -> None:
    album = create_album(name="相册")

    with pytest.raises(ValueError, match="未知字段"):
        update_album(album, not_a_field=1)


# ---------------------------------------------------------------------------
# 服务：soft_delete / restore / 文档归置
# ---------------------------------------------------------------------------


def test_soft_delete_and_restore_album(manager: User) -> None:
    album = create_album(name="待删", created_by=manager)

    soft_delete_album(album)

    assert Album.objects.filter(pk=album.pk).count() == 0
    assert Album.all_objects.get(pk=album.pk).is_deleted is True

    restore_album(album)
    assert Album.objects.filter(pk=album.pk).count() == 1


def test_add_documents_to_album() -> None:
    album = create_album(name="理赔资料")
    doc_a, doc_b = _make_doc("a.pdf"), _make_doc("b.pdf")

    add_documents_to_album(album, [str(doc_a.pk), str(doc_b.pk)])

    assert set(album.documents.all()) == {doc_a, doc_b}


def test_add_documents_ignores_invalid_pks() -> None:
    album = create_album(name="空相册")
    doc = _make_doc()

    add_documents_to_album(
        album, [str(doc.pk), "not-a-uuid", "00000000-0000-0000-0000-000000000000"]
    )

    assert list(album.documents.all()) == [doc]


def test_remove_documents_from_album() -> None:
    album = create_album(name="混合")
    doc_a, doc_b = _make_doc("a.pdf"), _make_doc("b.pdf")
    add_documents_to_album(album, [str(doc_a.pk), str(doc_b.pk)])

    remove_documents_from_album(album, [str(doc_a.pk)])

    assert list(album.documents.all()) == [doc_b]


# ---------------------------------------------------------------------------
# 视图：列表 / 详情 / 增删改 权限矩阵
# ---------------------------------------------------------------------------


def test_album_list_permissions(client: Any, manager: User, viewer: User, plain: User) -> None:
    create_album(name="客户证件", created_by=manager)

    assert client.get(reverse("documents:album_list")).status_code == 302

    client.force_login(plain)
    assert client.get(reverse("documents:album_list")).status_code == 403

    client.force_login(viewer)
    response = client.get(reverse("documents:album_list"))
    assert response.status_code == 200
    assert "客户证件" in response.content.decode()


def test_album_list_shows_document_count(client: Any, manager: User, viewer: User) -> None:
    album = create_album(name="保单资料", created_by=manager)
    add_documents_to_album(album, [str(_make_doc().pk), str(_make_doc().pk)])

    client.force_login(viewer)
    response = client.get(reverse("documents:album_list"))
    content = response.content.decode()

    assert "保单资料" in content
    assert "2 个文件" in content


def test_album_create_requires_manage(client: Any, viewer: User, manager: User) -> None:
    client.force_login(viewer)
    assert client.get(reverse("documents:album_create")).status_code == 403

    client.force_login(manager)
    response = client.get(reverse("documents:album_create"))
    assert response.status_code == 200


def test_album_create_post(manager: User, client: Any, customer: Customer) -> None:
    client.force_login(manager)

    response = client.post(
        reverse("documents:album_create"),
        {"name": "医院资料", "category": "hospital_docs", "customer": str(customer.pk)},
    )

    assert response.status_code == 302
    album = Album.objects.get(name="医院资料")
    assert album.category == "hospital_docs"
    assert album.customer == customer
    assert album.created_by == manager


def test_album_create_post_empty_name_rerenders(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(reverse("documents:album_create"), {"name": "  "})

    assert response.status_code == 200
    assert "相册名称不能为空" in response.content.decode()
    assert Album.objects.count() == 0


def test_album_edit_post(client: Any, manager: User, viewer: User) -> None:
    album = create_album(name="旧相册", created_by=manager)

    client.force_login(viewer)
    assert client.get(reverse("documents:album_edit", args=[str(album.pk)])).status_code == 403

    client.force_login(manager)
    response = client.post(
        reverse("documents:album_edit", args=[str(album.pk)]),
        {"name": "新相册", "category": "meeting_photos", "description": "更新"},
    )

    assert response.status_code == 302
    album.refresh_from_db()
    assert album.name == "新相册"
    assert album.category == "meeting_photos"
    assert album.description == "更新"


def test_album_delete_post_soft_deletes(client: Any, manager: User, viewer: User) -> None:
    album = create_album(name="删我", created_by=manager)

    client.force_login(viewer)
    assert client.post(reverse("documents:album_delete", args=[str(album.pk)])).status_code == 403

    client.force_login(manager)
    response = client.post(reverse("documents:album_delete", args=[str(album.pk)]))

    assert response.status_code == 302
    assert response.url == reverse("documents:album_list")
    assert Album.objects.filter(pk=album.pk).count() == 0
    assert Album.all_objects.get(pk=album.pk).is_deleted is True


def test_album_detail_shows_documents_grid(client: Any, manager: User, viewer: User) -> None:
    album = create_album(name="客户证件", created_by=manager)
    doc = _make_doc("证件照.pdf")
    add_documents_to_album(album, [str(doc.pk)])

    client.force_login(viewer)
    response = client.get(reverse("documents:album_detail", args=[str(album.pk)]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "客户证件" in content
    assert "证件照.pdf" in content


def test_album_detail_permissions(client: Any, manager: User, plain: User) -> None:
    album = create_album(name="私密相册", created_by=manager)

    assert client.get(reverse("documents:album_detail", args=[str(album.pk)])).status_code == 302

    client.force_login(plain)
    assert client.get(reverse("documents:album_detail", args=[str(album.pk)])).status_code == 403
