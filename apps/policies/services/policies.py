"""policies 服务层：保单创建、状态迁移、更新、软删、历史（T7.1，规格 §4.5）。

状态迁移图集中在 STATUS_TRANSITIONS；change_status 在事务内同时更新 status
并追加 PolicyStatusHistory（append-only），保证状态与历史原子一致。
"""

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.policies.models import Policy, PolicyStatusHistory

# 合法状态迁移图：value → 可到达的 value 集合。
# 语义：status_pending 可转任何状态（除自身）；终态（terminated/surrendered）
# 只能回到 status_pending，交由人工核实后重新流入。
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "active": {
        "paying",
        "paid_up",
        "lapsed",
        "reinstating",
        "surrendered",
        "terminated",
        "matured",
        "claim_closed",
        "status_pending",
    },
    "paying": {"active", "paid_up", "lapsed", "surrendered", "terminated", "status_pending"},
    "paid_up": {"active", "status_pending"},
    "lapsed": {"reinstating", "terminated", "status_pending"},
    "reinstating": {"active", "lapsed", "status_pending"},
    "surrendered": {"status_pending"},
    "terminated": set(),
    "matured": {"status_pending"},
    "claim_closed": {"active", "status_pending"},
    "status_pending": {
        "active",
        "paying",
        "paid_up",
        "lapsed",
        "reinstating",
        "surrendered",
        "terminated",
        "matured",
        "claim_closed",
    },
}


def create_policy(**kw: object) -> Policy:
    """创建保单：保单号必填且唯一；首次创建不产生状态历史。"""
    raw_no = kw.get("policy_no")
    policy_no = str(raw_no).strip() if raw_no is not None else ""
    if not policy_no:
        raise ValueError("保单号不能为空")
    kw["policy_no"] = policy_no
    try:
        with transaction.atomic():
            policy: Policy = Policy.objects.create(**kw)
            return policy
    except IntegrityError:
        raise ValueError("保单号已存在") from None


def change_status(
    *,
    policy: Policy,
    new_status: str,
    changed_by: User | None = None,
    note: str = "",
) -> Policy:
    """变更保单状态：校验合法迁移，事务内更新状态并写 append-only 历史。"""
    from_status = str(policy.status)
    if new_status not in STATUS_TRANSITIONS.get(from_status, set()):
        raise ValueError(f"非法状态迁移：{from_status} → {new_status}")
    with transaction.atomic():
        PolicyStatusHistory.objects.create(
            policy=policy,
            from_status=from_status,
            to_status=new_status,
            changed_by=changed_by,
            note=note,
        )
        policy.status = new_status
        policy.save(update_fields=["status", "updated_at"])
        record_audit(
            actor=changed_by,
            action="policy.change_status",
            object_type=policy._meta.label_lower,
            object_pk=str(policy.pk),
            target_label=policy.policy_no,
            detail={"from_status": from_status, "to_status": new_status},
        )
    return policy


def update_policy(policy: Policy, **fields: object) -> Policy:
    """部分更新并保存；未知字段拒绝，避免拼写错误静默失效。"""
    for field, value in fields.items():
        if not hasattr(policy, field):
            raise ValueError(f"未知字段：{field}")
        setattr(policy, field, value)
    policy.save()
    return policy


def soft_delete_policy(policy: Policy) -> Policy:
    """软删除保单（ADR-006 第 1 级）。"""
    return policy.soft_delete()


def restore_policy(policy: Policy) -> Policy:
    """恢复软删除的保单。"""
    return policy.restore()


def get_history(policy: Policy) -> QuerySet:
    """保单状态历史，按创建时间倒序。"""
    return policy.status_history.order_by("-created_at")
