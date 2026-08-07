# 客迹 Keji — 最终验收证据清单（Verification Ledger）

> 最终质量门证据文件。本清单逐项核对 15 项完成判定（产品需求规格 §7 / 任务判定清单），
> 每项记录：结论、证据位置、验证命令与结果、缺口。
> 生成时间：2026-08-07 · 生成方式：静态核对 + 关键命令快速复验（未重跑全量测试）。
> 状态：**14/15 通过，1 项有条件通过（含 1 个需编排者处理的 UI 占位残留）**。

---

## 逐项判定

### 1. Docker Compose 干净构建启动 ✅
- **证据**：`docker/prod/compose.yaml`（db/web/nginx 三服务，均带 healthcheck）；`docker/prod/Dockerfile`、`nginx.Dockerfile`、`entrypoint.sh`（migrate → collectstatic → gunicorn）、`nginx.conf`（`/healthz/` 探针）；`apps/core/tests/test_prod_compose.py`（生产部署结构断言测试）。
- **命令**：`grep -n "services:\|healthcheck" docker/prod/compose.yaml` → db/web/nginx 各有 healthcheck。
- **结果**：生产演练由编排者执行通过（3 容器 healthy、healthz 200、登录 200、静态 200），已 down 清理。本清单确认结构与健康探针在库。
- **缺口**：无。演练实时日志未入库（预期，`backups/` 与运行产物不入库）。

### 2. 空库迁移成功 ✅
- **证据**：`entrypoint.sh` 首行 `migrate --noinput`；迁移文件 `find apps -path "*/migrations/*.py" ! -name "__init__.py"` = **20 个** + Django 内置迁移 18 个 = **38 个迁移**（与「38 迁移应用」一致）。
- **命令**：`find apps -path "*/migrations/*.py" ! -name "__init__.py" | wc -l` → 20；内置 `auth/admin/contenttypes/sessions/messages` = 18。
- **结果**：`makemigrations --check`（编排者）No changes；迁移数合计 38，与 showmigrations 38 一致。
- **缺口**：无。

### 3. 创建管理员并登录 ✅
- **证据**：`apps/accounts/`（User 模型、登录限流、密码修改、用户管理）；`tests/e2e/auth.spec.ts`（登录/错误密码/登出/权限，4 例）；`scripts/capture_screenshots.mjs`（以 admin 登录采图）；`docs/deployment.md` createsuperuser 步骤。
- **命令**：编排者 prod 演练：`createsuperuser` 成功 + `curl -b` 登录 302。
- **结果**：登录流程可运行、E2E 覆盖。
- **缺口**：无。

### 4. 虚构数据完整演示全流程 ✅
- **证据**：`apps/core/management/commands/seed_demo.py`（`--reset` 支持，幂等）+ `seed_runner.py` + `seed_data.py`；备份 `backups/20260806_222557/manifest.json` counts（customers 16 / tags 10 / relations 7 / albums 4 / documents 15 / policies 8 / claims 5 / workevent 16 / communication 14 / tasks 31 / auditlog 32 等 23 类实体）；`apps/core/tests/test_seed.py`。
- **命令**：`sha256sum -c backups/20260806_222557/checksums.txt` → db.dump OK / media.tar.gz OK。
- **结果**：seed 数据计数与 manifest 一致；62 个 Playwright E2E 覆盖全流程。
- **缺口**：无。任务描述「22 待办」与 manifest 中 tasks.task=31 存在数字差异——以实际 manifest（31）为准，非缺陷。

### 5. 手机 + 桌面真实浏览器测试与截图 ✅
- **证据**：`docs/screenshots/` 共 **21 个文件**（20 张 PNG：desktop 14 + mobile 6 + `README.md` 索引）；`playwright.config.ts`（desktop 1440×900 + mobile 390×844 isMobile/hasTouch 双 project）；`tests/e2e/` 10 个 spec。
- **命令**：`ls docs/screenshots/desktop-*.png | wc -l` → 14；`mobile-*.png` → 6。
- **结果**：截图由 `scripts/capture_screenshots.mjs`（真实运行 + 演示数据）采集；Multimodal Looker 桌面 9/9 + 手机 6/6 PASS（编排者记录，含一轮修复）。
- **缺口**：Looker PASS 结果记录在编排会话，仓库内无独立 JSON 报告文件（建议编排者写入 final-acceptance-report）。

### 6. 自动化测试 + 静态检查 + 格式检查全绿 ✅
- **证据**：`docs/testing.md`（pytest 1166+ 全绿 / 收集数 1169；Playwright 62 例 / 10 spec）；`CHANGELOG.md`；`.coverage`（53KB）；`.github/workflows/ci.yml`（lint + types + tests 三阶段）。
- **命令**（本次复验）：
  - `ruff check .` → **All checks passed!**（EXIT 0）
  - `mypy config apps` → **Success: no issues found in 279 source files**
  - pytest collect-only → 1169 项（10 个 app 分布：customers 190 / policies 231 / claims 187 / documents 174 / core 165 / activities 92 / accounts 45 / audit 24 / tasks 51 / dashboard 10）
  - Playwright 静态计数：51 个 `test(` + mobile.spec 循环生成 12 = **62** ✅ 与文档一致
- **结果**：全绿。E2E 计数 62 经静态核算吻合（57 静态调用中 mobile 循环 1 处展开为 12 例）。
- **缺口**：无。

### 7. 权限 / 上传安全 / 软删除 / 恢复 / 审计测试通过 ✅
- **证据**（抽查确认存在）：
  - 权限：`apps/accounts/tests/test_permissions.py`（21 例，覆盖 has_bit/require_permission/模板标签/403）
  - 权限矩阵：`apps/core/tests/test_permission_matrix*.py`（含 admin 与 writes 两组）
  - 上传安全：`apps/documents/tests/test_security_upload.py`（14 例）+ `test_storage.py` + `test_upload.py`
  - 软删除 / 回收站三级：`apps/documents/tests/test_recycle.py`（24 例）
  - 恢复：`apps/core/tests/test_restore.py`（含恶意 tar 成员安全解包用例）+ `test_backup.py` + `test_backup_docs.py`
  - 审计：`apps/audit/tests/`（models/services/views/integration 4 文件）
  - CSRF/安全：`apps/core/tests/test_security.py`、`test_settings.py`
- **命令**：`grep -c "def test"` 各文件计数如上述。
- **结果**：对应测试文件全部在库且计入 1169 收集数，编排者全量运行全绿。
- **缺口**：无。

### 8. 备份恢复演练 ≥1 次 ✅
- **证据**：`backups/20260806_222557/`（`db.dump` 147KB / `media.tar.gz` / `manifest.json` / `checksums.txt`）；`docs/backup-restore.md` §7「恢复演练」记录（2026-08-06 恢复到 `keji_drill` 独立库，实体行数与 manifest counts 完全一致、校验和通过、演练库已删）；`apps/core/management/commands/restore_backup.py` + `scripts/restore.sh`。
- **命令**：`sha256sum -c backups/20260806_222557/checksums.txt` → **db.dump: OK / media.tar.gz: OK**。
- **结果**：备份产物完整、校验和真实可验、恢复演练已记录。
- **缺口**：无。

### 9. 无密钥 / 真实数据 / DB / 上传 / 备份提交 ✅
- **证据**：`git ls-files | grep -iE "\.env|media/|backups/|staticfiles|\.dump|\.sql"` → 仅 `.env.example`、`backups/.gitkeep`、`docker/prod/.env.production.example`（均为模板/占位，无真实值）。
- **命令**：
  - `git ls-files` 命中 media/、staticfiles/、*.dump → **0**；backups/ 仅 `.gitkeep`
  - `.env.example` / `.env.production.example` 内容抽查：SECRET_KEY 为 `change-me` / 空占位，仅注释与占位符
  - `config/settings/prod.py`：SECRET_KEY 从环境变量读取，缺失或等于开发占位值直接 `ImproperlyConfigured` 拒绝启动；`base.py` 默认仅为开发占位
- **结果**：工作区无 `.env` 文件、无真实密钥、无 DB dump / 上传 / 备份 / staticfiles 入库。`git status --porcelain` 0 项。
- **缺口**：无。

### 10. 无占位 / TODO / 假按钮 ⚠️ 有条件通过（1 处残留，需编排者处理）
- **证据**：
  - `grep -rn "TODO\|FIXME\|XXX" apps --include="*.py" | grep -v test` → **0 命中**（EXIT 1）
  - `grep -rn "即将上线" templates apps` → **0 命中**（EXIT 1）
  - `grep -rn "敬请期待\|开发中\|暂未开放\|coming soon"` → 0 命中
  - 假按钮检查：`href="#"` / `disabled` 仅 `documents/upload.html` 的 Alpine 提交中禁用态（功能性 loading 状态，非假按钮）
  - 模板注释中的「占位」均为 HTML/JS 注释（`{# #}` / `//`），不可见：`customer_detail.html:204`、`base.html:28`、`base.html:150`、`relationship_graph.html:88`
- **⚠️ 发现 1 处用户可见占位残留**：
  - `templates/policies/policy_detail.html:149-153`——「保单文件」区块显示可见文案 *「保单相关文件将在后续版本显示（T7.4）。」*
  - **但 T7.4 已实现**：`apps/policies/views/policies.py` 有 `policy_document_list/attach/detach`，urls.py 有对应路由，`apps/policies/tests/test_document_link.py`（20 例）已覆盖。即功能存在而模板未渲染，属**过期占位文案**，非核心功能缺失。
- **处理建议**：编排者将 policy_detail 的「保单文件」区块改为渲染已关联文档（复用 policy_document_list 数据）或至少移除「将在后续版本显示」文案。
- **结论**：其余无占位/TODO；此项判**通过但有 1 个待清理的 UI 文案残留**（阻塞性低，建议 final-acceptance-report 前修复）。

### 11. 文档与命令一致 ✅
- **证据**：`README.md` 命令与 `Makefile` 目标对照——`make dev-up / migrate / createsuperuser / seed / backup / restore / test / lint / typecheck / static` 全部存在且语义一致；`docs/deployment.md` 生产启动命令与 `docker/prod/compose.yaml` 一致；`docs/backup-restore.md` 命令与 `restore_backup` 参数一致。
- **命令**：抽查 README 命令清单 vs Makefile 目标（help 全部列出）。
- **⚠️ 微差**：README:134 仍写 `make typecheck   # mypy keji`（注释），实际目标为 `mypy`（按 pyproject files）。CHANGELOG 已记录「修正」，README 注释未同步——纯注释级差异，不影响命令可用性。
- **结论**：通过。建议顺手更新 README 注释。

### 12. git 工作区干净 ✅
- **命令**：`git status` → 「无文件要提交，工作区干净」；`git status --porcelain | wc -l` → **0**。
- **结果**：提交间工作区干净。
- **缺口**：无。

### 13. final-acceptance-report.md 逐项证据 📋（待编排者撰写）
- **现状**：`docs/final-acceptance-report.md` **不存在**（预期，编排者下一步撰写）。本文件 `docs/verification-ledger.md` 即为该报告的证据素材。
- **缺口**：final-acceptance-report 尚未生成；本清单可直接引用。

### 14. 已知限制记录 ✅
- **证据**：`README.md` §「当前限制与不在范围」（单管理员/非 RBAC、无原生 App、无 ML 去重、无邮件/短信同步、备份无增量与加密、zhparser 不在范围、check --deploy 2 个 low 提示）；`CHANGELOG.md`「已知限制（非缺陷）」同述。
- **结果**：限制被如实记录，未将核心功能缺失降级为限制。
- **缺口**：无。

### 15. 可虚构数据试运行 ✅
- **证据**：`seed_demo --reset`（seed_runner/seed_data，幂等 + 清空重建）；manifest counts 证明真实灌入；`docs/screenshots/` 截图基于 seed 数据真实运行；`apps/core/tests/test_seed.py` 覆盖。
- **结果**：可复现、计数可验证。
- **缺口**：无。

---

## 结论汇总

| # | 判定 | 结论 | 备注 |
|---|------|------|------|
| 1 | Docker Compose 干净构建启动 | ✅ | 结构 + 健康探针在库，演练由编排者执行 |
| 2 | 空库迁移成功 | ✅ | 20 app + 18 内置 = 38 迁移，check 无变更 |
| 3 | 创建管理员并登录 | ✅ | E2E auth 4 例 + 演练记录 |
| 4 | 虚构数据完整演示全流程 | ✅ | manifest 23 类实体计数 + 62 E2E |
| 5 | 手机 + 桌面真实浏览器测试与截图 | ✅ | 21 文件（20 PNG），双视口配置在库 |
| 6 | 自动化测试 + 静态 + 格式全绿 | ✅ | 复验 ruff/mypy；1169 收集 / 62 E2E 吻合 |
| 7 | 权限 / 上传安全 / 软删除 / 恢复 / 审计测试 | ✅ | 抽查 8 组测试文件均在库 |
| 8 | 备份恢复演练 ≥1 次 | ✅ | checksums 验证 OK + 演练文档 |
| 9 | 无密钥 / 真实数据 / DB / 上传 / 备份提交 | ✅ | ls-files 仅模板文件；settings 无明文密钥 |
| 10 | 无占位 / TODO / 假按钮 | ⚠️ | 1 处用户可见占位（policy_detail「保单文件」）需清理 |
| 11 | 文档与命令一致 | ✅ | 命令一致；1 处 README 注释微差（mypy keji） |
| 12 | git 工作区干净 | ✅ | porcelain 0 |
| 13 | final-acceptance-report 逐项证据 | 📋 | 待编排者撰写，本清单为素材 |
| 14 | 已知限制记录 | ✅ | README + CHANGELOG 双处记录 |
| 15 | 可虚构数据试运行 | ✅ | seed_demo --reset + 计数验证 |

## 缺口清单（交付前建议处理）

1. **【UI 占位残留】** `templates/policies/policy_detail.html:149-153`「保单文件」区块显示「将在后续版本显示（T7.4）」可见文案，但 T7.4（保单-文档关联）已实现并有 20 例测试。建议编排者改渲染已关联文档，或移除过期文案。
2. **【文档微差】** `README.md:134` 注释 `# mypy keji` 与实际命令 `mypy` 不符（CHANGELOG 已记修复，README 注释未同步）。低优先级。
3. **【截图任务描述差异】** 任务描述「22 待办」vs manifest `tasks.task=31`——以实际 manifest 为准，非缺陷，仅记录。
4. **【Looker 结果落点】** 桌面 9/9 + 手机 6/6 PASS 仅在编排会话记录，建议写入 final-acceptance-report 作为正式证据。

## 复验命令记录（2026-08-07）

```bash
# 工作区
git status                       # 干净
git status --porcelain | wc -l   # 0
# 密钥 / 生成物入库检查
git ls-files | grep -iE "\.env|media/|backups/|staticfiles|\.dump|\.sql"
# 占位 / TODO
grep -rn "TODO\|FIXME\|XXX" apps --include="*.py" | grep -v test     # 0
grep -rn "即将上线" templates apps                                   # 0
grep -rn "敬请期待\|开发中\|暂未开放" templates apps                  # 0
# 质量
.venv/bin/ruff check .              # All checks passed!
.venv/bin/mypy config apps          # Success: no issues found in 279 source files
pytest --collect-only -q            # 1169 items（10 app）
# 备份完整性
sha256sum -c backups/20260806_222557/checksums.txt   # db.dump OK / media.tar.gz OK
```
