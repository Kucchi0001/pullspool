#!/bin/sh
# PullSpool one-command setup for a fresh Linux VPS.
#
#   sudo ./scripts/quickstart.sh
#   ./scripts/quickstart.sh --domain pull.example.com
#   ./scripts/quickstart.sh --http --ip 203.0.113.5
#
# It creates .env from .env.example when missing, detects the public IP,
# writes UID/GID/data paths, runs preflight, builds/starts the stack and waits
# for /api/health. Internal TLS is the default; the CA still has to be imported
# into the browser/OS (the script prints its path).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

HTTP_ONLY=0
IP=""
DOMAIN=""
EMAIL=""
HTTP_PORT=""
HTTPS_PORT=""
HTTP_PORT_SET=0
HTTPS_PORT_SET=0
BIND=""
PROJECT=""
DATA_DIR=""
GHCR=""
NO_BUILD=0
SKIP_PREFLIGHT=0
DRY_RUN=0

usage() {
  cat <<'EOF'
用法: ./scripts/quickstart.sh [选项]

  --ip <IP>             公网 IP（默认自动检测）
  --domain <域名>       使用 Let's Encrypt（自动把端口设为 80/443）
  --email <邮箱>        ACME 邮箱（可选）
  --http                纯 HTTP 模式（仅测试；会明文传输密码）
  --http-port <端口>    默认 18080
  --https-port <端口>   默认 18443
  --bind <地址>         监听地址，默认 0.0.0.0；仅本机可填 127.0.0.1
  --project <名称>      Compose 项目名，默认 pullspool
  --data-dir <目录>     数据目录，默认 ./data
  --ghcr <命名空间>     使用预构建镜像，如 ghcr.io/yourname（不本地构建）
  --no-build            不构建镜像（本地已有镜像时用）
  --skip-preflight      跳过 preflight 检查（不推荐）
  --dry-run             只生成 .env 并打印计划，不启动容器
  -h, --help            显示帮助
EOF
}

need_value() {
  if [ "$#" -lt 2 ] || [ -z "$2" ]; then
    echo "缺少参数值: $1" >&2
    usage >&2
    exit 2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --ip) need_value "$1" "${2:-}"; IP=$2; shift 2 ;;
    --domain) need_value "$1" "${2:-}"; DOMAIN=$2; shift 2 ;;
    --email) need_value "$1" "${2:-}"; EMAIL=$2; shift 2 ;;
    --http) HTTP_ONLY=1; shift ;;
    --http-port) need_value "$1" "${2:-}"; HTTP_PORT=$2; HTTP_PORT_SET=1; shift 2 ;;
    --https-port) need_value "$1" "${2:-}"; HTTPS_PORT=$2; HTTPS_PORT_SET=1; shift 2 ;;
    --bind) need_value "$1" "${2:-}"; BIND=$2; shift 2 ;;
    --project) need_value "$1" "${2:-}"; PROJECT=$2; shift 2 ;;
    --data-dir) need_value "$1" "${2:-}"; DATA_DIR=$2; shift 2 ;;
    --ghcr) need_value "$1" "${2:-}"; GHCR=$2; shift 2 ;;
    --no-build) NO_BUILD=1; shift ;;
    --skip-preflight) SKIP_PREFLIGHT=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$DRY_RUN" = 0 ]; then
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "需要 Docker Engine 24+ 和 Docker Compose v2：" >&2
    echo "  https://docs.docker.com/engine/install/" >&2
    exit 1
  fi
fi

NEW_ENV=0
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  NEW_ENV=1
  echo "[quickstart] 已从 .env.example 创建 .env"
fi

get_env() {
  awk -v k="$1" 'index($0, k "=") == 1 { value = substr($0, length(k) + 2) } END { print value }' .env
}

set_env() {
  key=$1
  value=$2
  tmp=".env.quickstart.$$"
  awk -v k="$key" -v v="$value" '
    index($0, k "=") == 1 { print k "=" v; found = 1; next }
    { print }
    END { if (!found) print k "=" v }
  ' .env > "$tmp"
  mv "$tmp" .env
  chmod 600 .env
}

detect_ip() {
  if command -v curl >/dev/null 2>&1; then
    for endpoint in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
      candidate=$(curl -4 -fsS --max-time 5 "$endpoint" 2>/dev/null | tr -d '[:space:]' || true)
      case "$candidate" in
        *.*.*.*) printf '%s\n' "$candidate"; return 0 ;;
      esac
    done
  fi
  if command -v hostname >/dev/null 2>&1; then
    candidate=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    case "$candidate" in
      *.*.*.*) printf '%s\n' "$candidate"; return 0 ;;
    esac
  fi
  return 1
}

MODE=$(get_env TLS_MODE)
if [ "$HTTP_ONLY" = 1 ]; then
  MODE=off
elif [ -n "$DOMAIN" ]; then
  MODE=acme
elif [ -z "$MODE" ]; then
  MODE=internal
fi

if [ -z "$IP" ]; then
  IP=$(get_env PUBLIC_IP)
fi
case "$IP" in
  ""|203.0.113.5) IP="" ;;
esac

if [ -z "$IP" ] && [ "$MODE" != "acme" ]; then
  echo "[quickstart] 正在检测公网 IP…"
  if ! IP=$(detect_ip); then
    echo "无法自动检测公网 IP。请用 --ip <公网IP> 指定。" >&2
    exit 1
  fi
fi

if [ -z "$DOMAIN" ] && [ "$MODE" = "acme" ]; then
  DOMAIN=$(get_env DOMAIN)
fi
if [ "$MODE" = "acme" ] && [ -z "$DOMAIN" ]; then
  echo "TLS_MODE=acme 需要 --domain <域名> 或在 .env 设置 DOMAIN。" >&2
  exit 1
fi

if [ -z "$HTTP_PORT" ]; then
  HTTP_PORT=$(get_env HTTP_PORT)
fi
if [ -z "$HTTPS_PORT" ]; then
  HTTPS_PORT=$(get_env HTTPS_PORT)
fi
if [ "$MODE" = "acme" ]; then
  [ "$HTTP_PORT_SET" = 1 ] || HTTP_PORT=80
  [ "$HTTPS_PORT_SET" = 1 ] || HTTPS_PORT=443
else
  : "${HTTP_PORT:=18080}"
  : "${HTTPS_PORT:=18443}"
fi
if [ -z "$BIND" ]; then
  BIND=$(get_env BIND_ADDRESS)
  : "${BIND:=0.0.0.0}"
fi
if [ -z "$DATA_DIR" ]; then
  DATA_DIR=$(get_env HOST_DATA_DIR)
  : "${DATA_DIR:=./data}"
fi

if [ "$NEW_ENV" = 1 ]; then
  if [ "$(id -u)" -eq 0 ]; then
    if [ -n "${SUDO_UID:-}" ]; then
      RUN_UID=$SUDO_UID
      RUN_GID=${SUDO_GID:-$(id -g "$SUDO_UID")}
    else
      RUN_UID=1000
      RUN_GID=1000
      echo "[quickstart] 以 root 直接运行，数据目录将归属 1000:1000；建议用 sudo 从普通用户执行。"
    fi
  else
    RUN_UID=$(id -u)
    RUN_GID=$(id -g)
  fi
  set_env PULLSPOOL_UID "$RUN_UID"
  set_env PULLSPOOL_GID "$RUN_GID"
else
  RUN_UID=$(get_env PULLSPOOL_UID)
  RUN_GID=$(get_env PULLSPOOL_GID)
  : "${RUN_UID:=1000}"
  : "${RUN_GID:=1000}"
fi
set_env HOST_DATA_DIR "$DATA_DIR"
set_env HTTP_PORT "$HTTP_PORT"
set_env HTTPS_PORT "$HTTPS_PORT"
set_env BIND_ADDRESS "$BIND"

if [ "$MODE" = "acme" ]; then
  set_env HTTPS_ENABLED true
  set_env HTTP_ENABLED true
  set_env TLS_MODE acme
  set_env DOMAIN "$DOMAIN"
  set_env TLS_HOST "$DOMAIN"
  set_env PUBLIC_BASE_URL "https://$DOMAIN"
  [ -n "$EMAIL" ] && set_env ACME_EMAIL "$EMAIL"
  if [ -n "$IP" ]; then
    set_env PUBLIC_IP "$IP"
  else
    set_env PUBLIC_IP ""
  fi
elif [ "$MODE" = "off" ]; then
  set_env HTTPS_ENABLED false
  set_env HTTP_ENABLED true
  set_env TLS_MODE off
  set_env TLS_HOST "$IP"
  set_env PUBLIC_IP "$IP"
  set_env PUBLIC_BASE_URL "http://$IP:$HTTP_PORT"
  echo "[quickstart] 警告：纯 HTTP 会明文传输密码，仅限内网/SSH 隧道测试。"
else
  set_env HTTPS_ENABLED true
  set_env HTTP_ENABLED true
  set_env TLS_MODE internal
  set_env TLS_HOST "$IP"
  set_env PUBLIC_IP "$IP"
  set_env PUBLIC_BASE_URL "https://$IP:$HTTPS_PORT"
fi

if [ -n "$PROJECT" ]; then
  set_env COMPOSE_PROJECT_NAME "$PROJECT"
fi
if [ -n "$GHCR" ]; then
  case "$GHCR" in
    */*) ;;
    *) GHCR="ghcr.io/$GHCR" ;;
  esac
  set_env PULLSPOOL_GHCR_NAMESPACE "$GHCR"
fi

DATA_PATH=$DATA_DIR
case "$DATA_PATH" in
  /*) ;;
  *) DATA_PATH="$ROOT/$DATA_PATH" ;;
esac
mkdir -p "$DATA_PATH"
DATA_PATH=$(CDPATH= cd -- "$DATA_PATH" && pwd)
if [ "$(id -u)" -eq 0 ]; then
  chown -R "$RUN_UID:$RUN_GID" "$DATA_PATH" 2>/dev/null || true
  chmod 750 "$DATA_PATH" 2>/dev/null || true
fi
if [ ! -w "$DATA_PATH" ] && [ "$(id -u)" -ne 0 ]; then
  echo "数据目录不可写: $DATA_PATH" >&2
  echo "请执行: sudo chown -R $RUN_UID:$RUN_GID $DATA_PATH" >&2
  exit 1
fi
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_UID:-}" ]; then
  chown "$RUN_UID:$RUN_GID" .env 2>/dev/null || true
fi

if [ "$MODE" = "acme" ]; then
  BASE_URL="https://$DOMAIN"
elif [ "$MODE" = "off" ]; then
  BASE_URL="http://$IP:$HTTP_PORT"
else
  BASE_URL="https://$IP:$HTTPS_PORT"
fi

echo
echo "[quickstart] 配置完成"
echo "  访问地址 : $BASE_URL"
echo "  数据目录 : $DATA_PATH"
echo "  TLS 模式 : $MODE"
if [ "$MODE" = "off" ]; then
  echo "  初始账号 : admin（密码见 $DATA_PATH/bootstrap-admin.txt）"
elif [ "$MODE" = "internal" ]; then
  echo "  初始账号 : admin（密码见 $DATA_PATH/bootstrap-admin.txt）"
  echo "  CA 根证书: $DATA_PATH/caddy/data/caddy/pki/authorities/local/root.crt"
fi

compose() {
  if [ -n "$GHCR" ]; then
    docker compose -f "$ROOT/docker-compose.release.yml" "$@"
  else
    docker compose -f "$ROOT/docker-compose.yml" "$@"
  fi
}

if [ "$DRY_RUN" = 1 ]; then
  echo
  echo "[quickstart] dry-run：未启动容器"
  echo "  下一步: preflight -> docker compose up"
  exit 0
fi

if [ "$SKIP_PREFLIGHT" = 0 ]; then
  echo
  sh "$ROOT/scripts/preflight.sh"
fi

if [ -n "$GHCR" ]; then
  echo "[quickstart] 拉取预构建镜像: $GHCR"
  compose pull
  echo "[quickstart] 启动容器（--no-build）"
  compose up -d --no-build
elif [ "$NO_BUILD" = 1 ]; then
  echo "[quickstart] 启动容器（--no-build）"
  compose up -d --no-build
else
  echo "[quickstart] 构建并启动容器（首次可能需要几分钟）"
  compose up -d --build
fi

if command -v curl >/dev/null 2>&1; then
  if [ "$MODE" = "off" ]; then
    HEALTH_URL="http://127.0.0.1:$HTTP_PORT/api/health"
    HEALTH_OPTS=""
  else
    HEALTH_URL="https://127.0.0.1:$HTTPS_PORT/api/health"
    HEALTH_OPTS="-k"
  fi
  echo "[quickstart] 等待健康检查: $HEALTH_URL"
  i=0
  while [ "$i" -lt 45 ]; do
    if curl $HEALTH_OPTS -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      break
    fi
    i=$((i + 1))
    sleep 2
  done
  if [ "$i" -ge 45 ]; then
    echo "健康检查超时。查看日志：" >&2
    echo "  docker compose -f $ROOT/docker-compose.yml logs --tail=80 caddy backend" >&2
    exit 1
  fi
else
  echo "[quickstart] 未找到 curl，跳过健康检查；请手动打开 $BASE_URL"
fi

echo
echo "PullSpool 已启动: $BASE_URL"
if [ -f "$DATA_PATH/bootstrap-admin.txt" ]; then
  echo "初始凭据（首次登录后必须改密）："
  sed -n 's/^用户名: /  用户名: /p; s/^密码:   /  密码:   /p' "$DATA_PATH/bootstrap-admin.txt" || true
fi
if [ "$MODE" = "internal" ]; then
  echo "浏览器提示证书不受信任时，导入："
  echo "  $DATA_PATH/caddy/data/caddy/pki/authorities/local/root.crt"
fi
echo "查看日志: docker compose -f $ROOT/docker-compose.yml logs -f"
