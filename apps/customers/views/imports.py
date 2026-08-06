"""customers 批量导入视图（T4.5 / 规格 §16）。

- ``download_import_template``：CSV 模板下载（UTF-8 BOM），需 can_view_customers；
- ``import_preview``：GET 表单 / POST 解析预览（不落库），需 can_manage_customers；
- ``import_confirm``：确认导入（session 暂存文件内容与负责人），需 can_manage_customers。

模板下载不涉及客户数据，属只读辅助能力；导入即创建客户，走客户管理权限位。
"""

import base64

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import require_permission
from apps.customers.services import importer
from apps.customers.services.importer import ImportReport

_SESSION_CONTENT_KEY = "import_content_b64"
_SESSION_OWNER_KEY = "import_owner_id"
_SESSION_FILENAME_KEY = "import_filename"


@require_permission("can_view_customers")
@require_GET
def download_import_template(request: HttpRequest) -> HttpResponse:
    """下载 CSV 导入模板（UTF-8 BOM，含列头与必填星号说明）。"""
    response = HttpResponse(
        importer.template_csv_bytes(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="customers_import_template.csv"'
    return response


@require_permission("can_manage_customers")
def import_preview(request: HttpRequest) -> HttpResponse:
    """GET 渲染上传表单；POST 解析预览（不落库）并暂存文件内容供确认。"""
    if request.method != "POST":
        return render(request, "customers/import_form.html")

    uploaded = request.FILES.get("file")
    if uploaded is None:
        messages.error(request, "请选择要导入的 CSV 文件")
        return render(request, "customers/import_form.html")

    content = uploaded.read()
    preview = importer.preview_rows(content)
    request.session[_SESSION_CONTENT_KEY] = base64.b64encode(content).decode("ascii")
    request.session[_SESSION_OWNER_KEY] = str(request.user.id)
    request.session[_SESSION_FILENAME_KEY] = uploaded.name
    return render(
        request,
        "customers/import_preview.html",
        {"preview": preview, "filename": uploaded.name},
    )


@require_permission("can_manage_customers")
@require_POST
def import_confirm(request: HttpRequest) -> HttpResponse:
    """读取 session 中的文件内容与负责人，整体事务导入并渲染结果报告。"""
    content_b64 = request.session.get(_SESSION_CONTENT_KEY)
    owner_id = request.session.get(_SESSION_OWNER_KEY)
    if not content_b64 or owner_id != str(request.user.id):
        messages.error(request, "导入会话已失效，请重新上传文件")
        return redirect("customers:import_preview")

    content = base64.b64decode(content_b64)
    for key in (_SESSION_CONTENT_KEY, _SESSION_OWNER_KEY, _SESSION_FILENAME_KEY):
        request.session.pop(key, None)

    try:
        report: ImportReport = importer.import_customers(
            content=content,
            owner=request.user,
            created_by=request.user,
        )
    except ImportError as exc:
        messages.error(request, str(exc))
        report = {
            "imported": 0,
            "skipped": [],
            "failed": [{"line_no": None, "name": "—", "reason": str(exc)}],
        }

    messages.success(
        request,
        f"导入完成：成功 {report['imported']} 行，"
        f"跳过 {len(report['skipped'])} 行，失败 {len(report['failed'])} 行",
    )
    return render(request, "customers/import_result.html", {"report": report})
