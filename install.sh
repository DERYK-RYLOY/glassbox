#!/usr/bin/env bash
# GLASSBOX - zero-babysitting macOS/Linux installer
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$ROOT/python/glassbox_server.py"

step() { printf '\n\033[36m[%s] %s\033[0m\n' "$1" "$2"; }
ok() { printf '\033[32m    OK: %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    !! %s\033[0m\n' "$1"; }

printf '\n\033[35m  GLASSBOX - audited by code, not vibes\033[0m\n'
printf '\033[90m  installing...\033[0m\n'

# --- 1. Python ------------------------------------------------------------
step 1/4 'Checking Python 3.10+'
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" --version 2>&1 || true)
    case "$v" in *Python\ 3.*) PY="$c"; break ;; esac
  fi
done
if [ -z "$PY" ]; then warn 'Python 3.10+ not found - install from https://www.python.org/downloads/ and re-run.'; exit 1; fi
ok "$PY $($PY --version)"

# --- 2. Dependencies --------------------------------------------------------
step 2/4 'Installing dependencies (mcp, onnxruntime, tokenizers)'
"$PY" -m pip install -r "$ROOT/requirements.txt" --quiet
ok 'dependencies installed'

# --- 3. Lua (optional) ------------------------------------------------------
step 3/4 'Checking Lua 5.x'
if command -v lua >/dev/null 2>&1; then ok "$(lua -v 2>&1)";
else
  warn 'Lua not found - Glassbox will run on its Python fallback (fully functional).'
  printf '\033[90m    For the native Lua engine: brew install lua / sudo apt install lua5.4\033[0m\n'
fi

# --- 4. Self-test -----------------------------------------------------------
step 4/4 'Self-test'
cd "$ROOT"
STATUS="$("$PY" -c "import sys; sys.path.insert(0, 'python'); import glassbox_server as g; print(g.glassbox_status())")"
printf '    %s\n' "$STATUS"
if printf '%s' "$STATUS" | grep -q '"backend"'; then
  printf '\n\033[32m  GLASSBOX is installed. Add to your AI CLI:\033[0m\n'
  printf '    { "mcp": { "servers": { "glassbox": { "type": "local", "command": ["%s", "%s"] } } } }\n' "$PY" "$SERVER"
  printf '\033[90m  Or for OpenCode with the CLI already installed:\033[0m\n'
  printf '    opencode mcp add glassbox --global -- %s %s\n\n' "$PY" "$SERVER"
  exit 0
else
  warn 'Self-test failed - run python python/glassbox_server.py manually to see the error.'
  exit 1
fi
