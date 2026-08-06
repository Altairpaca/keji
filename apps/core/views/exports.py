"""导出视图（规格 §16 / §17 can_export_data / §10 敏感导出审计，T9.5）。

全部导出接口要求 ``can_export_data`` 权限位（T9.5 验收）；导出是敏感操作，
成功后应在审计服务（T10.2 接入 apps.audit）记录事件，见各视图末尾注释。
视图保持薄：参数解析与筛选在此，CSV / ZIP 生成全部委托 apps.core.services.exports。
"""

import uuid
from urllib.parse import quote

from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from apps.accounts.permissions import require_permission
from apps.core.services import exports
from apps.customers.models import Customer


def _is_valid_uuid(value: str) -> bool:
    """判断字符串是否为合法 UUID（非法筛选值直接忽略，避免 500）。"""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _filtered_customers(request: HttpRequest) -> QuerySet[Customer]:
    """沿用 customer_list 的筛选逻辑（q / status / tag 多选），供导出复用。

    与 apps/customers/views/customers.py 保持一致：q 走名称 / 手机号 /
    微信昵称 icontains，status 过滤状态，tag 多选过滤后 distinct 去重。
    """
    queryset: QuerySet[Customer] = Customer.objects.select_related("status")

    q = request.GET.get("q", "").strip()
    status_id = request.GET.get("status", "").strip()
    tag_ids = request.GET.getlist("tag")

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(phone__icontains=q) | Q(wechat_nickname__icontains=q)
        )
    if status_id and _is_valid_uuid(status_id):
        queryset = queryset.filter(status_id=status_id)
    valid_tag_ids = [tag_id for tag_id in tag_ids if _is_valid_uuid(tag_id)]
    if valid_tag_ids:
        # M2M 过滤会产生重复行，distinct 去重
        queryset = queryset.filter(tags__id__in=valid_tag_ids).distinct()
    return queryset


def _attachment_header(filename: str) -> str:
    """RFC 5987：中文文件名用 ``filename*=UTF-8''`` 编码，同时提供 ASCII 回退。"""
    ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii").strip() or "export"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


@require_permission("can_export_data")
def export_customers(request: HttpRequest) -> HttpResponse:
    """导出当前筛选下的客户名单 CSV（同 customer_list 的 q / status / tag 参数）。"""
    data = exports.export_customers_csv(_filtered_customers(request))
    response = HttpResponse(data, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = _attachment_header("客户名单.csv")
    # 审计（§10 / T10.2）：导出成功记录点 —— apps.audit 服务接入后在此记录
    # {event_type: "customer_list_export", scope: "customers", meta: {"count": ...}}
    return response


@require_permission("can_export_data")
def export_customer_profile(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """导出单客户档案摘要 CSV。"""
    customer = get_object_or_404(Customer, pk=pk)
    data = exports.export_customer_profile(customer)
    response = HttpResponse(data, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = _attachment_header(
        f"{exports.sanitize_filename(customer.name)}_档案.csv"
    )
    # 审计（§10 / T10.2）：导出成功记录点 —— {event_type: "customer_profile_export"}
    return response


@require_permission("can_export_data")
def export_customer_timeline(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """导出客户统一时间线 CSV。"""
    customer = get_object_or_404(Customer, pk=pk)
    data = exports.export_customer_timeline(customer)
    response = HttpResponse(data, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = _attachment_header(
        f"{exports.sanitize_filename(customer.name)}_时间线.csv"
    )
    # 审计（§10 / T10.2）：导出成功记录点 —— {event_type: "customer_timeline_export"}
    return response


@require_permission("can_export_data")
def export_customer_archive(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """导出客户全部资料 ZIP（档案 + 时间线 + 文档原件）。"""
    customer = get_object_or_404(Customer, pk=pk)
    data, filename = exports.export_customer_archive_zip(customer)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = _attachment_header(filename)
    # 审计（§10 / T10.2）：导出成功记录点 —— {event_type: "customer_archive_export"}
    return response
