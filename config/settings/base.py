"""base settings — dev/prod 共享配置。

所有机密 / 环境相关值一律从环境变量读取，并给出本地开发默认值，
保证不配置 .env 也能在开发环境跑通（默认值匹配 docker/dev/compose.yaml）。
"""

from __future__ import annotations

import os
from pathlib import Path

# 项目根目录：config/settings/base.py 上溯三级。
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    """把环境变量解析为布尔值；未设置时返回 default。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> list[str]:
    """把逗号分隔的环境变量解析为非空字符串列表。"""
    raw = os.environ.get(name, default)
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


# ---------------------------------------------------------------------------
# 核心
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.environ.get("SECRET_KEY", "django-insecure-dev-placeholder")

# 开发默认 True；prod.py 中强制 False。
DEBUG: bool = _env_bool("DEBUG", default=True)

ALLOWED_HOSTS: list[str] = _env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.accounts",
    "apps.core",
    "apps.customers",
    "apps.activities",
    "apps.documents",
    "apps.policies",
    "apps.claims",
    "apps.tasks",
    "apps.dashboard",
    "apps.audit",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF: str = "config.urls"

TEMPLATES: list[dict[str, object]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION: str = "config.wsgi.application"
ASGI_APPLICATION: str = "config.asgi.application"

# ---------------------------------------------------------------------------
# 数据库（默认值匹配 docker/dev/compose.yaml 的本地开发容器）
# ---------------------------------------------------------------------------

DATABASES: dict[str, dict[str, object]] = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "keji"),
        "USER": os.environ.get("DB_USER", "keji"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "keji"),
        "CONN_MAX_AGE": 60,
    }
}

# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------

AUTH_USER_MODEL: str = "accounts.User"

# 登录限流（.env 格式 "5/15m"，单位支持 s/m/h；django-axes 风格，见 .env.example）。
_LOGIN_RATE_LIMIT_RAW: str = os.environ.get("LOGIN_RATE_LIMIT", "5/15m")


def _parse_rate_limit(raw: str) -> tuple[int, int]:
    """解析 "5/15m" → (5, 900)。窗口单位支持 s / m / h。"""
    attempts, window = raw.split("/")
    value, unit = int(window[:-1]), window[-1]
    multiplier = {"s": 1, "m": 60, "h": 3600}[unit]
    return int(attempts), value * multiplier


LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int
LOGIN_RATE_LIMIT_WINDOW_SECONDS: int
LOGIN_RATE_LIMIT_MAX_ATTEMPTS, LOGIN_RATE_LIMIT_WINDOW_SECONDS = _parse_rate_limit(
    _LOGIN_RATE_LIMIT_RAW
)

# ---------------------------------------------------------------------------
# 国际化（面向台湾繁体用户，中文后端）
# ---------------------------------------------------------------------------

LANGUAGE_CODE: str = "zh-hans"
TIME_ZONE: str = "Asia/Taipei"
USE_I18N: bool = True
USE_TZ: bool = True

# ---------------------------------------------------------------------------
# 静态文件与媒体
# ---------------------------------------------------------------------------

STATIC_URL: str = "/static/"
STATICFILES_DIRS: list[Path] = [BASE_DIR / "static"]
STATIC_ROOT: Path = BASE_DIR / "staticfiles"

MEDIA_URL: str = "/media/"
MEDIA_ROOT: Path = Path(os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media")))

# ---------------------------------------------------------------------------
# 杂项
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

LOGIN_URL: str = "/accounts/login/"
LOGIN_REDIRECT_URL: str = "/"
LOGOUT_REDIRECT_URL: str = "/accounts/login/"

ADMIN_URL: str = os.environ.get("ADMIN_URL", "admin")
