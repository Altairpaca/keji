"""权限矩阵测试的共享数据与工具（非测试文件，不参与收集）。

- URL 遍历工具：把 urlpatterns 展开为具体路径（登录保护测试用）。
- 占位符替换：用例表里 ``"<customer>"`` 等占位符在运行时换成 fixture 主键。
- 用例表：_WRITE_CASES（普通用户 403）、_ADMIN_CASES（管理员抽查）。
"""

import uuid
from collections.abc import Iterator
from typing import Any

from django.urls.resolvers import URLPattern, URLResolver

# 公开 URL：无需登录（登录/登出/PWA 资源），跳过登录保护断言。
PUBLIC_PATHS: set[str] = {
    "/accounts/login/",
    "/accounts/logout/",
    "/sw.js",
    "/manifest.json",
    "/offline/",
}

Route = tuple[str, URLPattern]


def sample_route(route: str) -> str:
    """路由模板 → 具体路径：``<uuid:pk>`` 等换为随机 UUID，其余转换器换为示例值。"""
    parts: list[str] = []
    i = 0
    while i < len(route):
        if route[i] == "<":
            end = route.index(">", i)
            converter, _, _name = route[i + 1 : end].partition(":")
            if converter == "uuid":
                value = str(uuid.uuid4())
            elif converter == "int":
                value = "1"
            else:  # str / slug / path
                value = "x"
            parts.append(value)
            i = end + 1
        else:
            parts.append(route[i])
            i += 1
    return "".join(parts)


def iter_patterns(urlpatterns: list[URLPattern | URLResolver]) -> Iterator[Route]:
    """递归展开 urlpatterns，产出 (具体路径, URLPattern)。跳过 admin。"""
    for pattern in urlpatterns:
        if isinstance(pattern, URLResolver):
            if pattern.namespace == "admin":
                continue
            prefix = sample_route(pattern.pattern._route)
            for sub_route, sub_pattern in iter_patterns(pattern.url_patterns):
                yield prefix + sub_route, sub_pattern
        else:
            yield sample_route(pattern.pattern._route), pattern


def placeholder_value(value: Any, fixtures: dict[str, Any]) -> Any:
    """单个值：``<name>`` → fixture 主键；列表逐项处理。"""
    if isinstance(value, list):
        return [placeholder_value(item, fixtures) for item in value]
    if isinstance(value, str) and value.startswith("<") and value.endswith(">"):
        name = value[1:-1]
        return getattr(fixtures[name], "pk", fixtures[name])
    return value


def resolve_placeholders(kwargs: dict[str, Any], fixtures: dict[str, Any]) -> dict[str, Any]:
    """把 ``"<name>"`` 占位符换成对应 fixture 对象的主键（uuid/整数）。"""
    return {key: placeholder_value(value, fixtures) for key, value in kwargs.items()}


# (url name, 请求方法, url kwargs, 无关紧要的表单数据)
WRITE_CASES: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = [
    ("customers:customer_create", "GET", {}, {}),
    ("customers:customer_edit", "GET", {"pk": "<customer>"}, {}),
    ("customers:customer_delete", "POST", {"pk": "<customer>"}, {}),
    ("customers:customer_restore", "POST", {"pk": "<customer>"}, {}),
    ("customers:relation_create", "GET", {"customer_pk": "<customer>"}, {}),
    ("customers:relation_delete", "POST", {"customer_pk": "<customer>", "pk": "<uuid>"}, {}),
    ("customers:tag_create", "GET", {}, {}),
    ("customers:tag_edit", "GET", {"pk": "<tag>"}, {}),
    ("customers:tag_delete", "POST", {"pk": "<tag>"}, {}),
    ("customers:duplicate_list", "GET", {}, {}),
    ("customers:merge_confirm", "GET", {}, {}),
    ("customers:merge_do", "POST", {}, {}),
    ("customers:import_preview", "GET", {}, {}),
    ("customers:import_confirm", "POST", {}, {}),
    ("customers:relationship_graph", "GET", {"pk": "<customer>"}, {}),
    ("customers:relationship_graph_page", "GET", {"pk": "<customer>"}, {}),
    ("customers:referral_graph", "GET", {"pk": "<customer>"}, {}),
    ("customers:referral_graph_page", "GET", {"pk": "<customer>"}, {}),
    ("documents:upload", "GET", {}, {}),
    ("documents:upload_result", "GET", {}, {}),
    ("documents:bulk_action", "POST", {}, {}),
    ("documents:trash_list", "GET", {}, {}),
    ("documents:trash_restore", "POST", {"pk": "<document>"}, {}),
    ("documents:trash_permanent_delete", "POST", {"pk": "<document>"}, {}),
    ("documents:trash_empty", "POST", {}, {}),
    ("documents:album_create", "GET", {}, {}),
    ("documents:album_edit", "GET", {"pk": "<uuid>"}, {}),
    ("documents:album_delete", "POST", {"pk": "<uuid>"}, {}),
    ("documents:document_detail", "GET", {"pk": "<document>"}, {}),
    ("documents:document_download", "GET", {"pk": "<document>"}, {}),
    ("documents:viewer", "GET", {"pk": "<document>"}, {}),
    ("documents:document_image", "GET", {"pk": "<document>"}, {}),
    ("documents:document_thumb", "GET", {"pk": "<document>"}, {}),
    ("policies:policy_create", "GET", {}, {}),
    ("policies:policy_edit", "GET", {"pk": "<policy>"}, {}),
    ("policies:policy_change_status", "POST", {"pk": "<policy>"}, {}),
    ("policies:policy_delete", "POST", {"pk": "<policy>"}, {}),
    ("policies:policy_restore", "POST", {"pk": "<policy>"}, {}),
    ("policies:policy_document_list", "GET", {"pk": "<policy>"}, {}),
    ("policies:policy_document_attach", "POST", {"pk": "<policy>"}, {}),
    ("policies:policy_document_detach", "POST", {"pk": "<policy>", "doc_pk": "<document>"}, {}),
    ("policies:reminder_list", "GET", {}, {}),
    ("policies:reminder_mark_paid", "POST", {"pk": "<policy>"}, {}),
    ("policies:reminder_sync", "POST", {"pk": "<policy>"}, {}),
    ("claims:claim_create", "GET", {}, {}),
    ("claims:claim_edit", "GET", {"pk": "<claim>"}, {}),
    ("claims:claim_change_status", "POST", {"pk": "<claim>"}, {}),
    ("claims:claim_delete", "POST", {"pk": "<claim>"}, {}),
    ("claims:claim_restore", "POST", {"pk": "<claim>"}, {}),
    ("claims:claim_instantiate", "POST", {"pk": "<claim>"}, {}),
    ("claims:claim_material_add", "GET", {"pk": "<claim>"}, {}),
    ("claims:claim_material_status", "POST", {"pk": "<claim>", "mid": "<uuid>"}, {}),
    ("claims:claim_material_delete", "POST", {"pk": "<claim>", "mid": "<uuid>"}, {}),
    ("claims:claim_export_zip", "GET", {"claim_pk": "<claim>"}, {}),
    ("claims:material_attach_document", "POST", {"pk": "<claim>", "material_id": "<uuid>"}, {}),
    ("claims:material_detach_document", "POST", {"pk": "<claim>", "material_id": "<uuid>"}, {}),
    ("claims:material_download", "GET", {"pk": "<claim>", "material_id": "<uuid>"}, {}),
    ("tasks:task_create", "GET", {}, {}),
    ("tasks:task_edit", "GET", {"pk": "<task>"}, {}),
    ("tasks:task_complete", "POST", {"pk": "<task>"}, {}),
    ("tasks:task_cancel", "POST", {"pk": "<task>"}, {}),
    ("tasks:task_delete", "POST", {"pk": "<task>"}, {}),
    ("tasks:quick_followup", "POST", {}, {}),
    ("activities:event_list", "GET", {}, {}),
    ("activities:work_event_create", "GET", {}, {}),
    ("activities:work_event_edit", "GET", {"pk": "<uuid>"}, {}),
    ("activities:work_event_delete", "POST", {"pk": "<uuid>"}, {}),
    ("activities:communication_create", "GET", {}, {}),
    ("activities:communication_quick", "POST", {}, {}),
    ("activities:communication_edit", "GET", {"pk": "<uuid>"}, {}),
    ("activities:communication_delete", "POST", {"pk": "<uuid>"}, {}),
    ("activities:customer_timeline", "GET", {"customer_pk": "<customer>"}, {}),
    ("dashboard:home", "GET", {}, {}),
    ("dashboard:search", "GET", {}, {}),
    ("accounts:user_list", "GET", {}, {}),
    ("accounts:user_create", "GET", {}, {}),
    ("accounts:user_edit", "GET", {"pk": "<user>"}, {}),
    ("accounts:user_toggle_active", "POST", {"pk": "<user>"}, {}),
    ("core:saved_view_save", "POST", {}, {}),
    ("core:saved_view_list", "GET", {}, {}),
    ("core:saved_view_apply", "GET", {"pk": "<uuid>"}, {}),
    ("core:saved_view_delete", "POST", {"pk": "<uuid>"}, {}),
    ("audit:list", "GET", {}, {}),
    ("export:customers", "GET", {}, {}),
    ("export:customer_profile", "GET", {"pk": "<customer>"}, {}),
    ("export:customer_timeline", "GET", {"pk": "<customer>"}, {}),
    ("export:customer_archive", "GET", {"pk": "<customer>"}, {}),
    ("work_event_create_for_customer", "GET", {"customer_pk": "<customer>"}, {}),
]

# (url name, 请求方法, url kwargs, 表单数据, 期望状态码)
ADMIN_CASES: list[tuple[str, str, dict[str, Any], dict[str, Any], int]] = [
    ("dashboard:home", "GET", {}, {}, 200),
    ("customers:customer_list", "GET", {}, {}, 200),
    ("customers:customer_create", "GET", {}, {}, 200),
    ("customers:customer_detail", "GET", {"pk": "<customer>"}, {}, 200),
    ("customers:customer_edit", "GET", {"pk": "<customer>"}, {}, 200),
    ("customers:customer_delete", "POST", {"pk": "<delete_customer>"}, {}, 302),
    ("customers:tag_list", "GET", {}, {}, 200),
    ("customers:tag_create", "GET", {}, {}, 200),
    ("customers:tag_delete", "POST", {"pk": "<tag>"}, {}, 302),
    ("customers:duplicate_list", "GET", {}, {}, 200),
    ("documents:document_list", "GET", {}, {}, 200),
    ("documents:upload", "GET", {}, {}, 200),
    (
        "documents:bulk_action",
        "POST",
        {},
        {"action": "important", "doc_pks": ["<document>"], "value": "1"},
        302,
    ),
    ("documents:trash_list", "GET", {}, {}, 200),
    ("documents:trash_permanent_delete", "POST", {"pk": "<trashed>"}, {}, 302),
    ("documents:trash_empty", "POST", {}, {}, 302),
    ("documents:album_list", "GET", {}, {}, 200),
    ("policies:policy_list", "GET", {}, {}, 200),
    ("policies:policy_create", "GET", {}, {}, 200),
    ("policies:policy_detail", "GET", {"pk": "<policy>"}, {}, 200),
    (
        "policies:policy_change_status",
        "POST",
        {"pk": "<policy>"},
        {"new_status": "paying", "note": "m"},
        302,
    ),
    ("policies:policy_delete", "POST", {"pk": "<policy>"}, {}, 302),
    ("claims:claim_list", "GET", {}, {}, 200),
    ("claims:claim_create", "GET", {}, {}, 200),
    ("claims:claim_detail", "GET", {"pk": "<claim>"}, {}, 200),
    (
        "claims:claim_change_status",
        "POST",
        {"pk": "<claim>"},
        {"new_status": "waiting_materials"},
        302,
    ),
    ("claims:claim_delete", "POST", {"pk": "<claim>"}, {}, 302),
    ("tasks:task_list", "GET", {}, {}, 200),
    ("tasks:task_create", "GET", {}, {}, 200),
    ("tasks:task_complete", "POST", {"pk": "<task>"}, {}, 302),
    ("activities:event_list", "GET", {}, {}, 200),
    ("activities:work_event_create", "GET", {}, {}, 200),
    ("activities:customer_timeline", "GET", {"customer_pk": "<customer>"}, {}, 200),
    ("accounts:profile", "GET", {}, {}, 200),
    ("accounts:user_list", "GET", {}, {}, 200),
    ("accounts:user_create", "GET", {}, {}, 200),
    ("accounts:user_toggle_active", "POST", {"pk": "<user>"}, {}, 302),
    (
        "core:saved_view_save",
        "POST",
        {},
        {"app_label": "customers", "model_name": "customer", "name": "x", "filters": "{}"},
        200,
    ),
    ("core:saved_view_list", "GET", {}, {}, 200),
    ("audit:list", "GET", {}, {}, 200),
    ("export:customers", "GET", {}, {}, 200),
    ("export:customer_profile", "GET", {"pk": "<customer>"}, {}, 200),
]
