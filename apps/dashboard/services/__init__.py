"""dashboard 服务层包。"""

from apps.dashboard.services.queue import build_stats, build_work_queue

__all__ = [
    "build_stats",
    "build_work_queue",
]
