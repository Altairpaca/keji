"""documents 图片查看器 / 派生图输出视图（T6.2，ADR-002 派生图分离）。

- ``viewer``：查看器页——图片内联展示（原图或 1440 preview，敏感级别 blur-sm），
  PDF/Office 显示类型图标 + 文件名 + 下载入口，附元数据行；
- ``document_image``：查看器图片字节（原图 <3MB 直出，否则 preview），内联响应；
- ``document_thumb``：缩略图字节（网格卡片 <img> 用），无缩略图 404。
查看 / 派生图输出 need ``can_view_customers``；写操作仅涉及派生图生成，
不做任何原图写入。
"""

import uuid

from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import require_permission
from apps.documents.models import Document
from apps.documents.services.sensitive import sensitive_context
from apps.documents.services.thumbnails import resolve_view_source
from apps.documents.storage import default_storage


@require_permission("can_view_customers")
def viewer(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """图片查看器页：图片内联展示 / 非图片下载入口 + 元数据行。"""
    doc = get_object_or_404(
        Document.objects.select_related("uploaded_by").prefetch_related("customers", "albums"),
        pk=pk,
    )
    is_image = doc.mime_type.startswith("image/")
    source_key, source_mime = resolve_view_source(doc)
    using_preview = bool(source_key and source_key != doc.storage_key)
    return render(
        request,
        "documents/viewer.html",
        {
            "doc": doc,
            "is_image": is_image,
            "source_key": source_key,
            "source_mime": source_mime,
            "using_preview": using_preview,
            **sensitive_context(request.user),
        },
    )


@require_permission("can_view_customers")
def document_image(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """查看器图片字节：原图 <3MB 直出，否则 1440 preview。非图片 / 缺失 404。"""
    doc = get_object_or_404(Document, pk=pk)
    key, mime = resolve_view_source(doc)
    if not key or not default_storage.exists(key):
        raise Http404("图片不存在")
    stream = default_storage.open(key)
    return FileResponse(stream, content_type=mime)


@require_permission("can_view_customers")
def document_thumb(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """缩略图字节输出：网格卡片 <img> 使用；无缩略图 404。"""
    doc = get_object_or_404(Document, pk=pk)
    if not doc.thumb_storage_key or not default_storage.exists(doc.thumb_storage_key):
        raise Http404("缩略图不存在")
    stream = default_storage.open(doc.thumb_storage_key)
    return FileResponse(stream, content_type=doc.thumb_mime or "image/webp")
