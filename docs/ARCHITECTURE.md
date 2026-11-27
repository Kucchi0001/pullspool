# PullSpool 架构设计（P0 定稿）

> 版本：1.0.0-draft　状态：待评审　最后更新：2026-11-26

本文档是 PullSpool 第一版的架构契约。后续所有代码、配置、测试都必须与本文一致；如需偏离，先改本文并记录到[附录 A 决策记录](#附录-a决策记录与需求书偏差)。

---

## 1. 项目定位

PullSpool 是部署在 Linux VPS 上的**个人远程下载与文件回传系统**。

用户在自己的电脑或手机浏览器里提交 URL，VPS 用自身公网出口抓取该文件并落盘暂存；下载完成后，用户通过 VPS 提供的地址把文件流式取回本地，确认保存成功后由用户触发清理，VPS 删除临时文件。

三条不可违背的产品红线：

1. **不做流量代理**：不是 VPN、SOCKS5、HTTP 代理，用户设备的其他网络请求不经过 VPS，也不需要配置系统代理。
2. **不做直传转发**：文件必须完整落在 VPS 磁盘上并记录校验值，不允许"边下边转"给用户。
3. **不自动判定取回成功**：浏览器无法可靠告知"文件已写入用户磁盘"。只认用户显式点击「确认取回并删除」，绝不因为下载链接被打开、HTTP 请求结束、连接断开而删除文件。

关键推论：

- 目标网站看到的是 **VPS 的公网出口 IP**，不是用户设备的 IP。
- **下载阶段**（VPS ← 目标站）和**回传阶段**（用户 ← VPS）是两段独立的网络传输，必须分开计量。
- 删除后 **SHA-256 仍保留**在数据库和历史页面，供用户校验本地副本。

---

## 2. 核心工作流

```
① 用户提交 URL
        │
        ▼
② 后端校验 + 预检（SSRF 五层，见 §12）
        │
        ▼
③ 创建任务记录 + 独立目录，交给 aria2 下载
        │
        ▼
④ 轮询 aria2 同步进度 → 完成后校验（存在/大小/SHA-256）→ 状态 completed
        │
        ▼
⑤ 用户点击「取回」→ 后端流式回传（支持 Range/断点续传），逐字节计量
        │
        ▼
⑥ 用户点击「确认取回并删除」→ 幂等删除 → 记录 retrieved_at / deleted_at
```

除此之外还有一条兜底路径：等待取回超过 `retention_hours`（默认 24 小时）的任务，由后台清理任务自动过期删除，并记录 `deleted_reason=expired`。

---

## 3. 组件与职责

| 组件 | 技术 | 职责 | 对外暴露 |
|---|---|---|---|
| `caddy` | Caddy 2.8+ | TLS 终结、HTTP→HTTPS 跳转、反向代理到 frontend | **仅此容器发布 18080 / 18443** |
| `frontend` | Vue 3 + Vite 构建 → nginx 1.27 | 提供 SPA 静态资源；`/api` 反代到 backend；SSE/Range 透传 | 否（仅 `edge`/`app` 网络） |
| `backend` | Python 3.12 + FastAPI + SQLAlchemy + SQLite | 鉴权、任务生命周期、队列调度、aria2 RPC、预检、SSRF 策略、文件回传、SHA-256、清理、系统监控 | 否（仅 `app`/`core`/`egress`） |
| `aria2` | aria2 1.37.0（自建 Alpine 镜像） | 真正的下载引擎（HTTP/HTTPS） | 否（RPC 仅 `core` 网络可达） |

设计取舍：

- **只为 caddy 发布端口**。backend 的 8000、aria2 的 6800、frontend 的 80 一律不映射到宿主机，杜绝"调试时不小心暴露 RPC"。
- **frontend 用 nginx 而不是让 Caddy 直接托管静态文件**：因为 Caddy 是可选的（用户已有反代时可整块移除），去掉 Caddy 后 frontend 必须能自己发布 HTTP。
- **aria2 用自建镜像**：需要入口脚本注入出站防火墙规则（§12.4），并固定 1.37.0 版本。

---

## 4. 部署拓扑

```
                       Internet
                          │
          ┌───────────────┴────────────────┐
          │                                │
   18080 / 18443                    出站（egress 网络）
          │                                │
     ┌────▼─────┐                    ┌─────▼──────┐
     │  caddy   │                    │   aria2    │
     └────┬─────┘                    │ +iptables  │
          │ edge                     └─────┬──────┘
   ┌──────┴───────┐                        │ core（internal）
   │              │                        │
┌──▼───────┐  ┌───▼──────┐◄────────────────┘
│ frontend │  │ backend  │──── egress ──► Internet（预检）
│  nginx   │  │ FastAPI  │
└──┬───────┘  └──────────┘
   │ app
   └──────────────► backend
```

| 网络 | 驱动 | `internal` | 成员 | 说明 |
|---|---|---|---|---|
| `pullspool_edge` | bridge | 否 | caddy, frontend | 唯一承载 HTTP 入站的网络 |
| `pullspool_app` | bridge | 否 | frontend, backend | 仅承载 nginx → backend 的 API 流量 |
| `pullspool_core` | bridge | **是** | backend, aria2 | 无出网能力，只用于 RPC |
| `pullspool_egress` | bridge | 否 | backend, aria2 | 出网专用，不挂任何其他服务 |

`core` 设为 `internal: true`：它没有网关，容器在该网络上无法访问外部，只能与同网络容器互通。这保证即使 aria2 RPC 监听 `0.0.0.0`，也只有 backend 能访问到。

`app` 把 backend 从 `edge` 上摘出来：caddy 只与 frontend 同网，即使 caddy 被攻破也无法直连 backend 的 8000 端口（实测 `caddy` 容器内解析不到 `backend`）。frontend 则只通过 `app` 访问 backend，它同样解析不到 `aria2`。

aria2 同时挂在 `core` 与 `egress`：RPC 走 `core`，真实下载走 `egress`。`egress` 上没有其他服务，因此 aria2 即使被 SSRF 绕过，也只能打到宿主/公网，打不到 frontend、caddy、backend。

### 4.1 持久化卷

宿主机 `./data/`（可用 `.env` 的 `DATA_DIR` 改）：

| 宿主机路径 | 容器内路径 | 用途 |
|---|---|---|
| `./data/db/` | `/data/db/` | SQLite 主库 + WAL |
| `./data/downloads/` | `/data/downloads/`（backend 与 aria2 **使用同一路径**） | 下载文件根目录（每个任务一个子目录） |
| `./data/aria2/` | `/aria2/` | aria2 session、RPC 密钥、出口防火墙状态 |
| `./data/caddy/` | `/data/`（caddy 内置卷） | Caddy 证书、internal CA |
| `./data/bootstrap-admin.txt` | — | 首次启动生成的管理员初始密码（0600，改密后自动删除） |

> 路径约定：backend 通过 aria2 RPC 传入的 `dir` 必须是 **aria2 容器内的路径**。两边统一挂载到 `/data/downloads`，避免出现 backend 写 `/data/downloads` 而 aria2 只认 `/downloads` 的错位（P7 实测中真实踩到过）。

容器重建、镜像升级、`docker compose down`（不带 `-v`）都不会丢数据。**只有显式删除 `./data/` 才会丢。**

---

## 5. 端口与访问矩阵

| 端口 | 归属 | 监听位置 | 是否发布到宿主机 | `.env` 变量 |
|---|---|---|---|---|
| 18080 | caddy | 容器内 18080 | 是（`HTTP_ENABLED=true` 时） | `HTTP_PORT` |
| 18443 | caddy | 容器内 18443 | 是（`HTTPS_ENABLED=true` 时） | `HTTPS_PORT` |
| 80 | frontend(nginx) | 容器内 80 | 否 | — |
| 8000 | backend(uvicorn) | 容器内 8000 | 否 | `BACKEND_PORT`（仅容器内） |
| 6800 | aria2 RPC | 容器内 6800 | **否（永不发布）** | `ARIA2_RPC_PORT`（仅容器内） |

`HTTP_ENABLED` 与 `HTTPS_ENABLED` 相互独立，但必须至少开启一个，否则 preflight 直接报错退出。

> 注意：Compose 无法按 env 条件增删 `ports`，因此两个端口映射始终存在；关闭某个协议时，Caddy 不监听该端口，连接会被 RST，效果等同关闭。需要"物理上完全不占端口"时，用 `docker-compose.override.yml` 删除对应映射（INSTALL.md 给了示例）。

### 5.1 TLS 模式

| `TLS_MODE` | 站点地址 | 证书 | 适用 |
|---|---|---|---|
| `off` | `http://{$TLS_HOST}:{$HTTP_PORT}` | 无 | 纯内网/SSH 隧道调试，**密码明文过网**，默认禁止用于公网部署（preflight 警告） |
| `internal` | `https://{$TLS_HOST}:{$HTTPS_PORT}` | Caddy 内置 CA 为 `TLS_HOST` 签发 | 只有 IP 没有域名（本项目当前阶段） |
| `acme` | `https://{$DOMAIN}` | Let's Encrypt 自动签发 | 有域名且 80/443 可达（以后发布时切换） |

`TLS_HOST` 默认取 `PUBLIC_IP`。IP 变化、或以后绑定域名，只改 `.env` 后 `docker compose up -d` 即可，不改代码。

`internal` 模式下，Caddy 的根证书位于宿主机 `./data/caddy/data/caddy/pki/authorities/local/root.crt`，装到电脑/手机后不再告警（INSTALL.md 有各平台导入步骤）。

实现要点（P7 实测后补充）：

- `internal` 模式必须在 Caddy 全局块声明 `http_port` / `https_port`，并且**只关闭自动跳转**（`auto_https disable_redirects`）而不是整个 `auto_https off`——后者会导致 Caddy 根本不签发内部证书，握手直接失败；
- 浏览器对 IP 字面量**不发送 SNI**，因此必须设置 `default_sni {$TLS_HOST}`，否则无 SNI 的握手拿不到证书（`tlsv1 alert internal error`）；
- HTTP → HTTPS 使用 308，保留非 GET 请求的方法与请求体。

---

## 6. 配置分层

| 层 | 载体 | 例子 | 修改方式 |
|---|---|---|---|
| 基础设施配置 | `.env` | 端口、TLS、数据目录、UID/GID、aria2 RPC secret、日志级别 | 改 `.env` → `docker compose up -d` |
| 运行时设置 | 数据库 `settings` 表 | 并发数、限速、配额、过期时间、主题 | 页面「设置」→ 立即生效（少数需重启） |
| 常量 | 代码 | 状态枚举、错误码、分流阈值 | 发版 |

`.env` 里不得出现业务默认值（如"最大并发数"），避免同一配置两处定义。

---

## 7. 数据流

### 7.1 创建任务

```mermaid
sequenceDiagram
    participant U as 浏览器
    participant B as backend
    participant A as aria2
    U->>B: POST /api/tasks {url, 选项}
    B->>B: 鉴权 / 限流 / 参数校验
    B->>B: URL 规范化 + L1/L2 校验（§12）
    B->>B: 配额检查（并发/磁盘/单文件上限）
    B->>B: 写 tasks 行（status=queued）
    B->>B: 调度器分配槽位（§9）
    B->>B: 预检：钉 IP、手动跟重定向、取文件名/长度/类型（L3）
    B->>B: 建任务目录、净化文件名、落 stored_relpath
    B->>A: aria2.addUri(final_url, {dir,out,split,max-download-limit})
    A-->>B: gid
    B->>B: status=active, aria2_gid=gid, started_at
    B-->>U: 201 {task}
```

失败处理：

| 阶段失败 | 处理 |
|---|---|
| URL 非法 / SSRF 命中 | 不建任务，返回 400 `URL_INVALID` / 403 `SSRF_BLOCKED` |
| 配额不足 | 不建任务，返回 409 `QUOTA_EXCEEDED` / 428 `DISK_FULL` |
| 预检超时 / 目标 4xx/5xx | 任务转 `failed`，保留 `error_code`，用户可重试 |
| aria2 不可达 | 任务留在 `queued`，`error_code=ARIA2_UNAVAILABLE`，调度器退避重试 |

**幂等性**：同一用户 10 分钟内提交完全相同的 URL 时，返回已有任务（200，`duplicate=true`），不重复下载。

### 7.2 进度同步

- 单个后台任务（asyncio Task）每 **1 秒**批量调用一次 `aria2.tellStatus`，一次传入所有活动 gid，避免 N 次 RPC。
- 内存中维护运行时状态（速度、瞬时进度），**每 2 秒批量落库一次**（单写者），减少 SQLite 写放大。
- 通过 SSE 推送给所有在线客户端；客户端每 10 秒轮询 `/api/tasks` 作为兜底。
- 速度采用 3 秒滑动窗口，避免抖动；`eta = (file_size - downloaded_size) / speed`，分母为 0 时返回 `null`。

### 7.3 完成与校验

aria2 报 `status=complete` 后，任务进入 `verifying`：

1. `stat` 文件，必须存在且不是符号链接；
2. 文件大小必须 `>0` 且 ≤ `max_file_size_bytes`；若 `file_size` 已知，必须与磁盘大小一致（允许 0 字节偏差）；
3. 流式计算 SHA-256（1 MiB 分块，`asyncio.to_thread`，不阻塞事件循环）；
4. 校验通过 → `status=completed`、写 `completed_at`、`sha256`、`expires_at = completed_at + retention_hours`；
5. 校验失败 → `status=failed`、`error_code=FILE_INTEGRITY_FAILED`，**保留文件**供人工排查，不进入可取回状态。

> 对 HTTP 而言，服务器无法证明"源文件本身正确"。这里的"完整性"= 实际字节数与元数据一致 + 文件可读 + 自算哈希入库。目标站若在响应头提供 `Digest` / `X-Checksum-Sha256`，仅记录并做**可选**比对，不阻断下载。

### 7.4 回传

`GET /api/tasks/{id}/file`：

- 鉴权：会话 Cookie，或一次性下载令牌 `?token=`（`POST /api/tasks/{id}/download-token` 签发，绑定 task_id + 过期时间，HMAC-SHA256）。
- 支持 `Range: bytes=start-end`、`If-Range`（基于 `ETag`）、返回 `206` + `Content-Range`；不满足范围返回 `416` + `Content-Range: bytes */size`。
- 流式读取 256 KiB 块，**不把文件读进内存**；每块累加 `upload_bytes` 并更新 `traffic_daily('up')`。
- 响应头固定为 `application/octet-stream`，避免 iOS Safari 对 PDF/图片/视频做预览劫持；文件名用 RFC 5987 `filename*=UTF-8''...` 并附 ASCII 回退名。
- 并发回传上限默认 2；超过返回 429 `RATE_LIMITED`。
- **回传进行中禁止删除**：`ack` 或清理遇到活动传输返回 409 `TRANSFER_IN_PROGRESS`。

### 7.5 确认取回并删除

`POST /api/tasks/{id}/ack`：

1. 校验任务归属、状态（必须 `completed`）；
2. 若该任务有活动传输 → 409 `TRANSFER_IN_PROGRESS`；
3. 事务内条件更新 `deleted_at IS NULL`（防并发双击）；
4. 校验路径：`realpath(stored_path)` 必须在下载根目录内、不是符号链接、父目录名等于 task id；
5. 删除任务目录（含 `.aria2` 控制文件）；
6. 写 `retrieved_at`、`deleted_at`、`deleted_reason=user_ack`，追加 `task_events`；
7. 返回任务（含 `sha256`，用户可留档校验）。

**幂等**：重复调用返回 200 + 相同状态，不再执行删除，不报错。

### 7.6 过期清理与孤儿清理

| 清理器 | 周期 | 动作 |
|---|---|---|
| 过期清理 | 每 10 分钟（`CLEANUP_INTERVAL_SECONDS`） | `completed` 且 `deleted_at IS NULL` 且 `expires_at < now()` 且无活动传输 → 走 §7.5 的删除路径，`deleted_reason=expired` |
| 孤儿文件 | 每 10 分钟（与过期清共同一轮） | 下载根目录下存在、但数据库无对应 `tasks.id` 的目录 → 移入 `./data/downloads/.orphan/{ts}-{name}/`，隔离 `orphan_quarantine_hours`（默认 24 小时）后删除 |
| 会话清理 | 每 10 分钟 | 过期或已撤销超过 `session_retention_days`（默认 7 天）的会话行 |

孤儿目录**先隔离再删**，避免因为数据库短时不可用导致误删用户文件。

---

## 8. 任务状态机

### 8.1 持久状态（6 个）

| 状态 | 含义 | 是否有文件 |
|---|---|---|
| `queued` | 等待中（排队或等待 aria2） | 可能已有部分 |
| `active` | 下载中 | 部分 |
| `paused` | 已暂停 | 部分 |
| `verifying` | 下载完成，正在校验 | 完整 |
| `completed` | 校验通过，可取回 | 完整（直到删除） |
| `failed` | 下载或校验失败 | 可能有残留 |
| `canceled` | 用户取消 | 取决于是否勾选删除文件 |

> 注：需求书 4.3 列出 11 个状态，其中「下载完成 / 等待取回 / 正在回传 / 已取回 / 已删除」是同一批数据的**投影**，不是独立存储状态。映射见 §8.3。

### 8.2 转换图

```mermaid
stateDiagram-v2
    [*] --> queued: 创建
    queued --> active: 调度器分配槽位
    queued --> canceled: 取消
    active --> paused: 暂停
    paused --> active: 恢复
    active --> verifying: aria2 完成
    active --> failed: 错误/超时/超限
    active --> canceled: 取消
    paused --> canceled: 取消
    failed --> queued: 重试
    verifying --> completed: 校验通过
    verifying --> failed: 校验失败
    completed --> completed: ack / 过期（写 deleted_at）
    canceled --> [*]
```

非法转换（一律 409 `TASK_STATE_CONFLICT`）：`completed → active`、`completed → paused`、`canceled → *`、`failed → active`（必须先 retry 变 `queued`）。

### 8.3 界面状态映射

| 界面状态 | 判定条件 | 中文 | 颜色 |
|---|---|---|---|
| `downloading` | `status=active` | 下载中 | 蓝 |
| `queued` | `status=queued` | 等待中 | 灰 |
| `paused` | `status=paused` | 已暂停 | 灰 |
| `verifying` | `status=verifying` | 校验中 | 蓝（脉冲） |
| `transferring` | `status=completed` 且活动传输 > 0 | 正在回传 | 蓝 |
| `ready` | `completed` 且 `deleted_at IS NULL` 且无活动传输 | 等待取回 | 绿 |
| `retrieved` | `retrieved_at IS NOT NULL` | 已取回 | 灰绿 |
| `deleted` | `deleted_at IS NOT NULL`（`expired` 或无 `retrieved_at`） | 已删除 | 灰 |
| `failed` | `status=failed` | 下载失败 | 红 |
| `canceled` | `status=canceled` | 已取消 | 灰 |
| `expired` | `deleted_at` 且 `deleted_reason=expired` | 已过期清理 | 橙灰 |

时间戳语义：

- `created_at`：创建任务；
- `started_at`：首次进入 `active`；
- `completed_at`：校验通过（即"下载完成时间"，界面展示这个）；
- `retrieved_at`：用户点击「确认取回并删除」的时刻；
- `deleted_at`：文件实际删除完成的时刻；
- `expires_at`：`completed_at + retention_hours`，用于倒计时与清理。

---

## 9. 队列调度

**由后端调度，不依赖 aria2 内置队列**。理由：需要动态改并发、按磁盘配额整体暂停、失败退避重试、按优先级插入，aria2 的运行期参数修改能力不足以支撑。

规则：

1. 调度循环每 2 秒运行一次；
2. 可用槽位 = `max_concurrent_downloads - count(status in (active, verifying))`；
3. 从 `queued` 中按 `created_at` 升序取任务（FIFO），受"磁盘剩余 ≥ min_free_disk_bytes 且 已用配额 + 预估大小 ≤ max_total_storage_bytes"约束；
4. 分配槽位 → 执行预检 → `addUri` → `active`；
5. `active` 数达上限时，新任务保持 `queued`（SSE 推 `task.updated`）；
6. 磁盘不足时，**暂停整个队列**并广播 `alert` 事件，界面顶部出现红色横幅；空间恢复后自动继续；
7. 失败重试：仅对可重试错误（超时、连接重置、5xx、aria2 内部错误）按 10s/30s/90s 退避，`attempts` ≤ 3；403/404/410/文件超限/SSRF 命中不重试。

aria2 侧 `max-concurrent-downloads` 设为 `max_concurrent_downloads + 2` 作为兜底，防止后端调度器异常时任务全部卡住。

---

## 10. 重启与异常对账

后端启动顺序：等数据库可用 → 等 aria2 健康（最多 60 秒）→ 对账 → 启动后台任务（轮询/调度/清理/SSE）。

### 10.1 对账矩阵

| 场景 | 检测方式 | 处理 |
|---|---|---|
| backend 重启，aria2 存活 | 对每个 `active`/`paused`/`queued` 任务查 `tellStatus(gid)` | 按 aria2 状态回填；`complete` → 进 `verifying`；`error` → `failed` 或重试；`removed` → 重新提交 |
| aria2 重启（session 丢失） | `tellStatus` 返回 gid 不存在 | 用 `url` + `--continue=true` + 相同 `dir/out` 重新 `addUri`，写回新 gid |
| 主机重启 | 先等 aria2 健康，再对账 | 同上，并清理 `.aria2` 残片、跑一次孤儿扫描 |
| 数据库有记录、文件不存在（`completed`） | 启动时 `stat` | 标记 `failed` + `FILE_NOT_FOUND`，**绝不显示为可取回** |
| 磁盘有目录、数据库无记录 | 孤儿扫描 | 移入 `.orphan/`，24 小时后删除 |
| 文件大小与数据库不一致 | `stat` vs `downloaded_size`/`file_size` | 以磁盘为准重算；若 `completed` 且不一致 → `failed` |
| `downloaded_size` 大于磁盘实际 | `stat` | 以磁盘为准，避免进度条超过 100% |
| 用户取消但 aria2 仍在跑 | 对账 | `aria2.remove` + `forceRemove` 后再删文件 |
| 用户重复点删除 | 条件更新 `deleted_at IS NULL` | 第二次直接返回当前状态（幂等） |
| 备份恢复后 gid 全部失效 | 启动对账 | 全部按"重新提交"处理 |
| 磁盘写满 | aria2 错误码 + 定时 `disk_usage` | 任务 `failed(DISK_FULL)`，队列暂停，广播 `alert` |

### 10.2 健康检查

| 容器 | 检查 |
|---|---|
| backend | `GET /api/health` 返回 200 且 `db=ok`；`start_period` 40 秒 |
| frontend | `wget -q -O /dev/null http://127.0.0.1/` |
| caddy | `wget -q -O /dev/null http://127.0.0.1:${HTTP_PORT}/`（HTTPS-only 模式跳过） |
| aria2 | `aria2c` 无内置健康端点，由 backend 的 `/api/health` 间接反映；容器本身用进程存活 + `wget` RPC 探测（带 secret） |

`restart: unless-stopped`；`depends_on` 用 `condition: service_healthy` 编排。

---

## 11. 文件与路径安全模型

核心原则：**用户输入永远不参与路径拼接**。

1. 任务目录名 = 服务端生成的 UUID：`{download_root}/{task_id}/`；
2. 文件名只作为**该目录内的名字**，净化流程：
   - Unicode NFC 归一化 → 去除控制字符与 `/ \ : * ? " < > |` → 去除首尾空格与点 → 截断到 180 字节（按 UTF-8 边界）→ 空名 fallback 为 `download.bin`；
   - 追加去重后缀 ` (1)`、` (2)`，最长 3 次，之后改用 `{stem}-{8位随机}{ext}`；
3. `stored_relpath` 只存相对路径，读取时 `root.joinpath(rel).resolve()` 必须 `is_relative_to(root.resolve())`；
4. 删除前额外检查：`lstat` 不是符号链接、父目录名等于 task id、`realpath` 在根内；
5. 下载根目录在启动时校验：必须是绝对路径、存在、可写、不是 `/`、不是符号链接；
6. 每个任务目录单独 `mkdir(mode=0o750)`，容器内以非 root 用户运行（`PULLSPOOL_UID:1000`）；
7. 限制单文件大小与总配额（§15），防止磁盘打满。

---

## 12. SSRF 防护（五层）

威胁模型：攻击者能控制 URL 与目标站行为，目标是让 VPS 访问内网服务（Docker 网络内的 backend/aria2、宿主机、云元数据 `169.254.169.254` 等）或把内网内容下载回来。

### 12.1 L1 URL 规范化与表观校验

- 只允许 `http` / `https`（显式拒绝 `file`、`ftp`、`gopher`、`data`、`magnet`）；
- 拒绝空 host、非法端口、超长 URL（> 4096）；
- 拒绝 userinfo（`http://user:pass@host/`）——避免日志泄露与解析歧义；
- 异常 IP 表示法：纯数字主机（`http://2130706433/`）、十六进制（`0x7f.1`）、八进制（`0177.0.0.1`）、带尾点、`[::1]`、IPv4 映射 `::ffff:127.0.0.1`——凡"看起来是 IP 但 `ipaddress` 解析失败"一律拒绝；
- 单标签主机名（`http://intranet/`）拒绝；
- 保留域名拒绝：`localhost`、`*.localhost`、`*.local`、`*.internal`、`*.lan`、`*.home.arpa`、`metadata.google.internal`、`instance-data`；
- IDN 用 `idna` 转 punycode，转换失败拒绝。

### 12.2 L2 DNS 解析检查

- 解析全部 A/AAAA 记录（`getaddrinfo`，去重）；
- 每条记录都要通过黑名单：回环 `127/8`、`::1`、私网 `10/8`、`172.16/12`、`192.168/16`、链路本地 `169.254/16`、`fe80::/10`、CGNAT `100.64/10`、ULA `fc00::/7`、组播、保留段、`0.0.0.0`、`::`、文档段、云元数据 IP；
- 解析失败或结果为空 → 拒绝；
- 记录解析结果供 L3 钉住使用。

### 12.3 L3 固定 IP 预检

- 用带自定义 resolver 的 `aiohttp` 连接器，把连接钉在**已校验的 IP** 上，同时用原域名做 Host 与 TLS SNI（防 DNS rebinding）；
- `allow_redirects=False`，**手动**跟随最多 5 跳，每一跳都重新执行 L1 + L2 + 钉 IP；
- 支持 `HEAD`，若目标不支持 HEAD 则回退到 `GET Range: bytes=0-0`，立即关闭连接；
- 提取文件名（`Content-Disposition` 优先，其次 URL path）、`Content-Length`、`Content-Type`、`ETag`、`Last-Modified`、是否支持 Range；
- 校验 `Content-Length` 是否超过 `max_file_size_bytes`。

### 12.4 L4 aria2 出站防火墙（真正的兜底）

aria2 自己解析 DNS、自己跟随重定向，后端无法代理它的连接，因此加一层网络级限制：

- 容器入口脚本在 `iptables` 的 `OUTPUT` 链插入规则，顺序为：放行 `ESTABLISHED,RELATED`（否则 RPC 回包与端口转发会被误伤）→ 放行容器实际配置的 DNS 解析器（从 `/etc/resolv.conf` 读取，Linux 宿主通常是 `127.0.0.11`，Docker Desktop 是 `192.168.65.x`）→ 放行回环 → 对私网/回环/链路本地/元数据/组播段 `REJECT`；
- `conntrack` 不可用时回退到 `state` 模块；两条路径都失败则视为防护失效；
- 需要 `cap_add: [NET_ADMIN]`，入口脚本以 root 应用规则后用 `su-exec` 降权到 `aria2` 用户运行主进程；
- `ARIA2_EGRESS_GUARD=on|off` 控制；关闭时 SECURITY.md 必须标注"只剩 L1–L3，存在 TOCTOU 风险"；
- 规则应用失败时：容器仍启动（不阻断服务），但 `/api/health` 返回 `degraded`，并在界面顶部显示持久警告。

> 这是五层里唯一能堵住"预检时正常、aria2 下载时跳内网"的 TOCTOU 缺口的机制。IP 判定与 DNS rebinding 的残余风险在 SECURITY.md 中完整披露。

### 12.5 L5 落地复检

见 §7.3 与 §11：路径、符号链接、大小、`.aria2` 残片、SHA-256。

### 12.6 已知残余风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 出站防火墙不可用 | 部分加固内核/宿主禁用 `NET_ADMIN` | 健康检查降级 + 界面警告 + 文档说明 |
| 目标站对预检与 aria2 返回不同内容 | L3 校验过的 URL 在 aria2 抓取时 302 到内网 | L4 拦截；L1–L3 缩小窗口 |
| DNS 污染 | 解析到错误 IP | 概率低；L2 对解析结果做私网判定 |
| 目标站重定向到公网大文件 | 拖满磁盘 | 单文件上限 + 总配额 + 最低剩余空间 |

---

## 13. 流量统计口径

**明确定义：全部是应用层统计，不是运营商账单数据。**

| 指标 | 来源 | 精度 |
|---|---|---|
| 下载流量（VPS 入站） | aria2 `completedLength`，任务完成时一次性计入 `traffic_daily('down')` | 精确到字节，含重试重下的部分 |
| 回传流量（VPS 出站） | 流式响应实际写入 ASGI 的字节数，逐块累加 | 精确到字节；客户端中途断开时只计已发送部分 |
| 今日 / 本月 | `traffic_daily` 按本地日期聚合（`TZ` 环境变量，默认 `Asia/Shanghai`） | 日切按本地 00:00 |
| 单任务流量 | `tasks.download_bytes_counted` / `upload_bytes_counted` | 累计值 |
| 网卡总量（仅展示参考） | `psutil.net_io_counters()` | 收/发总量，**无法拆分任务，界面需标注"含系统开销"** |

不把网卡数据当作业务流量；界面上"应用层统计"与"网卡总计"分开显示并各带说明。

---

## 14. 鉴权与会话

- 密码：**Argon2id**（`argon2-cffi`，默认参数 `time_cost=3, memory_cost=64MiB, parallelism=4`，在 1 vCPU 上单次约 60–120ms），登录成功后可后台重哈希升级参数；
- 首次启动：数据库无用户时生成 32 字符随机密码 → 写 `./data/bootstrap-admin.txt`（0600，容器内 chmod）→ 日志只输出"初始密码已写入 data/bootstrap-admin.txt"；登录后除改密接口外全部返回 403 `PASSWORD_CHANGE_REQUIRED`，改密成功后文件删除；
- 会话：32 字节随机 token，Cookie `ps_session`（`HttpOnly`、`SameSite=Lax`、`Secure` 由 `X-Forwarded-Proto` 自动判定、`Path=/`），数据库只存 SHA-256 哈希；空闲 7 天 / 绝对 30 天过期；改密撤销其他所有会话；
- CSRF：`SameSite=Lax` + 对所有非 GET 请求校验 `Origin`（缺失则 `Referer`）主机必须匹配请求 Host 或 `PUBLIC_BASE_URL`；
- 暴力破解：按 `IP + username` 计数，5 次失败锁 15 分钟，指数退避，`429 AUTH_LOCKED` 带 `retry_after`；
- 日志脱敏：URL 只记 `scheme://host/path[:40]`，query 一律 `?***`；密码、token、Cookie、aria2 secret 永不入日志；`Authorization`/`Set-Cookie` 头过滤。

---

## 15. 资源预算与默认参数

目标机器：1 vCPU / 1 GB RAM / 20 GB 磁盘。

| 容器 | 内存上限 | 典型占用 | CPU |
|---|---|---|---|
| backend | 320 MB | 80–140 MB | 空闲 <1% |
| aria2 | 256 MB | 20–40 MB | 空闲 ~0% |
| frontend (nginx) | 64 MB | 8–15 MB | ~0% |
| caddy | 96 MB | 30–50 MB | ~0% |
| 合计 | 736 MB | 150–250 MB | — |

镜像体积（P7 实测，linux/amd64）：backend ≈ 284 MB、frontend ≈ 74 MB、aria2 ≈ 36 MB、caddy 官方镜像 ≈ 92 MB。

容器闲置资源实测（本机 Docker Desktop，`docker stats` 快照）：backend 78 MB / 1.1% CPU、aria2 5 MB / 0.01%、frontend 3.3 MB / 0%、caddy 13 MB / 0%。VPS 上的数值会随内核与负载略有差异，P9 会补充目标机实测。

默认设置（可在设置页/数据库调整）：

| 键 | 默认值 | 说明 |
|---|---|---|
| `max_concurrent_downloads` | 2 | 同时下载任务数 |
| `default_connections` | 4 | 单任务连接数（aria2 `split`） |
| `default_speed_limit_kib_per_s` | 0（不限速） | 0 = 不限 |
| `global_speed_limit_kib_per_s` | 0 | 全局限速 |
| `max_file_size_bytes` | 8 GiB | 单文件上限 |
| `max_total_storage_bytes` | 15 GiB | 下载目录配额 |
| `min_free_disk_bytes` | 2 GiB | 低于此值暂停队列 |
| `retention_hours` | 24 | 等待取回过期时间 |
| `orphan_quarantine_hours` | 24 | 孤儿目录隔离时长 |
| `download_token_ttl_seconds` | 1800 | 回传令牌有效期 |
| `max_transfer_concurrency` | 2 | 同时回传数 |
| `session_idle_days` | 7 | 会话空闲过期 |
| `session_absolute_days` | 30 | 会话绝对过期 |
| `login_max_attempts` | 5 | 登录失败阈值 |
| `login_window_minutes` | 15 | 失败统计窗口 |
| `login_lock_minutes` | 15 | 锁定时长 |
| `density` | `comfortable` | 界面密度 |

---

## 16. 技术选型与版本

| 组件 | 选型 | 版本策略 |
|---|---|---|
| Python | 3.12-slim-bookworm | 固定小版本，随镜像 |
| FastAPI / Uvicorn | 最新稳定 | 依赖锁定于 `requirements.txt` |
| SQLAlchemy + aiosqlite | 2.x | Alembic 管理迁移 |
| Pydantic | 2.x | 设置与请求模型 |
| aiohttp | 3.x | 预检与 aria2 RPC（需要自定义 resolver） |
| argon2-cffi | 最新 | 密码哈希 |
| psutil | 最新 | CPU/内存/磁盘/网卡 |
| aria2 | **1.37.0**（2023-11 最后版本） | 上游长期停更，固定版本 + 内网隔离 + 出站防火墙 |
| Vue / Vite / Pinia / Vue Router | Vue 3.5+ / Vite 6+ | 无 UI 组件库，自建设计系统 |
| nginx | 1.27-alpine | 静态托管 + `/api` 反代 |
| Caddy | 2.8-alpine | TLS + 反代（可选） |
| SQLite | 3.45+ | WAL、`busy_timeout=5000`、`synchronous=NORMAL` |

依赖总数控制在：后端 ≈ 10 个直接依赖，前端 ≈ 5 个（vue、vue-router、pinia、lucide-vue-next、开发依赖）。

---

## 17. 目录结构（最终交付）

```
pullspool/
├── backend/
│   ├── app/
│   │   ├── api/            # auth.py tasks.py system.py settings.py events.py health.py
│   │   ├── core/           # config.py logging.py security.py errors.py rate_limit.py
│   │   ├── models/         # user.py session.py task.py event.py traffic.py setting.py
│   │   ├── schemas/        # auth.py task.py system.py settings.py common.py
│   │   ├── services/
│   │   │   ├── aria2_service.py       # JSON-RPC 客户端
│   │   │   ├── download_service.py    # 创建/调度/重试/取消
│   │   │   ├── transfer_service.py    # Range 流式回传 + 字节计量
│   │   │   ├── cleanup_service.py     # ack/过期/孤儿
│   │   │   ├── storage_service.py     # 路径/配额/文件名净化
│   │   │   ├── net_policy.py          # SSRF L1/L2：URL 规范化、IP 分类、DNS 校验
│   │   │   ├── preflight.py           # SSRF L3：钉 IP 预检、逐跳重定向校验
│   │   │   ├── security_service.py    # 会话加固与审计辅助
│   │   │   ├── integrity_service.py   # SHA-256
│   │   │   ├── settings_service.py    # 设置读写与校验
│   │   │   ├── monitor_service.py     # 系统状态/流量
│   │   │   ├── reconcile_service.py   # 启动对账
│   │   │   └── event_bus.py           # SSE 广播
│   │   ├── database/       # base.py session.py migrate.py
│   │   └── main.py
│   ├── alembic/            # versions/ env.py
│   ├── tests/              # 单元 + 集成 + e2e
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/     # 表格/状态标签/进度条/抽屉/Toast...
│   │   ├── views/          # Login Overview Downloads Ready History Settings
│   │   ├── router/ stores/ services/ styles/ locales/ composables/
│   │   └── main.ts App.vue
│   ├── tests/
│   ├── package.json vite.config.ts tsconfig.json
│   └── Dockerfile
├── docker/
│   ├── aria2/{Dockerfile,aria2.conf,entrypoint.sh,egress-guard.sh}
│   ├── nginx/{default.conf,nginx.conf}
│   └── caddy/{Caddyfile.http,Caddyfile.https,Caddyfile.both,entrypoint.sh}
├── scripts/{preflight.sh,smoke-test.sh,backup.sh,restore.sh,gen-selfsigned.sh}
├── data/                   # 运行期数据（.gitignore）
├── docs/{ARCHITECTURE,API,DESIGN,SCHEMA}.md
├── docker-compose.yml
├── .env.example
├── README.md
├── INSTALL.md
├── SECURITY.md
├── CHANGELOG.md
└── LICENSE (MIT)
```

---

## 18. 阶段计划与验收

| 阶段 | 产出 | 验收方式 |
|---|---|---|
| P0 | 本文档 + API/DESIGN/SCHEMA | 人工评审通过 |
| P1 | 后端骨架、配置、DB、迁移、鉴权、限流、日志 | pytest：鉴权 12 例 + 限流 6 例 |
| P2 | SSRF 五层、预检、本地测试服务器 | pytest：恶意 URL 40+ 例全部拦截 |
| P3 | aria2 容器、RPC、出口防火墙 | 真实下载 + 续传 + session 恢复 |
| P4 | 生命周期、队列、SSE、对账 | 中断/重启/取消/重试 12 例 |
| P5 | 回传、校验、ack、清理 | Range/416/幂等/过期 15 例 |
| P6 | 前端 6 视图、设计系统、响应式 | Playwright 截图 5 尺寸 × 2 主题 |
| P7 | 4 镜像 + compose + 3 模式 Caddy | 本机 `docker compose up` 实测 |
| P8 | 安全审计清单逐条验证 | 越权/穿越/CSRF/日志泄露 |
| P9 | 文档 + 验收报告 | 需求书第十四部分逐项打勾 |

---

## 附录 A：决策记录与需求书偏差

| # | 需求书原文 | 处理 | 原因 |
|---|---|---|---|
| 1 | 项目名 PullSpool / UI 名 VPS Fetch / 目录 vps-fetch | **统一为 PullSpool** | 用户确认；三处名字会导致镜像、文档、界面不一致 |
| 2 | 4.3 列 11 个状态 | 6 持久 + 派生投影（§8） | 11 个独立状态会形成状态爆炸，且"已取回/已删除"是同一条记录的时间戳 |
| 3 | 6.5 设置页可改"临时文件保存位置" | 只允许改下载根目录下的**子目录名**（相对路径），绝对路径由 `.env` 决定、界面只读 | 允许任意路径 = 给 UI 一个任意写/删路径的后门 |
| 4 | 2.3 四个容器（含可选 caddy） | 保持 4 个；Caddy 可通过 `docker-compose.caddy-off.yml` 整体移除，改由 frontend 发布端口 | 无 Caddy 时仍需 HTTP 可用 |
| 5 | 5.1 每次重定向都重新验证 | 后端手动跟跳逐跳校验（L3），aria2 只拿最终 URL；加 L4 防火墙兜底 | aria2 无 `--max-redirect` 参数（官方手册已核实） |
| 6 | 3.3 下载完成必须检查完整 | 字节数 + 可读 + SHA-256；源站哈希仅可选比对 | HTTP 场景下"源站哈希"不是通用契约 |
| 7 | 5.2 限制单文件大小 | 预检 `Content-Length` + 运行时轮询 `totalLength` 超限取消 + 磁盘配额硬闸 | aria2 无单文件大小上限参数 |
| 8 | 端口 18080/18443 与 ACME 80/443 冲突 | 文档给两种映射方案，不硬编码 | 保留需求书端口规范 |
| 9 | 第十部分未列改密/删除/SSE | 增补 4 个接口 + 1 个 SSE 通道 | UI 与 4.1/4.7 功能必须有对应接口 |
| 10 | 未定义"正在回传"如何持久化 | 内存态 + SSE 推送，不落库 | 连接级状态落库会因异常退出产生脏数据 |
| 11 | 未定义下载队列归属 | 后端调度器（§9） | 需要动态并发、配额暂停、退避重试 |
| 12 | 未定义流量统计口径 | 应用层双向计数（§13） | 网卡统计无法拆分任务 |
| 13 | 未定义首次管理员初始化方式 | 随机密码文件 + 强制改密 | 用户确认；避免密钥进 `.env`/日志 |
| 14 | 未说明 TLS 无域名时的方案 | `TLS_MODE=off/internal/acme` 三态 | 当前阶段只有 IP |
