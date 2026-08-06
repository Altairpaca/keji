"""启用 PostgreSQL ``pg_trgm`` 扩展（规格 §15 / ADR-003）。

全局搜索当前以 ORM ``icontains`` 实现；``pg_trgm`` 为后续 trigram 索引 /
相关度排序预留能力。``CREATE EXTENSION IF NOT EXISTS`` 幂等，可安全重复执行。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm;",
        ),
    ]
