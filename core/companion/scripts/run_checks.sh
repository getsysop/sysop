#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# run_checks.sh — Run deterministic grep checks from .claude/checks.yml
#
# Thin wrapper that invokes the Python implementation.
# See WORKFLOW.md §6.5 for format documentation.
#
# Usage:
#   bash sysop/scripts/run_checks.sh                    # Run all checks
#   bash sysop/scripts/run_checks.sh --mode quality     # Codebase-review checks only
#   bash sysop/scripts/run_checks.sh --mode security    # Security-audit checks only
#   bash sysop/scripts/run_checks.sh --mode both        # All checks (default)
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

# Worktrees don't have their own .venv or node_modules. Resolve the main
# repo's toolchain via git-common-dir so pyright and tsc are reachable
# whether we're in the main checkout or a worktree. Harmless no-op when
# already in the main checkout (git-common-dir returns ".git").
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)" || GIT_COMMON_DIR=".git"
if [[ "$GIT_COMMON_DIR" != ".git" ]]; then
  MAIN_REPO_ROOT="$(cd "${GIT_COMMON_DIR}/.." && pwd)"
else
  MAIN_REPO_ROOT="$REPO_ROOT"
fi
VENV_BIN="${MAIN_REPO_ROOT}/.venv/bin"
# A plain `venv/` layout (no dot) is the other common in-repo venv home —
# probe it when `.venv/` is absent (Phase 133; matches install.sh's
# pick_python_with_yaml order). Out-of-repo venvs (poetry default) are
# covered separately: the pip-audit stage falls back to `python -m pip_audit`
# via whichever interpreter runs the checks.
[[ ! -d "$VENV_BIN" ]] && VENV_BIN="${MAIN_REPO_ROOT}/venv/bin"
FRONTEND_BIN="${REPO_ROOT}/frontend/node_modules/.bin"
# Worktrees typically lack frontend/node_modules — fall back to the main
# repo's install so `tsc` is at least resolvable. Note: _run_tsc will still
# skip gracefully if the worktree's frontend/node_modules/typescript is
# absent, because type resolution needs the adjacent node_modules.
[[ ! -d "$FRONTEND_BIN" ]] && FRONTEND_BIN="${MAIN_REPO_ROOT}/frontend/node_modules/.bin"
[[ -d "$VENV_BIN" ]] && export PATH="${VENV_BIN}:${PATH}"
[[ -d "$FRONTEND_BIN" ]] && export PATH="${FRONTEND_BIN}:${PATH}"

SCRIPT_DIR="${REPO_ROOT}/sysop/scripts"
# Prefer the main repo's venv python (resolves for worktrees too); fall back
# to the current checkout's .venv, then to whatever is on PATH.
if [[ -x "${MAIN_REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON="${MAIN_REPO_ROOT}/.venv/bin/python3"
elif [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python3"
else
  PYTHON="python3"
fi

# Never write bytecode beside the vendored source. CPython caches next to the
# module, so the pre-scan would otherwise mint `sysop/scripts/__pycache__/` and
# `sysop/scripts/run_checks/__pycache__/` in the consumer's tree on every run —
# 12 files — and a consumer without a bytecode ignore then carries them as
# tracked churn. Suppressing the write is the root fix; the gitignore entry
# install.sh appends is belt-and-braces for anything that bypasses this script.
# Measured cost of recompiling each run: ~10ms, against a scan measured in
# seconds. Phase 212.
export PYTHONDONTWRITEBYTECODE=1

exec "$PYTHON" "${SCRIPT_DIR}/run_checks_impl.py" --repo-root "$REPO_ROOT" "$@"
