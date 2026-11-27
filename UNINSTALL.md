# 卸载 PullSpool

> 删除数据不可恢复。卸载前请确认已取回需要的文件，或先做一次备份（[BACKUP.md](BACKUP.md)）。

## 1. 停止并删除容器与网络

```bash
cd /opt/pullspool
docker compose down
```

`down` 只删除容器、网络，不会删除 `./data`。

## 2. 决定是否保留数据

### 保留数据（以后重装可继续用）

```bash
# 数据仍在 ./data，可整体打包留存
sudo tar czf ~/pullspool-data-$(date +%F).tar.gz ./data
```

### 彻底删除

```bash
# 确认路径无误后执行
sudo rm -rf ./data
```

如果修改过 `HOST_DATA_DIR` 或使用自定义路径，请以 `.env` 中的实际值为准，并再次确认：

```bash
grep HOST_DATA_DIR .env
```

## 3. 删除镜像（可选）

```bash
docker image rm pullspool-backend:local pullspool-frontend:local pullspool-aria2:local 2>/dev/null || true
# 若不再使用 Caddy 基础镜像
docker image rm caddy:2-alpine 2>/dev/null || true
```

## 4. 移除根证书信任（使用 internal CA 时）

**Windows**：`certmgr.msc` → 受信任的根证书颁发机构 → 证书 → 删除 PullSpool CA；
或管理员 PowerShell：`certutil -delstore Root "<证书指纹或名称>"`。

**macOS**：钥匙串访问 → 系统 → 找到 PullSpool CA → 删除。

**Linux**：`sudo rm /usr/local/share/ca-certificates/pullspool.crt && sudo update-ca-certificates --fresh`。

**iOS**：设置 → 通用 → VPN 与设备管理 → 删除描述文件；再到「证书信任设置」关闭。

**Android**：设置 → 安全 → 加密与凭据 → 用户凭据 → 删除。

## 5. 清理外围

- 云防火墙/安全组关闭 18080、18443（或 80、443）；
- 删除域名 A 记录；
- 删除定时备份任务（`crontab -e`）；
- 删除本地的 `root.crt`、`.env` 副本与备份文件。

## 6. 确认

```bash
docker compose ps          # 应为空
docker ps -a | grep pullspool
ss -ltnp | grep -E '18080|18443'
```

都无输出即卸载干净。
