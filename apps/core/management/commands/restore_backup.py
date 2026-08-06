"""restore_backup 管理命令（规格 §18 恢复演练）。

用法：：

    python manage.py restore_backup --stamp 20260806_222557 [--db-name keji_drill] [--yes]
    python manage.py restore_backup --latest [--yes]

- ``--stamp`` 指定快照；``--latest`` 取最新快照（二者必填其一）
- ``--db-name`` 覆盖目标库名（恢复演练用 disposable 库，默认 settings DB_NAME）
- ``--yes`` 跳过确认；stdin 非 tty 时自动跳过
"""

from __future__ import annotations

import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.core.services.restore import list_backup_snapshots, restore_backup


class Command(BaseCommand):
    help = "从 backups/<stamp> 恢复数据库与 media（校验和验证 + pg_restore + 安全解包）。"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--stamp", help="备份快照时间戳（backups/<stamp> 目录名）")
        parser.add_argument("--latest", action="store_true", help="恢复最新备份快照")
        parser.add_argument("--db-name", help="覆盖目标库名（默认 settings 的 DB_NAME）")
        parser.add_argument("--yes", action="store_true", help="跳过确认提示")

    def handle(self, *args: Any, **options: Any) -> None:
        stamp = options["stamp"]
        if not stamp:
            if not options["latest"]:
                raise CommandError("必须提供 --stamp 或 --latest")
            snapshots = list_backup_snapshots()
            if not snapshots:
                raise CommandError("backups/ 下没有可恢复的备份快照")
            stamp = str(snapshots[0]["stamp"])

        auto_yes = options["yes"] or not sys.stdin.isatty()
        if not auto_yes:
            answer = input(f"恢复备份 {stamp} 将覆盖数据库与 media，继续？[y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                self.stdout.write("已取消。")
                return

        result = restore_backup(stamp=stamp, db_name=options["db_name"])
        self.stdout.write(f"恢复完成：{result['stamp']}")
        self.stdout.write(f"  时间：{result['restored_at']}")
        self.stdout.write(f"  实体行数：{result['counts']}")
