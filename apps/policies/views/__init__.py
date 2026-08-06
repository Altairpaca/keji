"""policies 视图包（T7.2 CRUD + T7.4 保单文件）。

- ``policies.py``：保单 CRUD 与状态流转（规格 §11）
- ``documents.py``：保单关联文件（T7.4，待补）
"""

from apps.policies.views.policies import (
    policy_change_status,
    policy_create,
    policy_delete,
    policy_detail,
    policy_edit,
    policy_list,
    policy_restore,
)

__all__ = [
    "policy_change_status",
    "policy_create",
    "policy_delete",
    "policy_detail",
    "policy_edit",
    "policy_list",
    "policy_restore",
]
