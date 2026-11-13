FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev pkg-config libxml2-dev libxmlsec1-dev libxmlsec1-openssl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/ci/backend
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-dev.txt
