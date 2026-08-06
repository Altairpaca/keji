"""documents 相册视图（T6.2，规格 §9 / REQ-DOC-002）。

查看 need ``can_view_customers``；增删改 need ``can_manage_customers``。
视图保持薄：表单校验在 AlbumForm，写操作全部经 services.albums
（create_album / update_album / soft_delete_album / add_documents_to_album）。
"""

import uuid

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.documents.models import Album, Document
from apps.documents.services import albums as album_services
from apps.documents.services.sensitive import sensitive_context
from apps.documents.views import PAGE_SIZE

# 敏感级别模糊上下文键：透传给文件网格 partial（_document_grid.html）。
SENSITIVE_KEYS = ("can_view_sensitive", "sensitive_blur_enabled")


class AlbumForm(forms.ModelForm):
    """相册表单：name 必填（去空白），category 限于默认类别，customer 可空。"""

    class Meta:
        model = Album
        fields = ["name", "category", "custom_category", "customer", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "选填"}),
            "custom_category": forms.TextInput(attrs={"placeholder": "超出默认类别时填写"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["name"].error_messages["required"] = "相册名称不能为空"
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"

    def clean_name(self) -> str:
        name = str(self.cleaned_data["name"]).strip()
        if not name:
            raise forms.ValidationError("相册名称不能为空")
        return name


@require_permission("can_view_customers")
def album_list(request: HttpRequest) -> HttpResponse:
    """相册卡片网格：名称 / 类别徽标 / 文件数（软删文档不计入）。"""
    albums = Album.objects.annotate(
        document_count=Count("documents", filter=Q(documents__is_deleted=False), distinct=True)
    )
    return render(request, "documents/album_list.html", {"albums": albums})


@require_permission("can_view_customers")
def album_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """相册详情：文件网格（缩略图卡片 + 批量操作复用 _document_grid）。"""
    album = get_object_or_404(Album, pk=pk)
    docs = (
        Document.objects.filter(albums=album)
        .select_related("uploaded_by")
        .prefetch_related("customers")
    )
    page_obj = Paginator(docs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "documents/album_detail.html",
        {
            "album": album,
            "page_obj": page_obj,
            "albums": Album.objects.order_by("name"),
            "can_manage": request.user.has_bit("can_manage_customers"),
            **sensitive_context(request.user),
        },
    )


@require_permission("can_manage_customers")
def album_create(request: HttpRequest) -> HttpResponse:
    """新建相册：POST 经表单 + services，成功跳详情。"""
    form = AlbumForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        album = album_services.create_album(
            **form.cleaned_data,
            created_by=request.user,
        )
        messages.success(request, f"相册「{album.name}」已创建")
        return redirect("documents:album_detail", pk=album.pk)
    return render(
        request,
        "documents/album_form.html",
        {"form": form, "title": "新建相册", "customers": Customer.objects.order_by("name")},
    )


@require_permission("can_manage_customers")
def album_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑相册：POST 经表单 + services，成功跳详情。"""
    album = get_object_or_404(Album, pk=pk)
    form = AlbumForm(request.POST or None, instance=album)
    if request.method == "POST" and form.is_valid():
        updated = album_services.update_album(album, **form.cleaned_data)
        messages.success(request, f"相册「{updated.name}」已更新")
        return redirect("documents:album_detail", pk=album.pk)
    return render(
        request,
        "documents/album_form.html",
        {
            "form": form,
            "title": f"编辑相册：{album.name}",
            "customers": Customer.objects.order_by("name"),
        },
    )


@require_permission("can_manage_customers")
@require_POST
def album_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除相册（ADR-006 第 1 级），文档与 M2M 关联保留。"""
    album = get_object_or_404(Album, pk=pk)
    album_services.soft_delete_album(album)
    messages.success(request, f"相册「{album.name}」已删除")
    return redirect("documents:album_list")
