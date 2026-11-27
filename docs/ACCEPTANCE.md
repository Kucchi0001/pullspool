# PullSpool 最终验收报告

日期：2026-11-26 ｜ 版本：1.0.0 ｜ 对应需求：`需求要求.txt`（第一至十五部分）

---

## 0. 结论摘要

PullSpool 第一版已完成：浏览器提交链接 → VPS 独立出口下载 → 落盘校验 → HTTPS 流式取回 → 确认后删除，
整条链路已在真实的 4 容器 Docker 栈上跑通；SSRF、越权、路径穿越、令牌泄露等安全项经过对抗性验证；
自动化测试 **264 项收集，263 通过，1 跳过**。

**必须说明的验证边界**：本项目的容器全部是 Linux 容器，但验收是在 Windows 11 + Docker Desktop 的
Linux VM 上完成的，**没有在真实 Linux VPS 裸机上执行安装脚本**；手机端使用 Chrome 移动仿真，
**没有使用实体手机**；"VPS 自身公网 IP" 验证的是容器经宿主 NAT 出网，未核对具体公网 IP。
这些项目在下方逐条标注为「部分验证」，不计作"已实测"。

---

## 1. 验证环境与边界

| 项目 | 实际值 |
|---|---|
| 宿主 | Windows 11，Docker Desktop 4.100.1 |
| 引擎 | Docker Engine 29.9.3，Compose v5.7.1 |
| Linux 运行时 | WSL2 2.9.13，内核 6.18（Docker Desktop Linux VM） |
| 浏览器 | 本机 Chrome（Playwright 驱动，真实渲染） |
| 手机验证 | Chrome 移动仿真：390×844、375×667，touch + 移动 UA |
| 数据目录 | 冷启动使用全新 `data-accept/`，非历史数据 |
| 测试日期 | 2026-11-26 |

**未覆盖**：真实 VPS（Ubuntu/Debian 裸机）、实体手机、真实公网 IP 核对、真实断网演练、
真实 Let's Encrypt 签发（ACME 逻辑已实现并做配置校验，但本环境无公网域名）。

---

## 2. 交付物清单（对应需求第十二部分）

| # | 交付物 | 位置 | 状态 |
|---|---|---|---|
| 1 | 完整前端源码 | `frontend/`（Vue 3 + TS，35 个源文件） | ✅ |
| 2 | 完整后端源码 | `backend/app/`（约 4,900 行） | ✅ |
| 3 | Docker Compose 配置 | `docker-compose.yml`（4 服务 / 4 网络 / 健康检查 / 资源上限） | ✅ |
| 4 | aria2 配置 | `docker/aria2/aria2.conf` + `entrypoint.sh` + `egress-guard.sh` | ✅ |
| 5 | Caddy 配置模板 | `docker/caddy/entrypoint.sh` 按 env 生成 HTTP / internal / ACME 三种配置并 `caddy validate` | ✅ |
| 6 | 数据库初始化与升级 | Alembic `0001`，启动自动迁移，迁移前自动备份 3 份 | ✅ |
| 7 | 自动化测试 | `backend/tests/`（264 项）+ Playwright 截图脚本 | ✅ |
| 8 | README 中文说明 | `README.md` | ✅ |
| 9 | Linux VPS 安装教程 | `INSTALL.md` | ✅ |
| 10 | 更新教程 | `UPDATE.md` | ✅ |
| 11 | 卸载教程 | `UNINSTALL.md` | ✅ |
| 12 | 备份与恢复教程 | `BACKUP.md` + `scripts/backup.sh` / `restore.sh` | ✅ |
| 13 | 安全配置说明 | `SECURITY.md` | ✅ |
| 14 | `.env.example` | 根目录，含全部变量与中文注释 | ✅ |

附加：`docs/ARCHITECTURE.md`、`docs/API.md`、`docs/DESIGN.md`、`docs/SCHEMA.md`、
`scripts/preflight.sh`、`scripts/smoke-test.sh`、`LICENSE`（MIT）。

---

## 3. 实际实现的功能

### 3.1 下载与任务

- 新建任务：URL 校验、可选文件名 / 连接数 / 单任务限速 / 大小上限；同 URL 10 分钟内去重。
- 队列：并发槽位（默认 2）、FIFO 排队、队列上限 50；磁盘不足时暂停调度并产生告警事件。
- 控制：暂停、恢复、取消（可选删文件）、失败重试、删除记录。
- 进度：aria2 轮询同步 + SSE 实时推送；状态 `queued/active/paused/verifying/completed/failed/canceled`
  映射为 11 种界面状态。
- 失败处理：HTTP 错误、目标 404、磁盘满、aria2 RPC 异常均映射为明确错误码与中文提示。
- 重启恢复：启动时对账 aria2 与数据库，保留暂停态，恢复中断任务（有测试）。

### 3.2 安全

- SSRF 五层：协议/IP 字面量/DNS 全记录校验、固定 IP 预检、重定向逐跳复检、aria2 iptables 出口防火墙、下载后大小校验。
- 认证：Argon2id、密码策略、初始密码文件 0600 且首登强制改密、登录失败锁定 + IP 限流、会话哈希存储、改密吊销其他会话。
- CSRF：Origin/Referer/Sec-Fetch-Site 校验。
- 文件：UUID 目录、文件名清洗、`realpath` 越界校验、0600/0750 权限。
- 回传：HMAC 令牌 30 分钟、常量时间比较、绑定任务；有活跃回传时拒绝删除。
- 运维：四网络分段、仅 Caddy 发布端口、非 root、`no-new-privileges`、CSP 与安全响应头、日志脱敏。

### 3.3 取回与清理

- 流式回传，支持 `Range`（200/206/416）、`If-Range`、ETag、RFC 5987 文件名。
- SHA-256 计算、存储、展示与 `/integrity` 校验接口。
- 「确认取回并删除」幂等；文件删除、SHA 记录保留；重复点击不会报错。
- 过期自动清理（默认 24h）、孤儿文件清理、删除原因记录。
- 回传流量按实际发送字节计入 `traffic_daily('up')`；下载流量按任务完成字节计入 `down`。

### 3.4 界面

- 7 个页面：登录、强制改密、总览、下载、等待取回、历史、设置。
- 浅色/深色/跟随系统；舒适/紧凑；中文文案；手机底部导航与卡片布局。
- 74 张真实截图（7 宽度 × 2 主题 × 5 页面 + 登录页/抽屉/移动菜单），自动检查无横向溢出。

### 3.5 观测

- 系统状态（CPU/内存/磁盘/aria2/出口防火墙/队列/运行时长）。
- 流量：今日/本月下载、回传，14 天堆叠图，单任务 `download_bytes` / `retrieved_bytes`。
- 任务事件时间线；应用层统计口径在界面明确标注。

---

## 4. 尚未实现 / 明确不支持

| 项 | 说明 |
|---|---|
| 多用户 / 角色权限 | 产品定位单管理员；数据模型已带 `user_id`，但无管理界面 |
| MFA / OIDC / LDAP | 未实现 |
| BT / 磁力 / FTP / SFTP / ed2k | 仅 HTTP/HTTPS（SSRF 策略也只允许这两种） |
| 多实例 / 水平扩展 | SQLite 单写 + 进程内事件总线，仅支持单实例 |
| 英文界面 | 仅中文；文案集中在模板中，可后续抽 i18n |
| 手机 App / 推送通知 | 仅响应式 Web |
| 下载内容病毒扫描 | 不做，提供 SHA-256 供用户自行校验 |
| 真实断网续传演练 | 依赖 aria2 `--continue` 与源站 Range；实验室只做了暂停/恢复与重启恢复 |
| 真实 VPS / 实体手机验收 | 见第 1 节边界 |

---

## 5. 最终验收标准（需求第十四部分，18 项）

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | Linux VPS 可以正常部署 | ⚠️ 部分 | 全部组件为 Linux 容器并在 Docker Desktop Linux VM 上冷启动成功；`INSTALL.md` 步骤完整、脚本通过 `sh -n`；**未在真实 VPS 裸机执行** |
| 2 | Docker Compose 正常启动全部服务 | ✅ | 全新 `data-accept/`：`up -d --build` 后 4 服务全部 Up，backend/frontend healthy，**15.7 秒**到健康 |
| 3 | 手机浏览器可以访问 | ⚠️ 部分 | Chrome 移动仿真 390/375 全页面截图、无横向溢出；**未用实体手机** |
| 4 | 电脑浏览器可以访问 | ✅ | 真实 Chrome：登录、总览、SSE"实时"、下载/取回操作（Playwright + 截图） |
| 5 | 用户可以提交下载 URL | ✅ | 界面「新建下载」与 `POST /api/tasks` 均验证 |
| 6 | VPS 使用自身公网 IP 下载 | ⚠️ 部分 | 容器经独立 egress 网络从 `https://example.com/` 下载成功（577 字节、SHA 匹配）；未核对具体公网 IP |
| 7 | 关闭浏览器后下载仍继续 | ✅ | 下载完全由 backend/aria2 执行；API 创建任务后无浏览器参与仍完成 |
| 8 | 文件完整保存到 VPS 本地磁盘 | ✅ | 宿主 `data-accept/downloads/<id>/download.bin` 存在、577 字节；`Get-FileHash` 与接口 SHA 一致 |
| 9 | 下载完成后等待用户取回 | ✅ | 任务进入 `completed/ready`，等待取回页可见，24h 过期策略生效（有测试） |
| 10 | 支持大文件流式回传 | ✅ | `test_large_file.py`：64 MiB 下载 + 1 MiB / 末尾 1 KiB Range 回传；流式分块，不整文件入内存 |
| 11 | 支持中断后的续传 | ⚠️ 部分 | 暂停/恢复、backend 重启恢复、Range/If-Range 均有测试；**未做真实断网演练** |
| 12 | 文件 SHA-256 校验 | ✅ | 完成后计算并入库；`/integrity` 返回；删除后仍保留（冷启动实测） |
| 13 | 用户确认后自动删除 VPS 临时文件 | ✅ | ack 后文件从宿主消失，状态 `deleted`；重复 ack 仍 200 |
| 14 | 不因浏览器意外断开而提前删除 | ✅ | 回传中途断开（P8 实测）文件仍在、任务仍 ready；删除只由 ack/过期触发 |
| 15 | 服务器重启后数据库和文件不丢失 | ✅ | `docker compose down/up` 后任务、会话、文件都在；`restart backend` 后任务仍 completed 且文件存在 |
| 16 | 不存在未授权访问文件的明显安全漏洞 | ✅ | P8：未认证 401、伪造 Cookie 401、越权/穿越/SSRF/令牌篡改全部拦截；残余风险见 SECURITY R1–R14 |
| 17 | 核心自动化测试通过 | ✅ | 264 collected / **263 passed / 1 skipped**；ruff 全绿 |
| 18 | 有完整中文部署文档 | ✅ | README + INSTALL + UPDATE + UNINSTALL + BACKUP + SECURITY + docs/ |

---

## 6. 测试要求（需求第十一部分，18 项）

| # | 测试项 | 自动化测试 | 结果 |
|---|---|---|---|
| 1 | 普通 HTTP 下载 | `test_download_completes_over_http`、`test_task_completes_and_stores_sha256` | ✅ |
| 2 | HTTPS 下载 | `test_download_completes_over_https_with_ca`（Windows 跳过）、`test_https_rejects_untrusted_certificate`；容器栈实测 `https://example.com/` | ✅（跳过项在 Linux 执行） |
| 3 | 大文件下载 | `test_large_file_download_and_streaming_range`（64 MiB） | ✅ |
| 4 | 断点续传 | `test_range_requests`、`test_if_range_validation`、`test_pause_and_resume`、`test_task_survives_backend_restart` | ✅（真实断网未演练） |
| 5 | 暂停和恢复 | `test_pause_and_resume`、`test_paused_queued_task_survives_restart` | ✅ |
| 6 | 下载失败重试 | `test_retry_failed_task`、`test_retry_rejects_non_failed_task` | ✅ |
| 7 | 多任务排队 | `test_queue_limit_returns_409`；调度器槽位/FIFO 由 `download_service` 保证 | ✅（顺序未单独断言） |
| 8 | SHA-256 校验 | `test_task_completes_and_stores_sha256`、`test_integrity_endpoint` | ✅ |
| 9 | 文件取回 | `test_download_token_flow`、`test_full_download_and_accounting` | ✅ |
| 10 | Range 请求 | `test_range_requests`、`test_unsatisfiable_range`、`test_if_range_validation` | ✅ |
| 11 | 用户确认删除 | `test_ack_deletes_files_and_is_idempotent` + 冷启动实测 | ✅ |
| 12 | 重复删除 | 同上（ack 幂等、`test_remove_task_tree_is_idempotent`） | ✅ |
| 13 | VPS 重启后任务恢复 | `test_task_survives_backend_restart`、compose down/up 实测 | ✅ |
| 14 | 磁盘空间不足 | `test_check_storage_rejects_disk_and_quota`（monkeypatch 磁盘/配额） | ✅（模拟） |
| 15 | SSRF 攻击拦截 | `test_net_policy.py`、`test_preflight_blocks_private_target`、`test_private_targets_are_rejected_by_the_api` + 容器实测 7 类地址 | ✅ |
| 16 | 路径穿越拦截 | `test_filename_traversal_is_contained`、`test_resolve_inside_rejects_symlink_escape`、`test_sanitize_strips_traversal_to_single_component` | ✅ |
| 17 | 未授权文件访问 | `test_download_requires_auth`、`test_events_require_auth`、`test_me_requires_auth`、`test_task_creation_requires_authentication` | ✅ |
| 18 | 手机和桌面浏览器适配 | Playwright：7 宽度 × 2 主题 × 5 页面 = 70 张，另含登录/抽屉/移动菜单 = 74 张；无横向溢出检查 | ✅（移动为仿真） |

---

## 7. 自动化测试结果

```
$ cd backend && .venv/bin/python -m pytest
264 tests collected
263 passed, 1 skipped, 1 warning in ~137s

$ ruff check app tests
All checks passed!

$ pip-audit -r requirements.txt
No known vulnerabilities found

$ cd frontend && npm audit --omit=dev
0 vulnerabilities

$ npm run build
✓ built in ~0.6s，dist 约 222 KB（主包 gzip 48 KB）
```

跳过项：`test_download_completes_over_https_with_ca` —— Windows 上 aria2 使用 Schannel，
会忽略 `--ca-certificate`；该测试在 Linux 上会正常执行。HTTPS 正向能力另有容器栈实测
（`https://example.com/` 下载成功）与负向证书校验测试（拒绝不受信任证书）兜底。

---

## 8. Docker 部署命令

```bash
cp .env.example .env && chmod 600 .env
# 编辑 PUBLIC_IP / TLS_HOST / PUBLIC_BASE_URL（有域名时改 DOMAIN 与 TLS_MODE）
sudo bash scripts/preflight.sh
docker compose up -d --build
docker compose ps
curl -k https://127.0.0.1:18443/api/health
```

更新：`bash scripts/backup.sh && docker compose build && docker compose up -d`
（详见 UPDATE.md）。

---

## 9. 首次访问方式

1. 默认账号 `admin` / `admin` 登录（初始信息也写入 `./data/bootstrap-admin.txt`，0600）；
2. 浏览器打开 `https://<公网IP>:18443`（internal 模式先导入
   `./data/caddy/data/caddy/pki/authorities/local/root.crt`）；
3. `admin` / `admin` 登录 → 强制改密 → 进入总览；
4. 「下载」→「新建下载」粘贴 URL。

---

## 10. 资源占用（实测，Docker Desktop Linux 容器）

| 容器 | 闲置内存 | 内存上限 | 闲置 CPU |
|---|---|---|---|
| backend | 76 MB | 320 MB | ~1.3% |
| caddy | 13 MB | 96 MB | 0% |
| frontend | 3 MB | 64 MB | 0% |
| aria2 | 5 MB | 256 MB | ~0% |
| **合计** | **约 97 MB** | 736 MB | <2% |

镜像：backend 284 MB、frontend 74 MB、aria2 36 MB、caddy 92 MB，合计约 486 MB。
冷启动到全部健康：**15.7 秒**（镜像已构建）。
真实 VPS 的数值会随内核、文件系统与负载不同，1C1G 可运行，1C2G 更稳。

---

## 11. 已知问题与安全限制

1. **aria2 1.37.0 停止维护**（2023-11 最后版本），未来 CVE 无上游修复；已限制为 HTTP/HTTPS、非 root、出口防火墙。
2. **internal CA 需手动信任**；忽略证书告警存在 MITM 风险；有域名建议 ACME。
3. **Caddy 以 root 运行**（官方镜像默认），无额外 capability、无 Docker socket。
4. 单用户、无 MFA；限流为单进程内存计数；静态数据未加密；备份含 `.env` 密钥。
5. 续传依赖源站支持 Range；应用层流量统计不等于运营商计费。
6. 本报告第 1 节的验证边界（真实 VPS / 实体手机 / 真实断网 / ACME 签发未实测）。
7. Windows 上 aria2 使用 Schannel，导致 1 项 CA 正向测试跳过。
8. API 响应存在 backend 与 nginx 重复下发相同安全头的情况（值一致，无安全影响）。

完整清单与缓解措施见 [SECURITY.md](../SECURITY.md) 第 4 节（R1–R14）。

---

## 12. 冷启动验收记录

```
2026-11-26 21:23  全新 data-accept/，docker compose up -d --build
                  → aria2/backend/frontend/caddy 全部启动，15.7s 后 healthy
                  → data/db/pullspool.db 0600，bootstrap-admin.txt 0600

21:24  默认 admin/admin 登录，强制改密 204，bootstrap 文件自动删除
       创建 https://example.com/ → queued → completed
       文件 data-accept/downloads/e3e3a935.../download.bin，577 字节
       SHA-256 25ddf2c883e0d195... 与宿主 Get-FileHash 完全一致

       Range bytes=0-49 → 206，Content-Range: bytes 0-49/577
       下载令牌 URL（ttl=1800）→ 200

21:25  docker compose restart backend → 任务仍 completed，文件仍在
       ack → deleted，文件从磁盘消失；重复 ack → 200，SHA 记录保留

21:26  docker stats：backend 76 MB、caddy 13 MB、frontend 3 MB、aria2 5 MB
```

---

## 13. 后续建议

1. 在真实 Ubuntu 24.04 VPS 上按 INSTALL.md 完整走一遍（重点验证 ufw、chown、CA 导入、1C1G 表现）。
2. 有域名后切到 ACME，补一次真实签发与续期验证。
3. 做一次真实断网/限速演练，记录 aria2 续传行为。
4. 用实体 Android/iPhone 验证 CA 导入与移动端交互。
5. 关注 aria2 上游；若长期无维护，评估替换为 curl/aria2 fork 或其他引擎。
