"""policies CRUD 视图（T7.2，规格 §4.5 / §11 / REQ-POL-001）。

视图保持薄：表单校验在 forms（PolicyForm / PolicyStatusForm），写操作全部经
services（create_policy / update_policy / change_status / soft_delete_policy /
restore_policy）。状态流转必须走服务层 change_status，绝不直接 save status，
保证 PolicyStatusHistory append-only。权限边界统一走 require_permission 装饰器。
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
from apps.policies.forms import PolicyForm, PolicyStatusForm
from apps.policies.models import Policy
from apps.policies.services import (
    change_status,
    create_policy,
    get_history,
    restore_policy,
    soft_delete_policy,
    update_policy,
)

PAGE_SIZE = 20


def _insurer_choices() -> list[str]:
    """保险公司下拉选项：从现有保单去重取非空值。"""
    return list(
        Policy.objects.exclude(insurer="")
        .order_by("insurer")
        .values_list("insurer", flat=True)
        .distinct()
    )


@require_permission("can_view_customers")
def policy_list(request: HttpRequest) -> HttpResponse:
    """保单列表：左栏筛选（status / insurer 下拉 + q 搜索）+ 卡片 + 分页（保留筛选参数）。"""
    queryset: QuerySet[Policy] = Policy.objects.select_related(
        "policyholder", "insured", "owner"
    ).order_by("-created_at")

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    insurer = request.GET.get("insurer", "").strip()

    if q:
        queryset = queryset.filter(Q(policy_no__icontains=q) | Q(name__icontains=q))
    if status:
        queryset = queryset.filter(status=status)
    if insurer:
        queryset = queryset.filter(insurer__icontains=insurer)

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    extra_parts: list[tuple[str, str]] = []
    if q:
        extra_parts.append(("q", q))
    if status:
        extra_parts.append(("status", status))
    if insurer:
        extra_parts.append(("insurer", insurer))
    extra_query = "&" + urlencode(extra_parts) if extra_parts else ""

    context = {
        "page_obj": page_obj,
        "q": q,
        "selected_status": status,
        "selected_insurer": insurer,
        "statuses": Policy.Status.choices,
        "insurers": _insurer_choices(),
        "extra_query": extra_query,
        "total_count": Policy.objects.count(),
    }
    return render(request, "policies/policy_list.html", context)


def _detail_response(
    request: HttpRequest,
    policy: Policy,
    status_form: PolicyStatusForm,
    status: int = 200,
) -> HttpResponse:
    """渲染保单详情页（含状态历史时间线 + 状态流转表单）。"""
    history = get_history(policy)
    return render(
        request,
        "policies/policy_detail.html",
        {"policy": policy, "history": history, "status_form": status_form},
        status=status,
    )


@require_permission("can_view_customers")
def policy_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """保单详情：信息卡全字段 + 状态历史时间线 + 关联客户卡 + 关联文件占位。"""
    policy = get_object_or_404(
        Policy.objects.select_related("policyholder", "insured", "owner"),
        pk=pk,
    )
    return _detail_response(request, policy, PolicyStatusForm(policy))


def _form_response(
    request: HttpRequest, form: PolicyForm, title: str, status: int = 200
) -> HttpResponse:
    """渲染创建 / 编辑表单页（校验失败时以 400 重渲染）。"""
    return render(
        request,
        "policies/policy_form.html",
        {"form": form, "title": title},
        status=status,
    )


@require_permission("can_manage_customers")
def policy_create(request: HttpRequest) -> HttpResponse:
    """创建保单：POST 经表单 + services；owner=当前用户；成功跳详情。"""
    form = PolicyForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            try:
                policy = create_policy(owner=request.user, **data)
            except ValueError as exc:
                form.add_error(None, str(exc))
                return _form_response(request, form, "创建保单", status=400)
            messages.success(request, f"保单 {policy.insurer} {policy.name} 已创建")
            return redirect("policies:policy_detail", pk=policy.pk)
        return _form_response(request, form, "创建保单", status=400)
    return _form_response(request, form, "创建保单")


@require_permission("can_manage_customers")
def policy_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑保单：POST 经表单 + services；成功跳详情。"""
    policy = get_object_or_404(Policy, pk=pk)
    form = PolicyForm(request.POST or None, instance=policy)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            try:
                update_policy(policy, **data)
            except ValueError as exc:
                form.add_error(None, str(exc))
                return _form_response(request, form, f"编辑保单 {policy.name}", status=400)
            messages.success(request, f"保单 {policy.insurer} {policy.name} 已更新")
            return redirect("policies:policy_detail", pk=policy.pk)
        return _form_response(request, form, f"编辑保单 {policy.name}", status=400)
    return _form_response(request, form, f"编辑保单 {policy.name}")


@require_permission("can_manage_customers")
@require_POST
def policy_change_status(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """状态流转：只接受合法目标（表单选项已限定），经 change_status 写历史。

    非法目标在表单选项校验层即被拒绝（400）；服务层 ValueError 兜底竞态。
    """
    policy = get_object_or_404(
        Policy.objects.select_related("policyholder", "insured", "owner"),
        pk=pk,
    )
    form = PolicyStatusForm(policy, request.POST)
    if form.is_valid():
        try:
            change_status(
                policy=policy,
                new_status=form.cleaned_data["new_status"],
                changed_by=request.user,
                note=form.cleaned_data["note"],
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return _detail_response(request, policy, form, status=400)
        messages.success(request, f"保单状态已变更为 {policy.get_status_display()}")
        return redirect("policies:policy_detail", pk=policy.pk)
    return _detail_response(request, policy, form, status=400)


@require_permission("can_delete_customers")
@require_POST
def policy_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除保单（ADR-006，可恢复）→ 列表。"""
    policy = get_object_or_404(Policy, pk=pk)
    soft_delete_policy(policy)
    messages.success(request, f"保单 {policy.insurer} {policy.name} 已删除（可在回收站恢复）")
    return redirect("policies:policy_list")


@require_permission("can_manage_customers")
@require_POST
def policy_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """恢复软删除保单 → 详情。已删除保单不在默认 manager，故从 all_objects 取。"""
    policy = get_object_or_404(Policy.all_objects, pk=pk)
    restore_policy(policy)
    messages.success(request, f"保单 {policy.insurer} {policy.name} 已恢复")
    return redirect("policies:policy_detail", pk=policy.pk)
