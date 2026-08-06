# AGENTS.md — 客迹 Keji 开发约定

> 供 AI Agent 与协作者阅读。文档优先级：对应 ADR > 本文档 > README。
> 项目定位：保险代理人 / 顾问的自托管客户工作档案系统。
> 技术基线：Django 5.2 (LTS) + PostgreSQL 17 + psycopg3 + Templates + HTMX + Alpine + Tailwind + Gunicorn + Nginx + Docker Compose + pytest-django + Playwright。

## 项目结构

### 源码布局（规划中，以 docs/decisions/ 下的 ADR 为准）

```
config/                  # Django 项目配置：settings 拆分、根 urls、wsgi / asgi
apps/
  accounts/              # 用户、登录限流、权限位（手写权限，不引 RBAC 框架）
  customers/             # 客户档案、标签、客户间关系（配偶/父母子女/家庭/介绍人/同一家庭/自定义）
  activities/            # 工作事件、沟通记录、客户时间线聚合
  documents/             # 相册 / 文件：原图与派生图分离、SHA-1 去重、回收站软删除
  policies/              # 保单
  claims/                # 理赔与材料清单
  tasks/                 # 待办跟进
  dashboard/             # 首页工作队列和统计
  audit/                 # 审计日志（event_type 枚举 + metadata JSONField + 复合索引）
  core/                  # 通用基础模型、系统设置、全局搜索（pg_trgm）、保存视图、导出、备份命令
templates/               # 服务端模板（Django Templates）
static/                  # 静态资源（Tailwind + Alpine + HTMX）
```

每个 app 的标准布局：`models.py`（或 `models/` 包）、`views/`、`services.py`、`urls.py`、`tests/`、`migrations/`。

## 常用命令

```bash
# 容器命令（推荐，依赖 docker/dev/compose.yaml，由后续任务提供）
make dev-up / dev-down   # 启动 / 停止开发容器
make migrate             # 应用迁移（docker compose exec web python manage.py migrate）
make makemigrations      # 生成迁移
make createsuperuser     # 创建超级管理员
make runserver           # 前台开发服务器（容器内，端口 8000）
make seed                # 灌入演示数据（seed_demo --reset）
make test                # pytest（容器内）
make lint                # ruff check . && ruff format --check .
make typecheck           # mypy keji
make static              # collectstatic
make backup / restore    # pg_dump + gzip 备份 / 恢复

# 本地 venv 等价命令
pytest
ruff check . && ruff format --check .
mypy keji

# Playwright E2E（浏览器自动化，具体入口 / 标记以 ADR 为准）
docker compose -f docker/dev/compose.yaml exec web pytest -m e2e
```

## 开发约定

**TDD：RED → GREEN**

- 先写失败测试，再实现，最后重构
- 每个 app 的测试独立放在 `apps/<name>/tests/`，不跨 app 耦合

**分层**

- 视图保持薄：只做 HTTP 解析与模板渲染
- 业务逻辑放各 app 的 `services.py`（或 `services/` 包）中的服务函数 / 领域函数
- 不可变领域规则（状态流转、默认值）放模型方法
- 数据库读写经 services 层进出，不散落视图

**类型与代码质量**

- 禁止类型逃逸：不用 `# type: ignore`、不用 `cast()` 绕过 mypy、不把 `Any` 当万能类型（Python 版 "as any / ts-ignore" 等价物）
- 单文件纯逻辑不超过 250 行，超出拆模块
- ruff 与 mypy 零告警才能提交

**事务与数据**

- 涉及多模型写操作必须包在 `transaction.atomic()` 中，事务边界由服务层函数声明
- 不提交 `media/`、`backups/`、`.env`（见 .gitignore）；真实备份与密钥永不入库

**搜索与中文**

- 中文搜索用 pg_trgm（Django 内置），不要裸用默认 FTS（见 docs/reference-analysis.md §3）
- 图片管线借鉴 Immich 设计（原图 / 派生图分离、单次解码多尺寸），不复制其代码（AGPL）

## Agent 工作规则

每个任务按以下顺序执行：

1. **先读**：任务涉及模块的对应 ADR（docs/decisions/）与 data-model（模型定义）。写代码前先确认是否存在相关 ADR
2. **写失败测试**：为要实现的改动先写失败测试（pytest），确认 RED
3. **实现**：最小实现到 GREEN，再做清理
4. **提交**：独立、小粒度的提交，中文信息说明变更
5. **完成前验证**：对改动文件运行 lsp_diagnostics 修复告警；运行对应 app 的 pytest 确认全绿
6. 涉及模型改动时，同步生成迁移（makemigrations）并在提交前跑 migrate

## 反模式（禁止）

- 在视图里堆业务逻辑
- 用 signals 跨 app 塞逻辑（参考分析中 DjangoCRM 作反例）
- 提交生成物：`media/`、`backups/`、`staticfiles/`、`.env`
- 复制 Immich / Twenty / Paperless-ngx 源码（仅借鉴设计决策）
