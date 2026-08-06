"""activities 表单：工作事件 / 沟通记录。

ModelForm 保持薄：字段集合与中文 label 走模型 verbose_name，样式统一加
``input`` 类；写操作由视图调用服务层完成（服务层负责业务校验）。
"""

from django import forms

from apps.activities.models import CommunicationRecord, WorkEvent


class WorkEventForm(forms.ModelForm):
    """工作事件表单：事件类型 / 标题 / 客户 / 发生时间 / 结论 / 结果 / 下一步。"""

    class Meta:
        model = WorkEvent
        fields = [
            "event_type",
            "title",
            "customer",
            "occurred_at",
            "summary",
            "outcome",
            "next_step",
            "next_followup_date",
        ]
        widgets = {
            "event_type": forms.Select(attrs={"class": "input"}),
            "title": forms.TextInput(attrs={"class": "input"}),
            "customer": forms.Select(attrs={"class": "input"}),
            "occurred_at": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "summary": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "outcome": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "next_step": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "next_followup_date": forms.DateInput(
                attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"
            ),
        }


class CommunicationForm(forms.ModelForm):
    """沟通记录完整表单（独立页入口）。"""

    class Meta:
        model = CommunicationRecord
        fields = [
            "customer",
            "channel",
            "occurred_at",
            "quick_result",
            "content",
            "customer_feedback",
            "next_plan",
            "next_followup_date",
        ]
        widgets = {
            "customer": forms.Select(attrs={"class": "input"}),
            "channel": forms.Select(attrs={"class": "input"}),
            "occurred_at": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "quick_result": forms.Select(attrs={"class": "input"}),
            "content": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "customer_feedback": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "next_plan": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "next_followup_date": forms.DateInput(
                attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"
            ),
        }


class CommunicationQuickForm(CommunicationForm):
    """快捷沟通表单（客户详情页内嵌，HTMX POST）：只保留快捷结果相关字段。

    T5.2 客户详情页将本表单 partial 内嵌到右栏/中栏；成功后返回新沟通卡片。
    """

    class Meta(CommunicationForm.Meta):
        fields = [
            "customer",
            "channel",
            "occurred_at",
            "quick_result",
            "content",
            "next_plan",
            "next_followup_date",
        ]
