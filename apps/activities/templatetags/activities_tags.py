"""activities 模板标签：客户统一时间线区块（T5.2）。"""

from django import template

from apps.activities.services.timeline import timeline_items
from apps.customers.models import Customer

register = template.Library()


@register.inclusion_tag("activities/_timeline.html")
def timeline_block(customer: Customer | None) -> dict[str, object]:
    """客户详情页中栏的时间线区块：服务端渲染首屏，空数据显示空状态。"""
    if customer is None:
        return {"items": []}
    return {"items": timeline_items(customer)}
