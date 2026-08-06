# 参考分析：Immich 媒体管线 + 关系图库选型 + Django 全文搜索

> 日期：2026-08-06 ｜ 提交：0687c0d3f76a075cf86ae5e28f1ec3ee3b355942 (immich main)
> 用途：客迹 Keji 照片模块（W9+）与客户关系图（W10）的实现依据

---

## 1. Immich 上传 / 缩略图 / 元数据管线（借鉴设计，不复制代码）

### 1.1 许可证：AGPL-3.0
[LICENSE](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/LICENSE)
- 采用：仅提取设计决策。不复制源码（AGPL 传染）。
- 自托管内部使用不受影响；若未来分发/提供网络服务需开源衍生代码。

### 1.2 三级派生文件 + 原图/派生图分离存储
[storage.core.ts L105-138](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/cores/storage.core.ts#L105-L138)

- 原图 → `library/{user}/...`（getLibraryFolder）
- 派生图（thumbnail/preview/fullsize）→ `thumbnails/{user}/{assetId}_{fileType}.{format}`（getImagePath 统一落 Thumbnails 目录，见 [L121-127](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/cores/storage.core.ts#L121-L127)）
- 视频转码 → `encoded-video/`
- 结论：原图与派生图分离（备份/存储分层、缩略图可重建、原图只写不读）。

### 1.3 尺寸与格式策略（默认值）
[config.ts L370-389](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/config.ts#L370-L389)

| 级别 | 格式 | 尺寸 | 质量 |
|---|---|---|---|
| thumbnail | **webp** | 250px | 80 |
| preview | **jpeg** | 1440px | 80 |
| fullsize | jpeg | —（默认禁用） | 80 |

- thumbnail 用 webp（体积小、支持透明）；preview 用 jpeg（兼容性优先）
- 解码管线：`rotate()`（按 EXIF Orientation 自动旋转）→ `resize(size, size, { fit:'outside', withoutEnlargement:true })`（等比缩放到包住目标框、**不放大**），[media.repository.ts L186-217](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/repositories/media.repository.ts#L186-L217)
- **单次解码多尺寸复用**：decodeImage 一次，同时产出 thumbhash + thumbnail + preview，[media.service.ts L312-364](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/services/media.service.ts#L312-L364) ← Keji 应照做（Pillow 打开一次，生成多尺寸）

### 1.4 HEIC/HEIF 处理
[mime-types.ts L77-78](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/utils/mime-types.ts#L77-L78)
- 结论：**sharp（libvips）直接解码** HEIC/HEIF/AVIF，无预转换步骤
- Keji 对应方案：Pillow 原生不支持 HEIC → 用 `pillow-heif`（注册 `register_heif_opener()`）后走同一管线；缩略图仍输出 webp（Django `WebPImagePlugin` 支持编码）
- 衍生：若原始图非 Web 支持格式，可选生成 fullsize jpeg（extractEmbedded 从 RAW 提取嵌入式预览）

### 1.5 EXIF 与拍摄时间
[metadata.repository.ts L83-120](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/repositories/metadata.repository.ts#L83-L120) ｜ [getDates L988-1055](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/services/metadata.service.ts#L988-L1055)
- 采用 exiftool（二进制子进程）+ `useMWG` 解决 EXIF/IPTC/XMP 冲突
- 时区策略：优先 EXIF 时区；无则 `inferTimezoneFromDatestamps` 推断；再退 GPS 坐标→时区（geo-tz）
- 无拍摄时间 → 回退 min(fileCreatedAt, mtime, birthtime)
- **存「本地时间」**（localDateTime）用于时间线排序；dateTimeOriginal 单独保留
- Keji 简化方案：`exifread`/`Pillow Image.getexif()` 取 `DateTimeOriginal` + 偏移；存 naive local datetime（用户时区单一，可省略 GPS 推断）

### 1.6 重复检测（两类）
- 上传查重：SHA-1 checksum，`getUploadAssetIdByChecksum(ownerId, checksum)` 上传前跳过重复，[asset.repository.ts L674-679](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/repositories/asset.repository.ts#L674-L679)
- 重复组：上传后 ML 向量相似度（duplicateId），非哈希——Keji 不需要，用 SHA-1 唯一约束即可

### 1.7 移动端批量上传并发
[foreground_upload.service.dart L189-231](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/mobile/lib/services/foreground_upload.service.dart#L189-L231)
- 前台：**默认 3 并发 worker 池**
- 后台 isolate：**串行**（注释明言并发 HTTP 客户端在后台 isolate 引发问题）
- Keji 手机端（HTMX/原生 input multiple）：直接参考——前端多选后按 3 并发分批上传，后台任务串行

### 1.8 回收站
[config.ts L403-406](https://github.com/immich-app/immich/blob/0687c0d3f76a075cf86ae5e28f1ec3ee3b355942/server/src/config.ts#L403-L406)
- `trash.enabled=true, days=30`：软删除 + 30 天后物理清理

---

## 2. 关系图库选型（电脑端有限层级展开 + 手机端单层列表）

| 库 | 许可证 | 渲染 | 移动触摸 | Django 集成 |
|---|---|---|---|---|
| **vis-network** | **Apache-2.0/MIT 双许可** | Canvas | 内置 touch 事件 | UMD 单文件 CDN/script，零构建 |
| Cytoscape.js | MIT | Canvas | 完整手势（捏合/拖拽） | UMD 可 script，偏图论分析/大图 |
| d3-force | ISC | SVG/Canvas | 无内置手势 | 只是力模拟引擎，非组件，需自建全部 |
| G6 (AntV) | MIT | Canvas/SVG/WebGL | 支持 | v5 包体系重，倾向打包器 |
| relation-graph | MIT | SVG/Canvas | 支持 | Vue/React 组件生态，纯 HTML 需 web-components 子包，体积大 |

**结论：采用 vis-network（Apache-2.0/MIT）**
- 原因：①**零构建 script 标签集成**最贴合「服务端渲染 Django + HTMX/Alpine」；②内置 `layout.hierarchical`（UD/LR 等）+ clustering/`openCluster`（selectNode 展开）正是「有限层级展开」场景；③触摸事件内置（`interaction` 支持 touch，见官方 interaction 文档），平板仍可用；④双许可最宽松
- 手机端：不渲染图，用「单层列表」替代（需求已如此定义）——这是正确降级：避免 Canvas 在触屏的可访问性/性能成本
- 拒绝 Cytoscape.js：强在图论分析/数千节点，有限层级（≤3 层、几十节点）大材小用且 API 更重
- 拒绝 G6/relation-graph：面向框架生态、需打包器或引入大型运行时，与 Django 模板直出冲突
- 拒绝 d3-force：无现成交互组件

---

## 3. Django 内置 Postgres 全文搜索（跨模型全局搜索）

**可行**，[Django 文档](https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/search/)：
- `SearchVector("name", "notes") + SearchVector("client__name", weight="C")` 支持跨字段/关联字段，权重 A/B/C/D
- `SearchRank(vector, query, weights=[...])` 相关度排序
- **跨模型合并**：每模型 annotate `search_document` + `type`，`values('pk','type','rank').union(...).order_by('-rank')`（Simon Willison 模式；需统一输出列，再按 type 二次取实例）

**局限（Keji 中文场景关键）**：
1. **默认分词器对中文失效**：PG `simple`/`english` 无中文词边界，`to_tsvector('中文文本')` 会整串当一个 token，FTS 基本无效 → 需自装 `zhparser` 或 `pg_jieba` 扩展（自托管可装）或改用 pg_trgm
2. **pg_trgm 是中文子串/模糊搜索的务实默认**：`TrigramSimilarity`/`TrigramWordSimilarity` + `__trigram_similar` lookup + `GIN (col gin_trgm_ops)` 索引，Django 内置支持，对「张三」「张小明」类模糊匹配有效
3. **union 分页/排序限制**：不能直接对跨模型 union 做 ORM 实例分页；大文本（沟通内容）应建 `SearchVectorField` + GIN 索引 + 触发器维护，否则扫描慢

**结论**：跨模型全局搜索「可行但有前提」——客户/保单/理赔等短字段用 **pg_trgm + gin_trgm_ops 索引**（中文友好、Django 内置）；沟通内容等长文本若要求相关度排序，装 zhparser 后走 SearchVector/GIN。不要裸用默认 FTS 搜中文。

---

## 4. 采用/拒绝汇总

| 决策 | 采用/拒绝 | 原因 |
|---|---|---|
| 原图/派生图分离 + 三级尺寸（thumb webp 250 / preview jpeg 1440） | 采用 | Immich 默认，单次解码多尺寸复用 |
| HEIC 用 pillow-heif 注册解码，缩略图输出 webp | 采用 | Pillow 不支持 HEIC 原生；webp 体积小 |
| 拍摄时间存 naive 本地时间，回退文件时间 | 采用 | Immich 同款策略，简化去时区推断 |
| SHA-1 checksum 上传查重 | 采用 | 足够；ML 向量重复组拒绝（复杂度不值） |
| 手机端 3 并发上传、后台串行 | 采用 | Immich 实测策略 |
| 回收站软删除 + 30 天清理 | 采用 | 同 Immich |
| **vis-network** 画关系图 | **采用** | MIT/Apache 双许可、零构建、hierarchical+cluster 契合 |
| 手机端图渲染 | 拒绝 | 用单层列表替代（需求既定，性能/可用性更优） |
| 全局搜索 pg_trgm 为主 | 采用 | 中文场景 FTS 默认无效 |
| 裸 SearchVector 搜中文 | 拒绝 | 需 zhparser/pg_jieba 前置 |

---

## 5. Twenty CRM + Django CRM 研究（客户列表/详情/保存视图/关系建模）

> 研究仓库：twentyhq/twenty、MicroPyramid/django-crm、DjangoCRM/django-crm（均浅克隆审计关键源码）

### 5.1 许可证

| 项目 | 许可证 | 说明 |
|---|---|---|
| twentyhq/twenty | **AGPL-3.0**（含商业例外：`/* @license Enterprise */` 文件不受 AGPL 约束） | LICENSE 开头明示 "mostly licensed under AGPLv3… with two qualifications" |
| MicroPyramid/django-crm | **MIT** | API `license.spdx_id = MIT` |
| DjangoCRM/django-crm | **AGPL-3.0** | LICENSE 文件 |

Twenty 与 DjangoCRM 均为 AGPL——只借鉴设计模式，不复刻代码。

### 5.2 Twenty CRM 结论

- **元数据驱动**：对象与字段本身是数据字典（`objectMetadata` 表，nameSingular/namePlural 唯一约束），列表/详情由元数据生成，无每对象手写页面。
- **保存视图五件套**：`view` 主表 + 子表族 `view-field`（列）/`view-filter`（筛选）/`view-filter-group`/`view-sort`/`view-group`（看板列）/`view-field-group`；每条筛选 = `{fieldMetadataId, operand(枚举), value(jsonb)}` 三元组。
- **详情页布局数据驱动**：`page-layout`/`page-layout-tab`/`page-layout-widget` 模块决定记录页 tab 与 widget，标准模板 `standard-page-layout-tabs.template.ts`。
- **关系建模**：field-metadata 上的 relation 类型（toOne/toMany）+ 对象元数据唯一键，无单独"关系表"。

关键文件：
`packages/twenty-server/src/engine/metadata-modules/view/entities/view.entity.ts`、`.../view-filter/entities/view-filter.entity.ts`、`.../object-metadata/object-metadata.entity.ts`、`.../page-layout-tab/entities/page-layout-tab.entity.ts`、`.../workspace-manager/twenty-standard-application/constants/standard-page-layout-tabs.template.ts`

**采用**：保存视图 = view 主表 + filter 子表（`{field, operand, value JSONField}`）映射为 Django models；详情页 tab 用配置/常量驱动。**拒绝**：运行时动态建表（TypeORM 模式在 Django 成本极高）与 React/GraphQL 前端。

### 5.3 MicroPyramid/django-crm 结论（MIT）

- **app 按业务域划分**：`backend/{accounts, contacts, leads, opportunity, cases, tasks, invoices, orders, packs, common}`。
- 每 app 标准布局：`models.py` + `views/`（多视图模块）+ `services.py`/`services/` 包 + `urls.py` + `serializer.py` + `tasks.py`（Celery）+ `swagger_params.py`。
- **时间线/附件**：`common` 中 `Comment`/`Attachment` 用 `GenericForeignKey(content_type, object_id)` + org 归属校验 + 复合索引 `(content_type, object_id)`。
- **审计日志**（`common/audit_log.py` 的 `SecurityAuditLog`）：`event_type` 枚举 + user/org FK + `metadata JSONField` + ip/user_agent/request_path/method + `success` 布尔 + 复合索引（如 `(event_type, -created_at)`）。
- 状态建模：`stage` FK 指向 `LeadStage`（归属 `LeadPipeline`），支持流程化管道。

关键文件：`backend/leads/{models.py, services.py, views/lead_views.py}`、`backend/contacts/models.py`、`backend/common/{models.py, audit_log.py}`

**采用**：app 边界对应业务域；审计日志字段集与索引设计；GenericFK 时间线条目 + 归属校验。**拒绝**：DRF + React 前端（与 HTMX/SSR 栈不符）。

### 5.4 DjangoCRM/django-crm 结论（AGPL-3.0）

- app 较少：`crm / common / tasks / massmail / analytics / voip / chat`。
- `crm/models/` 是**包**，按实体拆文件：`base_contact.py / contact.py / company.py / deal.py / lead.py / tag.py / payment.py / product.py / request.py / crmemail.py`。
- 实体用 **mixin 链**：`Contact(BaseCounterparty, BaseContact, Base1)`。
- **标签** = 独立 `Tag` 模型 + Contact/Deal 上 `ManyToManyField`（`tag.py`）。
- **状态** = `CharField(choices)` + `get_status_display` + 状态联动逻辑放 save 方法（`payment.py`）。

关键文件：`crm/models/{base_contact.py, contact.py, deal.py, tag.py, payment.py}`

**采用**：models/ 包拆分、Tag 独立模型 + M2M、状态 choices + 模型方法。**拒绝**：无服务层（逻辑堆 model+signals，作反例）；无独立 Timeline 模型（时间线建模取 mp-crm 的 GenericFK 模式）。

---

## 6. Paperless-ngx 文档管理研究（存储/去重/标签/权限/回收站/备份）

> 研究仓库：paperless-ngx/paperless-ngx（master @ commit `71e2f86`，GPL-3.0）

### 6.1 文件存储与元数据分离

- 磁盘目录三区分离：`MEDIA_ROOT/{documents/originals, documents/archive, documents/thumbnails}`；DB 不存路径模板，只存唯一 `filename`/`archive_filename` + 非唯一 `original_filename`（保留上传原名）。文件名由模板 + 冲突后缀生成，不用 checksum 作文件名。
- 证据：`src/paperless/settings/__init__.py#L69-L72`；`src/documents/models.py#L265-L293`；`src/documents/file_handling.py#L44-L97`

**采用**：原图/缩略图分离目录 + DB 存唯一存储键 + 单独保留原始文件名。**拒绝**：模板化命名（Keji 对象关联复杂，文件名需稳定）。

### 6.2 重复检测

- 精确重复 = SHA-256 checksum（`compute_checksum` 分块读，db_index），入库前 `Q(checksum=X) | Q(archive_checksum=X)` 查询，区分"回收站中的重复"。无内置相似度检测。
- 证据：`src/documents/utils.py#L189-L194`；`src/documents/consumer.py#L976-L1025`

**采用**：入库前 SHA-256 去重 + 唯一约束；sanity 复查防静默损坏。

### 6.3 标签/类型建模

- `Correspondent`/`DocumentType`/`StoragePath` 均为 `MatchingModel`（name + match + algorithm，可选 owner）；`Tag(MatchingModel, TreeNodeModel)` 支持**层级标签**（treenode 包，最大深度 5，防环）；文档用 `tags = M2M`，可空 FK + `SET_NULL`。命名唯一约束 `(name, owner)`。
- 证据：`src/documents/models.py#L46-L155`

**采用**：层级标签（深度≤5）+ 可空 FK + SET_NULL；**简化**：去掉匹配算法字段（Keji 不需自动归类）。

### 6.4 用户权限

- **django-guardian 对象级权限**：`PaperlessObjectPermissions(DjangoObjectPermissions)` 覆写 `has_object_permission`——有 owner 的对象 → 本人直接放行，否则查 guardian；无 owner → 全员可见。视图层 `get_objects_for_user_owner_aware` 过滤。
- 证据：`src/documents/permissions.py#L36-L61`、`#L334-L353`

**采用**：owner 快捷通道 + 对象权限模式。**实现取舍**：Keji 为单管理员/普通用户小规模，采用手写权限位（见 ADR-004），结构上保留 owner 归属字段。

### 6.5 删除/回收站/审计

- `Document(SoftDeleteModel)` 软删除（django_softdelete）；物理文件删除信号里移入 `EMPTY_TRASH_DIR`（冲突后缀）；定时任务 `empty_trash` 按 `PAPERLESS_EMPTY_TRASH_DELAY`（默认 30 天）硬删 + 清理审计日志。审计用 django-auditlog 中间件。
- 证据：`src/documents/models.py#L157`；`src/documents/tasks.py#L460-L487`；`src/documents/signals/handlers.py#L343-L355`；`src/paperless/settings/__init__.py#L1033-L1036`

**采用**：软删除 + 延迟硬删 + 审计全量方案（Keji 自建 audit app，见 ADR 决策；不引入 django-auditlog 依赖）。

### 6.6 备份/恢复

- **双轨制**：① `document_exporter` 管理命令导出文件+缩略图+`manifest.json`（全量元数据/标签/审计，JSON 流式分批，支持增量/zip/加密）；② 官方文档要求**另做 PostgreSQL 备份**（pg_dump），因 exporter 不含运行时数据。
- 证据：`docs/administration.md#L277-L320`；`src/documents/management/commands/document_exporter.py#L360-L430`

**采用**：双轨制（文件 manifest 导出 + pg_dump）；**简化**：第一版不做增量与加密，但保留 manifest + checksum。

### 6.7 总建议

| 决策点 | Keji 方案 |
|---|---|
| 存储 | `{originals, thumbnails, trash}/` 三区，DB 存唯一存储键 + 原名 |
| 去重 | SHA-256 checksum + db_index，入库前校验 |
| 标签 | 层级树（≤5 层），可空 FK + SET_NULL |
| 权限 | 手写权限位 + owner 归属（小规模，见 ADR-004） |
| 删除 | SoftDelete + 延迟清理 + 自建 audit |
| 备份 | manifest 导出 + pg_dump 双轨 |

**结构分歧点**：Paperless 的 Document 直接挂 checksum（单文件文档系统）；Keji 一份文件对象关联多实体（客户/相册/工作事件/保单/理赔/材料项）——checksum 放文件实体本身，关联走 M2M/中间表，服务端只存一份原始文件。

