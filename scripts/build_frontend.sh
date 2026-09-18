#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/frontend"
NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
if [[ -z "$NODE_BIN" ]]; then
  NODE_BIN="$(find "$HOME/.cache/codex-runtimes" -path '*/node/bin/node' 2>/dev/null | head -1 || true)"
fi

if [[ -z "$NODE_BIN" ]]; then
  echo "node is required only to rebuild the frontend; packaged wheels include static assets." >&2
  exit 1
fi

cd "$FRONTEND"

if [[ ! -d node_modules ]]; then
  PNPM_CJS=""
  if command -v pnpm >/dev/null 2>&1; then
    PNPM_CJS="$(node -e 'console.log(require.resolve("pnpm/bin/pnpm.cjs"))' 2>/dev/null || true)"
  fi
  if [[ -z "$PNPM_CJS" ]]; then
    PNPM_CJS="$(find "$HOME/.codex" "$HOME/.cache" -path '*/pnpm/bin/pnpm.cjs' 2>/dev/null | head -1 || true)"
  fi
  if [[ -n "$PNPM_CJS" ]]; then
    "$NODE_BIN" "$PNPM_CJS" install
  else
    echo "pnpm is required for the initial frontend dependency install." >&2
    exit 1
  fi
fi

TSC="$(find node_modules/.pnpm -path '*/typescript/bin/tsc' | head -1)"
VITE="$(find node_modules/.pnpm -path '*/vite/bin/vite.js' | head -1)"
if [[ -z "$TSC" || -z "$VITE" ]]; then
  echo "Frontend dependencies are incomplete." >&2
  exit 1
fi

"$NODE_BIN" "$TSC" -b
"$NODE_BIN" "$VITE" build
