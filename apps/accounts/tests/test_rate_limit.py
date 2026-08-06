"""登录限流测试（缓存实现，services/rate_limit.py + RateLimitedLoginView）。

覆盖：
- check_login_allowed：初始放行、剩余次数递减、上限后锁定（remaining=0）
- record_login_failure / clear_login_failures：计数与复位
- 键隔离：(ip, username) 组合互不影响
- 缓存到期自动恢复（用 cache.touch(key, 0) 模拟到期，不 sleep）
- 视图全链路：第 6 次尝试（即使密码正确）被拒并提示锁定；成功登录后重置；
  不同 IP 互不影响
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services.rate_limit import (
    check_login_allowed,
    clear_login_failures,
    record_login_failure,
)

IP = "127.0.0.1"


@pytest.fixture(autouse=True)
def _isolated_cache() -> Iterator[None]:
    """LocMemCache 跨测试共享，先清空再退出，避免失败计数泄漏到别的测试。"""
    cache.clear()
    yield
    cache.clear()


def _failure_key(ip: str, username: str) -> str:
    return f"login_fail:{ip}:{username}"


# ---------------------------------------------------------------------------
# 服务层：check_login_allowed / record_login_failure / clear_login_failures
# ---------------------------------------------------------------------------


def test_check_login_allowed_allows_initial_attempt() -> None:
    allowed, remaining = check_login_allowed(IP, "alice")

    assert allowed is True
    assert remaining == settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS


def test_check_login_allowed_reports_remaining_decreasing() -> None:
    record_login_failure(IP, "alice")

    allowed, remaining = check_login_allowed(IP, "alice")

    assert allowed is True
    assert remaining == settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS - 1


def test_locked_after_max_failures() -> None:
    for _ in range(settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        record_login_failure(IP, "alice")

    allowed, remaining = check_login_allowed(IP, "alice")

    assert allowed is False
    assert remaining == 0


def test_record_failure_accumulates_and_clear_resets() -> None:
    record_login_failure(IP, "alice")
    record_login_failure(IP, "alice")
    assert cache.get(_failure_key(IP, "alice")) == 2

    clear_login_failures(IP, "alice")

    assert cache.get(_failure_key(IP, "alice")) is None
    assert check_login_allowed(IP, "alice")[0] is True


def test_failures_isolated_by_ip_and_username() -> None:
    for _ in range(settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        record_login_failure(IP, "alice")

    assert check_login_allowed("198.51.100.9", "alice")[0] is True
    assert check_login_allowed(IP, "bob")[0] is True
    assert check_login_allowed(IP, "alice")[0] is False


def test_allowed_again_after_cache_entry_expires() -> None:
    for _ in range(settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        record_login_failure(IP, "alice")
    assert check_login_allowed(IP, "alice")[0] is False

    # 模拟窗口到期：timeout=0 → 条目立即过期，下次读取自动清空。
    cache.touch(_failure_key(IP, "alice"), 0)

    allowed, remaining = check_login_allowed(IP, "alice")

    assert allowed is True
    assert remaining == settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# 视图全链路：RateLimitedLoginView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sixth_attempt_locked_even_with_correct_password(client: Any) -> None:
    User.objects.create_user(username="alice", password="correct-password")
    url = reverse("accounts:login")

    for _ in range(settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        resp = client.post(url, {"username": "alice", "password": "wrong-password"})
        assert resp.status_code == 200

    resp = client.post(url, {"username": "alice", "password": "correct-password"})

    assert resp.status_code == 200
    assert "尝试次数过多" in resp.content.decode()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_successful_login_resets_failure_count(client: Any) -> None:
    User.objects.create_user(username="alice", password="correct-password")
    url = reverse("accounts:login")
    for _ in range(2):
        client.post(url, {"username": "alice", "password": "wrong-password"})

    resp = client.post(url, {"username": "alice", "password": "correct-password"})

    assert resp.status_code == 302
    allowed, remaining = check_login_allowed(IP, "alice")
    assert allowed is True
    assert remaining == settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS


@pytest.mark.django_db
def test_failed_attempts_from_different_ips_are_independent(client: Any) -> None:
    User.objects.create_user(username="alice", password="correct-password")
    url = reverse("accounts:login")

    for _ in range(settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        client.post(
            url,
            {"username": "alice", "password": "wrong-password"},
            REMOTE_ADDR="10.1.2.3",
        )
    assert check_login_allowed("10.1.2.3", "alice")[0] is False

    resp = client.post(
        url,
        {"username": "alice", "password": "correct-password"},
        REMOTE_ADDR="10.9.8.7",
    )

    assert resp.status_code == 302
    assert "_auth_user_id" in client.session
