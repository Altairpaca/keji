"""冒烟测试：验证 Django 项目可启动、无未生成的迁移。"""

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_pending_migrations() -> None:
    call_command("makemigrations", "--check", "--dry-run")
