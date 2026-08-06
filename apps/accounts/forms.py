"""accounts 表单：密码修改 + 用户管理。

权限位复选框由 ``User.PERMISSION_BITS`` 遍历生成（不手写 11 行模板）。
密码强度沿用 Django 默认 validators，不引入额外依赖。
"""

from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import User


class KejiPasswordChangeForm(PasswordChangeForm):
    """密码修改表单：中文标签 + 输入框样式，校验逻辑沿用 Django 默认。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        labels = {
            "old_password": "旧密码",
            "new_password1": "新密码",
            "new_password2": "确认新密码",
        }
        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            field.widget.attrs["class"] = "input"


class UserAdminForm(forms.ModelForm):
    """用户管理表单：账号字段 + is_superuser/is_active + 11 个权限位复选框。

    ``core_field_names`` 供模板区分「账号信息」与「权限位」两个区块；
    ``password`` 仅创建表单存在，留空则生成随机初始密码。
    """

    password = forms.CharField(
        label="初始密码",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
        help_text="留空则自动生成随机密码（仅创建时显示一次）",
    )

    core_field_names = ("username", "email", "is_superuser", "is_active", "password")

    class Meta:
        model = User
        fields = ["username", "email", "is_superuser", "is_active", *User.PERMISSION_BITS]
        widgets = {
            "username": forms.TextInput(attrs={"class": "input", "autocomplete": "username"}),
            "email": forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        labels = {
            "username": "账号",
            "email": "邮箱",
            "is_superuser": "设为管理员",
            "is_active": "启用账号",
        }
        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            if field.widget.input_type != "checkbox":
                field.widget.attrs["class"] = "input"
        self.fields["is_superuser"].help_text = "管理员拥有全部 11 个权限位"
        if not self.instance.pk:
            self.fields["is_active"].initial = True

    def clean_password(self) -> str:
        password = self.cleaned_data.get("password") or ""
        if password:
            validate_password(password, self.instance)
        return password


class UserCreateForm(UserAdminForm):
    """创建用户：可填初始密码，留空由视图生成随机密码。"""


class UserEditForm(UserAdminForm):
    """编辑用户：不含密码字段，角色 / 状态 / 权限位即时生效。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields.pop("password")
