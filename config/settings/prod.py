"""prod settings — 生产部署。

强制关闭 DEBUG，安全 Cookie 默认开启（可用环境变量关闭），
并配置反向代理（nginx）的 HTTPS 透传头。
"""

from .base import *  # noqa: F403
from .base import _env_bool

# 生产环境禁止开启 DEBUG（避免泄露源码、配置与密钥）。
DEBUG: bool = False

SESSION_COOKIE_SECURE: bool = _env_bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE: bool = _env_bool("CSRF_COOKIE_SECURE", default=True)

# nginx 反代后，确保 Django 认可 HTTPS（X-Forwarded-Proto）。
SECURE_PROXY_SSL_HEADER: tuple[str, str] = ("HTTP_X_FORWARDED_PROTO", "https")
