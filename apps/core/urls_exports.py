"""core 导出路由（规格 §16 / §17，T9.5）。

独立 urlconf，挂载于根 ``/export/``（见 config/urls.py），
namespace 为 ``export``：``{% url 'export:customers' %}`` 等。
全部接口要求 ``can_export_data`` 权限位，校验在视图装饰器完成。
"""

from django.urls import path

from apps.core.views import exports

app_name = "export"

urlpatterns = [
    path("customers/", exports.export_customers, name="customers"),
    path(
        "customers/<uuid:pk>/profile/",
        exports.export_customer_profile,
        name="customer_profile",
    ),
    path(
        "customers/<uuid:pk>/timeline/",
        exports.export_customer_timeline,
        name="customer_timeline",
    ),
    path(
        "customers/<uuid:pk>/archive/",
        exports.export_customer_archive,
        name="customer_archive",
    ),
]
