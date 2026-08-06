"""activities 路由：工作事件 / 沟通记录 CRUD 与事件列表。"""

from django.urls import path

from apps.activities import views

app_name = "activities"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("events/new/", views.work_event_create, name="work_event_create"),
    path("events/<uuid:pk>/edit/", views.work_event_edit, name="work_event_edit"),
    path("events/<uuid:pk>/delete/", views.work_event_delete, name="work_event_delete"),
    path("communications/new/", views.communication_create, name="communication_create"),
    path("communications/quick/", views.communication_quick, name="communication_quick"),
    path(
        "communications/<uuid:pk>/edit/",
        views.communication_edit,
        name="communication_edit",
    ),
    path(
        "communications/<uuid:pk>/delete/",
        views.communication_delete,
        name="communication_delete",
    ),
]
