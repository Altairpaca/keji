# 客迹 Keji — 最终验收报告（Final Acceptance Report）

> 版本：0.1.0 ｜ 日期：2026-08-07
> 本报告逐项对照初始任务规格的 15 项完成判定（规格 §28），给出验证命令、结果与证据位置。
> 全部页面截图使用虚构演示数据（`seed_demo`），无真实客户信息。

---

## 判定总览

| # | 完成判定 | 结果 | 证据 |
|---|---|---|---|
| 1 | Docker Compose 干净构建启动 | ✅ 通过 | 生产 3 容器 healthy，`docker compose ps` |
| 2 | 空库迁移成功 | ✅ 通过 | prod 首次启动 `migrate --noinput` 38 迁移全部应用 |
| 3 | 创建管理员并登录 | ✅ 通过 | `createsuperuser` + curl 登录 302 |
| 4 | 虚构数据完整演示全流程 | ✅ 通过 | `seed_demo --reset` + Playwright 62 E2E |
| 5 | 手机+桌面真实浏览器测试与截图 | ✅ 通过 | 20 张截图 + Multimodal Looker 桌面 9/9、手机 6/6 PASS |
| 6 | 自动化测试+静态检查+格式检查全绿 | ✅ 通过 | 1169 pytest + ruff + mypy 279 文件零告警 |
| 7 | 权限/上传安全/软删除/恢复/审计测试通过 | ✅ 通过 | 矩阵测试 + 各 app 专项测试 |
| 8 | 备份恢复演练 ≥1 次 | ✅ 通过 | `keji_drill` 库恢复演练（建库→恢复→对比→清理） |
| 9 | 无密钥/真实数据/DB/上传/备份提交 | ✅ 通过 | `git ls-files` 核查仅 `.env.example`/`.gitkeep` |
| 10 | 无占位/TODO/假按钮 | ✅ 通过 | 全模板扫描无用户可见占位（含一处修复） |
| 11 | 文档与命令一致 | ✅ 通过 | README 命令逐一核对 + 文档-命令一致性测试 |
| 12 | Git 工作区干净 | ✅ 通过 | `git status` 空 |
| 13 | final-acceptance-report.md 逐项证据 | ✅ 本文件 | — |
| 14 | 已知限制记录（不降级核心缺失） | ✅ 通过 | README「当前限制」+ CHANGELOG |
| 15 | 可虚构数据试运行 | ✅ 通过 | seed_demo + 全流程 E2E 通过 |

---

## 逐项证据

### 1. Docker Compose 干净构建启动 ✅

生产编排：`docker/prod/compose.yaml`（postgres 17 + web gunicorn 非 root UID 1001 + nginx）。

```bash
docker compose --env-file .env.production -f docker/prod/compose.yaml up -d --build
docker compose --env-file .env.production -f docker/prod/compose.yaml ps
# keji-prod-db     Up (healthy)
# keji-prod-web    Up (healthy)
# keji-prod-nginx  Up (healthy)
curl -s http://127.0.0.1:18080/healthz/   # {"status": "ok"}
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18080/accounts/login/   # 200
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18080/static/css/tailwind.css  # 200
```

演练后已 `down` 清理（保留卷策略见 docs/deployment.md）。

### 2. 空库迁移成功 ✅

```bash
docker compose -f docker/prod/compose.yaml exec web python manage.py showmigrations
# 38 migrations applied（accounts/activities/claims/core/customers/documents/policies/tasks + Django 内置）
```

entrypoint 幂等执行 `migrate --noinput` + `collectstatic --noinput`。开发侧 `manage.py migrate` 对空库同样通过、`makemigrations --check --dry-run` → No changes detected。

### 3. 创建管理员并登录 ✅

```bash
docker compose -f docker/prod/compose.yaml exec -T web env DJANGO_SUPERUSER_PASSWORD='***' \
  python manage.py createsuperuser --noinput --username admin --email admin@example.com
# Superuser created successfully.
# curl 登录：POST /accounts/login/ → 302 → GET / → 200（含工作队列首页）
```

### 4. 虚构数据完整演示全流程 ✅

```bash
make seed   # = manage.py seed_demo --reset
# 输出（节选）：customers 16 / policies 8 / claims 5 / materials 17 / events 16 / communications 14 / tasks 22+ / documents 15 / albums 4 / tags 10 / relations 7
```

Playwright E2E（`npx playwright test tests/e2e/`）覆盖完整旅程：登录 → 客户 CRUD → 事件 → 待办 → 上传 → 保单 → 理赔 → 搜索 → 导出 → 回收站，桌面 + 手机双 project，**62 项全部通过**。

### 5. 手机+桌面真实浏览器测试与截图 ✅

- `docs/screenshots/`：20 张真实运行截图（桌面 14：home/customers/customer-detail/documents/document-viewer/claims/claim-detail/policies/tasks/graph/search/upload/albums/activities；手机 6：home/customers/customer-detail/upload/tasks/claim-materials）。
- Multimodal Looker 视觉审查：桌面 9/9 PASS；手机 6/6 PASS（含一轮修复：移动端客户详情重构为四区块「是谁/下一步做什么/在处理什么/上次发生什么」、空字段折叠、触控 ≥44px、修复 Django 跨行注释渲染问题）。
- Playwright `mobile.spec.ts` 全站扫描断言 390×844 无横向滚动 + 触控 ≥44px，62/62 通过。

### 6. 自动化测试+静态检查+格式检查全绿 ✅

```bash
pytest                 # 1169 collected，全绿（DB_TEST_NAME 隔离测试库）
ruff check .           # All checks passed
ruff format --check .  # 全部已格式化
mypy config apps       # Success: no issues found in 279 source files
python manage.py check # System check identified no issues
```

### 7. 权限/上传安全/软删除/恢复/审计测试通过 ✅

专项测试（均在 1169 套件内）：
- 权限矩阵：`apps/core/tests/test_permission_matrix.py`（全部需登录 URL 匿名 302 断言 + 审计视图 403）+ 每 app `test_views.py` 权限矩阵（403/302/200）。
- 上传安全：`apps/documents/tests/test_security_upload.py`（伪造扩展名/魔数不符/超限/路径穿越/重复提交/中断清理）。
- 软删除/恢复：`apps/documents/tests/test_recycle.py`（三级删除 + 物理文件一致性）、`test_duplicates.py`。
- 审计：`apps/audit/tests/`（记录、敏感字段清洗、失败不阻断、视图权限）。
- 认证安全：`apps/accounts/tests/test_rate_limit.py`（限流）、安全响应头测试。

### 8. 备份恢复演练 ≥1 次 ✅

```bash
manage.py backup
# 20260806_222557/ 下：db.dump(147KB)、media.tar.gz、manifest.json（23 类实体行数）、checksums.txt
# checksums 与重算 sha256 一致

# 恢复演练（disposable 库）：
# 1. CREATE DATABASE keji_drill
# 2. restore_backup --stamp 20260806_222557 --db-name keji_drill
# 3. 对比演练库 counts 与 manifest 一致
# 4. DROP DATABASE keji_drill
```

演练日志记录于 `docs/backup-restore.md`「恢复演练」章节；Makefile `backup`/`restore` 目标与文档命令一致（有文档一致性测试）。

### 9. 无密钥/真实数据/DB/上传/备份提交 ✅

```bash
git ls-files | grep -iE "\.env|media/|backups/|staticfiles|\.dump|\.sql"
# 仅命中：.env.example、docker/prod/.env.production.example、backups/.gitkeep（均为示例/占位，无真实密钥）
```

`.gitignore` 覆盖：`.env*`、`media/`、`backups/*`、`staticfiles/`、`.venv/`、测试产物。上传文件均存 `media/`（未入库）。

### 10. 无占位/TODO/假按钮 ✅

```bash
grep -rn "TODO\|FIXME\|XXX" apps/ --include="*.py" | grep -v test   # 无
grep -rn "即将上线\|将在后续版本显示\|T7.4 填\|T8 填" templates/     # 无用户可见占位
```

验收审查发现并修复 2 处历史占位（policy_detail「保单文件占位」、customer_detail「保单/理赔/待办 将在后续版本显示」）→ 已替换为真实链接；对应占位测试同步更新。全部页面按钮可点击、无假按钮。

### 11. 文档与命令一致 ✅

- `apps/core/tests/test_backup_docs.py`：断言 Makefile backup/restore 目标与 docs/backup-restore.md 命令一致。
- README 快速启动/备份/测试章节命令与 Makefile、管理命令逐一核对可运行。
- 文档索引完整：README / AGENTS / product-requirements / architecture / data-model / reference-analysis / security / deployment / backup-restore / testing / decisions(14 ADR) / CHANGELOG / .env.example / LICENSE。

### 12. Git 工作区干净 ✅

```bash
git status --short   # 空
```

### 13. 本文件（final-acceptance-report.md）✅

当前文件，逐项证据如上；配套 `docs/verification-ledger.md` 为验收审查过程台账。

### 14. 已知限制记录 ✅

README「当前限制与不在范围」+ CHANGELOG「已知限制（非缺陷）」记录：
- 面向单管理员/小团队手写权限位（非企业 RBAC）；无对象级授权。
- 无原生 App（PWA + 响应式）；无 ML 相似图去重；无邮件/短信自动发送。
- 备份不含增量与加密（保留策略 + 校验和已具备）。
- 全局搜索以 pg_trgm/icontains 为主，长文本相关度排序需 zhparser（扩展点已留）。
- `check --deploy` 仅 2 个 low 级警告（HSTS/SSL 重定向由 nginx 反代处理，Tailscale 私网场景已声明）。
- HEIC 依赖 pillow-heif 可用性，不可用时显示类型图标（原文件保留）。

以上均为**明确记录的非缺陷限制**，不属于核心功能缺失。

### 15. 可虚构数据试运行 ✅

`seed_demo --reset` 一键生成完整演示数据；全流程 Playwright E2E（62 项）在真实浏览器中跑通；20 张截图证实各页面可实际使用。系统已达到个人/小团队以虚构数据试运行的程度。

---

## 已知遗留与后续建议（非阻断）

1. 截图仅 20 张覆盖核心页面（规格列举的 10 个场景全部覆盖：桌面 首页/客户列表/客户详情/文件查看/理赔详情 + 手机 首页/客户详情/上传流程/待办/理赔材料清单）。
2. Looker 视觉审查结论记录在本报告与编排会话，仓库未单独存放 JSON 报告。
3. 备份演练日志未入库（预期：`backups/` 不入库），恢复步骤见 docs/backup-restore.md。
4. 建议后续接入 CI（`.github/workflows/ci.yml` 已配置，含 ruff/mypy/pytest/postgres 服务）在远程仓库启用。

---

*本报告由自动化测试、真实浏览器 E2E、生产 Docker 演练与视觉审查证据构成，无人工编造结果。*
