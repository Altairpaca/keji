"""权限矩阵测试（规格 §17 / §25）：登录保护全覆盖 + 审计位抽查。

本文件只承载「无需业务对象」的矩阵断言：匿名访问全部受保护 URL 必须 302，
以及审计查看位的四态验证。普通用户 403 / 管理员 200 矩阵见
test_permission_matrix_writes.py 与 test_permission_matrix_admin.py。

新增 URL 时若忘记挂 require_permission，本文件会在匿名访问时得到 200 并失败。
"""

from typing import Any

import pytest
from django.urls import resolve

from apps.accounts.models import User
from apps.core.tests.permission_matrix_data import PUBLIC_PATHS, iter_patterns


@pytest.mark.django_db
def test_every_protected_url_redirects_anonymous(client: Any) -> None:
    from config.urls import urlpatterns

    unprotected: list[str] = []
    for route, pattern in iter_patterns(urlpatterns):
        path = "/" + route
        if path in PUBLIC_PATHS:
            continue
        resolve(path)  # 生成失败（转换器替换错误）立即暴露
        response = client.get(path)
        if response.status_code == 405:
            response = client.post(path)
        if response.status_code != 302:
            unprotected.append(
                f"{path} ({pattern.name or pattern.callback}) -> {response.status_code}"
            )
    assert unprotected == [], "以下 URL 未受登录保护：\n" + "\n".join(unprotected)


@pytest.mark.django_db
def test_audit_view_gated_by_can_view_audit_logs(
    client: Any,
    admin_user: User,
    plain_user: User,
) -> None:
    """审计查看视图已挂 ``can_view_audit_logs``（规格 §17）。

    仅该位用户 200；无权限普通用户 403；管理员 200；backup 尚无 URL。
    """
    resolver = resolve("/audit/")
    assert resolver.url_name == "list"

    client.force_login(plain_user)
    assert client.get("/audit/").status_code == 403

    viewer = User(username="matrix-auditor", can_view_audit_logs=True)
    viewer.save()
    assert isinstance(viewer, User)
    client.force_login(viewer)
    assert client.get("/audit/").status_code == 200

    client.force_login(admin_user)
    assert client.get("/audit/").status_code == 200

    # backup 目前仅有管理命令，无 URL（can_backup 位随备份视图落地时挂上）。
    from config.urls import urlpatterns

    names = [pattern.name or "" for _, pattern in iter_patterns(urlpatterns)]
    assert not any("backup" in n for n in names), names
    assert User.PERMISSION_BITS[10] == "can_backup"
