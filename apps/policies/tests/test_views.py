"""T7.2 policies 视图测试（RED 先行，规格 §4.5 / §11 / REQ-POL-001）。

覆盖：
- 列表：匿名 302、无权限 403、有权限 200、按 status / insurer / q 筛选、
  分页（>20 第 2 页）、空状态、金额 floatformat:2 渲染
- 详情：不存在 / 已软删 404、无权限 403、关键字段渲染、状态历史时间线（倒序）、
  关联客户卡链接客户详情
- 创建：匿名 302、无管理权限 403、GET 渲染表单、合法 POST（owner=当前用户、跳详情）、
  保单号重复 → 表单错误、缺必填 → 400
- 编辑：无管理权限 403、改字段生效
- 状态流转：无管理权限 403、合法 POST（状态变更 + 历史 +1、跳详情）、
  非法目标 → 400 且历史不新增
- 删除 / 恢复：无权限 403、软删后列表消失 / 详情 404、恢复后重新可见
"""

import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.policies.models import Policy, PolicyStatusHistory
from apps.policies.services import change_status, create_policy, soft_delete_policy

pytestmark = pytest.mark.django_db

LIST_URL = "/policies/"
CREATE_URL = "/policies/create/"

MakePolicy = Callable[..., Policy]


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
def make_customer(db: None) -> Callable[..., Customer]:
    """按需创建客户（owner/created_by 缺省为独立的临时用户）。"""

    def _make(name: str, *, owner: User | None = None, **kwargs: object) -> Customer:
        if owner is None:
            owner = User.objects.create(username=f"owner-{uuid.uuid4().hex[:6]}")
        return create_customer(
            name=name, owner=owner, created_by=owner, age_note="约30岁", **kwargs
        )

    return _make


@pytest.fixture
def make_policy(db: None) -> MakePolicy:
    """按需创建保单（owner 缺省为投保客户 owner，同保险代理人）。"""

    def _make(
        policy_no: str,
        *,
        name: str = "金佑人生",
        insurer: str = "平安人寿",
        policyholder: Customer | None = None,
        **kwargs: object,
    ) -> Policy:
        if policyholder is None:
            owner = User.objects.create(username=f"owner-{uuid.uuid4().hex[:6]}")
            policyholder = create_customer(
                name="投保客户", owner=owner, created_by=owner, age_note="约30岁"
            )
        owner = policyholder.owner
        assert owner is not None
        return create_policy(
            insurer=insurer,
            name=name,
            policy_no=policy_no,
            policyholder=policyholder,
            owner=owner,
            **kwargs,
        )

    return _make


def _valid_post_data(customer: Customer) -> dict[str, str]:
    """创建 / 编辑表单的合法 POST 数据。"""
    return {
        "insurer": "平安人寿",
        "name": "金佑人生",
        "policy_no": "POL-VIEW-001",
        "policyholder": str(customer.pk),
        "insured": "",
        "insurance_type": "重疾",
        "main_coverage": "重疾保障",
        "rider_note": "附加医疗",
        "application_date": "2026-01-01",
        "effective_date": "2026-02-01",
        "payment_term": "20年",
        "coverage_term": "终身",
        "payment_frequency": "annual",
        "premium_amount": "8000.00",
        "remark": "客户自购",
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


def test_list_viewer_with_permission_ok(client: Any, viewer: User, make_policy: MakePolicy) -> None:
    make_policy("POL-LIST-001", name="金佑人生")
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "金佑人生" in _body(response)
    assert "POL-LIST-001" in _body(response)


def test_list_filters_by_status(client: Any, viewer: User, make_policy: MakePolicy) -> None:
    make_policy("POL-S1", name="甲保单", status="paying")
    make_policy("POL-S2", name="乙保单", status="lapsed")
    client.force_login(viewer)

    response = client.get(LIST_URL, {"status": "paying"})

    assert response.status_code == 200
    assert "甲保单" in _body(response)
    assert "乙保单" not in _body(response)


def test_list_filters_by_insurer(client: Any, viewer: User, make_policy: MakePolicy) -> None:
    make_policy("POL-I1", name="甲保单", insurer="平安人寿")
    make_policy("POL-I2", name="乙保单", insurer="中国人寿")
    client.force_login(viewer)

    response = client.get(LIST_URL, {"insurer": "中国人寿"})

    assert response.status_code == 200
    assert "乙保单" in _body(response)
    assert "甲保单" not in _body(response)


def test_list_filters_by_q_name_and_policy_no(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    make_policy("POL-Q1", name="金佑人生")
    make_policy("POL-Q2", name="鑫福年年")
    client.force_login(viewer)

    by_name = client.get(LIST_URL, {"q": "鑫福"})
    assert "鑫福年年" in _body(by_name)
    assert "金佑人生" not in _body(by_name)

    by_no = client.get(LIST_URL, {"q": "POL-Q1"})
    assert "金佑人生" in _body(by_no)
    assert "鑫福年年" not in _body(by_no)


def test_list_pagination_second_page(client: Any, viewer: User, make_policy: MakePolicy) -> None:
    for index in range(1, 26):
        make_policy(f"POL-P-{index:02d}", name=f"保单-{index:02d}")
    client.force_login(viewer)

    # 列表按创建时间倒序：第 1 页最新 20 条，第 2 页最早 5 条
    page1 = client.get(LIST_URL, {"page": 1})
    assert "保单-25" in _body(page1)
    assert "保单-01" not in _body(page1)

    page2 = client.get(LIST_URL, {"page": 2})
    assert page2.status_code == 200
    assert "保单-01" in _body(page2)
    assert "保单-25" not in _body(page2)


def test_list_pagination_preserves_filter_query(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    for index in range(1, 26):
        make_policy(f"POL-P-{index:02d}", name=f"保单-{index:02d}")
    client.force_login(viewer)

    response = client.get(LIST_URL, {"q": "保单", "page": 2})

    assert response.status_code == 200
    assert "&amp;q=" in _body(response)


def test_list_empty_state_rendered(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "还没有保单" in _body(response)


def test_list_renders_premium_with_floatformat(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    make_policy("POL-AMT", premium_amount=Decimal("8000.00"))
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "8000.00" in _body(response)


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------


def test_detail_unknown_policy_404(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(f"/policies/{uuid.uuid4()}/")

    assert response.status_code == 404


def test_detail_soft_deleted_policy_404(client: Any, viewer: User, make_policy: MakePolicy) -> None:
    policy = make_policy("POL-SD-D")
    soft_delete_policy(policy)
    client.force_login(viewer)

    response = client.get(f"/policies/{policy.pk}/")

    assert response.status_code == 404


def test_detail_plain_user_forbidden(client: Any, plain: User, make_policy: MakePolicy) -> None:
    policy = make_policy("POL-FORB")
    client.force_login(plain)

    response = client.get(f"/policies/{policy.pk}/")

    assert response.status_code == 403


def test_detail_renders_key_fields(
    client: Any, viewer: User, make_policy: MakePolicy, make_customer: Callable[..., Customer]
) -> None:
    holder = make_customer("林小明")
    policy = make_policy(
        "POL-DET",
        policyholder=holder,
        insured=holder,
        insurance_type="重疾",
        main_coverage="重疾保障",
        effective_date="2026-02-01",
        premium_amount=Decimal("8000.00"),
        remark="客户自购",
    )
    client.force_login(viewer)

    response = client.get(f"/policies/{policy.pk}/")

    assert response.status_code == 200
    body = _body(response)
    for fragment in (
        "金佑人生",
        "平安人寿",
        "POL-DET",
        "林小明",
        "重疾保障",
        "2026-02-01",
        "8000.00",
        "客户自购",
    ):
        assert fragment in body


def test_detail_renders_status_history_timeline_newest_first(
    client: Any, viewer: User, make_policy: MakePolicy, manager: User
) -> None:
    policy = make_policy("POL-HIST")
    change_status(policy=policy, new_status="paying", changed_by=manager, note="开始缴费")
    change_status(policy=policy, new_status="paid_up", changed_by=manager, note="已缴清")
    client.force_login(viewer)

    response = client.get(f"/policies/{policy.pk}/")

    assert response.status_code == 200
    body = _body(response)
    # 时间线含两次历史的状态标签与操作人 / 备注
    assert "缴费中" in body
    assert "已缴清" in body
    assert "开始缴费" in body
    assert manager.username in body
    # 倒序：最新一条的备注在前（用带前缀的备注文本定位，避开顶部状态徽标）
    assert body.index("备注：已缴清") < body.index("备注：开始缴费")


def test_detail_no_history_renders_empty_state(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-NOHIST")
    client.force_login(viewer)

    response = client.get(f"/policies/{policy.pk}/")

    assert response.status_code == 200
    assert "暂无状态变更" in _body(response)


def test_detail_links_associated_customers(
    client: Any, viewer: User, make_policy: MakePolicy, make_customer: Callable[..., Customer]
) -> None:
    holder = make_customer("林小明")
    policy = make_policy("POL-LINK", policyholder=holder)
    client.force_login(viewer)

    response = client.get(f"/policies/{policy.pk}/")

    assert response.status_code == 200
    assert f"/customers/{holder.pk}/" in _body(response)


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
    assert "创建保单" in _body(response)


def test_create_post_valid_sets_owner_and_redirects(
    client: Any, manager: User, make_customer: Callable[..., Customer]
) -> None:
    holder = make_customer("林小明")
    client.force_login(manager)

    response = client.post(CREATE_URL, _valid_post_data(holder))

    assert response.status_code == 302
    policy = Policy.objects.get(policy_no="POL-VIEW-001")
    assert policy.owner == manager
    assert policy.policyholder == holder
    assert policy.status == "active"
    assert response.url == f"/policies/{policy.pk}/"
    assert PolicyStatusHistory.objects.filter(policy=policy).count() == 0


def test_create_post_duplicate_policy_no_returns_form_error(
    client: Any, manager: User, make_customer: Callable[..., Customer], make_policy: MakePolicy
) -> None:
    holder = make_customer("林小明")
    make_policy("POL-VIEW-001")
    client.force_login(manager)

    response = client.post(CREATE_URL, _valid_post_data(holder))

    assert response.status_code == 400
    assert "保单号已存在" in _body(response)
    assert Policy.objects.filter(policy_no="POL-VIEW-001").count() == 1


def test_create_post_missing_required_returns_400(
    client: Any, manager: User, make_customer: Callable[..., Customer]
) -> None:
    holder = make_customer("林小明")
    client.force_login(manager)
    data = _valid_post_data(holder)
    data["insurer"] = ""

    response = client.post(CREATE_URL, data)

    assert response.status_code == 400
    assert Policy.objects.count() == 0


def test_create_post_plain_user_forbidden(
    client: Any, plain: User, make_customer: Callable[..., Customer]
) -> None:
    holder = make_customer("林小明")
    client.force_login(plain)

    response = client.post(CREATE_URL, _valid_post_data(holder))

    assert response.status_code == 403
    assert Policy.objects.count() == 0


# ---------------------------------------------------------------------------
# 编辑
# ---------------------------------------------------------------------------


def test_edit_requires_manage_permission(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-EDIT-FORB")
    client.force_login(viewer)

    response = client.get(f"/policies/{policy.pk}/edit/")

    assert response.status_code == 403


def test_edit_post_updates_fields(
    client: Any, manager: User, make_policy: MakePolicy, make_customer: Callable[..., Customer]
) -> None:
    holder = make_customer("林小明")
    policy = make_policy("POL-EDIT", policyholder=holder)
    client.force_login(manager)
    data = _valid_post_data(holder)
    data["policy_no"] = "POL-EDIT"
    data["name"] = "鑫福年年"
    data["main_coverage"] = "两全保障"

    response = client.post(f"/policies/{policy.pk}/edit/", data)

    assert response.status_code == 302
    policy.refresh_from_db()
    assert policy.name == "鑫福年年"
    assert policy.main_coverage == "两全保障"
    assert policy.policy_no == "POL-EDIT"


# ---------------------------------------------------------------------------
# 状态流转
# ---------------------------------------------------------------------------


def test_change_status_requires_manage_permission(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-ST-FORB")
    client.force_login(viewer)

    response = client.post(f"/policies/{policy.pk}/status/", {"new_status": "paying"})

    assert response.status_code == 403


def test_change_status_legal_transition_updates_and_writes_history(
    client: Any, manager: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-ST-L")
    client.force_login(manager)

    response = client.post(
        f"/policies/{policy.pk}/status/",
        {"new_status": "paying", "note": "开始缴费"},
    )

    assert response.status_code == 302
    assert response.url == f"/policies/{policy.pk}/"
    policy.refresh_from_db()
    assert policy.status == "paying"
    history = list(PolicyStatusHistory.objects.filter(policy=policy))
    assert len(history) == 1
    assert history[0].from_status == "active"
    assert history[0].to_status == "paying"
    assert history[0].changed_by == manager
    assert history[0].note == "开始缴费"


def test_change_status_illegal_transition_returns_400_no_history(
    client: Any, manager: User, make_policy: MakePolicy
) -> None:
    # terminated 是终态：无任何合法迁移目标
    policy = make_policy("POL-ST-I", status="terminated")
    before = PolicyStatusHistory.objects.count()
    client.force_login(manager)

    response = client.post(
        f"/policies/{policy.pk}/status/",
        {"new_status": "active", "note": "非法尝试"},
    )

    assert response.status_code == 400
    assert PolicyStatusHistory.objects.count() == before
    policy.refresh_from_db()
    assert policy.status == "terminated"


# ---------------------------------------------------------------------------
# 删除 / 恢复
# ---------------------------------------------------------------------------


def test_delete_requires_delete_permission(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-DEL-FORB")
    client.force_login(viewer)

    response = client.post(f"/policies/{policy.pk}/delete/")

    assert response.status_code == 403


def test_delete_soft_deletes_policy(client: Any, manager: User, make_policy: MakePolicy) -> None:
    policy = make_policy("POL-DEL")
    client.force_login(manager)

    response = client.post(f"/policies/{policy.pk}/delete/")

    assert response.status_code == 302
    assert response.url == LIST_URL
    deleted = Policy.all_objects.get(pk=policy.pk)
    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None
    assert Policy.objects.filter(pk=policy.pk).count() == 0
    assert 'data-testid="policy-card"' not in _body(client.get(LIST_URL))
    assert client.get(f"/policies/{policy.pk}/").status_code == 404


def test_restore_requires_manage_permission(
    client: Any, viewer: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-RES-FORB")
    soft_delete_policy(policy)
    client.force_login(viewer)

    response = client.post(f"/policies/{policy.pk}/restore/")

    assert response.status_code == 403


def test_restore_makes_policy_visible_again(
    client: Any, manager: User, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-RES")
    soft_delete_policy(policy)
    client.force_login(manager)

    response = client.post(f"/policies/{policy.pk}/restore/")

    assert response.status_code == 302
    assert response.url == f"/policies/{policy.pk}/"
    restored = Policy.objects.get(pk=policy.pk)
    assert restored.is_deleted is False
    assert restored.deleted_at is None
    assert "POL-RES" in _body(client.get(LIST_URL))


def test_restore_unknown_policy_404(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(f"/policies/{uuid.uuid4()}/restore/")

    assert response.status_code == 404
