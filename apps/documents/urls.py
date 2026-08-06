"""documents 路由：上传 / 列表 / 详情 / 查看器 / 相册 / 安全下载 / 批量操作 / 重复文件 / 回收站。"""

from django.urls import path

from apps.documents import views, views_albums, views_recycle, views_viewer

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="document_list"),
    path("upload/", views.upload, name="upload"),
    path("upload/result/", views.upload_result, name="upload_result"),
    path("bulk/", views.bulk_action, name="bulk_action"),
    path("duplicates/", views.duplicate_list, name="duplicate_list"),
    path("trash/", views_recycle.trash_list, name="trash_list"),
    path("trash/empty/", views_recycle.trash_empty, name="trash_empty"),
    path("trash/<uuid:pk>/restore/", views_recycle.trash_restore, name="trash_restore"),
    path(
        "trash/<uuid:pk>/permanent-delete/",
        views_recycle.trash_permanent_delete,
        name="trash_permanent_delete",
    ),
    path("albums/", views_albums.album_list, name="album_list"),
    path("albums/create/", views_albums.album_create, name="album_create"),
    path("albums/<uuid:pk>/", views_albums.album_detail, name="album_detail"),
    path("albums/<uuid:pk>/edit/", views_albums.album_edit, name="album_edit"),
    path("albums/<uuid:pk>/delete/", views_albums.album_delete, name="album_delete"),
    path("<uuid:pk>/", views.document_detail, name="document_detail"),
    path("<uuid:pk>/download/", views.document_download, name="document_download"),
    path("<uuid:pk>/view/", views_viewer.viewer, name="viewer"),
    path("<uuid:pk>/image/", views_viewer.document_image, name="document_image"),
    path("<uuid:pk>/thumb/", views_viewer.document_thumb, name="document_thumb"),
]
