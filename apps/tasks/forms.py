"""tasks 表单：待办创建 / 编辑（规格 §13 / REQ-TASK-001）。

表单负责 HTTP 边界校验；写操作仍全部经 services（create_task / update_task）。
状态字段不在表单内，由完成 / 取消动作驱动（见 views.task_complete / task_cancel）。
"""

from django import forms

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.tasks.models import Task


class TaskForm(forms.ModelForm):
    """待办表单：title/task_type/customer/priority/due_date/due_time/content/remark/assignee。"""

    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(), required=False, label="关联客户", empty_label="无关联客户"
    )
    assignee = forms.ModelChoiceField(
        queryset=User.objects.all().order_by("username"),
        required=False,
        empty_label="未分配",
        label="负责人",
    )

    class Meta:
        model = Task
        fields = [
            "title",
            "task_type",
            "customer",
            "priority",
            "due_date",
            "due_time",
            "content",
            "remark",
            "assignee",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "due_time": forms.TimeInput(attrs={"type": "time"}),
            "content": forms.Textarea(attrs={"rows": 3}),
            "remark": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")
