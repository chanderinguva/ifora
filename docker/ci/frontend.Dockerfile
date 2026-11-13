FROM node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /opt/ci/frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
