# PullSpool API 设计（P0 定稿）

> 版本：1.0.0-draft　对应架构：[ARCHITECTURE.md](./ARCHITECTURE.md)　最后更新：2026-11-26

所有接口以 `/api` 为前缀，仅通过 Caddy（HTTPS）或 nginx（HTTP）对外暴露。后端自身不做 CORS——前后端同源。

---

## 1. 通用约定

### 1.1 请求

| 项 | 约定 |
|---|---|
| 编码 | UTF-8；请求体 `application/json`（文件流下载除外） |
| 认证 | Cookie `ps_session`（HttpOnly），或 `?token=` 下载令牌 |
| CSRF | 所有非 GET/HEAD 请求都要校验 `Origin`（缺失时用 `Referer`）的 host 与请求 host 一致；不一致返回 403 `ORIGIN_MISMATCH` |
| 时间 | ISO 8601 UTC，带 `Z`，如 `2026-11-26T11:30:00Z`；客户端负责转本地时区 |
| 标识 | 任务/会话 ID 为 UUIDv4 字符串 |
| 大小 | 所有 `*_bytes` 字段为整数（字节）；`*_kib_per_s` 为 KiB/s 整数 |
| 版本 | `GET /api/health` 与 `GET /api/auth/me` 返回版本信息 |

### 1.2 响应

- 成功：`200` 返回对象；创建：`201`；删除/登出等无内容：`204`；幂等重复操作：`200` 返回当前状态。
- 列表：统一结构

```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

- 错误：统一封套（HTTP 状态码按语义给出）

```json
{
  "error": {
    "code": "TASK_STATE_CONFLICT",
    "message": "任务当前状态不允许该操作",
    "details": { "status": "paused", "action": "ack" },
    "request_id": "8f3c1e0a9b2d4c55"
  }
}
```

`message` 是给用户看的中文短句；`details` 是给前端做判断的结构化数据；`request_id` 同时写入日志，便于对账。

### 1.3 错误码表

| code | HTTP | 含义 | 前端处理 |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | 参数不合法（`details.field` 指出字段） | 表单行内报错 |
| `URL_INVALID` | 400 | URL 格式非法 | 输入框报错 |
| `URL_SCHEME_NOT_ALLOWED` | 400 | 非 http/https | 输入框报错 |
| `SSRF_BLOCKED` | 403 | 命中 SSRF 策略（`details.reason`） | 提示"该地址不允许访问" |
| `DNS_RESOLUTION_FAILED` | 502 | 域名无法解析 | 提示检查域名 |
| `REDIRECT_LIMIT_EXCEEDED` | 502 | 重定向超过 5 跳 | 提示链接异常 |
| `TARGET_UNREACHABLE` | 502 | 目标站连接失败/超时 | 可重试 |
| `TARGET_REJECTED` | 502 | 目标站返回 4xx/5xx | 展示状态码 |
| `AUTH_REQUIRED` | 401 | 未登录 | 跳登录页 |
| `AUTH_INVALID` | 401 | 用户名或密码错误 | 行内报错 |
| `AUTH_LOCKED` | 429 | 登录锁定（`details.retry_after`） | 倒计时 |
| `SESSION_EXPIRED` | 401 | 会话过期/已撤销 | 跳登录页 |
| `PASSWORD_CHANGE_REQUIRED` | 403 | 首次登录必须改密 | 强制跳改密页 |
| `WEAK_PASSWORD` | 400 | 密码不满足强度（≥10 位，含两类字符） | 行内报错 |
| `USERNAME_INVALID` | 400 | 用户名格式不合法（3–32 位小写字母/数字/点/下划线/连字符） | 行内报错 |
| `USERNAME_TAKEN` | 409 | 用户名已被占用 | 行内报错 |
| `ORIGIN_MISMATCH` | 403 | CSRF 校验失败 | 提示刷新页面 |
| `FORBIDDEN` | 403 | 无权访问该任务 | 跳回列表 |
| `TASK_NOT_FOUND` | 404 | 任务不存在 | 提示/刷新 |
| `TASK_STATE_CONFLICT` | 409 | 当前状态不允许该操作 | Toast + 刷新 |
| `TASK_DUPLICATE` | 200 | 重复 URL，返回已有任务 | 提示"已存在" |
| `TRANSFER_IN_PROGRESS` | 409 | 正在回传，禁止删除 | 提示等传输结束 |
| `FILE_NOT_FOUND` | 404 | 文件已不存在 | 刷新任务 |
| `FILE_INTEGRITY_FAILED` | 409 | 校验未通过 | 显示错误详情 |
| `FILE_TOO_LARGE` | 413 | 文件超过单文件上限 | 提示上限值 |
| `RANGE_NOT_SATISFIABLE` | 416 | Range 越界 | 浏览器自行处理 |
| `QUOTA_EXCEEDED` | 409 | 超过总配额 | 提示清理 |
| `DISK_FULL` | 507 | 磁盘空间不足 | 顶部横幅 |
| `QUEUE_FULL` | 409 | 排队任务数超过上限（默认 50） | 提示稍后再试 |
| `ARIA2_UNAVAILABLE` | 503 | 下载引擎不可达 | 顶部告警 |
| `ARIA2_ERROR` | 502 | 引擎返回错误（`details.aria2_code`） | 展示错误 |
| `DOWNLOAD_TIMEOUT` | 504 | 下载超时/无进度 | 可重试 |
| `TOKEN_INVALID` | 401 | 下载令牌无效 | 重新生成链接 |
| `TOKEN_EXPIRED` | 401 | 下载令牌过期 | 重新生成链接 |
| `RATE_LIMITED` | 429 | 触发限流（`details.retry_after`） | 倒计时 |
| `SETTINGS_INVALID` | 400 | 设置值越界（`details.key`） | 行内报错 |
| `NOT_FOUND` | 404 | 路由不存在 | — |
| `METHOD_NOT_ALLOWED` | 405 | 方法不允许 | — |
| `INTERNAL_ERROR` | 500 | 未预期异常（带 `request_id`） | 提示重试并展示 ID |

### 1.4 任务对象 `Task`

所有返回任务的地方都用同一个结构：

```json
{
  "id": "6f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b",
  "url_display": "https://example.com/releases/pullspool-1.0.zip",
  "filename": "pullspool-1.0.zip",
  "display_name": null,
  "status": "active",
  "ui_status": "downloading",
  "file_size": 104857600,
  "downloaded_size": 52428800,
  "progress": 0.5,
  "download_speed": 5242880,
  "eta_seconds": 10,
  "sha256": null,
  "content_type": "application/zip",
  "supports_range": true,
  "error_code": null,
  "error_message": null,
  "attempts": 0,
  "max_connections": 4,
  "speed_limit_bytes": 0,
  "download_bytes": 0,
  "retrieved_bytes": 0,
  "transfer_count": 0,
  "is_file_available": true,
  "created_at": "2026-11-26T11:00:00Z",
  "started_at": "2026-11-26T11:00:03Z",
  "completed_at": null,
  "retrieved_at": null,
  "deleted_at": null,
  "expires_at": null
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `url_display` | 脱敏后的 URL（query 一律替换为 `?***`），界面只展示这个 |
| `status` | 持久状态之一：`queued`/`active`/`paused`/`verifying`/`completed`/`failed`/`canceled` |
| `ui_status` | 派生界面状态，见 §1.5 |
| `progress` | `downloaded_size / file_size`，未知大小或为 0 时 `null` |
| `download_speed` | 近 3 秒滑动平均，字节/秒 |
| `eta_seconds` | 剩余秒数，速度 ≤0 或大小未知时 `null` |
| `download_bytes` | 该任务累计入站字节（计入流量统计的值） |
| `retrieved_bytes` | 该任务累计回传字节 |
| `is_file_available` | 文件当前是否真实存在于磁盘且状态为 `completed` |

### 1.5 `ui_status` 枚举

`downloading` · `queued` · `paused` · `verifying` · `transferring` · `ready` · `retrieved` · `deleted` · `expired` · `failed` · `canceled`

判定规则见 ARCHITECTURE §8.3。后端负责计算，前端只做展示映射，**不在前端重复推导状态**。

---

## 2. 认证 `/api/auth`

### 2.1 POST `/api/auth/login`

| 项 | 值 |
|---|---|
| 认证 | 不需要 |
| 限流 | 同一 IP 15 分钟内 20 次；同一用户名 5 次失败锁定 15 分钟 |

请求：

```json
{ "username": "admin", "password": "**********" }
```

响应 `200`（同时 `Set-Cookie: ps_session=...; HttpOnly; SameSite=Lax; Path=/; Max-Age=...`）：

```json
{
  "user": {
    "id": 1,
    "username": "admin",
    "must_change_password": false,
    "created_at": "2026-11-26T10:00:00Z",
    "last_login_at": "2026-11-26T11:20:00Z"
  }
}
```

错误：`AUTH_INVALID`、`AUTH_LOCKED`、`VALIDATION_ERROR`、`RATE_LIMITED`。

### 2.2 POST `/api/auth/logout`

认证：需要。响应 `204`，服务端删除会话行并清除 Cookie。

### 2.3 GET `/api/auth/me`

认证：需要（`must_change_password=true` 时也允许，否则前端无法知道要跳转）。

```json
{
  "user": { "id": 1, "username": "admin", "must_change_password": false },
  "server": { "version": "1.0.0", "build": "2026.11.26", "started_at": "2026-11-26T10:00:00Z", "uptime_seconds": 7200 }
}
```

### 2.4 POST `/api/auth/password`

认证：需要（**这个接口在 `must_change_password=true` 时唯一可用**）。

请求：

```json
{ "current_password": "old", "new_password": "new-strong-pass" }
```

规则：新密码 ≥ 10 位，至少包含字母与数字两类；不得与旧密码相同；成功后撤销该用户其他所有会话，并删除 `data/bootstrap-admin.txt`。

响应 `204`。错误：`AUTH_INVALID`、`WEAK_PASSWORD`、`VALIDATION_ERROR`。

### 2.5 POST `/api/auth/username`

认证：需要（`must_change_password=false` 后可调用）。

请求：

```json
{ "new_username": "spool.admin", "current_password": "current-password" }
```

规则：

- 用户名统一转小写；3–32 位，仅允许 `a-z0-9._-`，且必须以字母或数字开头；
- 必须提供当前密码确认身份；
- 与当前用户名相同则直接返回当前用户（幂等）；
- 用户名唯一，冲突返回 `USERNAME_TAKEN`；
- 修改后当前会话保持有效，其他设备无需重新登录；下次登录使用新用户名；
- 操作记录到日志（旧名 → 新名），不记录密码。

响应 `200`，返回更新后的 `UserOut`：

```json
{ "id": 1, "username": "spool.admin", "must_change_password": false, "created_at": "…", "last_login_at": "…" }
```

错误：`AUTH_REQUIRED`、`AUTH_INVALID`（密码错误）、`USERNAME_INVALID`、`USERNAME_TAKEN`、`VALIDATION_ERROR`。

---

## 3. 任务 `/api/tasks`

### 3.1 POST `/api/tasks` 创建任务

| 项 | 值 |
|---|---|
| 认证 | 需要 |
| 限流 | 每分钟 10 次 |
| 幂等 | 同一用户 10 分钟内相同 URL 返回已有任务（200 + `duplicate: true`） |

请求：

```json
{
  "url": "https://example.com/file.zip",
  "filename": "自定义名字.zip",       // 可选
  "connections": 4,                    // 可选，1-16，默认取设置
  "speed_limit_kib_per_s": 0,          // 可选，0 = 不限
  "max_size_bytes": 8589934592         // 可选，不得超过全局上限
}
```

响应 `201`：

```json
{ "task": { "...Task..." }, "duplicate": false }
```

错误：`URL_INVALID`、`URL_SCHEME_NOT_ALLOWED`、`SSRF_BLOCKED`、`DNS_RESOLUTION_FAILED`、`TARGET_UNREACHABLE`、`TARGET_REJECTED`、`FILE_TOO_LARGE`、`QUOTA_EXCEEDED`、`DISK_FULL`、`QUEUE_FULL`、`ARIA2_UNAVAILABLE`、`VALIDATION_ERROR`。

> 注意：创建接口会同步执行预检（DNS + 重定向 + HEAD），最长阻塞 12 秒。前端按钮需显示 loading 并允许取消请求（取消不影响后端继续建任务）。

### 3.2 GET `/api/tasks` 列表

| 查询参数 | 类型 | 说明 |
|---|---|---|
| `scope` | enum | `active`（默认，queued/active/paused/verifying）、`ready`（等待取回）、`history`（completed 且已删除/已取回 + failed + canceled）、`all` |
| `status` | string | 逗号分隔的持久状态过滤 |
| `q` | string | 文件名/URL 模糊搜索（≤100 字符，SQL `LIKE` 参数化） |
| `sort` | enum | `created_at`（默认）、`completed_at`、`file_size`、`filename` |
| `order` | enum | `desc`（默认）/`asc` |
| `page` | int | 默认 1，≥1 |
| `page_size` | int | 默认 20，1–100 |

响应 `200`：`{ items, total, page, page_size, counts: { downloading, queued, ready, failed } }`

`counts` 用于侧栏导航角标，避免前端再发一次请求。

### 3.3 GET `/api/tasks/{id}` 详情

响应 `200`：

```json
{
  "task": { "...Task..." },
  "integrity": {
    "expected_sha256": null,
    "actual_sha256": "9f2c...",
    "verified_at": "2026-11-26T11:05:00Z",
    "size_matches": true,
    "matches_expected": null
  },
  "events": [
    { "kind": "created", "message": "任务已创建", "created_at": "2026-11-26T11:00:00Z" },
    { "kind": "completed", "message": "下载并校验完成", "created_at": "2026-11-26T11:05:00Z" }
  ],
  "aria2": { "reachable": true, "status": "complete", "connections": 4 }
}
```

错误：`TASK_NOT_FOUND`（也用于访问他人任务，避免枚举）、`FORBIDDEN`。

### 3.4 POST `/api/tasks/{id}/pause`

仅 `active` 或 `queued` 可暂停。响应 `200` + `{task}`。错误：`TASK_STATE_CONFLICT`、`ARIA2_UNAVAILABLE`。

### 3.5 POST `/api/tasks/{id}/resume`

仅 `paused` 可恢复。响应 `200` + `{task}`。错误：`TASK_STATE_CONFLICT`、`DISK_FULL`。

### 3.6 POST `/api/tasks/{id}/cancel`

请求：

```json
{ "delete_files": true }
```

- 仅 `queued`/`active`/`paused` 可取消；
- `delete_files=true`：先 `aria2.forceRemove`，再删目录；`false`：保留残留文件（仍标记 `canceled`，后续由孤儿清理处理）；
- 响应 `200` + `{task}`；错误：`TASK_STATE_CONFLICT`。

### 3.7 POST `/api/tasks/{id}/retry`

仅 `failed` 可重试：重置 `attempts`、`error_*`，状态回 `queued`，沿用原 URL 但**重新执行完整预检**（URL 可能已失效）。响应 `200` + `{task}`。

### 3.8 DELETE `/api/tasks/{id}` 删除任务记录

| 查询参数 | 说明 |
|---|---|
| `delete_files` | `true`（默认）/`false`：是否一并删除磁盘文件 |

- `active`/`verifying`/有活动传输时返回 409 `TASK_STATE_CONFLICT`/`TRANSFER_IN_PROGRESS`；
- 默认软删除：写 `deleted_at`，保留记录与 SHA-256 供历史查看；
- 响应 `200` 返回更新后的任务；重复调用返回相同结果（幂等）。

### 3.9 POST `/api/tasks/{id}/ack` 确认取回并删除

请求：

```json
{ "confirm": true }
```

语义与幂等性见 ARCHITECTURE §7.5。响应 `200` + `{task}`。

错误：`TASK_STATE_CONFLICT`（不是 `completed`）、`TRANSFER_IN_PROGRESS`、`FILE_NOT_FOUND`（文件已被外部删除，此时直接标记删除成功并返回）。

### 3.10 GET `/api/tasks/{id}/integrity`

响应 `200`：

```json
{
  "task_id": "...",
  "sha256": "9f2c...",
  "file_size": 104857600,
  "verified_at": "2026-11-26T11:05:00Z",
  "expected_sha256": null,
  "matches_expected": null,
  "note": "哈希由 VPS 对本地文件计算；不代表源站内容正确"
}
```

### 3.11 POST `/api/tasks/{id}/download-token`

为外部下载器（IDM、Free Download Manager、手机浏览器）签发短时效链接。

请求体可省略，字段：

```json
{ "ttl_seconds": 1800 }
```

`ttl_seconds` 范围 60–3600，默认取设置值。

响应 `200`：

```json
{
  "url": "https://203.0.113.5:18443/api/tasks/6f1e.../file?token=eyJ...",
  "expires_at": "2026-11-26T11:50:00Z",
  "ttl_seconds": 1800
}
```

令牌 = `base64url(payload).base64url(hmac_sha256(payload, secret))`，`payload = {task_id, exp, nonce}`；服务端用 `.env` 的 `DOWNLOAD_TOKEN_SECRET` 校验，常量时间比较。

### 3.12 GET `/api/tasks/{id}/file` 取回文件

| 项 | 值 |
|---|---|
| 认证 | Cookie，或 `?token=` |
| 限流 | 同时回传数 ≤ `max_transfer_concurrency`（默认 2），超出 429 |
| 缓存 | `Cache-Control: private, no-store` |

请求头：`Range: bytes=0-`、`If-Range: <etag>`

响应头：

```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="fallback.zip"; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip
Accept-Ranges: bytes
ETag: "sha256:<前16位>-<size>"
Content-Length: <本次响应字节数>
```

- `200`：完整文件；`206`：`Content-Range: bytes start-end/total`；`416`：`Content-Range: bytes */total`；
- 错误：`AUTH_REQUIRED`、`TOKEN_INVALID`、`TOKEN_EXPIRED`、`FILE_NOT_FOUND`、`TRANSFER_IN_PROGRESS`（同任务已有传输且策略为单流）、`RATE_LIMITED`。

> 断点续传依赖 `ETag` 与 `If-Range`：文件在续传期间被清理时，服务端必须返回 `416` 或 `404`，绝不能用新文件冒充旧文件的不同片段（本项目文件不可变，因此以 `sha256+size` 作为 ETag 天然安全）。

---

## 4. 系统 `/api/system`

### 4.1 GET `/api/system/status`

```json
{
  "server": { "version": "1.0.0", "build": "2026.11.26", "uptime_seconds": 7200, "started_at": "..." },
  "host": {
    "cpu_percent": 3.2,
    "load_1": 0.12, "load_5": 0.08, "load_15": 0.05,
    "mem_total": 1024, "mem_used": 410, "mem_percent": 40.0,
    "disk_total": 21474836480, "disk_used": 5368709120, "disk_free": 16106127360
  },
  "storage": {
    "root": "/data/downloads",
    "used_bytes": 2147483648,
    "quota_bytes": 16106127360,
    "free_bytes": 16106127360,
    "min_free_bytes": 2147483648,
    "orphan_count": 0
  },
  "aria2": { "reachable": true, "guarded": true, "active": 2, "waiting": 1, "stopped": 0 },
  "queue": { "active": 2, "max_concurrent": 2, "paused_reason": null },
  "counts": { "downloading": 2, "ready": 3, "failed": 0, "total": 12 },
  "public_ip": "203.0.113.5"
}
```

`public_ip` 来自 `.env` 的 `PUBLIC_IP`（不主动外呼），仅用于界面展示与下载链接拼装。`queue.paused_reason` 取值 `null`/`disk_low`/`quota_exceeded`。

### 4.2 GET `/api/system/storage`

```json
{
  "root": "/data/downloads",
  "total_bytes": 21474836480,
  "used_bytes": 5368709120,
  "free_bytes": 16106127360,
  "downloads_bytes": 2147483648,
  "quota_bytes": 16106127360,
  "tasks": [ { "id": "...", "filename": "a.zip", "bytes": 104857600 } ],
  "orphans": [ { "path": ".orphan/20261126T110000", "bytes": 0, "quarantined_at": "..." } ]
}
```

### 4.3 GET `/api/system/traffic`

| 参数 | 默认 | 说明 |
|---|---|---|
| `days` | 7 | 1–90，返回最近 N 天（含今天） |
| `tz` | 服务器 `TZ` | 仅接受 IANA 名称白名单，用于日界换算 |

```json
{
  "days": [
    { "date": "2026-11-26", "download_bytes": 3221225472, "upload_bytes": 2147483648 }
  ],
  "totals": {
    "today_download_bytes": 3221225472,
    "today_upload_bytes": 2147483648,
    "month_download_bytes": 9663676416,
    "month_upload_bytes": 6442450944,
    "all_download_bytes": 32212254720,
    "all_upload_bytes": 21474836480
  },
  "nic": { "rx_bytes": 40265318400, "tx_bytes": 26843545600, "collected_at": "..." },
  "note": "应用层统计：仅统计 PullSpool 下载与回传字节，不等于运营商计费流量"
}
```

### 4.4 GET `/api/health`

免认证，最小信息，供 Docker healthcheck 与 uptime 监控：

```json
{ "status": "ok", "checks": { "db": "ok", "aria2": "ok", "disk": "ok", "egress_guard": "ok" }, "version": "1.0.0" }
```

`status` 取值 `ok`/`degraded`；`degraded` 时单项检查给出 `error`/`missing`。响应始终 200（由 `status` 表达健康度），除非进程完全不可用。

---

## 5. 设置 `/api/settings`

### 5.1 GET `/api/settings`

```json
{
  "settings": {
    "max_concurrent_downloads": 2,
    "default_connections": 4,
    "default_speed_limit_kib_per_s": 0,
    "global_speed_limit_kib_per_s": 0,
    "max_file_size_bytes": 8589934592,
    "max_total_storage_bytes": 16106127360,
    "min_free_disk_bytes": 2147483648,
    "retention_hours": 24,
    "download_token_ttl_seconds": 1800,
    "max_transfer_concurrency": 2,
    "density": "comfortable",
    "theme": "system",
    "locale": "zh-CN"
  },
  "meta": {
    "storage_root": "/data/downloads",
    "storage_subdir": "downloads",
    "tls_mode": "internal",
    "public_base_url": "https://203.0.113.5:18443",
    "version": "1.0.0",
    "build": "2026.11.26",
    "aria2_version": "1.37.0",
    "read_only_keys": ["storage_subdir"]
  }
}
```

### 5.2 PUT `/api/settings`

请求为**部分更新**，只传要改的键：

```json
{ "max_concurrent_downloads": 3, "retention_hours": 48 }
```

校验规则（越界返回 `SETTINGS_INVALID` + `details.key`）：

| 键 | 范围 |
|---|---|
| `max_concurrent_downloads` | 1–6 |
| `default_connections` | 1–16 |
| `default_speed_limit_kib_per_s` | 0–1048576 |
| `global_speed_limit_kib_per_s` | 0–1048576 |
| `max_file_size_bytes` | 1 MiB – 100 GiB |
| `max_total_storage_bytes` | 1 GiB – 10 TiB，且 ≤ 磁盘总量 × 0.9 |
| `min_free_disk_bytes` | 0 – 100 GiB |
| `retention_hours` | 1–720 |
| `download_token_ttl_seconds` | 60–3600 |
| `max_transfer_concurrency` | 1–4 |
| `density` | `comfortable` / `compact` |
| `theme` | `system` / `light` / `dark` |
| `locale` | `zh-CN`（预留 `en-US`） |

变更 `max_concurrent_downloads`、`global_speed_limit_kib_per_s` 会立即调用 `aria2.changeGlobalOption`；变更 `retention_hours` 会重算所有未删除任务的 `expires_at`。

响应 `200`：`{ "settings": {...}, "applied": ["max_concurrent_downloads"] }`

---

## 6. 实时事件 `/api/events`（SSE）

| 项 | 值 |
|---|---|
| 认证 | Cookie（EventSource 自动携带同源 Cookie） |
| 响应头 | `Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no` |
| 心跳 | 每 15 秒发送 `event: ping`，`data: {"t":<epoch>}` |
| 断线 | 客户端 `EventSource` 自动重连；服务端不保留历史，重连后客户端拉一次列表对齐 |
| 并发 | 单用户最多 3 条连接，超出关闭最旧的一条 |

事件类型：

| event | data | 触发时机 |
|---|---|---|
| `task.created` | `{task}` | 创建成功 |
| `task.updated` | `{task, changed:[...]}` | 状态/进度/错误变化（进度类节流 1 秒/任务） |
| `task.deleted` | `{id, deleted_at, reason}` | ack/过期/删除 |
| `traffic.updated` | `{today_download_bytes, today_upload_bytes}` | 每 10 秒或任务完成时 |
| `system.updated` | `{host, storage, aria2, queue}` | 每 5 秒 |
| `alert` | `{level, code, message}` | 磁盘不足、aria2 不可达、出口防火墙失效 |
| `ping` | `{t}` | 心跳 |

`alert.level`：`info`/`warning`/`error`。同一 `code` 在 60 秒内只推一次，避免刷屏。

---

## 7. 限流汇总

| 端点 | 限制 | 维度 |
|---|---|---|
| `POST /api/auth/login` | 20 次 / 15 分钟 | IP |
| 登录失败 | 5 次 → 锁 15 分钟 | IP + username |
| `POST /api/tasks` | 10 次 / 分钟 | 用户 |
| `POST /api/tasks/{id}/download-token` | 20 次 / 分钟 | 用户 |
| `GET /api/tasks/{id}/file` | 并发 2 | 用户 |
| `GET /api/events` | 并发 3 | 用户 |
| 其他 `GET` | 120 次 / 分钟 | IP |
| 其他写操作 | 60 次 / 分钟 | 用户 |

超限统一 `429` + `Retry-After` 头。

---

## 8. 版本与兼容

- 第一版不引入 `/v2` 前缀；破坏性变更随主版本升级；
- 前端在 `GET /api/auth/me` 中读取 `server.version`，与构建期注入的版本不一致时提示"服务端已更新，请刷新"；
- 所有新增字段必须是可向后兼容的（可空/可选），删除字段需跨两个版本先弃用。
