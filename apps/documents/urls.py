"""documents 路由：上传 / 列表 / 详情 / 安全下载（T6.1）。"""

from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="document_list"),
    path("upload/", views.upload, name="upload"),
    path("<uuid:pk>/", views.document_detail, name="document_detail"),
    path("<uuid:pk>/download/", views.document_download, name="document_download"),
]
