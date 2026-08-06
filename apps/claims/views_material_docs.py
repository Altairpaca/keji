"""理赔材料 ↔ 文档关联视图（T8.4，规格 §12 材料项关联文件 / §9 一文件多关联）。

独立于 T8.2 的 apps/claims/views.py，避免并行冲突；claim_detail 材料行的
入口链接由编排者在 T8.2 完成后合并。
"""

from uuid import UUID

from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.claims.models import ClaimMaterial
from apps.claims.services.documents import (
    attach_document_to_material,
    detach_document_from_material,
    upload_material_document,
)
from apps.documents.models import Document
from apps.documents.services.files import DuplicateDocumentError
from apps.documents.storage import default_storage

_MANAGE_PERMISSION = "can_manage_customers"
_DOWNLOAD_PERMISSION = "can_download_originals"


def _get_material(claim_pk: UUID, material_id: UUID) -> ClaimMaterial:
    """按案件取材料：案件与材料均须存在，带 customer/document 避免 N+1。"""
    material = get_object_or_404(
        ClaimMaterial.objects.select_related("claim__customer", "document"),
        claim_id=claim_pk,
        pk=material_id,
    )
    # django-stubs 对 get_object_or_404 返回 Any，边界处收窄为具体模型。
    assert isinstance(material, ClaimMaterial)
    return material


@require_permission(_MANAGE_PERMISSION)
def material_attach_document(request: HttpRequest, pk: UUID, material_id: UUID) -> HttpResponse:
    """材料关联文件：GET 表单（选已有或上传新文件）；POST 后回 claim_detail。"""
    material = _get_material(pk, material_id)
    if request.method == "POST":
        return _handle_attach_post(request, material)
    available = Document.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    return render(
        request,
        "claims/material_document_form.html",
        {
            "material": material,
            "claim": material.claim,
            "available_documents": available,
            "current_document": material.document,
        },
    )


def _handle_attach_post(request: HttpRequest, material: ClaimMaterial) -> HttpResponse:
    """POST 分支：优先处理上传的新文件；否则按 select 的已有文档关联。"""
    uploaded = request.FILES.get("file")
    if uploaded is not None:
        try:
            _, doc = upload_material_document(
                material=material,
                file=uploaded,
                uploaded_by=request.user,
            )
        except DuplicateDocumentError:
            messages.error(request, "文件已存在")
            return redirect("claims:claim_detail", material.claim.pk)
        messages.success(request, f"已上传并关联文件：{doc.original_name}")
        return redirect("claims:claim_detail", material.claim.pk)

    existing_pk = request.POST.get("document", "").strip()
    if existing_pk:
        document = get_object_or_404(Document, pk=existing_pk, deleted_at__isnull=True)
        attach_document_to_material(material=material, document=document)
        messages.success(request, f"已关联文件：{document.original_name}")
        return redirect("claims:claim_detail", material.claim.pk)

    messages.warning(request, "请选择已有文件或上传新文件")
    return redirect("claims:claim_detail", material.claim.pk)


@require_POST
@require_permission(_MANAGE_PERMISSION)
def material_detach_document(request: HttpRequest, pk: UUID, material_id: UUID) -> HttpResponse:
    """解除材料与文件的关联（仅 POST）。"""
    material = _get_material(pk, material_id)
    detach_document_from_material(material)
    messages.success(request, "已解除文件关联")
    return redirect("claims:claim_detail", material.claim.pk)


@require_permission(_DOWNLOAD_PERMISSION)
def material_download(request: HttpRequest, pk: UUID, material_id: UUID) -> HttpResponse:
    """安全下载材料关联文件：attachment + 规范化文件名（security.md §4）。"""
    material = _get_material(pk, material_id)
    doc = material.document
    if doc is None:
        raise Http404("材料未关联文件")
    if not default_storage.exists(doc.storage_key):
        raise Http404("文件不存在")
    stream = default_storage.open(doc.storage_key)
    response = FileResponse(stream, content_type=doc.mime_type)
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=doc.original_name
    )
    response["Content-Length"] = str(doc.size)
    return response
