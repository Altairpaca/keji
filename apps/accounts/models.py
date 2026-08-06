"""accounts 模型。

User 首日即使用 UUID 主键（ADR-005）。
权限位框架（ADR-004 / ADR-012）：11 个布尔权限位 + has_bit 服务端校验。
字段名以任务规格为准（security.md 权限矩阵为蓝图）。
"""

import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """自定义用户模型：继承 AbstractUser，主键为 UUID（ADR-005）。

    11 个权限位为功能域级布尔开关（ADR-004），服务端校验统一走
    ``apps.accounts.permissions.require_permission`` 装饰器；模板层的
    ``has_perm`` 标签只做展示性隐藏，不作为安全边界。
    """

    PERMISSION_BITS: ClassVar[tuple[str, ...]] = (
        "can_view_customers",  # 查看客户
        "can_manage_customers",  # 创建和编辑客户
        "can_delete_customers",  # 删除客户
        "can_view_sensitive",  # 查看敏感资料
        "can_download_originals",  # 下载原文件
        "can_export_data",  # 导出数据
        "can_permanent_delete",  # 永久删除
        "can_manage_enums",  # 管理标签和枚举
        "can_manage_users",  # 管理用户
        "can_view_audit_logs",  # 查看审计日志
        "can_backup",  # 执行备份或恢复
    )

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)

    can_view_customers = models.BooleanField(default=False, verbose_name="查看客户")
    can_manage_customers = models.BooleanField(default=False, verbose_name="创建和编辑客户")
    can_delete_customers = models.BooleanField(default=False, verbose_name="删除客户")
    can_view_sensitive = models.BooleanField(default=False, verbose_name="查看敏感资料")
    can_download_originals = models.BooleanField(default=False, verbose_name="下载原文件")
    can_export_data = models.BooleanField(default=False, verbose_name="导出数据")
    can_permanent_delete = models.BooleanField(default=False, verbose_name="永久删除")
    can_manage_enums = models.BooleanField(default=False, verbose_name="管理标签和枚举")
    can_manage_users = models.BooleanField(default=False, verbose_name="管理用户")
    can_view_audit_logs = models.BooleanField(default=False, verbose_name="查看审计日志")
    can_backup = models.BooleanField(default=False, verbose_name="执行备份或恢复")

    def has_bit(self, bit_name: str) -> bool:
        """判断是否拥有指定权限位；超级管理员恒为 True（ADR-012 管理员覆盖）。"""
        if self.is_superuser:
            return True
        return bool(getattr(self, bit_name))
