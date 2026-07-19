#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# cleanup_worktrees.sh — List and clean up git worktrees.
#
# Usage:
#   bash sysop/scripts/cleanup_worktrees.sh            # List all worktrees with status
#   bash sysop/scripts/cleanup_worktrees.sh --clean    # Remove merged/stale worktrees
#   bash sysop/scripts/cleanup_worktrees.sh --force    # Remove ALL non-main worktrees
#
# Classification:
#   MAIN   — primary worktree (never touched)
#   MERGED — branch is ancestor of main (safe to remove)
#   ACTIVE — has uncommitted changes (skipped by --clean)
#   STALE  — directory missing (pruned automatically)
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

ACTION="${1:-list}"

# ── Prune stale worktrees first ───────────────────────────────
# Surface stderr so prune failures (corrupt worktree DB, permission errors)
# are visible — silently no-oping leaks STALE entries into the classifier.
git worktree prune

# ── Parse worktree list ───────────────────────────────────────
# git worktree list --porcelain gives structured output:
#   worktree /path
#   HEAD <sha>
#   branch refs/heads/<name>
#   (blank line)

classify_worktree() {
  local wt_path="$1"
  local wt_branch="$2"
  local main_branch="main"

  # Main worktree
  if [[ "$wt_path" == "$REPO_ROOT" ]]; then
    echo "MAIN"
    return
  fi

  # Directory missing (shouldn't happen after prune, but be safe)
  if [[ ! -d "$wt_path" ]]; then
    echo "STALE"
    return
  fi

  # Worktree directory exists but its .git pointer is corrupt/missing — classify
  # as STALE so `--clean` can reclaim it instead of leaking it as ACTIVE.
  if ! git -C "$wt_path" rev-parse --git-dir >/dev/null 2>&1; then
    echo "STALE"
    return
  fi

  # Has uncommitted changes? Inverted check (fall through on clean) reads
  # cleaner than `if clean; then : else ACTIVE; fi`.
  if ! git -C "$wt_path" diff --quiet 2>/dev/null || ! git -C "$wt_path" diff --cached --quiet 2>/dev/null; then
    echo "ACTIVE"
    return
  fi

  # Has untracked files? (lightweight check)
  if [[ -n "$(git -C "$wt_path" ls-files --others --exclude-standard 2>/dev/null | head -1)" ]]; then
    echo "ACTIVE"
    return
  fi

  # Branch merged into main?
  if [[ -n "$wt_branch" ]] && git merge-base --is-ancestor "$wt_branch" "$main_branch" 2>/dev/null; then
    echo "MERGED"
    return
  fi

  echo "ACTIVE"
}

# ── Collect worktrees ─────────────────────────────────────────
declare -a WT_PATHS=()
declare -a WT_BRANCHES=()
declare -a WT_CLASSES=()

current_path=""
current_branch=""

while IFS= read -r line; do
  if [[ "$line" =~ ^worktree[[:space:]]+(.*) ]]; then
    current_path="${BASH_REMATCH[1]}"
  elif [[ "$line" =~ ^branch[[:space:]]+refs/heads/(.*) ]]; then
    current_branch="${BASH_REMATCH[1]}"
  elif [[ -z "$line" && -n "$current_path" ]]; then
    classification=$(classify_worktree "$current_path" "$current_branch")
    WT_PATHS+=("$current_path")
    WT_BRANCHES+=("$current_branch")
    WT_CLASSES+=("$classification")
    current_path=""
    current_branch=""
  fi
done < <(git worktree list --porcelain; echo "")

# ── Mode: list (default) ─────────────────────────────────────
if [[ "$ACTION" == "list" ]]; then
  echo "┌──────────────────────────────────────────────────────────────────┐"
  echo "│  Git Worktrees                                                   │"
  echo "├────────┬────────────────────────────┬────────────────────────────┤"
  printf "│ %-6s │ %-26s │ %-26s │\n" "Status" "Branch" "Path"
  echo "├────────┼────────────────────────────┼────────────────────────────┤"

  for i in "${!WT_PATHS[@]}"; do
    wt_path="${WT_PATHS[$i]}"
    wt_branch="${WT_BRANCHES[$i]:-"(detached)"}"
    wt_class="${WT_CLASSES[$i]}"

    case "$wt_class" in
      MAIN)   icon="🏠" ;;
      MERGED) icon="✅" ;;
      ACTIVE) icon="🔵" ;;
      STALE)  icon="💀" ;;
      *)      icon="❓" ;;
    esac

    # Shorten path for display
    display_path="${wt_path/$HOME/~}"
    printf "│ %s%-5s │ %-26s │ %-26s │\n" "$icon" "$wt_class" "${wt_branch:0:26}" "${display_path: -26}"
  done

  echo "└────────┴────────────────────────────┴────────────────────────────┘"
  echo ""
  echo "Legend: 🏠 MAIN (never removed) · ✅ MERGED (safe to clean) · 🔵 ACTIVE (has changes) · 💀 STALE (pruned)"
  exit 0
fi

# ── Mode: --clean ─────────────────────────────────────────────
if [[ "$ACTION" == "--clean" ]]; then
  REMOVED=0
  SKIPPED=0
  FAILED=0

  for i in "${!WT_PATHS[@]}"; do
    wt_path="${WT_PATHS[$i]}"
    wt_branch="${WT_BRANCHES[$i]:-""}"
    wt_class="${WT_CLASSES[$i]}"

    if [[ "$wt_class" == "MAIN" ]]; then
      continue
    fi

    if [[ "$wt_class" == "ACTIVE" ]]; then
      echo "⏭️  Skipping ACTIVE worktree: ${wt_path} (${wt_branch})"
      SKIPPED=$((SKIPPED + 1))
      continue
    fi

    if [[ "$wt_class" == "MERGED" || "$wt_class" == "STALE" ]]; then
      echo "🗑️  Removing ${wt_class} worktree: ${wt_path} (${wt_branch})"
      # Use plain (non-force) remove so untracked work or submodule dirty state
      # that slipped past the MERGED classification blocks the destructive op.
      # Callers wanting to override must invoke the script with `--force`
      # explicitly (which routes through the --force branch below) per
      # CLAUDE.md "do not destructively delete user work".
      if git worktree remove "$wt_path"; then
        REMOVED=$((REMOVED + 1))
      else
        echo "   ⚠️  Failed to remove worktree at ${wt_path} (re-run with --force to override)"
        FAILED=$((FAILED + 1))
        continue
      fi

      # Delete merged branch (safe -d, not -D)
      if [[ -n "$wt_branch" && "$wt_branch" != "main" ]]; then
        git branch -d "$wt_branch" 2>/dev/null && \
          echo "   🌿 Deleted merged branch: ${wt_branch}" || \
          echo "   ℹ️  Branch '${wt_branch}' not deleted (not fully merged or still in use)"
      fi
    fi
  done

  git worktree prune
  echo ""
  echo "Done. Removed ${REMOVED} worktree(s), skipped ${SKIPPED} active, ${FAILED} failed."
  [[ $FAILED -gt 0 ]] && exit 1
  exit 0
fi

# ── Mode: --force ─────────────────────────────────────────────
if [[ "$ACTION" == "--force" ]]; then
  echo "⚠️  Force-removing ALL non-main worktrees..."
  echo ""
  REMOVED=0
  FAILED=0

  for i in "${!WT_PATHS[@]}"; do
    wt_path="${WT_PATHS[$i]}"
    wt_branch="${WT_BRANCHES[$i]:-""}"
    wt_class="${WT_CLASSES[$i]}"

    if [[ "$wt_class" == "MAIN" ]]; then
      continue
    fi

    echo "🗑️  Removing: ${wt_path} (${wt_branch})"
    if git worktree remove --force "$wt_path"; then
      REMOVED=$((REMOVED + 1))
    else
      echo "   ⚠️  Failed to remove worktree at ${wt_path}"
      FAILED=$((FAILED + 1))
      continue
    fi

    if [[ -n "$wt_branch" && "$wt_branch" != "main" ]]; then
      git branch -d "$wt_branch" 2>/dev/null && \
        echo "   🌿 Deleted branch: ${wt_branch}" || \
        echo "   ℹ️  Branch '${wt_branch}' not deleted (not fully merged)"
    fi
  done

  git worktree prune
  echo ""
  echo "Done. Force-removed ${REMOVED} worktree(s), ${FAILED} failed."
  [[ $FAILED -gt 0 ]] && exit 1
  exit 0
fi

echo "❌ Unknown action: ${ACTION}" >&2
echo "Usage: cleanup_worktrees.sh [--clean | --force]" >&2
exit 1
