# syntax=docker/dockerfile:1
# Sevaro Pulse UI: Next.js standalone server. Build from frontend/:  docker build -t sevaro-pulse/frontend .

FROM node:24-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

# --- Dependencies
FROM base AS deps
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- Build
FROM base AS build
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time. The empty default
# makes the UI call /api on its own origin, which the reverse proxy routes to the backend,
# so one image works on any domain. Set a full URL only if the API lives on another origin.
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_STATUS_POLL_MS=15000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_STATUS_POLL_MS=$NEXT_PUBLIC_STATUS_POLL_MS \
    BUILD_STANDALONE=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# --- Runtime image: the traced standalone server plus static assets, no node_modules install
FROM base AS runtime
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN mkdir .next && chown node:node .next
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node

EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]

CMD ["node", "server.js"]
