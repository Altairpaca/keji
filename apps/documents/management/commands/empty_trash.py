"""GC 管理命令：批量永久删除回收站中超过保留期的已删文档（T6.4）。

用法：``manage.py empty_trash [--before-days 30]``
默认只清理超过 30 天未恢复的文档；``--before-days 0`` 清空整个回收站。
"""

from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from apps.documents.services.recycle import DEFAULT_RETENTION_DAYS, empty_trash


class Command(BaseCommand):
    help = "永久删除回收站中超过保留期的已删文档（ADR-006 第 3 级）。"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--before-days",
            type=int,
            default=DEFAULT_RETENTION_DAYS,
            help=f"仅清理删除超过该天数的文档（默认 {DEFAULT_RETENTION_DAYS}；0=清空回收站）",
        )

    def handle(self, *args: object, **options: object) -> None:
        before_days_value = options.get("before_days")
        assert isinstance(before_days_value, int), "before-days 必须为整数"
        before_days = before_days_value
        stats = empty_trash(before_days=before_days)
        self.stdout.write(
            self.style.SUCCESS(
                f"回收站 GC 完成：删除记录 {stats['rows_deleted']} 条，"
                f"清理物理文件 {stats['files_deleted']} 个"
            )
        )
