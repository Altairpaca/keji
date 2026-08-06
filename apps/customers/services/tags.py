"""标签服务（T4.4 / 规格 §6 REQ-CUST-002 标签管理部分）。

视图保持薄，标签写操作经本模块进出：
- create_tag：名称必填（去除首尾空白）；
- update_tag：部分更新并保存，未知字段拒绝；
- soft_delete_tag：先断开与全部客户的 M2M 关联，再软删，避免软删标签
  仍出现在客户标签卡（默认 manager 之外的 base_manager 行为不保证过滤）。
"""

from django.db import transaction

from apps.customers.models import Customer, Tag


def list_tags_with_counts() -> list[tuple[Tag, int]]:
    """标签列表（按名称排序）及各自未删除客户数。

    计数经 Customer.objects（默认 manager）过滤软删客户，保证回收站客户不计入。
    """
    return [
        (tag, Customer.objects.filter(tags=tag).count()) for tag in Tag.objects.order_by("name")
    ]


def create_tag(*, name: str, color: str, description: str = "") -> Tag:
    """创建标签：名称去除首尾空白，空名拒绝。"""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("标签名称不能为空")
    tag: Tag = Tag.objects.create(name=cleaned, color=color, description=description)
    return tag


def update_tag(tag: Tag, **fields: str) -> Tag:
    """部分更新并保存；未知字段拒绝，避免拼写错误静默失效。"""
    for field, value in fields.items():
        if not hasattr(tag, field):
            raise ValueError(f"未知字段：{field}")
        setattr(tag, field, value)
    tag.save()
    return tag


def soft_delete_tag(tag: Tag) -> Tag:
    """软删除标签：事务内先断开 M2M（保留客户），再标记删除。"""
    with transaction.atomic():
        tag.customers.clear()
        return tag.soft_delete()
