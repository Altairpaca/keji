"""claims 服务包（T8.1，规格 §12）。"""

from apps.claims.services.claims import (
    CLAIM_STATUS_TRANSITIONS,
    MATERIAL_STATUS_TRANSITIONS,
    change_claim_status,
    change_material_status,
    create_claim,
    create_material,
    instantiate_template,
    material_completion_ratio,
    missing_materials,
    restore_claim,
    soft_delete_claim,
    update_claim,
)

__all__ = [
    "CLAIM_STATUS_TRANSITIONS",
    "MATERIAL_STATUS_TRANSITIONS",
    "change_claim_status",
    "change_material_status",
    "create_claim",
    "create_material",
    "instantiate_template",
    "material_completion_ratio",
    "missing_materials",
    "restore_claim",
    "soft_delete_claim",
    "update_claim",
]
