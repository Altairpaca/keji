# ===========================================================================
# 客迹 Keji — 开发 / 运维命令
#
# 用法：make <目标>；make help 查看全部目标。
#
# 说明：
#   - 涉及 web / db 容器的命令依赖 docker/dev/compose.yaml 提供的服务
#     （由后续初始化任务创建）。容器就绪前请勿调用这些目标。
#   - 环境变量从 .env 读取（若存在）；未设置时使用下方 ?= 默认值。
#   - help 与纯静态目标（如 dev-up 之外的查询类）现在即可运行。
# ===========================================================================

SHELL := /bin/bash
COMPOSE := docker compose -f docker/dev/compose.yaml

-include .env
DB_USER ?= keji
DB_NAME ?= keji

.DEFAULT_GOAL := help

.PHONY: help dev-up dev-down migrate makemigrations createsuperuser runserver
.PHONY: test lint typecheck static seed backup restore

help: ## 列出所有可用目标与说明
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F '## ' '{ cmd = $$1; sub(/: *$$/, "", cmd); printf "  \033[36m%-16s\033[0m %s\n", cmd, $$2 }'

dev-up: ## 启动开发环境（db + web 容器，后台运行）
	$(COMPOSE) up -d

dev-down: ## 停止并移除开发容器
	$(COMPOSE) down

migrate: ## 应用数据库迁移
	$(COMPOSE) exec web python manage.py migrate

makemigrations: ## 生成模型迁移文件
	$(COMPOSE) exec web python manage.py makemigrations

createsuperuser: ## 创建超级管理员（首次启动必做）
	$(COMPOSE) exec web python manage.py createsuperuser

runserver: ## 前台启动开发服务器（容器内，端口 8000）
	$(COMPOSE) exec web python manage.py runserver 0.0.0.0:8000

test: ## 运行后端测试（pytest-django）
	$(COMPOSE) exec web pytest

lint: ## 代码风格检查（ruff check + format 检查）
	$(COMPOSE) exec web ruff check . && $(COMPOSE) exec web ruff format --check .

typecheck: ## 静态类型检查（mypy）
	$(COMPOSE) exec web mypy keji

static: ## 收集静态文件（collectstatic）
	$(COMPOSE) exec web python manage.py collectstatic --noinput

seed: ## 灌入演示数据（seed_demo --reset）
	$(COMPOSE) exec web python manage.py seed_demo --reset

backup: ## 备份数据库到 backups/（pg_dump + gzip）
	@mkdir -p backups
	@f="backups/keji_$$(date +%Y%m%d_%H%M%S).sql.gz"; \
	$(COMPOSE) exec -T db pg_dump -U $(DB_USER) $(DB_NAME) | gzip > "$$f"; \
	echo "备份完成：$$f"

restore: ## 从 backups/ 最新备份恢复数据库（危险操作，覆盖现有数据）
	@latest=$$(ls -t backups/keji_*.sql.gz 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "错误：backups/ 中没有可恢复的备份文件"; exit 1; fi; \
	echo "将从 $$latest 恢复数据库（覆盖现有数据）..."; \
	gzip -dc "$$latest" | $(COMPOSE) exec -T db psql -U $(DB_USER) $(DB_NAME)
