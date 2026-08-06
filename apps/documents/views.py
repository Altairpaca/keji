"""documents 视图：上传、列表、详情、安全下载（T6.1，规格 §9/§10）。

权限边界（服务端装饰器为安全边界，模板只做展示）：
- 上传 need ``can_manage_customers``；列表 / 详情 need ``can_view_customers``；
- 下载原文件 need ``can_download_originals``，响应 ``attachment`` 附件头
  （security.md §4 Content-Disposition）。
视图保持薄：多文件逐个 save_upload，单个失败不影响其他，错误收集到消息。
"""

import uuid

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.documents.models import Album, Document
from apps.documents.services import DuplicateDocumentError, save_upload
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
        return redirect("documents:document_list")

    return render(
        request,
        "documents/upload.html",
        {
            "customers": Customer.objects.order_by("name"),
            "albums": Album.objects.order_by("name"),
            "sensitivity_choices": Document.Sensitivity.choices,
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
        },
    )


@require_permission("can_view_customers")
def document_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """文件详情：元数据表格 + 下载按钮（查看器由 T6.2 实现）。"""
    doc = get_object_or_404(
        Document.objects.select_related("uploaded_by").prefetch_related("customers", "albums"),
        pk=pk,
    )
    return render(request, "documents/document_detail.html", {"doc": doc})


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
