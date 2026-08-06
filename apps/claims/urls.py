"""claims 路由（规格 §12）。

- CRUD / 状态流转 / 材料清单 / 模板实例化（T8.2）：案件 <pk> 下挂载
  edit/status/delete/restore/instantiate 与 materials/* 子路径；
- 材料文档挂载（T8.4 并行）与 ZIP 导出（T8.3 并行）沿用既有路由。
"""

from django.urls import path

from apps.claims import views, views_material_docs

app_name = "claims"

urlpatterns = [
    path("", views.claim_list, name="claim_list"),
    path("create/", views.claim_create, name="claim_create"),
    path("<uuid:pk>/", views.claim_detail, name="claim_detail"),
    path("<uuid:pk>/edit/", views.claim_edit, name="claim_edit"),
    path("<uuid:pk>/status/", views.claim_change_status, name="claim_change_status"),
    path("<uuid:pk>/delete/", views.claim_delete, name="claim_delete"),
    path("<uuid:pk>/restore/", views.claim_restore, name="claim_restore"),
    path("<uuid:pk>/instantiate/", views.claim_instantiate_template, name="claim_instantiate"),
    path(
        "<uuid:pk>/materials/add/",
        views.material_add,
        name="claim_material_add",
    ),
    path(
        "<uuid:pk>/materials/<uuid:mid>/status/",
        views.material_change_status,
        name="claim_material_status",
    ),
    path(
        "<uuid:pk>/materials/<uuid:mid>/delete/",
        views.material_delete,
        name="claim_material_delete",
    ),
    path("<uuid:claim_pk>/export/", views.claim_export_zip, name="claim_export_zip"),
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
]
