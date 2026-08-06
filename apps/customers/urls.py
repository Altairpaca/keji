"""customers 路由：客户 CRUD（T4.2）+ 客户关系（T4.3）+ 标签与重复合并（T4.4）。

主列表 / 详情 / 创建 / 编辑 / 删除 / 恢复为 T4.2 追加；关系路由独立成组：
relation_list / relation_create / relation_delete；标签管理 tags/*、
重复检测与合并 duplicates/ / merge/ 为 T4.4 追加。
"""

from django.urls import path

from apps.customers.views import duplicates as duplicate_views
from apps.customers.views import graph as graph_views
from apps.customers.views import relations as relation_views
from apps.customers.views import tags as tag_views
from apps.customers.views.customers import (
    customer_create,
    customer_delete,
    customer_detail,
    customer_edit,
    customer_list,
    customer_restore,
)

app_name = "customers"

urlpatterns = [
    path("", customer_list, name="customer_list"),
    path("create/", customer_create, name="customer_create"),
    path("<uuid:pk>/", customer_detail, name="customer_detail"),
    path("<uuid:pk>/edit/", customer_edit, name="customer_edit"),
    path("<uuid:pk>/delete/", customer_delete, name="customer_delete"),
    path("<uuid:pk>/restore/", customer_restore, name="customer_restore"),
    path(
        "<uuid:customer_pk>/relations/",
        relation_views.relation_list,
        name="relation_list",
    ),
    path(
        "<uuid:customer_pk>/relations/create/",
        relation_views.relation_create,
        name="relation_create",
    ),
    path(
        "<uuid:customer_pk>/relations/<uuid:pk>/delete/",
        relation_views.relation_delete,
        name="relation_delete",
    ),
    # 标签管理（T4.4）
    path("tags/", tag_views.tag_list, name="tag_list"),
    path("tags/create/", tag_views.tag_create, name="tag_create"),
    path("tags/<uuid:pk>/edit/", tag_views.tag_edit, name="tag_edit"),
    path("tags/<uuid:pk>/delete/", tag_views.tag_delete, name="tag_delete"),
    # 重复检测与合并（T4.4）
    path("duplicates/", duplicate_views.duplicate_list, name="duplicate_list"),
    path("merge/", duplicate_views.merge_confirm, name="merge_confirm"),
    path("merge/do/", duplicate_views.merge_do, name="merge_do"),
    # 关系图 JSON API（T12.1 / ADR-010，vis-network 消费）
    path(
        "<uuid:pk>/graph/",
        graph_views.relationship_graph_data,
        name="relationship_graph",
    ),
    path(
        "<uuid:pk>/referral-graph/",
        graph_views.referral_graph_data,
        name="referral_graph",
    ),
]
