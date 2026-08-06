"""accounts 模型。

User 首日即使用 UUID 主键（ADR-005），避免日后更换主键痛苦。
权限位字段与登录限流等由后续里程碑（T3.x）扩展。
"""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """自定义用户模型：继承 AbstractUser，主键为 UUID（ADR-005）。"""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
