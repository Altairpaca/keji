"""tasks URL 配置（规格 §13 / §14）。"""

from django.urls import path

from apps.tasks import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name="task_list"),
    path("new/", views.task_create, name="task_create"),
    path("quick/", views.quick_followup, name="quick_followup"),
    path("<uuid:pk>/edit/", views.task_edit, name="task_edit"),
    path("<uuid:pk>/complete/", views.task_complete, name="task_complete"),
    path("<uuid:pk>/cancel/", views.task_cancel, name="task_cancel"),
    path("<uuid:pk>/delete/", views.task_delete, name="task_delete"),
]
