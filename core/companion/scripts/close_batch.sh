#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# close_batch.sh — Mark merged review batches as closed in review_tasks.md.
#
# Usage:
#   bash sysop/scripts/close_batch.sh <N> [<N2> ...]     # Close specific batches
#   bash sysop/scripts/close_batch.sh --dry-run <N>       # Preview changes
#   bash sysop/scripts/close_batch.sh --force <N>         # Skip merge verification (for cherry-picked branches)
#
# For each batch:
#   1. Verifies the batch branch is merged into main (or already deleted)
#   2. Updates review_tasks.md: header → `Merged`, checkboxes → [x],
#      Statistics table → Merged, Grand Total done/open counts adjusted
#   3. Commits the changes
#
# Must be run on main after branches are merged.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

TASKS_FILE="${REPO_ROOT}/review_tasks.md"

if [[ ! -f "$TASKS_FILE" ]]; then
  echo "❌ review_tasks.md not found at ${TASKS_FILE}" >&2
  exit 1
fi

DRY_RUN=false
FORCE=false
BATCH_NUMS=()

# Parse arguments
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  elif [[ "$arg" == "--force" ]]; then
    FORCE=true
  elif [[ "$arg" =~ ^[0-9]+$ ]]; then
    BATCH_NUMS+=("$arg")
  else
    echo "❌ Unknown argument: ${arg}" >&2
    echo "Usage: close_batch.sh [--dry-run] [--force] <N> [<N2> ...]" >&2
    exit 1
  fi
done

if [[ ${#BATCH_NUMS[@]} -eq 0 ]]; then
  echo "❌ No batch numbers provided." >&2
  echo "Usage: close_batch.sh [--dry-run] [--force] <N> [<N2> ...]" >&2
  exit 1
fi

INDEX_SCRIPT="${REPO_ROOT}/sysop/scripts/review_index.py"

# ── Helper: find batch section boundaries ─────────────────────
# Sets BATCH_START, BATCH_END (line numbers) for a given batch number.
# Uses the shadow JSON index for reliable parsing; falls back to grep.
# Returns 1 if batch not found.
find_batch_range() {
  local batch_num="$1"

  # Try JSON index first
  local range_line=""
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    range_line=$(python3 "$INDEX_SCRIPT" --range "$batch_num" 2>/dev/null) || true
  fi

  if [[ -n "$range_line" ]]; then
    BATCH_START=$(echo "$range_line" | cut -f1)
    BATCH_END=$(echo "$range_line" | cut -f2)
    return 0
  fi

  # Fallback: grep-based range detection
  local total_lines
  total_lines=$(wc -l < "$TASKS_FILE" | tr -d ' ')

  BATCH_START=$(grep -n "^### Batch ${batch_num} " "$TASKS_FILE" | head -1 | cut -d: -f1)
  if [[ -z "$BATCH_START" ]]; then
    return 1
  fi

  local offset_end
  offset_end=$(tail -n +"$((BATCH_START + 1))" "$TASKS_FILE" | grep -n '^##' | head -1 | cut -d: -f1)
  if [[ -n "$offset_end" ]]; then
    BATCH_END=$((BATCH_START + offset_end - 1))
  else
    BATCH_END=$total_lines
  fi
}

# ── Helper: rebuild JSON index after Markdown mutation ─────────
rebuild_index() {
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    python3 "$INDEX_SCRIPT" --rebuild >/dev/null 2>&1 || true
  fi
}

# ── Process each batch ────────────────────────────────────────
CLOSED=()
SKIPPED=()
TOTAL_TASKS_CLOSED=0

for BATCH_NUM in "${BATCH_NUMS[@]}"; do
  echo "── Batch ${BATCH_NUM} ──"

  # Find batch header
  if ! find_batch_range "$BATCH_NUM"; then
    echo "   ⚠️  Not found in review_tasks.md. Skipping."
    SKIPPED+=("${BATCH_NUM}:not-found")
    continue
  fi

  # Extract current status from header line. Anchor to end-of-line so a
  # title containing backtick-quoted tokens (e.g. ``Batch 12 — fix `foo`
  # regression `In Progress` ``) yields the *trailing* status token, not
  # the first backtick block on the line.
  BATCH_HEADER=$(sed -n "${BATCH_START}p" "$TASKS_FILE")
  BATCH_STATUS=$(echo "$BATCH_HEADER" | grep -oE '`[A-Za-z ]+`[[:space:]]*$' | tr -d '`' | sed 's/[[:space:]]*$//')

  if [[ "$BATCH_STATUS" == "Merged" ]]; then
    echo "   ℹ️  Already Merged. Skipping."
    SKIPPED+=("${BATCH_NUM}:already-merged")
    continue
  fi

  # Allowlist BATCH_STATUS before interpolating into sed patterns. A
  # malformed status (e.g., containing the sed delimiter) would otherwise
  # break the substitution silently.
  case "$BATCH_STATUS" in
    Pending|"In Progress"|"Review Ready") ;;
    *)
      echo "   ⚠️  Unrecognized batch status '${BATCH_STATUS}'. Skipping."
      SKIPPED+=("${BATCH_NUM}:bad-status")
      continue
      ;;
  esac

  # Extract branch name from batch metadata. The trailing `|| true` is
  # load-bearing: a batch with no `**Branch:**` line makes `grep -o` exit 1,
  # and under `set -euo pipefail` that would abort the whole command
  # substitution (silently, rc 1, no stderr) — defeating the explicit
  # "No branch metadata found. Proceeding" fallback below. Siblings at the
  # task-count and Grand Total greps already carry this guard (ISSUE-0044).
  BRANCH_NAME=$(sed -n "${BATCH_START},${BATCH_END}p" "$TASKS_FILE" \
    | grep -o '\*\*Branch:\*\* `[^`]*`' \
    | sed 's/.*`\(.*\)`.*/\1/' || true)

  if [[ -n "$BRANCH_NAME" ]]; then
    # Verify branch is merged into main (skip with --force for cherry-picked branches)
    if git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}" 2>/dev/null; then
      if ! git merge-base --is-ancestor "$BRANCH_NAME" main 2>/dev/null; then
        if $FORCE; then
          echo "   ⚠️  Branch '${BRANCH_NAME}' not ancestor-merged (--force: accepting cherry-pick)."
        else
          echo "   ❌ Branch '${BRANCH_NAME}' is NOT merged into main. Skipping. (Use --force for cherry-picked branches.)"
          SKIPPED+=("${BATCH_NUM}:unmerged")
          continue
        fi
      else
        echo "   ✓ Branch '${BRANCH_NAME}' verified merged."
      fi
    elif git show-ref --verify --quiet "refs/remotes/origin/${BRANCH_NAME}" 2>/dev/null; then
      if ! git merge-base --is-ancestor "origin/${BRANCH_NAME}" main 2>/dev/null; then
        if $FORCE; then
          echo "   ⚠️  Remote branch '${BRANCH_NAME}' not ancestor-merged (--force: accepting cherry-pick)."
        else
          echo "   ❌ Remote branch '${BRANCH_NAME}' is NOT merged into main. Skipping. (Use --force for cherry-picked branches.)"
          SKIPPED+=("${BATCH_NUM}:unmerged")
          continue
        fi
      else
        echo "   ✓ Remote branch '${BRANCH_NAME}' verified merged."
      fi
    else
      echo "   ✓ Branch '${BRANCH_NAME}' already deleted (assumed merged)."
    fi
  else
    echo "   ⚠️  No branch metadata found. Proceeding based on batch status."
  fi

  # Count tasks that will be closed (for Grand Total adjustment)
  TASKS_IN_BATCH=$(sed -n "${BATCH_START},${BATCH_END}p" "$TASKS_FILE" \
    | grep -cE '^\- \[ \]|^\- \[/\]' || true)

  if $DRY_RUN; then
    echo "   [dry-run] Would update:"
    echo "     - Batch header: '${BATCH_STATUS}' → 'Merged'"
    echo "     - Task checkboxes: ${TASKS_IN_BATCH} tasks → [x]"
    echo "     - Statistics table row: → Merged"
    TOTAL_TASKS_CLOSED=$((TOTAL_TASKS_CLOSED + TASKS_IN_BATCH))
    CLOSED+=("$BATCH_NUM")
    continue
  fi

  # Atomic rewrite: apply all sed mutations to a single tempfile, then mv into
  # place. CLAUDE.md § Data integrity requires `<path>.tmp` + atomic move so a
  # mid-flow interrupt cannot leave review_tasks.md half-edited (downstream
  # readers — review_index.py, /next-task — treat the file as canonical).
  TMP_FILE="${TASKS_FILE}.tmp"
  trap 'rm -f "$TMP_FILE"' EXIT
  sed -e "${BATCH_START}s#\`${BATCH_STATUS}\`#\`Merged\`#" \
      -e "${BATCH_START},${BATCH_END}s/^- \[ \]/- [x]/" \
      -e "${BATCH_START},${BATCH_END}s#^- \[/\]#- [x]#" \
      -e "/Batch ${BATCH_NUM})/s#| ${BATCH_STATUS} |#| Merged |#" \
      -e "/Batch ${BATCH_NUM})/s#| ${BATCH_STATUS}\$#| Merged#" \
      "$TASKS_FILE" > "$TMP_FILE"
  mv -- "$TMP_FILE" "$TASKS_FILE"
  trap - EXIT

  TOTAL_TASKS_CLOSED=$((TOTAL_TASKS_CLOSED + TASKS_IN_BATCH))
  echo "   ✅ Marked as Merged (${TASKS_IN_BATCH} tasks closed)."
  CLOSED+=("$BATCH_NUM")
done

# ── Update Grand Total done/open counts ───────────────────────
# Append `|| true` to each grep so a `review_tasks.md` without a `Grand Total`
# line (some consumers don't author a `## Statistics` block) doesn't abort the
# script under `set -o pipefail`. Existing inner `if [[ -n ... ]]` already
# short-circuits cleanly on empty captures. (BeanRider ISSUE-0044.)
if [[ $TOTAL_TASKS_CLOSED -gt 0 ]]; then
  CURRENT_DONE=$(grep 'Grand Total' "$TASKS_FILE" 2>/dev/null | sed -En 's/.*— ([0-9]+) done.*/\1/p' || true)
  CURRENT_OPEN=$(grep 'Grand Total' "$TASKS_FILE" 2>/dev/null | sed -En 's/.*, ([0-9]+) open.*/\1/p' || true)

  if [[ -n "$CURRENT_DONE" && -n "$CURRENT_OPEN" ]]; then
    NEW_DONE=$((CURRENT_DONE + TOTAL_TASKS_CLOSED))
    NEW_OPEN=$((CURRENT_OPEN - TOTAL_TASKS_CLOSED))
    [[ $NEW_OPEN -lt 0 ]] && NEW_OPEN=0

    if $DRY_RUN; then
      echo ""
      echo "── Grand Total ──"
      echo "   [dry-run] Would update: ${CURRENT_DONE} done → ${NEW_DONE} done, ${CURRENT_OPEN} open → ${NEW_OPEN} open"
    else
      # Atomic rewrite per CLAUDE.md § Data integrity.
      TMP_FILE="${TASKS_FILE}.tmp"
      trap 'rm -f "$TMP_FILE"' EXIT
      sed "s/${CURRENT_DONE} done, ${CURRENT_OPEN} open/${NEW_DONE} done, ${NEW_OPEN} open/" "$TASKS_FILE" > "$TMP_FILE"
      mv -- "$TMP_FILE" "$TASKS_FILE"
      trap - EXIT
    fi
  fi
fi

# ── Commit ────────────────────────────────────────────────────
if ! $DRY_RUN && [[ ${#CLOSED[@]} -gt 0 ]]; then
  # Build comma-separated list without mutating IFS.
  BATCH_LIST=""
  for n in "${CLOSED[@]}"; do
    if [[ -z "$BATCH_LIST" ]]; then
      BATCH_LIST="$n"
    else
      BATCH_LIST="${BATCH_LIST}, ${n}"
    fi
  done
  git add review_tasks.md
  # Wrap the commit in explicit failure handling. `set -euo pipefail` would
  # otherwise abort the script silently mid-flow on hook failure (e.g., a
  # pre-commit hook missing a venv-installed CLI), and the caller (typically
  # /review-close Step 4b) treats the script's exit as authoritative — a silent
  # mid-flow abort leaves review_tasks.md modified-but-uncommitted and the
  # workflow proceeds to consolidate docs without the close-batch commit ever
  # landing. (BeanRider ISSUE-0015, Sysop Phase 33.)
  if ! git commit -m "docs: close Batch ${BATCH_LIST}"; then
    echo "" >&2
    echo "❌ git commit failed — review_tasks.md still has the close-batch edits staged but uncommitted." >&2
    echo "   Inspect git status and the pre-commit-hook output above; common causes:" >&2
    echo "     • pre-commit hook missing a venv-installed CLI (re-run with PATH=.venv/bin:\$PATH)" >&2
    echo "     • commit signing failure" >&2
    echo "   Re-run \`bash sysop/scripts/close_batch.sh ${CLOSED[*]}\` after fixing." >&2
    exit 1
  fi
  echo ""
  echo "✅ Committed: docs: close Batch ${BATCH_LIST}"

  # Rebuild JSON index after Markdown mutation
  rebuild_index
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "── Summary ──"
if [[ ${#CLOSED[@]} -gt 0 ]]; then
  echo "   Closed: ${CLOSED[*]}"
fi
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo "   Skipped: ${SKIPPED[*]}"
fi
if $DRY_RUN; then
  echo "   (dry-run mode — no changes made)"
fi

# ── Terminal one-liner (BeanRider ISSUE-0039) ────────────────
# Pre-commit hooks that print to stdout (e.g., a full pytest summary) can push
# the commit-success banner above past the operator's `tail -N` window in
# /review-close Step 4b. This line is the LAST thing written: its *presence*
# proves the script ran to completion without a silent mid-flow abort under
# `set -euo pipefail`, and the commit-present count proves the close-batch
# commit actually landed (vs. the banner printing but the commit being reverted
# by a hook). Operators see this whether they pipe through `tail` or not.
CLOSE_BATCH_PRESENT=0
if [[ ${#CLOSED[@]} -gt 0 ]] && ! $DRY_RUN; then
  CLOSE_BATCH_PRESENT=$(git log -1 --pretty=%s 2>/dev/null | grep -c '^docs: close Batch ' || true)
fi
echo "── close_batch.sh completed — close-batch commit present: ${CLOSE_BATCH_PRESENT}"
