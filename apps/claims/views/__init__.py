"""claims 视图包（T8.2 / T8.3，规格 §12）。

- ``views.claims``：案件 CRUD、状态流转、模板实例化（T8.2）；
- ``views.materials``：材料添加 / 状态流转 / 删除（T8.2）；
- ``views.export``：资料 ZIP 导出（T8.3 并行）。

对外保持 ``apps.claims.views`` 命名空间兼容（urls.py 以 ``views.claim_list`` 引用）。
"""

from apps.claims.views.claims import (
    claim_change_status,
    claim_create,
    claim_delete,
    claim_detail,
    claim_edit,
    claim_instantiate_template,
    claim_list,
    claim_restore,
)
from apps.claims.views.export import claim_export_zip
from apps.claims.views.materials import (
    material_add,
    material_change_status,
    material_delete,
)

__all__ = [
    "claim_change_status",
    "claim_create",
    "claim_delete",
    "claim_detail",
    "claim_edit",
    "claim_export_zip",
    "claim_instantiate_template",
    "claim_list",
    "claim_restore",
    "material_add",
    "material_change_status",
    "material_delete",
]
