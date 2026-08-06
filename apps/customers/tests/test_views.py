"""T4.2 customers 视图测试（RED 先行，规格 §6 / §19）。

覆盖：
- 列表：匿名 302、无权限 403、有权限 200、按状态 / 标签 / q 筛选、分页（>20 第 2 页）、
  分页保留筛选 query、空状态渲染
- 详情：不存在 / 已软删 404、关键字段渲染、占位区块、权限 403
- 创建：匿名 302、无管理权限 403、合法 POST（owner/created_by=当前用户、默认状态）、
  name 空 / birth-age 皆空 / 手机号非法 → 400 带错误、无权限 403
- 编辑：无管理权限 403、改字段生效、改 next_followup_date 生效
- 删除 / 恢复：权限 403、软删后列表消失 / all_objects 保留 / 详情 404、恢复后重新可见
- 手机端冒烟：列表含卡片标记、详情含底部导航标记
"""

import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.activities.models import WorkEvent
from apps.claims.models import ClaimCase
from apps.customers.models import Customer, CustomerStatus, Tag
from apps.customers.services import assign_tags, create_customer, soft_delete_customer
from apps.policies.models import Policy
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

LIST_URL = "/customers/"
CREATE_URL = "/customers/create/"

MakeCustomer = Callable[..., Customer]


@pytest.fixture
def viewer(db: None) -> User:
    """仅拥有查看权限的用户。"""
    user = User(username="viewer", can_view_customers=True)
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def manager(db: None) -> User:
    """拥有查看 / 管理 / 删除权限的用户。"""
    user = User(
        username="manager",
        can_view_customers=True,
        can_manage_customers=True,
        can_delete_customers=True,
    )
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def plain(db: None) -> User:
    """无任何权限位的普通用户。"""
    user = User(username="plain")
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def make_customer(db: None) -> MakeCustomer:
    """按需创建客户（owner/created_by 缺省为独立的临时用户）。"""

    def _make(name: str, *, owner: User | None = None, **kwargs: object) -> Customer:
        if owner is None:
            owner = User.objects.create(username=f"owner-{uuid.uuid4().hex[:6]}")
        return create_customer(
            name=name, owner=owner, created_by=owner, age_note="约30岁", **kwargs
        )

    return _make


def _valid_post_data() -> dict[str, str]:
    """创建 / 编辑表单的合法 POST 数据。"""
    return {
        "name": "林小明",
        "gender": "男",
        "birth_date": "",
        "age_note": "约35岁",
        "phone": "13800138000",
        "wechat_nickname": "xiaoming",
        "region": "台北市",
        "occupation": "工程师",
        "marital_family_note": "已婚，育有一子",
        "source": "朋友介绍",
        "previous_agent": "王姐",
        "first_contact_date": "2026-01-01",
        "last_contact_date": "2026-07-01",
        "next_followup_date": "2026-08-01",
        "status": "",
        "priority": "高",
        "communication_preference": "微信",
        "notes": "偏好晚间联系",
    }


def _body(response: Any) -> str:
    """响应内容转字符串，便于子串断言。"""
    return str(response.content.decode())


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------


def test_list_anonymous_redirects_to_login(client: Any) -> None:
    response = client.get(LIST_URL)

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_list_plain_user_forbidden(client: Any, plain: User) -> None:
    client.force_login(plain)

    response = client.get(LIST_URL)

    assert response.status_code == 403


def test_list_viewer_with_permission_ok(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    make_customer("林小明")
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "林小明" in _body(response)


def test_list_filters_by_status(client: Any, viewer: User, make_customer: MakeCustomer) -> None:
    waiting = CustomerStatus.objects.get(name="待首次联系")
    met = CustomerStatus.objects.get(name="已见面")
    make_customer("甲客户", status=waiting)
    make_customer("乙客户", status=met)
    client.force_login(viewer)

    response = client.get(LIST_URL, {"status": str(met.pk)})

    assert response.status_code == 200
    assert "乙客户" in _body(response)
    assert "甲客户" not in _body(response)


def test_list_filters_by_tag(client: Any, viewer: User, make_customer: MakeCustomer) -> None:
    tagged = make_customer("甲客户")
    make_customer("乙客户")
    tag = Tag.objects.create(name="vip")
    assign_tags(tagged, ["vip"])
    client.force_login(viewer)

    response = client.get(LIST_URL, {"tag": str(tag.pk)})

    assert response.status_code == 200
    assert "甲客户" in _body(response)
    assert "乙客户" not in _body(response)


def test_list_filters_by_q_name_phone_wechat(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    make_customer("甲客户", phone="13800138000", wechat_nickname="nick-a")
    make_customer("乙客户", phone="13900139000")
    client.force_login(viewer)

    by_name = client.get(LIST_URL, {"q": "甲客户"})
    assert "甲客户" in _body(by_name)
    assert "乙客户" not in _body(by_name)

    by_phone = client.get(LIST_URL, {"q": "13900139000"})
    assert "乙客户" in _body(by_phone)
    assert "甲客户" not in _body(by_phone)

    by_wechat = client.get(LIST_URL, {"q": "nick-a"})
    assert "甲客户" in _body(by_wechat)
    assert "乙客户" not in _body(by_wechat)


def test_list_pagination_second_page(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    for index in range(1, 26):
        make_customer(f"cust-{index:02d}")
    client.force_login(viewer)

    page1 = client.get(LIST_URL, {"page": 1})
    assert "cust-01" in _body(page1)
    assert "cust-25" not in _body(page1)

    page2 = client.get(LIST_URL, {"page": 2})
    assert page2.status_code == 200
    assert "cust-25" in _body(page2)
    assert "cust-01" not in _body(page2)


def test_list_pagination_preserves_filter_query(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    for index in range(1, 26):
        make_customer(f"cust-{index:02d}")
    client.force_login(viewer)

    response = client.get(LIST_URL, {"q": "cust", "page": 2})

    assert response.status_code == 200
    assert "&amp;q=cust" in _body(response)


def test_list_empty_state_rendered(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "还没有客户" in _body(response)


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------


def test_detail_unknown_customer_404(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(f"/customers/{uuid.uuid4()}/")

    assert response.status_code == 404


def test_detail_soft_deleted_customer_404(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    soft_delete_customer(customer)
    client.force_login(viewer)

    response = client.get(f"/customers/{customer.pk}/")

    assert response.status_code == 404


def test_detail_plain_user_forbidden(client: Any, plain: User, make_customer: MakeCustomer) -> None:
    customer = make_customer("林小明")
    client.force_login(plain)

    response = client.get(f"/customers/{customer.pk}/")

    assert response.status_code == 403


def test_detail_renders_key_fields(client: Any, viewer: User, make_customer: MakeCustomer) -> None:
    servicing = CustomerStatus.objects.get(name="保单服务中")
    customer = make_customer(
        "林小明",
        gender="男",
        birth_date=date(1990, 1, 1),
        phone="13800138000",
        wechat_nickname="xiaoming",
        region="台北市",
        occupation="工程师",
        marital_family_note="已婚，育有一子",
        source="朋友介绍",
        previous_agent="王姐",
        first_contact_date=date(2026, 1, 1),
        last_contact_date=date(2026, 7, 1),
        next_followup_date=date(2026, 8, 1),
        status=servicing,
        priority="高",
        communication_preference="微信",
        notes="偏好晚间联系",
    )
    client.force_login(viewer)

    response = client.get(f"/customers/{customer.pk}/")

    assert response.status_code == 200
    body = _body(response)
    for fragment in (
        "林小明",
        "13800138000",
        "xiaoming",
        "保单服务中",
        "工程师",
        "台北市",
        "2026-08-01",
        "偏好晚间联系",
    ):
        assert fragment in body


def test_detail_contains_placeholder_blocks(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    client.force_login(viewer)

    response = client.get(f"/customers/{customer.pk}/")

    assert response.status_code == 200
    assert "将在后续版本显示" in _body(response)


def test_detail_mobile_four_blocks(client: Any, manager: User, make_customer: MakeCustomer) -> None:
    """手机端四区块（规格 §19）：是谁 / 在处理什么 / 上次发生什么 / 下一步做什么。"""
    customer = make_customer("林小明")
    client.force_login(manager)

    body = _body(client.get(f"/customers/{customer.pk}/"))

    for fragment in ("是谁", "在处理什么", "上次发生什么", "下一步做什么"):
        assert fragment in body
    # 编辑 / 删除按钮满足 44px 触控高度
    assert "min-h-[44px]" in body


def test_detail_mobile_empty_fields_collapsed(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    """手机端「是谁」空字段折叠：无值的字段不渲染，仅桌面信息卡保留标签行。"""
    customer = make_customer(
        "林小明",
        phone="",
        wechat_nickname="",
        region="",
        occupation="",
        birth_date=date(1990, 1, 1),
    )
    client.force_login(viewer)

    body = _body(client.get(f"/customers/{customer.pk}/"))

    assert body.count('<dt class="label">手机号</dt>') == 1
    assert body.count('<dt class="label">职业</dt>') == 1
    assert body.count('<dt class="label">地区</dt>') == 1
    assert "暂无跟进安排" in body


def test_detail_mobile_shows_open_work_and_timeline(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    """手机端四区块内容：未完成待办 / 进行中保单 / 理赔中案件 / 最近时间线 / 下次跟进。"""
    customer = make_customer("林小明", phone="13800138000", next_followup_date=date(2026, 8, 1))
    Task.objects.create(customer=customer, title="确认保费缴纳", due_date=date(2026, 7, 20))
    Task.objects.create(
        customer=customer, title="已完成回访", due_date=date(2026, 6, 1), status="done"
    )
    Policy.objects.create(
        insurer="平安人寿",
        name="e生保医疗险",
        policy_no="P-2026-0001",
        policyholder=customer,
        status="active",
    )
    ClaimCase.objects.create(customer=customer, name="门诊理赔", status="reported")
    WorkEvent.objects.create(customer=customer, title="面谈家庭保障方案")
    client.force_login(viewer)

    body = _body(client.get(f"/customers/{customer.pk}/"))

    for fragment in (
        "确认保费缴纳",
        "e生保医疗险",
        "门诊理赔",
        "面谈家庭保障方案",
        "计划跟进日",
        "2026-08-01",
    ):
        assert fragment in body
    # 终态待办不进入「在处理什么」（时间线仍会展示，属正常）
    in_progress_section = body.split("在处理什么", 1)[1].split("上次发生什么", 1)[0]
    assert "已完成回访" not in in_progress_section
    assert "确认保费缴纳" in in_progress_section
    assert "暂无跟进安排" not in body
    # 手机号有值：桌面信息卡 + 手机端「是谁」各渲染 1 处
    assert body.count('<dt class="label">手机号</dt>') == 2


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------


def test_create_anonymous_redirected(client: Any) -> None:
    response = client.get(CREATE_URL)

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_create_viewer_without_manage_forbidden(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(CREATE_URL)

    assert response.status_code == 403


def test_create_get_renders_form(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.get(CREATE_URL)

    assert response.status_code == 200
    assert "创建客户" in _body(response)


def test_create_post_valid_sets_owner_and_default_status(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(CREATE_URL, _valid_post_data())

    assert response.status_code == 302
    customer = Customer.objects.get(name="林小明")
    assert customer.owner == manager
    assert customer.created_by == manager
    assert customer.status is not None
    assert customer.status.name == "待首次联系"
    assert response.url == f"/customers/{customer.pk}/"


def test_create_post_empty_name_returns_400(client: Any, manager: User) -> None:
    client.force_login(manager)
    data = _valid_post_data()
    data["name"] = ""

    response = client.post(CREATE_URL, data)

    assert response.status_code == 400
    assert "客户姓名不能为空" in _body(response)
    assert Customer.objects.count() == 0


def test_create_post_missing_birth_and_age_returns_400(client: Any, manager: User) -> None:
    client.force_login(manager)
    data = _valid_post_data()
    data["birth_date"] = ""
    data["age_note"] = ""

    response = client.post(CREATE_URL, data)

    assert response.status_code == 400
    assert "出生日期与年龄说明至少填写其一" in _body(response)
    assert Customer.objects.count() == 0


def test_create_post_bad_phone_returns_400(client: Any, manager: User) -> None:
    client.force_login(manager)
    data = _valid_post_data()
    data["phone"] = "abc"

    response = client.post(CREATE_URL, data)

    assert response.status_code == 400
    assert "手机号格式不正确" in _body(response)
    assert Customer.objects.count() == 0


def test_create_post_plain_user_forbidden(client: Any, plain: User) -> None:
    client.force_login(plain)

    response = client.post(CREATE_URL, _valid_post_data())

    assert response.status_code == 403
    assert Customer.objects.count() == 0


# ---------------------------------------------------------------------------
# 编辑
# ---------------------------------------------------------------------------


def test_edit_requires_manage_permission(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    client.force_login(viewer)

    response = client.get(f"/customers/{customer.pk}/edit/")

    assert response.status_code == 403


def test_edit_post_updates_fields(client: Any, manager: User, make_customer: MakeCustomer) -> None:
    customer = make_customer("林小明", phone="13800138000")
    client.force_login(manager)
    data = _valid_post_data()
    data["name"] = "林大明"
    data["phone"] = "13900139000"
    data["status"] = str(customer.status_id)

    response = client.post(f"/customers/{customer.pk}/edit/", data)

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.name == "林大明"
    assert customer.phone == "13900139000"


def test_edit_post_updates_next_followup_date(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    client.force_login(manager)
    data = _valid_post_data()
    data["status"] = str(customer.status_id)
    data["next_followup_date"] = "2026-09-01"

    response = client.post(f"/customers/{customer.pk}/edit/", data)

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.next_followup_date == date(2026, 9, 1)


# ---------------------------------------------------------------------------
# 删除 / 恢复
# ---------------------------------------------------------------------------


def test_delete_requires_delete_permission(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    client.force_login(viewer)

    response = client.post(f"/customers/{customer.pk}/delete/")

    assert response.status_code == 403


def test_delete_soft_deletes_customer(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    client.force_login(manager)

    response = client.post(f"/customers/{customer.pk}/delete/")

    assert response.status_code == 302
    assert response.url == LIST_URL
    deleted = Customer.all_objects.get(pk=customer.pk)
    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None
    assert Customer.objects.filter(pk=customer.pk).count() == 0
    assert 'data-testid="customer-card"' not in _body(client.get(LIST_URL))
    assert client.get(f"/customers/{customer.pk}/").status_code == 404


def test_restore_requires_delete_permission(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    soft_delete_customer(customer)
    client.force_login(viewer)

    response = client.post(f"/customers/{customer.pk}/restore/")

    assert response.status_code == 403


def test_restore_makes_customer_visible_again(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    soft_delete_customer(customer)
    client.force_login(manager)

    response = client.post(f"/customers/{customer.pk}/restore/")

    assert response.status_code == 302
    assert response.url == f"/customers/{customer.pk}/"
    restored = Customer.objects.get(pk=customer.pk)
    assert restored.is_deleted is False
    assert restored.deleted_at is None
    assert "林小明" in _body(client.get(LIST_URL))


def test_restore_unknown_customer_404(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(f"/customers/{uuid.uuid4()}/restore/")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 手机端冒烟
# ---------------------------------------------------------------------------


def test_list_contains_customer_card_markup(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    make_customer("林小明")
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert 'data-testid="customer-card"' in _body(response)


def test_detail_contains_mobile_bottom_nav(
    client: Any, viewer: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("林小明")
    client.force_login(viewer)

    response = client.get(f"/customers/{customer.pk}/")

    assert response.status_code == 200
    assert 'aria-label="主导航"' in _body(response)
