"""customers 模板标签：详情右栏「关系」卡渲染（规格 §7）。

``{% relation_card customer %}`` 由服务层计算最近 5 条 + 总数并渲染
``customers/_relation_card.html``，供客户详情页 / 其他页面右栏复用。
卡片内部使用 ``has_perm``（takes_context），故以 takes_context 透传 request。
"""

from typing import Any

from django import template

from apps.customers.models import Customer
from apps.customers.views.relations import relation_card_context

register = template.Library()


@register.inclusion_tag("customers/_relation_card.html", takes_context=True)
def relation_card(context: dict[str, Any], customer: Customer) -> dict[str, Any]:
    """渲染客户详情右栏的「关系」卡（最近 5 条 + 查看全部）。"""
    data = relation_card_context(customer)
    data["request"] = context["request"]
    return data
