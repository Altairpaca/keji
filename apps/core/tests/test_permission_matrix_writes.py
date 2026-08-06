"""权限矩阵测试（规格 §17 / §25）：无权限位普通用户访问关键写操作 → 403。

占位符 ``"<customer>"`` 等在运行时替换为 conftest fixture 的主键；权限校验
先于视图逻辑与对象查找执行，因此对象是否存在不影响 403 结果。
"""

import uuid
from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.claims.models import ClaimCase
from apps.core.tests.permission_matrix_data import WRITE_CASES, resolve_placeholders
from apps.customers.models import Customer, Tag
from apps.documents.models import Document
from apps.policies.models import Policy
from apps.tasks.models import Task


@pytest.mark.django_db
def test_plain_user_forbidden_on_key_write_urls(
    client: Any,
    plain_user: User,
    customer: Customer,
    tag: Tag,
    policy: Policy,
    claim: ClaimCase,
    task: Task,
    document: Document,
    target_user: User,
) -> None:
    fixtures: dict[str, Any] = {
        "customer": customer,
        "tag": tag,
        "policy": policy,
        "claim": claim,
        "task": task,
        "document": document,
        "user": target_user,
        "uuid": uuid.uuid4(),
    }
    client.force_login(plain_user)
    leaks: list[str] = []
    for name, method, kwargs, data in WRITE_CASES:
        url = reverse(name, kwargs=resolve_placeholders(kwargs, fixtures))
        response = getattr(client, method.lower())(url, data=data or None)
        if response.status_code != 403:
            leaks.append(f"{name} {method} {url} -> {response.status_code}")
    assert leaks == [], "以下写操作未强制权限位（普通用户应 403）：\n" + "\n".join(leaks)
