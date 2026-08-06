"""core 路由：保存视图（规格 §15）。挂载于根 /saved-views/。"""

from django.urls import path

from apps.core.views import saved_views

app_name = "core"

urlpatterns = [
    path("save/", saved_views.save_current_view, name="saved_view_save"),
    path("", saved_views.list_saved_views, name="saved_view_list"),
    path("<uuid:pk>/apply/", saved_views.apply_saved_view, name="saved_view_apply"),
    path("<uuid:pk>/delete/", saved_views.delete_saved_view, name="saved_view_delete"),
]
