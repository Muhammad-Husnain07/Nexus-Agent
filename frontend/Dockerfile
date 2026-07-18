# =============================================================================
# Nexus Console — Frontend multi-stage Dockerfile
#
# Builder:  builds the Vite React app
# Runtime:  serves static assets via nginx, proxies API to backend
# =============================================================================

# ── Builder ──────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM nginx:alpine

RUN addgroup -S nexus && adduser -S nexus -G nexus

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN chown -R nexus:nexus /usr/share/nginx/html /var/cache/nginx /var/run && \
    chmod -R 755 /usr/share/nginx/html

USER nexus

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
