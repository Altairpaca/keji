"""T7.4 保单-文档双向关联测试（RED 先行，规格 §11 关联文件 / §9 一文件多关联）。

覆盖：
- 服务：attach / detach（幂等与生效）、policy_documents 过滤软删文档
- 视图：列表（权限矩阵 / 只渲染已关联文档 / 空状态 / 软删隐藏）、
  attach（选择已有文件 / 上传新文件、权限矩阵）、detach（权限 / 生效）
- 文档软删后不再出现在 policy_documents 与列表页
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Document
from apps.documents.services.files import save_upload, soft_delete_document
from apps.documents.storage import LocalDiskStorage
from apps.policies.models import Policy
from apps.policies.services import create_policy
from apps.policies.services.documents import (
    attach_document_to_policy,
    detach_document_from_policy,
    policy_documents,
)

pytestmark = pytest.mark.django_db

PNG_SIG = b"\x89PNG\r\n\x1a\n"

MakePolicy = Callable[..., Policy]
MakeDocument = Callable[..., Document]


def _png_bytes(variant: int = 0) -> bytes:
    """最小合法 PNG：前 12 字节满足魔数，不同 variant 内容不同（防 SHA 撞车）。"""
    return PNG_SIG + variant.to_bytes(4, "big") + b"\x00" * 24


def _make_upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> LocalDiskStorage:
    """独立临时存储后端：上传服务不触碰真实 MEDIA_ROOT。"""
    backend = LocalDiskStorage(root=tmp_path)
    monkeypatch.setattr("apps.documents.services.files.default_storage", backend)
    return backend


@pytest.fixture
def viewer(db: None) -> User:
    user = User(username="viewer", can_view_customers=True)
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def manager(db: None) -> User:
    user = User(
        username="manager",
        can_view_customers=True,
        can_manage_customers=True,
        can_delete_customers=True,
    )
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def plain(db: None) -> User:
    user = User(username="plain")
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def make_policy(db: None) -> MakePolicy:
    """按需创建保单（owner 缺省为投保客户 owner，同保险代理人）。"""

    def _make(
        policy_no: str,
        *,
        name: str = "金佑人生",
        insurer: str = "平安人寿",
        policyholder: Customer | None = None,
        **kwargs: object,
    ) -> Policy:
        if policyholder is None:
            owner = User.objects.create(username=f"owner-{uuid.uuid4().hex[:6]}")
            policyholder = create_customer(
                name="投保客户", owner=owner, created_by=owner, age_note="约30岁"
            )
        owner = policyholder.owner
        assert owner is not None
        return create_policy(
            insurer=insurer,
            name=name,
            policy_no=policy_no,
            policyholder=policyholder,
            owner=owner,
            **kwargs,
        )

    return _make


@pytest.fixture
def make_document(db: None, isolated_storage: LocalDiskStorage) -> MakeDocument:
    """按需经 save_upload 建文档（内容为合法 PDF，每次内容唯一防 SHA 撞车）。"""

    def _make(*, title: str = "", name: str = "policy.pdf") -> Document:
        uploader = User.objects.create(username=f"up-{uuid.uuid4().hex[:6]}")
        payload = f"%PDF-1.4 doc-{uuid.uuid4().hex}".encode()
        return save_upload(
            file=_make_upload(name, payload, "application/pdf"),
            uploaded_by=uploader,
            title=title,
        )

    return _make


def _list_url(policy: Policy) -> str:
    url: str = reverse("policies:policy_document_list", args=[policy.pk])
    return url


def _attach_url(policy: Policy) -> str:
    url: str = reverse("policies:policy_document_attach", args=[policy.pk])
    return url


def _detach_url(policy: Policy, doc: Document) -> str:
    url: str = reverse("policies:policy_document_detach", args=[policy.pk, doc.pk])
    return url


def _body(response: Any) -> str:
    return str(response.content.decode())


# ---------------------------------------------------------------------------
# 服务层
# ---------------------------------------------------------------------------


def test_attach_links_document_to_policy(
    make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-1")
    doc = make_document(title="附加资料")

    attach_document_to_policy(policy, doc)

    assert list(policy_documents(policy)) == [doc]


def test_attach_is_idempotent(make_policy: MakePolicy, make_document: MakeDocument) -> None:
    policy = make_policy("POL-DOC-2")
    doc = make_document()

    attach_document_to_policy(policy, doc)
    attach_document_to_policy(policy, doc)

    assert policy_documents(policy).count() == 1


def test_detach_removes_link(make_policy: MakePolicy, make_document: MakeDocument) -> None:
    policy = make_policy("POL-DOC-3")
    doc = make_document()
    attach_document_to_policy(policy, doc)

    detach_document_from_policy(policy, doc)

    assert policy_documents(policy).count() == 0


def test_detach_not_attached_is_noop(make_policy: MakePolicy, make_document: MakeDocument) -> None:
    policy = make_policy("POL-DOC-4")
    doc = make_document()

    detach_document_from_policy(policy, doc)

    assert policy_documents(policy).count() == 0


def test_policy_documents_filters_soft_deleted(
    make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-5")
    kept = make_document(title="保留文件")
    gone = make_document(title="待删文件")
    attach_document_to_policy(policy, kept)
    attach_document_to_policy(policy, gone)

    soft_delete_document(gone)

    assert list(policy_documents(policy)) == [kept]


# ---------------------------------------------------------------------------
# 视图：列表
# ---------------------------------------------------------------------------


def test_list_anonymous_redirects_to_login(client: Any) -> None:
    response = client.get(reverse("policies:policy_document_list", args=[uuid.uuid4()]))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_list_plain_user_forbidden(client: Any, plain: User, make_policy: MakePolicy) -> None:
    policy = make_policy("POL-DOC-LIST-FORB")
    client.force_login(plain)

    response = client.get(_list_url(policy))

    assert response.status_code == 403


def test_list_viewer_renders_only_attached_documents(
    client: Any, viewer: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-LIST")
    doc = save_upload(
        file=_make_upload("bill.pdf", b"%PDF-1.4 " + b"0" * 2048, "application/pdf"),
        uploaded_by=User.objects.create(username=f"up-{uuid.uuid4().hex[:6]}"),
        title="年度对账单",
    )
    attach_document_to_policy(policy, doc)
    other = make_document(title="无关文件", name="other.pdf")
    client.force_login(viewer)

    response = client.get(_list_url(policy))

    assert response.status_code == 200
    body = _body(response)
    assert "年度对账单" in body
    assert "bill.pdf" in body
    assert "KB" in body  # 大小经 filesizeformat 渲染
    assert "无关文件" not in body
    assert str(other.pk) not in body


def test_list_empty_state(client: Any, viewer: User, make_policy: MakePolicy) -> None:
    policy = make_policy("POL-DOC-EMPTY")
    client.force_login(viewer)

    response = client.get(_list_url(policy))

    assert response.status_code == 200
    assert "还没有关联文件" in _body(response)


def test_list_hides_soft_deleted_document(
    client: Any, viewer: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-SD")
    gone = make_document(title="已删文件")
    attach_document_to_policy(policy, gone)
    soft_delete_document(gone)
    client.force_login(viewer)

    body = _body(client.get(_list_url(policy)))

    assert "已删文件" not in body


# ---------------------------------------------------------------------------
# 视图：attach
# ---------------------------------------------------------------------------


def test_attach_anonymous_redirected(client: Any) -> None:
    response = client.get(reverse("policies:policy_document_attach", args=[uuid.uuid4()]))

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_attach_viewer_without_manage_forbidden(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-DOC-ATT-FORB")
    client.force_login(viewer)

    assert client.get(_attach_url(policy)).status_code == 403
    assert client.post(_attach_url(policy), {}).status_code == 403
    assert policy_documents(policy).count() == 0


def test_attach_get_renders_form_with_existing_documents(
    client: Any, manager: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-ATT-GET")
    make_document(title="已有文件")
    client.force_login(manager)

    response = client.get(_attach_url(policy))

    assert response.status_code == 200
    body = _body(response)
    assert "选择已有文件" in body
    assert "已有文件" in body
    assert "敏感级别" in body


def test_attach_post_existing_document_links_and_redirects(
    client: Any, manager: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-ATT-EXIST")
    doc = make_document(title="已有文件")
    client.force_login(manager)

    response = client.post(_attach_url(policy), {"document_pk": str(doc.pk)})

    assert response.status_code == 302
    assert response.url == _list_url(policy)
    assert list(policy_documents(policy)) == [doc]


def test_attach_post_upload_new_file_creates_and_links(
    client: Any, manager: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-DOC-ATT-UPLOAD")
    client.force_login(manager)

    response = client.post(
        _attach_url(policy),
        {
            "files": _make_upload("contract.pdf", b"%PDF-1.4 contract", "application/pdf"),
            "title": "保险合同",
            "sensitivity": "sensitive",
        },
    )

    assert response.status_code == 302
    assert response.url == _list_url(policy)
    docs = list(policy_documents(policy))
    assert len(docs) == 1
    assert docs[0].title == "保险合同"
    assert docs[0].sensitivity == "sensitive"
    assert docs[0].source == "policy"
    assert Document.objects.count() == 1


def test_attach_post_soft_deleted_document_not_selectable(
    client: Any, manager: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-ATT-SD")
    gone = make_document(title="已删文件")
    soft_delete_document(gone)
    client.force_login(manager)

    response = client.post(_attach_url(policy), {"document_pk": str(gone.pk)})

    assert response.status_code == 404
    assert policy_documents(policy).count() == 0


def test_attach_post_neither_file_nor_document_redirects_without_link(
    client: Any, manager: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-DOC-ATT-NONE")
    client.force_login(manager)

    response = client.post(_attach_url(policy), {})

    assert response.status_code == 302
    assert response.url == _attach_url(policy)
    assert policy_documents(policy).count() == 0


# ---------------------------------------------------------------------------
# 视图：detach
# ---------------------------------------------------------------------------


def test_detach_requires_manage_permission(
    client: Any, viewer: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-DET-FORB")
    doc = make_document()
    attach_document_to_policy(policy, doc)
    client.force_login(viewer)

    response = client.post(_detach_url(policy, doc))

    assert response.status_code == 403
    assert policy_documents(policy).count() == 1


def test_detach_removes_link_and_keeps_document(
    client: Any, manager: User, make_policy: MakePolicy, make_document: MakeDocument
) -> None:
    policy = make_policy("POL-DOC-DET")
    doc = make_document(title="待移除")
    attach_document_to_policy(policy, doc)
    client.force_login(manager)

    response = client.post(_detach_url(policy, doc))

    assert response.status_code == 302
    assert response.url == _list_url(policy)
    assert policy_documents(policy).count() == 0
    assert Document.objects.filter(pk=doc.pk).exists()


def test_detach_unknown_document_404(client: Any, manager: User, make_policy: MakePolicy) -> None:
    policy = make_policy("POL-DOC-DET-404")
    client.force_login(manager)

    response = client.post(f"/policies/{policy.pk}/documents/{uuid.uuid4()}/detach/")

    assert response.status_code == 404
