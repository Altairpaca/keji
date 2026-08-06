"""seed_demo 管理命令：生成完整虚构演示数据（规格 §9/§25、ADR-013）。

用法：``python manage.py seed_demo``（幂等，已存在则跳过）或
``python manage.py seed_demo --reset``（先清空全部演示数据再重建）。

演示数据约定：
- 客户名以「演示-」前缀；标签名以「演示」开头；相册名以「演示-」前缀；
- 其余演示对象（关系/事件/沟通/待办/保单/理赔/文档）经关联的演示客户识别；
- 手机号一律 13900000000+i 假号段，无真实 PII；文档为 Pillow 生成随机 PNG。

实现见 seed_runner.py（逻辑）与 seed_data.py（数据表）。
"""

from typing import Any

from django.core.management.base import BaseCommand

from apps.core.management.commands.seed_reset import clear_demo_data
from apps.core.management.commands.seed_runner import DEMO_CUSTOMER_PREFIX, seed_demo_data
from apps.customers.models import Customer


class Command(BaseCommand):
    help = "生成完整虚构演示数据（客户/关系/事件/沟通/待办/文件/保单/理赔/标签），--reset 先清空。"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="先删除全部演示数据（含物理文件）再重新生成",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        if options.get("reset"):
            deleted = clear_demo_data()
            self.stdout.write(
                "已清空演示数据：" + "，".join(f"{k}={v}" for k, v in deleted.items())
            )
        elif Customer.objects.filter(name__startswith=DEMO_CUSTOMER_PREFIX).exists():
            self.stdout.write("演示数据已存在，跳过（使用 --reset 重建）")
            return None

        counts = seed_demo_data()
        self.stdout.write("演示数据生成完成：")
        for key, value in counts.items():
            self.stdout.write(f"  {key}: {value}")
        return None
