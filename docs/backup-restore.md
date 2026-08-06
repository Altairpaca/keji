# 备份与恢复（backup-restore）

> 对应规格 §18（备份）、§23（运维文档）、§24（备份恢复一致性），决策见
> `docs/decisions/ADR-011.md`。本文档命令与仓库 `Makefile`、管理命令逐字一致，
> 由 `apps/core/tests/test_backup_docs.py` 强制校验；改命令先改文档与测试。
> 仓库内已完成的恢复演练记录见文末「恢复演练」。

备份与恢复是合规底线（`docs/security.md`）：客户档案、照片、事件时间线只存在这套
系统里。Tailscale / 内网穿透解决「远程访问」，不是备份的替代品。

---

## 1. 备份内容与产物结构

每次备份产生一个按时间戳命名的目录，放于 `BACKUP_DIR`（默认 `backups/`，容器内
`/app/backups`，对应宿主仓库 `backups/`）。目录名：`backups/<YYYYMMDD_HHMMSS>/`。

一个备份批次含四个产物：

| 文件 | 说明 |
|---|---|
| `db.dump` | 数据库完整导出，`pg_dump --format=custom`（支持选择性恢复）。含表结构、索引、序列、业务数据；不含用户上传的文件（在 media.tar.gz）。 |
| `media.tar.gz` | `MEDIA_ROOT`（照片原图 / 缩略图 / 上传文件）整体 tar + gzip。数据库与媒体两轨缺一不可，只备一项无法完整恢复。 |
| `manifest.json` | 批次清单：`version`、`created_at`、产物文件名、各实体行数（`counts`，恢复后核对数据量）、两个产物的 sha256 校验和。 |
| `checksums.txt` | 校验和文本（`<sha256>  <文件名>`，一行一个），即 `sha256sum` 输出格式，可直接 `sha256sum -c` 校验。 |

manifest 示例：

```json
{
  "version": 1,
  "created_at": "2026-08-06T22:25:57+00:00",
  "db_dump": "db.dump",
  "media_tar": "media.tar.gz",
  "counts": {"customers.customer": 3, "policies.policy": 5},
  "checksums": {"db.dump": "<sha256>", "media.tar.gz": "<sha256>"}
}
```

---

## 2. 手动备份

### 容器内执行（推荐）

备份在 **web 容器内** 执行（`pg_dump` 客户端装在 web 镜像，连接参数取
`settings.DATABASES`）：

```bash
make backup
# 等价于：
docker compose -f docker/dev/compose.yaml exec web python manage.py backup
```

输出：`备份完成：<stamp>`、目录路径、`db.dump` / `media.tar.gz` 大小、
实体行数、校验和、保留清理份数。

### 宿主（本机）执行

开发库只监听 `127.0.0.1:5432`，宿主若无 `pg_dump` / `pg_restore` 客户端请走容器内
方式（`make backup`）。宿主侧做产物的查看 / 拷贝 / 异机备份：

```bash
ls -lR backups/ | tail -20    # 查看最近备份产物
du -sh backups/                # 备份占用空间
```

---

## 3. 备份验证

备份完成后立即验证，不要等到恢复时才发现坏档：

```bash
# 1) 目录与产物齐全
ls -l backups/<stamp>/

# 2) 校验和核对（在备份目录内执行，checksums.txt 用相对文件名）
cd backups/<stamp> && sha256sum -c checksums.txt
# 期望输出两行 OK：db.dump: OK / media.tar.gz: OK

# 3) manifest 可读
python -m json.tool backups/<stamp>/manifest.json
```

---

## 4. 保留策略与清理

- 每次 `manage.py backup` 运行后自动按 `BACKUP_RETENTION_COUNT`（默认 `30`，见
  `.env.example`）清理：目录数超过该值时删除最旧批次。
- 保留的是「批次」不是「文件」——目录整体保留 / 删除，避免只剩 db.dump 的半截备份。
- 调份数：改 `.env` 的 `BACKUP_RETENTION_COUNT`，重载 web 容器生效。
- 手动清理：直接删 `backups/` 下对应时间戳目录；`prune` 只管「超保留数」的最旧批次，
  手动删除不触发后台任务。

---

## 5. 定时备份

### 方案 A：宿主机 cron（推荐）

宿主机 cron 直接调用 compose 备份目标，无需进容器：

```cron
# 每日凌晨 3:00 备份（宿主机 crontab -e）
0 3 * * * cd /path/to/keji && docker compose -f docker/dev/compose.yaml exec web python manage.py backup >> /var/log/keji-backup.log 2>&1
```

要点：

- 容器需在运行（`make dev-up`），cron 不拉起容器；生产换编排文件，命令形态不变。
- `>> log` 便于排查；成败以日志「备份完成」及 `ls backups/` 为准。

### 方案 B：容器内 cron

容器内放 cron 需额外安装 `cron` 并保证 db / web 先就绪，属镜像 / 编排定制，开发镜像
未内置。需要时：

```bash
# 容器内 /etc/crontab（假设已装 cron，当前用户可写 /app/backups）
0 3 * * * root cd /app && python manage.py backup >> /app/backups/cron.log 2>&1
```

> 优先方案 A：不依赖容器内额外软件，日志落宿主，排查方便。

### 备份状态查看

- 首页工作队列有「备份状态」卡（dashboard `backup_status`）：设置键 `last_backup_at`
  非空时显示「上次备份：<时间>」，未配置时显示「备份功能待配置」占位 badge。
- 命令行看历史清单：

```bash
docker compose -f docker/dev/compose.yaml exec web python manage.py shell -c "from apps.core.services.backup import list_backups; print(list_backups())"
```

---

## 6. 恢复流程

恢复命令由 `apps/core/management/commands/restore_backup` 实现（T11.2），
`scripts/restore.sh` 提供包装。恢复是**破坏性操作**，执行前先按步骤 2 保护当前数据。

### 命令语法

```bash
# 恢复指定批次
docker compose -f docker/dev/compose.yaml exec web python manage.py restore_backup --stamp <stamp> [--db-name X] [--yes]

# 恢复最新批次（Makefile 目标等价形式）
make restore
# 等价于：docker compose -f docker/dev/compose.yaml exec web python manage.py restore_backup --latest --yes
```

| 参数 | 说明 |
|---|---|
| `--stamp <stamp>` | 备份目录名，如 `20260806_222557`；与 `--latest` 二选一。 |
| `--latest` | 使用 `backups/` 下最新批次。 |
| `--db-name X` | 恢复到指定库名（默认 `DB_NAME`）；演练时恢复进 `keji_drill`。 |
| `--yes` | 跳过交互确认（脚本 / cron 场景必备）。 |

### 恢复步骤

1. **停止写操作**：通知使用者停止录入，必要时 `docker compose -f
   docker/dev/compose.yaml stop web`（只留 db）。
2. **保护当前数据**：先再备份一次（§2），保证恢复失败仍有当前数据可回退。
3. **执行恢复**：指定批次跑 `restore_backup`（交互模式输入 `yes` 确认；`--yes` 无人值守）。
4. **验证数据**：对比 `manifest.json` 的 `counts` 与恢复后各表行数一致。
5. **重启服务**：拉起 §6.1 停止的服务，登录抽查客户档案与照片。

---

## 7. 恢复演练

> ADR-011：没有演练过的备份等于没有备份。本仓库交付前已完整演练一次，记录如下；
> 每次大版本发布前应重演并更新记录。

### 演练记录

- **日期**：2026-08-06
- **方式**：备份批次恢复到独立库 `keji_drill`，不触碰主库 `keji`
- **结果**：恢复后实体行数与 `manifest.json` 的 `counts` 完全一致；文件校验和核对
  通过；应用连 `keji_drill` 可正常查询；演练库已删除。

### 如何复现演练

```bash
# 1) 先做一次备份，得到 <stamp>
docker compose -f docker/dev/compose.yaml exec web python manage.py backup

# 2) 创建演练库（独立于主库）
docker compose -f docker/dev/compose.yaml exec db createdb -U keji keji_drill

# 3) 恢复备份批次到演练库（不覆盖主库）
docker compose -f docker/dev/compose.yaml exec web python manage.py restore_backup --stamp <stamp> --db-name keji_drill --yes

# 4) 对比实体行数与 manifest 的 counts：select count(*) from <table>，
#    与 manifest.json 中 counts.<app>.<model> 比对

# 5) 演练完毕，删除演练库
docker compose -f docker/dev/compose.yaml exec db dropdb -U keji keji_drill
```

> `dropdb` 失败时先断开对该库的连接。想用演练库做界面验证，可临时改 `.env` 的
> `DB_NAME=keji_drill` 重启 web 容器，验证完改回。

---

## 8. 数据安全

- `backups/` 已在 `.gitignore` 排除（`backups/*`，仅留 `.gitkeep`）。**真实备份永不
  入库**；不要把备份拷进 `media/`、`staticfiles/` 等入库目录。
- 备份目录若在仓库磁盘，务必配合宿主侧异机备份（rsync / NAS / 云盘），否则同盘故障
  时备份与数据一起丢。
- 恢复前必须先备份当前数据（§6 步骤 2）：恢复覆盖瞬间完成，无二次确认。
- `db.dump` 含全部敏感资料，异机传输建议加密（scp / rclone 加密远程等）；本版备份
  无内置加密（ADR-011 边界）。

---

## 9. 常见问题

### pg_dump 不在 PATH

`pg_dump` 在 web 容器内（Dockerfile 装 `postgresql-client`），**必须容器内执行**：
`docker compose -f docker/dev/compose.yaml exec web python manage.py backup`。宿主
直接用 `pg_dump` 需自行装客户端且版本与 PostgreSQL 17 兼容。

### 备份文件属主是 root

容器以 root 运行，备份产物属主为容器内 root，宿主 `ls -l` 显示 `root:root`，普通
用户只读。处理：

```bash
sudo chown -R "$USER":"$USER" backups/<stamp>
```

### 磁盘空间不足

每次备份约等于「数据库导出 + 全部媒体」体积，按保留 30 份预留数倍空间。查看占用：
`du -sh backups/`。空间紧张时调低 `BACKUP_RETENTION_COUNT` 或手动删最旧批次（§4），
再跑一次 `manage.py backup` 触发清理。

### 定时备份没跑

先确认宿主 cron 服务、日志路径、容器是否运行（`make dev-up`）。cron 行里的
`cd /path/to/keji` 必须为仓库绝对路径，compose 文件路径相对该目录生效。
