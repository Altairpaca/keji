"""测试系统设置服务：读写往返、缓存命中与失效、非法 key 拒绝（core）。"""

from collections.abc import Iterator

import pytest
from django.core.cache import cache

from apps.core.models.setting import SystemSetting
from apps.core.services.settings import get_all_settings, get_setting, set_setting


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    """每个用例前清理内存缓存，避免跨用例污染。"""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_set_get_roundtrip() -> None:
    set_setting("site_name", "客迹", label="站点名称")

    assert get_setting("site_name") == "客迹"
    assert SystemSetting.objects.count() == 1


@pytest.mark.django_db
def test_get_setting_returns_default_when_missing() -> None:
    assert get_setting("no_such_key", default="fallback") == "fallback"
    assert get_setting("no_such_key") is None


@pytest.mark.django_db
def test_set_setting_updates_existing_key() -> None:
    set_setting("key_a", 1)
    set_setting("key_a", 2, label="新标签")

    assert get_setting("key_a") == 2
    assert SystemSetting.objects.count() == 1
    assert SystemSetting.objects.get(key="key_a").label == "新标签"


@pytest.mark.django_db
def test_get_setting_serves_from_cache() -> None:
    set_setting("key_b", {"v": 1})
    assert get_setting("key_b") == {"v": 1}  # 预热缓存

    # 绕过服务直接改库：缓存未失效时，读到的仍是旧值，证明命中缓存。
    SystemSetting.objects.filter(key="key_b").update(value={"v": 2})

    assert get_setting("key_b") == {"v": 1}


@pytest.mark.django_db
def test_set_setting_invalidates_cache() -> None:
    set_setting("key_c", "old")
    assert get_setting("key_c") == "old"

    set_setting("key_c", "new")

    assert cache.get("system_setting:key_c") is None
    assert get_setting("key_c") == "new"


@pytest.mark.django_db
def test_get_all_settings_returns_key_value_map() -> None:
    set_setting("a", 1)
    set_setting("b", "two")

    assert get_all_settings() == {"a": 1, "b": "two"}


def test_set_setting_rejects_non_string_key() -> None:
    with pytest.raises(TypeError):
        set_setting(123, "x")


def test_get_setting_rejects_non_string_key() -> None:
    with pytest.raises(TypeError):
        get_setting(["not", "a", "string"])


def test_set_setting_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        set_setting("", "x")
