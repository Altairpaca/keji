# 架构与模块边界

> 日期：2026-08-07 ｜ 版本：0.1.0
> 本文件是「客迹 Keji」第一版架构总览。架构决策记录见 `docs/decisions/`（14 份 ADR），
> 数据模型细节见 `docs/data-model.md`，技术选型背景见 `docs/reference-analysis.md`。

## 1. 总体架构：模块化单体

Keji 是**模块化单体（Modular Monolith）**（ADR-001）：

- 单个 Django 项目（`config/` settings 三态拆分：base / dev / prod）、单个进程、单个 PostgreSQL 数据库。
- 按业务域划分为 10 个 Django app，app 之间通过公开模型与明确的函数边界交互。
- 服务端渲染（Django Templates + HTMX + Alpine.js），无前后端分离（ADR-007）。
- 无微服务、无消息队列、无图数据库、无搜索服务（ADR-003）。

```
浏览器（桌面三栏 / 手机底部导航）
        │  HTTP（HTMX 局部刷新 + 标准表单）
        ▼
Django（Gunicorn）←── Nginx（生产：静态/媒体/反代）
        │
        ├── accounts   用户、登录限流、11 权限位（ADR-004/012）
        ├── customers  客户档案、状态、标签、关系、重复合并
        ├── activities 工作事件、沟通记录、统一时间线
        ├── documents  相册、文件存储抽象、缩略图、回收站（ADR-002/005/006）
        ├── policies   保单、状态历史、缴费提醒
        ├── claims     理赔案件、材料清单、ZIP 导出
        ├── tasks      待办、快速跟进
        ├── dashboard  首页工作队列与统计
        ├── audit      审计日志
        └── core       通用基类、系统设置、全局搜索、保存视图、导出、备份恢复
        │
        ▼
PostgreSQL 17（pg_trgm 中文搜索；生产与应用同 Compose 部署）
```

## 2. 分层与职责

每个 app 的标准分层（AGENTS.md 强制）：

| 层 | 位置 | 职责 |
|---|---|---|
| 模型 | `models/` 包 | 字段、约束、不可变领域规则（状态流转校验）、软删除（core 基类） |
| 服务 | `services/` 包 | 业务逻辑、事务边界（`transaction.atomic`）、跨模型写操作 |
| 视图 | `views/` | 只做 HTTP 解析与模板渲染；权限装饰器强制服务端校验 |
| 表单 | `forms.py` | 服务端校验、ModelForm |
| 模板 | `templates/<app>/` | 继承 `base.html` 三栏壳 / 手机底部导航 |

约束：

- 视图不堆业务逻辑；数据库读写经 services 进出。
- 跨 app 联动通过 import 服务函数（**不用 signals**，AGENTS.md 反模式）。
- 单文件纯逻辑 ≤250 行，超出拆模块。
- 涉及多模型写操作必须 `transaction.atomic()`。

## 3. 模块边界

### 3.1 accounts — 用户与权限
- `User`：AbstractUser 扩展，UUID 主键，11 个布尔权限位 + `has_bit()`（superuser 恒 True）。
- 登录限流（缓存 5 次/15 分钟）、密码修改、用户管理（can_manage_users）。
- `require_permission(bit)` 装饰器：未登录 302、无权限 403（ADR-004/012）。

### 3.2 customers — 客户档案
- `Customer`：规格 §6 全字段（姓名/手机/微信/地区/职业/来源/状态/优先级/沟通偏好/备注/负责人…）。
- `CustomerStatus`：15 个默认状态，管理员可维护（数据迁移种子）。
- `Tag`：自定义标签，M2M。
- `CustomerRelation`：7 类关系（配偶/父母子女/家庭成员/介绍人/同一家庭/自定义），双向查询。
- 服务：create/update/soft_delete/restore、assign_tags、find_duplicates、merge_customers。

### 3.3 activities — 工作事件与时间线
- `WorkEvent`（9 类）、`CommunicationRecord`（9 通道 + 10 快捷结果）。
- `build_timeline(customer)`：聚合事件/沟通/待办/文件上传，registry 扩展点（保单/理赔变化预留）。
- 跟进钩子：事件/沟通设置 `next_followup_date` 自动创建 Task（source_key 防重）。

### 3.4 documents — 文件管理
- 存储抽象 `StorageBackend` + `LocalDiskStorage`（ADR-002）：UUID 分片存储键、原子写入、防路径穿越。
- `Document`：元数据（原始名/存储键/MIME/大小/SHA-256/拍摄时间/敏感级别/核对状态…），`customers`/`albums` M2M，一文件多关联。
- 上传管线：魔数 + 扩展名白名单 + 100MB 上限 + 流式 SHA-256 去重 + 缩略图（webp 250px，HEIC 容错）。
- 敏感模糊（可配置开关 + can_view_sensitive 权限）、批量操作、回收站三级（软删/恢复/永久删除 + GC）。
- 相册 10 默认类别 + 自定义。

### 3.5 policies — 保单
- `Policy`：规格 §11 全字段，10 状态 + `STATUS_TRANSITIONS` 显式状态机。
- `PolicyStatusHistory`：append-only 状态历史。
- 缴费提醒：`next_premium_due` 计算、`mark_premium_paid`、自动同步待办。

### 3.6 claims — 理赔
- `ClaimCase`：14 状态状态机；`ClaimMaterial`：6 状态状态机（缺料队列数据源）。
- `ClaimMaterialTemplate`：按理赔类型预置材料清单（种子模板），`instantiate_template` 幂等。
- ZIP 导出：稳定目录结构 + 清单文件 + 路径净化 + 导出权限位。

### 3.7 tasks — 待办
- `Task`：11 类、优先级、状态机（open/in_progress/done/cancelled）、快速跟进（7/15/30/90 天）。
- 首页队列数据源：`overdue_tasks`、`tasks_due_between`。

### 3.8 dashboard — 首页
- 12 工作队列 + 6 统计卡；备份状态与存储概况占位（T11 已接备份状态）。

### 3.9 audit — 审计日志
- `AuditLog`：actor/action/object/result/detail(JSON)/IP/UA；detail 敏感字段清洗；不软删、不随业务对象删除。
- 关键操作接入点：永久删除、客户软删/恢复、保单/理赔状态变更、用户管理、导出、备份。

### 3.10 core — 通用能力
- 基类：`UUIDModel`/`TimeStampedModel`/`SoftDeleteModel`（objects 过滤 + all_objects + 三级删除）。
- `SystemSetting`（缓存读写）、`SavedView`（通用保存视图）。
- 全局搜索（pg_trgm + icontains registry，跨 5 类实体）、导出（CSV/档案/时间线/ZIP）。
- 备份/恢复命令（pg_dump + media tar + manifest + checksum + 保留策略）。

## 4. 关键横切设计

### 4.1 权限模型（ADR-004/012）
- 11 权限位挂在 User 上，`require_permission` 服务端强制；模板 `{% has_perm %}` 仅显示控制。
- 管理员（is_superuser）经 `has_bit` 覆盖一切。
- 权限矩阵见 `docs/security.md`；`apps/core/tests/test_permission_matrix.py` 强制回归。

### 4.2 软删除与回收站（ADR-006）
- 全部业务模型继承 `SoftDeleteModel`：普通删除 → 回收站 → 恢复 → 管理员永久删除。
- 永久删除需一致性处理（DB 记录/关联/物理文件/缩略图/审计），GC 命令清理过期项。
- 审计日志不随业务对象删除。

### 4.3 文件存储（ADR-002/005）
- 原始文件与缩略图分离目录；DB 只存元数据/哈希/存储键；UUID 存储键（非客户姓名）。
- 存储接口预留 S3 迁移；第一版本地磁盘直跑。

### 4.4 搜索（ADR-003）
- 中文场景 pg_trgm（已建扩展）+ ORM icontains；registry 扩展实体；无 Elasticsearch。

### 4.5 时区与金额
- `USE_TZ=True`、`TIME_ZONE=Asia/Taipei`；日期字段用 Date/DateTime；金额用 DecimalField。

## 5. 部署拓扑

- 开发：`docker/dev/compose.yaml`（postgres + runserver + 挂载源码）。
- 生产：`docker/prod/compose.yaml`（postgres + gunicorn 非 root + nginx 127.0.0.1:18080）；健康检查 `/healthz/`；迁移/collectstatic 由 entrypoint 幂等执行。
- 仅绑定本机端口，Tailscale 接入由部署者自管（`docs/deployment.md`）。
- 备份/恢复双轨（`docs/backup-restore.md`）：pg_dump 数据库 + media 卷，manifest + checksum + 保留策略 + 演练。

## 6. 扩展点（不实现的留白）

- 文件存储 S3 后端（StorageBackend 接口就位）。
- 搜索长文本相关度（zhparser 扩展预留，参考 `docs/reference-analysis.md` §3）。
- 时间线条目类型 registry（保单/理赔变化已预留 key）。
- 多用户团队规模扩展（权限位结构支持，RBAC 不做）。
- 短信/微信/OCR/AI 均不在第一版（见 `docs/product-requirements.md` 不在范围清单）。
