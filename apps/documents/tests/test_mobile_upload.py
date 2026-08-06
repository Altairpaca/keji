"""手机端多选上传 UI（T6.5，规格 §3/§9/§19）。

- 模板（移动优先）：capture 拍照输入 + 无 capture 相册多选输入、
  Alpine 预览网格与逐文件状态、44px 触控目标、CSRF、关联表单区；
- 视图：POST 部分成功部分失败 → 结果页成功/失败计数与明细；
  同内容重复（SHA-256 去重）→ 跳过计数，不算失败。
"""

from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.documents.tests.test_upload import _make_upload, _png_bytes


@pytest.fixture
def uploader(db: Any) -> User:
    return User(username="mobile_uploader", can_view_customers=True, can_manage_customers=True)


def test_upload_get_mobile_first_markup(client: Any, uploader: Any) -> None:
    """GET 上传页：拍照/相册双输入、Alpine 预览网格、关联表单、CSRF、触控目标≥44px。"""
    client.force_login(uploader)

    response = client.get(reverse("documents:upload"))
    assert response.status_code == 200
    html = response.content.decode()

    # 两个隐藏文件输入：拍照（capture）与相册多选（唯一提交载体 name=files）
    assert html.count('type="file"') >= 2
    assert 'capture="environment"' in html
    assert 'name="files"' in html
    assert "multiple" in html
    # 相册输入自身不带 capture（避免总是弹相机）
    gallery = html[html.index('id="gallery-input"') :]
    assert "capture" not in gallery.split(">", 1)[0]
    # Alpine 上传器 + 预览网格 + 逐文件状态
    assert 'x-data="uploader()"' in html
    assert 'id="upload-preview"' in html
    assert 'x-for="item in items"' in html
    assert "个文件" in html  # 已选计数
    # 触控目标 ≥44px：触发按钮 h-14（56px）、移除按钮 h-11（44px）、提交按钮 h-12（48px）
    assert "h-14" in html
    assert "h-11" in html
    assert "h-12" in html
    # CSRF 与关联表单区
    assert 'name="csrfmiddlewaretoken"' in html
    assert 'name="customers"' in html
    assert 'name="albums"' in html
    assert 'name="title"' in html
    assert 'name="note"' in html
    assert 'name="sensitivity"' in html
    # 上下文提供选择项与既有 queryset
    assert "customer_choices" in response.context
    assert "album_choices" in response.context
    assert "customers" in response.context
    assert "albums" in response.context


def test_upload_post_partial_success_shows_result_counts(
    client: Any, uploader: Any, isolated_storage: Any
) -> None:
    """POST 一合法一非法：结果页成功/失败两组计数，合法文件入库，失败文件列出原因。"""
    client.force_login(uploader)

    good = _make_upload("ok.png", _png_bytes(7), "image/png")
    bad = _make_upload("evil.exe", b"MZ\x90\x00\x03", "application/octet-stream")
    response = client.post(reverse("documents:upload"), {"files": [good, bad]}, follow=True)

    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-success="1"' in html
    assert 'data-skipped="0"' in html
    assert 'data-failed="1"' in html
    assert "evil.exe" in html  # 失败明细列出文件名
    assert "不支持的文件类型" in html


def test_upload_post_duplicate_counts_skipped(
    client: Any, uploader: Any, isolated_storage: Any
) -> None:
    """同一内容两次上传：第二次按 SHA-256 去重 → 跳过计数（不算失败）。"""
    client.force_login(uploader)

    content = _png_bytes(8)
    response = client.post(
        reverse("documents:upload"),
        {
            "files": [
                _make_upload("a.png", content, "image/png"),
                _make_upload("b.png", content, "image/png"),
            ]
        },
        follow=True,
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-success="1"' in html
    assert 'data-skipped="1"' in html
    assert 'data-failed="0"' in html
