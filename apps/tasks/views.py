"""tasks 视图（规格 §13 / §14）。

视图保持薄：列表筛选 + 分页；写操作全部经 services（create_task / update_task /
complete_task / cancel_task / soft_delete_task / set_quick_followup）。
权限边界统一走 accounts.require_permission（ADR-004 / ADR-012）。
"""

import uuid
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer
from apps.tasks.forms import TaskForm
from apps.tasks.models import Task
from apps.tasks.services import (
    cancel_task,
    complete_task,
    create_task,
    set_quick_followup,
    soft_delete_task,
    update_task,
)

PAGE_SIZE = 20


@require_permission("can_view_customers")
def task_list(request: HttpRequest) -> HttpResponse:
    """待办列表：status（all/open/done/overdue）+ task_type 筛选 + 分页。"""
    queryset: QuerySet = Task.objects.select_related("customer", "assignee").order_by(
        "due_date", "created_at"
    )

    status = request.GET.get("status", "all").strip()
    task_type = request.GET.get("task_type", "").strip()

    if status == "open":
        queryset = queryset.filter(status__in=["open", "in_progress"])
    elif status == "done":
        queryset = queryset.filter(status="done")
    elif status == "overdue":
        queryset = queryset.filter(due_date__lt=timezone.localdate()).exclude(
            status__in=["done", "cancelled"]
        )
    if task_type:
        queryset = queryset.filter(task_type=task_type)

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    extra_parts: list[tuple[str, str]] = []
    if status != "all":
        extra_parts.append(("status", status))
    if task_type:
        extra_parts.append(("task_type", task_type))
    extra_query = "&" + urlencode(extra_parts) if extra_parts else ""

    context: dict[str, Any] = {
        "page_obj": page_obj,
        "status": status,
        "task_type": task_type,
        "task_types": Task.TaskType.choices,
        "extra_query": extra_query,
        "open_count": Task.objects.filter(status__in=["open", "in_progress"]).count(),
        "done_count": Task.objects.filter(status="done").count(),
        "overdue_count": Task.objects.filter(due_date__lt=timezone.localdate())
        .exclude(status__in=["done", "cancelled"])
        .count(),
    }
    return render(request, "tasks/task_list.html", context)


@require_permission("can_manage_customers")
def task_create(request: HttpRequest) -> HttpResponse:
    """新建待办：POST 经表单 + services；成功回列表。"""
    form = TaskForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            task = create_task(
                title=data.pop("title"),
                task_type=data.pop("task_type"),
                customer=data.pop("customer", None),
                due_date=data.pop("due_date"),
                due_time=data.pop("due_time", None),
                priority=data.pop("priority", "中"),
                content=data.pop("content", ""),
                remark=data.pop("remark", ""),
                assignee=data.pop("assignee", None),
                created_by=request.user,
            )
            messages.success(request, f"待办「{task.title}」已创建")
            return redirect("tasks:task_list")
        return _form_response(request, form, "新建待办", status=400)
    return _form_response(request, form, "新建待办")


@require_permission("can_manage_customers")
def task_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑待办：POST 经表单 + services；成功回列表。"""
    task = get_object_or_404(Task, pk=pk)
    form = TaskForm(request.POST or None, instance=task)
    if request.method == "POST":
        if form.is_valid():
            data: dict[str, Any] = dict(form.cleaned_data)
            update_task(task, **data)
            messages.success(request, f"待办「{task.title}」已更新")
            return redirect("tasks:task_list")
        return _form_response(request, form, f"编辑待办 {task.title}", status=400)
    return _form_response(request, form, f"编辑待办 {task.title}")


def _form_response(
    request: HttpRequest, form: TaskForm, title: str, status: int = 200
) -> HttpResponse:
    """渲染创建 / 编辑表单页（校验失败时以 400 重渲染）。"""
    return render(request, "tasks/task_form.html", {"form": form, "title": title}, status=status)


@require_permission("can_manage_customers")
@require_POST
def task_complete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """完成任务 → 列表（HTMX 时返回卡片片段）。"""
    task = get_object_or_404(Task, pk=pk)
    complete_task(task)
    messages.success(request, f"待办「{task.title}」已完成")
    if getattr(request, "htmx", False):
        return render(request, "tasks/_task_card.html", {"task": task})
    return redirect("tasks:task_list")


@require_permission("can_manage_customers")
@require_POST
def task_cancel(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """取消任务 → 列表。"""
    task = get_object_or_404(Task, pk=pk)
    cancel_task(task)
    messages.success(request, f"待办「{task.title}」已取消")
    return redirect("tasks:task_list")


@require_permission("can_manage_customers")
@require_POST
def task_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除待办 → 列表。"""
    task = get_object_or_404(Task, pk=pk)
    soft_delete_task(task)
    messages.success(request, f"待办「{task.title}」已删除")
    return redirect("tasks:task_list")


@require_permission("can_manage_customers")
@require_POST
def quick_followup(request: HttpRequest) -> HttpResponse:
    """客户快速回访：?customer=<uuid>&days=7|15|30|90 → 回访任务 + 顺延跟进日期。"""
    customer_id = request.POST.get("customer") or request.GET.get("customer")
    days_raw = request.POST.get("days") or request.GET.get("days")
    customer = get_object_or_404(Customer, pk=customer_id)
    try:
        days = int(days_raw or "")
    except ValueError as exc:
        raise Http404 from exc
    try:
        set_quick_followup(
            customer=customer, days=days, assignee=request.user, created_by=request.user
        )
    except ValueError:
        messages.error(request, "快速跟进天数必须是 7 / 15 / 30 / 90")
        return _back(request, customer)
    messages.success(request, f"已为客户 {customer.name} 创建回访待办")
    return _back(request, customer)


def _back(request: HttpRequest, customer: Customer) -> HttpResponse:
    """回退到来源页；无来源时回客户详情。"""
    referer = request.META.get("HTTP_REFERER")
    if referer:
        return redirect(referer)
    return redirect("customers:customer_detail", pk=customer.pk)
