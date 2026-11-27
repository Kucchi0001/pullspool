#!/bin/sh
# PullSpool aria2 entrypoint.
#
# Responsibilities:
#   1. resolve (or generate) the RPC secret shared with the backend,
#   2. install the egress firewall (SSRF layer L4) when enabled,
#   3. fix volume ownership and drop privileges to the download user,
#   4. start aria2 with the session file so restarts resume in-flight tasks.
set -eu

# Downloaded files must not be world-readable on multi-user hosts.
umask 077

SECRET_FILE=/aria2/secret
SESSION_FILE=/aria2/session.txt
GUARD_STATUS=/aria2/egress-guard.status
PUID="${PULLSPOOL_UID:-1000}"
PGID="${PULLSPOOL_GID:-1000}"

mkdir -p /aria2 /data/downloads

# --- 1. RPC secret ---------------------------------------------------------
if [ -n "${ARIA2_RPC_SECRET:-}" ]; then
    SECRET="${ARIA2_RPC_SECRET}"
    umask 077
    printf '%s' "${SECRET}" > "${SECRET_FILE}"
elif [ -s "${SECRET_FILE}" ]; then
    SECRET="$(cat "${SECRET_FILE}")"
else
    SECRET="$(head -c 32 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-32)"
    umask 077
    printf '%s' "${SECRET}" > "${SECRET_FILE}"
    echo "[aria2] generated a new RPC secret in ${SECRET_FILE}" >&2
fi

# --- 2. egress firewall (SSRF L4) -----------------------------------------
if [ "${ARIA2_EGRESS_GUARD:-on}" = "on" ]; then
    if /usr/local/bin/egress-guard.sh; then
        echo "ok" > "${GUARD_STATUS}"
        echo "[aria2] egress guard active" >&2
    else
        echo "failed" > "${GUARD_STATUS}"
        echo "[aria2] WARNING: egress guard failed; relying on URL/DNS checks only" >&2
    fi
else
    echo "disabled" > "${GUARD_STATUS}"
    echo "[aria2] WARNING: egress guard disabled" >&2
fi

# --- 3. ownership ----------------------------------------------------------
chown "${PUID}:${PGID}" /aria2 /data/downloads 2>/dev/null || true
chown "${PUID}:${PGID}" "${SECRET_FILE}" "${GUARD_STATUS}" 2>/dev/null || true
if [ -f "${SESSION_FILE}" ]; then
    chown "${PUID}:${PGID}" "${SESSION_FILE}" 2>/dev/null || true
fi

# --- 4. start --------------------------------------------------------------
set -- aria2c \
    --conf-path=/etc/aria2/aria2.conf \
    --dir=/data/downloads \
    --rpc-listen-port="${ARIA2_RPC_PORT:-6800}" \
    --rpc-secret="${SECRET}" \
    --save-session="${SESSION_FILE}" \
    --save-session-interval="${ARIA2_SAVE_SESSION_INTERVAL:-30}"

if [ -s "${SESSION_FILE}" ]; then
    set -- "$@" --input-file="${SESSION_FILE}"
fi

exec su-exec "${PUID}:${PGID}" "$@"
