"""材料清单模板种子（规格 §12 / REQ-CLAIM-002）。

按理赔类型预设常见材料：医疗/意外两套完整，其余类型示例 1-3 项。
幂等：同名（同 claim_type）模板已存在则跳过；可回滚。
"""

from typing import Any

from django.db import migrations

#: 各理赔类型的默认材料清单，顺序即 sort_order。
DEFAULT_MATERIAL_TEMPLATES: dict[str, list[str]] = {
    "medical": [
        "理赔申请书",
        "身份证件",
        "银行卡",
        "诊断证明",
        "医疗费用发票",
        "费用清单",
        "病历资料",
    ],
    "accident": [
        "理赔申请书",
        "身份证件",
        "银行卡",
        "诊断证明",
        "医疗费用发票",
        "费用清单",
        "病历资料",
        "事故证明",
    ],
    "critical_illness": ["诊断证明", "病理报告"],
    "death": ["死亡证明", "户口注销证明", "受益人身份证明"],
    "annuity": ["保险合同", "身份证件", "银行卡"],
    "other": ["理赔申请书"],
}


def seed_claim_material_templates(apps: Any, schema_editor: Any) -> None:
    """插入默认材料模板；已存在（同 claim_type + name）则跳过。"""
    template = apps.get_model("claims", "ClaimMaterialTemplate")
    for claim_type, names in DEFAULT_MATERIAL_TEMPLATES.items():
        for sort_order, name in enumerate(names):
            template.objects.get_or_create(
                claim_type=claim_type,
                name=name,
                defaults={"is_required": True, "sort_order": sort_order},
            )


def unseed_claim_material_templates(apps: Any, schema_editor: Any) -> None:
    """回滚：删除默认模板（唯一约束保证匹配的行即种子行）。"""
    template = apps.get_model("claims", "ClaimMaterialTemplate")
    for claim_type, names in DEFAULT_MATERIAL_TEMPLATES.items():
        template.objects.filter(claim_type=claim_type, name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("claims", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            seed_claim_material_templates, unseed_claim_material_templates
        ),
    ]
