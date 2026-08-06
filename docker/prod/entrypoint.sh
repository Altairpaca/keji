#!/usr/bin/env sh
# 生产入口：迁移 → 收集静态 → 启动 Gunicorn。
# 全部命令幂等，容器重启可安全重入。
set -e

echo "==> 应用数据库迁移 (migrate --noinput)"
python manage.py migrate --noinput

echo "==> 收集静态文件 (collectstatic --noinput)"
python manage.py collectstatic --noinput

echo "==> 启动 Gunicorn (workers=${WORKERS:-3})"
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WORKERS:-3}" \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
