"""恢复服务与管理命令测试（规格 §18 恢复演练）。

测试策略：
- list_backup_snapshots：造 fake 备份目录 + manifest，验证解析与倒序
- restore_backup：pg_restore 用假 subprocess.run 替换（记录参数断言），
  校验和用真实文件计算；media 用真实 tar.gz（含恶意成员用例验证安全解包）
- 管理命令：缺 --stamp 时报错
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.core.services import restore

pytestmark = pytest.mark.django_db


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_snapshot(
    root: Path,
    stamp: str,
    *,
    dump_bytes: bytes = b"FAKE-PGDUMP-DATA",
    tar_bytes: bytes | None = None,
) -> Path:
    """在 root 下构造一个完整快照目录（db.dump / media.tar.gz / manifest.json / checksums.txt）。"""
    target = root / stamp
    target.mkdir(parents=True)
    (target / "db.dump").write_bytes(dump_bytes)
    tar_bytes = tar_bytes if tar_bytes is not None else b"FAKE-TAR-DATA"
    (target / "media.tar.gz").write_bytes(tar_bytes)
    manifest = {
        "version": 1,
        "created_at": "2026-08-06T22:25:57",
        "db_dump": "db.dump",
        "media_tar": "media.tar.gz",
        "counts": {"customers.customer": 16, "claims.claimcase": 5},
        "checksums": {
            "db.dump": _sha256(dump_bytes),
            "media.tar.gz": _sha256(tar_bytes),
        },
    }
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "checksums.txt").write_text("", encoding="utf-8")
    return target


class _FakeResult:
    def __init__(self, *, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr


class FakeRestoreSubprocess:
    """替换 restore 模块内的 subprocess：模拟 pg_restore 并记录调用参数。"""

    def __init__(self, *, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs: object) -> _FakeResult:
        self.calls.append(list(cmd))
        return _FakeResult(returncode=self.returncode, stderr=self.stderr)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> FakeRestoreSubprocess:
    fake = FakeRestoreSubprocess()
    monkeypatch.setattr(restore, "subprocess", fake)
    return fake


def _media_tar(tmp_path: Path, files: dict[str, bytes]) -> bytes:
    """构造一个模拟 media.tar.gz（成员带 media/ 前缀，与备份产物一致）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        root_dir = tarfile.TarInfo(name="media")
        root_dir.type = tarfile.DIRTYPE
        tar.addfile(root_dir)
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# list_backup_snapshots
# ---------------------------------------------------------------------------


def test_list_backup_snapshots_parses_manifest_desc(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    _make_snapshot(root, "20260801_100000")
    _make_snapshot(root, "20260806_222557")
    _make_snapshot(root, "20260803_120000")

    with override_settings(BACKUP_DIR=root):
        items = restore.list_backup_snapshots()

    assert [i["stamp"] for i in items] == [
        "20260806_222557",
        "20260803_120000",
        "20260801_100000",
    ]
    item = items[0]
    counts = item["counts"]
    assert isinstance(counts, dict)
    assert counts["customers.customer"] == 16
    assert item["db_dump"] == "db.dump"


def test_list_backup_snapshots_skips_invalid(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    _make_snapshot(root, "20260806_222557")
    (root / "broken").mkdir()
    (root / "broken" / "manifest.json").write_text("{not json", encoding="utf-8")
    (root / "nodir").mkdir()  # 无 manifest

    with override_settings(BACKUP_DIR=root):
        items = restore.list_backup_snapshots()

    assert [i["stamp"] for i in items] == ["20260806_222557"]


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------


def test_restore_backup_pg_restore_args_and_media_extract(
    tmp_path: Path, fake_subprocess: FakeRestoreSubprocess
) -> None:
    root = tmp_path / "backups"
    media_root = tmp_path / "media"
    media_root.mkdir()
    tar_bytes = _media_tar(tmp_path, {"media/photo.jpg": b"JPEG", "media/sub/a.txt": b"text"})
    _make_snapshot(root, "20260806_222557", tar_bytes=tar_bytes)

    with override_settings(BACKUP_DIR=root, MEDIA_ROOT=media_root):
        result = restore.restore_backup(stamp="20260806_222557")

    assert result["stamp"] == "20260806_222557"
    assert result["counts"]["customers.customer"] == 16
    assert "restored_at" in result

    cmd = fake_subprocess.calls[0]
    conf = settings.DATABASES["default"]
    assert cmd[0] == "pg_restore"
    assert "--clean" in cmd
    assert "--if-exists" in cmd
    assert cmd[cmd.index("-U") + 1] == str(conf["USER"])
    assert cmd[cmd.index("-h") + 1] == str(conf["HOST"])
    assert cmd[cmd.index("-p") + 1] == str(conf["PORT"])
    assert cmd[cmd.index("-d") + 1] == str(conf["NAME"])
    assert cmd[-1].endswith("db.dump")

    # media 解包：media/ 前缀被剥离，落到 MEDIA_ROOT 下
    assert (media_root / "photo.jpg").read_bytes() == b"JPEG"
    assert (media_root / "sub" / "a.txt").read_bytes() == b"text"


def test_restore_backup_db_name_override(
    tmp_path: Path, fake_subprocess: FakeRestoreSubprocess
) -> None:
    root = tmp_path / "backups"
    tar_bytes = _media_tar(tmp_path, {"media/a.txt": b"hello"})
    _make_snapshot(root, "20260806_222557", tar_bytes=tar_bytes)

    with override_settings(BACKUP_DIR=root, MEDIA_ROOT=tmp_path / "media"):
        restore.restore_backup(stamp="20260806_222557", db_name="keji_drill")

    cmd = fake_subprocess.calls[0]
    assert cmd[cmd.index("-d") + 1] == "keji_drill"


def test_restore_backup_checksum_mismatch_raises(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    _make_snapshot(root, "20260806_222557")
    # 篡改 db.dump 内容，校验和应与 manifest 不符
    (root / "20260806_222557" / "db.dump").write_bytes(b"TAMPERED-DATA")

    with (
        override_settings(BACKUP_DIR=root, MEDIA_ROOT=tmp_path / "media"),
        pytest.raises(restore.RestoreError, match="校验和"),
    ):
        restore.restore_backup(stamp="20260806_222557")


def test_restore_backup_unknown_stamp_raises(tmp_path: Path) -> None:
    with (
        override_settings(BACKUP_DIR=tmp_path / "backups"),
        pytest.raises(restore.RestoreError),
    ):
        restore.restore_backup(stamp="20260101_000000")


def test_restore_backup_pg_restore_failure_raises_and_keeps_media(
    tmp_path: Path, fake_subprocess: FakeRestoreSubprocess
) -> None:
    fake_subprocess.returncode = 1
    fake_subprocess.stderr = "pg_restore: error: could not connect"
    root = tmp_path / "backups"
    media_root = tmp_path / "media"
    media_root.mkdir()
    _make_snapshot(root, "20260806_222557")

    with (
        override_settings(BACKUP_DIR=root, MEDIA_ROOT=media_root),
        pytest.raises(restore.RestoreError, match="pg_restore"),
    ):
        restore.restore_backup(stamp="20260806_222557")

    # 半解包不得残留：无 .tmp 目录，且 media 未被打乱
    assert not list(tmp_path.glob("media.tmp*"))
    assert not (media_root / "photo.jpg").exists()


# ---------------------------------------------------------------------------
# _safe_extract_tar
# ---------------------------------------------------------------------------


def test_safe_extract_tar_normal(tmp_path: Path) -> None:
    tar_bytes = _media_tar(tmp_path, {"media/a.txt": b"hello", "media/dir/b.txt": b"world"})
    tar_path = tmp_path / "media.tar.gz"
    tar_path.write_bytes(tar_bytes)
    dest = tmp_path / "out"
    dest.mkdir()

    files = restore._safe_extract_tar(tar_path, dest)

    assert (dest / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (dest / "dir" / "b.txt").read_text(encoding="utf-8") == "world"
    assert files == ["a.txt", "dir/b.txt"]


def test_safe_extract_tar_rejects_path_traversal(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../../evil.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"EVIL"))
    tar_path = tmp_path / "evil.tar.gz"
    tar_path.write_bytes(buf.getvalue())
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(restore.RestoreError, match="拒绝"):
        restore._safe_extract_tar(tar_path, dest)

    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


# ---------------------------------------------------------------------------
# 管理命令
# ---------------------------------------------------------------------------


def test_restore_backup_command_missing_stamp_errors(tmp_path: Path) -> None:
    out = io.StringIO()
    with (
        override_settings(BACKUP_DIR=tmp_path / "backups", MEDIA_ROOT=tmp_path / "media"),
        pytest.raises(CommandError, match="--stamp"),
    ):
        call_command("restore_backup", stdout=out)


def test_restore_backup_command_latest(
    tmp_path: Path, fake_subprocess: FakeRestoreSubprocess
) -> None:
    root = tmp_path / "backups"
    media_root = tmp_path / "media"
    media_root.mkdir()
    tar_bytes = _media_tar(tmp_path, {"media/a.txt": b"hello"})
    _make_snapshot(root, "20260806_222557", tar_bytes=tar_bytes)
    out = io.StringIO()

    with override_settings(BACKUP_DIR=root, MEDIA_ROOT=media_root):
        call_command("restore_backup", "--latest", "--yes", stdout=out)

    text = out.getvalue()
    assert "20260806_222557" in text
    assert (media_root / "a.txt").read_text(encoding="utf-8") == "hello"
