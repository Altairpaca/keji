# 安全设计（security）

> 日期：2026-08-06 ｜ 状态：蓝图。W2 起实现的安全基线，与 ADR-004（权限位）、ADR-012（角色）、ADR-002（存储）、ADR-006（软删除）配套阅读。
> 原则：服务端强制校验优先；UI 隐藏只是展示；不宣称实现本文件之外的安全能力（尤其病毒查杀）。

## 1 威胁模型

| 威胁 | 描述 | 对策 |
|---|---|---|
| 越权访问 | 未认证或低权限用户访问他人数据、URL 枚举遍历 | UUID 主键 + requires_permission 服务端校验 + 403 |
| 认证攻击 | 密码爆破、弱口令、会话劫持 | bcrypt/argon2、登录限流、安全 Cookie、会话超时 |
| 恶意上传 | 可执行文件、SVG 脚本、压缩炸弹、超大图 DoS | 类型白名单 + 魔数 + 大小/像素上限（见 §4） |
| 路径穿越 | `..`、绝对路径、危险文件名写入磁盘 | UUID 存储键 + 路径规范化拒绝 |
| 数据泄漏 | PII 进日志、错误页、URL、文件路径 | UUID 键、日志脱敏、Content-Disposition |
| 删除/数据丢失 | 误删、故障、无备份 | 软删除三级协议 + 备份演练（ADR-006/011） |
| CSRF/XSS | 跨站请求伪造、上传内容携带脚本 | CSRF 全程启用、模板输出转义、SVG 拒绝 |
| 供应链 | 外网 CDN、外部 AI 服务外发数据 | 本地托管静态资源、外部 AI 默认关闭 |

## 2 权限矩阵（11 权限位 × 2 角色）

| 权限位 | 说明 | 管理员 | 普通用户默认 | 管理员覆盖 |
|---|---|---|---|---|
| perm_customer_view | 查看客户资料与关系 | 是 | 是 | 覆盖 |
| perm_customer_manage | 新增/编辑/软删/恢复客户 | 是 | 否 | 覆盖 |
| perm_policy_view | 查看保单 | 是 | 是 | 覆盖 |
| perm_policy_manage | 管理保单与状态流转 | 是 | 否 | 覆盖 |
| perm_claim_view | 查看理赔案件 | 是 | 是 | 覆盖 |
| perm_claim_manage | 管理理赔与材料审核 | 是 | 否 | 覆盖 |
| perm_document_view | 查看文件与缩略图 | 是 | 是 | 覆盖 |
| perm_document_manage | 上传/软删/恢复文件 | 是 | 是 | 覆盖 |
| perm_document_download_export | 下载/导出/永久删除敏感文件 | 是 | 否 | 覆盖 |
| perm_activity_view | 查看活动/任务/时间线 | 是 | 是 | 覆盖 |
| perm_activity_manage | 管理活动/任务 | 是 | 否 | 覆盖 |

「管理员覆盖」= `is_superuser` 在 `requires_permission` 直接放行，不逐个校验权限位；普通用户默认值可在用户管理页逐项调整。无 UI-only 门禁：所有入口对应视图必有服务端 403。

## 3 视图权限挂载清单

| app | 视图/动作 | 挂载权限 |
|---|---|---|
| accounts | 登录/登出/改密 | 认证即可（无权限位） |
| accounts | 用户管理（建/停用/授权） | 仅管理员（is_superuser） |
| customers | 列表/详情 | perm_customer_view |
| customers | 新增/编辑/软删/恢复/关系管理 | perm_customer_manage |
| activities | 工作事件/沟通/时间线 查看 | perm_activity_view |
| activities | 事件/沟通 增改删 | perm_activity_manage |
| documents | 相册/文件列表、查看缩略图与原图 | perm_document_view |
| documents | 上传/删除/恢复 | perm_document_manage |
| documents | 下载/导出/永久删除 | perm_document_download_export |
| policies | 列表/详情 | perm_policy_view |
| policies | 增改删/状态流转 | perm_policy_manage |
| claims | 列表/详情 | perm_claim_view |
| claims | 增改删/材料审核 | perm_claim_manage |
| claims | 理赔 ZIP 导出 | perm_claim_manage + perm_document_download_export |
| tasks | 列表/详情 | perm_activity_view |
| tasks | 增改删/完成/逾期处理 | perm_activity_manage |
| audit | 审计日志查看 | 仅管理员 |
| core | 系统设置 | 仅管理员 |
| core | 保存视图 | 本人（个人数据，无权限位） |

## 4 上传安全策略

- **类型白名单**：MIME 与扩展名双重白名单（jpeg/png/webp/heic/heif/pdf 等），两者不一致即拒绝。
- **魔数校验**：按文件头签名核对真实类型，与声明 MIME 不符拒绝（不信任 Content-Type）。
- **大小限制**：单文件上限可配置（默认 50MB），请求体总量上限防整包轰炸。
- **压缩炸弹与超大图防护**：解码前校验像素数上限，超限拒绝而非硬撑；压缩包解压设层数与总量上限。
- **SVG/可执行内容拒绝**：SVG 不在白名单（内嵌脚本风险），任何可执行扩展名直接拒绝。
- **路径穿越防护**：存储键一律 UUID（ADR-005），存储层拒绝 `..` 与绝对路径，危险字符白名单化。
- **Content-Disposition**：下载响应 `attachment; filename="安全化名称"`，文件名经规范化，防注入下载头。
- **临时文件清理**：校验/写入失败即清理临时文件与半成品记录，不留残留。
- **并发与重复提交**：SHA-256 唯一约束 + 事务内查重，重复请求返回既有记录（ADR-009）。
- **缩略图异常**：生成失败降级（原图可看、缩略图置空）并记日志，不阻断上传。
- **HEIC 处理**：pillow-heif 注册解码（参考分析 §1.4），HEIC/HEIF 入白名单，缩略图统一输出 webp。
- **敏感缩略图模糊**：`sensitive` 文件缩略图模糊或占位，原图查看需 perm_document_view。
- **敏感操作记审计**：敏感文件的查看/下载/导出/永久删除均写 AuditLog（操作者、对象、IP）。

## 5 认证与会话安全

- **密码存储**：bcrypt/argon2 哈希（Django 密码哈希栈配置 argon2 优先），禁明文、禁弱散列。
- **CSRF**：全程启用 CSRF 保护，上传端点与 JSON 接口一并覆盖。
- **会话超时**：空闲会话过期（SESSION_COOKIE_AGE 可配置），敏感操作要求近期认证。
- **登录失败限制**：按用户名/IP 限流，连续失败锁定或延迟，防爆破。
- **安全 Cookie**：生产强制 `SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE`、`HttpOnly`、`SameSite=Lax`。
- **禁止默认管理员密码**：生产部署检查拒绝空/默认密码，首次登录强制改密（配合 docs/security.md 部署检查项）。

## 6 病毒扫描边界声明

本系统**不内置病毒查杀能力**，也不宣称提供病毒查杀。防护边界为：类型白名单 + 魔数校验 + 大小/像素限制 + 权限控制 + 隔离下载（附件下载而非内联渲染）。下载方应自行对文件做防病毒扫描。此边界写入部署文档，避免使用者误以为上传文件已过杀毒。

## 7 隐私与法律边界

- **敏感数据范围**：客户个人资料、保单信息、病历与理赔文件均属敏感，默认不导出、不外发。
- **部署者合规责任**：数据控制者与处理者是部署者本人，需自行确认所在地区法律法规（如《个人信息保护法》）；本文件**不声称满足任何具体国家或行业合规要求**，不构成合规承诺。
- **默认私有网络**：默认仅私有网络自托管，不默认开放公网端口。
- **Tailscale 不是备份替代**：远程访问通道不等于数据冗余，备份仍需 ADR-011 方案。
- **真实部署前检查单**：改默认密钥与数据库口令、按 §2 矩阵核对普通用户权限、执行一次备份还原演练。
- **外部 AI 默认关闭**：任何外部 AI/云服务默认关闭且不自动外发数据，启用需显式配置并重新评估隐私。

## 相关文档

docs/decisions/ADR-004、ADR-012（权限）；ADR-002/005/006（存储与删除）；docs/data-model.md（敏感字段标注）；docs/testing.md（§26 安全测试范围）。
