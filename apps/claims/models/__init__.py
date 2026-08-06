"""claims 模型包：ClaimCase、ClaimMaterial、ClaimMaterialTemplate（规格 §12）。"""

from apps.claims.models.case import CLAIM_STATUS_CHOICES, CLAIM_TYPES, ClaimCase
from apps.claims.models.material import MATERIAL_STATUS_CHOICES, ClaimMaterial
from apps.claims.models.template import ClaimMaterialTemplate

__all__ = [
    "CLAIM_STATUS_CHOICES",
    "CLAIM_TYPES",
    "ClaimCase",
    "ClaimMaterial",
    "ClaimMaterialTemplate",
    "MATERIAL_STATUS_CHOICES",
]
