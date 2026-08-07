# 生产部署指南（deployment）

> 对应规格 §23（部署）、§24（文档与命令一致）。编排文件：`docker/prod/compose.yaml`，
> 环境变量模板：`docker/prod/.env.production.example`。备份 / 恢复见 `docs/backup-restore.md`。

本文档面向部署者。默认部署形态是「本机可达、可选接入 Tailscale 内网」：nginx 只监听
`127.0.0.1:18080`，不主动暴露到公网。是否开放公网、如何加 HTTPS，由部署者自行决定。

---

## 1. 前置条件

- Linux 服务器（或 NAS / VPS），已安装 Docker 与 Docker Compose V2
- `git` 已拉取本仓库到服务器（如 `/srv/keji`）
- 一个访问入口，任选其一：
  - Tailscale 网络内的节点（推荐，下文 §4）
  - 内网 / 局域网 IP（如 `192.168.x.x`）
  - 一个公网域名（可选，需要自行处理 HTTPS）
- 2GB 以上可用内存、约 10GB 磁盘（DB + 媒体文件随使用增长）

---

## 2. 生产部署步骤

### 2.1 准备环境变量

```bash
cp docker/prod/.env.production.example .env.production
```

编辑 `.env.production`，必填两项：

```bash
# 生成方式：
#   python -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=<随机强密钥>

# DB 口令：强随机，禁止 keji/keji。需与下方 POSTGRES_PASSWORD 保持一致。
DB_PASSWORD=<强口令>
POSTGRES_PASSWORD=<强口令>
```

生产启动会强制检查这两项，缺失或为空直接拒绝启动（compose 的 `:?` 语法）。
建议同时把 `ADMIN_URL` 改成非常规前缀（如 `admin-x7k9z2`），并把 `ALLOWED_HOSTS`
改为你的域名或 Tailscale IP。

`.env.production` 已在 `.gitignore` 中，永远不会被提交。

### 2.2 构建并启动

```bash
docker compose --env-file .env.production -f docker/prod/compose.yaml up -d --build
```

启动过程：`db` 容器先就绪（healthcheck 通过）→ `web` 容器自动执行
`migrate --noinput` 与 `collectstatic --noinput`，然后启动 Gunicorn
（默认 3 个 worker，可用 `WORKERS` 覆盖）→ `nginx` 就绪对外服务。

三个容器都以非 root 运行（web 为 UID 1001），数据落在命名卷
`prod-db-data` / `prod-media` / `prod-static` / `prod-backups`，`down` 不会丢失。

### 2.3 创建超级管理员

```bash
docker compose -f docker/prod/compose.yaml exec web \
  env DJANGO_SUPERUSER_PASSWORD=<强口令> python manage.py createsuperuser --noinput \
  --username admin --email admin@example.com
```

### 2.4 验证

```bash
# 健康检查端点返回 200
curl -i http://127.0.0.1:18080/healthz/

# 登录页面可访问
curl -I http://127.0.0.1:18080/login/
```

浏览器打开 `http://127.0.0.1:18080/`（Tailscale 接入后为 `http://100.x.y.z:18080/`），
用刚创建的管理员登录。后台入口按 `ADMIN_URL` 配置（默认 `http://127.0.0.1:18080/admin/`）。

### 2.5 停止与卸载

```bash
docker compose -f docker/prod/compose.yaml down        # 停止，保留数据卷
docker compose -f docker/prod/compose.yaml down -v     # 停止并删除数据卷（不可逆，先备份）
```

---

## 3. 端口策略

- nginx 默认只绑定宿主 `127.0.0.1:18080`，仅本机可达。这是刻意的默认值：数据库
  与业务端口一律不对外，`web` 容器完全不映射端口。
- 需要局域网访问时，把 `docker/prod/compose.yaml` 中的端口映射改为 `0.0.0.0:18080:80`，
  或交由反向代理转发。**公网暴露是部署者自己的决定**，一旦绑定 `0.0.0.0` 就必须先做好
  HTTPS 与访问控制（见 §5）。
- 想换端口直接改映射左侧：如 `127.0.0.1:18081:80`。

---

## 4. Tailscale 接入（推荐）

Tailscale 解决「如何从外面安全地访问内网服务」，不走公网端口映射，也不需要在
nginx 前加复杂反代。步骤：

```bash
# 在服务器上安装并登录 Tailscale（一次性）
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

登录后服务器会获得一个 `100.x.y.z` 的 Tailscale IP。此后：

- 从任意已加入同一 tailnet 的设备访问：`http://100.x.y.z:18080/`
- 手机安装 Tailscale 客户端后，同样可以直接打开上面地址，配合 PWA 可安装到主屏

注意事项：

- **ACL 由部署者自管**。客迹不修改、不读取你的 Tailscale ACL；默认 tailnet 内
  所有节点互相可达，如需限制到特定账号 / 设备，请在 Tailscale 控制台配置 ACL。
- Tailscale 提供的是访问链路，不是备份。数据备份仍必须做（见
  `docs/backup-restore.md`）。
- `100.x.y.z` 是 `ALLOWED_HOSTS` 的一个候选值；用 IP 访问时把它加进
  `.env.production` 的 `ALLOWED_HOSTS` 即可。

---

## 5. HTTPS（可选）

默认 compose 里 nginx 监听的是 HTTP。HTTPS 有多种接法，本文不写死证书与域名方案，
按你的环境选择：

- **Tailscale HTTPS**：tailnet 开启 HTTPS（MagicDNS 后）后，可
  `sudo tailscale cert <machine>.<tailnet>.ts.net` 取得证书，再在 nginx 或前置
  反代上挂载。适合「仅 tailnet 内访问」。
- **上游反向代理**：nginx 后面再接一层 Caddy / Traefik / Nginx Proxy Manager，
  由这层做 TLS 终止并转发到 `127.0.0.1:18080`。这是最常见的家用 NAS 方案，
  证书由反代自动管理（如 Caddy 的自动 HTTPS）。
- **直连公网**：若必须对公网提供 HTTPS，同样由前置反代或自签 / Let's Encrypt
  证书承担 TLS 终止，客迹的 nginx 继续只做内网 HTTP 转发。

启用 HTTPS 后：

- 确认 `.env.production` 中 `SESSION_COOKIE_SECURE=true` 与 `CSRF_COOKIE_SECURE=true`
  （模板默认已是 true）。
- `ALLOWED_HOSTS` 加上你的域名。
- `python manage.py check --deploy` 剩余的 2 个 low 级提示（HTTPS 相关）随之清零。

---

## 6. 升级 / 备份 / 恢复

- **备份**：`docker compose -f docker/prod/compose.yaml exec web python manage.py backup`
  （或开发环境用 `make backup`）。产物结构、保留策略、恢复参数
  （`restore_backup --stamp / --latest / --db-name / --yes`）详见
  `docs/backup-restore.md`。
- **升级**：拉取新代码 → `docker compose --env-file .env.production \
  -f docker/prod/compose.yaml up -d --build`。启动时自动执行 `migrate --noinput`
  ​与 `collectstatic --noinput`，幂等可重入。升级前先做一次备份。
- **恢复**：见 `docs/backup-restore.md` 的「恢复」章节，恢复操作会覆盖现有数据，
  请确认后再执行。

---

## 7. 常见问题

**启动报错 `required variable is missing a value: POSTGRES_PASSWORD`**

`.env.production` 没填或字段为空。确认已按 §2.1 填写并 `--env-file .env.production`。

**`SECRET_KEY` 为空导致启动失败**

生产强制校验。用 `python -c "import secrets; print(secrets.token_urlsafe(64))"`
生成后填入。

**从宿主机 curl 不到 `http://127.0.0.1:18080/healthz/`**

先 `docker compose -f docker/prod/compose.yaml ps` 看三容器是否都 healthy；
`docker compose -f docker/prod/compose.yaml logs -f web` 看 web 是否完成迁移并起
gunicorn。nginx 依赖 web healthy 后才对外服务。

**`ALLOWED_HOSTS` 报错 `Invalid HTTP_HOST header`**

用哪个地址访问，就把哪个加进 `.env.production` 的 `ALLOWED_HOSTS`（域名 / Tailscale IP /
局域网 IP），然后 `up -d` 重建 web 容器生效。

**升级后页面样式丢失（静态文件 404）**

正常流程会自动 collectstatic；若手动改过 static，重跑
`docker compose -f docker/prod/compose.yaml exec web python manage.py collectstatic --noinput`。

**想改端口 / 对外开放**

见 §3 端口策略；对外开放前务必先读 §5 HTTPS 一节。

---

## 相关文档

- `docs/backup-restore.md`：备份 / 恢复详细说明与恢复演练记录
- `docs/security.md`：安全设计（权限位、上传边界、审计）
- `README.md`：快速启动（开发环境）与功能总览
