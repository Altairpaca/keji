"""T6.3 敏感文件模糊展示测试（RED 先行，规格 §9/§10 + security.md 权限矩阵）。

覆盖：can_view_sensitive_doc / masked_thumbnail_url 服务层判定、
sensitive_blur_enabled 系统开关、文档网格与详情页的模糊展示。
敏感判定在服务端完成（视图传入上下文），模板只消费结果。
"""

from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.core.services.settings import set_setting
from apps.documents.models import Document
from apps.documents.services.sensitive import (
    BLUR_SETTING_DEFAULT,
    BLUR_SETTING_KEY,
    can_view_sensitive_doc,
    is_blur_enabled,
    masked_thumbnail_url,
    sensitive_context,
)

pytestmark = pytest.mark.django_db

MASK_TEXT = "无查看敏感资料权限"


def _make_doc(uploader: User, sensitivity: str = "sensitive", suffix: str = "a") -> Document:
    """直接建 Document（不落盘，模糊判定只依赖元数据）。"""
    doc: Document = Document.objects.create(
        original_name=f"{suffix}.png",
        storage_key=f"originals/ab/{suffix}",
        mime_type="image/png",
        size=1024,
        sha256=f"{suffix}{'0' * 60}",
        uploaded_by=uploader,
        sensitivity=sensitivity,
    )
    return doc


@pytest.fixture
def uploader() -> User:
    u = User(
        username="uploader",
        can_view_customers=True,
        can_manage_customers=True,
        can_view_sensitive=True,
    )
    u.save()
    return u


@pytest.fixture
def viewer() -> User:
    u = User(username="viewer", can_view_customers=True)
    u.save()
    return u


# ---------------------------------------------------------------------------
# 服务：权限判定
# ---------------------------------------------------------------------------


def test_can_view_sensitive_doc_normal_always_true(viewer: User, uploader: User) -> None:
    doc = _make_doc(uploader, sensitivity="normal", suffix="n1")

    assert can_view_sensitive_doc(viewer, doc) is True


def test_can_view_sensitive_doc_sensitive_requires_permission(viewer: User, uploader: User) -> None:
    doc = _make_doc(uploader, sensitivity="sensitive", suffix="s1")

    assert can_view_sensitive_doc(viewer, doc) is False
    assert can_view_sensitive_doc(uploader, doc) is True


def test_can_view_sensitive_doc_highly_sensitive_requires_permission(
    viewer: User, uploader: User
) -> None:
    doc = _make_doc(uploader, sensitivity="highly_sensitive", suffix="h1")

    assert can_view_sensitive_doc(viewer, doc) is False


# ---------------------------------------------------------------------------
# 服务：masked_thumbnail_url
# ---------------------------------------------------------------------------


def test_masked_thumbnail_url_masked_without_permission(viewer: User, uploader: User) -> None:
    doc = _make_doc(uploader, sensitivity="sensitive", suffix="m1")

    assert masked_thumbnail_url(doc, viewer) is None


def test_masked_thumbnail_url_with_permission_returns_key(uploader: User) -> None:
    doc = _make_doc(uploader, sensitivity="sensitive", suffix="p1")

    assert masked_thumbnail_url(doc, uploader) == doc.thumb_storage_key


def test_masked_thumbnail_url_normal_never_masked(viewer: User, uploader: User) -> None:
    doc = _make_doc(uploader, sensitivity="normal", suffix="n2")

    assert masked_thumbnail_url(doc, viewer) == doc.thumb_storage_key


def test_masked_thumbnail_url_blur_disabled_shows_directly(viewer: User, uploader: User) -> None:
    set_setting(BLUR_SETTING_KEY, "false", label="敏感模糊")
    doc = _make_doc(uploader, sensitivity="sensitive", suffix="b1")

    assert masked_thumbnail_url(doc, viewer) == doc.thumb_storage_key


def test_is_blur_enabled_default_and_switchable() -> None:
    set_setting(BLUR_SETTING_KEY, BLUR_SETTING_DEFAULT, label="敏感模糊")

    assert is_blur_enabled() is True

    set_setting(BLUR_SETTING_KEY, "false", label="敏感模糊")

    assert is_blur_enabled() is False


def test_sensitive_context_flags(viewer: User, uploader: User) -> None:
    set_setting(BLUR_SETTING_KEY, "true", label="敏感模糊")

    assert sensitive_context(viewer) == {
        "can_view_sensitive": False,
        "sensitive_blur_enabled": True,
    }
    assert sensitive_context(uploader)["can_view_sensitive"] is True


# ---------------------------------------------------------------------------
# 视图：文档网格模糊
# ---------------------------------------------------------------------------


def test_document_list_masks_sensitive_for_viewer(
    client: Any, viewer: User, uploader: User
) -> None:
    set_setting(BLUR_SETTING_KEY, "true", label="敏感模糊")
    client.force_login(viewer)
    _make_doc(uploader, sensitivity="sensitive", suffix="sec")
    _make_doc(uploader, sensitivity="normal", suffix="nor")

    response = client.get(reverse("documents:document_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "blur-sm" in content
    assert MASK_TEXT in content
    assert "sec.png" in content
    assert "nor.png" in content


def test_document_list_shows_sensitive_to_privileged_user(client: Any, uploader: User) -> None:
    set_setting(BLUR_SETTING_KEY, "true", label="敏感模糊")
    client.force_login(uploader)
    _make_doc(uploader, sensitivity="sensitive", suffix="sec2")

    response = client.get(reverse("documents:document_list"))

    assert response.status_code == 200
    assert "blur-sm" not in response.content.decode()


def test_document_list_no_blur_when_setting_disabled(
    client: Any, viewer: User, uploader: User
) -> None:
    set_setting(BLUR_SETTING_KEY, "false", label="敏感模糊")
    client.force_login(viewer)
    _make_doc(uploader, sensitivity="sensitive", suffix="sec3")

    response = client.get(reverse("documents:document_list"))

    assert response.status_code == 200
    assert "blur-sm" not in response.content.decode()


# ---------------------------------------------------------------------------
# 视图：详情页模糊
# ---------------------------------------------------------------------------


def test_document_detail_masked_for_viewer(client: Any, viewer: User, uploader: User) -> None:
    set_setting(BLUR_SETTING_KEY, "true", label="敏感模糊")
    client.force_login(viewer)
    doc = _make_doc(uploader, sensitivity="sensitive", suffix="sec4")

    response = client.get(reverse("documents:document_detail", args=[str(doc.pk)]))

    assert response.status_code == 200
    assert MASK_TEXT in response.content.decode()


def test_document_detail_normal_for_privileged_user(client: Any, uploader: User) -> None:
    set_setting(BLUR_SETTING_KEY, "true", label="敏感模糊")
    client.force_login(uploader)
    doc = _make_doc(uploader, sensitivity="sensitive", suffix="sec5")

    response = client.get(reverse("documents:document_detail", args=[str(doc.pk)]))

    assert response.status_code == 200
    assert MASK_TEXT not in response.content.decode()
