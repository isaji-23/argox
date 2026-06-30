# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS build

WORKDIR /app

# Pin pnpm via corepack so the image build matches the committed lockfile
# (lockfileVersion 9.0) without installing through npm/yarn.
RUN corepack enable && corepack prepare pnpm@11.5.0 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
# Rendered by the stock nginx entrypoint at startup: templates in
# /etc/nginx/templates/*.template are envsubst'd into /etc/nginx/conf.d/.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Where nginx proxies /api and /v1. Override per environment (e.g.
# http://collector for Azure Container Apps internal ingress). The filter
# limits substitution to COLLECTOR_* so nginx's own $-variables are preserved.
ENV COLLECTOR_UPSTREAM=http://collector:8000 \
    NGINX_ENVSUBST_FILTER=COLLECTOR_

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1
