"""record_audit 服务测试（T10.2，RED 先行，规格 §17 / §18）。

- 正常记录字段齐全；
- request 提供时自动提取 IP / User-Agent；
- detail 敏感字段脱敏：key 含 password / secret / id_card / bank 的值置为 "***"，
  绝不记录完整密码 / 密钥 / 身份证 / 银行卡；
- 创建失败绝不影响业务：异常被吞掉并返回 None。
"""

import pytest
from django.test import RequestFactory

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import record_audit

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator() -> User:
    u = User(username="operator", can_view_audit_logs=True)
    u.save()
    return u


def test_record_with_actor_and_detail(operator: User) -> None:
    log = record_audit(
        actor=operator,
        action="policy.change_status",
        object_type="policies.policy",
        object_pk=str(operator.pk),
        target_label="P-2026-001",
        detail={"from_status": "active", "to_status": "lapsed"},
    )

    assert log is not None
    assert log.actor == operator
    assert log.action == "policy.change_status"
    assert log.object_type == "policies.policy"
    assert log.target_label == "P-2026-001"
    assert log.result == "success"
    assert log.detail == {"from_status": "active", "to_status": "lapsed"}


def test_record_without_actor_allows_null(operator: User) -> None:
    log = record_audit(action="export")

    assert log is not None
    assert log.actor is None


def test_record_extracts_ip_and_user_agent_from_request(operator: User) -> None:
    request = RequestFactory().get("/", HTTP_USER_AGENT="keji-test/1.0")
    request.META["REMOTE_ADDR"] = "203.0.113.9"

    log = record_audit(actor=operator, action="export", request=request)

    assert log is not None
    assert log.ip_address == "203.0.113.9"
    assert log.user_agent == "keji-test/1.0"


def test_record_sanitizes_sensitive_detail_keys(operator: User) -> None:
    log = record_audit(
        actor=operator,
        action="user.create",
        detail={"password": "x", "id_card_no": "y", "bank_account": "z", "ok": "safe"},
    )

    assert log is not None
    assert log.detail == {
        "password": "***",
        "id_card_no": "***",
        "bank_account": "***",
        "ok": "safe",
    }


def test_record_swallows_create_failure(operator: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """审计落库失败不能阻断业务主流程：吞掉异常并返回 None。"""

    def boom(**kwargs: object) -> AuditLog:
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditLog.objects, "create", boom)

    assert record_audit(actor=operator, action="export") is None
    assert AuditLog.objects.count() == 0
