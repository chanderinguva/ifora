FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /opt/ci/frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
