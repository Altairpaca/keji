"""系统设置读写服务（core）。

- get_setting：读库并缓存 60 秒（key: ``system_setting:{key}``），写时失效；
- set_setting：写库并失效缓存；
- 种子默认设置由 seed 命令负责，本模块只提供读写。
"""

from typing import Any

from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist

from apps.core.models.setting import SystemSetting

CACHE_PREFIX = "system_setting:"
CACHE_TIMEOUT = 60


def _cache_key(key: str) -> str:
    return f"{CACHE_PREFIX}{key}"


def _validate_key(key: Any) -> str:
    """key 必须是非空字符串；非字符串视为类型错误。"""
    if not isinstance(key, str):
        raise TypeError("系统设置 key 必须是字符串类型")
    if not key.strip():
        raise ValueError("系统设置 key 不能为空")
    return key


def get_setting(key: Any, default: Any = None) -> Any:
    """读取设置值：先查缓存，未命中则读库并回填缓存。"""
    valid_key = _validate_key(key)
    cached = cache.get(_cache_key(valid_key))
    if cached is not None:
        return cached
    try:
        setting = SystemSetting.objects.get(key=valid_key)
    except ObjectDoesNotExist:
        return default
    cache.set(_cache_key(valid_key), setting.value, CACHE_TIMEOUT)
    return setting.value


def set_setting(
    key: Any,
    value: Any,
    label: str = "",
    description: str = "",
    user: Any = None,
) -> SystemSetting:
    """写入或更新设置并失效缓存；返回更新后的 SystemSetting。"""
    valid_key = _validate_key(key)
    setting, _ = SystemSetting.objects.update_or_create(
        key=valid_key,
        defaults={
            "value": value,
            "label": label,
            "description": description,
            "updated_by": user,
        },
    )
    assert isinstance(setting, SystemSetting)
    cache.delete(_cache_key(valid_key))
    return setting


def get_all_settings() -> dict[str, Any]:
    """返回全部设置的 key -> value 映射。"""
    return {setting.key: setting.value for setting in SystemSetting.objects.all()}
