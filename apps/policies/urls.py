"""policies 路由：保单 CRUD + 状态流转（T7.2，规格 §11）。

列表 / 详情 / 创建 / 编辑 / 删除 / 恢复 + 状态流转 status/（独立视图，POST only，
保证状态历史经服务层 append-only 写入）。
"""

from django.urls import path

from apps.policies.views import (
    policy_change_status,
    policy_create,
    policy_delete,
    policy_detail,
    policy_edit,
    policy_list,
    policy_restore,
)
from apps.policies.views_documents import (
    policy_document_attach,
    policy_document_detach,
    policy_document_list,
)
from apps.policies.views_reminders import (
    mark_paid as reminder_mark_paid,
)
from apps.policies.views_reminders import (
    reminder_list,
    sync_reminder,
)

app_name = "policies"

urlpatterns = [
    path("", policy_list, name="policy_list"),
    path("create/", policy_create, name="policy_create"),
    path("<uuid:pk>/", policy_detail, name="policy_detail"),
    path("<uuid:pk>/edit/", policy_edit, name="policy_edit"),
    path("<uuid:pk>/status/", policy_change_status, name="policy_change_status"),
    path("<uuid:pk>/delete/", policy_delete, name="policy_delete"),
    path("<uuid:pk>/restore/", policy_restore, name="policy_restore"),
    path("<uuid:pk>/documents/", policy_document_list, name="policy_document_list"),
    path(
        "<uuid:pk>/documents/attach/",
        policy_document_attach,
        name="policy_document_attach",
    ),
    path(
        "<uuid:pk>/documents/<uuid:doc_pk>/detach/",
        policy_document_detach,
        name="policy_document_detach",
    ),
    path("reminders/", reminder_list, name="reminder_list"),
    path(
        "<uuid:pk>/reminders/mark-paid/",
        reminder_mark_paid,
        name="reminder_mark_paid",
    ),
    path(
        "<uuid:pk>/reminders/sync/",
        sync_reminder,
        name="reminder_sync",
    ),
]
