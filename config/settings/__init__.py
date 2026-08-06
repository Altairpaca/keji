"""settings 包。

默认暴露开发配置（config.settings == config.settings.dev）。
生产部署请显式指定 DJANGO_SETTINGS_MODULE=config.settings.prod。
"""

from .dev import *  # noqa: F403
