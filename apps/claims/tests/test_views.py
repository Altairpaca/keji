"""T8.2 claims 视图测试（RED 先行，规格 §12）。

覆盖：
- 列表：匿名 302、无权限 403、有权限 200、按 status / claim_type / q 筛选、
  分页（>20 第 2 页）、缺料数显示、空状态
- 详情：不存在 / 已软删 404、无权限 403、全字段渲染、材料清单、状态流转表单
  （仅列合法目标）、缺料提示
- 创建：匿名 302、无管理权限 403、GET 渲染表单、合法 POST（owner=当前用户、
  跳详情）、缺必填 → 400
- 编辑：无管理权限 403、改字段生效
- 状态流转：无管理权限 403、合法 POST 状态生效 / 非法 → 400 且状态不变
- 材料：添加、重复添加 → 400、状态流转（checked 写 checked_by/checked_at）、
  非法流转 → 400、删除（软删）
- 模板实例化：生成 N 份材料 + 消息、幂等（重复点击不重复建）
- 权限矩阵：匿名 302 / 无位 403 / 有位 200
"""

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.claims.models import ClaimCase
from apps.claims.services import (
    create_claim,
    create_material,
    soft_delete_claim,
)
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.policies.models import Policy
from apps.policies.services import create_policy

pytestmark = pytest.mark.django_db

LIST_URL = "/claims/"
CREATE_URL = "/claims/create/"

MakeCustomer = Callable[..., Customer]
MakePolicy = Callable[..., Policy]
MakeClaim = Callable[..., ClaimCase]


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


@pytest.fixture
def make_policy(db: None, make_customer: MakeCustomer) -> MakePolicy:
    """按需创建保单（owner 缺省为客户 owner，同保险代理人）。"""

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


@pytest.fixture
def make_claim(db: None, make_customer: MakeCustomer) -> MakeClaim:
    """按需创建理赔案件（owner 缺省为独立临时用户）。"""

    def _make(
        name: str,
        *,
        owner: User | None = None,
        customer: Customer | None = None,
        policy: Policy | None = None,
        claim_type: str = "other",
        incident_date: date | None = None,
        report_date: date | None = None,
        description: str = "",
        status: str | None = None,
        estimated_amount: Decimal | None = None,
        actual_paid_amount: Decimal | None = None,
    ) -> ClaimCase:
        if owner is None:
            owner = User.objects.create(username=f"owner-{uuid.uuid4().hex[:6]}")
        if customer is None:
            customer = create_customer(
                name=f"客户-{uuid.uuid4().hex[:4]}",
                owner=owner,
                created_by=owner,
                age_note="约30岁",
            )
        claim = create_claim(
            name=name,
            customer=customer,
            owner=owner,
            policy=policy,
            claim_type=claim_type,
            incident_date=incident_date,
            report_date=report_date,
            description=description,
        )
        extras: dict[str, object] = {}
        if status is not None:
            extras["status"] = status
        if estimated_amount is not None:
            extras["estimated_amount"] = estimated_amount
        if actual_paid_amount is not None:
            extras["actual_paid_amount"] = actual_paid_amount
        if extras:
            for field, value in extras.items():
                setattr(claim, field, value)
            claim.save()
        return claim

    return _make


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


def test_list_viewer_with_permission_ok(client: Any, viewer: User, make_claim: MakeClaim) -> None:
    make_claim("门诊报销案")
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "门诊报销案" in _body(response)


def test_list_filters_by_status(client: Any, viewer: User, make_claim: MakeClaim) -> None:
    make_claim("甲案", status="submitted")
    make_claim("乙案", status="reported")
    client.force_login(viewer)

    response = client.get(LIST_URL, {"status": "reported"})

    assert response.status_code == 200
    assert "乙案" in _body(response)
    assert "甲案" not in _body(response)


def test_list_filters_by_claim_type(client: Any, viewer: User, make_claim: MakeClaim) -> None:
    make_claim("医疗案", claim_type="medical")
    make_claim("意外案", claim_type="accident")
    client.force_login(viewer)

    response = client.get(LIST_URL, {"claim_type": "accident"})

    assert response.status_code == 200
    assert "意外案" in _body(response)
    assert "医疗案" not in _body(response)


def test_list_filters_by_q_name_and_description(
    client: Any, viewer: User, make_claim: MakeClaim
) -> None:
    make_claim("门诊报销案", description="腿部骨折住院")
    make_claim("重疾确诊案", description="恶性肿瘤确诊")
    client.force_login(viewer)

    by_name = client.get(LIST_URL, {"q": "门诊"})
    assert "门诊报销案" in _body(by_name)
    assert "重疾确诊案" not in _body(by_name)

    by_desc = client.get(LIST_URL, {"q": "肿瘤"})
    assert "重疾确诊案" in _body(by_desc)
    assert "门诊报销案" not in _body(by_desc)


def test_list_shows_missing_materials_count(
    client: Any, viewer: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("缺料案")
    create_material(claim=claim, name="身份证件")
    create_material(claim=claim, name="医疗发票")
    checked = create_material(claim=claim, name="已核对项")
    checked.status = "checked"
    checked.save()
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    # 缺料队列：not_submitted + needs_supplement → 2
    assert "缺料" in _body(response)
    assert "2" in _body(response)


def test_list_pagination_second_page(client: Any, viewer: User, make_claim: MakeClaim) -> None:
    for index in range(1, 26):
        make_claim(f"案件-{index:02d}")
    client.force_login(viewer)

    # 列表按创建时间倒序：第 1 页最新 20 条，第 2 页最早 5 条
    page1 = client.get(LIST_URL, {"page": 1})
    assert "案件-25" in _body(page1)
    assert "案件-01" not in _body(page1)

    page2 = client.get(LIST_URL, {"page": 2})
    assert page2.status_code == 200
    assert "案件-01" in _body(page2)
    assert "案件-25" not in _body(page2)


def test_list_empty_state_rendered(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "还没有理赔案件" in _body(response)


def test_list_renders_amount_with_floatformat(
    client: Any, viewer: User, make_claim: MakeClaim
) -> None:
    make_claim("金额案", estimated_amount=Decimal("8000.00"))
    client.force_login(viewer)

    response = client.get(LIST_URL)

    assert response.status_code == 200
    assert "8000.00" in _body(response)


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------


def test_detail_unknown_claim_404(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(f"/claims/{uuid.uuid4()}/")

    assert response.status_code == 404


def test_detail_soft_deleted_claim_404(client: Any, viewer: User, make_claim: MakeClaim) -> None:
    claim = make_claim("已删案")
    soft_delete_claim(claim)
    client.force_login(viewer)

    response = client.get(f"/claims/{claim.pk}/")

    assert response.status_code == 404


def test_detail_plain_user_forbidden(client: Any, plain: User, make_claim: MakeClaim) -> None:
    claim = make_claim("保密案")
    client.force_login(plain)

    response = client.get(f"/claims/{claim.pk}/")

    assert response.status_code == 403


def test_detail_renders_full_fields(
    client: Any, viewer: User, make_claim: MakeClaim, make_policy: MakePolicy
) -> None:
    policy = make_policy("POL-D-1")
    claim = make_claim(
        "全字段案",
        policy=policy,
        claim_type="medical",
        incident_date=date(2026, 5, 1),
        report_date=date(2026, 5, 3),
        estimated_amount=Decimal("12000.50"),
        actual_paid_amount=Decimal("9000.25"),
        description="腿部骨折住院治疗",
    )
    client.force_login(viewer)

    response = client.get(f"/claims/{claim.pk}/")

    body = _body(response)
    assert response.status_code == 200
    assert "全字段案" in body
    assert "医疗" in body
    assert "客户-" in body
    assert "POL-D-1" in body
    assert "2026-05-01" in body
    assert "2026-05-03" in body
    assert "12000.50" in body
    assert "9000.25" in body
    assert "腿部骨折住院治疗" in body


def test_detail_renders_material_list(client: Any, viewer: User, make_claim: MakeClaim) -> None:
    claim = make_claim("材料案")
    create_material(claim=claim, name="身份证件")
    create_material(claim=claim, name="医疗发票", is_required=False)
    client.force_login(viewer)

    response = client.get(f"/claims/{claim.pk}/")

    body = _body(response)
    assert response.status_code == 200
    assert "材料清单" in body
    assert "身份证件" in body
    assert "医疗发票" in body


def test_detail_status_form_lists_only_legal_targets(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    # consultation → 合法目标：waiting_materials / collecting_materials / reported / closed
    claim = make_claim("流转案", status="consultation")
    client.force_login(manager)

    response = client.get(f"/claims/{claim.pk}/")

    body = _body(response)
    assert response.status_code == 200
    assert "变更状态" in body
    assert "资料收集中" in body
    assert "已报案" in body
    # 不可从 consultation 直达的目标不在下拉中
    assert "已提交" not in body
    assert "理赔通过" not in body


def test_detail_shows_missing_materials_alert(
    client: Any, viewer: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("缺料案")
    create_material(claim=claim, name="身份证件")
    create_material(claim=claim, name="医疗发票")
    client.force_login(viewer)

    response = client.get(f"/claims/{claim.pk}/")

    body = _body(response)
    assert response.status_code == 200
    assert "缺少 2 份材料" in body
    assert "身份证件" in body


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------


def test_create_anonymous_redirects_to_login(client: Any) -> None:
    response = client.get(CREATE_URL)

    assert response.status_code == 302
    assert response.url == settings.LOGIN_URL


def test_create_plain_user_forbidden(client: Any, plain: User) -> None:
    client.force_login(plain)

    response = client.get(CREATE_URL)

    assert response.status_code == 403


def test_create_viewer_cannot_access_form(client: Any, viewer: User) -> None:
    client.force_login(viewer)

    response = client.get(CREATE_URL)

    assert response.status_code == 403


def test_create_get_renders_form(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.get(CREATE_URL)

    assert response.status_code == 200
    assert "新增理赔案件" in _body(response)


def test_create_post_sets_owner_current_user_and_redirects(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("张女士")
    client.force_login(manager)

    response = client.post(
        CREATE_URL,
        {
            "name": "张女士门诊报销",
            "customer": str(customer.pk),
            "claim_type": "medical",
            "incident_date": "2026-05-01",
            "report_date": "2026-05-03",
            "estimated_amount": "8000.00",
            "description": "意外骨折门诊",
        },
    )

    assert response.status_code == 302
    claim = ClaimCase.objects.get(name="张女士门诊报销")
    assert claim.owner == manager
    assert claim.customer == customer
    assert claim.claim_type == "medical"
    assert response.url == f"/claims/{claim.pk}/"


def test_create_post_missing_customer_returns_400(client: Any, manager: User) -> None:
    client.force_login(manager)

    response = client.post(
        CREATE_URL,
        {"name": "无客户案", "claim_type": "medical"},
    )

    assert response.status_code == 400
    assert not ClaimCase.objects.filter(name="无客户案").exists()


# ---------------------------------------------------------------------------
# 编辑
# ---------------------------------------------------------------------------


def test_edit_plain_user_forbidden(client: Any, plain: User, make_claim: MakeClaim) -> None:
    claim = make_claim("编辑案")
    client.force_login(plain)

    response = client.get(f"/claims/{claim.pk}/edit/")

    assert response.status_code == 403


def test_edit_post_updates_fields(client: Any, manager: User, make_claim: MakeClaim) -> None:
    claim = make_claim("编辑前")
    client.force_login(manager)

    response = client.post(
        f"/claims/{claim.pk}/edit/",
        {
            "name": "编辑后",
            "customer": str(claim.customer.pk),
            "claim_type": "accident",
            "incident_date": "2026-06-01",
            "estimated_amount": "15000.00",
            "description": "更新后的描述",
        },
    )

    assert response.status_code == 302
    claim.refresh_from_db()
    assert claim.name == "编辑后"
    assert claim.claim_type == "accident"
    assert claim.incident_date == date(2026, 6, 1)
    assert claim.description == "更新后的描述"


# ---------------------------------------------------------------------------
# 状态流转
# ---------------------------------------------------------------------------


def test_change_status_plain_user_forbidden(
    client: Any, plain: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("流转案")
    client.force_login(plain)

    response = client.post(f"/claims/{claim.pk}/status/", {"new_status": "reported"})

    assert response.status_code == 403


def test_change_status_legal_updates_status(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("流转案", status="consultation")
    client.force_login(manager)

    response = client.post(f"/claims/{claim.pk}/status/", {"new_status": "reported"})

    assert response.status_code == 302
    claim.refresh_from_db()
    assert claim.status == "reported"


def test_change_status_illegal_returns_400_and_keeps_status(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    # consultation 不可直达 approved
    claim = make_claim("非法流转案", status="consultation")
    client.force_login(manager)

    response = client.post(f"/claims/{claim.pk}/status/", {"new_status": "approved"})

    assert response.status_code == 400
    claim.refresh_from_db()
    assert claim.status == "consultation"


# ---------------------------------------------------------------------------
# 材料管理
# ---------------------------------------------------------------------------


def test_material_add_plain_user_forbidden(client: Any, plain: User, make_claim: MakeClaim) -> None:
    claim = make_claim("材料案")
    client.force_login(plain)

    response = client.post(
        f"/claims/{claim.pk}/materials/add/",
        {"name": "身份证件", "is_required": "on"},
    )

    assert response.status_code == 403


def test_material_add_creates_and_redirects(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("材料案")
    client.force_login(manager)

    response = client.post(
        f"/claims/{claim.pk}/materials/add/",
        {"name": "身份证件", "is_required": "on", "note": "客户已提供"},
    )

    assert response.status_code == 302
    material = claim.materials.get(name="身份证件")
    assert material.is_required is True
    assert material.note == "客户已提供"


def test_material_add_duplicate_returns_400(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("材料案")
    create_material(claim=claim, name="身份证件")
    client.force_login(manager)

    response = client.post(
        f"/claims/{claim.pk}/materials/add/",
        {"name": "身份证件"},
    )

    assert response.status_code == 400
    assert claim.materials.filter(name="身份证件").count() == 1


def test_material_change_status_plain_user_forbidden(
    client: Any, plain: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("材料案")
    material = create_material(claim=claim, name="身份证件")
    client.force_login(plain)

    response = client.post(
        f"/claims/{claim.pk}/materials/{material.pk}/status/",
        {"new_status": "submitted"},
    )

    assert response.status_code == 403


def test_material_change_status_submitted_to_pending_review(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("材料案")
    material = create_material(claim=claim, name="身份证件")
    material.status = "submitted"
    material.save()
    client.force_login(manager)

    response = client.post(
        f"/claims/{claim.pk}/materials/{material.pk}/status/",
        {"new_status": "pending_review"},
    )

    assert response.status_code == 302
    material.refresh_from_db()
    assert material.status == "pending_review"


def test_material_change_status_checked_writes_checked_by(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("材料案")
    material = create_material(claim=claim, name="身份证件")
    material.status = "submitted"
    material.save()
    client.force_login(manager)

    # submitted → checked 需经 pending_review（服务层转移图限制）
    client.post(
        f"/claims/{claim.pk}/materials/{material.pk}/status/",
        {"new_status": "pending_review"},
    )
    response = client.post(
        f"/claims/{claim.pk}/materials/{material.pk}/status/",
        {"new_status": "checked"},
    )

    assert response.status_code == 302
    material.refresh_from_db()
    assert material.status == "checked"
    assert material.checked_by == manager
    assert material.checked_at is not None


def test_material_change_status_illegal_returns_400(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    # not_submitted 不可直达 checked
    claim = make_claim("材料案")
    material = create_material(claim=claim, name="身份证件")
    client.force_login(manager)

    response = client.post(
        f"/claims/{claim.pk}/materials/{material.pk}/status/",
        {"new_status": "checked"},
    )

    assert response.status_code == 400
    material.refresh_from_db()
    assert material.status == "not_submitted"


def test_material_delete_soft_deletes(client: Any, manager: User, make_claim: MakeClaim) -> None:
    claim = make_claim("材料案")
    material = create_material(claim=claim, name="身份证件")
    client.force_login(manager)

    response = client.post(f"/claims/{claim.pk}/materials/{material.pk}/delete/")

    assert response.status_code == 302
    material.refresh_from_db()
    assert material.is_deleted is True


# ---------------------------------------------------------------------------
# 模板实例化
# ---------------------------------------------------------------------------


def test_instantiate_template_creates_materials_and_message(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("医疗案", claim_type="medical")
    client.force_login(manager)

    response = client.post(f"/claims/{claim.pk}/instantiate/", follow=True)

    body = _body(response)
    assert response.status_code == 200
    assert "已按模板生成 7 份材料" in body
    assert claim.materials.count() == 7


def test_instantiate_template_is_idempotent(
    client: Any, manager: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("医疗案", claim_type="medical")
    client.force_login(manager)

    client.post(f"/claims/{claim.pk}/instantiate/")
    second = client.post(f"/claims/{claim.pk}/instantiate/", follow=True)

    body = _body(second)
    assert "已按模板生成 0 份材料" in body
    assert claim.materials.count() == 7


def test_instantiate_template_plain_user_forbidden(
    client: Any, plain: User, make_claim: MakeClaim
) -> None:
    claim = make_claim("医疗案", claim_type="medical")
    client.force_login(plain)

    response = client.post(f"/claims/{claim.pk}/instantiate/")

    assert response.status_code == 403
