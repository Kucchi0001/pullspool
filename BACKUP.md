# 备份与恢复

PullSpool 的状态集中在 `./data` 与 `.env`。下载的临时文件（`data/downloads/`）通常**不需要**备份，
真正要保住的是数据库、密钥与配置。

## 1. 备份什么

| 内容 | 路径 | 是否必需 | 说明 |
|---|---|---|---|
| SQLite 数据库 | `data/db/pullspool.db` | ✅ | 用户、会话、任务、事件、流量 |
| 令牌密钥 | `data/.token_secret` | ✅ | 丢了会导致已签发下载链接全部失效 |
| aria2 RPC 密钥 / session | `data/aria2/` | ✅ | 密钥丢了 backend 连不上引擎 |
| Caddy 证书 / internal CA | `data/caddy/` | 建议 | 丢了需重新给客户端装根证书 |
| 配置 | `.env` | ✅ | 端口、TLS、资源上限 |
| 下载文件 | `data/downloads/` | 可选 | 临时文件，通常无需备份 |

## 2. 一键备份

```bash
cd /opt/pullspool
bash scripts/backup.sh              # 不含下载文件
bash scripts/backup.sh --with-files # 含下载文件（可能很大）
```

产物：

```
backups/pullspool-YYYYmmdd-HHMMSS.tar.gz   # 数据 + 密钥 + 证书
backups/pullspool-YYYYmmdd-HHMMSS.env      # .env 副本（0600，含密钥）
```

脚本特性：

- backend 运行时用 SQLite 在线备份 API 做**一致性快照**，不会拿到半写状态；
- 自动保留最近 **7 份**归档；
- `.env` 副本权限 0600；请把备份放在受控位置。

### 手动等价命令

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p backups data/db/backups
docker compose exec -T backend python - "$STAMP" <<'PY'
import sqlite3, sys
stamp = sys.argv[1]
src = sqlite3.connect("/data/db/pullspool.db")
dst = sqlite3.connect(f"/data/db/backups/pre-backup-{stamp}.db")
src.backup(dst); dst.close(); src.close()
PY
tar czf "backups/pullspool-$STAMP.tar.gz" data/db data/aria2 data/caddy
cp .env "backups/pullspool-$STAMP.env" && chmod 600 "backups/pullspool-$STAMP.env"
```

## 3. 定时与异地

```bash
# 每天 04:10 备份
sudo crontab -e
10 4 * * * cd /opt/pullspool && bash scripts/backup.sh >> /var/log/pullspool-backup.log 2>&1
```

异地保存（任选）：

```bash
# rsync 到另一台机器
rsync -av backups/ backup-host:/srv/pullspool-backups/

# rclone 到对象存储
rclone copy backups/ remote:pullspool-backups/

# 加密后再外传（推荐；备份含 .env 密钥）
gpg --symmetric --cipher-algo AES256 backups/pullspool-*.tar.gz
```

监控磁盘：备份目录本身也会占空间，失败日志会写入上面的 log 文件。

## 4. 恢复

```bash
cd /opt/pullspool
bash scripts/restore.sh backups/pullspool-YYYYmmdd-HHMMSS.tar.gz
```

脚本会：

1. `docker compose down`（停止写入）；
2. 把现有 `data/{db,aria2,caddy}` 移到 `data/.rescue-<时间>`；
3. 解包备份；
4. 修正属主（以 root 运行时）；
5. `docker compose up -d` 并提示跑冒烟测试。

恢复后验证：

```bash
curl -k https://127.0.0.1:18443/api/health
bash scripts/smoke-test.sh
# 登录网页，确认任务/设置/历史存在
```

确认无误后再删除 `data/.rescue-*`。

### 手动恢复（脚本不可用时）

```bash
docker compose down
mv data/db data/db.broken && mkdir -p data/db
tar xzf backups/pullspool-YYYYmmdd-HHMMSS.tar.gz -C .
sudo chown -R 1000:1000 data
docker compose up -d
```

> 恢复包含数据库结构；如果备份来自旧版本，启动时 backend 会自动执行迁移。

## 5. 演练与检查

- **每季度演练一次**：在测试目录恢复一份备份，执行 `smoke-test.sh`，确认能登录、能建任务。
- 检查归档完整性：`tar tzf backups/xxx.tar.gz | head`。
- 检查数据库：`docker compose exec -T backend python -c "import sqlite3;print(sqlite3.connect('/data/db/pullspool.db').execute('PRAGMA integrity_check').fetchone())"`。
- 备份文件含 RPC/令牌密钥与 `.env`，泄露等同于泄露部署密钥；请加密并限制访问。
- 下载文件默认不备份：它们本就是临时文件，且体积可能很大。
