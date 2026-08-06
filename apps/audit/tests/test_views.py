"""审计日志查看视图测试（T10.2，RED 先行，规格 §17 / ADR-012）。

- 权限矩阵：未登录重定向登录页；已登录无 can_view_audit_logs 抛 403；
  有权限返回 200 并渲染记录；
- 分页与筛选：action 下拉过滤、q 文本搜索。
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.services import record_audit

pytestmark = pytest.mark.django_db


@pytest.fixture
def auditor() -> User:
    u = User(username="auditor", can_view_audit_logs=True)
    u.save()
    return u


@pytest.fixture
def plain() -> User:
    u = User(username="plain")
    u.save()
    return u


def test_anonymous_redirects_to_login(client: Client) -> None:
    response = client.get(reverse("audit:list"))

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_without_permission_is_forbidden(client: Client, plain: User) -> None:
    client.force_login(plain)

    assert client.get(reverse("audit:list")).status_code == 403


def test_with_permission_lists_logs(client: Client, auditor: User) -> None:
    record_audit(actor=auditor, action="customer.soft_delete", target_label="张三")
    client.force_login(auditor)

    response = client.get(reverse("audit:list"))

    assert response.status_code == 200
    assert b"customer.soft_delete" in response.content
    assert "张三".encode() in response.content
    assert b"auditor" in response.content


def test_filter_by_action(client: Client, auditor: User) -> None:
    record_audit(actor=auditor, action="customer.soft_delete", target_label="张三")
    record_audit(actor=auditor, action="export", target_label="客户名单导出")
    client.force_login(auditor)

    response = client.get(reverse("audit:list"), {"action": "export"})

    # action 下拉列出全部已出现动作，故用行专属的 target_label 断言过滤生效。
    assert "张三".encode() not in response.content
    assert "客户名单导出".encode() in response.content


def test_search_text(client: Client, auditor: User) -> None:
    record_audit(actor=auditor, action="export", target_label="客户档案导出")
    record_audit(actor=auditor, action="backup", target_label="每日备份")
    client.force_login(auditor)

    response = client.get(reverse("audit:list"), {"q": "档案"})

    assert "客户档案导出".encode() in response.content
    assert "每日备份".encode() not in response.content


def test_pagination(client: Client, auditor: User) -> None:
    for i in range(30):
        record_audit(actor=auditor, action="export", target_label=f"导出{i:02d}")
    client.force_login(auditor)

    first = client.get(reverse("audit:list"))
    assert first.status_code == 200
    assert "导出29".encode() in first.content  # 最新在前（created_at 倒序）
    assert "导出00".encode() not in first.content  # 最老落在第 2 页

    second = client.get(reverse("audit:list"), {"page": "2"})
    assert "导出00".encode() in second.content
    assert "导出29".encode() not in second.content
