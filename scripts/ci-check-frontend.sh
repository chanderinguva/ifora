#!/bin/sh
set -eu
cd frontend
ln -s /opt/ci/frontend/node_modules node_modules
trap 'rm -f node_modules' EXIT
npm run lint
npm run type-check
