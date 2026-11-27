FROM caddy:2-alpine

LABEL org.opencontainers.image.title="PullSpool caddy"
LABEL org.opencontainers.image.licenses="MIT"

COPY --from=licenses . /usr/share/doc/pullspool/

# PullSpool ships its Caddy entrypoint inside the image so a released
# compose file needs no bind-mounted repository files.
COPY entrypoint.sh /etc/caddy/entrypoint.sh
RUN chmod 755 /etc/caddy/entrypoint.sh

ENTRYPOINT ["/bin/sh", "/etc/caddy/entrypoint.sh"]
