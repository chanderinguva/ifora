#!/bin/sh
set -eu
cd frontend
ln -s /opt/ci/frontend/node_modules node_modules
trap 'rm -f node_modules' EXIT
npm run lint
npm run type-check
npm run test:unit
npm run test:coverage # same tests again with the 70% line gate on the critical-flow files (frontend/vitest.config.mts)

