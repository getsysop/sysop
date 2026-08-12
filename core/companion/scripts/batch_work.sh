#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# batch_work.sh — Create an isolated worktree for a review_tasks.md batch.
#
# Usage:
#   bash sysop/scripts/batch_work.sh <BATCH_NUMBER>    # Create worktree for batch
#   bash sysop/scripts/batch_work.sh --list            # Show pending/in-progress batches
#   bash sysop/scripts/batch_work.sh --list-all        # Show all batches including complete
#   bash sysop/scripts/batch_work.sh --release [--force] <BATCH_NUMBER>   # Un-claim
#
# A batch number may also be given in claim-ID form (`BATCH-7` == `7`) so a
# caller holding a claim ID does not have to strip the prefix.
#
# Creates a git worktree at ../<project basename>-batch-<N>/ with the
# branch specified in review_tasks.md. Override the prefix by exporting
# WORKTREE_PREFIX (e.g. WORKTREE_PREFIX=foo → ../foo-batch-<N>).
# Prints next-step instructions.
#
# Designed for parallel agent sessions — each batch gets its own
# isolated directory so concurrent work never conflicts.
#
# Batch locks (Phase 156):
#   A claim also writes `sysop/runtime/locks/BATCH-<N>.lock` under the MAIN
#   repo, the same file shape and the same location `claim_task.sh --lock`
#   uses for a roadmap task. Four readers were already written against a lock
#   that nothing had ever produced: `next_task.py`'s in-flight batch filter,
#   `sitrep_survey.py`'s batch classifier (`has_lock`) and its orphan-worktree
#   probe, and `scope_overlap.py`'s in-flight set. `--release` and
#   `close_batch.sh` remove it — a write with no removal path would make every
#   batch unclaimable after its first claim.
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
# Uses the shadow JSON index (sysop/scripts/review_index.py) for reliable parsing.
# Falls back to inline bash regex if Python is unavailable.
# Output: tab-separated lines: NUMBER<tab>TITLE<tab>STATUS<tab>BRANCH<tab>SCOPE<tab>VERIFY
INDEX_SCRIPT="${REPO_ROOT}/sysop/scripts/review_index.py"

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
    # `[^\`]+`, not `[A-Za-z ]+`: a status carrying a hyphen or a digit is a
    # thing a consumer can write, and a reader that cannot see it does not
    # prevent it — it just makes the batch invisible. `--release <N>` answered
    # "not found" for a batch plainly in the file. What the value MEANS is
    # decided by the status ladder on the claim path, which is where an
    # undeclared value gets refused by name.
    if [[ "$line" =~ ^###[[:space:]]+Batch[[:space:]]+([0-9]+)[[:space:]]+—[[:space:]]+(.+)[[:space:]]+\`([^\`]+)\` ]]; then
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

    # A `### Batch <N>` line the pattern above could NOT parse still ends the
    # open batch. Without this it fell through as ordinary content and the
    # orphan's own `> **Branch:**`/`Scope:`/`Verify:` lines overwrote the
    # PREVIOUS batch's — so `batch_work.sh 7` built a worktree named
    # `…-batch-7` on branch `review/batch-8`, with batch 8's scope and batch 8's
    # verify command. Measured in this parser and in the Python index alike, so
    # the shadow index was never a safety net for it.
    #
    # Widening the status charset above shrinks this class but cannot close it:
    # a header with no status token at all, or a hyphen where the em-dash
    # belongs, still fails to parse. Those are authoring slips, not statuses —
    # they leave the batch invisible, which is honest, but they must not
    # corrupt a batch that IS visible.
    if [[ "$line" =~ ^###[[:space:]]+Batch[[:space:]]+[0-9]+ ]]; then
      if $in_batch && [[ -n "$num" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$num" "$title" "$status" "$branch" "$scope" "$verify"
      fi
      num="" title="" status="" branch="" scope="" verify=""
      in_batch=false
      echo "⚠️  Unparseable batch header, skipped: ${line}" >&2
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

# ── Helper: normalise a claim-ID-shaped batch argument ────────
# `BATCH-7`, `batch-7` and `7` all name the same batch. Callers hold whichever
# form their own step produced, and a "must be a positive integer" rejection of
# the canonical claim ID is a bad error for a correct invocation.
normalize_batch_arg() {
  local raw="$1"
  # Anchored to the literal BATCH prefix on purpose: a looser `^[A-Za-z]+-`
  # would make `TECH-7` claim batch 7, which is the claim-kind confusion this
  # phase exists to remove.
  if [[ "$raw" =~ ^[Bb][Aa][Tt][Cc][Hh]-([0-9]+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    printf '%s\n' "$raw"
  fi
}

# ── Helper: resolve the canonical sysop/runtime/locks/ ────────
# Locks always live under the MAIN repo (Phase 32), so every worktree and every
# cwd sees one lock state. `git rev-parse --git-common-dir` returns the `.git`
# DIRECTORY — the repo root is its dirname — and from a main checkout it
# answers with the relative `.git`, which has to be absolutised first.
#
# Kept inline rather than sourced from a shared helper. The same resolution is
# duplicated on purpose in claim_task.sh, next_task.py, validate_tasks.py and
# scope_overlap.py, each carrying a comment naming the others: these files are
# delivered independently, and a claim that fails because a sourced helper was
# missing from a partial install is worse than the duplication.
resolve_main_root() {
  local common_dir
  common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$common_dir" ]] || return 1
  if [[ "$common_dir" = /* ]]; then
    dirname "$common_dir"
  else
    dirname "$(cd "$common_dir" && pwd)"
  fi
}

resolve_locks_dir() {
  local main_root
  main_root="$(resolve_main_root)" || return 1
  printf '%s/sysop/runtime/locks\n' "$main_root"
}

# ── Helper: locate the worktree holding a branch ──────────────
# Asks git rather than recomputing the WORKTREE_PREFIX-dependent path the claim
# used — WORKTREE_PREFIX may differ between the claiming shell and this one.
find_worktree_for_branch() {
  local branch="$1" wt="" line
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) wt="${line#worktree }" ;;
      "branch refs/heads/"*)
        if [[ "${line#branch refs/heads/}" == "$branch" ]]; then
          printf '%s\n' "$wt"
          return 0
        fi
        ;;
    esac
  done < <(git worktree list --porcelain 2>/dev/null)
  return 1
}

# ── Helper: write the batch lock ──────────────────────────────
# Mirrors the file `claim_task.sh` writes for a roadmap task, field for field,
# so every existing reader parses it without a special case.
#
# Idempotent by design: an existing lock is reported and left alone, never
# overwritten and never an error. `batch_work.sh <N>` is re-runnable on purpose
# — /auto-fix and /auto-judge call it in a loop over `Pending` batches, and the
# claim path's status gate admits both live statuses (`Pending` outright,
# `In Progress` as the resume) — so turning a present lock into a hard failure
# would be a new abort in three skills' fan-out. A finished batch reaches this
# helper too, but only behind `--force`.
# (`claim_task.sh --lock` DOES refuse an existing lock. The asymmetry is
# deliberate: that path is one-shot per task and its lock is a schema
# invariant, this one is a re-runnable coordination marker.) Leaving the
# original file also preserves its `started:` stamp, which is the only record
# of how long the batch has been held.
write_batch_lock() {
  local batch_num="$1" branch="$2" workspace="$3"
  local locks_dir lock_file timestamp expires expiry_epoch

  if ! locks_dir="$(resolve_locks_dir)"; then
    # Unreachable in practice — `git rev-parse --show-toplevel` already
    # succeeded above. Warn rather than abort: batch state lives in
    # review_tasks.md, and the lock is an advisory in-flight marker, so a
    # git-plumbing failure must not cost the caller its worktree.
    echo "⚠️  Could not resolve sysop/runtime/locks/ — batch lock not written." >&2
    return 0
  fi

  lock_file="${locks_dir}/BATCH-${batch_num}.lock"
  if [[ -f "$lock_file" ]]; then
    echo "ℹ️  Batch lock already present (left as-is): ${lock_file}"
    return 0
  fi

  mkdir -p "$locks_dir"
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # Expiry = 4 hours out. Same three-way `date` fallback as claim_task.sh
  # (BSD `-v` → GNU `-d` → POSIX epoch arithmetic) so a lock never lands with
  # a blank `expires:` field.
  if date -v+4H +"%Y-%m-%dT%H:%M:%SZ" &>/dev/null; then
    expires=$(date -u -v+4H +"%Y-%m-%dT%H:%M:%SZ")
  elif expires=$(date -u -d "+4 hours" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null); then
    : # GNU date succeeded
  else
    expiry_epoch=$(( $(date +%s) + 14400 ))
    expires=$(date -u -r "$expiry_epoch" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
      || date -u "+%Y-%m-%dT%H:%M:%SZ" -d "@$expiry_epoch" 2>/dev/null \
      || echo "")
    if [[ -z "$expires" ]]; then
      echo "⚠️  Unable to compute lock expiry — batch lock not written." >&2
      return 0
    fi
  fi

  # Values are written unquoted, exactly as claim_task.sh does. The batch
  # TITLE is deliberately NOT interpolated: a title carrying `: ` would make
  # the lock invalid YAML, and scope_overlap.py parses locks as YAML — a
  # malformed lock would silently drop the batch out of the in-flight set,
  # which is the defect this whole change exists to fix.
  cat > "$lock_file" <<EOF
task_id: BATCH-${batch_num}
status: in_progress
agent: batch_work.sh
branch: ${branch}
mode: worktree
workspace: ${workspace}
started: ${timestamp}
expires: ${expires}
files_impacted:
  - (update manually or via git diff --name-only main...HEAD)
plan_summary: (update with a one-line description of the work)
notes:
EOF

  echo "✅ Batch lock created: ${lock_file}"
}

# ── Helper: remove the batch lock ─────────────────────────────
# Reports what it did either way — a removal path that is silent when the file
# is absent cannot be distinguished from one that never ran.
remove_batch_lock() {
  local batch_num="$1"
  local locks_dir lock_file

  if ! locks_dir="$(resolve_locks_dir)"; then
    echo "⚠️  Could not resolve sysop/runtime/locks/ — batch lock not removed." >&2
    return 0
  fi

  lock_file="${locks_dir}/BATCH-${batch_num}.lock"
  if [[ -f "$lock_file" ]]; then
    rm -f "$lock_file"
    echo "✅ Removed batch lock ${lock_file}."
  else
    echo "ℹ️  No batch lock at ${lock_file} (already released, or the batch was claimed before batch locks shipped)."
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
    # Every DECLARED status gets a glyph. `Review Ready` and `Ready for Review`
    # used to fall to `*)` and render `❓` — the glyph a typo gets — so the one
    # signal this table has for "that status is not a thing" was spent on two
    # values the workflow defines. Now `❓` means only what it says, which is
    # what makes it worth printing at all.
    case "$status" in
      Pending)              icon="⬜" ;;
      "In Progress")        icon="🔵" ;;
      "Review Ready")       icon="👀" ;;
      Complete|Merged|"Ready for Review") icon="✅" ;;
      *)                    icon="❓" ;;
    esac

    # In --list mode, skip the finished three. `Ready for Review` joins
    # `Complete`/`Merged` here because it is terminal despite its name, and
    # because the claim path refuses all three — a listing that offers work the
    # claim path will not take is the contradiction this pairing removes.
    #
    # `Review Ready` deliberately stays visible: it is LIVE, and it is the one
    # status that needs someone to act. The claim path refuses it too, but for
    # the opposite reason — you should see it, you just should not re-claim it.
    if ! $SHOW_ALL && [[ "$status" == "Complete" || "$status" == "Merged" \
                         || "$status" == "Ready for Review" ]]; then
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
    echo "   The worktree and the lock are still created — the batch will read" >&2
    echo "   'Pending' while holding a lock. Clear it with: bash sysop/scripts/batch_work.sh --release ${batch_num}" >&2
    return 0
  fi

  # Working tree must be clean for review_tasks.md
  if ! git -C "$REPO_ROOT" diff --quiet -- review_tasks.md 2>/dev/null || \
     ! git -C "$REPO_ROOT" diff --cached --quiet -- review_tasks.md 2>/dev/null; then
    echo "⚠️  review_tasks.md has uncommitted changes. Skipping batch claim." >&2
    echo "   The worktree and the lock are still created — the batch will read" >&2
    echo "   'Pending' while holding a lock. Clear it with: bash sysop/scripts/batch_work.sh --release ${batch_num}" >&2
    return 0
  fi

  # Pull latest main
  echo "📥 Pulling latest main..."
  git pull --ff-only origin main 2>/dev/null || {
    echo "⚠️  git pull --ff-only failed. Skipping batch claim." >&2
    echo "   The worktree and the lock are still created — the batch will read" >&2
    echo "   'Pending' while holding a lock. Clear it with: bash sysop/scripts/batch_work.sh --release ${batch_num}" >&2
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
    # `|| true` for the same reason as the release path's copy: without it the
    # abort pre-empts the message below.
    batch_start=$(grep -n "^### Batch ${batch_num} " "$TASKS_FILE" | head -1 | cut -d: -f1 || true)

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

# ── Mode: --release (un-claim) ────────────────────────────────
# The sanctioned inverse of a claim, and the reason the lock write is safe to
# ship: without it an abandoned batch keeps a lock nothing ever clears, and
# next_task.py skips a locked batch forever.
#
# Mutations are ordered so every early exit leaves a consistent state:
# pre-flight everything → remove the worktree (abort untouched if it is dirty
# and --force was not passed) → revert review_tasks.md and commit → remove the
# lock last. If the commit fails the lock survives, so the batch still reads as
# claimed rather than as claimable-but-half-reverted.
if [[ "${1:-}" == "--release" ]]; then
  shift
  RELEASE_FORCE=false
  while [[ "${1:-}" == --* ]]; do
    case "$1" in
      --force) RELEASE_FORCE=true; shift ;;
      *) echo "❌ Unknown flag: $1" >&2
         echo "Usage: batch_work.sh --release [--force] <BATCH_NUMBER>" >&2
         exit 1 ;;
    esac
  done

  if [[ -z "${1:-}" ]]; then
    echo "❌ Usage: batch_work.sh --release [--force] <BATCH_NUMBER>" >&2
    exit 1
  fi
  REL_NUM="$(normalize_batch_arg "$1")"
  shift || true
  # Flags are consumed only *before* the positional, so a trailing flag would
  # silently no-op — reject it rather than abort a dirty-worktree release and
  # tell the operator to add the very flag they already passed.
  if [[ "${1:-}" == --* ]]; then
    echo "❌ Flags must come before <BATCH_NUMBER> (e.g. batch_work.sh --release --force ${REL_NUM})." >&2
    echo "   Saw trailing flag: $1" >&2
    exit 1
  fi
  if ! [[ "$REL_NUM" =~ ^[0-9]+$ ]]; then
    echo "❌ Batch number must be a positive integer, got: ${REL_NUM}" >&2
    exit 1
  fi

  # Refuse to run anywhere but the main checkout, BEFORE reading any batch
  # state. `REPO_ROOT` comes from `git rev-parse --show-toplevel`, which in a
  # worktree is the WORKTREE's root — so `$TASKS_FILE` would be that branch's
  # copy of review_tasks.md, frozen at whatever it held when the branch was
  # cut. Releasing off that copy reads a batch as `Pending` while main has it
  # `In Progress`, takes the lock-only path, and clears the lock on a batch
  # that is still claimed. Caught in this phase's own smoke test.
  #
  # This also subsumes the "you are inside the worktree being released" case:
  # that cwd is not the main checkout, so it is refused before anything is read.
  REL_MAIN_ROOT="$(resolve_main_root 2>/dev/null)" || REL_MAIN_ROOT=""
  if [[ -z "$REL_MAIN_ROOT" ]]; then
    echo "❌ Could not resolve the main repo root — refusing to release from an unknown checkout." >&2
    exit 1
  fi
  REL_MAIN_REAL="$(cd "$REL_MAIN_ROOT" && pwd -P 2>/dev/null)" || REL_MAIN_REAL="$REL_MAIN_ROOT"
  REL_HERE_REAL="$(cd "$REPO_ROOT" && pwd -P 2>/dev/null)" || REL_HERE_REAL="$REPO_ROOT"
  if [[ "$REL_HERE_REAL" != "$REL_MAIN_REAL" ]]; then
    echo "❌ --release must run from the main checkout, not a worktree." >&2
    echo "   here: ${REL_HERE_REAL}" >&2
    echo "   main: ${REL_MAIN_REAL}" >&2
    echo "   A worktree carries its branch's own review_tasks.md, so the batch state read here" >&2
    echo "   would be stale. cd to the main checkout and re-run — nothing was released." >&2
    exit 1
  fi

  REL_FOUND=""
  while IFS=$'\t' read -r num title status branch scope verify; do
    if [[ "$num" == "$REL_NUM" ]]; then
      REL_FOUND="found"; REL_STATUS="$status"; REL_BRANCH="$branch"
      break
    fi
  done < <(parse_batches)

  if [[ -z "$REL_FOUND" ]]; then
    echo "❌ Batch ${REL_NUM} not found in review_tasks.md" >&2
    exit 1
  fi

  echo "🔓 Releasing Batch ${REL_NUM}"
  echo "   status: ${REL_STATUS}"
  echo "   branch: ${REL_BRANCH:-<none recorded>}"
  echo ""

  case "$REL_STATUS" in
    Complete|Merged|"Ready for Review")
      echo "❌ Batch ${REL_NUM} is '${REL_STATUS}' — releasing a finished batch would" >&2
      echo "   re-open work that is already done. close_batch.sh owns that transition." >&2
      echo "   If it is holding a stale lock, clear it from main with:" >&2
      echo "     bash sysop/scripts/close_batch.sh ${REL_NUM}" >&2
      exit 1
      ;;
    Pending)
      # No claim to reverse in review_tasks.md — but an orphaned lock is
      # exactly what strands a Pending batch (next_task.py skips it while the
      # status says it is claimable), so clearing the lock IS the release here.
      echo "ℹ️  Batch ${REL_NUM} is already Pending in review_tasks.md — clearing the lock only."
      remove_batch_lock "$REL_NUM"
      exit 0
      ;;
    "In Progress"|"Review Ready") ;;
    *)
      echo "❌ Unrecognized batch status '${REL_STATUS}' — refusing to guess at the inverse." >&2
      exit 1
      ;;
  esac

  # Committing the revert requires the same preconditions the claim commit has.
  REL_CUR_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null)" || REL_CUR_BRANCH=""
  if [[ "$REL_CUR_BRANCH" != "main" ]]; then
    echo "❌ Not on main (on '${REL_CUR_BRANCH:-detached HEAD}')." >&2
    echo "   The claim was committed on main, so its reversal must be too." >&2
    exit 1
  fi
  # `git -C "$REPO_ROOT"`, not a bare git: a bare `-- review_tasks.md`
  # pathspec is resolved against the CWD, so from `<repo>/sysop/scripts/` this
  # check matches nothing and silently passes over a dirty file.
  if ! git -C "$REPO_ROOT" diff --quiet -- review_tasks.md 2>/dev/null || \
     ! git -C "$REPO_ROOT" diff --cached --quiet -- review_tasks.md 2>/dev/null; then
    echo "❌ review_tasks.md has uncommitted changes — commit or stash them first." >&2
    exit 1
  fi

  # Locate the batch section.
  REL_RANGE=""
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    REL_RANGE=$(python3 "$INDEX_SCRIPT" --range "$REL_NUM" 2>/dev/null) || true
  fi
  if [[ -n "$REL_RANGE" ]]; then
    REL_START=$(echo "$REL_RANGE" | cut -f1)
    REL_END=$(echo "$REL_RANGE" | cut -f2)
  else
    REL_TOTAL=$(wc -l < "$TASKS_FILE" | tr -d ' ')
    # Trailing `|| true`: under `set -euo pipefail` a non-matching grep takes
    # the assignment's status down with it, so the script exits 1 *before* the
    # message below can print — a zero-diagnostic abort. Same guard the range
    # grep two lines down already carries.
    REL_START=$(grep -n "^### Batch ${REL_NUM} " "$TASKS_FILE" | head -1 | cut -d: -f1 || true)
    if [[ -z "$REL_START" ]]; then
      echo "❌ Could not find the Batch ${REL_NUM} header in review_tasks.md." >&2
      exit 1
    fi
    REL_END=$(tail -n +"$((REL_START + 1))" "$TASKS_FILE" | grep -n '^##' | head -1 | cut -d: -f1 || true)
    if [[ -n "$REL_END" ]]; then
      REL_END=$((REL_START + REL_END - 1))
    else
      REL_END=$REL_TOTAL
    fi
  fi

  # Completed work is not abandonable by default: `- [x]` inside the batch
  # means an agent finished something, and reverting the header to `Pending`
  # would advertise that work as unstarted. /review-close owns a batch that has
  # results; --release owns one that does not.
  REL_DONE=$(sed -n "${REL_START},${REL_END}p" "$TASKS_FILE" | grep -cE '^- \[x\]' || true)
  if [[ "$REL_DONE" -gt 0 ]] && ! $RELEASE_FORCE; then
    echo "❌ Batch ${REL_NUM} has ${REL_DONE} completed task(s) marked [x]." >&2
    echo "   Releasing would mark the batch Pending with that work still recorded done." >&2
    echo "   Run /review-close on the branch instead, or re-run with --force to release anyway." >&2
    exit 1
  fi

  # Remove the worktree, if one still holds the branch.
  if [[ -n "$REL_BRANCH" ]]; then
    if REL_WT="$(find_worktree_for_branch "$REL_BRANCH")"; then
      REL_WT_REAL="$( { cd "$REL_WT" && pwd -P; } 2>/dev/null || echo "$REL_WT" )"
      # `REL_MAIN_REAL` was resolved by the main-checkout guard above.
      if [[ "$REL_WT_REAL" == "$REL_MAIN_REAL" ]]; then
        echo "⚠️  Branch ${REL_BRANCH} is checked out in the main worktree — not removing it."
      elif $RELEASE_FORCE; then
        if ! git worktree remove --force "$REL_WT_REAL"; then
          echo "❌ Could not remove worktree ${REL_WT_REAL} even with --force." >&2
          echo "   Nothing was released — the claim is intact." >&2
          exit 1
        fi
        echo "✅ Removed worktree ${REL_WT_REAL} (--force)."
      elif git worktree remove "$REL_WT_REAL"; then
        echo "✅ Removed worktree ${REL_WT_REAL}."
      else
        echo "❌ Could not remove worktree ${REL_WT_REAL} (uncommitted changes?)." >&2
        echo "   Re-run with --force to discard, or commit/stash the work first." >&2
        echo "   Nothing was released — the claim is intact." >&2
        exit 1
      fi
    else
      echo "ℹ️  No worktree holds ${REL_BRANCH} (already removed, or never created)."
    fi
  fi

  # Exact inverse of claim_batch's three substitutions, atomically.
  REL_TMP="${TASKS_FILE}.tmp"
  trap 'rm -f "$REL_TMP"' EXIT
  sed -e "${REL_START}s/\`${REL_STATUS}\`/\`Pending\`/" \
      -e "${REL_START},${REL_END}s#^- \[/\]#- [ ]#" \
      -e "/Batch ${REL_NUM})/s/| ${REL_STATUS} |/| Pending |/" \
      "$TASKS_FILE" > "$REL_TMP"
  mv -- "$REL_TMP" "$TASKS_FILE"
  trap - EXIT

  # Repo-anchored AND pathspec-scoped. Anchored because a bare pathspec is
  # CWD-relative — from a subdirectory this failed `fatal: pathspec ... did not
  # match`, after the worktree was already removed, leaving the revert
  # uncommitted with only a raw git error to show for it. Scoped because
  # `git add` + a bare `git commit` sweeps whatever else the operator had
  # staged into `docs: release Batch N` (Phase 151's all-or-nothing rule).
  if ! git -C "$REPO_ROOT" commit -m "docs: release Batch ${REL_NUM}" -- review_tasks.md; then
    # Put the file back. Without this the revert survives on disk while HEAD
    # still says `In Progress`, so `--list` reads the batch as Pending and the
    # re-run prescribed below takes the Pending arm — which clears the lock and
    # never commits, leaving exactly the claimable-but-half-reverted state the
    # mutation ordering above exists to prevent.
    git -C "$REPO_ROOT" checkout -- review_tasks.md 2>/dev/null || true
    echo "" >&2
    echo "❌ git commit failed — the release was rolled back." >&2
    echo "   review_tasks.md is restored to HEAD and the batch lock was NOT removed," >&2
    echo "   so the batch still reads as claimed. NOTE: the worktree was already removed." >&2
    echo "   Fix the commit failure and re-run: bash sysop/scripts/batch_work.sh --release ${REL_NUM}" >&2
    exit 1
  fi
  echo "✅ Reverted Batch ${REL_NUM} to Pending on main."

  rebuild_index
  remove_batch_lock "$REL_NUM"

  echo ""
  echo "ℹ️  Branch ${REL_BRANCH:-<none>} was left in place (a claim leaves the branch, so an un-claim does too)."
  echo "   Delete it yourself if it is dead: git branch -D ${REL_BRANCH:-<branch>}"
  exit 0
fi

# ── Mode: create worktree for batch ───────────────────────────
# Flag parsing mirrors --release exactly (consume flags before the positional,
# then reject a trailing one). A silent no-op on `batch_work.sh 5 --force` is
# worse here than there: the operator believes they forced a claim that was
# actually refused, or — before the status gate below existed — believes they
# were warned about one that went through anyway.
CLAIM_FORCE=false
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --force) CLAIM_FORCE=true; shift ;;
    *) echo "❌ Unknown flag: $1" >&2
       echo "Usage: batch_work.sh [--force] <BATCH_NUMBER>" >&2
       exit 1 ;;
  esac
done

if [[ -z "${1:-}" ]]; then
  echo "❌ Usage: batch_work.sh [--force] <BATCH_NUMBER> | --list | --list-all | --release [--force] <BATCH_NUMBER>" >&2
  exit 1
fi
BATCH_NUM="$(normalize_batch_arg "$1")"
shift || true
if [[ "${1:-}" == --* ]]; then
  echo "❌ Flags must come before <BATCH_NUMBER> (e.g. batch_work.sh --force ${BATCH_NUM})." >&2
  echo "   Saw trailing flag: $1" >&2
  exit 1
fi

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
  echo "   Run: bash sysop/scripts/batch_work.sh --list-all" >&2
  exit 1
fi

if [[ -z "$BATCH_BRANCH" ]]; then
  echo "❌ Batch ${BATCH_NUM} has no Branch: metadata in review_tasks.md" >&2
  exit 1
fi

# ── Status decision, BEFORE anything is written ──────────────
# The claim path had no status decision at all. `claim_batch()`'s
# `!= "Pending"` early return reads like one and is not: that helper performs
# only the review_tasks.md flip, and its `return 0` returns from a FUNCTION —
# the script then continues to the branch/worktree/lock writes regardless. So
# returning early skipped the flip and nothing else.
#
# Ordering is not the mechanism, and saying it was is a defect this phase's own
# round caught: `claim_batch` is called at the line ABOVE those writes, not
# below them. The upstream filing said "after", this phase repeated it to five
# sites without running it, and `claim_batch`'s own messages three functions up
# ("The worktree and the lock are still created") contradict it in the same
# file. Function-scope return is why the writes happen; the line order is not.
#
# Measured on a fixture carrying one batch per status: every PARSEABLE status,
# including `Merged`, `Complete`, `Ready for Review` and parseable undeclared
# values, left a lock and a worktree on disk. An unparseable status was
# invisible to the reader, so nothing was written for it — which is this
# phase's own charset finding, and the reason "any status" would overstate it.
#
# Why a lock makes that § High rather than untidy: `close_batch.sh` and
# `--release` are the only things that remove one. A second agent claiming a
# TERMINAL batch the first still holds gets a worktree on the same branch while
# the first agent's lock stays live — the collision `scope_overlap.py` and the
# whole lock discipline exist to prevent, reached through the front door.
#
# Stated for the terminal states on purpose. `In Progress` is the one status a
# batch carries WHILE another agent holds it, and that arm deliberately proceeds
# (below) because re-running after a dropped session is the documented way back
# in — it announces the foreign claim rather than stepping over it silently.
# That is a resume affordance, not a closed collision, and an earlier draft of
# this comment stated the collision claim unconditionally, which is false for
# the one state where the collision is most likely.
#
# The arms REUSE `--release`'s live/terminal split — they are not its arms
# inverted, and only `Review Ready` actually inverts (release proceeds, claim
# refuses). `Pending` acts on both paths, the terminal three refuse on both,
# `In Progress` proceeds on both. That split was verified by execution against
# all six declared values, and a claim gate that disagreed with the release gate
# about which states are live would just relocate the confusion. `Review Ready`
# is LIVE (--release still owns it) and `Ready for Review` is TERMINAL, despite the
# names.
case "$BATCH_STATUS" in
  Pending)
    : # the claim this path exists for
    ;;
  "In Progress")
    # Resume. Re-running on your own in-flight batch after a dropped session is
    # the documented way back in, so this proceeds — but it announces the lock
    # rather than stepping over it in silence, because the same invocation is
    # what a second agent runs when it does not know the batch is taken.
    # `resolve_locks_dir` returns 1 when the main root is unresolvable, so it is
    # given its own `|| CLAIM_LOCK_DIR=""` rather than being inlined into the
    # test — an unset-on-failure assignment inside `if` would take the helper's
    # exit status for the whole condition and read as "no lock". The `|| true`
    # on the grep is the same guard close_batch.sh's Branch/Grand-Total greps
    # carry: no matching field must not abort the run under `set -euo pipefail`.
    CLAIM_LOCK_DIR="$(resolve_locks_dir 2>/dev/null)" || CLAIM_LOCK_DIR=""
    CLAIM_LOCK_FILE="${CLAIM_LOCK_DIR}/BATCH-${BATCH_NUM}.lock"
    if [[ -n "$CLAIM_LOCK_DIR" && -f "$CLAIM_LOCK_FILE" ]]; then
      echo "ℹ️  Batch ${BATCH_NUM} is already claimed — resuming."
      grep -E '^(agent|started|workspace):' "$CLAIM_LOCK_FILE" \
        | sed 's/^/   /' || true
      echo "   If that is not your claim, stop: release it from main first with"
      echo "     bash sysop/scripts/batch_work.sh --release ${BATCH_NUM}"
      echo ""
    fi
    ;;
  "Review Ready")
    # Live, but finished and awaiting review. Claiming it is precisely the
    # colleague-collision case: the work is done, someone is reviewing it, and a
    # second worktree on that branch has nothing to add.
    if ! $CLAIM_FORCE; then
      echo "❌ Batch ${BATCH_NUM} is '${BATCH_STATUS}' — the work is done and waiting on review." >&2
      echo "   Claiming it would put a second worktree on a branch someone is reviewing." >&2
      echo "   To close it out:  bash sysop/scripts/close_batch.sh ${BATCH_NUM}" >&2
      echo "   To re-open it:    bash sysop/scripts/batch_work.sh --release ${BATCH_NUM}" >&2
      echo "   To claim anyway:  bash sysop/scripts/batch_work.sh --force ${BATCH_NUM}" >&2
      exit 1
    fi
    echo "⚠️  Batch ${BATCH_NUM} is '${BATCH_STATUS}' — claiming anyway (--force)."
    echo ""
    ;;
  Complete|Merged|"Ready for Review")
    # Finished. `--release` refuses this same triple ("releasing a finished
    # batch would re-open work that is already done"); the claim side owes the
    # symmetric refusal. --force keeps the follow-up-work affordance the old
    # warn-and-proceed offered, so the capability survives — it just stops being
    # the default for an invocation that reads like a fresh claim.
    if ! $CLAIM_FORCE; then
      echo "❌ Batch ${BATCH_NUM} is already '${BATCH_STATUS}' — refusing to claim finished work." >&2
      echo "   A claim writes a lock, and only close_batch.sh and --release remove one," >&2
      echo "   so a stray claim here strands the lock on a batch nothing will close again." >&2
      echo "   Doing follow-up work on it is still supported:" >&2
      echo "     bash sysop/scripts/batch_work.sh --force ${BATCH_NUM}" >&2
      exit 1
    fi
    echo "⚠️  Batch ${BATCH_NUM} is already '${BATCH_STATUS}' — claiming anyway (--force, follow-up work)."
    echo ""
    ;;
  *)
    # Undeclared, and --force does NOT open this arm. Every other refusal above
    # knows what it is refusing and can name the right next command; here we
    # cannot tell live from terminal, so there is no safe action to offer and no
    # way to word a --force that means anything. `--release`'s `*)` already
    # refuses "to guess at the inverse" — this refuses to guess at all. The
    # remedy is to fix the record, so the message says which record and where.
    echo "❌ Batch ${BATCH_NUM} has status '${BATCH_STATUS}', which is not a value this workflow defines." >&2
    echo "   Declared: Pending · In Progress · Review Ready (live) · Complete · Merged · Ready for Review (finished)." >&2
    echo "   Nothing can tell whether that batch is claimable, so nothing was written." >&2
    echo "   Fix the header in review_tasks.md, then re-run. --force does not cover this." >&2
    exit 1
    ;;
esac

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

# ── Write the batch lock ──────────────────────────────────────
# After the worktree exists, so `workspace:` records a path that is really
# there — scope_overlap.py reads the in-flight scope from that worktree's diff,
# and sitrep_survey.py reports a lock pointing at a missing workspace as a
# stale-lock discrepancy.
write_batch_lock "$BATCH_NUM" "$BATCH_BRANCH" "$WORKTREE_DIR"

# ── Hooks: deliberately not armed here ───────────────────────
# Worktrees share the main repo's hooks directory, so arming from inside a new
# worktree pushed this batch branch's sysop/scripts/hooks/* into the MAIN
# checkout — replacing a consumer's armed checks with the shipped skeletons.
# Dropped in Phase 150 (upstream #202); see the fuller note in claim_task.sh.
# Arm explicitly from the main checkout: bash sysop/scripts/install_hooks.sh

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
echo "   Cleanup:   bash sysop/scripts/cleanup_worktrees.sh --clean"
