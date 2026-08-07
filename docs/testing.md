# 测试策略与命令（testing）

> 状态：已执行。本文件给出实际可运行的命令与当前真实结果，与 AGENTS.md 的 TDD 约定、
> docs/security.md（安全测试范围）、docs/data-model.md（校验节）配套。
> 命令与 Makefile 逐字一致；后端命令在 web 容器内执行（`make test` 等价于
> `docker compose exec web pytest`），E2E 命令在宿主机执行（需 node）。

## 1 实际命令与当前结果

### 后端单元 / 集成测试（pytest）

```bash
# 全量（等价于 make test）
docker compose -f docker/dev/compose.yaml exec web pytest

# 单个 app（如 customers）
docker compose -f docker/dev/compose.yaml exec web pytest apps/customers

# 单个测试函数
docker compose -f docker/dev/compose.yaml exec web pytest apps/customers/tests/test_services.py::test_merge_duplicates
```

当前结果：**1166+ 个用例全绿**（pytest 收集数为 1169）。用例分布在 10 个 app 的
`tests/` 目录，覆盖模型方法、服务层、视图、表单、安全、CSV 导入导出、备份恢复一致性等。

### 覆盖率

```bash
# 本机 venv（需已安装 pytest-cov）：
pytest --cov
coverage report      # 查看上次跑出的覆盖率汇总
coverage html        # 生成 HTML 报告（htmlcov/）

# 只看单个 app：
pytest apps/audit --cov=apps.audit
```

当前结果：行覆盖率 **97%**（13438 语句，缺失 394）。覆盖率作为趋势指标，
新代码必须带测试；红线只在显著回退时阻塞。

### 代码质量（ruff / mypy）

```bash
docker compose -f docker/dev/compose.yaml exec web ruff check .
docker compose -f docker/dev/compose.yaml exec web ruff format --check .
docker compose -f docker/dev/compose.yaml exec web mypy
```

（等价于 `make lint` / `make typecheck`。）

当前结果：ruff **All checks passed**（276 个文件格式正确）；mypy **Success:
no issues found in 279 source files**（检查范围见 pyproject.toml 的 `files`）。
两者零告警才能提交（AGENTS.md：禁止 `# type: ignore` 与 `cast()` 绕行）。

### Playwright E2E（浏览器自动化）

E2E 用 Playwright 独立于 pytest 运行，spec 在 `tests/e2e/`，在宿主机执行（需
node 与 `npm install` 装好的依赖）：

```bash
npx playwright test                     # 全量（desktop + mobile 两个 project）
npx playwright test --project=desktop   # 桌面视口（1440×900）
npx playwright test --project=mobile    # 手机视口（390×844，触控模式）
npx playwright test mobile.spec.ts      # 单文件
```

当前结果：**62 个用例 / 10 个 spec 文件**。E2E 面向 `http://127.0.0.1:8000`
（开发 web 容器），覆盖客户 CRUD、关系图、回收站、理赔材料流程、全局搜索、
上传、PWA 与手机端全站扫描（无横向滚动 + 触控目标 ≥44px）。失败时自动截图到
`test-results/`。

### 生产安全检查

```bash
SECRET_KEY=<生成的真实密钥> python manage.py check --deploy --settings config.settings.prod
```

当前结果：生产配置（prod）报告 **2 个 low 级提示**，均为 HTTPS 相关：
`security.W004`（未设 HSTS）与 `security.W008`（未设 SSL 重定向）。
纯 HTTP 内网部署（Tailscale）下为预期行为；接入 HTTPS 后按
`docs/deployment.md` §5 补上即可清零。开发配置（dev）还会额外报告
DEBUG / SECRET_KEY / Secure Cookie 等提示，属预期，不代表生产状态。

## 2 测试原则

- 每个 app 的测试独立放在 `apps/<name>/tests/`，不跨 app 耦合（AGENTS.md）。
- 分层测试：模型方法、服务层函数、视图、表单、安全各归其位。
- 数据库读写经 services 层进出，测试随之优先测服务层，视图只测编排与权限。
- 演示数据（seed_demo）不进入自动化测试，测试用独立 fixtures。

## 3 TDD：RED → GREEN → REFACTOR

- 规则：**先写失败测试**，确认 RED（断言失败原因明确），再最小实现到 GREEN，最后清理。
- 每笔改动先补测试再动实现；涉及模型改动的，先写模型 / 服务测试再生成迁移。
- 禁止「先实现后补测试」，也禁止「实现和测试一起写完直接跑绿」（RED 从未发生）。
- 提交前该 app 测试全绿，且不能以跳过 / 修改既有测试来换绿。

## 4 目录布局

```
apps/<name>/tests/
├── __init__.py
├── conftest.py          # 本 app 专属 fixtures
├── test_models.py       # 模型方法、状态流转、软删除、约束
├── test_views.py        # 页面渲染、上下文、HTMX 片段、重定向
├── test_forms.py        # 表单校验、字段清洗、错误信息
├── test_services.py     # 服务层函数与事务边界
├── test_security.py     # 权限位 403、未授权对象访问、敏感操作
└── test_api.py          # JSON 端点（关系图、上传等）

tests/e2e/               # Playwright spec（desktop + mobile 双视口）
├── global-setup.ts      # 登录态准备（tests/e2e/.auth/admin.json）
├── customer.spec.ts     # 客户 CRUD、关系图、回收站
├── claim.spec.ts        # 理赔材料流程
├── policy.spec.ts       # 保单流程
├── upload.spec.ts       # 多选上传
├── search.spec.ts       # 全局搜索
├── task.spec.ts         # 待办 / 快速跟进
├── activity.spec.ts     # 事件与时间线
├── auth.spec.ts         # 登录 / 权限
├── desktop.spec.ts      # 桌面布局
└── mobile.spec.ts       # 手机视口全站扫描
```

- 命名：测试函数 `test_<行为描述>`，一个函数只断言一件事。
- 全局 fixtures 放项目级 `conftest.py`（登录用户、角色矩阵、存储后端 stub）。
- 上传 / 文件相关测试用临时媒体目录，不污染真实 `media/`。

## 5 Fixtures 策略

- **角色 fixture**：`admin_user`、`normal_user_all_perms`、`normal_user_minimal`
  （零权限）三种基础角色，安全测试复用。
- **数据 fixture**：客户 / 保单 / 理赔 / 文件的对象工厂（factory 函数或 fixture
  级联），对象级联组装，不在模块内裸造对象。
- **存储 fixture**：`StorageBackend` 换成临时目录实现，测试断言文件落在预期存储键。
- **解耦原则**：fixture 只造被测对象所需的最小数据；demo 数据与测试数据彻底分开。
- 时间相关测试用冻结时间，避免「待办逾期」类测试随日期漂移。

## 6 覆盖范围（现状）

已覆盖：认证与登录限流、11 个权限位的 403 断言、客户 CRUD / 软删除 / 合并、
关系 7 类型与关系图 JSON 权限过滤、事件 / 沟通 / 时间线聚合、上传去重与下载权限、
路径穿越与危险文件名拒绝、上传边界（超限 / 类型 / 魔数 / SVG / 压缩炸弹）、
保单状态流转与状态历史、理赔材料状态机全路径与 ZIP 导出权限、待办逾期与首页队列、
中文搜索子串命中与跨模型排序、CSV 导入导出、审计落库、备份 manifest / 校验和 /
还原核对记录数、页面 200 与模板上下文、未授权对象 404/403、CSRF 拒绝、
空库迁移。

## 7 质量门禁

```bash
docker compose -f docker/dev/compose.yaml exec web pytest
docker compose -f docker/dev/compose.yaml exec web ruff check .
docker compose -f docker/dev/compose.yaml exec web ruff format --check .
docker compose -f docker/dev/compose.yaml exec web mypy
npx playwright test    # 宿主机
```

提交前以上全部必须通过。CI 与本地同一套命令。

## 相关文档

AGENTS.md（TDD 与质量约定）、docs/security.md（安全测试范围）、
docs/data-model.md（校验节）、docs/deployment.md（`check --deploy` 生产上下文）、
ADR-013（演示数据与测试解耦）。
