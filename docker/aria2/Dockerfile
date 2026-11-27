FROM alpine:3.20

LABEL org.opencontainers.image.title="PullSpool aria2"
LABEL org.opencontainers.image.licenses="MIT"

RUN apk add --no-cache \
        aria2 \
        ca-certificates \
        tini \
        iptables \
        su-exec \
    && addgroup -g 1000 aria2 \
    && adduser -D -u 1000 -G aria2 -h /home/aria2 aria2

COPY aria2.conf /etc/aria2/aria2.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY egress-guard.sh /usr/local/bin/egress-guard.sh

RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/egress-guard.sh \
    && mkdir -p /data/downloads /aria2 \
    && chown 1000:1000 /data/downloads /aria2

VOLUME ["/data/downloads", "/aria2"]
EXPOSE 6800

# The entrypoint needs root only to install the egress firewall rules and fix
# volume ownership; it then execs aria2c as the unprivileged download user.
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
