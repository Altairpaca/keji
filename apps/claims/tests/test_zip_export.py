"""T8.3 理赔案件资料 ZIP 打包导出测试（RED 先行，规格 §12 / §16 / §10）。

覆盖：
- ``_sanitize_filename``：路径穿越清洗 / 空值兜底 / 超长截断；
- ``build_claim_zip``：目录结构 / 必需优先排序 / 清单内容 / 缺失说明 /
  确定性（两次导出字节一致）/ 全路径消毒；
- 视图：200 + ZIP 头 + Content-Disposition；无 can_export_data 403；
  无可查看客户权限 403；匿名 302；材料全无也能导出。
"""

import hashlib
import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.claims.models import ClaimCase
from apps.claims.services import create_claim, create_material
from apps.claims.services.export import (
    _dedupe_path,
    _sanitize_filename,
    build_claim_zip,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.documents.models import Document
from apps.documents.storage import LocalDiskStorage, new_storage_key

pytestmark = pytest.mark.django_db

#: 固定「生成时间」，保证导出字节确定性与清单断言稳定。
FIXED_NOW = datetime(2026, 8, 6, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def exporter(db: None) -> User:
    """拥有导出数据 + 查看客户权限的用户。"""
    u = User(username="exporter", can_export_data=True, can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def customer(user: User) -> Customer:
    return create_customer(name="林小明", owner=user, created_by=user, age_note="约35岁")


@pytest.fixture
def claim(user: User, customer: Customer) -> ClaimCase:
    return create_claim(name="林小明-医疗理赔", customer=customer, owner=user)


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskStorage:
    """每个测试独立的临时存储后端，替换 export 模块引用的 default_storage。"""
    backend = LocalDiskStorage(root=tmp_path / "media")
    monkeypatch.setattr("apps.claims.services.export.default_storage", backend)
    return backend


def _make_document(storage: LocalDiskStorage, *, name: str, content: bytes, user: User) -> Document:
    """直接造真实文件：storage 落盘 + Document 元数据。"""
    key = new_storage_key()
    storage.save(key, io.BytesIO(content))
    doc: Document = Document.objects.create(
        original_name=name,
        storage_key=key,
        mime_type="application/pdf",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=user,
    )
    return doc


def _zip_bytes(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


def test_sanitize_filename_removes_traversal() -> None:
    assert _sanitize_filename("../../etc/passwd") == "etc_passwd"
    assert "/" not in _sanitize_filename("a/b\\c")
    assert "\\" not in _sanitize_filename("a/b\\c")
    assert ".." not in _sanitize_filename("../x")
    assert "\x00" not in _sanitize_filename("a\x00b")


def test_sanitize_filename_empty_falls_back() -> None:
    assert _sanitize_filename("") == "未命名"
    assert _sanitize_filename("   ") == "未命名"
    assert _sanitize_filename("..") == "未命名"


def test_sanitize_filename_truncates_to_100() -> None:
    assert len(_sanitize_filename("文" * 200)) == 100


# ---------------------------------------------------------------------------
# build_claim_zip
# ---------------------------------------------------------------------------


def test_build_claim_zip_structure_and_required_first(
    claim: ClaimCase, user: User, storage: LocalDiskStorage
) -> None:
    create_material(
        claim=claim,
        name="住院发票",
        is_required=True,
        document=_make_document(storage, name="住院发票.pdf", content=b"%PDF-1.7 fake", user=user),
    )
    create_material(
        claim=claim,
        name="诊断证明",
        is_required=False,
        document=_make_document(
            storage, name="诊断证明.jpg", content=b"\xff\xd8\xff\xe0 fake", user=user
        ),
    )
    claim_dir = _sanitize_filename(claim.name)

    zip_bytes, filename = build_claim_zip(claim, now=FIXED_NOW)

    assert filename == f"理赔资料_{claim_dir}_{date.today()}.zip"
    with _zip_bytes(zip_bytes) as zf:
        names = zf.namelist()
    required_path = f"{claim_dir}/01_材料/01_住院发票/住院发票.pdf"
    optional_path = f"{claim_dir}/01_材料/02_诊断证明/诊断证明.jpg"
    assert names[0] == f"{claim_dir}/00_说明.txt"
    assert names == [names[0], required_path, optional_path]
    # 必需材料排在非必需之前
    assert names.index(required_path) < names.index(optional_path)
    with _zip_bytes(zip_bytes) as zf:
        assert zf.read(required_path) == b"%PDF-1.7 fake"
        assert zf.read(optional_path) == b"\xff\xd8\xff\xe0 fake"


def test_build_claim_zip_manifest_lists_materials(
    claim: ClaimCase, user: User, storage: LocalDiskStorage
) -> None:
    create_material(
        claim=claim,
        name="住院发票",
        is_required=True,
        document=_make_document(storage, name="住院发票.pdf", content=b"%PDF fake", user=user),
    )
    create_material(claim=claim, name="诊断证明", is_required=False)
    zip_bytes, _ = build_claim_zip(claim, now=FIXED_NOW)
    with _zip_bytes(zip_bytes) as zf:
        manifest = zf.read(f"{_sanitize_filename(claim.name)}/00_说明.txt").decode("utf-8")
    assert claim.name in manifest
    assert "住院发票" in manifest
    assert "诊断证明" in manifest
    assert "必需" in manifest
    assert "2026-08-06" in manifest  # 生成时间（固定 now）


def test_build_claim_zip_missing_material_note(
    claim: ClaimCase, user: User, storage: LocalDiskStorage
) -> None:
    create_material(claim=claim, name="出院小结", is_required=True)
    claim_dir = _sanitize_filename(claim.name)
    zip_bytes, _ = build_claim_zip(claim, now=FIXED_NOW)
    with _zip_bytes(zip_bytes) as zf:
        names = zf.namelist()
        note = f"{claim_dir}/01_材料/01_缺失.txt"
        assert note in names
        assert "出院小结" in zf.read(note).decode("utf-8")


def test_build_claim_zip_empty_claim_has_manifest_only(claim: ClaimCase) -> None:
    zip_bytes, _ = build_claim_zip(claim, now=FIXED_NOW)
    with _zip_bytes(zip_bytes) as zf:
        assert zf.namelist() == [f"{_sanitize_filename(claim.name)}/00_说明.txt"]


def test_build_claim_zip_deterministic(
    claim: ClaimCase, user: User, storage: LocalDiskStorage
) -> None:
    create_material(
        claim=claim,
        name="发票",
        is_required=True,
        document=_make_document(storage, name="发票.pdf", content=b"%PDF fake", user=user),
    )
    first, _ = build_claim_zip(claim, now=FIXED_NOW)
    second, _ = build_claim_zip(claim, now=FIXED_NOW)
    assert first == second


def test_build_claim_zip_sanitizes_all_paths(
    claim: ClaimCase, user: User, storage: LocalDiskStorage
) -> None:
    evil_claim = create_claim(name="../恶意案件", customer=claim.customer, owner=claim.owner)
    create_material(
        claim=evil_claim,
        name="a/b\\报告",
        is_required=True,
        document=_make_document(storage, name="../泄露.txt", content=b"secret", user=user),
    )
    zip_bytes, _ = build_claim_zip(evil_claim, now=FIXED_NOW)
    with _zip_bytes(zip_bytes) as zf:
        for entry in zf.namelist():
            assert not entry.startswith("/")
            assert "\\" not in entry
            assert ".." not in entry.split("/")


def test_dedupe_path_appends_suffix() -> None:
    used: set[str] = set()
    assert _dedupe_path("a/b/f.pdf", used) == "a/b/f.pdf"
    assert _dedupe_path("a/b/f.pdf", used) == "a/b/f(2).pdf"
    assert _dedupe_path("a/b/f.pdf", used) == "a/b/f(3).pdf"


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


def _export_url(claim: ClaimCase) -> str:
    url: str = reverse("claims:claim_export_zip", args=[claim.pk])
    return url


def test_export_view_requires_login(client: Client, claim: ClaimCase) -> None:
    resp = client.get(_export_url(claim))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_export_view_forbids_without_export_permission(
    client: Client, user: User, claim: ClaimCase
) -> None:
    client.force_login(user)
    assert client.get(_export_url(claim)).status_code == 403


def test_export_view_forbids_without_view_customers(client: Client, claim: ClaimCase) -> None:
    u = User(username="no-view", can_export_data=True, can_view_customers=False)
    u.save()
    client.force_login(u)
    assert client.get(_export_url(claim)).status_code == 403


def test_export_view_returns_zip(
    client: Client, exporter: User, claim: ClaimCase, user: User, storage: LocalDiskStorage
) -> None:
    create_material(
        claim=claim,
        name="发票",
        is_required=True,
        document=_make_document(storage, name="发票.pdf", content=b"%PDF fake", user=user),
    )
    client.force_login(exporter)
    resp = client.get(_export_url(claim))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/zip"
    assert "filename*=UTF-8''" in resp["Content-Disposition"]
    assert resp.content[:4] == b"PK\x03\x04"
    with _zip_bytes(resp.content) as zf:
        assert f"{_sanitize_filename(claim.name)}/00_说明.txt" in zf.namelist()


def test_export_view_empty_claim_ok(client: Client, exporter: User, claim: ClaimCase) -> None:
    client.force_login(exporter)
    resp = client.get(_export_url(claim))
    assert resp.status_code == 200
    assert resp.content[:4] == b"PK\x03\x04"
