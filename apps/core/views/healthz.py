"""健康检查端点（规格 §23 生产部署，供编排探活）。

返回 200 JSON，不做数据库访问、无需鉴权；数据库就绪性由
web 容器 entrypoint 的 migrate 阶段保证（migrate 失败则容器退出）。
"""

from django.http import HttpRequest, JsonResponse


def healthz(request: HttpRequest) -> JsonResponse:
    """编排健康检查：始终返回 200 {"status": "ok"}。"""
    return JsonResponse({"status": "ok"})
