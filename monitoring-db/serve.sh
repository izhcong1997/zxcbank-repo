#!/bin/sh
# Live mode: refresh GitHub data every 20 seconds and serve the dashboard.
set -eu
cd "$(dirname "$0")"
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Set GITHUB_TOKEN to a read-only fine-grained token for this repository."
  exit 1
fi
python fetch_data.py --watch 20 &
fetch_pid=$!
python -m http.server 8080 &
server_pid=$!
trap 'kill "$fetch_pid" "$server_pid" 2>/dev/null' INT TERM
wait
