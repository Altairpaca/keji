# Changelog

本项目所有重要变更均记录在此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 里程碑：W0 — 初始化（进行中）

#### 新增

- 初始化仓库骨架：`.gitignore`、AGPL-3.0-only 许可证、`docs/`、`scripts/`、`backups/` 目录
- 完成参考分析 `docs/reference-analysis.md`（Immich 媒体管线、关系图库选型、Django 中文全文搜索、Twenty / django-crm / Paperless-ngx 的借鉴与拒绝结论）
- 生成项目骨架文档：`.env.example`、`README.md`、`AGENTS.md`、`CHANGELOG.md`、`Makefile`
- 环境变量模板 `.env.example`（全部占位符，无真实密钥）

#### 规划中（未完成，后续里程碑）

- 开发环境编排 `docker/dev/compose.yaml` 与相关容器
- 生产部署指南 `docs/deployment.md`
- 架构决策记录（ADR，`docs/decisions/`）
- Django 5.2 项目与业务应用初始化（TDD）
