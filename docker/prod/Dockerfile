# 生产容器镜像：非 root 用户、最小化运行时依赖、静态/媒体/备份卷分离。
# 构建上下文为仓库根（docker/prod/compose.yaml 中 context: ../..）。

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 仅生产运行时依赖：
# - postgresql-client：pg_dump / pg_restore（backup / restore 命令，ADR-011）
# - libpq5：psycopg 运行时动态链接
# 不装 build-essential / 开发头文件，镜像保持最小。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行：应用用户 UID 1001。
RUN useradd --create-home --uid 1001 --shell /usr/sbin/nologin app

WORKDIR /app

# 仅生产依赖（requirements.txt 与 dev 分离，见仓库根文件）。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# 入口脚本可执行；运行期写入目录（staticfiles/media/backups）归 app 所有。
# 命名卷首次挂载时保留镜像内目录属主（app:app），保证非 root 可写。
RUN mkdir -p /app/staticfiles /app/media /app/backups \
    && chown -R app:app /app/staticfiles /app/media /app/backups \
    && chmod +x /app/docker/prod/entrypoint.sh

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/prod/entrypoint.sh"]
