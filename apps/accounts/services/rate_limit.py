"""登录限流服务（缓存实现）。

基于 ``django.core.cache``（开发环境 LocMemCache，生产可切 Redis 后端）。
键 ``login_fail:{ip}:{username}``，窗口 ``LOGIN_RATE_LIMIT_WINDOW_SECONDS``，
上限 ``LOGIN_RATE_LIMIT_MAX_ATTEMPTS``（见 config/settings/base.py），
到期由缓存层自动清理，无需手动任务。

不引入第三方限流库（django-ratelimit 等）：自托管场景手写缓存计数足够。
"""

from django.conf import settings
from django.core.cache import cache


def _failure_key(ip: str, username: str) -> str:
    return f"login_fail:{ip}:{username}"


def check_login_allowed(ip: str, username: str) -> tuple[bool, int]:
    """返回 (是否允许本次登录尝试, 剩余可用次数)。

    - 允许：剩余 = 上限 - 当前失败计数；
    - 锁定：剩余 = 0（失败计数已达上限）。
    """
    limit = settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS
    failures = int(cache.get(_failure_key(ip, username), 0))
    if failures >= limit:
        return False, 0
    return True, limit - failures


def record_login_failure(ip: str, username: str) -> None:
    """记录一次登录失败；计数在窗口过期后自动归零。"""
    key = _failure_key(ip, username)
    failures = int(cache.get(key, 0)) + 1
    cache.set(key, failures, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)


def clear_login_failures(ip: str, username: str) -> None:
    """登录成功后清零失败计数。"""
    cache.delete(_failure_key(ip, username))
