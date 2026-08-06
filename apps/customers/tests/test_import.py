"""T4.5 客户 CSV 批量导入测试（RED 先行，规格 §16）。

覆盖：
- 模板下载：UTF-8 BOM、含全部列头、权限边界
- parse_csv：UTF-8 BOM / GBK 编码容错、列名归一（姓名* → 姓名）
- validate_row：姓名空、出生日期格式、手机号格式（宽松）
- preview_rows：total / valid_rows / invalid_rows 统计与行号
- import_customers：全合法导入（默认状态、标签）、重复手机号跳过、
  有错行整体拒绝不落库、create 期异常整体回滚、成功后重复导入全跳过
- 视图：预览 GET/POST、确认导入全流程、权限 403、无会话重定向
"""

import csv
import io
from datetime import date
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services.customers import create_customer
from apps.customers.services.importer import (
    IMPORT_COLUMNS,
    import_customers,
    parse_csv,
    preview_rows,
    validate_row,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# 工具与夹具
# ---------------------------------------------------------------------------


def _csv_bytes(headers: list[str], rows: list[list[str]], encoding: str = "utf-8") -> bytes:
    """按 headers + rows 生成 CSV 字节。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode(encoding)


def _valid_row(name: str = "张三", phone: str = "") -> list[str]:
    """一条校验合法的 CSV 数据行（姓名 + 出生日期保证 create 可通过）。"""
    return [name, "男", phone, "", "1990-01-01", "", "上海", "工程师", "备注", "vip"]


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent")
    u.save()
    return u


@pytest.fixture
def manager(db: None) -> User:
    """客户管理权限用户。"""
    u = User(username="import_manager", can_view_customers=True, can_manage_customers=True)
    u.save()
    return u


@pytest.fixture
def viewer(db: None) -> User:
    """仅查看权限用户。"""
    u = User(username="import_viewer", can_view_customers=True)
    u.save()
    return u


@pytest.fixture
def no_perm(db: None) -> User:
    u = User(username="import_no_perm")
    u.save()
    return u


def login(client: Any, user: User) -> None:
    client.force_login(user)


# ---------------------------------------------------------------------------
# 模板下载
# ---------------------------------------------------------------------------


def test_download_template_returns_csv_with_bom_and_headers(client: Any, viewer: User) -> None:
    login(client, viewer)

    resp = client.get(reverse("customers:import_template"))

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert resp.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    decoded = resp.content.decode("utf-8-sig")
    for column in IMPORT_COLUMNS:
        assert column in decoded


def test_download_template_requires_view_permission(client: Any, no_perm: User) -> None:
    login(client, no_perm)

    resp = client.get(reverse("customers:import_template"))

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------


def test_parse_csv_utf8_bom_normalizes_column_names() -> None:
    content = "\ufeff姓名*,手机号\n张三,13800138000\n".encode("utf-8")

    rows = parse_csv(content)

    assert len(rows) == 1
    assert rows[0]["姓名"] == "张三"
    assert rows[0]["手机号"] == "13800138000"


def test_parse_csv_gbk_chinese_fallback() -> None:
    content = "姓名,备注\n李四,客户备注中文\n".encode("gbk")

    rows = parse_csv(content)

    assert len(rows) == 1
    assert rows[0]["姓名"] == "李四"
    assert rows[0]["备注"] == "客户备注中文"


def test_parse_csv_strips_blank_lines() -> None:
    content = "姓名,手机号\n张三,13800138000\n\n李四,13900139000\n".encode()

    rows = parse_csv(content)

    assert [row["姓名"] for row in rows] == ["张三", "李四"]


# ---------------------------------------------------------------------------
# validate_row
# ---------------------------------------------------------------------------


def _make_row(**overrides: str) -> dict[str, str]:
    base = {
        "姓名": "张三",
        "性别": "男",
        "手机号": "13800138000",
        "微信昵称": "",
        "出生日期(YYYY-MM-DD)": "1990-01-01",
        "年龄说明": "",
        "地区": "上海",
        "职业": "工程师",
        "备注": "",
        "标签(逗号分隔)": "",
    }
    base.update(overrides)
    return base


def test_validate_row_valid_row_returns_no_errors() -> None:
    assert validate_row(_make_row(), line_no=2) == []


def test_validate_row_missing_name() -> None:
    errors = validate_row(_make_row(姓名="   "), line_no=2)

    assert errors == ["姓名不能为空"]


def test_validate_row_bad_birth_date_format() -> None:
    errors = validate_row(_make_row(**{"出生日期(YYYY-MM-DD)": "1990/01/01"}), line_no=2)

    assert errors == ["出生日期格式应为 YYYY-MM-DD"]


def test_validate_row_bad_phone() -> None:
    errors = validate_row(_make_row(手机号="abcd"), line_no=2)

    assert errors == ["手机号格式不正确"]


def test_validate_row_multiple_errors() -> None:
    errors = validate_row(
        _make_row(姓名="", **{"出生日期(YYYY-MM-DD)": "nope"}, 手机号="12"),
        line_no=2,
    )

    assert set(errors) == {"姓名不能为空", "出生日期格式应为 YYYY-MM-DD", "手机号格式不正确"}


# ---------------------------------------------------------------------------
# preview_rows
# ---------------------------------------------------------------------------


def test_preview_rows_counts_and_line_numbers() -> None:
    content = _csv_bytes(
        IMPORT_COLUMNS,
        [
            _valid_row("张三", "13800138000"),
            _valid_row("", "13900139000"),  # 姓名空 → 无效
            _valid_row("李四", "13700137000"),
        ],
    )

    preview = preview_rows(content)

    assert preview["total"] == 3
    assert len(preview["valid_rows"]) == 2
    assert len(preview["invalid_rows"]) == 1
    invalid = preview["invalid_rows"][0]
    assert invalid["line_no"] == 3
    assert invalid["errors"] == ["姓名不能为空"]
    assert invalid["row"]["姓名"] == ""


# ---------------------------------------------------------------------------
# import_customers
# ---------------------------------------------------------------------------


def test_import_valid_rows_creates_customers_with_defaults_and_tags(user: User) -> None:
    content = _csv_bytes(
        IMPORT_COLUMNS,
        [
            [
                "张三",
                "男",
                "13800138000",
                "zs",
                "1990-01-01",
                "",
                "上海",
                "工程师",
                "备注",
                "vip,老客户",
            ],
            ["李四", "女", "13900139000", "", "", "约40岁", "北京", "", "", ""],
        ],
    )
    report = import_customers(content=content, owner=user, created_by=user)

    assert report["imported"] == 2
    assert report["skipped"] == []
    assert report["failed"] == []
    assert Customer.objects.count() == 2

    zhang = Customer.objects.get(name="张三")
    assert zhang.owner == user
    assert zhang.created_by == user
    assert zhang.gender == "男"
    assert zhang.phone == "13800138000"
    assert zhang.wechat_nickname == "zs"
    assert zhang.birth_date == date(1990, 1, 1)
    assert zhang.region == "上海"
    assert zhang.occupation == "工程师"
    assert zhang.notes == "备注"
    assert zhang.status is not None
    assert zhang.status.name == "待首次联系"
    assert {t.name for t in zhang.tags.all()} == {"vip", "老客户"}

    li = Customer.objects.get(name="李四")
    assert li.birth_date is None
    assert li.age_note == "约40岁"


def test_import_duplicate_phone_skipped(user: User) -> None:
    create_customer(
        name="已有客户", owner=user, created_by=user, phone="13800138000", age_note="约30岁"
    )
    content = _csv_bytes(IMPORT_COLUMNS, [_valid_row("张三", "13800138000")])

    report = import_customers(content=content, owner=user, created_by=user)

    assert report["imported"] == 0
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["name"] == "张三"
    assert report["skipped"][0]["reason"] == "手机号重复"
    assert Customer.objects.count() == 1


def test_import_invalid_row_rejects_all_and_persists_nothing(user: User) -> None:
    content = _csv_bytes(
        IMPORT_COLUMNS,
        [_valid_row("张三", "13800138000"), _valid_row("", "13900139000")],
    )

    report = import_customers(content=content, owner=user, created_by=user)

    assert report["imported"] == 0
    assert len(report["failed"]) == 1
    assert report["failed"][0]["line_no"] == 3
    assert "姓名不能为空" in report["failed"][0]["reason"]
    assert Customer.objects.count() == 0


def test_import_dirty_row_create_error_rolls_back_everything(user: User) -> None:
    # 姓名/手机号/格式均合法，但出生日期与年龄说明双缺 → create_customer 抛 ValueError。
    # 首行（本可成功）必须一并回滚，不得部分写入。
    content = _csv_bytes(
        IMPORT_COLUMNS,
        [
            _valid_row("张三", "13800138000"),
            ["李四", "女", "13900139000", "", "", "", "北京", "", "", ""],
        ],
    )

    with pytest.raises(ImportError):
        import_customers(content=content, owner=user, created_by=user)

    assert Customer.objects.count() == 0


def test_import_again_after_success_skips_all(user: User) -> None:
    content = _csv_bytes(IMPORT_COLUMNS, [_valid_row("张三", "13800138000")])
    first = import_customers(content=content, owner=user, created_by=user)
    assert first["imported"] == 1

    second = import_customers(content=content, owner=user, created_by=user)

    assert second["imported"] == 0
    assert len(second["skipped"]) == 1
    assert Customer.objects.count() == 1


def test_import_dry_run_persists_nothing(user: User) -> None:
    content = _csv_bytes(IMPORT_COLUMNS, [_valid_row("张三", "13800138000")])

    report = import_customers(content=content, owner=user, created_by=user, dry_run=True)

    assert report["imported"] == 1
    assert Customer.objects.count() == 0


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


def test_import_preview_get_shows_form(client: Any, manager: User) -> None:
    login(client, manager)

    resp = client.get(reverse("customers:import_preview"))

    assert resp.status_code == 200
    assert b'type="file"' in resp.content
    assert resp.context is not None


def test_import_preview_requires_manage_permission(client: Any, viewer: User) -> None:
    login(client, viewer)

    resp = client.get(reverse("customers:import_preview"))

    assert resp.status_code == 403


def test_import_preview_post_lists_invalid_rows(client: Any, manager: User) -> None:
    login(client, manager)
    content = _csv_bytes(IMPORT_COLUMNS, [_valid_row("", "13800138000")])

    resp = client.post(
        reverse("customers:import_preview"),
        {"file": SimpleUploadedFile("customers.csv", content, content_type="text/csv")},
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "姓名不能为空" in body
    assert "无效 1" in body


def test_import_confirm_requires_manage_permission(client: Any, viewer: User) -> None:
    login(client, viewer)

    resp = client.post(reverse("customers:import_confirm"))

    assert resp.status_code == 403


def test_import_confirm_without_preview_redirects_back(client: Any, manager: User) -> None:
    login(client, manager)

    resp = client.post(reverse("customers:import_confirm"))

    assert resp.status_code == 302
    assert resp.url == reverse("customers:import_preview")


def test_import_full_flow_preview_then_confirm(client: Any, manager: User) -> None:
    login(client, manager)
    content = _csv_bytes(
        IMPORT_COLUMNS,
        [
            ["张三", "男", "13800138000", "zs", "1990-01-01", "", "上海", "工程师", "备注", "vip"],
            ["李四", "女", "13900139000", "", "", "约40岁", "北京", "", "", ""],
        ],
    )

    resp = client.post(
        reverse("customers:import_preview"),
        {"file": SimpleUploadedFile("customers.csv", content, content_type="text/csv")},
    )
    assert resp.status_code == 200
    assert "有效 2" in resp.content.decode()

    resp = client.post(reverse("customers:import_confirm"))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "成功 2" in body
    assert Customer.objects.count() == 2
