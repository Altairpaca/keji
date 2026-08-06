"""T8.4 测试专用 URLconf：自包含、可独立运行。

T8.2 / T8.3 并行实现 claim_detail、导出等案件路由（同一 apps/claims/urls.py
实时变动中），本模块不 include 真实 claims 路由，而是显式声明本任务负责的
三个材料文档路由 + 必要的桩（claim_detail / base.html 引用的 dashboard、
accounts 命名空间），保证本任务测试与并行任务互不干扰、随时可验。
"""

from django.http import HttpRequest, HttpResponse
from django.urls import include, path

from apps.claims import views_material_docs


def claim_detail_stub(request: HttpRequest, pk: str) -> HttpResponse:  # noqa: ARG001
    return HttpResponse("claim detail stub")


def _stub(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    return HttpResponse("stub")


dashboard_patterns = ([path("", _stub, name="home")], "dashboard")
accounts_patterns = (
    [path("profile/", _stub, name="profile"), path("logout/", _stub, name="logout")],
    "accounts",
)
claims_patterns = (
    [
        path("<uuid:pk>/", claim_detail_stub, name="claim_detail"),
        path(
            "<uuid:pk>/materials/<uuid:material_id>/document/",
            views_material_docs.material_attach_document,
            name="material_attach_document",
        ),
        path(
            "<uuid:pk>/materials/<uuid:material_id>/document/detach/",
            views_material_docs.material_detach_document,
            name="material_detach_document",
        ),
        path(
            "<uuid:pk>/materials/<uuid:material_id>/download/",
            views_material_docs.material_download,
            name="material_download",
        ),
    ],
    "claims",
)

urlpatterns = [
    path("", include(dashboard_patterns)),
    path("accounts/", include(accounts_patterns)),
    path("claims/", include(claims_patterns)),
]
