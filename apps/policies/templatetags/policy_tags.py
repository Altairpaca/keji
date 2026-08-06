"""policies 模板标签：状态值 → 中文标签（规格 §4.5）。

PolicyStatusHistory 的 from_status / to_status 是未带 choices 的 CharField
（历史模型改动留待后续），此处用 Policy.Status 的 choices 统一映射显示标签。
"""

from django import template

from apps.policies.models import Policy

register = template.Library()


@register.filter
def status_label(value: str) -> str:
    """把状态 value（如 "paying"）映射为中文标签（如 "缴费中"）。"""
    return str(Policy.Status(value).label)
