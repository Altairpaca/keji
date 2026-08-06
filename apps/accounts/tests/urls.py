"""测试用 URLConf：通过 pytest.mark.urls 覆盖 ROOT_URLCONF（仅测试使用）。"""

from django.urls import path

from apps.accounts.tests.views import backup_view, customers_view

urlpatterns = [
    path("perm-check/customers/", customers_view, name="perm-check-customers"),
    path("perm-check/backup/", backup_view, name="perm-check-backup"),
]
