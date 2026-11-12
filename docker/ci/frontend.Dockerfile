FROM node:20-bookworm-slim
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /opt/ci/frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
