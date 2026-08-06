"""policies 表单：PolicyForm（创建 / 编辑保单）+ PolicyStatusForm（状态流转）。

表单负责 HTTP 边界校验：
- PolicyForm 排除 owner / status —— owner 由视图自动设为当前用户，状态流转走
  独立 change_status 视图（保证历史 append-only），不混入普通编辑；
- policy_no 唯一校验在表单层先拦截（错误消息与 services 一致「保单号已存在」），
  服务层 create_policy 的 IntegrityError 兜底竞态；
- PolicyStatusForm 的 new_status 选项只列 STATUS_TRANSITIONS[当前状态] 的合法目标，
  非法目标在选项校验层即被拒绝。
写操作仍全部经 services（create_policy / update_policy / change_status）。
"""

from django import forms

from apps.customers.models import Customer
from apps.policies.models import Policy
from apps.policies.services.policies import STATUS_TRANSITIONS


class PolicyForm(forms.ModelForm):
    """保单创建 / 编辑表单：全部可编辑字段（不含 owner / status）。

    - ``policyholder`` 必填、``insured`` 可选，均从全部客户中选择。
    """

    policyholder = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        label="投保人",
        required=True,
    )
    insured = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        label="被保险人",
        required=False,
    )

    class Meta:
        model = Policy
        fields = [
            "insurer",
            "name",
            "policy_no",
            "policyholder",
            "insured",
            "insurance_type",
            "main_coverage",
            "rider_note",
            "application_date",
            "effective_date",
            "payment_term",
            "coverage_term",
            "payment_frequency",
            "premium_amount",
            "remark",
        ]
        widgets = {
            "application_date": forms.DateInput(attrs={"type": "date"}),
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "rider_note": forms.Textarea(attrs={"rows": 3}),
            "remark": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"

    def clean_policy_no(self) -> str:
        policy_no = str(self.cleaned_data.get("policy_no") or "").strip()
        existing = Policy.objects.filter(policy_no=policy_no)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("保单号已存在")
        return policy_no


class PolicyStatusForm(forms.Form):
    """保单状态流转表单：目标下拉只含当前状态的合法迁移目标。

    构造参数：``PolicyStatusForm(policy, POST_data_or_None)`` —— 选项随保单当前
    状态动态生成（终态 terminated 的选项为空集，任何提交都会校验失败）。
    """

    new_status = forms.ChoiceField(label="变更到")
    note = forms.CharField(label="备注", required=False, max_length=200)

    def __init__(self, policy: Policy, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        legal_targets = set(STATUS_TRANSITIONS.get(str(policy.status), set()))
        self.fields["new_status"].choices = [
            (value, label) for value, label in Policy.Status.choices if value in legal_targets
        ]
        self.fields["new_status"].widget.attrs["class"] = "input"
        self.fields["note"].widget.attrs["class"] = "input"
