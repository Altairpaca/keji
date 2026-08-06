"""activities 服务包。"""

from apps.activities.services.activities import (
    create_communication,
    create_work_event,
    restore_communication,
    restore_work_event,
    soft_delete_communication,
    soft_delete_work_event,
    update_communication,
    update_work_event,
)

__all__ = [
    "create_communication",
    "create_work_event",
    "restore_communication",
    "restore_work_event",
    "soft_delete_communication",
    "soft_delete_work_event",
    "update_communication",
    "update_work_event",
]
