# Changelog

本项目所有重要变更均记录在此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-08-07

第一版。10 个业务应用全部实现，开发与生产部署可用，备份恢复演练完成，pytest / Playwright / ruff / mypy 全绿。

### 新增

#### 项目骨架与基础设施

- 初始化仓库：`.gitignore`、AGPL-3.0-only 许可证、`docs/`、`scripts/`、`backups/` 目录
- 项目骨架文档：`.env.example`、`README.md`、`AGENTS.md`、`CHANGELOG.md`、`Makefile`
- 参考分析 `docs/reference-analysis.md`（Immich 媒体管线、关系图库选型、Django 中文全文搜索、Twenty / django-crm / Paperless-ngx 的借鉴与拒绝结论）
- 开发环境编排 `docker/dev/`（PostgreSQL 17 + web 容器）与全部 Make 目标
- 生产环境编排 `docker/prod/`：nginx → web → db 三层，对外只暴露 nginx 的 `127.0.0.1:18080`，全部服务非 root 运行，web=UID 1001
- 生产环境变量模板 `docker/prod/.env.production.example`，生产强制 `SECRET_KEY` 与 `POSTGRES_PASSWORD`（缺失拒绝启动）
- 健康检查端点 `/healthz/`（web 容器 gunicorn 与 nginx 均内置 healthcheck）
- 架构决策记录（ADR-001 ~ ADR-014，`docs/decisions/`）

#### 账户与权限（apps/accounts / apps/audit）

- 登录 / 登出、登录失败限流、11 个手写权限位（无 RBAC 框架）
- 操作审计日志 `AuditLog`（event_type 枚举 + metadata JSONField + 复合索引）

#### 客户档案（apps/customers）

- 客户 CRUD、15 种客户状态、标签分类
- 客户间 7 类关系（配偶 / 父母子女 / 家庭成员 / 介绍人 / 同一家庭 / 上下级 / 自定义）
- 重复客户检测与合并
- 客户关系网络图：vis-network 渲染（电脑端有限层级展开，手机端单层列表）

#### 工作事件与时间线（apps/activities）

- 工作事件 9 类、沟通记录 9 种通道
- 客户 / 保单 / 理赔 / 文件的统一时间线聚合

#### 文件与相册（apps/documents）

- 上传校验：魔数 + 白名单类型、单文件上限 100MB、sha256 去重
- HEIC / HEIF 容错（pillow-heif）、EXIF 拍摄时间读取
- WebP 缩略图、敏感图片模糊、原图 / 派生图分离存储
- 回收站三级：软删除 → 30 天延迟清理 → 永久删除（`empty_trash` 命令）
- 批量上传 / 批量操作、相册（10 个默认分类）

#### 保单与理赔（apps/policies / apps/claims）

- 保单管理：10 种状态、状态历史 `PolicyStatusHistory`、缴费到期提醒
- 理赔管理：14 种状态、材料清单 6 种材料状态、材料模板、ZIP 批量导出

#### 待办与首页（apps/tasks / apps/dashboard）

- 待办 11 类、快速跟进（7 / 15 / 30 / 90 天）
- 首页工作队列：12 个队列 + 6 项统计

#### 检索与数据（apps/core）

- 全局搜索：跨客户 / 保单 / 理赔（PostgreSQL pg_trgm，中文友好）
- 保存视图（筛选条件持久化）
- CSV 批量导入与导出
- 演示数据命令 `seed_demo`（`--reset` 支持）
- 备份命令 `backup`：`backups/<时间戳>/{db.dump, media.tar.gz, manifest.json, checksums.txt}`，含保留策略清理
- 恢复命令 `restore_backup`：`--stamp` / `--latest` / `--db-name` / `--yes`，校验和验证 + pg_restore + 安全解包

#### 前端与多端

- Tailwind 3.4 样式 + HTMX + Alpine.js 交互
- 响应式布局（桌面 / 手机双视口）
- PWA：manifest、service worker、离线缓存

#### 测试

- pytest 全量用例 1166+ 全绿（单元 / 集成 / 安全 / 备份恢复一致性）
- Playwright E2E 62 例（`tests/e2e/`，桌面 + mobile 双视口）
- 覆盖率统计、ruff 与 mypy 零告警
- 恢复演练完成（见 `docs/backup-restore.md`）

### 变更

- 文档定位从「开发早期蓝图」更新为「第一版可用」：`docs/deployment.md`、`docs/testing.md` 补齐为实际可执行命令与真实结果
- 文档命令与 Makefile / 管理命令逐字对齐，由测试与本次文档核对双重校验

### 修复

- README 文件去重描述由 SHA-1 更正为 sha256（与实现一致）
- Makefile 的 `typecheck` 目标 `mypy keji` 修正为 `mypy`（检查范围以 pyproject.toml 的 `files` 为准）；同步更正 AGENTS.md 中的等价命令

### 已知限制（非缺陷）

- 备份为全量 + 保留策略，不含增量与加密
- 全局搜索以 pg_trgm 为主，长文本相关度排序需 zhparser 扩展，不在当前版本
- `check --deploy` 尚有 2 个 low 级 HTTPS 相关提示，纯 HTTP 内网部署下为预期行为
