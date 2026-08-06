"""policies-文档关联视图（T7.4，规格 §11 关联文件 / §9 一文件多关联）。

独立于 T7.2 的 ``views.py``（policy_detail 并行在建，本文件不依赖也不修改它）。
权限边界：列表 / attach 页查看 need ``can_view_customers``；写操作
（attach / detach）need ``can_manage_customers``。上传新文件复用 documents
服务 ``save_upload``（校验 / 查重 / 落盘），成功后再关联到保单。
"""

import uuid

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import has_permission, require_permission
from apps.documents.models import Document
from apps.documents.services import DuplicateDocumentError, save_upload
from apps.policies.models import Policy
from apps.policies.services.documents import (
    attach_document_to_policy,
    detach_document_from_policy,
    policy_documents,
)


def _display_name(doc: Document) -> str:
    """卡片 / 消息展示名：优先标题，缺省用原始文件名。

    Django 模型字段对 mypy 为 ``Any``（尚无 django-stubs），
    转 ``str`` 收敛为字符串类型，避免 ``warn_return_any``。
    """
    return str(doc.title or doc.original_name)


def _is_valid_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@require_permission("can_view_customers")
def policy_document_list(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """保单关联文件列表：卡片网格（类型图标 / 标题 / 大小 / 上传时间）+ 移除按钮。"""
    policy = get_object_or_404(Policy.objects.select_related("policyholder", "insured"), pk=pk)
    documents = policy_documents(policy).select_related("uploaded_by")
    return render(
        request,
        "policies/policy_documents.html",
        {
            "policy": policy,
            "documents": documents,
            "can_manage": has_permission(request.user, "can_manage_customers"),
        },
    )


@require_permission("can_manage_customers")
def policy_document_attach(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """关联文件页：选择已有文件（select，未删除）或上传新文件（multipart）。

    POST 优先处理 ``document_pk``（关联已有文件）；否则处理 ``files``
    （逐个 save_upload 后关联）；两者皆缺则回表单并提示。
    """
    policy = get_object_or_404(Policy, pk=pk)

    if request.method == "POST":
        raw_pk = request.POST.get("document_pk", "").strip()
        if raw_pk:
            doc_id = _is_valid_uuid(raw_pk)
            if doc_id is not None:
                doc = get_object_or_404(Document, pk=doc_id)
                attach_document_to_policy(policy, doc)
                messages.success(request, f"已关联文件「{_display_name(doc)}」")
                return redirect("policies:policy_document_list", pk=policy.pk)
            messages.error(request, "文件标识无效，请重新选择")
            return redirect("policies:policy_document_attach", pk=policy.pk)

        files = request.FILES.getlist("files")
        if files:
            title = request.POST.get("title", "").strip()
            note = request.POST.get("note", "")
            sensitivity = request.POST.get("sensitivity", Document.Sensitivity.NORMAL)
            success_count = 0
            for f in files:
                try:
                    doc = save_upload(
                        file=f,
                        uploaded_by=request.user,
                        title=title,
                        note=note,
                        sensitivity=sensitivity,
                        source="policy",
                    )
                except DuplicateDocumentError as exc:
                    messages.error(request, f"{f.name}：{exc}")
                    continue
                except ValueError as exc:
                    messages.error(request, f"{f.name}：{exc}")
                    continue
                attach_document_to_policy(policy, doc)
                success_count += 1
            if success_count:
                messages.success(request, f"已上传并关联 {success_count} 个文件")
            return redirect("policies:policy_document_list", pk=policy.pk)

        messages.error(request, "请选择已有文件或上传新文件")
        return redirect("policies:policy_document_attach", pk=policy.pk)

    documents = Document.objects.order_by("title", "original_name")
    return render(
        request,
        "policies/policy_document_attach.html",
        {
            "policy": policy,
            "documents": documents,
            "sensitivity_choices": Document.Sensitivity.choices,
        },
    )


@require_permission("can_manage_customers")
@require_POST
def policy_document_detach(request: HttpRequest, pk: uuid.UUID, doc_pk: uuid.UUID) -> HttpResponse:
    """解除关联：文件本身不删除，仅移除保单与文件的关联。"""
    policy = get_object_or_404(Policy, pk=pk)
    doc = get_object_or_404(Document, pk=doc_pk)
    detach_document_from_policy(policy, doc)
    messages.success(request, f"已移除关联文件「{_display_name(doc)}」")
    return redirect("policies:policy_document_list", pk=policy.pk)
