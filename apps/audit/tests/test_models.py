"""AuditLog 模型测试（T10.2，RED 先行，规格 §17 / §18）。

- 字段完整性：actor / action / object_type / object_pk / target_label /
  result / detail / ip_address / user_agent；
- 索引：(actor, created_at)、(action, created_at)、(object_type, object_pk)；
- 审计日志不软删（规格 §18 后半）：无 is_deleted 字段，delete() 即物理删除，
  审计记录管理另由清理命令承担，本任务不实现。
"""

import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator() -> User:
    u = User(username="operator", can_view_audit_logs=True)
    u.save()
    return u


def test_str_includes_actor_action_and_created_at(operator: User) -> None:
    log = AuditLog.objects.create(
        actor=operator, action="customer.soft_delete", target_label="张三"
    )

    assert str(log) == f"{operator} customer.soft_delete @ {log.created_at}"


def test_indexes_cover_query_hot_paths() -> None:
    index_field_lists = {tuple(idx.fields) for idx in AuditLog._meta.indexes}

    assert ("actor", "created_at") in index_field_lists
    assert ("action", "created_at") in index_field_lists
    assert ("object_type", "object_pk") in index_field_lists


def test_action_field_is_db_indexed() -> None:
    assert AuditLog._meta.get_field("action").db_index


def test_defaults() -> None:
    log = AuditLog.objects.create(action="export")

    assert log.actor is None
    assert log.result == "success"
    assert log.detail == {}
    assert log.object_type == ""
    assert log.object_pk == ""
    assert log.target_label == ""
    assert log.ip_address is None
    assert log.user_agent == ""


def test_audit_log_is_not_soft_deleted(operator: User) -> None:
    """审计日志模型不继承 SoftDeleteModel：不随业务对象删除而消失（§18）。"""
    log = AuditLog.objects.create(actor=operator, action="customer.soft_delete", object_pk="x")

    assert not hasattr(AuditLog, "is_deleted")
    assert log.delete() == (1, {"audit.AuditLog": 1})
    assert not AuditLog.objects.filter(pk=log.pk).exists()
