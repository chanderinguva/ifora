#!/bin/sh
# Only manifests and Dockerfiles enter these contexts, never source or secrets.
set -eu
ci_context="$(mktemp -d)"
trap 'rm -rf "$ci_context"' EXIT
mkdir "$ci_context/backend" "$ci_context/frontend"
cp docker/ci/backend.Dockerfile "$ci_context/backend/Dockerfile"
cp backend/requirements.txt backend/requirements-dev.txt "$ci_context/backend/"
cp docker/ci/frontend.Dockerfile "$ci_context/frontend/Dockerfile"
cp frontend/package.json frontend/package-lock.json "$ci_context/frontend/"
# Re-run docker build each time: changed manifests invalidate the install layer.
# Fixed local tags are safe with this dedicated single-capacity Mac runner.
docker build -t ifora-ci-backend:py312 "$ci_context/backend"
docker build -t ifora-ci-frontend:node20 "$ci_context/frontend"
