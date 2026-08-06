"""claims 服务层：理赔案件/材料创建、状态迁移、模板实例化（T8.1，规格 §12）。

状态迁移图集中在 CLAIM_STATUS_TRANSITIONS / MATERIAL_STATUS_TRANSITIONS；
非法迁移一律抛 ValueError，合法迁移由各 change_* 函数落库。
"""

from datetime import date

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.claims.models import ClaimCase, ClaimMaterial, ClaimMaterialTemplate
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.policies.models import Policy

#: 理赔案件合法状态迁移图：value → 可到达的 value 集合（规格 §12，14 态）。
#: closed 为终态（∅），其余状态语义见模型 choices 注释。
CLAIM_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "consultation": {"waiting_materials", "collecting_materials", "reported", "closed"},
    "waiting_materials": {
        "collecting_materials",
        "materials_incomplete",
        "submitted",
        "closed",
    },
    "collecting_materials": {
        "waiting_materials",
        "materials_pending_review",
        "materials_incomplete",
        "submitted",
        "closed",
    },
    "materials_pending_review": {"collecting_materials", "submitted", "requested_supplement"},
    "materials_incomplete": {"collecting_materials", "waiting_materials", "closed"},
    "reported": {"submitted", "insurer_reviewing", "closed"},
    "submitted": {
        "insurer_reviewing",
        "requested_supplement",
        "approved",
        "partial_paid",
        "rejected",
        "closed",
    },
    "insurer_reviewing": {
        "submitted",
        "requested_supplement",
        "approved",
        "partial_paid",
        "rejected",
        "closed",
    },
    "requested_supplement": {"collecting_materials", "submitted", "closed"},
    "approved": {"partial_paid", "closed"},
    "partial_paid": {"approved", "closed"},
    "rejected": {"disputing", "closed"},
    "disputing": {"submitted", "rejected", "closed"},
    "closed": set(),
}

#: 理赔材料合法状态迁移图：value → 可到达的 value 集合（规格 §12，6 态）。
MATERIAL_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "not_submitted": {"submitted", "not_applicable"},
    "submitted": {"pending_review", "needs_supplement", "checked", "not_applicable"},
    "pending_review": {"checked", "needs_supplement", "submitted", "not_applicable"},
    "checked": {"needs_supplement"},
    "needs_supplement": {"submitted", "not_applicable"},
    "not_applicable": {"submitted"},
}


# ---------------------------------------------------------------------------
# 理赔案件
# ---------------------------------------------------------------------------


def create_claim(
    *,
    name: str,
    customer: Customer | None,
    policy: Policy | None = None,
    claim_type: str = "other",
    incident_date: date | None = None,
    report_date: date | None = None,
    owner: User | None = None,
    description: str = "",
) -> ClaimCase:
    """创建理赔案件：名称与客户必填；咨询阶段可无保单，首次不建材料。"""
    stripped_name = name.strip()
    if not stripped_name:
        raise ValueError("名称不能为空")
    if customer is None:
        raise ValueError("客户不能为空")
    claim: ClaimCase = ClaimCase.objects.create(
        name=stripped_name,
        customer=customer,
        policy=policy,
        claim_type=claim_type,
        incident_date=incident_date,
        report_date=report_date,
        owner=owner,
        description=description,
    )
    return claim


def change_claim_status(
    *,
    claim: ClaimCase,
    new_status: str,
    changed_by: User | None = None,  # noqa: ARG002 -- 预留：签名与材料一致，案件暂无历史表
) -> ClaimCase:
    """变更案件状态：非法迁移抛 ValueError；进入 closed 落 closed_at。"""
    from_status = str(claim.status)
    if new_status not in CLAIM_STATUS_TRANSITIONS.get(from_status, set()):
        raise ValueError(f"非法状态迁移：{from_status} → {new_status}")
    claim.status = new_status
    if new_status == "closed":
        claim.closed_at = timezone.now()
    elif claim.closed_at is not None:
        # 防御：closed 为终态正常无法离开，但若历史数据异常则同步清空结案时间。
        claim.closed_at = None
    claim.save(update_fields=["status", "closed_at", "updated_at"])
    return claim


def update_claim(claim: ClaimCase, **fields: object) -> ClaimCase:
    """部分更新并保存；未知字段拒绝，避免拼写错误静默失效。"""
    for field, value in fields.items():
        if not hasattr(claim, field):
            raise ValueError(f"未知字段：{field}")
        setattr(claim, field, value)
    claim.save()
    return claim


def soft_delete_claim(claim: ClaimCase) -> ClaimCase:
    """软删除理赔案件（ADR-006 第 1 级）。"""
    return claim.soft_delete()


def restore_claim(claim: ClaimCase) -> ClaimCase:
    """恢复软删除的理赔案件。"""
    return claim.restore()


# ---------------------------------------------------------------------------
# 理赔材料
# ---------------------------------------------------------------------------


def create_material(
    *,
    claim: ClaimCase,
    name: str,
    is_required: bool = True,
    document: Document | None = None,
) -> ClaimMaterial:
    """创建材料：同案件同名材料（未软删）不允许重复。"""
    if claim.materials.filter(name=name).exists():
        raise ValueError("材料已存在")
    material: ClaimMaterial = ClaimMaterial.objects.create(
        claim=claim,
        name=name,
        is_required=is_required,
        document=document,
    )
    return material


def change_material_status(
    *,
    material: ClaimMaterial,
    new_status: str,
    changed_by: User | None = None,
) -> ClaimMaterial:
    """变更材料状态：非法迁移抛 ValueError；checked 记录核对人/时间，离开清空。"""
    from_status = str(material.status)
    if new_status not in MATERIAL_STATUS_TRANSITIONS.get(from_status, set()):
        raise ValueError(f"非法状态迁移：{from_status} → {new_status}")
    material.status = new_status
    if new_status == "checked":
        material.checked_by = changed_by
        material.checked_at = timezone.now()
    else:
        material.checked_by = None
        material.checked_at = None
    material.save(update_fields=["status", "checked_by", "checked_at", "updated_at"])
    return material


def missing_materials(claim: ClaimCase) -> QuerySet:
    """缺少资料队列（首页数据源）：未提交 + 需要补充。"""
    return claim.materials.filter(status__in=("not_submitted", "needs_supplement"))


def material_completion_ratio(claim: ClaimCase) -> float:
    """材料齐备度：checked + not_applicable 占总材料比例；无材料返回 0.0。"""
    total: int = claim.materials.count()
    if total == 0:
        return 0.0
    done: int = claim.materials.filter(status__in=("checked", "not_applicable")).count()
    return done / total


# ---------------------------------------------------------------------------
# 材料清单模板实例化
# ---------------------------------------------------------------------------


def instantiate_template(
    *,
    claim: ClaimCase,
    template: ClaimMaterialTemplate | QuerySet | None = None,
) -> list[ClaimMaterial]:
    """按 claim.claim_type 将模板实例化为材料；同名已存在则跳过（幂等）。

    template 缺省取该案件理赔类型的全部模板（按 sort_order）；也可传入单个
    模板或 QuerySet 限定实例化范围。
    """
    if template is None:
        templates: QuerySet = ClaimMaterialTemplate.objects.filter(
            claim_type=claim.claim_type
        ).order_by("sort_order")
    elif isinstance(template, ClaimMaterialTemplate):
        templates = ClaimMaterialTemplate.objects.filter(pk=template.pk)
    else:
        templates = template
    existing = set(claim.materials.values_list("name", flat=True))
    created: list[ClaimMaterial] = []
    with transaction.atomic():
        for item in templates:
            if item.name in existing:
                continue
            created.append(
                ClaimMaterial.objects.create(
                    claim=claim,
                    name=item.name,
                    is_required=item.is_required,
                )
            )
    return created
