#!/usr/bin/env bash
# restore.sh — 容器友好的恢复脚本（规格 §18 恢复演练）
#
# 用法：
#   ./scripts/restore.sh                 # 恢复最新备份（交互确认）
#   ./scripts/restore.sh <stamp>         # 恢复指定备份（交互确认）
#   ./scripts/restore.sh --yes [<stamp>] # 跳过确认（CI / 演练用）
#
# 行为：在 web 容器内调用 manage.py restore_backup（校验和 → pg_restore
# → media 安全解包）。默认恢复目标为 settings 的 DB_NAME；可用环境变量
# RESTORE_DB_NAME 覆盖（如恢复演练库 keji_drill），不影响开发主库。
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker/dev/compose.yaml"

if ! $COMPOSE ps --status running web >/dev/null 2>&1; then
    echo "错误：web 容器未运行（先执行 make dev-up）" >&2
    exit 1
fi

LATEST=$($COMPOSE exec -T web python manage.py shell -c \
    "from apps.core.services.restore import list_backup_snapshots; print(list_backup_snapshots()[0]['stamp'])" 2>/dev/null || true)

YES=""
if [ "${1:-}" = "--yes" ]; then
    YES="--yes"
    shift
fi

STAMP="${1:-$LATEST}"
if [ -z "$STAMP" ]; then
    echo "错误：backups/ 下没有可恢复的备份快照" >&2
    exit 1
fi

ARGS=""
if [ -n "${RESTORE_DB_NAME:-}" ]; then
    ARGS="--db-name $RESTORE_DB_NAME"
fi

echo "将恢复备份快照：$STAMP"
echo "  目标库：${RESTORE_DB_NAME:-<settings DB_NAME>}"
$COMPOSE exec web python manage.py restore_backup --stamp "$STAMP" $ARGS $YES
