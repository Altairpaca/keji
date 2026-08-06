"""备份服务与管理命令测试（规格 §18 备份、ADR-011）。

测试策略：pg_dump 用假 subprocess.run 替换（不依赖真实数据库导出），
验证整条管线与产物（db.dump / media.tar.gz / manifest.json / checksums.txt / 保留策略）。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from apps.core.services import backup
from apps.customers.models import Customer

pytestmark = pytest.mark.django_db


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FakeResult:
    """模拟 subprocess.CompletedProcess 的最小实现。"""

    def __init__(self, *, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr


class FakeSubprocess:
    """替换 backup 模块内的 subprocess：模拟 pg_dump 行为并记录调用参数。"""

    def __init__(
        self,
        *,
        write_file: bool = True,
        returncode: int = 0,
        stderr: str = "",
    ) -> None:
        self.write_file = write_file
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs: object) -> _FakeResult:
        self.calls.append(list(cmd))
        if self.write_file:
            out = Path(cmd[cmd.index("-f") + 1])
            out.write_bytes(b"FAKE-PGDUMP-DATA")
        return _FakeResult(returncode=self.returncode, stderr=self.stderr)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> FakeSubprocess:
    fake = FakeSubprocess()
    monkeypatch.setattr(backup, "subprocess", fake)
    return fake


def test_now_stamp_format() -> None:
    stamp = backup._now_stamp()
    assert re.fullmatch(r"\d{8}_\d{6}", stamp)


def test_build_manifest_contains_sha256_checksums(tmp_path: Path) -> None:
    dump = tmp_path / "db.dump"
    tar = tmp_path / "media.tar.gz"
    dump.write_bytes(b"dump-bytes")
    tar.write_bytes(b"tar-bytes")

    manifest = backup.build_manifest(
        db_dump=str(dump),
        media_tar=str(tar),
        created_at=datetime(2026, 8, 6, 10, 30, 0),
        counts={"customers.customer": 3},
    )

    assert manifest["version"] == 1
    assert manifest["created_at"] == "2026-08-06T10:30:00"
    assert manifest["db_dump"] == "db.dump"
    assert manifest["media_tar"] == "media.tar.gz"
    assert manifest["counts"] == {"customers.customer": 3}
    assert manifest["checksums"]["db.dump"] == _sha256(b"dump-bytes")
    assert manifest["checksums"]["media.tar.gz"] == _sha256(b"tar-bytes")


def test_run_backup_creates_manifest_and_checksums(
    tmp_path: Path, fake_subprocess: FakeSubprocess
) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "a.txt").write_text("hello", encoding="utf-8")
    Customer.objects.create(name="备份测试客户")

    with override_settings(
        MEDIA_ROOT=media_dir,
        BACKUP_DIR=tmp_path / "backups",
        BACKUP_RETENTION_COUNT=5,
    ):
        result = backup.run_backup()

    target = Path(result["path"])
    dump = target / "db.dump"
    tar = target / "media.tar.gz"

    assert dump.exists()
    assert dump.read_bytes() == b"FAKE-PGDUMP-DATA"
    assert tar.exists()
    assert (target / "manifest.json").exists()
    assert (target / "checksums.txt").exists()

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert manifest["db_dump"] == "db.dump"
    assert manifest["media_tar"] == "media.tar.gz"
    assert manifest["counts"]["customers.customer"] == 1
    assert manifest["checksums"]["db.dump"] == _sha256(dump.read_bytes())
    assert manifest["checksums"]["media.tar.gz"] == _sha256(tar.read_bytes())

    with tarfile.open(tar, "r:gz") as tf:
        assert "media/a.txt" in tf.getnames()


def test_run_backup_pg_dump_args_from_settings(
    tmp_path: Path, fake_subprocess: FakeSubprocess
) -> None:
    with override_settings(MEDIA_ROOT=tmp_path / "media", BACKUP_DIR=tmp_path / "backups"):
        backup.run_backup()

    cmd = fake_subprocess.calls[0]
    conf = settings.DATABASES["default"]
    assert cmd[0] == "pg_dump"
    assert cmd[cmd.index("-U") + 1] == str(conf["USER"])
    assert cmd[cmd.index("-h") + 1] == str(conf["HOST"])
    assert cmd[cmd.index("-p") + 1] == str(conf["PORT"])
    assert cmd[-1] == str(conf["NAME"])


def test_prune_removes_oldest_backups(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    for i in range(35):
        (root / f"20260101_{i:06d}").mkdir(parents=True)

    removed = backup.prune_backups(backup_dir=root, keep=30)

    assert len(removed) == 5
    assert removed == [f"20260101_{i:06d}" for i in range(5)]
    remaining = sorted(p.name for p in root.iterdir())
    assert remaining == [f"20260101_{i:06d}" for i in range(5, 35)]


def test_prune_keep_5(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    for i in range(8):
        (root / f"20260101_{i:06d}").mkdir(parents=True)

    removed = backup.prune_backups(backup_dir=root, keep=5)

    assert len(removed) == 3
    assert len(list(root.iterdir())) == 5


def test_list_backups_parses_manifest(tmp_path: Path, fake_subprocess: FakeSubprocess) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    with override_settings(MEDIA_ROOT=media_dir, BACKUP_DIR=tmp_path / "backups"):
        backup.run_backup()
        items = backup.list_backups()

    assert len(items) == 1
    item = items[0]
    assert item["version"] == 1
    assert item["db_dump"] == "db.dump"
    assert item["media_tar"] == "media.tar.gz"
    assert "counts" in item
    assert "stamp" in item


def test_run_backup_failure_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "backups"
    fake = FakeSubprocess(returncode=1, stderr="pg_dump: connection refused")
    monkeypatch.setattr(backup, "subprocess", fake)

    with (
        override_settings(MEDIA_ROOT=tmp_path / "media", BACKUP_DIR=root),
        pytest.raises(backup.BackupError),
    ):
        backup.run_backup()

    assert not root.exists() or not list(root.iterdir())


def test_backup_command_success(tmp_path: Path, fake_subprocess: FakeSubprocess) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    out = io.StringIO()
    with override_settings(MEDIA_ROOT=media_dir, BACKUP_DIR=tmp_path / "backups"):
        call_command("backup", stdout=out)

    text = out.getvalue()
    assert "备份完成" in text
    assert str(tmp_path / "backups") in text
    assert len(list((tmp_path / "backups").iterdir())) == 1
