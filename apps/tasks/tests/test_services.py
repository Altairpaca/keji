"""tasks 服务层测试（RED 先行，规格 §13 / §14）。

覆盖：create_task（默认值、title 空校验、customer 可空）、update_task（部分更新、
status=done 自动补 completed_at、status=cancelled 自动补 cancelled_at、未知字段拒绝）、
complete_task / cancel_task / soft_delete_task / restore_task、
set_quick_followup（建任务 + 更新客户 next_followup_date、非法 days、失败回滚）、
overdue_tasks（排除 done/cancelled、user 过滤）、tasks_due_between。
"""

from collections.abc import Callable
from datetime import date, timedelta

import pytest

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.tasks.models import Task
from apps.tasks.services import (
    cancel_task,
    complete_task,
    create_task,
    overdue_tasks,
    restore_task,
    set_quick_followup,
    soft_delete_task,
    tasks_due_between,
    update_task,
)

pytestmark = pytest.mark.django_db

MakeCustomer = Callable[..., Customer]


@pytest.fixture
def user(db: None) -> User:
    u = User(username="agent", password="pw")
    u.set_password("pw")
    u.save()
    return u


@pytest.fixture
def make_customer(db: None) -> MakeCustomer:
    """按需创建客户（独立临时 owner，避免跨测试耦合）。"""

    def _make(name: str = "林小明") -> Customer:
        owner = User(username=f"own-{date.today().isoformat()}-{name}")
        owner.save()
        return create_customer(name=name, owner=owner, created_by=owner, age_note="约35岁")

    return _make


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


def test_create_task_defaults(user: User) -> None:
    task = create_task(title="整理保单", due_date=date.today(), created_by=user)

    assert task.title == "整理保单"
    assert task.task_type == "followup"
    assert task.priority == "中"
    assert task.status == "open"
    assert task.customer is None
    assert task.created_by == user


def test_create_task_with_customer(user: User, make_customer: MakeCustomer) -> None:
    customer = make_customer()
    task = create_task(
        title="送资料",
        task_type="deliver_materials",
        customer=customer,
        due_date=date.today(),
        created_by=user,
    )

    assert task.customer == customer
    assert task.task_type == "deliver_materials"


def test_create_task_blank_title_raises_value_error(user: User) -> None:
    with pytest.raises(ValueError):
        create_task(title="   ", due_date=date.today(), created_by=user)


def test_create_task_accepts_null_created_by() -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=None)
    assert task.created_by is None


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------


def test_update_task_partial_update(user: User) -> None:
    task = create_task(title="旧标题", due_date=date.today(), created_by=user)

    updated = update_task(task, title="新标题")

    assert updated.title == "新标题"
    assert updated.status == "open"
    assert updated.completed_at is None


def test_update_task_done_sets_completed_at(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)

    update_task(task, status="done")

    assert task.status == "done"
    assert task.completed_at is not None


def test_update_task_cancelled_sets_cancelled_at(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)

    update_task(task, status="cancelled")

    assert task.status == "cancelled"
    assert task.cancelled_at is not None


def test_update_task_unknown_field_raises_value_error(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)

    with pytest.raises(ValueError):
        update_task(task, nonexistent_field="x")


# ---------------------------------------------------------------------------
# complete / cancel / soft delete / restore
# ---------------------------------------------------------------------------


def test_complete_task(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)

    complete_task(task)

    assert task.status == "done"
    assert task.completed_at is not None


def test_cancel_task(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)

    cancel_task(task)

    assert task.status == "cancelled"
    assert task.cancelled_at is not None


def test_soft_delete_task_hides_from_default_manager(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)

    soft_delete_task(task)

    assert task.is_deleted is True
    assert not Task.objects.filter(pk=task.pk).exists()
    assert Task.all_objects.filter(pk=task.pk).exists()


def test_restore_task(user: User) -> None:
    task = create_task(title="回访", due_date=date.today(), created_by=user)
    soft_delete_task(task)

    restore_task(task)

    assert task.is_deleted is False
    assert Task.objects.filter(pk=task.pk).exists()


# ---------------------------------------------------------------------------
# set_quick_followup
# ---------------------------------------------------------------------------


def test_set_quick_followup_creates_task_and_updates_customer(
    user: User, make_customer: MakeCustomer
) -> None:
    customer = make_customer("张美玲")

    task = set_quick_followup(customer=customer, days=7, assignee=user, created_by=user)

    assert task.task_type == "followup"
    assert task.title == "张美玲 客户回访"
    assert task.customer == customer
    assert task.due_date == date.today() + timedelta(days=7)
    customer.refresh_from_db()
    assert customer.next_followup_date == task.due_date


def test_set_quick_followup_invalid_days_raises(user: User, make_customer: MakeCustomer) -> None:
    customer = make_customer()

    with pytest.raises(ValueError):
        set_quick_followup(customer=customer, days=3, created_by=user)


def test_set_quick_followup_rolls_back_on_failure(
    user: User, make_customer: MakeCustomer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """事务内任一失败即整体回滚：任务不残留、next_followup_date 不更新。"""
    customer = make_customer()

    def _boom(self: object, *args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(Customer, "save", _boom)

    with pytest.raises(RuntimeError):
        set_quick_followup(customer=customer, days=15, assignee=user, created_by=user)

    assert not Task.objects.filter(customer=customer).exists()
    customer.refresh_from_db()
    assert customer.next_followup_date is None


# ---------------------------------------------------------------------------
# overdue_tasks / tasks_due_between
# ---------------------------------------------------------------------------


def test_overdue_tasks_excludes_done_and_cancelled(user: User) -> None:
    overdue = create_task(
        title="逾期未办", due_date=date.today() - timedelta(days=2), created_by=user
    )
    done_task = create_task(
        title="逾期已办", due_date=date.today() - timedelta(days=2), created_by=user
    )
    complete_task(done_task)
    cancelled_task = create_task(
        title="逾期已取消", due_date=date.today() - timedelta(days=2), created_by=user
    )
    cancel_task(cancelled_task)
    future = create_task(
        title="未来任务", due_date=date.today() + timedelta(days=2), created_by=user
    )

    result = overdue_tasks()

    ids = {t.pk for t in result}
    assert overdue.pk in ids
    assert done_task.pk not in ids
    assert cancelled_task.pk not in ids
    assert future.pk not in ids


def test_overdue_tasks_filters_by_user(user: User) -> None:
    mine = create_task(title="我的逾期", due_date=date.today() - timedelta(days=1), created_by=user)
    other = User(username="other", password="pw")
    other.set_password("pw")
    other.save()
    not_mine = create_task(
        title="别人的逾期", due_date=date.today() - timedelta(days=1), created_by=other
    )

    result = overdue_tasks(user=user)

    ids = {t.pk for t in result}
    assert mine.pk in ids
    assert not_mine.pk not in ids


def test_overdue_tasks_matches_assignee(user: User) -> None:
    assigned = create_task(
        title="指派给我", due_date=date.today() - timedelta(days=1), assignee=user, created_by=user
    )
    result = overdue_tasks(user=user)
    assert assigned.pk in {t.pk for t in result}


def test_tasks_due_between(user: User) -> None:
    start = date.today()
    end = start + timedelta(days=7)
    inside = create_task(title="区间内", due_date=start + timedelta(days=3), created_by=user)
    before = create_task(title="区间前", due_date=start - timedelta(days=1), created_by=user)
    after = create_task(title="区间后", due_date=end + timedelta(days=1), created_by=user)
    done_task = create_task(
        title="区间内已完成", due_date=start + timedelta(days=4), created_by=user
    )
    complete_task(done_task)

    result = tasks_due_between(start, end)

    ids = {t.pk for t in result}
    assert inside.pk in ids
    assert before.pk not in ids
    assert after.pk not in ids
    assert done_task.pk not in ids
