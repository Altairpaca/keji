"""claims 表单：案件 / 材料创建编辑 + 状态流转（规格 §12）。

表单负责 HTTP 边界校验；写操作全部经 services（create_claim / update_claim /
create_material / change_claim_status / change_material_status）。

- ClaimForm 排除 owner / status —— owner 由视图自动设为当前用户，状态流转走
  独立 change_status 视图；policy 可空（咨询阶段可能无保单）；
- MaterialForm 排除 claim / status —— claim 由 URL 注入，状态流转走独立视图；
- ChangeClaimStatusForm / ChangeMaterialStatusForm 的 new_status 选项只列
  合法迁移目标，非法目标在选项校验层即被拒绝。
"""

from django import forms

from apps.claims.models import (
    CLAIM_STATUS_CHOICES,
    MATERIAL_STATUS_CHOICES,
    ClaimCase,
    ClaimMaterial,
)
from apps.claims.services.claims import (
    CLAIM_STATUS_TRANSITIONS,
    MATERIAL_STATUS_TRANSITIONS,
)
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.policies.models import Policy


class ClaimForm(forms.ModelForm):
    """理赔案件创建 / 编辑表单：全部可编辑字段（不含 owner / status）。

    - ``customer`` 必填；
    - ``policy`` 可空（客户咨询阶段可能尚无对应保单）；
    - 金额为 Decimal 字段，模板侧用 floatformat:2 渲染。
    """

    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        label="客户",
        required=True,
    )
    policy = forms.ModelChoiceField(
        queryset=Policy.objects.all(),
        label="关联保单",
        required=False,
        empty_label="暂未关联保单",
    )

    class Meta:
        model = ClaimCase
        fields = [
            "name",
            "customer",
            "policy",
            "claim_type",
            "incident_date",
            "report_date",
            "estimated_amount",
            "description",
        ]
        widgets = {
            "incident_date": forms.DateInput(attrs={"type": "date"}),
            "report_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"


class MaterialForm(forms.ModelForm):
    """材料表单：名称 / 必需 / 备注 / 关联文件（可空）。claim 与 status 由视图处理。"""

    document = forms.ModelChoiceField(
        queryset=Document.objects.all(),
        label="关联文件",
        required=False,
        empty_label="暂无关联文件",
    )

    class Meta:
        model = ClaimMaterial
        fields = ["name", "is_required", "note", "document"]
        widgets = {
            "note": forms.TextInput(attrs={"placeholder": "补充说明（可选）"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"


class ChangeClaimStatusForm(forms.Form):
    """案件状态流转表单：目标下拉只含当前状态的合法迁移目标。

    构造参数：``ChangeClaimStatusForm(claim, POST_data_or_None)`` —— 选项随
    案件当前状态动态生成（closed 终态的选项为空集，任何提交都会校验失败）。
    """

    new_status = forms.ChoiceField(label="变更到")

    def __init__(self, claim: ClaimCase, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        legal_targets = set(CLAIM_STATUS_TRANSITIONS.get(str(claim.status), set()))
        self.fields["new_status"].choices = [
            (value, label) for value, label in CLAIM_STATUS_CHOICES if value in legal_targets
        ]
        self.fields["new_status"].widget.attrs["class"] = "input"


class ChangeMaterialStatusForm(forms.Form):
    """材料状态流转表单：目标下拉只含当前状态的合法迁移目标。

    构造参数：``ChangeMaterialStatusForm(material, POST_data_or_None)``。
    """

    new_status = forms.ChoiceField(label="变更到")

    def __init__(self, material: ClaimMaterial, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        legal_targets = set(MATERIAL_STATUS_TRANSITIONS.get(str(material.status), set()))
        self.fields["new_status"].choices = [
            (value, label) for value, label in MATERIAL_STATUS_CHOICES if value in legal_targets
        ]
        self.fields["new_status"].widget.attrs["class"] = "input"
