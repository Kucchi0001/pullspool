# PullSpool 安装教程（Linux VPS）

本文从一台全新的 Linux VPS 开始，到能在电脑和手机上取回第一个文件。
全过程约 10–15 分钟，默认只使用 IP + 自签内部证书；有域名时可切到 Let's Encrypt。

> 目标环境：Ubuntu 22.04/24.04、Debian 12 等主流 x86_64/arm64 发行版。
> 需要 Docker Engine 24+ 与 Docker Compose v2。

> **最快路径**：`git clone <repo> && cd pullspool && sudo sh scripts/quickstart.sh`，
> 自动检测 IP、生成 `.env`、preflight、构建并等待健康检查；详细手动步骤见下文。

---

## 0. 准备

| 项目 | 最低 | 建议 |
|---|---|---|
| CPU | 1 核 | 1–2 核 |
| 内存 | 1 GB | 2 GB |
| 磁盘 | 10 GB 空闲 | 20 GB+（取决于临时文件大小） |
| 系统 | 现代 Linux + Docker | Ubuntu 24.04 LTS |
| 网络 | 有公网 IPv4 | 固定公网 IP |

确认：

```bash
uname -m                  # x86_64 或 aarch64
free -m
df -h /
```

如果内存只有 1 GB，建议先加 1–2 GB swap：

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 1. 安装 Docker

以 Ubuntu/Debian 为例（官方脚本，最省事）：

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # 重新登录后生效
docker version
docker compose version
```

如果服务器在中国大陆且拉取镜像很慢，可在 `/etc/docker/daemon.json` 配置镜像加速：

```json
{
  "registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.1ms.run"]
}
```

```bash
sudo systemctl restart docker
docker run --rm hello-world
```

> 本项目需要的镜像：`python:3.12-slim-bookworm`、`node:22-alpine`、`nginx:1.27-alpine`、
> `caddy:2-alpine`、`alpine:3.20`（aria2 镜像本地构建）。

---

## 2. 取得代码

把项目目录上传到 VPS（任选其一）：

```bash
# 方式 A：从你自己的 Git 仓库
sudo mkdir -p /opt/pullspool && sudo chown "$USER" /opt/pullspool
git clone <你的仓库地址> /opt/pullspool && cd /opt/pullspool

# 方式 B：本地打包上传
# 本地执行： tar czf pullspool.tar.gz --exclude node_modules --exclude .venv --exclude data pullspool
scp pullspool.tar.gz user@VPS:/tmp/
# VPS 执行：
sudo mkdir -p /opt/pullspool && sudo tar xzf /tmp/pullspool.tar.gz -C /opt/pullspool --strip-components=1
cd /opt/pullspool
```

确认关键文件存在：

```bash
ls docker-compose.yml .env.example backend/Dockerfile frontend/Dockerfile docker/caddy/entrypoint.sh
```

---

## 3. 配置 `.env`

```bash
cp .env.example .env
chmod 600 .env
```

至少修改这几项（用 `nano .env` 或 `vim .env`）：

```ini
PUBLIC_IP=203.0.113.5              # 改成你的 VPS 公网 IP
TLS_HOST=203.0.113.5               # 与公网 IP 一致（或填域名）
PUBLIC_BASE_URL=https://203.0.113.5:18443
HOST_DATA_DIR=./data
PULLSPOOL_UID=1000                 # 用 `id -u` 查看，通常 1000
PULLSPOOL_GID=1000                 # 用 `id -g` 查看
TZ=Asia/Shanghai
```

### 三种 TLS 形态

| 场景 | 配置 | 说明 |
|---|---|---|
| 只有 IP（默认，推荐先跑通） | `TLS_MODE=internal`、`TLS_HOST=<IP>` | Caddy 内置 CA 签发，需要客户端导入根证书 |
| 有域名 | `TLS_MODE=acme`、`DOMAIN=pull.example.com`、`HTTP_PORT=80`、`HTTPS_PORT=443`、`PUBLIC_BASE_URL=https://pull.example.com` | Let's Encrypt 自动签发与续期 |
| 纯 HTTP（仅隧道/内网） | `TLS_MODE=off`、`HTTPS_ENABLED=false`、`HTTP_ENABLED=true` | 密码明文传输，**不要直接暴露公网** |

> 端口默认 `18080/18443`。改成 80/443 需要 root 权限，但 Docker 发布端口本来就由 root 完成，
> 直接改 `.env` 即可。改完执行 `docker compose up -d` 重新创建容器。

### 其他可调项（一般保持默认）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ARIA2_EGRESS_GUARD` | `on` | 出口防火墙，强烈建议保持开启 |
| `ARIA2_RPC_SECRET` | 空 | 留空自动生成到 `data/aria2/secret` |
| `DOWNLOAD_TOKEN_SECRET` | 空 | 留空自动生成到 `data/.token_secret` |
| `BACKEND_MEM_LIMIT` 等 | 320m/256m/64m/96m | 容器资源上限，1C1G 可保持默认 |
| `PIP_INDEX_URL` / `NPM_REGISTRY` | 空/官方 | 大陆构建慢时可填清华/ npmmirror |

> **不要**把 `.env` 提交到 Git；它包含 RPC/令牌密钥。

---

## 4. 开放防火墙

以 `ufw` 为例（云厂商安全组也要同步放行）：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 18080/tcp
sudo ufw allow 18443/tcp
sudo ufw enable
sudo ufw status
```

- 使用 ACME 时改为放行 `80/tcp` 与 `443/tcp`。
- **不要**放行 8000、6800、3306 等内部端口——它们在 compose 中本来就没有发布。
- 只想通过 SSH 隧道访问时，可把 `BIND_ADDRESS=127.0.0.1`，不开放任何 Web 端口。

---

## 5. 目录权限

容器以非 root 运行（UID/GID 来自 `.env`），需要数据目录可写：

```bash
sudo mkdir -p ./data
sudo bash scripts/preflight.sh    # 以 root 运行时会自动 chown 到 PULLSPOOL_UID/PULLSPOOL_GID
```

如果不用 root 跑 preflight，手动执行：

```bash
sudo chown -R 1000:1000 ./data
sudo chmod 750 ./data
```

---

## 6. 启动

```bash
sudo bash scripts/preflight.sh     # 检查端口、磁盘、内存、TLS、权限；有问题会给出修复命令
docker compose up -d --build
docker compose ps
```

首次构建需要下载基础镜像并安装依赖，通常 3–10 分钟；二次启动约 15 秒。
四个服务都应显示 `Up`，其中 backend 与 frontend 为 `healthy`。

检查：

```bash
curl -k https://127.0.0.1:18443/api/health
# {"status":"ok","checks":{"db":"ok","disk":"ok","aria2":"ok","egress_guard":"ok"},"version":"1.0.0"}

docker compose logs -f backend     # 观察启动日志，Ctrl+C 退出
```

`egress_guard` 不是 `ok` 时不要继续：说明 aria2 的出口防火墙没装成功，见第 13 节。

---

## 7. 导入 CA 根证书

`TLS_MODE=internal` 时，浏览器会提示证书不受信任。根证书在：

```bash
sudo ls -l ./data/caddy/data/caddy/pki/authorities/local/root.crt
```

先核对指纹，再导入：

```bash
openssl x509 -in ./data/caddy/data/caddy/pki/authorities/local/root.crt \
  -noout -subject -fingerprint -sha256
```

把 `root.crt` 下载到本地（`scp user@VPS:/opt/pullspool/data/caddy/data/caddy/pki/authorities/local/root.crt .`），然后：

**Windows**
1. 双击 `root.crt` →「安装证书」→「本地计算机」→「受信任的根证书颁发机构」；
2. 或管理员 PowerShell：`certutil -addstore -f Root root.crt`；
3. 重启浏览器。

**macOS**
1. 双击导入「钥匙串访问」→ 系统 → 找到 PullSpool CA → 显示简介 → 信任 →「始终信任」；
2. 或：`sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain root.crt`。

**Linux（Chrome/Edge）**
```bash
sudo cp root.crt /usr/local/share/ca-certificates/pullspool.crt
sudo update-ca-certificates
```

**iPhone / iPad**
1. 用 AirDrop/邮件把 `root.crt` 发到设备并安装描述文件；
2. 设置 → 通用 → 关于本机 → 证书信任设置 → 打开 PullSpool CA 的完全信任。

**Android**
设置 → 安全 → 加密与凭据 → 安装证书 → CA 证书 → 选择 `root.crt`。
（Android 11+ 需要手动进入该菜单；部分厂商浏览器不信任用户 CA，可用 Chrome。）

> 根证书私钥在 VPS 的 `root.key`，**不要**外传；换 VPS 或重装后需要重新导入新证书。

---

## 8. 首次登录与管理员初始化

```bash
sudo cat ./data/bootstrap-admin.txt
```

默认初始账号是 `admin` / `admin`，同时写入 `data/bootstrap-admin.txt`（0600）：

```
用户名: admin
密码: admin
```

浏览器打开 `https://<你的公网IP>:18443`：

1. 用默认账号 `admin`、密码 `admin` 登录；
2. 系统强制要求修改密码（至少 10 位，需包含字母与数字/符号）；
3. 修改成功后 `bootstrap-admin.txt` 会被自动删除，其他设备的会话被吊销。

**不要**跳过改密。默认密码只是"首次登录的入口"，改密前无法访问任务/设置等接口。
如果 VPS 首次启动即暴露公网，建议先在 `.env` 设置随机值再启动：

```ini
BOOTSTRAP_ADMIN_PASSWORD=用 openssl rand -base64 24 生成
```

---

## 9. 第一个任务

1. 进入「下载」→「新建下载」；
2. 粘贴一个测试链接，例如 `https://example.com/`；
3. 观察状态从「等待中」→「下载中」→「等待取回」；
4. 到「等待取回」点「取回」，浏览器开始下载；
5. 确认本地文件完整后，点「确认取回并删除」——VPS 上的临时文件立即删除，SHA-256 记录保留。

也可以用 curl 验证 API（把 `PASSWORD` 换成你的密码）：

```bash
curl -k -c /tmp/ps.jar -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"PASSWORD"}' \
  https://127.0.0.1:18443/api/auth/login

curl -k -b /tmp/ps.jar -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/"}' https://127.0.0.1:18443/api/tasks
```

完整的冒烟测试：

```bash
SMOKE_PASSWORD='你的密码' bash scripts/smoke-test.sh
```

---

## 10. 低配 VPS 调优

1C1G 可以跑，但建议做以下调整（网页「设置」里改，立即生效）：

| 设置 | 默认 | 1C1G 建议 |
|---|---|---|
| 最大并发下载数 | 2 | 1 |
| 默认连接数 | 4 | 1–2 |
| 默认限速 | 0（不限速） | 8–10 MB/s |
| 全局限速 | 0（不限） | 10 MB/s |
| 临时存储配额 | 15 GB | 磁盘的 60% |
| 最低剩余磁盘 | 2 GB | 3 GB |
| 等待取回过期 | 24 小时 | 12 小时 |

另外：

- 加 1–2 GB swap（见第 0 节）；
- 保持 `ARIA2_EGRESS_GUARD=on`，但它只增加包过滤开销，几乎不占 CPU；
- 日志级别用默认 `INFO`；长期运行可改 `LOG_LEVEL=WARNING`；
- 大文件取回是流式的，不会把文件读进内存，回传并发默认 2。

---

## 11. 切换域名与 ACME

准备工作：

1. 域名 A 记录指向 VPS 公网 IP；
2. 云防火墙/ufw 放行 80、443；
3. 修改 `.env`：

```ini
DOMAIN=pull.example.com
TLS_MODE=acme
ACME_EMAIL=you@example.com
HTTP_PORT=80
HTTPS_PORT=443
PUBLIC_BASE_URL=https://pull.example.com
TLS_HOST=pull.example.com
```

4. 重新创建 Caddy：

```bash
docker compose up -d --force-recreate caddy
docker compose logs -f caddy
```

看到 `certificate obtained successfully` 即成功；证书会自动续期。之后可不再需要导入 CA。
若签发失败，检查 80 端口是否可达、域名是否解析、是否有其他服务占用 80。

---

## 12. 纯 HTTP / SSH 隧道

不希望暴露 Web 端口时：

```ini
BIND_ADDRESS=127.0.0.1
HTTP_ENABLED=true
HTTPS_ENABLED=false
TLS_MODE=off
PUBLIC_BASE_URL=http://127.0.0.1:18080
```

```bash
docker compose up -d
# 本地电脑执行：
ssh -N -L 18080:127.0.0.1:18080 user@VPS
# 浏览器打开 http://127.0.0.1:18080
```

此模式密码明文传输，务必只走隧道。

---

## 13. 排错

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `docker compose up` 报端口被占用 | 18080/18443 已被其他服务使用 | `ss -ltnp \| grep 18080`；改 `.env` 端口或停掉冲突服务 |
| backend 反复重启，日志 `Permission denied` | `./data` 属主不是 UID 1000 | `sudo chown -R 1000:1000 ./data`，或修正 `.env` 的 `PULLSPOOL_UID/GID` |
| 浏览器证书告警 | 未导入 internal CA | 按第 7 节导入根证书；或改用 ACME |
| 页面 502 / API 不通 | frontend 连不上 backend | `docker compose ps` 看 backend 是否 healthy；`docker compose logs backend frontend` |
| `egress_guard` 为 `failed`/`unknown` | aria2 容器缺 `NET_ADMIN` 或 iptables 不可用 | 确认未删 compose 的 `cap_add`；`docker compose logs aria2`；重启 aria2 |
| 下载任务立即失败 `ARIA2_UNAVAILABLE` | RPC 密钥不一致或 aria2 未启动 | `docker compose logs aria2 backend`；`docker compose up -d --force-recreate aria2 backend` |
| 所有任务「等待中」不动 | 并发已满或磁盘门禁 | 看总览的「队列」与磁盘；删除旧任务或提高并发/配额 |
| 登录 429 | 触发了限流/锁定 | 等 15 分钟，或重启 backend 清空内存计数 |
| 修改 `.env` 不生效 | 容器未重建 | `docker compose up -d`（必要时 `--force-recreate`） |
| 升级后文件 0644 | 旧数据目录未受 umask 保护 | `sudo chmod -R go-rwx ./data/db ./data/downloads` |

收集诊断信息：

```bash
docker compose ps
docker compose logs --tail=100 backend aria2 caddy frontend
docker inspect pullspool-backend-1 --format '{{.State.Health.Status}}'
curl -k https://127.0.0.1:18443/api/health
```

---

## 14. 下一步

- 日常更新：[UPDATE.md](UPDATE.md)
- 备份与恢复：[BACKUP.md](BACKUP.md)
- 卸载：[UNINSTALL.md](UNINSTALL.md)
- 安全加固与风险：[SECURITY.md](SECURITY.md)
- 验收报告：[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)
