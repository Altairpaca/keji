"""恢复服务（规格 §18 恢复演练）。

- ``list_backup_snapshots``：backups/<stamp>/manifest.json 摘要列表（按时间倒序）
- ``restore_backup``：校验和验证 → pg_restore → media 安全解包
- ``_safe_extract_tar``：tar 安全解包（拒绝绝对路径 / ``..`` 路径穿越）

恢复目标库默认取 ``settings.DATABASES["default"]``，可用 ``db_name`` 覆盖
（用于恢复演练的 disposable 库）。media 先解到临时目录、成功后原子替换
MEDIA_ROOT，任何失败不残留半解包内容。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from django.conf import settings


class RestoreError(Exception):
    """恢复失败（校验和不匹配、pg_restore 非零退出、危险 tar 成员等）。"""


class RestoreResult(TypedDict):
    stamp: str
    restored_at: str
    counts: dict[str, int]


def _sha256_file(path: Path) -> str:
    """流式计算文件 sha256（避免一次性读入内存）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_backup_snapshots(*, backup_dir: Path | str | None = None) -> list[dict[str, object]]:
    """backups/ 下各快照的 manifest 摘要，按时间戳倒序（无效快照跳过）。"""
    root = Path(backup_dir) if backup_dir is not None else Path(settings.BACKUP_DIR)
    if not root.exists():
        return []
    items: list[dict[str, object]] = []
    for p in sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True):
        manifest_path = p / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            items.append({"stamp": p.name, "path": str(p), **data})
    return items


def _pg_restore_command(
    dump_file: Path,
    *,
    db_name: str | None = None,
) -> list[str]:
    """由 settings.DATABASES 构造 pg_restore 参数（--clean --if-exists -F c）。"""
    conf = settings.DATABASES["default"]
    name = db_name if db_name is not None else str(conf["NAME"])
    return [
        "pg_restore",
        "-U",
        str(conf["USER"]),
        "-h",
        str(conf["HOST"]),
        "-p",
        str(conf["PORT"]),
        "--clean",
        "--if-exists",
        "-F",
        "c",
        "-d",
        name,
        str(dump_file),
    ]


def _run_pg_restore(dump_file: Path, *, db_name: str | None = None) -> None:
    """执行 pg_restore；非零退出抛 RestoreError。"""
    env = {**os.environ, "PGPASSWORD": str(settings.DATABASES["default"]["PASSWORD"])}
    proc = subprocess.run(
        _pg_restore_command(dump_file, db_name=db_name),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RestoreError(f"pg_restore 失败（退出码 {proc.returncode}）：{proc.stderr.strip()}")


def _verify_checksums(target: Path, manifest: dict[str, object]) -> None:
    """重算并比对 manifest 中每个产物的 sha256；不符抛 RestoreError。"""
    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        raise RestoreError("manifest 缺少 checksums 字段")
    for filename, expected in checksums.items():
        if not isinstance(filename, str) or not isinstance(expected, str):
            raise RestoreError("manifest checksums 字段非法")
        artifact = target / filename
        if not artifact.exists():
            raise RestoreError(f"备份产物缺失：{filename}")
        if _sha256_file(artifact) != expected:
            raise RestoreError(f"校验和不匹配：{filename}")


def _archive_root_prefix(names: list[str]) -> str | None:
    """推断 tar 的统一顶层目录（备份产物为 ``media/...``），无统一顶层则返回 None。"""
    tops = {n.split("/", 1)[0] for n in names if n and n != "."}
    if len(tops) == 1:
        top = tops.pop()
        if top not in ("", ".", ".."):
            return top
    return None


def _safe_relative_name(name: str, prefix: str | None) -> str | None:
    """将 tar 成员名转为相对 dest 的安全路径；危险成员（绝对 / ``..``）返回 None。

    归档根目录自身（成员名恰为 prefix）返回空串，由调用方跳过。
    """
    while name.startswith("./"):
        name = name[2:]
    name = name.strip("/")
    if not name:
        return None
    if prefix:
        if name == prefix:
            return ""  # 归档根目录自身
        parts = name.split("/", 1)
        if parts[0] != prefix:
            return None  # 成员位于统一顶层之外，拒绝
        name = parts[1]
        if not name:
            return None
    if name.startswith("/"):
        return None
    if any(p == ".." for p in name.split("/")):
        return None
    return name


def _safe_extract_tar(tar_path: Path, dest: Path) -> list[str]:
    """安全解包 tar.gz（拒绝绝对路径 / ``..`` 穿越），返回解出的相对文件路径列表。"""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with tarfile.open(tar_path, "r:gz") as tar:
        prefix = _archive_root_prefix(tar.getnames())
        for member in tar.getmembers():
            rel = _safe_relative_name(member.name, prefix)
            if rel is None:
                raise RestoreError(f"拒绝危险 tar 成员：{member.name!r}")
            if rel == "":
                continue  # 归档根目录自身（目标目录已创建）
            target = dest / rel
            if not target.resolve().is_relative_to(dest):
                raise RestoreError(f"拒绝越界 tar 成员：{member.name!r}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym() or member.islnk() or member.isfifo() or member.isdev():
                raise RestoreError(f"拒绝非常规 tar 成员：{member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                raise RestoreError(f"无法读取 tar 成员：{member.name!r}")
            with target.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            extracted.append(rel)
    return extracted


def _restore_media(tar_path: Path, media_root: Path) -> list[str]:
    """将 media.tar.gz 原子解包到 MEDIA_ROOT（先解临时目录，成功后替换）。"""
    dest = media_root.resolve()
    tmp_dest = dest.with_name(dest.name + ".tmp")
    if tmp_dest.exists():
        shutil.rmtree(tmp_dest)
    try:
        files = _safe_extract_tar(tar_path, tmp_dest)
    except BaseException:
        shutil.rmtree(tmp_dest, ignore_errors=True)
        raise
    # 原子替换：旧 media 先让位，新目录就位后再清旧
    stale = dest.with_name(dest.name + ".old")
    if stale.exists():
        shutil.rmtree(stale)
    if dest.exists():
        dest.rename(stale)
    tmp_dest.rename(dest)
    if stale.exists():
        shutil.rmtree(stale)
    return files


def restore_backup(
    *,
    stamp: str,
    backup_dir: Path | str | None = None,
    db_name: str | None = None,
) -> RestoreResult:
    """执行一次恢复：校验和 → pg_restore → media 解包，返回摘要。

    任何步骤失败抛 RestoreError，且不残留半解包 media。
    """
    root = Path(backup_dir) if backup_dir is not None else Path(settings.BACKUP_DIR)
    target = root / stamp
    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        raise RestoreError(f"备份快照不存在：{stamp}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreError(f"manifest 解析失败：{stamp}") from exc
    if not isinstance(manifest, dict):
        raise RestoreError(f"manifest 格式非法：{stamp}")

    _verify_checksums(target, manifest)

    db_dump = target / str(manifest["db_dump"])
    media_tar = target / str(manifest["media_tar"])
    _run_pg_restore(db_dump, db_name=db_name)
    _restore_media(media_tar, Path(settings.MEDIA_ROOT))

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    return {
        "stamp": stamp,
        "restored_at": datetime.now().isoformat(),
        "counts": counts,
    }
