"""理赔案件 CRUD / 状态流转 / 模板实例化视图（T8.2，规格 §12）。

视图保持薄：表单校验在 forms（ClaimForm / ChangeClaimStatusForm），写操作全部
经 services（create_claim / update_claim / change_claim_status /
soft_delete_claim / restore_claim / instantiate_template）。状态流转绝不直接
save status，保证转移图统一。权限边界统一走 require_permission（ADR-004/012）。
"""

import uuid
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.claims.forms import ChangeClaimStatusForm, ChangeMaterialStatusForm, ClaimForm
from apps.claims.models import CLAIM_STATUS_CHOICES, CLAIM_TYPES, ClaimCase
from apps.claims.services.claims import (
    change_claim_status,
    create_claim,
    instantiate_template,
    missing_materials,
    restore_claim,
    soft_delete_claim,
    update_claim,
)

PAGE_SIZE = 20


@require_permission("can_view_customers")
def claim_list(request: HttpRequest) -> HttpResponse:
    """理赔列表：status / claim_type 筛选 + q 搜索 + 分页（保留筛选参数）。"""
    queryset: QuerySet[ClaimCase] = (
        ClaimCase.objects.select_related("customer", "policy")
        .order_by("-created_at")
        .annotate(
            missing_count=Count(
                "materials",
                filter=Q(materials__status__in=("not_submitted", "needs_supplement")),
            )
        )
    )

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    claim_type = request.GET.get("claim_type", "").strip()

    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if status:
        queryset = queryset.filter(status=status)
    if claim_type:
        queryset = queryset.filter(claim_type=claim_type)

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    extra_parts: list[tuple[str, str]] = []
    if q:
        extra_parts.append(("q", q))
    if status:
        extra_parts.append(("status", status))
    if claim_type:
        extra_parts.append(("claim_type", claim_type))
    extra_query = "&" + urlencode(extra_parts) if extra_parts else ""

    context: dict[str, Any] = {
        "page_obj": page_obj,
        "q": q,
        "selected_status": status,
        "selected_claim_type": claim_type,
        "statuses": CLAIM_STATUS_CHOICES,
        "claim_types": CLAIM_TYPES,
        "extra_query": extra_query,
        "total_count": ClaimCase.objects.count(),
    }
    return render(request, "claims/claim_list.html", context)


def _detail_response(
    request: HttpRequest,
    claim: ClaimCase,
    status_form: ChangeClaimStatusForm,
    status: int = 200,
) -> HttpResponse:
    """渲染案件详情页（信息卡 + 状态流转表单 + 材料清单 + 缺料提示）。"""
    materials = claim.materials.select_related("document", "checked_by").all()
    material_rows = [(material, ChangeMaterialStatusForm(material)) for material in materials]
    return render(
        request,
        "claims/claim_detail.html",
        {
            "claim": claim,
            "status_form": status_form,
            "material_rows": material_rows,
            "missing": missing_materials(claim),
        },
        status=status,
    )


@require_permission("can_view_customers")
def claim_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """案件详情：信息卡全字段 + 状态流转 + 材料清单 + 缺料提示。"""
    claim = get_object_or_404(
        ClaimCase.objects.select_related("customer", "policy", "owner"),
        pk=pk,
    )
    return _detail_response(request, claim, ChangeClaimStatusForm(claim))


def _form_response(
    request: HttpRequest, form: ClaimForm, title: str, status: int = 200
) -> HttpResponse:
    """渲染创建 / 编辑表单页（校验失败时以 400 重渲染）。"""
    return render(
        request,
        "claims/claim_form.html",
        {"form": form, "title": title},
        status=status,
    )


@require_permission("can_manage_customers")
def claim_create(request: HttpRequest) -> HttpResponse:
    """创建案件：POST 经表单 + services；owner=当前用户；成功跳详情。"""
    form = ClaimForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            estimated_amount = data.pop("estimated_amount", None)
            try:
                claim = create_claim(owner=request.user, **data)
            except ValueError as exc:
                form.add_error(None, str(exc))
                return _form_response(request, form, "新增理赔案件", status=400)
            if estimated_amount is not None:
                update_claim(claim, estimated_amount=estimated_amount)
            messages.success(request, f"理赔案件「{claim.name}」已创建")
            return redirect("claims:claim_detail", pk=claim.pk)
        return _form_response(request, form, "新增理赔案件", status=400)
    return _form_response(request, form, "新增理赔案件")


@require_permission("can_manage_customers")
def claim_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑案件：POST 经表单 + services；成功跳详情。"""
    claim = get_object_or_404(
        ClaimCase.objects.select_related("customer", "policy", "owner"),
        pk=pk,
    )
    form = ClaimForm(request.POST or None, instance=claim)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            try:
                update_claim(claim, **data)
            except ValueError as exc:
                form.add_error(None, str(exc))
                return _form_response(request, form, f"编辑案件 {claim.name}", status=400)
            messages.success(request, f"理赔案件「{claim.name}」已更新")
            return redirect("claims:claim_detail", pk=claim.pk)
        return _form_response(request, form, f"编辑案件 {claim.name}", status=400)
    return _form_response(request, form, f"编辑案件 {claim.name}")


@require_permission("can_delete_customers")
@require_POST
def claim_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除案件（ADR-006，可恢复）→ 列表。"""
    claim = get_object_or_404(ClaimCase, pk=pk)
    soft_delete_claim(claim)
    messages.success(request, f"理赔案件「{claim.name}」已删除（可在回收站恢复）")
    return redirect("claims:claim_list")


@require_permission("can_manage_customers")
@require_POST
def claim_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """恢复软删除案件 → 详情。已删除案件不在默认 manager，故从 all_objects 取。"""
    claim = get_object_or_404(ClaimCase.all_objects, pk=pk)
    restore_claim(claim)
    messages.success(request, f"理赔案件「{claim.name}」已恢复")
    return redirect("claims:claim_detail", pk=claim.pk)


@require_permission("can_manage_customers")
@require_POST
def claim_change_status(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """案件状态流转：只接受合法目标（表单选项已限定），经 change_claim_status。

    非法目标在表单选项校验层即被拒绝（400）；服务层 ValueError 兜底竞态。
    """
    claim = get_object_or_404(
        ClaimCase.objects.select_related("customer", "policy", "owner"),
        pk=pk,
    )
    form = ChangeClaimStatusForm(claim, request.POST)
    if form.is_valid():
        try:
            change_claim_status(
                claim=claim,
                new_status=form.cleaned_data["new_status"],
                changed_by=request.user,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return _detail_response(request, claim, form, status=400)
        messages.success(request, f"案件状态已变更为 {claim.get_status_display()}")
        return redirect("claims:claim_detail", pk=claim.pk)
    return _detail_response(request, claim, form, status=400)


@require_permission("can_manage_customers")
@require_POST
def claim_instantiate_template(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """按理赔类型实例化材料清单模板：同名跳过（幂等）→ 详情 + 消息。"""
    claim = get_object_or_404(ClaimCase, pk=pk)
    created = instantiate_template(claim=claim)
    if created:
        messages.success(request, f"已按模板生成 {len(created)} 份材料")
    else:
        messages.info(request, "已按模板生成 0 份材料（材料已齐备，无需重复生成）")
    return redirect("claims:claim_detail", pk=claim.pk)
