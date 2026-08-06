# 客迹 Keji

自托管客户工作档案系统。面向保险代理人、独立理财顾问等个人从业者，把客户档案、照片文件、事件跟进收拢到一个私有、可检索、可备份的地方。

> 当前状态：开发早期（里程碑 W0 初始化）。生产部署与完整功能逐步完善中。

## 项目定位

客户资料散落在手机相册、Excel、微信聊天记录里，是代理人最常见的管理痛点。客迹用一个自托管系统把这些信息统一管理：客户基本档案、家庭 / 推荐关系、历次沟通事件、保单、理赔材料、照片文件、待办事项，全部落在一个由你自己掌控的服务器上。

- 面向用户：保险代理人、独立理财顾问、房产经纪等需要长期维护客户档案的从业者
- 部署形态：自托管（自有服务器 / NAS / VPS），数据不出自己的网络
- 使用端：电脑浏览器 + 手机浏览器（响应式 + PWA，可安装到桌面 / 主屏）

## 功能特性

**客户档案**

- 客户基本信息与备注，标签分类
- 客户关系网络（vis-network 关系图：电脑端有限层级展开，手机端单层列表）
- 推荐人 / 家庭关系 / 上下级关系建模

**工作事件时间线**

- 每次跟进、拜访、沟通记录为一条事件，按时间线组织
- 事件可关联客户、保单、理赔，后续补录也可回溯

**照片与文件**

- 原图 / 缩略图分离存储，单次解码产出多尺寸（借鉴 Immich 设计）
- HEIC / HEIF 支持（pillow-heif），读取 EXIF 拍摄时间
- SHA-1 上传去重，回收站软删除 + 30 天延迟清理

**保单与理赔**

- 保单管理（险种、保额、缴费、期限）
- 理赔材料清单：按材料项逐项核对是否齐备

**待办与工作队列**

- 待办跟进事项（到期提醒）
- 首页工作队列：今日待办、近期到期、待处理理赔汇总

**检索与数据**

- 全局搜索：跨客户 / 保单 / 理赔（PostgreSQL pg_trgm，中文友好）
- 批量导入导出（CSV）
- 操作审计日志：谁在何时改了什么

**运维与多端**

- 回收站 + 备份 / 恢复（pg_dump + 文件 manifest 双轨）
- 手机端 / 电脑端自适应界面，PWA 可离线使用

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | Django 5.2 (LTS) | Python 服务端渲染（Templates） |
| 数据库 | PostgreSQL 17 + psycopg3 | pg_trgm 中文搜索、JSONField |
| 交互 | HTMX + Alpine.js | 局部刷新与轻量前端状态 |
| 样式 | Tailwind CSS | 响应式布局 |
| 服务 | Gunicorn + Nginx | 生产部署 |
| 容器 | Docker Compose | 开发与部署编排 |
| 终端 | PWA | 手机端可安装、离线缓存 |
| 测试 | pytest-django + Playwright | 单元 / E2E |
| 质量 | ruff + mypy | 风格与静态类型检查 |

## 快速启动（开发环境）

前置：Docker + Docker Compose（V2）、Make。

```bash
# 1. 准备环境变量（复制模板后按需修改，各变量含义见 .env.example 注释）
cp .env.example .env

# 2. 启动开发环境（db + web 容器，后台运行）
make dev-up

# 3. 应用数据库迁移
make migrate

# 4. 创建超级管理员（首次启动必做）
make createsuperuser

# 5. 灌入演示数据（可选，用于体验完整功能）
make seed

# 6. 访问系统
#    主界面：  http://127.0.0.1:8000
#    后台管理：http://127.0.0.1:8000/admin/ （入口由 ADMIN_URL 决定）
```

常用命令：`make dev-down` 停止环境、`make test` 跑测试、`make lint` 风格检查、`make typecheck` 类型检查、`make backup` / `make restore` 备份与恢复。完整列表见 `make help`。

> 生产部署请阅读 `docs/deployment.md`（规划中，尚未随本仓库提供）。

## 目录结构

```
keji/
├── .env.example          # 环境变量模板（复制为 .env 后使用，.env 不入库）
├── .gitignore
├── LICENSE               # AGPL-3.0-only
├── Makefile              # 常用开发 / 运维命令
├── README.md             # 本文档
├── AGENTS.md             # 面向 AI Agent 与开发者的工作约定
├── CHANGELOG.md          # 变更记录（Keep a Changelog）
├── config/               # Django 项目配置（settings / urls / wsgi / asgi）
├── apps/                 # 业务应用（accounts / clients / relations / ...）
├── templates/            # 服务端模板
├── static/               # 静态资源（CSS / JS / 图片）
├── media/                # 用户上传文件（不入库，需随备份保留）
├── backups/              # 备份输出目录（不入库）
├── docker/
│   └── dev/
│       └── compose.yaml  # 开发环境编排（后续初始化任务创建）
├── scripts/              # 运维脚本
└── docs/
    ├── reference-analysis.md  # 参考项目分析（Immich / Twenty / Paperless-ngx 等）
    ├── deployment.md          # 生产部署指南（规划中）
    ├── decisions/             # ADR 架构决策记录
    └── screenshots/           # 真实运行截图（虚构数据）
```

> 上述 `config/`、`apps/` 为规划结构，最终以 `docs/decisions/` 下的 ADR 为准。

## 文档索引

| 文档 | 一句话说明 |
|---|---|
| `docs/reference-analysis.md` | 参考项目研究：Immich 媒体管线、关系图库选型、Django 中文全文搜索、Twenty / django-crm / Paperless-ngx 的借鉴与拒绝结论 |
| `docs/decisions/` | 架构决策记录（ADR）。改动核心结构前先读对应 ADR |
| `docs/deployment.md` | 生产部署指南（规划中） |
| `docs/screenshots/` | 真实运行截图，内容为虚构数据 |

## 当前限制与不在范围

- 面向单管理员 / 小团队，采用手写权限位（结构上保留 owner 归属字段），不做企业级 RBAC
- 不做原生移动 App，以响应式 + PWA 覆盖手机端
- 不做 ML 相似图片去重与自动归类（参考分析中已明确拒绝）
- 不做邮件 / 短信自动同步
- 第一版备份不含增量与加密（后续版本规划）
- 全局搜索以 pg_trgm 为主；长文本相关度排序需要 zhparser 扩展，不在第一版范围

## 隐私与合规

- 本项目为自托管软件，数据保存在你自己的服务器与私有网络内
- 使用前请确认遵守当地数据保护法规（如《个人信息保护法》；涉及 GDPR 等同样适用）
- Tailscale / 内网穿透解决的是「远程访问」，不是备份的替代品，请仍配置备份
- 生产部署前必须修改 `.env` 中的默认密钥与数据库口令，并将 `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` 设为 true

## 许可证

AGPL-3.0-only（详见 LICENSE）。

本项目借鉴了 Immich / Twenty / Paperless-ngx 的设计，仅借鉴设计决策，不复制其代码，相关结论见 `docs/reference-analysis.md`。

## 截图

见 `docs/screenshots/`（真实运行截图，虚构数据）。
