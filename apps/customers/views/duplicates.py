"""customers 重复检测与合并视图（T4.4 / 规格 §16）。

- duplicate_list：列出手机号重复组与同名组，每组合并入口；
- merge_confirm：GET 展示 target / source 对比摘要；
- merge_do：POST 执行合并 → 跳转 target 详情。

权限统一 require_permission("can_manage_customers")。
"""

from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.customers.services.duplicates import (
    find_name_duplicates,
    find_phone_duplicates,
    merge_customers,
)


def _summary(customer: Customer) -> dict[str, object]:
    """客户对比摘要：合并确认页展示的核心字段。"""
    return {
        "name": customer.name,
        "phone": customer.phone,
        "wechat_nickname": customer.wechat_nickname,
        "region": customer.region,
        "tags": [tag.name for tag in customer.tags.all()],
        "owner": customer.owner,
        "notes": customer.notes,
        "created_at": customer.created_at,
    }


@require_permission("can_manage_customers")
def duplicate_list(request: HttpRequest) -> HttpResponse:
    """重复客户列表：手机号重复组 + 同名组，每组给合并入口。"""
    context: dict[str, Any] = {
        "phone_groups": find_phone_duplicates(),
        "name_groups": find_name_duplicates(),
    }
    return render(request, "customers/duplicate_list.html", context)


@require_permission("can_manage_customers")
def merge_confirm(request: HttpRequest) -> HttpResponse:
    """合并确认：GET target / source 两个 query 参数，展示对比摘要。"""
    target_pk = request.GET.get("target")
    source_pk = request.GET.get("source")
    if not target_pk or not source_pk:
        messages.error(request, "缺少合并参数，请从重复列表发起")
        return redirect("customers:duplicate_list")
    target = get_object_or_404(Customer, pk=target_pk)
    source = get_object_or_404(Customer, pk=source_pk)
    return render(
        request,
        "customers/merge_confirm.html",
        {
            "target": target,
            "source": source,
            "target_summary": _summary(target),
            "source_summary": _summary(source),
        },
    )


@require_permission("can_manage_customers")
@require_POST
def merge_do(request: HttpRequest) -> HttpResponse:
    """执行合并：POST target / source → 合并进 target → 跳 target 详情。"""
    target = get_object_or_404(Customer, pk=request.POST.get("target"))
    source = get_object_or_404(Customer, pk=request.POST.get("source"))
    try:
        merged = merge_customers(target, source)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("customers:duplicate_list")
    messages.success(request, f"已将「{source.name}」合并到「{merged.name}」")
    return redirect("customers:customer_detail", pk=merged.pk)
