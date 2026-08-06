"""customers 标签管理视图（T4.4 / 规格 §6）。

查看需 can_view_customers，增删改需 can_manage_enums；权限边界走
accounts.require_permission 服务端装饰器，模板只做展示性隐藏。
写操作全部经 services.tags；重名校验在 TagForm.clean_name。
"""

import uuid

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.models import Tag
from apps.customers.services import tags as tag_services


class TagForm(forms.ModelForm):
    """标签表单：name 必填唯一、color 用颜色选择器、description 可选。"""

    class Meta:
        model = Tag
        fields = ["name", "color", "description"]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
            "description": forms.TextInput(attrs={"placeholder": "可选"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs["class"] = "input"
        self.fields["name"].widget.attrs["placeholder"] = "如：vip"
        self.fields["color"].widget.attrs["class"] = "input w-20"
        self.fields["description"].widget.attrs["class"] = "input"

    def clean_name(self) -> str:
        name = str(self.cleaned_data["name"]).strip()
        base = Tag.all_objects
        queryset = base.exclude(pk=self.instance.pk) if self.instance else base
        if queryset.filter(name=name).exists():
            raise forms.ValidationError("已存在同名标签（含回收站）")
        return name


@require_permission("can_view_customers")
def tag_list(request: HttpRequest) -> HttpResponse:
    """标签表格：名称 / 颜色色块 / 客户数 / 操作（增删改按钮按权限展示）。"""
    rows = tag_services.list_tags_with_counts()
    return render(request, "customers/tag_list.html", {"rows": rows})


@require_permission("can_manage_enums")
def tag_create(request: HttpRequest) -> HttpResponse:
    """新建标签：POST 经表单 + services，成功跳列表。"""
    form = TagForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tag = tag_services.create_tag(**form.cleaned_data)
        messages.success(request, f"标签「{tag.name}」已创建")
        return redirect("customers:tag_list")
    return render(request, "customers/tag_form.html", {"form": form, "title": "新建标签"})


@require_permission("can_manage_enums")
def tag_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑标签：POST 经表单 + services，成功跳列表。"""
    tag = get_object_or_404(Tag, pk=pk)
    form = TagForm(request.POST or None, instance=tag)
    if request.method == "POST" and form.is_valid():
        updated = tag_services.update_tag(tag, **form.cleaned_data)
        messages.success(request, f"标签「{updated.name}」已更新")
        return redirect("customers:tag_list")
    title = f"编辑标签 {tag.name}"
    return render(request, "customers/tag_form.html", {"form": form, "title": title})


@require_permission("can_manage_enums")
@require_POST
def tag_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除标签（M2M 自动断开，客户保留）→ 列表。"""
    tag = get_object_or_404(Tag, pk=pk)
    tag_services.soft_delete_tag(tag)
    messages.success(request, f"标签「{tag.name}」已删除")
    return redirect("customers:tag_list")
