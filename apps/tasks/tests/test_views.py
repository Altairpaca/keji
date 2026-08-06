"""tasks 视图测试（RED 先行，规格 §13 / §14）。

覆盖：
- 列表：匿名 302、无权限 403、有权限 200、status 筛选（all/open/done/overdue）、
  task_type 筛选、逾期卡片渲染、空状态
- 创建 / 编辑：权限 403、GET 200、POST 创建 / 更新
- 完成 / 取消 / 删除：POST only、权限 403、状态变更生效
- quick_followup：POST 建任务并更新客户下次跟进日期
"""

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

MakeCustomer = Callable[..., Customer]


@pytest.fixture
def viewer(db: None) -> User:
    u = User(username="viewer", can_view_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def manager(db: None) -> User:
    u = User(username="manager", can_view_customers=True, can_manage_customers=True)
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def plain(db: None) -> User:
    u = User(username="plain")
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def make_customer(db: None) -> MakeCustomer:
    """按需创建客户（独立临时 owner，避免跨测试耦合）。"""

    def _make(name: str = "林小明") -> Customer:
        owner = User(username=f"own-{uuid.uuid4().hex[:6]}")
        owner.save()
        return create_customer(name=name, owner=owner, created_by=owner, age_note="约35岁")

    return _make


def _make_task(**kwargs: object) -> Task:
    defaults: dict[str, object] = {"title": "默认待办", "due_date": date.today()}
    defaults.update(kwargs)
    task = Task(**defaults)
    task.save()
    return task


# ---------------------------------------------------------------------------
# task_list
# ---------------------------------------------------------------------------


def test_task_list_anonymous_redirects_to_login(client: Any) -> None:
    resp = client.get("/tasks/")
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


def test_task_list_plain_user_gets_403(client: Any, plain: User) -> None:
    client.force_login(plain)
    resp = client.get("/tasks/")
    assert resp.status_code == 403


def test_task_list_viewer_gets_200(client: Any, viewer: User) -> None:
    client.force_login(viewer)
    resp = client.get("/tasks/")
    assert resp.status_code == 200


def test_task_list_status_done_filter(client: Any, viewer: User) -> None:
    done = _make_task(title="已完成任务", status="done")
    open_task = _make_task(title="未开始任务")
    client.force_login(viewer)

    resp = client.get("/tasks/", {"status": "done"})

    assert resp.status_code == 200
    content = resp.content.decode()
    assert str(done.pk) in content
    assert str(open_task.pk) not in content


def test_task_list_status_open_filter_excludes_done(client: Any, viewer: User) -> None:
    done = _make_task(title="已完成任务", status="done")
    open_task = _make_task(title="未开始任务")
    client.force_login(viewer)

    resp = client.get("/tasks/", {"status": "open"})

    content = resp.content.decode()
    assert str(done.pk) not in content
    assert str(open_task.pk) in content


def test_task_list_status_overdue_shows_only_overdue(client: Any, viewer: User) -> None:
    overdue = _make_task(title="逾期任务", due_date=date.today() - timedelta(days=1))
    future = _make_task(title="未来任务", due_date=date.today() + timedelta(days=1))
    client.force_login(viewer)

    resp = client.get("/tasks/", {"status": "overdue"})

    content = resp.content.decode()
    assert str(overdue.pk) in content
    assert str(future.pk) not in content


def test_task_list_task_type_filter(client: Any, viewer: User) -> None:
    call = _make_task(title="打电话", task_type="call")
    meeting = _make_task(title="约见面", task_type="meeting")
    client.force_login(viewer)

    resp = client.get("/tasks/", {"task_type": "call"})

    content = resp.content.decode()
    assert str(call.pk) in content
    assert str(meeting.pk) not in content


def test_task_list_renders_overdue_red_marker(client: Any, viewer: User) -> None:
    _make_task(title="逾期任务", due_date=date.today() - timedelta(days=1))
    client.force_login(viewer)

    resp = client.get("/tasks/")

    content = resp.content.decode()
    assert "逾期" in content


def test_task_list_empty_state(client: Any, viewer: User) -> None:
    client.force_login(viewer)
    resp = client.get("/tasks/")
    assert "还没有待办" in resp.content.decode()


def test_task_list_preserves_filter_in_pagination_link(client: Any, viewer: User) -> None:
    for i in range(25):
        _make_task(title=f"任务{i}")
    client.force_login(viewer)

    resp = client.get("/tasks/", {"status": "open"})

    content = resp.content.decode()
    assert "?page=2" in content
    assert "status=open" in content


# ---------------------------------------------------------------------------
# task_create / task_edit
# ---------------------------------------------------------------------------


def _valid_form_data(customer: Customer) -> dict[str, str]:
    return {
        "title": "送合同",
        "task_type": "deliver_materials",
        "customer": str(customer.pk),
        "priority": "高",
        "due_date": str(date.today() + timedelta(days=3)),
        "due_time": "10:30",
        "content": "带上身份证复印件",
        "remark": "",
        "assignee": "",
    }


def test_task_create_anonymous_redirects_to_login(client: Any) -> None:
    resp = client.post("/tasks/new/")
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


def test_task_create_plain_user_gets_403(client: Any, plain: User) -> None:
    client.force_login(plain)
    resp = client.post("/tasks/new/")
    assert resp.status_code == 403


def test_task_create_get_renders_form(client: Any, manager: User) -> None:
    client.force_login(manager)
    resp = client.get("/tasks/new/")
    assert resp.status_code == 200
    assert "新建待办" in resp.content.decode()


def test_task_create_post_creates_and_redirects(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer()
    client.force_login(manager)

    resp = client.post("/tasks/new/", _valid_form_data(customer))

    assert resp.status_code == 302
    assert resp["Location"] == reverse("tasks:task_list")
    task = Task.objects.get()
    assert task.title == "送合同"
    assert task.customer == customer
    assert task.priority == "高"
    assert task.created_by == manager


def test_task_create_post_invalid_returns_400(client: Any, manager: User) -> None:
    client.force_login(manager)
    resp = client.post("/tasks/new/", {"title": "", "due_date": ""})
    assert resp.status_code == 400


def test_task_edit_post_updates_and_redirects(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer()
    task = _make_task(title="旧标题", due_date=date.today())
    client.force_login(manager)

    resp = client.post(f"/tasks/{task.pk}/edit/", _valid_form_data(customer))

    assert resp.status_code == 302
    task.refresh_from_db()
    assert task.title == "送合同"
    assert task.customer == customer


def test_task_edit_get_renders_form(client: Any, manager: User) -> None:
    task = _make_task(title="旧标题", due_date=date.today())
    client.force_login(manager)
    resp = client.get(f"/tasks/{task.pk}/edit/")
    assert resp.status_code == 200
    assert "旧标题" in resp.content.decode()


# ---------------------------------------------------------------------------
# task_complete / task_cancel / task_delete
# ---------------------------------------------------------------------------


def test_task_complete_post_marks_done(client: Any, manager: User) -> None:
    task = _make_task(title="待完成")
    client.force_login(manager)

    resp = client.post(f"/tasks/{task.pk}/complete/")

    assert resp.status_code == 302
    task.refresh_from_db()
    assert task.status == "done"
    assert task.completed_at is not None


def test_task_complete_get_not_allowed(client: Any, manager: User) -> None:
    task = _make_task(title="待完成")
    client.force_login(manager)
    resp = client.get(f"/tasks/{task.pk}/complete/")
    assert resp.status_code == 405


def test_task_complete_plain_user_gets_403(client: Any, plain: User) -> None:
    task = _make_task(title="待完成")
    client.force_login(plain)
    resp = client.post(f"/tasks/{task.pk}/complete/")
    assert resp.status_code == 403


def test_task_cancel_post_marks_cancelled(client: Any, manager: User) -> None:
    task = _make_task(title="要取消")
    client.force_login(manager)

    resp = client.post(f"/tasks/{task.pk}/cancel/")

    assert resp.status_code == 302
    task.refresh_from_db()
    assert task.status == "cancelled"
    assert task.cancelled_at is not None


def test_task_delete_post_soft_deletes(client: Any, manager: User) -> None:
    task = _make_task(title="要删除")
    client.force_login(manager)

    resp = client.post(f"/tasks/{task.pk}/delete/")

    assert resp.status_code == 302
    assert not Task.objects.filter(pk=task.pk).exists()
    assert Task.all_objects.filter(pk=task.pk).exists()


# ---------------------------------------------------------------------------
# quick_followup
# ---------------------------------------------------------------------------


def test_quick_followup_creates_task_and_updates_customer(
    client: Any, manager: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("张美玲")
    client.force_login(manager)

    resp = client.post(reverse("tasks:quick_followup"), {"customer": str(customer.pk), "days": "7"})

    assert resp.status_code == 302
    task = Task.objects.get()
    assert task.title == "张美玲 客户回访"
    assert task.due_date == date.today() + timedelta(days=7)
    customer.refresh_from_db()
    assert customer.next_followup_date == task.due_date


def test_quick_followup_anonymous_redirects_to_login(client: Any) -> None:
    resp = client.post(
        reverse("tasks:quick_followup"), {"customer": str(uuid.uuid4()), "days": "7"}
    )
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


def test_quick_followup_plain_user_gets_403(client: Any, plain: User) -> None:
    client.force_login(plain)
    resp = client.post(
        reverse("tasks:quick_followup"), {"customer": str(uuid.uuid4()), "days": "7"}
    )
    assert resp.status_code == 403
