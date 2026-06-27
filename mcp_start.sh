#!/usr/bin/env bash
# mcp_start.sh — start the kapa-rag MCP server
#
# Credentials are loaded from .env. The Python TokenManager inside the server
# handles login + silent token refresh automatically — no restarts needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load env vars from .env (OPENAI_API_KEY, COHERE_API_KEY, LOAD_TEST_PASSWORD, etc.)
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
fi

export QUERY_SERVICE_URL="${QUERY_SERVICE_URL:-http://54.156.190.134:9000}"
export AUTH_URL="${AUTH_URL:-http://54.156.190.134:8004}"

exec "$SCRIPT_DIR/venv/bin/python" -m backend.mcp.server
