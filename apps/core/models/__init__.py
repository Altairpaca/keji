"""core 应用模型包：通用基础模型 + 系统设置 + 保存视图。"""

from apps.core.models.base import (
    SoftDeleteManager,
    SoftDeleteModel,
    TimeStampedModel,
    UUIDModel,
)
from apps.core.models.saved_view import SavedView
from apps.core.models.setting import SystemSetting

__all__ = [
    "SavedView",
    "SoftDeleteManager",
    "SoftDeleteModel",
    "SystemSetting",
    "TimeStampedModel",
    "UUIDModel",
]
