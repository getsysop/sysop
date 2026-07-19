#!/usr/bin/env bash
# self_check.sh — one-command post-install health check (Phase 133).
#
# Usage:  bash sysop/scripts/self_check.sh
#
# Verifies the environment a fresh Sysop install depends on and reports one
# line per probe (round-4 cold-read request: bash version + PyYAML + hooks in
# a single command instead of discovery-by-failure):
#   1. git repo + install lock (.claude/sysop.lock) + install mode
#   2. bash version (3.2+ supported; 4+ reported)
#   3. a python3 that can `import yaml` (the validator / checks dependency),
#      probed in the installer's own order: .venv → venv → PATH
#   4. git hooks armed (pre-commit / pre-merge-commit present + executable)
#   5. optional scanners (semgrep, pip-audit, pyright) — advisory only
#
# Exit 0 when every hard prereq passes (1–3; hooks and scanners are reported
# but never fail the check — loop-mode consumers may run checks via CI only).
set -uo pipefail

PASS=0
FAIL=0

ok()   { printf '  ✓ %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '  ✗ %s\n' "$1"; FAIL=$((FAIL + 1)); }
info() { printf '  · %s\n' "$1"; }

printf 'Sysop self-check\n\n'

# ── 1. repo + lock ──────────────────────────────────────────────────────────
if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  ok "git repository: $REPO_ROOT"
else
  bad "not inside a git repository — run from your project root"
  printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
  exit 1
fi

LOCK="$REPO_ROOT/.claude/sysop.lock"
if [[ -f "$LOCK" ]]; then
  MODE="$(sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$LOCK" | head -1)"
  ok "install lock present (mode: ${MODE:-unknown})"
else
  bad "no .claude/sysop.lock — is Sysop installed here? (bash install.sh <target>)"
fi

# ── 2. bash ─────────────────────────────────────────────────────────────────
if [[ "${BASH_VERSINFO[0]:-0}" -ge 4 ]]; then
  ok "bash ${BASH_VERSION}"
elif [[ "${BASH_VERSINFO[0]:-0}" -eq 3 && "${BASH_VERSINFO[1]:-0}" -ge 2 ]]; then
  ok "bash ${BASH_VERSION} (companion scripts run on 3.2; install/update runs need bash 4+ — brew install bash)"
else
  bad "bash ${BASH_VERSION:-unknown} — Sysop scripts need bash 3.2+"
fi

# ── 3. python3 + PyYAML ─────────────────────────────────────────────────────
# Probe the interpreter run_checks.sh will ACTUALLY use (its selection order:
# .venv/bin/python3 unconditionally when executable, then venv/bin via the
# PATH prefix, then PATH python3), then verify PyYAML on THAT interpreter — a
# yaml-capable system python is no comfort if run_checks picks a venv python
# without it (adversarial-review finding, 2026-07-19).
if [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then
  RC_PY="$REPO_ROOT/.venv/bin/python3"
elif [[ -x "$REPO_ROOT/venv/bin/python3" ]]; then
  RC_PY="$REPO_ROOT/venv/bin/python3"
else
  RC_PY="python3"
fi
PYYAML_PY=""
if command -v "$RC_PY" >/dev/null 2>&1 && "$RC_PY" -c 'import yaml' >/dev/null 2>&1; then
  PYYAML_PY="$RC_PY"
  ok "python3 with PyYAML: $RC_PY (what run_checks.sh will use)"
else
  bad "run_checks.sh will use '$RC_PY', which lacks PyYAML (or is broken)"
  info "fix: python3 -m venv .venv && .venv/bin/pip install pyyaml   (PEP-668-safe;"
  info "     install into THAT interpreter — a yaml-capable system python won't help)"
fi

# ── 4. git hooks armed ──────────────────────────────────────────────────────
# -C anchors the (possibly relative) --git-path result to the repo root, so
# running self-check from a subdirectory doesn't misreport armed hooks.
HOOKS_DIR="$(git -C "$REPO_ROOT" rev-parse --git-path hooks 2>/dev/null)"
case "$HOOKS_DIR" in
  /*) : ;;
  *) HOOKS_DIR="$REPO_ROOT/$HOOKS_DIR" ;;
esac
ARMED=0
for tmpl in "$REPO_ROOT/sysop/scripts/hooks/"*; do
  [[ -f "$tmpl" ]] || continue
  name="$(basename "$tmpl")"
  if [[ -x "$HOOKS_DIR/$name" ]]; then
    ok "hook armed: $name"
    ARMED=$((ARMED + 1))
  else
    info "hook not armed: $name  (arm: bash sysop/scripts/install_hooks.sh)"
  fi
done
if [[ "$ARMED" -eq 0 ]] && [[ -d "$REPO_ROOT/sysop/scripts/hooks" ]]; then
  info "no hooks armed — enforcement runs only where you wire it (CI, or arm the hooks)"
fi

# ── 5. optional scanners (advisory) ─────────────────────────────────────────
if command -v semgrep >/dev/null 2>&1; then
  ok "semgrep on PATH (AST checks will run)"
else
  info "semgrep not on PATH — AST checks skip (brew install semgrep / pip install semgrep)"
fi
if command -v pip-audit >/dev/null 2>&1 \
   || { [[ -n "$PYYAML_PY" ]] && "$PYYAML_PY" -c 'import pip_audit' >/dev/null 2>&1; }; then
  ok "pip-audit available (dependency audit will run)"
else
  info "pip-audit not found — dependency audit skips (pip install pip-audit)"
fi
if command -v pyright >/dev/null 2>&1 || [[ -x "$REPO_ROOT/.venv/bin/pyright" ]] \
   || [[ -x "$REPO_ROOT/venv/bin/pyright" ]]; then
  ok "pyright available (Python typecheck will run)"
else
  info "pyright not found — Python typecheck skips (pip install pyright)"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
