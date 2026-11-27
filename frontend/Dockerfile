# syntax=docker/dockerfile:1
FROM node:22-alpine AS build

WORKDIR /app

ARG NPM_REGISTRY="https://registry.npmjs.org"
COPY package.json package-lock.json ./
RUN npm config set registry "$NPM_REGISTRY" \
    && npm ci --no-audit --no-fund

COPY index.html tsconfig.json vite.config.ts ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="PullSpool frontend"
LABEL org.opencontainers.image.licenses="MIT"

COPY --from=licenses . /usr/share/doc/pullspool/

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
