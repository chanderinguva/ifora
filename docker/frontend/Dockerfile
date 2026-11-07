# Two targets. Default (dev): `next dev`, used by the local stack and the e2e suite.
# Production: docker compose build --build-arg ... with FRONTEND_TARGET=prod (see docker/.env.example): a compiled build
# served by `next start`, run as a non-root user. NEXT_PUBLIC_* values are fixed at build time.
FROM node:20-alpine AS base
WORKDIR /app
COPY frontend/package*.json ./

FROM base AS dev
RUN npm install
COPY frontend/ .
RUN adduser -D appuser && chown -R appuser /app
USER appuser
EXPOSE 3000
CMD ["npx", "next", "dev", "-H", "0.0.0.0", "-p", "3000"]

FROM base AS build
RUN npm ci
COPY frontend/ .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY frontend/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/next.config.js ./next.config.js
RUN adduser -D appuser && chown -R appuser /app
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
