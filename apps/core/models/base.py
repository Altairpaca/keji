"""通用基础模型（core）。

所有领域模型的基类：UUID 主键（ADR-005）、时间戳、软删除（ADR-006）。
业务 app 通过多重继承组合使用，例如：

    class Customer(SoftDeleteModel, UUIDModel, TimeStampedModel):
        ...
"""

import uuid
from typing import Any, Self

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """created_at / updated_at 时间戳（data-model 全局约定）。"""

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """UUID 主键（ADR-005）：不可枚举、跨备份恢复引用稳定。"""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)

    class Meta:
        abstract = True


class SoftDeleteManager(models.Manager):
    """默认 manager：正常查询自动排除已删除对象（ADR-006 第 1 级）。"""

    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    """软删除模型（ADR-006 三级删除协议第 1、2 级）。

    - 默认 manager（objects）过滤 is_deleted=False；
    - all_objects 不过滤，供回收站使用；
    - delete() 默认走软删除，force=True 或 hard_delete() 永久删除。
    """

    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="已删除")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self) -> Self:
        """软删除：标记删除并写入 deleted_at，返回 self。"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=self._soft_delete_update_fields())
        return self

    def restore(self) -> Self:
        """恢复：清空删除标记，返回 self。"""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=self._soft_delete_update_fields())
        return self

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
        force: bool = False,
    ) -> Any:
        """默认软删除；force=True 时走 Django 原生永久删除。"""
        if force:
            return super().delete(using=using, keep_parents=keep_parents)
        self.soft_delete()
        return self

    def hard_delete(self, using: str | None = None, keep_parents: bool = False) -> Any:
        """永久删除（ADR-006 第 3 级由管理员触发）。"""
        return super().delete(using=using, keep_parents=keep_parents)

    def _soft_delete_update_fields(self) -> list[str]:
        """软删除/恢复只需更新删除标记字段；若含 updated_at 一并刷新。"""
        fields: list[str] = ["is_deleted", "deleted_at"]
        for field in self._meta.fields:
            if field.name == "updated_at":
                fields.append("updated_at")
                break
        return fields
