"""PWA 基础测试：manifest、应用图标、Service Worker、离线错误页（规格 §4，ADR-014）。

只缓存应用壳（静态资源 + manifest + 导航页）与离线错误页，
不缓存任何编辑类数据（ADR-014）。
"""

import json
from pathlib import Path
from typing import Any

from django.contrib.staticfiles import finders
from PIL import Image

from apps.core.tests._pwa_icons import ICON_FILES

# 静态文件在测试客户端下经 StaticFilesHandler 提供（dev settings DEBUG=True）。


def _get_manifest(client: Any) -> dict[str, Any]:
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")
    data: dict[str, Any] = json.loads(resp.content)
    return data


def test_manifest_served_with_required_fields(client: Any) -> None:
    data = _get_manifest(client)

    assert data["name"] == "客迹"
    assert data["short_name"] == "客迹"
    assert data["lang"] == "zh-CN"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"
    assert data["display"] == "standalone"
    assert data["background_color"] == "#0f172a"
    assert data["theme_color"] == "#1d4ed8"

    icons = data["icons"]
    sizes = {icon["sizes"] for icon in icons}
    assert sizes == {"192x192", "512x512"}
    assert all(icon["type"] == "image/png" for icon in icons)


def test_manifest_icon_files_resolve(client: Any) -> None:
    data = _get_manifest(client)

    icons = data["icons"]
    for icon in icons:
        assert isinstance(icon["src"], str)
        relative = icon["src"].removeprefix("/static/")
        assert finders.find(relative) is not None


def test_icon_files_exist_and_are_valid_png() -> None:
    for name, expected_size in ICON_FILES.items():
        path = Path(finders.find(f"icons/{name}") or "")
        assert path.is_file(), f"图标缺失：{name}"
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            assert img.format == "PNG"
            assert img.size == (expected_size, expected_size), f"尺寸不符：{name}"


def test_service_worker_served_at_root(client: Any) -> None:
    resp = client.get("/sw.js")

    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/javascript"

    body = resp.content.decode()
    assert "cache.addAll" in body
    assert "/offline/" in body
    assert "/static/" in body
    assert "navigate" in body  # 导航回退逻辑存在


def test_offline_page_is_public(client: Any) -> None:
    resp = client.get("/offline/")

    assert resp.status_code == 200
    assert "离线" in resp.content.decode()
    assert "重试" in resp.content.decode()
