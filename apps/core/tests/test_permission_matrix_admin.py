"""权限矩阵测试（规格 §17 / §25）：is_superuser 经 has_bit 恒 True，不被权限门拦截。

抽查关键读/写 URL：管理员 GET 读页面 200、POST 写动作 302/200。
"""

from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.claims.models import ClaimCase
from apps.core.tests.permission_matrix_data import ADMIN_CASES, resolve_placeholders
from apps.customers.models import Customer, Tag
from apps.documents.models import Document
from apps.policies.models import Policy
from apps.tasks.models import Task


@pytest.mark.django_db
def test_admin_superuser_not_blocked_by_permission_gate(
    client: Any,
    admin_user: User,
    customer: Customer,
    delete_customer: Customer,
    tag: Tag,
    policy: Policy,
    claim: ClaimCase,
    task: Task,
    document: Document,
    trashed_document: Document,
    target_user: User,
) -> None:
    fixtures: dict[str, Any] = {
        "customer": customer,
        "delete_customer": delete_customer,
        "tag": tag,
        "policy": policy,
        "claim": claim,
        "task": task,
        "document": document,
        "trashed": trashed_document,
        "user": target_user,
    }
    client.force_login(admin_user)
    blocked: list[str] = []
    for name, method, kwargs, data, expected in ADMIN_CASES:
        kwargs = resolve_placeholders(kwargs, fixtures)
        data = resolve_placeholders(data, fixtures)
        response = getattr(client, method.lower())(reverse(name, kwargs=kwargs), data=data or None)
        if response.status_code != expected:
            blocked.append(f"{name} {method} -> {response.status_code} (期望 {expected})")
    assert blocked == [], "管理员被权限门误拦截：\n" + "\n".join(blocked)
