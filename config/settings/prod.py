"""prod settings — 生产部署。

强制关闭 DEBUG，安全 Cookie 默认开启（可用环境变量关闭），
配置反向代理（nginx）的 HTTPS 透传头；SECRET_KEY 必须由环境变量提供，
base 的占位默认值在 prod 一律拒绝（防误部署弱密钥）。
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import _env_bool

# 生产环境禁止开启 DEBUG（避免泄露源码、配置与密钥）。
DEBUG: bool = False

# base 的 "django-insecure-dev-placeholder" 仅限开发：prod 缺 SECRET_KEY 直接拒绝启动。
_SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not _SECRET_KEY or _SECRET_KEY == "django-insecure-dev-placeholder":
    raise ImproperlyConfigured("生产环境必须通过环境变量 SECRET_KEY 提供密钥（禁止使用开发占位值）")
SECRET_KEY = _SECRET_KEY

SESSION_COOKIE_SECURE: bool = _env_bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE: bool = _env_bool("CSRF_COOKIE_SECURE", default=True)

# nginx 反代后，确保 Django 认可 HTTPS（X-Forwarded-Proto）。
SECURE_PROXY_SSL_HEADER: tuple[str, str] = ("HTTP_X_FORWARDED_PROTO", "https")

# TLS 终止在 nginx 层完成，应用层不重复重定向（W008 由部署架构承接）。
SECURE_SSL_REDIRECT: bool = False
