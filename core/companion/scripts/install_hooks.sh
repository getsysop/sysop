#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# install_hooks.sh — Copy tracked hook scripts into .git/hooks/
#
# Usage:
#   bash scripts/install_hooks.sh
#
# Run this after cloning or creating a worktree to activate
# the pre-merge-commit gate that blocks untested merges to main.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

HOOKS_SRC="${REPO_ROOT}/scripts/hooks"
HOOKS_DST="$(git rev-parse --git-common-dir)/hooks"

if [[ ! -d "$HOOKS_SRC" ]]; then
  echo "❌ No hooks found in scripts/hooks/." >&2
  exit 1
fi

INSTALLED=0
BACKED_UP=()
# Explicit allowlist: only these tracked filenames are ever copied into
# .git/hooks/ so stray files (.DS_Store, *.swp, README.md, accidentally
# pasted hook files) cannot get installed and executed on git events.
for BASENAME in pre-commit pre-merge-commit pre-push; do
  HOOK="${HOOKS_SRC}/${BASENAME}"
  [[ -f "$HOOK" ]] || continue
  DST="${HOOKS_DST}/${BASENAME}"

  # Back up any pre-existing hook that differs from the tracked version
  # so user customizations are not silently clobbered.
  if [[ -f "$DST" ]] && ! cmp -s "$HOOK" "$DST"; then
    TS=$(date -u +"%Y%m%dT%H%M%SZ")
    BACKUP="${DST}.bak.${TS}"
    cp "$DST" "$BACKUP"
    BACKED_UP+=("${BASENAME} → $(basename "$BACKUP")")
  fi

  # Atomic install: write to .tmp and mv into place so a partial copy
  # never leaves a half-written executable. See CLAUDE.md § Atomic file rewrites.
  TMP="${DST}.tmp"
  cp "$HOOK" "$TMP"
  chmod +x "$TMP"
  mv "$TMP" "$DST"
  echo "✅ Installed: ${BASENAME}"
  INSTALLED=$((INSTALLED + 1))
done

echo ""
echo "Done. ${INSTALLED} hook(s) installed to ${HOOKS_DST}/"
if [[ ${#BACKED_UP[@]} -gt 0 ]]; then
  echo ""
  echo "⚠️  Backed up pre-existing customized hooks:"
  for BACKUP_NOTE in "${BACKED_UP[@]}"; do
    echo "   • ${BACKUP_NOTE}"
  done
fi
