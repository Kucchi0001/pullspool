# PullSpool 数据模型（P0 定稿）

> 版本：1.0.0-draft　引擎：SQLite 3.45+　ORM：SQLAlchemy 2.x（async + aiosqlite）　迁移：Alembic

---

## 1. 设计原则

1. **单库单写者**：SQLite 在 WAL 模式下允许并发读，但写必须串行。后端只起一个进程，所有写操作走同一个 `AsyncSession` 工厂 + 短事务；高频进度更新走内存缓冲，每 2 秒批量落库。
2. **时间统一存 UTC 文本**：格式 `YYYY-MM-DDTHH:MM:SSZ`（`strftime('%Y-%m-%dT%H:%M:%SZ','now')`），可排序、可比较、无时区歧义。日界聚合在查询层按 `TZ` 换算。
3. **不存敏感明文**：会话只存 token 的 SHA-256；URL 存原始值（重试需要）但**永不写入日志与 API**；API 只暴露脱敏后的 `url_display`。
4. **删除即标记**：任务记录默认软删除（`deleted_at`），保留哈希与时间戳；物理删除只发生在"清空历史"这类显式操作（第一版不提供）。
5. **金额式累加**：流量按"已计入"字段防重复累加（`download_bytes_counted`、`upload_bytes_counted`）。
6. **外键开启**：每个连接执行 `PRAGMA foreign_keys=ON`。

---

## 2. PRAGMA 与连接设置

```sql
PRAGMA journal_mode = WAL;          -- 并发读 + 单写
PRAGMA synchronous = NORMAL;        -- WAL 下兼顾安全与性能
PRAGMA busy_timeout = 5000;         -- 锁等待 5 秒，避免瞬时 500
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 67108864;        -- 64 MiB，低配 VPS 上限
```

连接池：`pool_size=5`、`max_overflow=5`、`pool_pre_ping=True`、`pool_recycle=1800`。

---

## 3. 表结构

### 3.1 `users`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `username` | TEXT | NOT NULL UNIQUE | 小写，3–32 位，`[a-z0-9_-]` |
| `password_hash` | TEXT | NOT NULL | Argon2id 完整字符串（含盐与参数） |
| `must_change_password` | INTEGER | NOT NULL DEFAULT 0 | 0/1 |
| `created_at` | TEXT | NOT NULL | |
| `password_changed_at` | TEXT | NULL | |
| `last_login_at` | TEXT | NULL | |
| `failed_login_count` | INTEGER | NOT NULL DEFAULT 0 | |
| `locked_until` | TEXT | NULL | 暴力破解锁定截止时间 |

索引：`ux_users_username`（UNIQUE）。

第一版只有一行数据（单用户），但保留表结构与 `user_id` 外键，为将来多用户留余量。

### 3.2 `sessions`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | UUIDv4 |
| `user_id` | INTEGER | NOT NULL FK→users(id) ON DELETE CASCADE | |
| `token_hash` | TEXT | NOT NULL UNIQUE | SHA-256(hex) of 32-byte token |
| `created_at` | TEXT | NOT NULL | |
| `last_seen_at` | TEXT | NOT NULL | 每次请求滑动更新（节流 60 秒） |
| `expires_at` | TEXT | NOT NULL | `min(now+idle_days, created+absolute_days)` |
| `revoked_at` | TEXT | NULL | 登出/改密时写 |
| `ip` | TEXT | NULL | 取自可信代理头 |
| `user_agent` | TEXT | NULL | 截断 255 字符 |

索引：`ux_sessions_token_hash`（UNIQUE）、`ix_sessions_user`、`ix_sessions_expires`。

### 3.3 `tasks`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | UUIDv4，同时作为目录名 |
| `user_id` | INTEGER | NOT NULL FK→users(id) | |
| `url` | TEXT | NOT NULL | 原始 URL，含敏感 query，**不出 API/日志** |
| `url_display` | TEXT | NOT NULL | 脱敏展示值 |
| `final_url` | TEXT | NULL | 预检后最终 URL（含 query，仅内部重试用） |
| `final_url_display` | TEXT | NULL | 最终 URL 脱敏值 |
| `filename` | TEXT | NOT NULL | 净化后的落盘文件名 |
| `display_name` | TEXT | NULL | 用户自定义名（可为空） |
| `stored_relpath` | TEXT | NULL | 相对下载根的路径，如 `{id}/{filename}` |
| `status` | TEXT | NOT NULL CHECK IN (...) | 见 §4 |
| `ui_status` | —（不存储，计算字段） | | 由 API 层派生 |
| `error_code` | TEXT | NULL | 与 API 错误码同表 |
| `error_message` | TEXT | NULL | 面向用户的中文短句，≤500 字符 |
| `aria2_gid` | TEXT | NULL | 当前有效的 aria2 GID |
| `file_size` | INTEGER | NULL | 总字节数（Content-Length 或 aria2 totalLength） |
| `downloaded_size` | INTEGER | NOT NULL DEFAULT 0 | 已下载字节 |
| `download_speed` | INTEGER | NOT NULL DEFAULT 0 | 最近一次采样速度（字节/秒），仅用于展示，权威值在前端 3 秒窗口 |
| `sha256` | TEXT | NULL | 64 位小写十六进制 |
| `sha256_computed_at` | TEXT | NULL | |
| `expected_sha256` | TEXT | NULL | 源站声明值（`Digest`/`X-Checksum-Sha256`），仅比对 |
| `content_type` | TEXT | NULL | |
| `supports_range` | INTEGER | NULL | 0/1/NULL(未知) |
| `etag` | TEXT | NULL | 源站 ETag，仅记录 |
| `max_connections` | INTEGER | NOT NULL DEFAULT 4 | |
| `speed_limit_bytes` | INTEGER | NOT NULL DEFAULT 0 | 0 = 不限 |
| `max_size_bytes` | INTEGER | NULL | 本次任务上限，空则取全局 |
| `attempts` | INTEGER | NOT NULL DEFAULT 0 | 重试计数 |
| `download_bytes_counted` | INTEGER | NOT NULL DEFAULT 0 | 已计入流量统计的入站字节 |
| `upload_bytes_counted` | INTEGER | NOT NULL DEFAULT 0 | 已计入流量统计的出站字节 |
| `transfer_count` | INTEGER | NOT NULL DEFAULT 0 | 完整回传次数 |
| `created_at` | TEXT | NOT NULL | |
| `started_at` | TEXT | NULL | |
| `completed_at` | TEXT | NULL | 校验通过时间 |
| `retrieved_at` | TEXT | NULL | 用户确认取回时间 |
| `deleted_at` | TEXT | NULL | 文件删除时间 |
| `deleted_reason` | TEXT | NULL | `user_ack` / `expired` / `user_cancel` / `admin` |
| `expires_at` | TEXT | NULL | `completed_at + retention_hours` |
| `last_synced_at` | TEXT | NULL | 最后一次从 aria2 同步时间 |

索引：

```sql
CREATE INDEX ix_tasks_user_status   ON tasks(user_id, status);
CREATE INDEX ix_tasks_created       ON tasks(created_at DESC);
CREATE INDEX ix_tasks_completed     ON tasks(completed_at DESC);
CREATE INDEX ix_tasks_expires       ON tasks(expires_at) WHERE deleted_at IS NULL AND status = 'completed';
CREATE INDEX ix_tasks_gid           ON tasks(aria2_gid);
CREATE INDEX ix_tasks_filename      ON tasks(filename);
```

`CHECK` 约束：

```sql
CHECK (status IN ('queued','active','paused','verifying','completed','failed','canceled'))
CHECK (downloaded_size >= 0 AND (file_size IS NULL OR downloaded_size >= 0))
CHECK (sha256 IS NULL OR length(sha256) = 64)
CHECK (deleted_reason IS NULL OR deleted_reason IN ('user_ack','expired','user_cancel','admin'))
```

### 3.4 `task_events`

审计与错误历史（界面"查看错误信息"与任务详情时间线）。

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |
| `task_id` | TEXT | NULL FK→tasks(id) ON DELETE CASCADE（系统事件为空） |
| `kind` | TEXT | NOT NULL（见下） |
| `message` | TEXT | NOT NULL（已脱敏，≤500 字符） |
| `created_at` | TEXT | NOT NULL |

`kind` 取值：`created`、`started`、`paused`、`resumed`、`canceled`、`completed`、`verified`、`retrieved`、`deleted`、`expired`、`failed`、`retried`、`reconciled`、`alert`。

索引：`ix_events_task (task_id, created_at)`、`ix_events_created (created_at DESC)`。

保留策略：每任务最多保留 200 条，超出由清理器删除最旧的（按 `id`）。

### 3.5 `traffic_daily`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `day` | TEXT | NOT NULL | 本地日期 `YYYY-MM-DD`（按 `TZ`） |
| `direction` | TEXT | NOT NULL CHECK IN ('down','up') | |
| `bytes` | INTEGER | NOT NULL DEFAULT 0 | |

主键：`PRIMARY KEY (day, direction)`。

写入：`INSERT ... ON CONFLICT(day, direction) DO UPDATE SET bytes = bytes + excluded.bytes`。

### 3.6 `settings`

| 列 | 类型 | 约束 |
|---|---|---|
| `key` | TEXT | PK |
| `value` | TEXT | NOT NULL（JSON 编码值） |
| `updated_at` | TEXT | NOT NULL |

启动时：缺失的键用默认值补齐（不覆盖已有值）；未知键保留（向前兼容）但不下发。

### 3.7 `alembic_version`

Alembic 管理，`version_num TEXT PK`。

---

## 4. 状态与转换的数据库层约束

状态只在服务层变更，且都经过 `UPDATE tasks SET status=?, ... WHERE id=? AND status=?` 的**条件更新**，受影响行数为 0 时抛 `TASK_STATE_CONFLICT`。这保证并发请求（例如两个标签页同时点"暂停"）不会互相覆盖。

删除类操作统一用：

```sql
UPDATE tasks
   SET deleted_at = ?, retrieved_at = COALESCE(retrieved_at, ?), deleted_reason = ?
 WHERE id = ? AND deleted_at IS NULL
```

受影响行数 0 → 说明已被删除，返回当前记录（幂等）。

---

## 5. 一致性校验 SQL

启动对账与定时巡检使用：

```sql
-- 1) 标记为 completed 但文件缺失（由应用层 stat 后写入 failed）
SELECT id, stored_relpath FROM tasks
 WHERE status = 'completed' AND deleted_at IS NULL;

-- 2) downloaded_size 超过 file_size（脏数据）
SELECT id, downloaded_size, file_size FROM tasks
 WHERE file_size IS NOT NULL AND downloaded_size > file_size;

-- 3) 已完成但缺 sha256
SELECT id FROM tasks WHERE status = 'completed' AND sha256 IS NULL;

-- 4) 过期未清理
SELECT id, expires_at FROM tasks
 WHERE status = 'completed' AND deleted_at IS NULL
   AND expires_at IS NOT NULL AND expires_at < :now;

-- 5) 队列中耗时异常的任务（可能卡在 aria2 不可达）
SELECT id, created_at FROM tasks
 WHERE status = 'queued' AND created_at < :now_minus_1h;

-- 6) 流量重复计入检测（同一任务被多次计入）
SELECT id, download_bytes_counted FROM tasks
 WHERE download_bytes_counted > 0 AND status IN ('queued','active');
```

---

## 6. 迁移策略

- 目录：`backend/alembic/versions/`，基线版本 `0001_init`；
- 容器启动时由 `backend/app/database/migrate.py` 执行 `alembic upgrade head`（幂等），失败则进程退出并打印明确错误；
- 每次迁移前自动生成数据库备份：`./data/db/pullspool.db.bak-{timestamp}`（仅保留最近 3 份）；
- 迁移脚本要求：**只加不删**（第一版内），必须可在已有数据上重放；
- 回滚：提供 `alembic downgrade -1` 的文档说明，但生产不自动回滚（避免半回滚状态）。

新增字段示例（保证旧数据可用）：

```sql
ALTER TABLE tasks ADD COLUMN new_field TEXT NULL;
```

SQLite 的 `ALTER TABLE` 限制（不能改列类型/加约束）通过"建新表 → 迁数据 → 改名"三步完成，Alembic 的 `batch_alter_table` 会自动处理。

---

## 7. 备份与恢复要点

| 项 | 做法 |
|---|---|
| 在线备份 | `sqlite3 pullspool.db ".backup '/backup/pullspool-$(date).db'"`（WAL 安全，不走文件拷贝） |
| 一致性 | 备份时不需要停容器；`.backup` 使用事务快照 |
| 附件 | `./data/downloads/` 与数据库**分开备份**；恢复时任务记录与文件按 `stored_relpath` 对齐 |
| 恢复后 | 启动对账会重新校验：文件缺失 → `failed`；多余目录 → 孤儿隔离 |
| 版本 | 备份文件随附 `alembic_version` 与 `version` 字符串，恢复时先跑迁移 |

`scripts/backup.sh` 输出：`pullspool-backup-{YYYYmmdd-HHMMSS}.tar.gz`，内含 `db/pullspool.db`、`VERSION`、`manifest.json`（记录版本与文件数）。下载文件默认**不**打包（体积大），可用 `--with-files` 显式包含。

---

## 8. 数据保留

| 数据 | 保留策略 |
|---|---|
| 任务记录 | 永久（软删除）；用户手动"清空历史"功能第一版不提供 |
| `task_events` | 每任务 200 条上限；`alert` 类系统事件保留 1000 条 |
| `traffic_daily` | 永久（每天 2 行，一年 730 行） |
| `sessions` | 过期后 7 天由清理器物理删除 |
| 文件 | `completed` 后 24 小时（可配）或用户确认后立即删除 |
| 孤儿目录 | 隔离 24 小时后删除 |
| `.aria2` 控制文件 | 任务终态后删除 |

---

## 9. 查询性能预算

| 查询 | 目标 |
|---|---|
| 任务列表（20 条，带计数） | < 15 ms |
| 任务详情（含 20 条事件） | < 10 ms |
| 7/30 天流量聚合 | < 5 ms |
| 过期清理扫描 | < 20 ms（10 万行内） |
| 进度批量更新（10 个任务） | < 10 ms |

上述目标在 1 vCPU VPS 上以 1 万任务量级基准测试验证（P1 交付基准脚本）。
