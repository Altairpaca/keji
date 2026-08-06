"""T6.3 重复文件列表测试（RED 先行，规格 §9）。

按 SHA-256 分组（未删除），组内多于 1 份才视为重复；软删除文件不计入
分组；页面 200 且展示组内文件与去重建议。
"""

from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.documents.models import Document
from apps.documents.services.duplicates import find_duplicate_groups

pytestmark = pytest.mark.django_db

SAME = "abc" + "0" * 60
OTHER = "xyz" + "0" * 60


@pytest.fixture
def user() -> User:
    u = User(username="uploader", can_view_customers=True)
    u.save()
    return u


def _make_doc(user: User, suffix: str, sha256: str | None = None) -> Document:
    doc: Document = Document.objects.create(
        original_name=f"dup-{suffix}.png",
        storage_key=f"originals/ab/{suffix}",
        mime_type="image/png",
        size=1,
        sha256=sha256 or f"{suffix}{'0' * 60}",
        uploaded_by=user,
    )
    return doc

# ---------------------------------------------------------------------------
# 服务：find_duplicate_groups
# ---------------------------------------------------------------------------


def test_find_duplicate_groups_groups_by_sha256(user: User) -> None:
    _make_doc(user, "a", sha256=SAME)
    _make_doc(user, "b", sha256=SAME)
    _make_doc(user, "c", sha256=OTHER)

    groups = find_duplicate_groups()

    assert len(groups) == 1
    group = groups[0]
    assert group.sha256 == SAME
    assert group.count == 2
    assert sorted(d.original_name for d in group.docs) == ["dup-a.png", "dup-b.png"]


def test_find_duplicate_groups_empty_when_no_duplicates(user: User) -> None:
    _make_doc(user, "a", sha256=OTHER)

    assert find_duplicate_groups() == []


def test_find_duplicate_groups_excludes_soft_deleted(user: User) -> None:
    a = _make_doc(user, "a", sha256=SAME)
    b = _make_doc(user, "b", sha256=SAME)
    c = _make_doc(user, "c", sha256=SAME)

    assert len(find_duplicate_groups()) == 1

    c.soft_delete()
    assert len(find_duplicate_groups()) == 1

    b.soft_delete()
    assert find_duplicate_groups() == []

    # a 仍然存在且未删除
    assert Document.objects.filter(pk=a.pk).count() == 1


# ---------------------------------------------------------------------------
# 视图：duplicate_list
# ---------------------------------------------------------------------------


def test_duplicate_list_requires_view_permission(client: Any, user: User) -> None:
    _make_doc(user, "a", sha256=SAME)
    _make_doc(user, "b", sha256=SAME)

    assert client.get(reverse("documents:duplicate_list")).status_code == 302

    plain = User(username="plain")
    plain.save()
    client.force_login(plain)
    assert client.get(reverse("documents:duplicate_list")).status_code == 403


def test_duplicate_list_page_shows_groups(client: Any, user: User) -> None:
    client.force_login(user)
    _make_doc(user, "a", sha256=SAME)
    _make_doc(user, "b", sha256=SAME)

    response = client.get(reverse("documents:duplicate_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "重复文件" in content
    assert "dup-a.png" in content
    assert "dup-b.png" in content


def test_duplicate_list_page_excludes_soft_deleted(client: Any, user: User) -> None:
    client.force_login(user)
    _make_doc(user, "a", sha256=SAME)
    b = _make_doc(user, "b", sha256=SAME)
    b.soft_delete()

    response = client.get(reverse("documents:duplicate_list"))

    assert response.status_code == 200
    assert "没有重复文件" in response.content.decode()


def test_duplicate_list_empty_state(client: Any, user: User) -> None:
    client.force_login(user)
    _make_doc(user, "a", sha256=OTHER)

    response = client.get(reverse("documents:duplicate_list"))

    assert response.status_code == 200
    assert "没有重复文件" in response.content.decode()
