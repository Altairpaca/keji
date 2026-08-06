"""dashboard 路由。"""

from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.global_search, name="search"),
]
