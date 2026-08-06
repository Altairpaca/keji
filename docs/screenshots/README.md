# 截图

真实运行页面截图，全部使用虚构演示数据（`seed_demo` 灌入），不包含任何真实客户信息。

- 采集方式：`node scripts/capture_screenshots.mjs`（Playwright，登录 admin 后逐页导航、等待渲染完成后截图）
- 环境：开发容器（http://127.0.0.1:8000），Django 5.2 + PostgreSQL 17
- 桌面端：Chromium 1440×900；手机端：Chromium 390×844（isMobile + hasTouch）

## 桌面端（1440×900）

| 文件 | 页面 | 说明 |
|---|---|---|
| `desktop-home.png` | `/` | 首页工作队列：统计卡片（客户总数/本月新增/理赔处理中/逾期任务等）+ 今日任务分组 |
| `desktop-customers.png` | `/customers/` | 客户列表 |
| `desktop-customer-detail.png` | `/customers/<uuid>/` | 客户详情：基本信息、事件时间线、关系卡、标签 |
| `desktop-documents.png` | `/documents/` | 文件/相册列表（缩略图网格） |
| `desktop-document-viewer.png` | `/documents/<uuid>/` | 文件详情：元数据（类型/SHA-256/大小/敏感级别）+ 下载原文件 |
| `desktop-upload.png` | `/documents/upload/` | 上传页（拍照/相册入口 + 预览区） |
| `desktop-albums.png` | `/documents/albums/` | 相册管理 |
| `desktop-policies.png` | `/policies/` | 保单列表（险种/保额/缴费/期限） |
| `desktop-claims.png` | `/claims/` | 理赔列表 |
| `desktop-claim-detail.png` | `/claims/<uuid>/` | 理赔详情：材料清单逐项核对 |
| `desktop-tasks.png` | `/tasks/` | 待办跟进列表（到期提醒） |
| `desktop-activities.png` | `/activities/` | 工作事件时间线 |
| `desktop-search.png` | `/search/?q=演示` | 全局搜索（pg_trgm，中文）：客户/保单/理赔结果 |
| `desktop-graph.png` | `/customers/<uuid>/graph-page/` | 客户关系图（vis-network：节点+连线，单击展开一层） |

## 手机端（390×844）

| 文件 | 页面 | 说明 |
|---|---|---|
| `mobile-home.png` | `/` | 首页 + 底部导航（首页/客户/上传/待办/我的） |
| `mobile-customers.png` | `/customers/` | 客户列表（单列卡片） |
| `mobile-customer-detail.png` | `/customers/<uuid>/` | 客户详情（移动端布局） |
| `mobile-upload.png` | `/documents/upload/` | 拍照 / 从相册选择入口 + 预览区 |
| `mobile-tasks.png` | `/tasks/` | 待办列表（移动端） |
| `mobile-claim-materials.png` | `/claims/<uuid>/` | 理赔材料清单（缺少 6 份材料逐项列出） |

> 截图中的客户、保单、理赔、文档均为 `seed_demo` 生成的虚构演示数据（如「演示-张伟明」等），仅用于文档展示。
