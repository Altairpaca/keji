"""customers 表单：客户创建 / 编辑（规格 §6 / REQ-CUST-001）。

表单负责 HTTP 边界校验：
- name 必填（自定义错误消息，先于服务层拦截并回显表单错误）；
- birth_date/age_note 至少其一（与 create_customer 服务校验一致）；
- phone 格式宽松（仅排除明显非法字符，不做严格号码规则）。
写操作仍全部经 services（create_customer / update_customer / assign_tags）。
"""

import re
from typing import Any

from django import forms

from apps.customers.models import Customer, CustomerStatus, Tag

# 宽松手机号校验：允许数字 / + / - / 括号 / 空格，长度 6-25。
_LOOSE_PHONE_RE = re.compile(r"[0-9+\-()\s]{6,25}")


class CustomerForm(forms.ModelForm):
    """客户表单：全字段 + tags 多选 checkbox 组。

    - ``name`` 必填，错误消息「客户姓名不能为空」；
    - ``status`` 可选：留空时创建由 services 取默认状态，编辑保持可清空；
    - ``tags`` 以 checkbox 组呈现，模板单独渲染。
    """

    name = forms.CharField(
        max_length=100,
        label="客户姓名",
        error_messages={"required": "客户姓名不能为空"},
    )
    status = forms.ModelChoiceField(
        queryset=CustomerStatus.objects.filter(is_active=True),
        required=False,
        label="客户状态",
    )
    gender = forms.ChoiceField(choices=Customer.Gender.choices, required=False, label="性别")
    priority = forms.ChoiceField(choices=Customer.Priority.choices, required=False, label="优先级")
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        label="标签",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Customer
        fields = [
            "name",
            "gender",
            "birth_date",
            "age_note",
            "phone",
            "wechat_nickname",
            "region",
            "occupation",
            "marital_family_note",
            "source",
            "previous_agent",
            "first_contact_date",
            "last_contact_date",
            "next_followup_date",
            "status",
            "priority",
            "communication_preference",
            "notes",
            "tags",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "first_contact_date": forms.DateInput(attrs={"type": "date"}),
            "last_contact_date": forms.DateInput(attrs={"type": "date"}),
            "next_followup_date": forms.DateInput(attrs={"type": "date"}),
            "marital_family_note": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "tags":
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            field.widget.attrs["class"] = "input"

    def clean_phone(self) -> str:
        phone = str(self.cleaned_data.get("phone") or "").strip()
        if phone and not _LOOSE_PHONE_RE.fullmatch(phone):
            raise forms.ValidationError("手机号格式不正确")
        return phone

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = dict(super().clean())
        birth_date = cleaned.get("birth_date")
        age_note = str(cleaned.get("age_note") or "").strip()
        if not birth_date and not age_note:
            self.add_error(None, "出生日期与年龄说明至少填写其一")
        # 空选回落模型默认值（gender=未知、priority=中）
        if not cleaned.get("gender"):
            cleaned["gender"] = "未知"
        if not cleaned.get("priority"):
            cleaned["priority"] = "中"
        return cleaned
