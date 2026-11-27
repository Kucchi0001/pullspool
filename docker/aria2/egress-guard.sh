#!/bin/sh
# SSRF layer L4: block aria2 from reaching private, loopback, link-local,
# carrier-grade-NAT and cloud-metadata destinations at the network layer.
#
# This is the only layer that still holds when a target site behaves
# differently for aria2 than it did during the preflight probe (TOCTOU /
# DNS rebinding). Name resolution must keep working, so the container's
# configured resolver(s) are allowed on port 53 *before* the private ranges
# are rejected:
#   - Docker's embedded resolver on Linux hosts: 127.0.0.11
#   - Docker Desktop's forwarder in the VM: usually 192.168.65.x
# Those allowances are limited to UDP/TCP 53 towards the exact resolver IPs.
#
# Requires CAP_NET_ADMIN. Exits non-zero when the rules cannot be installed;
# the entrypoint records the failure and the backend surfaces it as degraded.
set -eu

if ! command -v iptables >/dev/null 2>&1; then
    echo "[egress-guard] iptables not found" >&2
    exit 1
fi

allow_dns() {
    address="$1"
    case "${address}" in
        *:*)  # IPv6 resolver
            if command -v ip6tables >/dev/null 2>&1; then
                ip6tables -w 5 -A OUTPUT -p udp -d "${address}" --dport 53 -j ACCEPT 2>/dev/null || true
                ip6tables -w 5 -A OUTPUT -p tcp -d "${address}" --dport 53 -j ACCEPT 2>/dev/null || true
            fi
            ;;
        *)
            iptables -w 5 -A OUTPUT -p udp -d "${address}" --dport 53 -j ACCEPT
            iptables -w 5 -A OUTPUT -p tcp -d "${address}" --dport 53 -j ACCEPT
            ;;
    esac
}

# Replies on already-accepted connections must pass, otherwise the backend's
# RPC calls (backend -> aria2, reply to a private container IP) and Docker's
# published-port forwarding would be rejected by the rules below. New outbound
# connections to private ranges are still blocked.
if ! iptables -w 5 -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; then
    iptables -w 5 -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
fi

# Docker's embedded DNS is always allowed; the loopback interface is accepted
# first so that this rule is reachable.
iptables -w 5 -A OUTPUT -o lo -j ACCEPT
allow_dns 127.0.0.11

# Resolver(s) actually configured for this container.
if [ -f /etc/resolv.conf ]; then
    while IFS= read -r line; do
        case "${line}" in
            nameserver\ *)
                resolver=${line#nameserver }
                resolver=${resolver%% *}
                if [ -n "${resolver}" ]; then
                    allow_dns "${resolver}"
                fi
                ;;
        esac
    done < /etc/resolv.conf
fi

for network in \
    0.0.0.0/8 \
    10.0.0.0/8 \
    100.64.0.0/10 \
    127.0.0.0/8 \
    169.254.0.0/16 \
    172.16.0.0/12 \
    192.168.0.0/16 \
    224.0.0.0/4 \
    240.0.0.0/4
do
    iptables -w 5 -A OUTPUT -d "${network}" -j REJECT
done

# Best effort IPv6; hosts without IPv6 still succeed.
if command -v ip6tables >/dev/null 2>&1; then
    ip6tables -w 5 -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
    for network in ::1/128 fc00::/7 fe80::/10 ff00::/8; do
        ip6tables -w 5 -A OUTPUT -d "${network}" -j REJECT 2>/dev/null || true
    done
fi

echo "[egress-guard] rules installed" >&2
