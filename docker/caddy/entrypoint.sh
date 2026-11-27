#!/bin/sh
# Entrypoint notes for maintainers:
# - `auto_https off` would stop Caddy from obtaining the internal certificate
#   entirely, so internal mode only disables automatic HTTP->HTTPS redirects.
# - Browsers never send SNI for IP literals, hence `default_sni`.
# - HTTP->HTTPS uses 308 so non-GET requests keep their method.
#
# Modes:
#   TLS_MODE=off       plain HTTP only (HTTPS_ENABLED must be false)
#   TLS_MODE=internal  HTTPS with Caddy's local CA for TLS_HOST (an IP is fine)
#   TLS_MODE=acme      HTTPS for DOMAIN via Let's Encrypt (needs 80/443 reachable)
set -eu

CONFIG=/tmp/Caddyfile
HTTP_ENABLED="${HTTP_ENABLED:-true}"
HTTPS_ENABLED="${HTTPS_ENABLED:-true}"
TLS_MODE="${TLS_MODE:-internal}"
HTTP_PORT="${HTTP_PORT:-18080}"
HTTPS_PORT="${HTTPS_PORT:-18443}"
TLS_HOST="${TLS_HOST:-}"
DOMAIN="${DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"

if [ "$HTTP_ENABLED" != "true" ] && [ "$HTTPS_ENABLED" != "true" ]; then
    echo "[caddy] HTTP_ENABLED and HTTPS_ENABLED cannot both be false" >&2
    exit 1
fi

if [ "$HTTPS_ENABLED" = "true" ]; then
    case "$TLS_MODE" in
        internal)
            if [ -z "$TLS_HOST" ]; then
                echo "[caddy] TLS_MODE=internal requires TLS_HOST (or PUBLIC_IP)" >&2
                exit 1
            fi
            ;;
        acme)
            if [ -z "$DOMAIN" ]; then
                echo "[caddy] TLS_MODE=acme requires DOMAIN" >&2
                exit 1
            fi
            ;;
        off)
            echo "[caddy] HTTPS_ENABLED=true conflicts with TLS_MODE=off" >&2
            exit 1
            ;;
        *)
            echo "[caddy] unsupported TLS_MODE: $TLS_MODE" >&2
            exit 1
            ;;
    esac
fi

proxy_block() {
    cat <<'EOF'
    encode gzip
    reverse_proxy frontend:80 {
        flush_interval -1
    }
EOF
}

if [ "$HTTPS_ENABLED" = "true" ] && [ "$TLS_MODE" = "acme" ]; then
    {
        echo "{"
        echo "    http_port ${HTTP_PORT}"
        echo "    https_port ${HTTPS_PORT}"
        echo "    admin off"
        if [ -n "$ACME_EMAIL" ]; then
            echo "    email ${ACME_EMAIL}"
        fi
        echo "}"
        echo
        echo "${DOMAIN} {"
        proxy_block
        echo "}"
    } > "$CONFIG"
elif [ "$HTTPS_ENABLED" = "true" ]; then
    {
        echo "{"
        # Ports must be declared in the global block for automatic HTTPS to
        # manage the internal certificate on our non-standard ports.
        echo "    http_port ${HTTP_PORT}"
        echo "    https_port ${HTTPS_PORT}"
        echo "    auto_https disable_redirects"
        echo "    admin off"
        # Browsers never send SNI for IP literals; without a default SNI Caddy
        # cannot pick the certificate and the handshake fails.
        echo "    default_sni ${TLS_HOST}"
        echo "}"
        echo
        echo "https://${TLS_HOST}:${HTTPS_PORT} {"
        echo "    tls internal"
        proxy_block
        echo "}"
        if [ "$HTTP_ENABLED" = "true" ]; then
            echo
            echo "http://:${HTTP_PORT} {"
            echo "    redir https://${TLS_HOST}:${HTTPS_PORT}{uri} 308"
            echo "}"
        fi
    } > "$CONFIG"
else
    {
        echo "{"
        echo "    auto_https off"
        echo "    admin off"
        echo "}"
        echo
        echo "http://:${HTTP_PORT} {"
        proxy_block
        echo "}"
    } > "$CONFIG"
fi

echo "[caddy] generated configuration:" >&2
sed 's/^/[caddy]   /' "$CONFIG" >&2

caddy validate --config "$CONFIG" --adapter caddyfile >&2
exec caddy run --config "$CONFIG" --adapter caddyfile
