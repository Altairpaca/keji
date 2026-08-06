"""审计记录服务（规格 §17 / §18，T10.2）。

``record_audit`` 是全部审计写入的唯一入口（业务服务用 import 调用，不引 signals）：
- request 提供时自动提取 IP 与 User-Agent；
- detail 统一脱敏：key 含 password / secret / id_card / bank 的值替换为 "***"，
  绝不在审计里留下完整敏感数据；
- 创建失败绝不抛出：审计失败不应中断业务主流程（try/except 包住并吞掉）。

备份命令（T11）接入点在 services 之外的 core 管理命令，届时调用
``record_audit(action="backup", ...)`` 即可，本任务留调用点。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.http import HttpRequest

from apps.accounts.models import User
from apps.audit.models import AuditLog

#: detail 的 key 命中以下子串（不区分大小写）即视为敏感字段，值一律脱敏。
_SENSITIVE_KEY_PARTS: tuple[str, ...] = ("password", "secret", "id_card", "bank")


def _sanitize_detail(detail: Mapping[str, Any] | None) -> dict[str, Any]:
    """把 detail 中敏感 key 的值替换为 ``"***"``；key 本身保留便于审计定位。"""
    if not detail:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in detail.items():
        if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
            cleaned[key] = "***"
        else:
            cleaned[key] = value
    return cleaned


def record_audit(
    *,
    actor: User | None = None,
    action: str,
    object_type: str = "",
    object_pk: str = "",
    target_label: str = "",
    result: str = "success",
    detail: Mapping[str, Any] | None = None,
    request: HttpRequest | None = None,
) -> AuditLog | None:
    """写入一条审计日志；失败返回 None 且绝不抛出（审计不能阻断业务）。

    ``request`` 非空时自动从 META 提取 REMOTE_ADDR 与 HTTP_USER_AGENT。
    """
    ip_address: str | None = None
    user_agent = ""
    if request is not None:
        ip_address = request.META.get("REMOTE_ADDR") or None
        user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:255]
    try:
        # 独立保存点：即使外层业务事务中落库失败，也只回滚到本保存点，
        # 不污染外层事务，业务主流程可继续。
        with transaction.atomic():
            created: AuditLog = AuditLog.objects.create(
                actor=actor,
                action=action,
                object_type=object_type,
                object_pk=object_pk,
                target_label=target_label,
                result=result,
                detail=_sanitize_detail(detail),
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return created
    except Exception:
        # 审计失败不应中断业务主流程（规格 §18 审计为附属记录）。
        return None
