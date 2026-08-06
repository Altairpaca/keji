"""备份服务（规格 §18、ADR-011）。

- ``run_backup``：pg_dump 数据库 + media 目录 tar.gz + manifest + sha256 校验 + 保留策略
- ``prune_backups``：按保留份数删除最旧备份
- ``list_backups``：backups/ 下各备份目录的 manifest 摘要

备份目录按时间戳组织：
``backups/<YYYYMMDD_HHMMSS>/{db.dump, media.tar.gz, manifest.json, checksums.txt}``。
pg_dump 连接参数取自 ``settings.DATABASES["default"]``：
容器内执行时 HOST 为 ``db``，本地执行为 ``127.0.0.1``，均直接使用 settings 值。
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

from django.apps import apps
from django.conf import settings


class BackupError(Exception):
    """备份失败（pg_dump 非零退出、产物缺失等）。"""


class BackupManifest(TypedDict):
    version: int
    created_at: str
    db_dump: str
    media_tar: str
    counts: dict[str, int]
    checksums: dict[str, str]


class BackupResult(TypedDict):
    stamp: str
    path: str
    manifest: BackupManifest
    removed: list[str]


def _now_stamp() -> str:
    """返回 YYYYMMDD_HHMMSS 形式的时间戳，用于备份目录命名。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha256_file(path: Path) -> str:
    """流式计算文件 sha256（避免一次性读入内存）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pg_dump_command(dump_file: Path) -> list[str]:
    """由 settings.DATABASES 构造 pg_dump 参数（-F c 自定义格式）。"""
    conf = settings.DATABASES["default"]
    return [
        "pg_dump",
        "-U",
        str(conf["USER"]),
        "-h",
        str(conf["HOST"]),
        "-p",
        str(conf["PORT"]),
        "-F",
        "c",
        "-f",
        str(dump_file),
        str(conf["NAME"]),
    ]


def _entity_counts() -> dict[str, int]:
    """遍历已安装模型，统计各实体行数（非软删：默认 manager 已过滤 is_deleted）。"""
    counts: dict[str, int] = {}
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        label = f"{model._meta.app_label}.{model._meta.model_name}"
        counts[label] = model._default_manager.count()
    return counts


def build_manifest(
    *,
    db_dump: str,
    media_tar: str,
    created_at: datetime,
    counts: dict[str, int],
) -> BackupManifest:
    """构造 manifest.json 内容（版本、时间、产物文件名、实体行数、sha256 校验和）。"""
    db_name = Path(db_dump).name
    tar_name = Path(media_tar).name
    return {
        "version": 1,
        "created_at": created_at.isoformat(),
        "db_dump": db_name,
        "media_tar": tar_name,
        "counts": counts,
        "checksums": {
            db_name: _sha256_file(Path(db_dump)),
            tar_name: _sha256_file(Path(media_tar)),
        },
    }


def _write_checksums_txt(target: Path, manifest: BackupManifest) -> None:
    """写出 checksums.txt（文件名 + sha256，一行一个）。"""
    lines = [f"{digest}  {name}" for name, digest in manifest["checksums"].items()]
    (target / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_pg_dump(dump_file: Path) -> None:
    """执行 pg_dump；非零退出抛 BackupError。"""
    env = {**os.environ, "PGPASSWORD": str(settings.DATABASES["default"]["PASSWORD"])}
    proc = subprocess.run(
        _pg_dump_command(dump_file),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise BackupError(f"pg_dump 失败（退出码 {proc.returncode}）：{proc.stderr.strip()}")


def _archive_media(media_tar: Path) -> None:
    """media 目录流式打包为 tar.gz（tarfile 流式，避免大内存）。"""
    media_root = Path(settings.MEDIA_ROOT)
    with tarfile.open(media_tar, "w:gz") as tar:
        if media_root.exists():
            tar.add(media_root, arcname=media_root.name)


def run_backup(*, backup_dir: Path | str | None = None) -> BackupResult:
    """执行一次完整备份，返回 manifest 与产物路径。

    流程：pg_dump → media tar.gz → sha256 校验 → manifest.json/checksums.txt → 保留策略。
    失败（pg_dump 非零退出等）时清理半成品目录并抛 BackupError。
    """
    root = Path(backup_dir) if backup_dir is not None else Path(settings.BACKUP_DIR)
    stamp = _now_stamp()
    target = root / stamp
    target.mkdir(parents=True, exist_ok=True)

    db_dump = target / "db.dump"
    media_tar = target / "media.tar.gz"

    try:
        _run_pg_dump(db_dump)
        _archive_media(media_tar)
        manifest = build_manifest(
            db_dump=str(db_dump),
            media_tar=str(media_tar),
            created_at=datetime.now(),
            counts=_entity_counts(),
        )
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_checksums_txt(target, manifest)
        removed = prune_backups(backup_dir=root, keep=settings.BACKUP_RETENTION_COUNT)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise

    return {"stamp": stamp, "path": str(target), "manifest": manifest, "removed": removed}


def prune_backups(*, backup_dir: Path | str | None = None, keep: int | None = None) -> list[str]:
    """删除最旧备份目录直到剩余 keep 份，返回被删除目录名列表。"""
    root = Path(backup_dir) if backup_dir is not None else Path(settings.BACKUP_DIR)
    keep = keep if keep is not None else settings.BACKUP_RETENTION_COUNT
    if not root.exists():
        return []
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
    removed: list[str] = []
    if len(dirs) > keep:
        for stale in dirs[: len(dirs) - keep]:
            shutil.rmtree(stale, ignore_errors=True)
            removed.append(stale.name)
    return removed


def list_backups() -> list[dict[str, object]]:
    """backups/ 下各备份目录的 manifest 摘要，按时间戳倒序。"""
    root = Path(settings.BACKUP_DIR)
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
