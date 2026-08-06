"""备份 / 恢复文档与命令一致性测试（规格 §18、§23、§24、ADR-011）。

职责：文档（docs/backup-restore.md）与 Makefile 中的备份 / 恢复命令，
必须与真实管理命令逐字一致 —— 文档漂移等于没有文档。本测试是文档一致性护栏：
修改文档或 Makefile 导致命令不一致时，测试先行变红。

注意：
- 备份命令 ``manage.py backup`` 无 --dry-run，只断言模块可导入、是 BaseCommand，
  不实际执行（避免产生真实备份产物）。
- 恢复命令 ``manage.py restore_backup`` 由 T11.2 并行实现中；模块存在时才断言，
  未落地时该断言 skip，文档文本断言不受影响。
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path

import pytest
from django.core.management.base import BaseCommand

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = PROJECT_ROOT / "Makefile"
BACKUP_DOC = PROJECT_ROOT / "docs" / "backup-restore.md"

COMPOSE_PREFIX = "docker compose -f docker/dev/compose.yaml"


def _make_target(target: str) -> str:
    """提取 Makefile 中指定目标（含 body），并把 $(COMPOSE) 变量展开为实际命令。"""
    text = MAKEFILE.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^{re.escape(target)}:.*?(?=^[ \t]*[a-zA-Z0-9_.-]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    assert match, f"Makefile 中不存在目标 {target}"
    return match.group(0).replace("$(COMPOSE)", COMPOSE_PREFIX)


def _doc_text() -> str:
    return BACKUP_DOC.read_text(encoding="utf-8")


def test_makefile_has_backup_and_restore_targets() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^backup:.*?## ", text, re.MULTILINE)
    assert re.search(r"^restore:.*?## ", text, re.MULTILINE)


def _target_body(block: str) -> str:
    """返回目标 body（以 tab 缩进的命令行，排除 help 注释行）。"""
    return "\n".join(line for line in block.splitlines() if line.startswith("\t"))


def test_makefile_backup_target_calls_management_command() -> None:
    body = _target_body(_make_target("backup"))
    assert "python manage.py backup" in body
    assert COMPOSE_PREFIX in body
    assert "pg_dump" not in body


def test_makefile_restore_target_calls_management_command() -> None:
    body = _target_body(_make_target("restore"))
    assert "python manage.py restore_backup" in body
    assert "--latest" in body
    assert "--yes" in body
    assert COMPOSE_PREFIX in body
    assert "psql" not in body


def test_doc_exists() -> None:
    assert BACKUP_DOC.is_file(), "docs/backup-restore.md 缺失"


def test_doc_contains_manual_backup_command() -> None:
    text = _doc_text()
    assert "python manage.py backup" in text
    assert COMPOSE_PREFIX in text


def test_doc_contains_restore_command() -> None:
    text = _doc_text()
    assert "python manage.py restore_backup" in text
    assert "--stamp" in text


def test_doc_contains_retention_policy() -> None:
    text = _doc_text()
    assert "BACKUP_RETENTION_COUNT" in text
    assert "30" in text


def test_doc_contains_cron_example() -> None:
    text = _doc_text()
    assert "cron" in text.lower()
    assert COMPOSE_PREFIX in text
    assert "manage.py backup" in text
    # 定时备份示例应给出具体的分钟 / 小时字段。
    assert re.search(r"\b\d{1,2}\s+\d{1,2}\s+\*\s+\*\s+\*", text)


def test_doc_contains_drill_section() -> None:
    text = _doc_text()
    assert "演练" in text
    assert "keji_drill" in text


def test_doc_contains_artifacts_and_checksum_verification() -> None:
    text = _doc_text()
    for artifact in ("db.dump", "media.tar.gz", "manifest.json", "checksums.txt"):
        assert artifact in text
    assert "sha256sum" in text or "sha256" in text


def test_doc_backup_command_matches_management_command() -> None:
    """文档命令与真实管理命令一致：backup 可导入且是 BaseCommand（无 dry-run，不执行）。"""
    module = import_module("apps.core.management.commands.backup")
    assert issubclass(module.Command, BaseCommand)


def test_doc_restore_command_matches_management_command() -> None:
    """restore_backup 由 T11.2 并行实现；模块存在时断言其一致性，未落地则跳过。"""
    try:
        module = import_module("apps.core.management.commands.restore_backup")
    except ModuleNotFoundError:
        pytest.skip("restore_backup 命令尚未落地（T11.2 并行实现中）")
    assert issubclass(module.Command, BaseCommand)
