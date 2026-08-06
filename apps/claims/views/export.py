"""理赔案件资料 ZIP 导出视图（T8.3 并行，规格 §16/§17）。

``GET /claims/<uuid>/export/``：打包导出案件全部材料。权限边界：
- ``can_export_data`` 由装饰器强制（§17 导出数据权限位）；
- ``can_view_customers`` 在视图内校验（§16 导出不绕过查看权限）。
"""

from urllib.parse import quote

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from apps.accounts.permissions import has_permission, require_permission
from apps.claims.models import ClaimCase
from apps.claims.services.export import build_claim_zip, record_export_audit


@require_permission("can_export_data")
def claim_export_zip(request: HttpRequest, claim_pk: str) -> HttpResponse:
    """打包导出案件全部材料为 ZIP（字节响应，案件规模小无需流式）。"""
    if not has_permission(request.user, "can_view_customers"):
        raise PermissionDenied
    claim: ClaimCase = get_object_or_404(ClaimCase, pk=claim_pk)
    zip_bytes, filename = build_claim_zip(claim)
    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    record_export_audit(claim=claim, user=request.user)
    return response
