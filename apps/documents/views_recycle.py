"""documents 回收站视图（T6.4，规格 §18 / ADR-006 三级删除协议）。

权限边界（服务端装饰器为安全边界，模板只做展示）：
- 回收站列表 need ``can_view_customers``；
- 恢复 need ``can_manage_customers``（第 2 级）；
- 永久删除 / 清空 need ``can_permanent_delete``（第 3 级管理员专属，不可恢复）。
"""

import uuid

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.documents.models import Document
from apps.documents.services import (
    empty_trash,
    list_trashed_documents,
    permanent_delete_document,
    restore_document,
)
from apps.documents.views import PAGE_SIZE


def _get_trashed_document(pk: uuid.UUID) -> Document:
    """取回收站中的已删文档；不存在或未删除 → 404。"""
    doc: Document = get_object_or_404(Document.all_objects, pk=pk, is_deleted=True)
    return doc


@require_permission("can_view_customers")
def trash_list(request: HttpRequest) -> HttpResponse:
    """回收站：已删文档列表（原始名 / 删除时间 / 恢复、永久删除操作）。"""
    page_obj = Paginator(list_trashed_documents(), PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "documents/trash_list.html", {"page_obj": page_obj})


@require_POST
@require_permission("can_manage_customers")
def trash_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """恢复单条已删文档（ADR-006 第 2 级）。"""
    doc = _get_trashed_document(pk)
    restore_document(doc)
    messages.success(request, f"已恢复「{doc.original_name}」")
    return redirect("documents:trash_list")


@require_POST
@require_permission("can_permanent_delete")
def trash_permanent_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """永久删除单条已删文档（ADR-006 第 3 级，管理员专属，不可恢复）。"""
    doc = _get_trashed_document(pk)
    stats = permanent_delete_document(doc, actor=request.user)
    messages.success(
        request,
        f"已永久删除「{doc.original_name}」（删除记录 {stats['rows_deleted']} 条，"
        f"清理物理文件 {stats['files_deleted']} 个）",
    )
    return redirect("documents:trash_list")


@require_POST
@require_permission("can_permanent_delete")
def trash_empty(request: HttpRequest) -> HttpResponse:
    """清空回收站全部已删文档（管理员专属，不可恢复）。"""
    stats = empty_trash(before_days=0, actor=request.user)
    messages.success(
        request,
        f"回收站已清空（删除记录 {stats['rows_deleted']} 条，"
        f"清理物理文件 {stats['files_deleted']} 个）",
    )
    return redirect("documents:trash_list")
