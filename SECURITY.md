# PullSpool 安全说明

版本：1.0.0 ｜ 审计日期：2026-11-26 ｜ 适用部署：单机 Docker Compose（VPS）

PullSpool 把"用户浏览器 → 目标站点"的直接访问，改为"VPS 用自己的公网出口下载 → 用户从 VPS 取回"。
因此它同时承担两个安全角色：**面向公网的下载代理**（必须防 SSRF、防滥用）和**临时文件中转站**
（必须防越权读取、防路径穿越、防令牌泄露）。本文说明威胁模型、已实现的控制、实测结果、已知限制与部署清单。

> 说明：本版本经过代码审计、自动化测试与真实容器栈的对抗性验证，但**未经过第三方渗透测试**。
> 本文只声称"实测过的结论"，未测项会明确标注。

---

## 1. 威胁模型

### 1.1 资产

| 资产 | 位置 | 泄露后果 |
|---|---|---|
| 管理员密码哈希、会话 | `data/db/pullspool.db` | 账号完全接管 |
| 下载文件（临时） | `data/downloads/<task>/` | 隐私/商业文件泄露 |
| 下载令牌 | URL 查询串、日志 | 30 分钟内可下载对应文件 |
| aria2 RPC 密钥 | `data/aria2/secret` | 可操控下载引擎 |
| Caddy internal CA 私钥 | `data/caddy/data/caddy/pki/` | 可伪造该部署的 HTTPS 证书 |
| `.env` | 仓库根目录 | 含 RPC/令牌密钥与端口配置 |

### 1.2 信任边界

```
Internet ──► Caddy :18443 ──► nginx(frontend) ──► backend ──► aria2 ──► Internet
                                                                  (目标站点)
```

- 浏览器与 VPS 之间：HTTPS（internal CA 或 ACME）。
- backend 与 aria2 之间：Docker `core` 内部网络的 JSON-RPC，带 secret 鉴权。
- aria2 与目标站点之间：独立 `egress` 网络 + 容器内 iptables 出口白名单（L4）。

### 1.3 攻击者能力

覆盖：

- 未认证的互联网访问者（爆破、扫描、CSRF、越权尝试）；
- 已登录但怀有恶意的唯一用户（提交内网地址、构造文件名、滥用带宽）；
- 被攻陷或恶意构造的目标站点（重定向到内网、超大文件、慢速响应、错误 Content-Length、畸形文件名）；
- 能读取日志/备份但不能登录主机的低权限本机用户。

不覆盖：

- 宿主 root / Docker daemon 被攻陷；
- 物理访问、侧信道、供应链投毒；
- 目标站点本身对下载内容（如可执行文件）的恶意性——PullSpool 不查毒。

---

## 2. 已实现的安全控制

### 2.1 网络与容器隔离

| 控制 | 实现 |
|---|---|
| 最小暴露面 | 只有 `caddy` 发布端口；backend:8000、aria2:6800、frontend:80 **均不映射到宿主机**（P8 实测 `Get-NetTCPConnection` 无监听） |
| 四网络分段 | `edge`（caddy+frontend）、`app`（frontend+backend）、`core`（backend+aria2，`internal: true`）、`egress`（backend+aria2） |
| RPC 不可达 | aria2 只在 `core`/`egress`；frontend 与 caddy **解析不到** `aria2` |
| 横向移动限制 | caddy 与 backend 不同网，caddy 容器**解析不到** `backend` |
| 非 root | backend 以 UID 1000 运行；aria2 由 tini 启动后 `su-exec 1000:1000`；nginx 的 worker 进程为 `nginx` 用户；**caddy 官方镜像默认以 root 运行**（无额外 capability、无 Docker socket，见 R13） |
| 权限收紧 | 所有服务 `security_opt: no-new-privileges:true`；backend/aria2 `umask 077`，数据文件默认 0600、任务目录 0750 |
| 资源上限 | 每个容器独立 `mem_limit`/`cpus`，日志 `json-file` 10 MB × 3 |
| 无特权容器 | 仅 aria2 申请 `NET_ADMIN`（安装 iptables 规则所必需），无 `privileged`、无宿主 PID/网络命名空间 |

### 2.2 SSRF 纵深防御（L1–L5）

| 层 | 位置 | 内容 |
|---|---|---|
| L1 | `net_policy.py` | 只允许 `http/https`；拒绝 userinfo、空 host、非法端口、超长 URL；拒绝 IP 字面量中的 loopback/私网/链路本地/元数据/组播/保留段（IPv4 + IPv6） |
| L2 | `net_policy.py` | 对域名做 **A + AAAA 全记录**解析，任一条落在禁止网段即拒绝（防"公网域名解析到内网"） |
| L3 | `preflight.py` | HEAD/GET 预检时**固定已校验的 IP**，手动逐跳跟随 ≤5 次重定向，每一跳重新做 L1/L2；限制响应头大小、超时、声明大小；禁用系统代理（`trust_env=False`） |
| L4 | `egress-guard.sh` | aria2 容器内 iptables：`ESTABLISHED,RELATED` ACCEPT → 仅放行 `/etc/resolv.conf` 中的 DNS 与 `127.0.0.11:53` → 拒绝全部私网/loopback/link-local/169.254.169.254/组播（IPv6 同样） |
| L5 | `download_service.py` | 下载完成后按预检得到的 `content_length` 校验实际大小，不匹配即删除并置 `failed`；文件落在按 UUID 隔离的目录 |

L4 是"最后一米"：即使 L1–L3 被绕过（DNS rebinding、aria2 自行重解析），aria2 也连不到内网与云元数据。
guard 失败时状态文件写 `failed`，`/api/health` 的 `egress_guard` 字段会变为非 `ok`。

### 2.3 身份认证与会话

- 密码哈希：**Argon2id**（`time_cost=3`, `memory_cost=65536` KiB, `parallelism=4`），参数记录在哈希串中，可平滑升级。
- 密码策略：≥10 位，禁止纯数字/纯字母/常见弱口令（注册与改密都校验）。
- 初始管理员：默认 `admin` / `admin`，首次登录**强制改密**（改密前只能访问登录/改密/me），
  初始信息写入 `data/bootstrap-admin.txt`（0600），改密后删除；可用
  `BOOTSTRAP_ADMIN_PASSWORD` 在首次启动前覆盖默认密码。默认凭据窗口的风险见 R15。
- 会话令牌：`secrets.token_urlsafe(32)`（256 bit），**数据库只存 SHA-256 哈希**；Cookie `ps_session` 为 `HttpOnly; SameSite=Lax; Path=/; Secure`（HTTPS 时），默认 30 天绝对过期。
- 登录防爆破：同一用户名连续失败 5 次锁定 15 分钟；同一 IP 15 分钟内最多 20 次登录请求（`RATE_LIMITED`）。
- 改密后吊销该用户其他所有会话；登出立即吊销当前会话。
- 会话固定：每次登录生成全新令牌（实测两次登录 Cookie 不同）。

### 2.4 CSRF

- 所有非安全方法校验 `Origin`（缺失时回退 `Referer`），只接受 `PUBLIC_BASE_URL` 同源；跨站 `Origin` 直接 **403**。
- 现代浏览器发送 `Sec-Fetch-Site: cross-site` 时同样拒绝。
- 无 Cookie 的非浏览器客户端（curl/下载器）允许通过——它们无法借用受害者 Cookie。
- Cookie 使用 `SameSite=Lax`，跨站 POST 不会携带。

### 2.5 授权与越权

- 所有任务查询/操作都带 `user_id == 当前用户` 条件；不存在"按 ID 直接取任意任务"的路径。
- 任务 ID 为 UUID v4（122 bit 随机），不可枚举；非法/未知 ID 统一 404。
- 未认证访问任务、设置、系统状态、事件流、文件下载一律 401（实测 5 个端点）。
- 文件下载有两条等价路径：登录 Cookie，或 HMAC 下载令牌；两者都绑定任务 ID。

### 2.6 文件名与路径

- 任务目录 = `download_root/<uuid>`，UUID 经 `uuid.UUID()` 规范化并校验字符串完全一致（防大小写/编码变体）。
- 文件名清洗：把路径分隔符与非法字符替换为 `_`，去掉控制/格式字符与首尾的点、空格，保留 1–180 字节；空名回退 `download.bin`。内部的 `..` 只作为普通字符存在，无法构成路径分隔。
- 落盘前用 `realpath` 确认最终路径位于任务目录内；删除时同样校验，且只删任务目录。
- 实测：提交 `filename="../../evil.sh"` → 实际存储 `_.._evil.sh`，文件只在任务目录内，`data/evil.sh` 与 `data/downloads/evil.sh` 均不存在。

### 2.7 回传令牌

- HMAC-SHA256 签名，载荷含 `tid`（任务 ID）、`exp`（30 分钟）、`nonce`；密钥来自 `DOWNLOAD_TOKEN_SECRET` 或自动生成的 0600 文件。
- 校验使用 `hmac.compare_digest`（常量时间）；任务 ID 不匹配、签名错误、过期分别返回 `TOKEN_INVALID` / `TOKEN_EXPIRED`。
- 令牌只允许 `GET /api/tasks/{id}/file`；不提供写操作能力。
- 支持 Range（200/206/416）、`If-Range`、ETag；有活跃回传时拒绝删除任务（`TRANSFER_IN_PROGRESS`）。

### 2.8 速率限制与滥用防护

| 端点 | 限制 |
|---|---|
| 登录 | 20 次 / 15 分钟 / IP（另有 5 次失败锁定 / 用户名 / 15 分钟） |
| 创建任务 | 10 次 / 分钟 / IP |
| 签发下载令牌 | 20 次 / 分钟 / IP |
| 其余 API | 300 次 / 分钟 / IP（P8 新增，SSE 长连接不计入） |

另有资源型限制：同时下载数、全局/单任务限速、单文件大小上限、临时存储配额、最低剩余磁盘、排队上限。
这些限制是**单进程内存计数**，重启即清零，且不是 DDoS 防护（见 R5）。

### 2.9 日志与敏感信息

- 关闭 uvicorn 自带 access log（它会原样打印查询串），统一由 `RequestContextMiddleware` 输出结构化访问日志。
- 访问日志中的 URL 经 `redact_url()`：去掉 userinfo，query 统一显示为 `?***`，路径截断 48 字符。
- 全局日志格式化器再做一次 `redact()`：URL、`Bearer`、`password=/token=/secret=` 等键值对统一打码。
- `QueryRedactor` 过滤器额外挂在 `uvicorn.access` 上作为兜底（即使未来 uvicorn 重新启用 access log 也不会泄露 `?token=`）。
- 服务器端不记录请求体、不记录密码明文；登录失败记录 `登录失败 username=<用户名> ip=<来源> code=<原因>`，登录成功记录 `登录成功 username=<用户名> ip=<来源>`（实测密码 0 命中）。
- 敏感文件权限：`.token_secret`、`aria2/secret`、下载文件均 0600（`umask 077`）。
- **P8 修复的漏洞**：此前 uvicorn access log 会把下载令牌明文写入容器日志。修复后实测同一令牌在日志中 0 命中。

### 2.10 浏览器侧

nginx 对所有响应（含 SPA 入口与静态资源）下发：

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'none'; object-src 'none';
  base-uri 'self'; form-action 'self'; frame-ancestors 'none'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security: max-age=31536000   （仅 HTTPS）
Cross-Origin-Opener-Policy: same-origin      （API 响应）
```

内联主题脚本已移到 `/theme-init.js`，因此 `script-src` 不需要 `'unsafe-inline'`；`style-src` 保留
`'unsafe-inline'` 是因为 Vue 会写内联 `style` 属性（进度条宽度），这不构成脚本执行面。

### 2.11 注入类

- **SQL 注入**：所有查询通过 SQLAlchemy 表达式/参数绑定构造，没有字符串拼接 SQL；搜索用
  `contains(..., autoescape=True)`，`%`/`_` 会被转义，用户输入无法改变查询结构。
- **XSS**：前端全部使用 Vue 文本插值（默认转义），源码中 `v-html` / `innerHTML` 命中数为 0；
  再加 CSP `script-src 'self'` 兜底。
- **命令执行**：应用不调用 shell；aria2 只通过 JSON-RPC 传参；文件名与 URL 从不进入命令行。

### 2.12 依赖与镜像
- 运行依赖全部在 `backend/requirements.txt` **精确锁版本**；前端 `package-lock.json` 锁定。
- 基础镜像：`python:3.12-slim-bookworm`、`node:22-alpine`、`nginx:1.27-alpine`、`caddy:2-alpine`、`alpine:3.20`。
- 生产镜像只装运行期依赖（tests、`.venv`、`.cache` 通过 `.dockerignore` 排除）。
- 2026-11-26 审计结果：`pip-audit -r requirements.txt` → **No known vulnerabilities**；
  `npm audit`（含 dev，官方 registry）→ **0 vulnerabilities**。

---

## 3. 实测记录（2026-11-26，本机 Docker Desktop + 真实 Compose 栈）

| # | 验证项 | 方法 | 结果 |
|---|---|---|---|
| 1 | 端口暴露面 | `Get-NetTCPConnection` | 仅 127.0.0.1:18080/18443；8000、6800 无监听 |
| 2 | 未认证访问 | curl 5 个端点 | 全部 401 |
| 3 | 伪造会话 | `Cookie: ps_session=forged-value` | 401 |
| 4 | 跨站 CSRF | 带有效 Cookie + `Origin: https://evil.example` PUT /api/settings | 403 |
| 5 | SSRF | 7 个地址（127.0.0.1、localhost、169.254.169.254、10/8、192.168/16、::1、metadata.google.internal） | 全部 403 `SSRF_BLOCKED` |
| 6 | 路径穿越 | `filename="../../evil.sh"` | 存为 `_.._evil.sh`，仅任务目录内，无逃逸文件 |
| 7 | 下载令牌 | 有效 / 篡改 2 字节 / 不带令牌 | 200 / 401 / 401 |
| 8 | 令牌落日志 | 用有效令牌下载后 grep 容器日志 | 修复后 0 命中；访问日志显示 `?***` |
| 9 | 登录限流 | 连续错误登录 | 19×401 → 429，`Retry-After: 888` |
| 10 | Cookie 标志 | `Set-Cookie` | `HttpOnly; Secure; SameSite=lax; Path=/; Max-Age=2592000` |
| 11 | 会话固定 | 两次登录对比 Cookie | 不同 |
| 12 | 登出吊销 | logout 后 /api/auth/me | 204 → 401 |
| 13 | 网络隔离 | 容器内解析/连接 | caddy→backend 失败；frontend→aria2 失败；backend→aria2 成功 |
| 14 | 出口防火墙 | aria2 内访问元数据/私网/公网 | 拒绝 / 拒绝 / 成功 |
| 15 | 运行身份 | `id`、`docker top` | backend uid=1000；aria2c 为 1000；tini 为 root（仅作为 init） |
| 16 | 文件权限 | 容器内 `ls -l` | 下载文件 0600、任务目录 0750、密钥 0600 |
| 17 | 安全响应头 | `/login`、`/api/health` | CSP、XFO、nosniff、Referrer-Policy、Permissions-Policy、HSTS 均在 |
| 18 | CSP 不破坏功能 | Playwright 真实 Chrome 登录并加载总览 | 页面正常、SSE"实时"、0 个 page error（仅登录前的预期 401） |
| 19 | 健康检查 | `/api/health` | `db/disk/aria2/egress_guard` 全部 `ok` |
| 20 | 依赖漏洞 | pip-audit、npm audit | 0 / 0 |
| 21 | 回归测试 | `pytest` | **263 passed, 1 skipped** |
| 22 | 登录失败审计 | 错误密码登录后检查日志 | 记录用户名/IP/原因，密码 0 命中 |

复现命令：

```bash
cd backend
.venv/bin/python -m pytest tests/test_security_http.py tests/test_security_unit.py
.venv/bin/python -m pip_audit -r requirements.txt

# 针对运行中的栈
curl -k https://127.0.0.1:18443/api/health
docker compose exec -T caddy sh -c 'wget -T 3 -qO- http://backend:8000/api/health'   # 应失败
docker compose exec -T frontend sh -c 'wget -T 3 -qO- http://aria2:6800/jsonrpc'    # 应失败
docker compose exec -T aria2 wget -T 5 -qO- http://169.254.169.254/                  # 应拒绝
```

---

## 4. 已知限制与残余风险

| 编号 | 风险 | 说明与缓解 |
|---|---|---|
| R1 | **aria2 1.37.0 已停止维护**（2023-11 最后版本） | 新披露的解析类 CVE 不会修复。暴露面被限制为 HTTP/HTTPS + 出口防火墙 + 非 root；建议关注上游，必要时替换下载引擎 |
| R2 | DNS rebinding 的 TOCTOU 窗口 | 预检固定 IP，但 aria2 下载时会重新解析。L4 出口防火墙阻断全部私网/元数据地址，使重绑定无法达成目标；公网地址之间的重定向属于设计允许 |
| R3 | internal CA 需手动信任 | 不导入根证书就会看到证书告警；若用户习惯性忽略告警，存在 MITM 风险。生产建议用域名 + `TLS_MODE=acme`；internal 模式请核对证书指纹 |
| R4 | 单用户、无 MFA、无 RBAC | 产品定位为个人 VPS；多用户/团队共享需另行设计。管理员密码是唯一凭证，请使用密码管理器 |
| R5 | 限流是单进程内存计数 | 重启清零、多 IP 可绕过；不防 DDoS。公网部署建议在云防火墙层加连接数/速率限制 |
| R6 | 容器未启用只读根文件系统与自定义 seccomp | 使用 Docker 默认 profile；后端需要写 `/data`，aria2 需要 `NET_ADMIN`。进一步硬化需按发行版定制 |
| R7 | 升级部署的历史文件权限 | 新部署由 `umask 077` 保证 0600；从旧版本升级时，已有 DB/WAL 可能仍是 0644。升级后建议 `chmod -R go-rwx ./data/db ./data/downloads` |
| R8 | 日志保留与审计 | 仅 stdout + Docker json-file（10 MB × 3），无远程集中审计；任务事件存于 SQLite（`task_events`），随备份保留 |
| R9 | 不扫描下载内容 | 用户从不可信站点取回的可执行文件需自行校验（页面提供 SHA-256）；VPS 不负责查毒 |
| R10 | 未设置 `PUBLIC_BASE_URL` 时 | Origin 校验与下载链接会退化为按请求推断。生产部署务必显式设置 |
| R11 | 镜像按 tag 而非 digest 固定 | 上游 tag 漂移会改变运行时；对可复现性要求高的场景可改为 `@sha256:` 固定 |
| R12 | 备份包含密钥 | `backup.sh` 会复制 `.env`（含 RPC/令牌密钥）。备份文件应加密并限制访问 |
| R13 | caddy 以 root 运行 | 官方镜像默认 root。它不持有额外 capability、不挂 Docker socket，配置由受控脚本从环境变量生成，且仅写 `./data/caddy`；风险低于"任意 root 服务"，但仍是提权后的第一落点。对隔离要求更高的部署可自行改为非 root 并 `chown -R 1000:1000 ./data/caddy` |
| R14 | 静态数据未加密 | SQLite、下载文件与备份都以明文存放在 `./data`。依赖宿主磁盘加密（云盘/LUKS）与目录权限；对高敏感内容请在取回后立即删除，或把 `HOST_DATA_DIR` 放到加密卷 |
| R15 | 首次启动默认凭据 admin/admin | 为方便首次部署，默认密码是 `admin`；改密前所有业务接口都被拦截，但改密接口本身对已登录者开放。若实例在首次登录前就暴露公网，可能被他人抢先登录并改密。缓解：启动前设置 `BOOTSTRAP_ADMIN_PASSWORD`，或先通过 SSH 隧道完成首次改密 |

另有两项**非风险但值得知道**的行为：

- API 响应会同时带 backend 与 nginx 的安全头，个别头出现两次（值相同）；浏览器取最严格值，不影响安全。
- `GET /api/health` 不鉴权，用于容器健康检查；它只返回 `ok` 与版本，不含主机/任务信息。

---

## 5. 安全部署清单

- [ ] 云防火墙只放行 SSH 与 `18080/18443`（或 acme 模式的 80/443），其余全部关闭。
- [ ] `.env` 中 `PUBLIC_BASE_URL`、`TLS_HOST`/`DOMAIN` 填写正确；`TLS_MODE=internal` 时导入 CA 根证书。
- [ ] `BIND_ADDRESS` 按需设为 `0.0.0.0`；只走 SSH 隧道时设为 `127.0.0.1`。
- [ ] `sudo chown -R 1000:1000 ./data && chmod 750 ./data`，确认 `PULLSPOOL_UID/GID` 与属主一致。
- [ ] 首次登录后立即修改默认密码 `admin`，并确认 `data/bootstrap-admin.txt` 已删除。
- [ ] 保持 `ARIA2_EGRESS_GUARD=on`，定期检查 `/api/health` 的 `egress_guard` 为 `ok`。
- [ ] 备份加密并异地保存；`.env` 与备份分开存放。
- [ ] 定期 `pip-audit` / `npm audit` / 拉取新镜像；关注 aria2 上游状态。
- [ ] 监控日志中的 `RATE_LIMITED`、`ACCOUNT_LOCKED`、`SSRF_BLOCKED` 异常峰值。
- [ ] 不要把 `./data` 放进 Web 根目录或公开的静态服务。

---

## 6. 漏洞报告

请通过部署者自己的私有渠道联系维护者，附上：版本号、复现步骤、影响面、PoC（如有）。
在修复发布前请勿公开细节。PullSpool 是自托管项目，没有赏金计划。

---

## 7. 本次审计的修复清单

| 问题 | 影响 | 修复 |
|---|---|---|
| uvicorn access log 明文记录 `?token=` | 有日志读取权限者可盗用 30 分钟下载令牌 | 关闭 uvicorn access log；访问日志统一走 `redact_url`；新增 `QueryRedactor` 兜底；Dockerfile 加 `--no-access-log` |
| Alembic `fileConfig` 重置应用日志 | 迁移后日志级别变 WARNING、脱敏格式化器被替换 | `env.py` 仅在 CLI 模式配置日志；`run_migrations` 传 `configure_logger=False`；新增回归测试 |
| nginx `add_header` 继承陷阱 | `/login` 与 `/assets/*` 丢失 CSP/XFO/HSTS | 抽出 `security-headers.conf`，在所有设置了 Cache-Control 的 location 显式 include |
| 缺少 CSP | XSS 后可利用面更大 | 新增严格 CSP；内联主题脚本外置为 `/theme-init.js` |
| 全局 API 无速率上限 | 单客户端可无限刷接口 | 新增 `ApiRateLimitMiddleware`（默认 300/min/IP，SSE 除外） |
| backend 与 caddy 同网 | caddy 被攻陷可直连 backend:8000 | 新增 `app` 网络，backend 退出 `edge` |
| 容器提权面 | — | 四个服务统一 `no-new-privileges:true` |
| 文件默认 0644 | 多用户 VPS 上其他本地用户可读 | backend/aria2 `umask 077`（新文件 0600、目录 0750） |
| HTTP 跳转 301 | 非 GET 请求方法被降级 | 改为 308 |
