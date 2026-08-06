"""导出功能测试（规格 §16 导出 / §17 can_export_data / §10 敏感导出审计，T9.5）。

- 服务：CSV 表头+行（标签合并 / 空值）、profile 关联概要+最近时间线、
  timeline 行数、zip 结构（3 类文件、文档内容一致、文件名 sanitize、缺文件占位）
- 视图：200 + Content-Disposition（中文名 filename*=UTF-8''）、无 can_export_data 403、
  匿名 302、筛选参数生效（导出只含筛选结果）
"""

import csv
import io
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest

from apps.accounts.models import User
from apps.activities.models import WorkEvent
from apps.core.services.exports import (
    export_customer_archive_zip,
    export_customer_profile,
    export_customer_timeline,
    export_customers_csv,
)
from apps.customers.models import Customer, CustomerRelation, CustomerStatus
from apps.customers.services import assign_tags, create_customer
from apps.documents.models import Document
from apps.documents.storage import default_storage, new_storage_key
from apps.policies.models.policy import Policy
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

LIST_EXPORT_URL = "/export/customers/"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _csv_rows(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def _make_user(username: str, **bits: bool) -> User:
    user = User(username=username, **bits)
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def status_potential(db: None) -> CustomerStatus:
    status: CustomerStatus = CustomerStatus.objects.create(name="潜在客户", is_system=True)
    return status


@pytest.fixture
def data_owner(db: None) -> User:
    """客户数据的归属用户（服务层测试用）。"""
    return _make_user("data_owner", can_export_data=True)


@pytest.fixture
def customer_a(db: None, status_potential: CustomerStatus, data_owner: User) -> Customer:
    customer = create_customer(
        name="张三",
        owner=data_owner,
        created_by=data_owner,
        gender=Customer.Gender.MALE,
        phone="13800138000",
        wechat_nickname="nick-a",
        birth_date=datetime(1990, 1, 1).date(),
        age_note="约36岁",
        region="上海",
        occupation="教师",
        source="朋友介绍",
        priority=Customer.Priority.HIGH,
        last_contact_date=datetime(2026, 1, 5).date(),
        next_followup_date=datetime(2026, 2, 1).date(),
        notes="重要客户",
        status=status_potential,
    )
    assign_tags(customer, ["vip", "老客户"])
    return customer


@pytest.fixture
def customer_b(db: None, data_owner: User) -> Customer:
    return create_customer(
        name="李四",
        owner=data_owner,
        created_by=data_owner,
        age_note="约30岁",
    )


# ---------------------------------------------------------------------------
# 服务：客户名单 CSV
# ---------------------------------------------------------------------------


def test_customers_csv_has_utf8_bom(customer_a: Customer) -> None:
    data = export_customers_csv(Customer.objects.all())
    assert data.startswith(b"\xef\xbb\xbf")


def test_customers_csv_header_and_row(customer_a: Customer, customer_b: Customer) -> None:
    data = export_customers_csv(Customer.objects.filter(pk=customer_a.pk))
    rows = _csv_rows(data)

    assert rows[0] == [
        "姓名",
        "性别",
        "手机号",
        "微信昵称",
        "出生日期",
        "年龄说明",
        "地区",
        "职业",
        "来源",
        "状态",
        "优先级",
        "标签",
        "最后联系",
        "下次跟进",
        "备注",
    ]
    assert len(rows) == 2  # 表头 + 一行

    row = rows[1]
    assert row[0] == "张三"
    assert row[1] == "男"
    assert row[2] == "13800138000"
    assert row[3] == "nick-a"
    assert row[4] == "1990-01-01"
    assert row[5] == "约36岁"
    assert row[6] == "上海"
    assert row[7] == "教师"
    assert row[8] == "朋友介绍"
    assert row[9] == "潜在客户"
    assert row[10] == "高"
    assert row[11] == "vip,老客户"
    assert row[12] == "2026-01-05"
    assert row[13] == "2026-02-01"
    assert row[14] == "重要客户"


def test_customers_csv_empty_values_are_blank(customer_b: Customer) -> None:
    data = export_customers_csv(Customer.objects.filter(pk=customer_b.pk))
    rows = _csv_rows(data)
    row = rows[1]
    assert row[0] == "李四"
    assert row[1] == "未知"  # gender 默认值
    assert row[2] == ""  # phone
    assert row[4] == ""  # birth_date
    assert row[6] == ""  # region
    # 状态：未显式指定时取系统默认状态（数据迁移已播种），故不为空
    assert row[9] != ""
    assert row[11] == ""  # 标签
    assert row[12] == ""  # 最后联系
    assert row[13] == ""  # 下次跟进
    assert row[14] == ""  # 备注


# ---------------------------------------------------------------------------
# 服务：客户档案摘要 CSV
# ---------------------------------------------------------------------------


def test_profile_contains_full_fields_and_summary(
    customer_a: Customer, customer_b: Customer
) -> None:
    # 关联数据：1 保单、1 待办、1 文档、1 关系、1 工作事件
    Policy.objects.create(
        insurer="平安",
        name="重疾险",
        policy_no="POL-001",
        policyholder=customer_a,
    )
    Task.objects.create(
        title="催收续期保费",
        customer=customer_a,
        due_date=datetime(2026, 2, 1).date(),
    )
    doc_key = new_storage_key()
    default_storage.save(doc_key, io.BytesIO(b"doc-content"))
    doc = Document.objects.create(
        original_name="身份证.png",
        storage_key=doc_key,
        mime_type="image/png",
        size=11,
        sha256="abc",
    )
    doc.customers.add(customer_a)
    CustomerRelation.objects.create(
        from_customer=customer_a,
        to_customer=customer_b,
        relation_type=CustomerRelation.RelationType.SPOUSE,
    )
    WorkEvent.objects.create(
        title="拜访谈续保",
        customer=customer_a,
        summary="客户倾向加保",
        occurred_at=datetime(2026, 1, 10, 14, 30, tzinfo=UTC),
    )

    data = export_customer_profile(customer_a)
    rows = _csv_rows(data)

    fields = {row[0]: row[1] for row in rows if len(row) == 2}
    assert fields["姓名"] == "张三"
    assert fields["性别"] == "男"
    assert fields["手机号"] == "13800138000"
    assert fields["优先级"] == "高"
    assert fields["保单数"] == "1"
    assert fields["理赔数"] == "0"
    assert fields["待办数"] == "1"
    assert fields["文档数"] == "1"
    assert fields["关系数"] == "1"

    # 最近时间线（最多 5 条）：表头 + 各条目；文档上传条目 created_at 更新，
    # 故按标题定位工作事件行，而不是断言首行
    timeline_header_idx = next(i for i, row in enumerate(rows) if row and row[0] == "类型")
    assert rows[timeline_header_idx] == ["类型", "时间", "标题", "摘要"]
    timeline_rows = [row for row in rows[timeline_header_idx + 1 :] if len(row) == 4]
    by_title = {row[2]: row for row in timeline_rows}
    assert by_title["拜访谈续保"][0] == "工作事件"
    assert by_title["拜访谈续保"][1] == "2026-01-10 14:30"
    assert by_title["拜访谈续保"][3] == "客户倾向加保"
    assert by_title["身份证.png"][0] == "文件上传"


# ---------------------------------------------------------------------------
# 服务：客户时间线 CSV
# ---------------------------------------------------------------------------


def test_timeline_csv_rows(customer_a: Customer) -> None:
    WorkEvent.objects.create(
        title="第一次拜访",
        customer=customer_a,
        summary="初次接触",
        occurred_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
    )
    WorkEvent.objects.create(
        title="电话回访",
        customer=customer_a,
        summary="确认保单生效",
        occurred_at=datetime(2026, 1, 12, 11, 0, tzinfo=UTC),
    )

    data = export_customer_timeline(customer_a)
    rows = _csv_rows(data)

    assert rows[0] == ["类型", "时间", "标题", "摘要"]
    assert len(rows) == 3  # 表头 + 2 条

    by_title = {row[2]: row for row in rows[1:]}
    assert by_title["第一次拜访"][0] == "工作事件"
    assert by_title["第一次拜访"][1] == "2026-01-10 09:00"
    assert by_title["第一次拜访"][3] == "初次接触"
    # 时间线按 occurred_at 倒序
    assert rows[1][2] == "电话回访"


# ---------------------------------------------------------------------------
# 服务：客户全部资料 ZIP
# ---------------------------------------------------------------------------


def test_archive_zip_structure_and_content(customer_a: Customer) -> None:
    doc_key = new_storage_key()
    default_storage.save(doc_key, io.BytesIO(b"doc-content"))
    doc = Document.objects.create(
        original_name="护照.png",
        storage_key=doc_key,
        mime_type="image/png",
        size=11,
        sha256="abc",
    )
    doc.customers.add(customer_a)
    WorkEvent.objects.create(
        title="档案会议",
        customer=customer_a,
        occurred_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
    )

    data, filename = export_customer_archive_zip(customer_a)

    assert filename == "张三_全部资料.zip"
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "张三/00_客户档案.csv" in names
    assert "张三/01_时间线.csv" in names
    assert "张三/02_文档/护照.png" in names
    assert zf.read("张三/02_文档/护照.png") == b"doc-content"
    # 00 为 profile CSV（含 BOM），01 为 timeline CSV
    assert zf.read("张三/00_客户档案.csv").startswith(b"\xef\xbb\xbf")
    assert zf.read("张三/01_时间线.csv").startswith(b"\xef\xbb\xbf")


def test_archive_zip_sanitizes_path_separators(data_owner: User) -> None:
    customer = create_customer(
        name="张/三",
        owner=data_owner,
        created_by=data_owner,
        age_note="约40岁",
    )
    doc_key = new_storage_key()
    default_storage.save(doc_key, io.BytesIO(b"scan"))
    doc = Document.objects.create(
        original_name="扫/描.png",
        storage_key=doc_key,
        mime_type="image/png",
        size=4,
        sha256="scan",
    )
    doc.customers.add(customer)

    data, filename = export_customer_archive_zip(customer)

    assert filename == "张_三_全部资料.zip"
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "张_三/00_客户档案.csv" in names
    assert "张_三/02_文档/扫_描.png" in names


def test_archive_zip_writes_placeholder_for_missing_file(customer_a: Customer) -> None:
    missing_doc = Document.objects.create(
        original_name="缺失文件.jpg",
        storage_key="originals/00/not-exists",
        mime_type="image/jpeg",
        size=0,
        sha256="missing",
    )
    missing_doc.customers.add(customer_a)

    data, _ = export_customer_archive_zip(customer_a)
    zf = zipfile.ZipFile(io.BytesIO(data))
    placeholder = zf.read("张三/02_文档/缺失文件.jpg").decode("utf-8")
    assert "文件缺失" in placeholder


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


@pytest.fixture
def exporter(db: None) -> User:
    return _make_user(
        "exporter",
        can_view_customers=True,
        can_export_data=True,
    )


@pytest.fixture
def viewer(db: None) -> User:
    """可查看客户但无 can_export_data。"""
    return _make_user("viewer", can_view_customers=True)


def test_export_customers_view_ok(client: Any, exporter: User, customer_a: Customer) -> None:
    client.force_login(exporter)
    response = client.get(LIST_EXPORT_URL)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"].startswith("attachment")
    assert "张三" in response.content.decode("utf-8-sig")


def test_export_customers_view_forbidden_without_bit(client: Any, viewer: User) -> None:
    client.force_login(viewer)
    assert client.get(LIST_EXPORT_URL).status_code == 403


def test_export_customers_view_anonymous_redirects(client: Any) -> None:
    response = client.get(LIST_EXPORT_URL)
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_export_customers_view_respects_filters(
    client: Any, exporter: User, customer_a: Customer, customer_b: Customer
) -> None:
    client.force_login(exporter)
    response = client.get(LIST_EXPORT_URL, {"q": "张三"})
    body = response.content.decode("utf-8-sig")
    assert "张三" in body
    assert "李四" not in body


def test_export_customers_view_respects_status_filter(
    client: Any,
    exporter: User,
    customer_a: Customer,
    customer_b: Customer,
    status_potential: CustomerStatus,
) -> None:
    client.force_login(exporter)
    response = client.get(LIST_EXPORT_URL, {"status": str(status_potential.pk)})
    body = response.content.decode("utf-8-sig")
    assert "张三" in body
    assert "李四" not in body


def test_export_profile_view_ok(client: Any, exporter: User, customer_a: Customer) -> None:
    client.force_login(exporter)
    response = client.get(f"/export/customers/{customer_a.pk}/profile/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "filename*=UTF-8''" in response["Content-Disposition"]
    assert "张三" in response.content.decode("utf-8-sig")


def test_export_timeline_view_ok(client: Any, exporter: User, customer_a: Customer) -> None:
    WorkEvent.objects.create(
        title="回访",
        customer=customer_a,
        occurred_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
    )
    client.force_login(exporter)
    response = client.get(f"/export/customers/{customer_a.pk}/timeline/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "filename*=UTF-8''" in response["Content-Disposition"]
    assert "回访" in response.content.decode("utf-8-sig")


def test_export_archive_view_zip(client: Any, exporter: User, customer_a: Customer) -> None:
    client.force_login(exporter)
    response = client.get(f"/export/customers/{customer_a.pk}/archive/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert "filename*=UTF-8''" in response["Content-Disposition"]
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    assert "张三/00_客户档案.csv" in zf.namelist()


def test_export_detail_views_forbidden_without_bit(
    client: Any, viewer: User, customer_a: Customer
) -> None:
    client.force_login(viewer)
    assert client.get(f"/export/customers/{customer_a.pk}/profile/").status_code == 403
    assert client.get(f"/export/customers/{customer_a.pk}/timeline/").status_code == 403
    assert client.get(f"/export/customers/{customer_a.pk}/archive/").status_code == 403


def test_export_detail_views_404_for_unknown_customer(client: Any, exporter: User) -> None:
    client.force_login(exporter)
    unknown = uuid.uuid4()
    assert client.get(f"/export/customers/{unknown}/profile/").status_code == 404
    assert client.get(f"/export/customers/{unknown}/archive/").status_code == 404
