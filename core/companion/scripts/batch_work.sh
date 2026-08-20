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
# Uses the shadow JSON index (sysop/scripts/review_index.py), which is the ONLY
# parser — the inline bash regex fallback this comment used to advertise was
# retired (Q-036, Q-226); see `require_index_parser` for the reasoning.
# Output: tab-separated lines: NUMBER<tab>TITLE<tab>STATUS<tab>BRANCH<tab>SCOPE<tab>VERIFY
INDEX_SCRIPT="${REPO_ROOT}/sysop/scripts/review_index.py"

# ── Helper: refuse when an unterminated fence swallows structure (Q-012) ──
#
# `review_index.py` ignores an unterminated fence on purpose, so a fenced
# EXAMPLE `### Batch <N>` is parsed as a real batch and — because batches are
# keyed by number — OVERWRITES the real one. Measured: on such a tracker the
# index path creates a branch, a worktree and a lock for a batch the file says
# is `Merged`, while this script's own grep fallback correctly refuses. The
# better-equipped path is the broken one, which is why the fix is a refusal
# here rather than "route everything through the index".
#
# Deliberately NO `--force` arm. The claim path's existing `--force` covers the
# statuses a doc example carries (`Complete|Merged|Ready for Review`), so a
# fence bypass would be reachable by a flag that already exists — and unlike the
# cases where an escape hatch is mercy, the remedy costs nothing: close the
# fence. Q-213 is the standing example of a hatch that nullified its own check.
#
# Callers must invoke this BEFORE flag parsing for that reason.
#
# `&& rc=0 || rc=$?`, not `|| true`: under `set -euo pipefail` a bare `|| true`
# discards the status (verified: `$?` becomes 0), and `local rc=$(cmd) || rc=$?`
# is masked by `local`'s own exit status. Keep the declaration separate.
refuse_on_structural_fence() {
  # $1 is "force" when the caller's own --allow-open-fence was given. It admits
  # the AMBIGUOUS case (exit 5, any unterminated fence containing a batch
  # header) and never the PROVEN one (exit 3, a fenced batch header colliding
  # with a real number). In THIS script Q-012's ordering does the work: the
  # check runs above flag parsing, so no flag can reach exit 3.
  #
  # It is a DEDICATED flag, not `--force`. `--force` means "skip the merge-base
  # ancestry check" in close_batch.sh and "admit a terminal status" in
  # batch_work.sh, and `/review-close` Step 4b mandates it for every `pr`-policy
  # consumer — so binding the fence escape to it disarmed this gate on the close
  # path for exactly the consumers it protects. Found by this phase's round,
  # which closed a fenced example to `Merged` and corrupted the Grand Total.
  local forced="${1:-}"
  local rc=0
  local err=""
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    # `2>&1 >/dev/null` keeps the diagnostic and drops the "fences ok" line, so
    # the check runs ONCE. Order matters: stderr is duped to the current stdout
    # (the capture) before stdout is sent to /dev/null.
    err=$(python3 "$INDEX_SCRIPT" --check-fences 2>&1 >/dev/null) && rc=0 || rc=$?
    if [[ "$rc" -eq 3 ]]; then
      echo "❌ review_tasks.md: an unterminated fence contains a duplicate batch header." >&2
      echo "$err" >&2
      echo "   Close the fence in review_tasks.md, then re-run. --force does not cover this." >&2
      return 1
    fi
    if [[ "$rc" -eq 5 ]]; then
      if [[ "$forced" == "force" ]]; then
        echo "⚠️  review_tasks.md has an unterminated fence — proceeding under --allow-open-fence." >&2
        echo "$err" >&2
        return 0
      fi
      echo "❌ review_tasks.md: an unterminated fence is open (Q-229, Q-231)." >&2
      echo "$err" >&2
      return 1
    fi
  fi
  return 0
}

# Q-037: refuse to MUTATE a batch number the tracker declares more than once.
#
# Scoped to the one number, not the file, and that is the whole design. A real
# tracker measured 2026-08-16 restarts batch numbering per round (Round 1: 1-6,
# Round 2: 1-5); nothing in the shipped tree forbids that — WORKFLOW.md's
# template nests `### Batch <N>` under `## Round N` and states no numbering
# scope. (An earlier version of this comment added "and no shipped skill derives
# the next number from existing headers". That is FALSE and was corrected in
# Phase 211: `codebase-review/SKILL.md:164` and `security-audit/SKILL.md:179` —
# the only two writers of batch headers in the tree — both say `next_batch_number`
# = highest Batch N + 1, i.e. a file-global rule. It does not rescue the
# whole-file refusal, because nothing ENFORCES that rule and a per-round tracker
# still parses; but the scoping argument rests on the template's silence alone,
# which is a narrower claim than the one that was written here.) So
# refusing the whole file would reject a legal tracker, which is the defect
# Phase 208 shipped and had to reshape mid-round. Refusing only the number being
# acted on stops the operator exactly when acting would be a coin flip and
# leaves every unambiguous batch on that file claimable.
#
# NO availability guard, unlike refuse_on_structural_fence: `parse_batches`
# below now REQUIRES python3 + review_index.py, so there is no path that reaches
# a mutation without them. A guard here would only add a way to skip the check.
refuse_on_duplicate_number() {
  local n="$1" err="" rc=0
  err=$(python3 "$INDEX_SCRIPT" --check-duplicates "$n" 2>&1 >/dev/null) && rc=0 || rc=$?
  if [[ "$rc" -eq 4 ]]; then
    # The diagnostic is the Python side's, verbatim — it carries the line
    # numbers. Restating it here would be a second wording to keep in sync.
    echo "$err" >&2
    return 1
  fi
  return 0
}

parse_batches() {
  # `review_index.py` is the only parser. Availability is established by
  # `require_index_parser` above the dispatch — deliberately not re-checked
  # here, because this function's callers cannot observe its exit status.
  #
  # stderr is NOT redirected, and that is load-bearing: review_index.py's
  # duplicate-number warning (Q-037) is the only place an operator learns that a
  # batch is missing from this very output. The previous `2>/dev/null` would
  # have swallowed it, which is how the collision stayed invisible.
  python3 "$INDEX_SCRIPT" --list
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

# ── The parser preflight (Q-036, Q-226) ──────────────────────
#
# Runs HERE, above every dispatch, and not inside `parse_batches` — because all
# three of its callers consume it as `done < <(parse_batches)`, and process
# substitution discards the exit status. A refusal placed inside the
# row-producing function would print to stderr, be ignored, and leave the loop
# reading empty input: the script would render a table header and then behave as
# though the tracker held no batches. Placing it above the dispatch is what makes
# the refusal an actual halt.
#
# This is the retirement of `_parse_batches_fallback` (Q-036: it had no fence
# rule, so a fenced `### Batch <N>` was structural to it alone and claimable;
# Q-226: its `while read` dropped the file's last line when there was no
# trailing newline, losing a whole batch from --list-all and from the claim
# path). Both die with the code rather than being patched, because a second
# divergent parser is the defect and one more fix would not have changed that.
#
# The trade, stated rather than buried: the old code fell through to bash on ANY
# non-zero exit from review_index.py — a corrupt vendor copy, a Python version
# skew — so it recovered from a FAILING index, not merely a missing interpreter.
# That recovery is now gone, and the failure is loud instead. python3 is already
# a documented hard prerequisite (README.md § Prerequisites) and self_check.sh
# exits non-zero without it, so an install that cannot run this is one Sysop
# already refuses to certify.
require_index_parser() {
  if ! command -v python3 &>/dev/null; then
    echo "❌ python3 is required to read review_tasks.md and was not found." >&2
    echo "   It is a hard prerequisite (README.md § Prerequisites)." >&2
    echo "   Diagnose with: bash sysop/scripts/self_check.sh" >&2
    return 1
  fi
  if [[ ! -f "$INDEX_SCRIPT" ]]; then
    echo "❌ Missing ${INDEX_SCRIPT}, which is the only parser for review_tasks.md." >&2
    echo "   Reinstall or update Sysop to restore it." >&2
    return 1
  fi
  # Presence is not usability, and the difference is not academic. A TRUNCATED
  # or corrupt review_index.py defines nothing, runs nothing, and exits 0 with
  # empty output — so `--list` printed an empty table and said "No batches
  # found" on a tracker full of them, at exit 0, with no diagnostic on any
  # stream. That is the exact silent-degradation this retirement was supposed to
  # replace with a loud failure, and the phase's own record claimed it had.
  # Found by this phase's review round.
  #
  # The probe is a POSITIVE self-test: `--check-duplicates 0` must print its
  # one-line answer. A file that parses but does nothing produces no output and
  # fails here, where an exit-code-only check would pass it.
  local probe=""
  probe=$(python3 "$INDEX_SCRIPT" --check-duplicates 0 2>/dev/null) || probe=""
  if [[ -z "$probe" ]]; then
    echo "❌ ${INDEX_SCRIPT} did not answer a basic query." >&2
    echo "   It is present but not usable — a truncated or corrupt copy, or a" >&2
    echo "   python3 too old to run it. review_tasks.md cannot be read safely." >&2
    echo "   Diagnose with: python3 ${INDEX_SCRIPT} --list" >&2
    return 1
  fi
  return 0
}
require_index_parser || exit 1

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

  # Find batch section boundaries. `review_index.py` is the ONLY parser here.
  #
  # Q-017/Phase 211 retired the grep fallback that used to occupy the `else`
  # arm. What it was NOT reachable by, each checked rather than assumed:
  #   - a missing python3 — `require_index_parser || exit 1`, above the
  #     dispatch, refuses that for the whole script;
  #   - a header the index cannot parse (an ASCII hyphen where
  #     `_BATCH_HEADER_RE` demands an em-dash) — the status lookup upstream
  #     refuses first, with "Batch N not found". Measured: `close_batch.sh`
  #     DOES close such a batch through its own surviving fallback, so the
  #     shape is live there and dead here. That asymmetry is Q-017's remaining
  #     half and is pinned in tests/test_batch_range_offset_guard.py.
  # What could reach it was `--range`'s own fence preflight firing in the window
  # after this script's preflight (a `git pull` between the two), whose `|| true`
  # then swallowed the refusal and handed the range to a fence-BLIND grep. So the
  # arm was a silent bypass of a refusal, on a path nothing could construct on
  # demand. A wrong range is worse than a refusal, and now it is one.
  local batch_start batch_end
  local range_line=""
  range_line=$(python3 "$INDEX_SCRIPT" --range "$batch_num") || true

  if [[ -z "$range_line" ]]; then
    echo "❌ review_index.py could not locate Batch ${batch_num} in review_tasks.md." >&2
    echo "   Refusing rather than guessing the range: the retired grep fallback" >&2
    echo "   bounded batches fence-blind and matched headers the index does not." >&2
    echo "   The header needs an em-dash and a backticked status, as in:" >&2
    echo "     ### Batch ${batch_num} — Title \`Pending\`" >&2
    echo "   Compare against: python3 ${INDEX_SCRIPT} --list" >&2
    return 1
  fi
  batch_start=$(echo "$range_line" | cut -f1)
  batch_end=$(echo "$range_line" | cut -f2)

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
  # Q-012: before flag parsing, so --force cannot reach past the exit-3 arm.
  # The exit-5 arm (Q-229/Q-231: any unterminated fence) IS forceable, so the
  # flag is pre-scanned here rather than read from RELEASE_FORCE below — that
  # variable does not exist yet, and moving this call after it would hand
  # --force the exit-3 bypass the comment above exists to deny.
  _fence_force=""
  for _a in "$@"; do [[ "$_a" == "--allow-open-fence" ]] && _fence_force="force"; done
  refuse_on_structural_fence "$_fence_force" || exit 1
  RELEASE_FORCE=false
  while [[ "${1:-}" == --* ]]; do
    case "$1" in
      --force) RELEASE_FORCE=true; shift ;;
      --allow-open-fence) shift ;;   # consumed by the fence pre-scan above
      *) echo "❌ Unknown flag: $1" >&2
         echo "Usage: batch_work.sh --release [--force] [--allow-open-fence] <BATCH_NUMBER>" >&2
         exit 1 ;;
    esac
  done

  if [[ -z "${1:-}" ]]; then
    echo "❌ Usage: batch_work.sh --release [--force] [--allow-open-fence] <BATCH_NUMBER>" >&2
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

  # Q-037: as early as the number is known, and before any state is read or
  # written. `--force` is parsed above but cannot reach past this, matching the
  # fence refusal's placement rule for the same reason: --force already admits
  # the statuses an ambiguous batch is likely to carry.
  refuse_on_duplicate_number "$REL_NUM" || exit 1

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
  # `-ef` (same device+inode), NOT a string compare: `pwd -P` resolves symlinks
  # but not CASE, and `REPO_ROOT` carries the on-disk spelling while
  # `REL_MAIN_ROOT` carries the spelling the caller entered. On a
  # case-insensitive filesystem the two reach the same directory and compare
  # unequal, which refused a legitimate release FROM the main checkout.
  REL_MAIN_REAL="$(cd "$REL_MAIN_ROOT" && pwd -P 2>/dev/null)" || REL_MAIN_REAL="$REL_MAIN_ROOT"
  REL_HERE_REAL="$(cd "$REPO_ROOT" && pwd -P 2>/dev/null)" || REL_HERE_REAL="$REPO_ROOT"
  if [[ ! "$REL_HERE_REAL" -ef "$REL_MAIN_REAL" ]]; then
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

  # Locate the batch section. `review_index.py` is the ONLY parser here, for
  # the reason the claim path's copy states (Q-017/Phase 211) — and the stake is
  # higher on this path: REL_END bounds the `- [x]` count implementing
  # "Completed work is not abandonable by default" below, so a range bounded
  # away from the finished work is a safety-guard BYPASS, not a miscount. The
  # retired fallback could revert a batch that had results, at exit 0, silently.
  REL_RANGE=""
  REL_RANGE=$(python3 "$INDEX_SCRIPT" --range "$REL_NUM") || true
  if [[ -z "$REL_RANGE" ]]; then
    echo "❌ review_index.py could not locate Batch ${REL_NUM} in review_tasks.md." >&2
    echo "   Refusing rather than guessing the range: this range bounds the" >&2
    echo "   completed-work check that makes --release safe, so a guessed one" >&2
    echo "   could abandon finished work silently." >&2
    echo "   The header needs an em-dash and a backticked status, as in:" >&2
    echo "     ### Batch ${REL_NUM} — Title \`In Progress\`" >&2
    echo "   Compare against: python3 ${INDEX_SCRIPT} --list" >&2
    exit 1
  fi
  REL_START=$(echo "$REL_RANGE" | cut -f1)
  REL_END=$(echo "$REL_RANGE" | cut -f2)

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
      # `-ef`, not `==` — a case-divergent spelling would make this
      # "never remove the main worktree" guard MISS, which is the direction
      # that fails open. (git refuses to remove a main working tree, so it is
      # the backstop; a guard whose whole job is not reaching that error should
      # not depend on it.)
      if [[ "$REL_WT_REAL" -ef "$REL_MAIN_REAL" ]]; then
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
#
# Q-012: the fence refusal runs BEFORE that parsing, for the same reason the
# comment above gives — `--force` already admits `Complete|Merged|Ready for
# Review`, which are exactly the statuses a fenced doc example carries, so a
# refusal placed after it would be bypassable by an existing flag. It also runs
# before the status gate below, so the operator never reads a `Pending` banner
# for a batch the file records as `Merged`.
# The exit-5 arm is forceable and CLAIM_FORCE is parsed below, so the flag is
# pre-scanned rather than read from it; see the --release copy above.
_fence_force=""
for _a in "$@"; do [[ "$_a" == "--allow-open-fence" ]] && _fence_force="force"; done
refuse_on_structural_fence "$_fence_force" || exit 1

CLAIM_FORCE=false
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --force) CLAIM_FORCE=true; shift ;;
    --allow-open-fence) shift ;;   # consumed by the fence pre-scan above
    *) echo "❌ Unknown flag: $1" >&2
       echo "Usage: batch_work.sh [--force] [--allow-open-fence] <BATCH_NUMBER>" >&2
       exit 1 ;;
  esac
done

if [[ -z "${1:-}" ]]; then
  echo "❌ Usage: batch_work.sh [--force] [--allow-open-fence] <BATCH_NUMBER> | --list | --list-all | --release [--force] <BATCH_NUMBER>" >&2
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

# Q-037: as early as the number is known, and before the batch is located,
# before the status gate, and before any branch, worktree or lock exists.
# `--force` is parsed above and cannot reach past this — same rule as the fence
# refusal, and for the same reason.
refuse_on_duplicate_number "$BATCH_NUM" || exit 1

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
# `|| exit 1`, not a bare call: `claim_batch`'s own `return` returns from a
# FUNCTION, and this script continues to the branch/worktree/lock writes
# regardless — the mechanism the status-decision comment above spells out.
# Its range refusal (Q-017) would otherwise print and then be walked past,
# leaving a lock and a worktree against a batch nothing could bound.
claim_batch "$BATCH_NUM" "$BATCH_STATUS" || exit 1

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
# Dropped in Phase 150 (internal tracker #202); see the fuller note in claim_task.sh.
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
