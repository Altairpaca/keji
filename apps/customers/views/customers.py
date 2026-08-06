"""customers CRUD 视图（T4.2，规格 §6 / REQ-CUST-001/005）。

视图保持薄：表单校验在 forms.CustomerForm，写操作全部经 services
（create_customer / update_customer / soft_delete_customer / restore_customer / assign_tags）。
权限边界统一走 accounts.require_permission 服务端装饰器（ADR-004 / ADR-012）。
"""

import uuid
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.forms import CustomerForm
from apps.customers.models import Customer, CustomerStatus, Tag
from apps.customers.services import (
    assign_tags,
    create_customer,
    restore_customer,
    soft_delete_customer,
    update_customer,
)

PAGE_SIZE = 20

# 详情页侧栏「客户列表」最多展示条数（简化复用列表）。
SIDEBAR_CUSTOMER_LIMIT = 50


def _is_valid_uuid(value: str) -> bool:
    """判断字符串是否为合法 UUID（非法筛选值直接忽略，避免 500）。"""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


@require_permission("can_view_customers")
def customer_list(request: HttpRequest) -> HttpResponse:
    """客户列表：左栏筛选（q / status / tag 多选）+ 中栏卡片 + 分页（保留筛选参数）。"""
    queryset: QuerySet = Customer.objects.select_related("status", "owner").prefetch_related("tags")

    q = request.GET.get("q", "").strip()
    status_id = request.GET.get("status", "").strip()
    tag_ids = request.GET.getlist("tag")

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(phone__icontains=q) | Q(wechat_nickname__icontains=q)
        )
    if status_id and _is_valid_uuid(status_id):
        queryset = queryset.filter(status_id=status_id)
    valid_tag_ids = [tag_id for tag_id in tag_ids if _is_valid_uuid(tag_id)]
    if valid_tag_ids:
        # M2M 过滤会产生重复行，distinct 去重
        queryset = queryset.filter(tags__id__in=valid_tag_ids).distinct()

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    extra_parts: list[tuple[str, str]] = []
    if q:
        extra_parts.append(("q", q))
    if status_id and _is_valid_uuid(status_id):
        extra_parts.append(("status", status_id))
    for tag_id in valid_tag_ids:
        extra_parts.append(("tag", tag_id))
    extra_query = "&" + urlencode(extra_parts) if extra_parts else ""

    context = {
        "page_obj": page_obj,
        "q": q,
        "statuses": CustomerStatus.objects.filter(is_active=True),
        "tags": Tag.objects.all(),
        "selected_status": status_id,
        "selected_tag_ids": tag_ids,
        "extra_query": extra_query,
        "total_count": Customer.objects.count(),
    }
    return render(request, "customers/customer_list.html", context)


@require_permission("can_view_customers")
def customer_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """客户详情：中栏信息卡 + 占位区块；右栏状态 / 下一步 / 关系 / 标签卡。

    已软删除客户由默认 manager 排除，get_object_or_404 即返回 404。
    左栏简化复用客户列表（当前客户高亮），供桌面快速切换。
    """
    customer = get_object_or_404(
        Customer.objects.select_related("status", "owner", "created_by").prefetch_related("tags"),
        pk=pk,
    )
    sidebar_customers: QuerySet = Customer.objects.select_related("status").order_by("name")[
        :SIDEBAR_CUSTOMER_LIMIT
    ]
    return render(
        request,
        "customers/customer_detail.html",
        {"customer": customer, "sidebar_customers": sidebar_customers},
    )


@require_permission("can_manage_customers")
def customer_create(request: HttpRequest) -> HttpResponse:
    """创建客户：POST 经表单 + services；成功跳详情。owner/created_by = 当前用户。

    表单校验失败返回 400 并重渲染（HTMX 可直接替换表单区域）。
    """
    form = CustomerForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            tag_objects = list(data.pop("tags", []) or [])
            customer = create_customer(
                name=data.pop("name"),
                owner=request.user,
                created_by=request.user,
                **data,
            )
            if tag_objects:
                assign_tags(customer, [tag.name for tag in tag_objects])
            messages.success(request, f"客户 {customer.name} 已创建")
            return redirect("customers:customer_detail", pk=customer.pk)
        return _form_response(request, form, "创建客户", status=400)
    return _form_response(request, form, "创建客户")


@require_permission("can_manage_customers")
def customer_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑客户：POST 经表单 + services；成功跳详情。表单校验失败返回 400。"""
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            tag_objects = list(data.pop("tags", []) or [])
            update_customer(customer, **data)
            if tag_objects:
                assign_tags(customer, [tag.name for tag in tag_objects])
            messages.success(request, f"客户 {customer.name} 已更新")
            return redirect("customers:customer_detail", pk=customer.pk)
        return _form_response(request, form, f"编辑客户 {customer.name}", status=400)
    return _form_response(request, form, f"编辑客户 {customer.name}")


def _form_response(
    request: HttpRequest, form: CustomerForm, title: str, status: int = 200
) -> HttpResponse:
    """渲染创建 / 编辑表单页（校验失败时以 400 重渲染）。"""
    return render(
        request, "customers/customer_form.html", {"form": form, "title": title}, status=status
    )


@require_permission("can_delete_customers")
@require_POST
def customer_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除客户（ADR-006，可恢复）→ 列表。"""
    customer = get_object_or_404(Customer, pk=pk)
    soft_delete_customer(customer)
    messages.success(request, f"客户 {customer.name} 已删除（可在回收站恢复）")
    return redirect("customers:customer_list")


@require_permission("can_delete_customers")
@require_POST
def customer_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """恢复软删除客户 → 详情。已删除客户不在默认 manager，故从 all_objects 取。"""
    customer = get_object_or_404(Customer.all_objects, pk=pk)
    restore_customer(customer)
    messages.success(request, f"客户 {customer.name} 已恢复")
    return redirect("customers:customer_detail", pk=customer.pk)
