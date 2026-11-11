#!/usr/bin/env bash
# Usage: scripts/need.sh <command> "<how to install it>"
# Fails with a clear message when a gate's tool is missing, instead of an obscure "command not found".
set -u
cmd="${1:?usage: need.sh <command> <install hint>}"
hint="${2:-see scripts/TOOLS.txt}"
# $cmd may carry arguments (e.g. a docker wrapper); only the first word has to exist.
first="${cmd%% *}"
if ! command -v "$first" >/dev/null 2>&1; then
  echo "MISSING TOOL: '$first' is not installed or not on PATH." >&2
  echo "  install: $hint" >&2
  echo "  all tools and pinned versions: make tools" >&2
  exit 127
fi
