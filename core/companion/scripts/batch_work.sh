#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# batch_work.sh — Create an isolated worktree for a review_tasks.md batch.
#
# Usage:
#   bash scripts/batch_work.sh <BATCH_NUMBER>    # Create worktree for batch
#   bash scripts/batch_work.sh --list            # Show pending/in-progress batches
#   bash scripts/batch_work.sh --list-all        # Show all batches including complete
#
# Creates a git worktree at ../<project basename>-batch-<N>/ with the
# branch specified in review_tasks.md. Override the prefix by exporting
# WORKTREE_PREFIX (e.g. WORKTREE_PREFIX=foo → ../foo-batch-<N>).
# Installs git hooks and prints next-step instructions.
#
# Designed for parallel agent sessions — each batch gets its own
# isolated directory so concurrent work never conflicts.
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

# ── Helper: parse all batches ─────────────────────────────────
# Uses the shadow JSON index (scripts/review_index.py) for reliable parsing.
# Falls back to inline bash regex if Python is unavailable.
# Output: tab-separated lines: NUMBER<tab>TITLE<tab>STATUS<tab>BRANCH<tab>SCOPE<tab>VERIFY
INDEX_SCRIPT="${REPO_ROOT}/scripts/review_index.py"

parse_batches() {
  # Try the JSON index first (auto-rebuilds if stale)
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    python3 "$INDEX_SCRIPT" --list 2>/dev/null && return 0
  fi

  # Fallback: inline bash regex parser
  _parse_batches_fallback
}

_parse_batches_fallback() {
  local num="" title="" status="" branch="" scope="" verify=""
  local in_batch=false

  while IFS= read -r line; do
    if [[ "$line" =~ ^###[[:space:]]+Batch[[:space:]]+([0-9]+)[[:space:]]+—[[:space:]]+(.+)[[:space:]]+\`([A-Za-z ]+)\` ]]; then
      if $in_batch && [[ -n "$num" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$num" "$title" "$status" "$branch" "$scope" "$verify"
      fi
      num="${BASH_REMATCH[1]}"
      title="${BASH_REMATCH[2]}"
      status="${BASH_REMATCH[3]}"
      branch="" scope="" verify=""
      in_batch=true
      continue
    fi

    if $in_batch; then
      if [[ "$line" =~ ^\>[[:space:]]+\*\*Branch:\*\*[[:space:]]+\`([^\`]+)\` ]]; then
        branch="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ ^\>[[:space:]]+\*\*Scope:\*\*[[:space:]]+(.*) ]]; then
        scope="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ ^\>[[:space:]]+\*\*Verify:\*\*[[:space:]]+(.*) ]]; then
        verify="${BASH_REMATCH[1]}"
      fi
    fi
  done < "$TASKS_FILE"

  if $in_batch && [[ -n "$num" ]]; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$num" "$title" "$status" "$branch" "$scope" "$verify"
  fi
}

# ── Helper: rebuild JSON index after Markdown mutation ─────────
rebuild_index() {
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    python3 "$INDEX_SCRIPT" --rebuild >/dev/null 2>&1 || true
  fi
}

# ── Mode: --list / --list-all ─────────────────────────────────
if [[ "${1:-}" == "--list" || "${1:-}" == "--list-all" ]]; then
  SHOW_ALL=false
  [[ "${1:-}" == "--list-all" ]] && SHOW_ALL=true

  echo "┌─────────────────────────────────────────────────────────────┐"
  echo "│  Review Task Batches                                        │"
  echo "├──────┬──────────────────────────────────────┬───────────────┤"
  printf "│ %-4s │ %-36s │ %-13s │\n" "#" "Title" "Status"
  echo "├──────┼──────────────────────────────────────┼───────────────┤"

  FOUND=0
  while IFS=$'\t' read -r num title status branch scope verify; do
    # Status emoji
    case "$status" in
      Pending)       icon="⬜" ;;
      "In Progress") icon="🔵" ;;
      Complete|Merged) icon="✅" ;;
      *)             icon="❓" ;;
    esac

    # In --list mode, skip completed/merged
    if ! $SHOW_ALL && [[ "$status" == "Complete" || "$status" == "Merged" ]]; then
      continue
    fi

    printf "│ %s%-3s │ %-36s │ %-12s │\n" "$icon" "$num" "${title:0:36}" "$status"
    FOUND=$((FOUND + 1))
  done < <(parse_batches)

  echo "└──────┴──────────────────────────────────────┴───────────────┘"

  if [[ $FOUND -eq 0 ]]; then
    echo ""
    echo "No batches found. Use --list-all to include completed batches."
  fi
  exit 0
fi

# ── Helper: claim a Pending batch on main ─────────────────────
# Marks the batch as In Progress in review_tasks.md and commits on main.
# Skips gracefully if not on main, tree is dirty, or batch is already claimed.
claim_batch() {
  local batch_num="$1"
  local batch_status="$2"

  # Only claim Pending batches
  if [[ "$batch_status" != "Pending" ]]; then
    return 0
  fi

  # Must be on main
  local current_branch
  current_branch="$(git symbolic-ref --short HEAD 2>/dev/null)" || true
  if [[ "$current_branch" != "main" ]]; then
    echo "⚠️  Not on main (on '${current_branch}'). Skipping batch claim." >&2
    echo "   Claim the batch manually by updating review_tasks.md on main." >&2
    return 0
  fi

  # Working tree must be clean for review_tasks.md
  if ! git diff --quiet -- review_tasks.md 2>/dev/null || \
     ! git diff --cached --quiet -- review_tasks.md 2>/dev/null; then
    echo "⚠️  review_tasks.md has uncommitted changes. Skipping batch claim." >&2
    return 0
  fi

  # Pull latest main
  echo "📥 Pulling latest main..."
  git pull --ff-only origin main 2>/dev/null || {
    echo "⚠️  git pull --ff-only failed. Skipping batch claim." >&2
    return 0
  }

  # Find batch section boundaries (prefer JSON index, fallback to grep)
  local batch_start batch_end total_lines
  local range_line
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    range_line=$(python3 "$INDEX_SCRIPT" --range "$batch_num" 2>/dev/null) || true
  fi

  if [[ -n "${range_line:-}" ]]; then
    batch_start=$(echo "$range_line" | cut -f1)
    batch_end=$(echo "$range_line" | cut -f2)
  else
    # Fallback: grep-based range detection
    total_lines=$(wc -l < "$TASKS_FILE" | tr -d ' ')
    batch_start=$(grep -n "^### Batch ${batch_num} " "$TASKS_FILE" | head -1 | cut -d: -f1)

    if [[ -z "$batch_start" ]]; then
      echo "⚠️  Could not find Batch ${batch_num} header. Skipping batch claim." >&2
      return 0
    fi

    # Trailing `|| true`: when this batch is the file's last section (no
    # following `^##` line) grep exits 1, which under `set -euo pipefail`
    # would abort this directly-called function (set -e is active here, unlike
    # close_batch's find_batch_range which runs under `if !`). Fall through to
    # the total-lines default below instead. (Same class as the close_batch
    # ISSUE-0044 grep guards.)
    batch_end=$(tail -n +"$((batch_start + 1))" "$TASKS_FILE" | grep -n '^##' | head -1 | cut -d: -f1 || true)
    if [[ -n "$batch_end" ]]; then
      batch_end=$((batch_start + batch_end - 1))
    else
      batch_end=$total_lines
    fi
  fi

  if [[ -z "$batch_start" ]]; then
    echo "⚠️  Could not find Batch ${batch_num} header. Skipping batch claim." >&2
    return 0
  fi

  # Atomic rewrite: apply all sed mutations in one pass to a tempfile, then mv
  # into place. CLAUDE.md § Data integrity requires `<path>.tmp` + atomic move
  # so an interrupt mid-flow cannot leave review_tasks.md half-edited.
  local tmp_file="${TASKS_FILE}.tmp"
  trap 'rm -f "$tmp_file"' RETURN
  sed -e "${batch_start}s/\`Pending\`/\`In Progress\`/" \
      -e "${batch_start},${batch_end}s/^- \[ \]/- [\/]/" \
      -e "/Batch ${batch_num})/s/| Pending |/| In Progress |/" \
      "$TASKS_FILE" > "$tmp_file"
  mv -- "$tmp_file" "$TASKS_FILE"
  trap - RETURN

  # Commit the claim
  git add review_tasks.md
  git commit -m "docs: claim Batch ${batch_num}"
  echo "✅ Claimed Batch ${batch_num} on main (marked In Progress)."

  # Rebuild JSON index after Markdown mutation
  rebuild_index

  # Update caller's status variable
  BATCH_STATUS="In Progress"
}

# ── Mode: create worktree for batch ───────────────────────────
BATCH_NUM="${1:?Usage: batch_work.sh <BATCH_NUMBER> | --list | --list-all}"

# Validate it's a number
if ! [[ "$BATCH_NUM" =~ ^[0-9]+$ ]]; then
  echo "❌ Batch number must be a positive integer, got: ${BATCH_NUM}" >&2
  exit 1
fi

# Find the batch in review_tasks.md
BATCH_LINE=""
while IFS=$'\t' read -r num title status branch scope verify; do
  if [[ "$num" == "$BATCH_NUM" ]]; then
    BATCH_LINE="found"
    BATCH_TITLE="$title"
    BATCH_STATUS="$status"
    BATCH_BRANCH="$branch"
    BATCH_SCOPE="$scope"
    BATCH_VERIFY="$verify"
    break
  fi
done < <(parse_batches)

if [[ -z "$BATCH_LINE" ]]; then
  echo "❌ Batch ${BATCH_NUM} not found in review_tasks.md" >&2
  echo "   Run: bash scripts/batch_work.sh --list-all" >&2
  exit 1
fi

if [[ -z "$BATCH_BRANCH" ]]; then
  echo "❌ Batch ${BATCH_NUM} has no Branch: metadata in review_tasks.md" >&2
  exit 1
fi

if [[ "$BATCH_STATUS" == "Complete" || "$BATCH_STATUS" == "Merged" ]]; then
  echo "⚠️  Batch ${BATCH_NUM} is already marked as '${BATCH_STATUS}'."
  echo "   Proceeding anyway (you may be doing follow-up work)."
  echo ""
fi

# ── Claim batch on main (Pending → In Progress) ──────────────
claim_batch "$BATCH_NUM" "$BATCH_STATUS"

WORKTREE_DIR="${REPO_ROOT}/../${WORKTREE_PREFIX:-$(basename "$REPO_ROOT")}-batch-${BATCH_NUM}"

# ── Create branch if needed (check remote too) ───────────────
if git show-ref --verify --quiet "refs/heads/${BATCH_BRANCH}" 2>/dev/null; then
  echo "ℹ️  Branch '${BATCH_BRANCH}' already exists locally."
elif git show-ref --verify --quiet "refs/remotes/origin/${BATCH_BRANCH}" 2>/dev/null; then
  git branch "$BATCH_BRANCH" "origin/${BATCH_BRANCH}"
  echo "✅ Created local branch '${BATCH_BRANCH}' tracking remote."
else
  git branch "$BATCH_BRANCH" main
  echo "✅ Created branch '${BATCH_BRANCH}' from main."
fi

# ── Create worktree ───────────────────────────────────────────
if [[ -d "$WORKTREE_DIR" ]]; then
  echo "ℹ️  Worktree directory already exists: ${WORKTREE_DIR}"
else
  git worktree add "$WORKTREE_DIR" "$BATCH_BRANCH"
  echo "✅ Created worktree at ${WORKTREE_DIR}"
fi

# ── Install hooks (non-fatal) ────────────────────────────────
if [[ -f "${REPO_ROOT}/scripts/install_hooks.sh" ]]; then
  # Surface stderr so a real install failure (missing .git/hooks, permission
  # error, hook source corruption) is visible — symmetric with claim_task.sh.
  (cd "$WORKTREE_DIR" && bash "${REPO_ROOT}/scripts/install_hooks.sh") || \
    echo "⚠️  Hook installation failed (non-fatal)."
fi

# ── Print summary ────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│  Batch ${BATCH_NUM} — ${BATCH_TITLE}"
echo "├─────────────────────────────────────────────────────────────┤"
echo "│  Path:   ${WORKTREE_DIR}"
echo "│  Branch: ${BATCH_BRANCH}"
echo "│  Status: ${BATCH_STATUS}"
if [[ -n "$BATCH_SCOPE" ]]; then
echo "│  Scope:  ${BATCH_SCOPE}"
fi
if [[ -n "$BATCH_VERIFY" ]]; then
echo "│  Verify: ${BATCH_VERIFY}"
fi
echo "└─────────────────────────────────────────────────────────────┘"
echo ""
echo "📝 Next steps:"
echo "   1. cd ${WORKTREE_DIR}"
echo "   2. Review the batch tasks in review_tasks.md"
echo "   3. Start working!"
echo ""
echo "   When done: git push -u origin ${BATCH_BRANCH}"
echo "   Cleanup:   bash scripts/cleanup_worktrees.sh --clean"
