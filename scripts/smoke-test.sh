#!/bin/sh
# PullSpool smoke test against a running deployment.
#
# Usage:
#   SMOKE_PASSWORD='the-admin-password' bash scripts/smoke-test.sh
#   SMOKE_PASSWORD=... SMOKE_URL=https://example.com/file.zip bash scripts/smoke-test.sh
#
# For TLS_MODE=internal the certificate is self-signed by Caddy's local CA, so
# curl runs with --insecure unless CURL_OPTS is provided explicitly.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ -f .env ]; then
    set +u
    . ./.env
    set -u
fi

BASE="${SMOKE_BASE:-${PUBLIC_BASE_URL:-}}"
if [ -z "$BASE" ]; then
    if [ "${HTTPS_ENABLED:-true}" = "true" ]; then
        BASE="https://${TLS_HOST:-${PUBLIC_IP:-127.0.0.1}}:${HTTPS_PORT:-18443}"
    else
        BASE="http://127.0.0.1:${HTTP_PORT:-18080}"
    fi
fi

CURL_OPTS="${CURL_OPTS:--k -sS}"
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT

step() { printf '%s ... ' "$1"; }
pass() { printf 'ok\n'; }
fail() { printf 'FAIL\n  %s\n' "$1"; exit 1; }

step "health"
body=$(curl $CURL_OPTS "$BASE/api/health") || fail "无法连接 $BASE/api/health"
echo "$body" | grep -q '"status":"ok"' || fail "健康检查未通过：$body"
pass

PASSWORD="${SMOKE_PASSWORD:-}"
if [ -z "$PASSWORD" ]; then
    if [ -f "${HOST_DATA_DIR:-./data}/bootstrap-admin.txt" ]; then
        PASSWORD=$(sed -n 's/^密码:[[:space:]]*//p' "${HOST_DATA_DIR:-./data}/bootstrap-admin.txt")
    fi
fi
if [ -z "$PASSWORD" ]; then
    fail "缺少 SMOKE_PASSWORD，且找不到初始密码文件（首次登录后该文件会被删除）"
fi

step "login"
code=$(curl $CURL_OPTS -c "$JAR" -o /tmp/pullspool-login.json -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${SMOKE_USER:-admin}\",\"password\":\"$PASSWORD\"}" \
    "$BASE/api/auth/login")
[ "$code" = "200" ] || fail "登录失败 HTTP $code：$(cat /tmp/pullspool-login.json 2>/dev/null)"
if grep -q '"must_change_password":true' /tmp/pullspool-login.json; then
    fail "当前仍在使用初始密码，请先在网页中修改密码后再跑 smoke test"
fi
pass

step "settings"
code=$(curl $CURL_OPTS -b "$JAR" -o /dev/null -w '%{http_code}' "$BASE/api/settings")
[ "$code" = "200" ] || fail "设置接口 HTTP $code"
pass

step "task list"
code=$(curl $CURL_OPTS -b "$JAR" -o /dev/null -w '%{http_code}' "$BASE/api/tasks?scope=active")
[ "$code" = "200" ] || fail "任务列表 HTTP $code"
pass

step "system status"
code=$(curl $CURL_OPTS -b "$JAR" -o /tmp/pullspool-status.json -w '%{http_code}' "$BASE/api/system/status")
[ "$code" = "200" ] || fail "系统状态 HTTP $code"
grep -q '"reachable":true' /tmp/pullspool-status.json || fail "aria2 不可达，请检查 docker compose logs aria2 backend"
pass

if [ -n "${SMOKE_URL:-}" ]; then
    step "create task ($SMOKE_URL)"
    task_id=$(curl $CURL_OPTS -b "$JAR" -H 'Content-Type: application/json' \
        -d "{\"url\":\"$SMOKE_URL\"}" "$BASE/api/tasks" \
        | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -n1)
    [ -n "$task_id" ] || fail "创建任务失败"
    pass

    step "wait for completion"
    i=0
    while [ "$i" -lt 60 ]; do
        state=$(curl $CURL_OPTS -b "$JAR" "$BASE/api/tasks/$task_id" \
            | sed -n 's/.*"status":"\([^"]*\)".*/\1/p' | head -n1)
        [ "$state" = "completed" ] && break
        [ "$state" = "failed" ] && fail "任务失败，请查看任务详情"
        i=$((i + 1))
        sleep 2
    done
    [ "$state" = "completed" ] || fail "等待下载超时"
    pass

    step "range download"
    code=$(curl $CURL_OPTS -b "$JAR" -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-99' \
        "$BASE/api/tasks/$task_id/file")
    [ "$code" = "206" ] || fail "Range 请求期望 206，实际 $code"
    pass

    echo
    echo "任务 $task_id 已完成并保留在等待取回页；确认无误后可在网页中删除，或："
    echo "  curl $CURL_OPTS -b <cookie> -X POST $BASE/api/tasks/$task_id/ack -d '{\"confirm\":true}'"
fi

echo
echo "smoke test 通过：$BASE"
