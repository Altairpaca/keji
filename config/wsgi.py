"""WSGI 配置。生产使用 gunicorn 加载本模块（并显式指定 prod settings）。"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
