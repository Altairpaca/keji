"""核心安全测试（security.md §5 + 规格 §17/§22）：HTTP 安全头 / Cookie 加固 / 管理后台 URL。

- HTTP 响应头：X-Content-Type-Options nosniff、Referrer-Policy same-origin、
  X-Frame-Options DENY（SecurityMiddleware 经 settings 配置驱动）；
- Cookie：sessionid / csrftoken 均 HttpOnly + SameSite=Lax；
- 管理后台 URL：默认 /admin/ 可访问；ADMIN_URL 换为非标准路径后旧路径 404、
  新路径可访问（防 URL 枚举，规格 §17）。
"""

import importlib
import os
import subprocess
import sys
from typing import Any

import pytest
from django.conf import settings
from django.urls import clear_url_caches

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# HTTP 安全头（SecurityMiddleware）
# ---------------------------------------------------------------------------


def test_response_sends_nosniff_and_referrer_policy(client: Any) -> None:
    response = client.get("/accounts/login/")

    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"


def test_response_denies_frame_embedding(client: Any) -> None:
    response = client.get("/accounts/login/")

    assert response["X-Frame-Options"] == "DENY"


def test_session_cookie_http_only_and_samesite(client: Any) -> None:
    User.objects.create_user(username="header-user", password="pw")

    resp = client.post("/accounts/login/", {"username": "header-user", "password": "pw"})

    assert resp.status_code == 302
    cookie = resp.cookies["sessionid"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


def test_csrf_cookie_http_only_and_samesite(client: Any) -> None:
    client.get("/accounts/login/")

    cookie = client.cookies["csrftoken"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


def test_security_settings_configured() -> None:
    """base 配置基线：响应头相关开关显式开启（防未来被无意关闭）。"""
    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert settings.SECURE_REFERRER_POLICY == "same-origin"
    assert settings.X_FRAME_OPTIONS == "DENY"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.CSRF_COOKIE_HTTPONLY is True


# ---------------------------------------------------------------------------
# 管理后台 URL（ADMIN_URL 来自环境变量，默认 "admin"，规格 §17 防枚举）
# ---------------------------------------------------------------------------


def test_admin_accessible_at_default_url(client: Any) -> None:
    # 登录页直接渲染 200；index 未认证时 302 → /admin/login/
    assert client.get("/admin/login/").status_code == 200
    assert client.get("/admin/").status_code == 302


def test_admin_url_follows_setting_in_urlconf() -> None:
    """urls.py 的前缀由 settings.ADMIN_URL 驱动（改动设置即改入口）。"""
    from config import urls as urlconf

    admin_paths = [str(p.pattern) for p in urlconf.urlpatterns if "admin" in str(p.pattern)]
    assert admin_paths == [f"{settings.ADMIN_URL}/"]


def test_custom_admin_url_works_and_old_path_404s(client: Any) -> None:
    """ADMIN_URL 换为非标准路径：新路径可访问，旧 /admin/ 变 404（防枚举）。"""
    from config import urls as urlconf

    original = settings.ADMIN_URL
    settings.ADMIN_URL = "super-secret-console"
    clear_url_caches()
    importlib.reload(urlconf)
    try:
        assert client.get("/super-secret-console/login/").status_code == 200
        assert client.get("/admin/login/").status_code == 404
    finally:
        settings.ADMIN_URL = original
        clear_url_caches()
        importlib.reload(urlconf)


# ---------------------------------------------------------------------------
# 生产 settings：禁止明文/缺省 SECRET_KEY（配置从 env 读，缺省仅限 dev）
# ---------------------------------------------------------------------------


def test_prod_settings_refuse_missing_secret_key() -> None:
    """prod settings 在缺少 SECRET_KEY 环境变量时启动即失败（ImproperlyConfigured）。"""
    env = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"}
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
    result = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
