#!/bin/sh
# PullSpool preflight: verify the host before `docker compose up`.
# Usage: sudo bash scripts/preflight.sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

problems=0
ok() { printf '  [ok]   %s\n' "$1"; }
warn() { printf '  [warn] %s\n' "$1"; }
bad() { printf '  [fail] %s\n' "$1"; problems=$((problems + 1)); }
section() { printf '\n%s\n' "$1"; }

section "1. Docker"
if command -v docker >/dev/null 2>&1; then
    ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'engine not running')"
else
    bad "docker 未安装：https://docs.docker.com/engine/install/"
fi
if docker compose version >/dev/null 2>&1; then
    ok "docker compose $(docker compose version --short 2>/dev/null || true)"
else
    bad "docker compose v2 不可用（需要 compose 插件）"
fi

section "2. 配置文件"
if [ -f .env ]; then
    ok ".env 存在"
    set +u
    . ./.env
    set -u
else
    bad ".env 不存在：cp .env.example .env"
fi

if docker compose config -q >/dev/null 2>&1; then
    ok "compose 配置语法正确"
else
    bad "docker compose config 失败，请检查 docker-compose.yml 与 .env"
fi

section "3. 端口"
HTTP_PORT="${HTTP_PORT:-18080}"
HTTPS_PORT="${HTTPS_PORT:-18443}"
check_port() {
    port="$1"
    label="$2"
    if command -v ss >/dev/null 2>&1; then
        line=$(ss -ltn "sport = :$port" 2>/dev/null | tail -n +2)
    else
        line=$(netstat -ltn 2>/dev/null | awk -v p=":$port" '$4 ~ p"$"')
    fi
    if [ -n "$line" ]; then
        bad "端口 $port ($label) 已被占用。查看占用：ss -ltnp | grep :$port；或修改 .env 中的端口"
    else
        ok "端口 $port ($label) 空闲"
    fi
}
check_port "$HTTP_PORT" "HTTP"
check_port "$HTTPS_PORT" "HTTPS"

section "4. 资源"
free_mb=$(df -Pm . | awk 'NR==2 {print $4}')
if [ "${free_mb:-0}" -ge 5120 ]; then
    ok "磁盘剩余 ${free_mb} MB"
else
    warn "磁盘剩余仅 ${free_mb} MB，建议至少 5 GB（下载临时文件需要空间）"
fi
mem_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)
if [ "$mem_mb" -ge 900 ]; then
    ok "内存 ${mem_mb} MB"
else
    warn "内存 ${mem_mb} MB，低于推荐的 1 GB"
fi

section "5. TLS 与对外地址"
TLS_MODE="${TLS_MODE:-internal}"
HTTP_ENABLED="${HTTP_ENABLED:-true}"
HTTPS_ENABLED="${HTTPS_ENABLED:-true}"
PUBLIC_IP="${PUBLIC_IP:-}"
TLS_HOST="${TLS_HOST:-${PUBLIC_IP:-}}"
DOMAIN="${DOMAIN:-}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"

if [ "$HTTP_ENABLED" != "true" ] && [ "$HTTPS_ENABLED" != "true" ]; then
    bad "HTTP_ENABLED 与 HTTPS_ENABLED 不能同时为 false"
fi
case "$TLS_MODE" in
    off)
        if [ "$HTTPS_ENABLED" = "true" ]; then
            bad "TLS_MODE=off 时 HTTPS_ENABLED 必须为 false"
        else
            warn "纯 HTTP 模式：登录密码会明文传输，请仅通过 SSH 隧道或内网访问"
        fi
        ;;
    internal)
        if [ -z "$TLS_HOST" ]; then
            bad "TLS_MODE=internal 需要 TLS_HOST（或 PUBLIC_IP）"
        else
            ok "内部 CA 证书主机：$TLS_HOST"
        fi
        ;;
    acme)
        if [ -z "$DOMAIN" ]; then
            bad "TLS_MODE=acme 需要 DOMAIN"
        else
            ok "ACME 域名：$DOMAIN"
            warn "Let's Encrypt 需要外部能访问 80 端口；本项目默认监听 ${HTTP_PORT}，请做端口转发或用 TLS_MODE=internal"
        fi
        ;;
    *)
        bad "未知 TLS_MODE=$TLS_MODE"
        ;;
esac
if [ -z "$PUBLIC_BASE_URL" ]; then
    warn "PUBLIC_BASE_URL 为空：下载令牌链接与 Origin 校验会使用请求头推断"
else
    ok "对外地址：$PUBLIC_BASE_URL"
fi

section "6. 数据目录"
HOST_DATA_DIR="${HOST_DATA_DIR:-./data}"
mkdir -p "$HOST_DATA_DIR"/{db,downloads,aria2,caddy}
PUID="${PULLSPOOL_UID:-1000}"
PGID="${PULLSPOOL_GID:-1000}"
if [ "$(id -u)" = "0" ]; then
    # Run as root (sudo): make the bind mounts writable by the unprivileged
    # containers that now run caddy/backend/aria2.
    chown -R "$PUID:$PGID" "$HOST_DATA_DIR" 2>/dev/null || true
    chmod 750 "$HOST_DATA_DIR" 2>/dev/null || true
    ok "$HOST_DATA_DIR 属主已设为 $PUID:$PGID（权限 750）"
else
    current=$(stat -c '%u' "$HOST_DATA_DIR" 2>/dev/null || echo "?")
    if [ "$current" = "$PUID" ]; then
        ok "$HOST_DATA_DIR 属主 UID=$current"
    else
        warn "$HOST_DATA_DIR 属主 UID=$current，与 PULLSPOOL_UID=$PUID 不一致"
        warn "建议执行：sudo chown -R ${PUID}:${PGID} $HOST_DATA_DIR"
    fi
fi

section "结果"
if [ "$problems" -eq 0 ]; then
    echo "  检查通过，可以执行：docker compose up -d --build"
    exit 0
fi
echo "  发现 $problems 个必须解决的问题，请先修复再启动。"
exit 1
