"""敏感文件模糊展示服务（T6.3，规格 §9/§10 + security.md 权限矩阵）。

敏感级别（sensitive / highly_sensitive）的文档对无 ``can_view_sensitive``
权限的用户一律模糊：``masked_thumbnail_url`` 返回 None，模板据此渲染灰色
锁定占位 + ``blur-sm``；系统开关 ``sensitive_blur_enabled``（默认 true）
关闭时直接显示。安全判断在服务端完成，视图把判定结果传入模板。
"""

from apps.accounts.models import User
from apps.accounts.permissions import has_permission
from apps.core.services.settings import get_setting
from apps.documents.models import Document

# SystemSetting 开关键与默认值（core 的 seed 未预置则走默认）。
BLUR_SETTING_KEY = "sensitive_blur_enabled"
BLUR_SETTING_DEFAULT = "true"


def can_view_sensitive_doc(user: User, doc: Document) -> bool:
    """普通文档恒可查看；敏感 / 高敏感文档需 ``can_view_sensitive`` 权限位。"""
    if doc.sensitivity == Document.Sensitivity.NORMAL:
        return True
    return has_permission(user, "can_view_sensitive")


def is_blur_enabled() -> bool:
    """敏感模糊开关是否开启（SystemSetting sensitive_blur_enabled，默认 true）。"""
    return str(get_setting(BLUR_SETTING_KEY, BLUR_SETTING_DEFAULT)).lower() == "true"


def masked_thumbnail_url(doc: Document, user: User) -> str | None:
    """返回缩略图键；敏感且无权限且开关开启时返回 None（模糊占位）。

    None 表示模板渲染灰色锁定占位（blur-sm）；其余返回 ``doc.thumb_storage_key``，
    T6.2 生成真实缩略图后由 viewer 使用（空串时模板退化为类型图标）。
    """
    if not can_view_sensitive_doc(user, doc) and is_blur_enabled():
        return None
    return str(doc.thumb_storage_key)


def sensitive_context(user: User) -> dict[str, bool]:
    """视图上下文：服务端判定 can_view_sensitive 与敏感模糊开关。

    模板只消费这两个布尔值（不再用模板标签二次判断），安全边界在服务端。
    """
    return {
        "can_view_sensitive": has_permission(user, "can_view_sensitive"),
        "sensitive_blur_enabled": is_blur_enabled(),
    }
