"""backup 管理命令（规格 §18、ADR-011）。

用法：``python manage.py backup``。
调用 run_backup 执行完整备份（pg_dump + 媒体卷 tar + manifest + 校验和），
并按保留策略清理旧备份，stdout 输出路径 / 大小 / 保留数摘要。
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.core.services.backup import run_backup


class Command(BaseCommand):
    help = "创建完整备份（pg_dump + media tar + manifest + 校验和），并按保留策略清理旧备份。"

    def handle(self, *args: Any, **options: Any) -> str | None:
        result = run_backup()
        manifest = result["manifest"]
        self.stdout.write(f"备份完成：{result['stamp']}")
        self.stdout.write(f"  目录：{result['path']}")
        self.stdout.write(f"  db.dump：{manifest['db_dump']}")
        self.stdout.write(f"  media.tar.gz：{manifest['media_tar']}")
        self.stdout.write(f"  实体行数：{manifest['counts']}")
        self.stdout.write(f"  校验和：{manifest['checksums']}")
        self.stdout.write(f"  保留：已清理 {len(result['removed'])} 份旧备份")
        return None
