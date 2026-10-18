#!/usr/bin/env bash
# Deploy the Steward MCP server (mcp-runtime) to Manufact Cloud from the CLI.
# Reads the same values the dashboard form asks for. Nothing here runs git.
# Usage: STEWARD_BACKEND_URL=https://<handle>.inkboxwire.com bash manufact/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${STEWARD_BACKEND_URL:?set STEWARD_BACKEND_URL to the public https tunnel URL of the backend}"
NAME="${MANUFACT_SERVER_NAME:-steward}"
ARGS=(
  --name "$NAME"
  --root-dir mcp-runtime
  --dockerfile Dockerfile
  --env "STEWARD_BACKEND_URL=$STEWARD_BACKEND_URL"
  --env "STEWARD_ALLOW_REMOTE_BACKEND=true"
  --env "STEWARD_MCP_PROPERTY_IDS=harbor-works,myer-plant,bristol-pumps"
)
[ -n "${STEWARD_BACKEND_TOKEN:-}" ] && ARGS+=(--env "STEWARD_BACKEND_TOKEN=$STEWARD_BACKEND_TOKEN")
[ -n "${STEWARD_MCP_TOKEN:-}" ]     && ARGS+=(--env "STEWARD_MCP_TOKEN=$STEWARD_MCP_TOKEN")
[ -n "${ARMATURE_API_KEY:-}" ]      && ARGS+=(--env "ARMATURE_API_KEY=$ARMATURE_API_KEY" --env "ANALYTICS_INGEST_API_KEY=$ARMATURE_API_KEY")
[ -n "${ANALYTICS_INGEST_URL:-}" ]  && ARGS+=(--env "ANALYTICS_INGEST_URL=$ANALYTICS_INGEST_URL")
# --no-github uploads the local source as a tarball to a Manufact-managed repo (no GitHub push needed).
# Drop it once the public GitHub repo exists and the mcp-use GitHub App is installed on it.
exec npx -y mcp-use@latest deploy "${ARGS[@]}" --no-github -y "$@"
