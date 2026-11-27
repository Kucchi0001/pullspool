# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="PullSpool backend"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata keeps "today" buckets and log timestamps correct on minimal images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 pullspool \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin pullspool

WORKDIR /app

ARG PIP_INDEX_URL=""
COPY requirements.txt ./
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --index-url "$PIP_INDEX_URL" -r requirements.txt; \
    else \
        pip install -r requirements.txt; \
    fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN mkdir -p /data && chown -R pullspool:pullspool /app /data

USER pullspool
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=8s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status == 200 else 1)"

# One worker only: SQLite, the in-memory event bus and the rate limiter all
# assume a single process.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
