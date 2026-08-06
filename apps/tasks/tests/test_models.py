"""tasks 模型测试（RED 先行，规格 §13 / REQ-TASK-001）。

覆盖：默认 status/task_type、__str__、is_overdue 边界（今天截止 false、
昨天截止 true、done 后 false）。
"""

from collections.abc import Callable
from datetime import date, timedelta

import pytest

from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

MakeTask = Callable[..., Task]


@pytest.fixture
def make_task(db: None) -> MakeTask:
    """按需构造任务（直接 models 级创建，不经服务层）。"""

    def _make(**kwargs: object) -> Task:
        defaults: dict[str, object] = {
            "title": "回访客户",
            "task_type": "followup",
            "due_date": date.today(),
        }
        defaults.update(kwargs)
        task = Task(**defaults)
        task.save()
        return task

    return _make


def test_default_status_is_open(make_task: MakeTask) -> None:
    task = make_task()
    assert task.status == "open"


def test_default_task_type_is_followup(make_task: MakeTask) -> None:
    task = make_task()
    assert task.task_type == "followup"


def test_str_returns_title(make_task: MakeTask) -> None:
    task = make_task(title="整理保单资料")
    assert str(task) == "整理保单资料"


def test_is_overdue_false_when_due_today(make_task: MakeTask) -> None:
    task = make_task(due_date=date.today())
    assert task.is_overdue is False


def test_is_overdue_true_when_due_yesterday(make_task: MakeTask) -> None:
    task = make_task(due_date=date.today() - timedelta(days=1))
    assert task.is_overdue is True


def test_is_overdue_false_when_done_after_due(make_task: MakeTask) -> None:
    task = make_task(due_date=date.today() - timedelta(days=1), status="done")
    assert task.is_overdue is False


def test_is_overdue_false_when_cancelled_after_due(make_task: MakeTask) -> None:
    task = make_task(due_date=date.today() - timedelta(days=1), status="cancelled")
    assert task.is_overdue is False
