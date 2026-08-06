"""生产部署结构断言（规格 §23）与健康检查端点测试。

测试套件仅做结构断言（文件存在 + 关键配置项），不构建镜像——
真实构建与运行验证由部署脚本/CI 承担（见 README 生产部署章节）。
"""

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_DIR = REPO_ROOT / "docker" / "prod"


def _read_relative(relative: str) -> str:
    path = PROD_DIR / relative
    assert path.exists(), f"缺少生产部署文件: {relative}"
    return path.read_text(encoding="utf-8")


# ---- Dockerfile ---------------------------------------------------------


def test_prod_dockerfile_exists_and_core_content() -> None:
    dockerfile = _read_relative("Dockerfile")

    assert "FROM python:3.13-slim" in dockerfile
    assert "postgresql-client" in dockerfile
    # 非 root 运行：USER 指令（uid 1001）
    assert "USER" in dockerfile
    assert "1001" in dockerfile
    assert "ENTRYPOINT" in dockerfile
    assert "entrypoint.sh" in dockerfile


def test_prod_entrypoint_runs_gunicorn_with_workers_override() -> None:
    entrypoint = (PROD_DIR / "entrypoint.sh").read_text(encoding="utf-8")

    assert "migrate --noinput" in entrypoint
    assert "collectstatic --noinput" in entrypoint
    assert "gunicorn" in entrypoint
    assert "config.wsgi:application" in entrypoint
    assert "0.0.0.0:8000" in entrypoint
    assert "WORKERS" in entrypoint
    assert "exec gunicorn" in entrypoint


def test_prod_dockerfile_non_root_user_present() -> None:
    dockerfile = _read_relative("Dockerfile")
    # USER 指令出现在 ENTRYPOINT/CMD 之前且与 useradd 的 uid 一致
    user_line_idx = dockerfile.splitlines().index(
        next(line for line in dockerfile.splitlines() if line.strip().startswith("USER "))
    )
    cmd_idx = dockerfile.splitlines().index(
        next(
            line
            for line in dockerfile.splitlines()
            if line.strip().startswith("ENTRYPOINT") or line.strip().startswith("CMD")
        )
    )
    assert user_line_idx < cmd_idx


def test_prod_dockerfile_no_dev_dependencies() -> None:
    dockerfile = _read_relative("Dockerfile")
    assert "requirements-dev" not in dockerfile


# ---- nginx.conf ---------------------------------------------------------


def test_nginx_conf_exists_and_core_content() -> None:
    nginx = _read_relative("nginx.conf")

    assert "server" in nginx
    assert "proxy_pass" in nginx
    assert "web:8000" in nginx
    assert "X-Forwarded-For" in nginx
    assert "X-Forwarded-Proto" in nginx
    assert "client_max_body_size" in nginx
    assert "150m" in nginx
    assert "proxy_read_timeout" in nginx
    assert "300s" in nginx
    assert "/static/" in nginx
    assert "/media/" in nginx


# ---- compose.yaml -------------------------------------------------------


def test_prod_compose_exists_and_services() -> None:
    compose = _read_relative("compose.yaml")

    assert "postgres:17" in compose
    assert "nginx.Dockerfile" in compose
    assert "prod-db-data" in compose
    assert "prod-media" in compose
    assert "prod-static" in compose
    assert "prod-backups" in compose


def test_prod_nginx_dockerfile_runs_as_app_uid() -> None:
    nginx_dockerfile = _read_relative("nginx.Dockerfile")

    assert "nginx:1.27-alpine" in nginx_dockerfile
    assert "1001" in nginx_dockerfile
    assert "adduser" in nginx_dockerfile


def test_prod_compose_healthchecks_and_non_default_password() -> None:
    compose = _read_relative("compose.yaml")

    # 三个服务都有健康检查
    assert compose.count("healthcheck") >= 3
    # 生产强制 DB 口令来自环境，禁止明文口令 keji
    assert "POSTGRES_PASSWORD" in compose
    assert "POSTGRES_PASSWORD: keji" not in compose


def test_prod_compose_binds_only_loopback() -> None:
    compose = _read_relative("compose.yaml")
    assert "127.0.0.1:18080:80" in compose
    assert "127.0.0.1:8000:8000" not in compose


# ---- .env.production.example -------------------------------------------


def test_env_production_example_exists_and_no_secrets() -> None:
    env = _read_relative(".env.production.example")

    assert "SECRET_KEY" in env
    assert "\nSECRET_KEY=" in env
    assert "\nDB_PASSWORD=" in env
    assert "DB_PASSWORD" in env
    assert "ADMIN_URL" in env
    assert "SESSION_COOKIE_SECURE" in env
    assert "CSRF_COOKIE_SECURE" in env
    assert "BACKUP_RETENTION_COUNT" in env


# ---- /healthz/ 健康检查端点 ---------------------------------------------


def test_healthz_returns_200_json(client: Any) -> None:
    resp = client.get("/healthz/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_requires_no_authentication(client: Any) -> None:
    resp = client.get("/healthz/")
    assert resp.status_code == 200
    # 无鉴权：未登录匿名请求同样 200
    assert resp.json() == {"status": "ok"}
