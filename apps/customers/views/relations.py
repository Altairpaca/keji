"""customers 关系视图（规格 §7 / REQ-REL-001）：列表 / 创建 / 删除。

视图保持薄：HTTP 解析 + 模板渲染；业务规则（自环、custom 缺 label、
重复关系）全部走 services.relations，ValueError 映射为表单错误。

详情右栏「关系」卡复用：T4.2 的客户详情页可调用 ``relation_card_context``
并用 ``_relation_card.html`` 渲染（最近 5 条 + 查看全部）。
"""

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.customers.models import Customer, CustomerRelation
from apps.customers.services.relations import (
    create_relation,
    delete_relation,
    get_relations,
)

PAGE_SIZE = 20


class RelationForm(forms.Form):
    """创建关系表单：对方客户 + 关系类型 + 自定义名称 + 备注。

    业务校验（自环 / custom 缺 label / 重复）在服务层完成，视图捕获
    ValueError 后回填到表单错误，保证 UI 与领域规则单一来源。
    """

    to_customer = forms.ModelChoiceField(
        queryset=Customer.objects.order_by("name"), label="对方客户"
    )
    relation_type = forms.ChoiceField(
        choices=CustomerRelation.RelationType.choices, label="关系类型"
    )
    custom_label = forms.CharField(
        required=False,
        max_length=50,
        label="自定义关系名称",
        widget=forms.TextInput(attrs={"placeholder": "如：大学同学"}),
    )
    note = forms.CharField(
        required=False,
        label="备注",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "可选，补充说明"}),
    )


def _relation_queryset(customer: Customer) -> QuerySet:
    """该客户全部关系，预取两端客户对象。"""
    return get_relations(customer).select_related("from_customer", "to_customer")


def _get_customer(customer_pk: str) -> Customer:
    customer: Customer = get_object_or_404(Customer, pk=customer_pk)
    return customer


def relation_card_context(customer: Customer) -> dict[str, object]:
    """「关系」卡上下文：当前客户 + 最近 5 条 + 总数（供详情右栏 / 列表右栏复用）。"""
    relations = _relation_queryset(customer)
    return {
        "customer": customer,
        "recent_relations": list(relations[:5]),
        "relation_count": relations.count(),
    }


@require_permission("can_view_customers")
def relation_list(request: HttpRequest, customer_pk: str) -> HttpResponse:
    """客户的关系列表（出 + 入双向可见）。"""
    customer = _get_customer(customer_pk)
    page_obj = Paginator(_relation_queryset(customer), PAGE_SIZE).get_page(request.GET.get("page"))
    context: dict[str, object] = {
        "customer": customer,
        "page_obj": page_obj,
    }
    context.update(relation_card_context(customer))
    return render(request, "customers/relation_list.html", context)


@require_permission("can_manage_customers")
def relation_create(request: HttpRequest, customer_pk: str) -> HttpResponse:
    """创建一条 from=当前客户 的定向关系。"""
    customer = _get_customer(customer_pk)
    form = RelationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            relation = create_relation(
                from_customer=customer,
                to_customer=form.cleaned_data["to_customer"],
                relation_type=form.cleaned_data["relation_type"],
                custom_label=form.cleaned_data.get("custom_label") or "",
                note=form.cleaned_data.get("note") or "",
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"已与 {relation.to_customer.name} 建立关系")
            return redirect("customers:relation_list", customer_pk=customer.pk)
    return render(
        request,
        "customers/relation_form.html",
        {
            "form": form,
            "customer": customer,
            "customers": Customer.objects.order_by("name"),
        },
    )


@require_permission("can_manage_customers")
@require_POST
def relation_delete(request: HttpRequest, customer_pk: str, pk: str) -> HttpResponse:
    """软删除一条关系，返回当前客户的关系列表。"""
    customer = _get_customer(customer_pk)
    relation = get_object_or_404(_relation_queryset(customer), pk=pk)
    delete_relation(relation)
    messages.success(request, "关系已删除")
    return redirect("customers:relation_list", customer_pk=customer.pk)
