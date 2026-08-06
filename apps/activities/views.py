"""activities 视图：工作事件 / 沟通记录 CRUD 与列表（T5.1）。

查看 require can_view_customers，写操作 require can_manage_customers
（服务端装饰器为安全边界，模板只做展示）。视图保持薄：表单校验 + 服务层调用。
"""

import uuid

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.activities.forms import CommunicationForm, CommunicationQuickForm, WorkEventForm
from apps.activities.models import CommunicationRecord, WorkEvent
from apps.activities.services import (
    create_communication,
    create_work_event,
    soft_delete_communication,
    soft_delete_work_event,
    update_communication,
    update_work_event,
)
from apps.customers.models import Customer

PAGE_SIZE = 20


def _get_customer(request: HttpRequest, customer_pk: uuid.UUID | None) -> Customer | None:
    """解析预选客户：优先路径参数，其次 ``?customer=`` 查询参数。"""
    raw = str(customer_pk) if customer_pk is not None else request.GET.get("customer", "").strip()
    if not raw:
        return None
    customer: Customer = get_object_or_404(Customer, pk=raw)
    return customer


# ---------------------------------------------------------------------------
# 工作事件
# ---------------------------------------------------------------------------


@require_permission("can_view_customers")
def event_list(request: HttpRequest) -> HttpResponse:
    """全部工作事件：occurred_at 倒序分页，支持 ``?type=`` 与 ``?customer=`` 筛选。"""
    events = WorkEvent.objects.select_related("customer").order_by("-occurred_at")
    event_type = request.GET.get("type", "").strip()
    if event_type:
        events = events.filter(event_type=event_type)
    customer_raw = request.GET.get("customer", "").strip()
    if customer_raw:
        events = events.filter(customer_id=customer_raw)

    paginator = Paginator(events, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    extra_query = ""
    if event_type:
        extra_query += f"&type={event_type}"
    if customer_raw:
        extra_query += f"&customer={customer_raw}"

    return render(
        request,
        "activities/event_list.html",
        {
            "page_obj": page_obj,
            "customers": Customer.objects.order_by("name"),
            "type_choices": WorkEvent.EventType.choices,
            "selected_type": event_type,
            "selected_customer": customer_raw,
            "extra_query": extra_query,
        },
    )


@require_permission("can_manage_customers")
def work_event_create(request: HttpRequest, customer_pk: uuid.UUID | None = None) -> HttpResponse:
    """创建工作事件：预选客户后隐藏客户下拉，直接进入事件填写。"""
    customer = _get_customer(request, customer_pk)
    initial: dict[str, object] = {"customer": customer} if customer is not None else {}
    form = WorkEventForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        create_work_event(
            customer=data["customer"],
            title=data["title"],
            event_type=data["event_type"],
            occurred_at=data["occurred_at"],
            summary=data["summary"],
            outcome=data["outcome"],
            next_step=data["next_step"],
            next_followup_date=data["next_followup_date"],
            created_by=request.user,
            owner=request.user,
        )
        messages.success(request, f"工作事件「{data['title']}」已记录")
        return redirect("activities:event_list")
    return render(
        request,
        "activities/event_form.html",
        {"form": form, "preselected_customer": customer},
    )


@require_permission("can_manage_customers")
def work_event_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑工作事件。"""
    event = get_object_or_404(WorkEvent, pk=pk)
    form = WorkEventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        update_work_event(
            event,
            customer=data["customer"],
            title=data["title"],
            event_type=data["event_type"],
            occurred_at=data["occurred_at"],
            summary=data["summary"],
            outcome=data["outcome"],
            next_step=data["next_step"],
            next_followup_date=data["next_followup_date"],
        )
        messages.success(request, f"工作事件「{event.title}」已更新")
        return redirect("activities:event_list")
    return render(request, "activities/event_form.html", {"form": form})


@require_permission("can_manage_customers")
@require_POST
def work_event_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除工作事件（ADR-006 第 1 级）。"""
    event = get_object_or_404(WorkEvent, pk=pk)
    title = event.title
    soft_delete_work_event(event)
    messages.success(request, f"工作事件「{title}」已删除")
    return redirect("activities:event_list")


# ---------------------------------------------------------------------------
# 沟通记录
# ---------------------------------------------------------------------------


@require_permission("can_manage_customers")
def communication_create(
    request: HttpRequest, customer_pk: uuid.UUID | None = None
) -> HttpResponse:
    """独立页创建沟通记录；``?customer=`` 预选客户。"""
    customer = _get_customer(request, customer_pk)
    initial: dict[str, object] = {"customer": customer} if customer is not None else {}
    form = CommunicationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        create_communication(
            customer=data["customer"],
            channel=data["channel"],
            occurred_at=data["occurred_at"],
            quick_result=data["quick_result"],
            content=data["content"],
            customer_feedback=data["customer_feedback"],
            next_plan=data["next_plan"],
            next_followup_date=data["next_followup_date"],
            recorded_by=request.user,
        )
        messages.success(request, f"已记录与 {data['customer']} 的沟通")
        return redirect("activities:event_list")
    return render(
        request,
        "activities/communication_form.html",
        {"form": form, "preselected_customer": customer},
    )


@require_permission("can_manage_customers")
@require_POST
def communication_quick(request: HttpRequest) -> HttpResponse:
    """快捷沟通表单：HTMX POST，成功后返回新沟通卡片 partial 供就地插入。

    T5.2 客户详情页将本端点对应的表单 partial 内嵌；失败时返回带错误的表单 partial。
    """
    form = CommunicationQuickForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        communication = create_communication(
            customer=data["customer"],
            channel=data["channel"],
            occurred_at=data["occurred_at"],
            quick_result=data["quick_result"],
            content=data["content"],
            next_plan=data["next_plan"],
            next_followup_date=data["next_followup_date"],
            recorded_by=request.user,
        )
        return render(
            request,
            "activities/_communication_card.html",
            {"communication": communication},
        )
    return render(
        request,
        "activities/_communication_quick_form.html",
        {"form": form},
    )


@require_permission("can_manage_customers")
def communication_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """编辑沟通记录。"""
    communication = get_object_or_404(CommunicationRecord, pk=pk)
    form = CommunicationForm(request.POST or None, instance=communication)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        update_communication(
            communication,
            customer=data["customer"],
            channel=data["channel"],
            occurred_at=data["occurred_at"],
            quick_result=data["quick_result"],
            content=data["content"],
            customer_feedback=data["customer_feedback"],
            next_plan=data["next_plan"],
            next_followup_date=data["next_followup_date"],
        )
        messages.success(request, "沟通记录已更新")
        return redirect("activities:event_list")
    return render(request, "activities/communication_form.html", {"form": form})


@require_permission("can_manage_customers")
@require_POST
def communication_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """软删除沟通记录（ADR-006 第 1 级）。"""
    communication = get_object_or_404(CommunicationRecord, pk=pk)
    soft_delete_communication(communication)
    messages.success(request, "沟通记录已删除")
    return redirect("activities:event_list")
