"""理赔材料视图：添加 / 状态流转 / 软删除（T8.2，规格 §12）。

表单校验在 forms（MaterialForm / ChangeMaterialStatusForm），写操作经 services
（create_material / change_material_status）。状态流转绝不直接 save status。
手机端友好：一律普通 POST + redirect 回详情，不依赖 HTMX。
"""

import uuid
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.claims.forms import ChangeClaimStatusForm, ChangeMaterialStatusForm, MaterialForm
from apps.claims.models import ClaimCase
from apps.claims.services.claims import change_material_status, create_material
from apps.claims.views.claims import _detail_response


@require_permission("can_manage_customers")
def material_add(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """添加材料：GET 渲染表单；POST 经 MaterialForm → create_material → 详情。

    同名重复由服务层 create_material 抛 ValueError，以表单错误 400 呈现。
    """
    claim = get_object_or_404(
        ClaimCase.objects.select_related("customer", "policy", "owner"),
        pk=pk,
    )
    form = MaterialForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            note = data.pop("note", "")
            try:
                material = create_material(claim=claim, **data)
            except ValueError as exc:
                form.add_error("name", str(exc))
                return _material_form_response(request, claim, form, status=400)
            if note:
                material.note = note
                material.save(update_fields=["note", "updated_at"])
            messages.success(request, f"材料「{material.name}」已添加")
            return redirect("claims:claim_detail", pk=claim.pk)
        return _material_form_response(request, claim, form, status=400)
    return _material_form_response(request, claim, form)


def _material_form_response(
    request: HttpRequest, claim: ClaimCase, form: MaterialForm, status: int = 200
) -> HttpResponse:
    """渲染材料添加表单页（校验失败时以 400 重渲染）。"""
    return render(
        request,
        "claims/material_form.html",
        {"form": form, "claim": claim, "title": f"添加材料 · {claim.name}"},
        status=status,
    )


@require_permission("can_manage_customers")
@require_POST
def material_change_status(request: HttpRequest, pk: uuid.UUID, mid: uuid.UUID) -> HttpResponse:
    """材料状态流转：合法目标经 change_material_status（checked 写核对人/时间）。

    非法目标在表单选项校验层即被拒绝（400）；服务层 ValueError 兜底竞态。
    """
    claim = get_object_or_404(
        ClaimCase.objects.select_related("customer", "policy", "owner"),
        pk=pk,
    )
    material = get_object_or_404(claim.materials, pk=mid)
    form = ChangeMaterialStatusForm(material, request.POST)
    if form.is_valid():
        try:
            change_material_status(
                material=material,
                new_status=form.cleaned_data["new_status"],
                changed_by=request.user,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            messages.error(request, str(exc))
            return _detail_response(request, claim, ChangeClaimStatusForm(claim), status=400)
        messages.success(
            request, f"材料「{material.name}」状态已变更为 {material.get_status_display()}"
        )
        return redirect("claims:claim_detail", pk=claim.pk)
    for _field, errors in form.errors.items():
        for error in errors:
            messages.error(request, str(error))
    return _detail_response(request, claim, ChangeClaimStatusForm(claim), status=400)


@require_permission("can_manage_customers")
@require_POST
def material_delete(request: HttpRequest, pk: uuid.UUID, mid: uuid.UUID) -> HttpResponse:
    """软删除材料（ADR-006）→ 详情。"""
    claim = get_object_or_404(ClaimCase, pk=pk)
    material = get_object_or_404(claim.materials, pk=mid)
    material.soft_delete()
    messages.success(request, f"材料「{material.name}」已删除")
    return redirect("claims:claim_detail", pk=claim.pk)
