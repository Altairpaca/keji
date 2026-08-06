"""dev settings — 本地开发。

继承 base 的全部配置；base 中 DEBUG 已默认 True，这里不重复设置。
调试工具（如 django-debug-toolbar）待后续里程碑按需加入。
"""

from .base import *  # noqa: F403
