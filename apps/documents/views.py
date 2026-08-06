"""documents 视图：上传、列表、详情、安全下载（T6.1，规格 §9/§10）。
回收站视图见 ``views_recycle.py``（T6.4）。

权限边界（服务端装饰器为安全边界，模板只做展示）：
- 上传 need ``can_manage_customers``；列表 / 详情 need ``can_view_customers``；
- 下载原文件 need ``can_download_originals``，响应 ``attachment`` 附件头
  （security.md §4 Content-Disposition）。
视图保持薄：多文件逐个 save_upload，单个失败不影响其他，错误收集到消息。
"""

import uuid

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.documents.models import Album, Document
from apps.documents.services import DuplicateDocumentError, save_upload
from apps.documents.services.batch import (
    bulk_mark_important,
    bulk_mark_sensitive,
    bulk_move_to_album,
    bulk_soft_delete,
)
from apps.documents.services.duplicates import find_duplicate_groups
from apps.documents.services.sensitive import sensitive_context
from apps.documents.storage import default_storage

PAGE_SIZE = 24

# 列表「类型」筛选：按 MIME 前缀分组（security.md 与规格 §9 的文件类型归类）。
TYPE_FILTERS: dict[str, tuple[str, str]] = {
    "image": ("图片", "image/"),
    "application": ("文档", "application/"),
    "video": ("视频", "video/"),
    "audio": ("音频", "audio/"),
    "text": ("文本", "text/"),
}


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _resolve_ids(raw: list[str]) -> list[uuid.UUID]:
    """解析表单提交的 UUID 列表，忽略非法值（避免 500）。"""
    result: list[uuid.UUID] = []
    for value in raw:
        value = value.strip()
        if _is_valid_uuid(value):
            result.append(uuid.UUID(value))
    return result


@require_permission("can_manage_customers")
def upload(request: HttpRequest) -> HttpResponse:
    """GET：上传表单；POST：多文件循环 save_upload。

    手机优先：``<input type="file" multiple accept=... capture="environment">``；
    失败 / 重复的单文件不影响其他文件，错误收集到 messages。
    """
    if request.method == "POST":
        files = request.FILES.getlist("files")
        if not files:
            messages.error(request, "请选择要上传的文件")
            return redirect("documents:document_list")

        customer_ids = _resolve_ids(request.POST.getlist("customers"))
        album_ids = _resolve_ids(request.POST.getlist("albums"))
        customers = list(Customer.objects.filter(pk__in=customer_ids))
        albums = list(Album.objects.filter(pk__in=album_ids))

        title = request.POST.get("title", "").strip()
        note = request.POST.get("note", "")
        sensitivity = request.POST.get("sensitivity", Document.Sensitivity.NORMAL)
        source = request.POST.get("source", "web")

        success_count = 0
        duplicate_count = 0
        errors: list[str] = []
        for f in files:
            try:
                save_upload(
                    file=f,
                    uploaded_by=request.user,
                    title=title,
                    note=note,
                    sensitivity=sensitivity,
                    customers=customers,
                    albums=albums,
                    source=source,
                )
                success_count += 1
            except DuplicateDocumentError:
                duplicate_count += 1
            except ValueError as exc:
                errors.append(f"{f.name}：{exc}")

        if success_count:
            messages.success(request, f"成功上传 {success_count} 个文件")
        if duplicate_count:
            messages.warning(request, f"{duplicate_count} 个文件内容已存在，已跳过")
        for error in errors:
            messages.error(request, error)
        # 结果数据经 session 传结果页（POST 仍 302，防重复提交）
        request.session["upload_result"] = {
            "success": success_count,
            "skipped": duplicate_count,
            "failed": errors,
        }
        return redirect("documents:upload_result")

    customers = Customer.objects.order_by("name")
    albums = Album.objects.order_by("name")
    return render(
        request,
        "documents/upload.html",
        {
            "customers": customers,
            "albums": albums,
            "customer_choices": [(c.id, c.name) for c in customers],
            "album_choices": [(a.id, a.name) for a in albums],
            "sensitivity_choices": Document.Sensitivity.choices,
            "initial_title": request.GET.get("title", ""),
            "initial_note": request.GET.get("note", ""),
        },
    )


@require_permission("can_manage_customers")
def upload_result(request: HttpRequest) -> HttpResponse:
    """上传结果页：成功 / 跳过（重复）/ 失败三组计数与失败明细（T6.5）。

    数据来自 POST 时写入 session 的 ``upload_result``，读取即清除；
    直接访问无数据时渲染全零结果，不报错。
    """
    payload = request.session.pop("upload_result", None)
    if payload is None:
        payload = {"success": 0, "skipped": 0, "failed": []}
    return render(
        request,
        "documents/upload_result.html",
        {
            "success_count": payload["success"],
            "duplicate_count": payload["skipped"],
            "failed": payload["failed"],
        },
    )


@require_permission("can_view_customers")
def document_list(request: HttpRequest) -> HttpResponse:
    """全部文件网格：客户 / 相册 / 类型 / 敏感级别筛选 + 分页 + 空状态。

    缩略图占位由 T6.2 生成，本任务先显示类型图标与文件名。
    """
    queryset = Document.objects.select_related("uploaded_by").prefetch_related(
        "customers", "albums"
    )

    customer_id = request.GET.get("customer", "").strip()
    album_id = request.GET.get("album", "").strip()
    type_filter = request.GET.get("type", "").strip()
    sensitivity = request.GET.get("sensitivity", "").strip()

    if _is_valid_uuid(customer_id):
        queryset = queryset.filter(customers__id=customer_id).distinct()
    if _is_valid_uuid(album_id):
        queryset = queryset.filter(albums__id=album_id).distinct()
    if type_filter in TYPE_FILTERS:
        queryset = queryset.filter(mime_type__startswith=TYPE_FILTERS[type_filter][1])
    if sensitivity:
        queryset = queryset.filter(sensitivity=sensitivity)

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    extra_parts: list[str] = []
    if customer_id and _is_valid_uuid(customer_id):
        extra_parts.append(f"&customer={customer_id}")
    if album_id and _is_valid_uuid(album_id):
        extra_parts.append(f"&album={album_id}")
    if type_filter in TYPE_FILTERS:
        extra_parts.append(f"&type={type_filter}")
    if sensitivity:
        extra_parts.append(f"&sensitivity={sensitivity}")
    extra_query = "".join(extra_parts)

    return render(
        request,
        "documents/document_list.html",
        {
            "page_obj": page_obj,
            "customers": Customer.objects.order_by("name"),
            "albums": Album.objects.order_by("name"),
            "type_filters": TYPE_FILTERS,
            "sensitivity_choices": Document.Sensitivity.choices,
            "selected_customer": customer_id,
            "selected_album": album_id,
            "selected_type": type_filter,
            "selected_sensitivity": sensitivity,
            "extra_query": extra_query,
            **sensitive_context(request.user),
        },
    )


@require_permission("can_view_customers")
def document_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """文件详情：元数据表格 + 下载按钮（查看器由 T6.2 实现）。"""
    doc = get_object_or_404(
        Document.objects.select_related("uploaded_by").prefetch_related("customers", "albums"),
        pk=pk,
    )
    return render(
        request,
        "documents/document_detail.html",
        {"doc": doc, **sensitive_context(request.user)},
    )


@require_permission("can_download_originals")
def document_download(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """安全下载原文件（T10.3 安全下载入口，本任务先落 FileResponse 流式）。

    响应 ``attachment; filename="安全化名称"``（security.md §4），
    文件名经 content_disposition_header 规范化与 RFC 5987 编码。
    """
    doc = get_object_or_404(Document, pk=pk)
    if not default_storage.exists(doc.storage_key):
        raise Http404("文件不存在")
    stream = default_storage.open(doc.storage_key)
    response = FileResponse(stream, content_type=doc.mime_type)
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=doc.original_name
    )
    response["Content-Length"] = str(doc.size)
    return response


# ---------------------------------------------------------------------------
# 批量操作（T6.3，规格 §9/§10）
# ---------------------------------------------------------------------------


@require_POST
@require_permission("can_manage_customers")
def bulk_action(request: HttpRequest) -> HttpResponse:
    """批量操作入口：action ∈ album / important / sensitive / delete。

    POST 表单：``action`` + ``doc_pks[]`` + 目标参数（``target_album`` /
    ``value`` / ``next``）。默认重定向回来源页并提示处理数量；请求带
    ``format=json`` 或 HTMX 头时返回 JSON 计数。业务与事务边界在服务层，
    视图只做参数解析与防御。
    """
    action = request.POST.get("action", "").strip()
    doc_pks = _resolve_ids(request.POST.getlist("doc_pks"))

    raw_next = request.POST.get("next", "").strip()
    if raw_next and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}):
        next_url = raw_next
    else:
        next_url = reverse("documents:document_list")

    if not doc_pks:
        messages.warning(request, "未选择文件")
        return redirect(next_url)

    count = 0
    try:
        if action == "album":
            target = request.POST.get("target_album", "").strip()
            if not _is_valid_uuid(target):
                messages.error(request, "请选择目标相册")
                return redirect(next_url)
            count = bulk_move_to_album(doc_pks, uuid.UUID(target))
        elif action == "important":
            value = request.POST.get("value", "").strip().lower()
            count = bulk_mark_important(doc_pks, value in ("1", "true", "on", "yes"))
        elif action == "sensitive":
            value = request.POST.get("value", "").strip() or "sensitive"
            count = bulk_mark_sensitive(doc_pks, value)
        elif action == "delete":
            count = bulk_soft_delete(doc_pks)
        else:
            messages.error(request, "不支持的操作")
            return redirect(next_url)
    except (Album.DoesNotExist, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(next_url)

    if request.headers.get("HX-Request") == "true" or request.POST.get("format") == "json":
        return JsonResponse({"count": count})

    messages.success(request, f"已处理 {count} 个文件")
    return redirect(next_url)


@require_permission("can_view_customers")
def duplicate_list(request: HttpRequest) -> HttpResponse:
    """重复文件列表（T6.3）：按 SHA-256 分组未删除文件，组内多于 1 份。"""
    return render(
        request,
        "documents/duplicate_list.html",
        {"groups": find_duplicate_groups()},
    )
