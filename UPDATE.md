# 更新 PullSpool

更新会重建镜像并重启容器，期间服务短暂中断（通常 20–60 秒）。
数据库迁移在 backend 启动时自动执行，且**迁移前会自动备份**到 `data/db/backups/`（保留 3 份）。

## 1. 更新前

```bash
cd /opt/pullspool

# 1) 完整备份（数据库 + 配置 + 密钥）
bash scripts/backup.sh

# 2) 记录当前版本（便于回滚）
docker image tag pullspool-backend:local pullspool-backend:prev
docker image tag pullspool-frontend:local pullspool-frontend:prev
docker image tag pullspool-aria2:local pullspool-aria2:prev
cp .env .env.bak

# 3) 查看新版本的 .env 是否新增变量
#    上传/拉取新代码后执行：
diff -u .env.bak .env.example | head -50
```

## 2. 取得新代码并重建

```bash
# Git 方式
git pull

# 或上传新目录覆盖（保留 ./data 与 .env）

# 按需同步新变量到 .env，然后：
docker compose build
docker compose up -d
```

`docker compose up -d` 只会重建有变化的容器；数据库迁移由 backend 自动完成。

## 3. 验证

```bash
docker compose ps
curl -k https://127.0.0.1:18443/api/health
docker compose logs --tail=80 backend

SMOKE_PASSWORD='你的密码' bash scripts/smoke-test.sh
```

- 打开网页确认任务列表、设置、历史都在；
- 新建一个测试任务，确认下载/取回/删除正常；
- 若 `egress_guard` 不是 `ok`，重启 aria2：`docker compose restart aria2`。

## 4. 回滚

### 4.1 代码回滚

```bash
git checkout <上一个版本 tag/commit>
docker compose build
docker compose up -d
```

### 4.2 镜像回滚（未重新 build 时）

```bash
docker image tag pullspool-backend:prev pullspool-backend:local
docker image tag pullspool-frontend:prev pullspool-frontend:local
docker image tag pullspool-aria2:prev pullspool-aria2:local
docker compose up -d
```

### 4.3 数据回滚

如果新版本的迁移导致数据结构变化，需要同时恢复备份：

```bash
bash scripts/restore.sh backups/pullspool-YYYYmmdd-HHMMSS.tar.gz
```

`restore.sh` 会先停止服务、把现有数据移到 `data/.rescue-*`，再解包并启动。
确认无误后可手动删除 rescue 目录。

> 迁移是单向的：只回滚代码而不恢复数据库，可能与旧代码不兼容。跨版本回滚请成对处理。

## 5. 注意

- 不要把 `./data` 放进 Git；更新不会碰它。
- 更新后若浏览器仍加载旧页面，强制刷新（Ctrl/Cmd+Shift+R）以获取新的静态资源哈希。
- 长期不更新时，至少定期查看 `SECURITY.md` 的依赖与 aria2 风险说明。
