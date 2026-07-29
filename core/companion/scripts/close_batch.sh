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
# A task carrying a `> Failed:` annotation on the following line is NOT closed:
# its checkbox is left as-is and it is excluded from the batch's closed count
# (and so from the Grand Total). A FAIL verdict means the task was attempted and
# left unfinished, so closing it would make review_tasks.md overstate what the
# round resolved. The batch still becomes `Merged` — "this batch shipped, but
# this item in it did not."
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

# ── Checkbox pass: count (mode=count) and rewrite (mode=flip) ──
# ONE program serving both modes, on purpose. The count feeds TASKS_IN_BATCH →
# the Grand Total, and the rewrite decides which boxes flip; if the two ever
# disagreed about what a failed task looks like, the totals would drift from the
# file they describe — the exact class of defect this pass exists to prevent.
#
# awk rather than sed because the decision needs one line of LOOKAHEAD: a task
# is left open when the NEXT line is its `> Failed:` annotation (the shape
# /auto-judge writes, mirroring `> Dropped:`). The bold-tolerance is written
# `[*][*]` rather than `\*\*` and the optional group avoids an interval
# (`{0,2}`), both for BSD/mawk portability; verified byte-identical output
# across one-true-awk 20200816, gawk 5.4.1 and mawk 1.3.4.
#
# `s`/`e` are the batch's 1-indexed line range. Lines outside it pass through
# untouched. A `> Failed:` line sitting one past `e` still counts, because only
# the TASK line is range-checked.
readonly CLOSE_AWK='
function is_open_task(l) { return (l ~ /^- \[ \]/ || l ~ /^- \[\/\]/) }
function is_failed(l) {
  # Deliberately generous. The adversarial round drove the real script against
  # every shape an agent plausibly writes and found each of these SILENTLY
  # closing the task: a missing space after the marker, all-caps, lowercase,
  # bold-italic emphasis, and a space before the colon. All-caps mattered most —
  # TASKS_FAILED:, "FAILED —" and "Tasks Marked FAILED" are the vocabulary
  # /auto-judge uses everywhere EXCEPT the one place the read side was looking.
  # Over-matching is now reported (see HELD); under-matching was silent, so the
  # generous side is the safe one.
  # (No apostrophes in this block: it lives inside a single-quoted shell string.)
  return (tolower(l) ~ /^[[:space:]]*>[[:space:]]*[*_]*failed[*_]*[[:space:]]*:/)
}
function looks_like_failed(l) {
  # A near miss: the annotation WORD starts with "fail" but the line did not
  # match — "> Fail:", "> Failure:", "> FAILED" with no colon. Anchored to the
  # word directly after the marker rather than searched across the whole line,
  # so an ordinary "> Dropped: the test was failing" produces no noise.
  # Reported, never honoured: guessing would be worse than saying plainly
  # "I saw this and did not act on it".
  return (!is_failed(l) && tolower(l) ~ /^[[:space:]]*>[[:space:]]*[*_]*fail/)
}
function emit(nextline,   line) {
  if (!held) return
  line = heldline
  if (heldnr >= s && heldnr <= e) {
    if (is_open_task(line)) {
      if (is_failed(nextline)) {
        failed++
        if (mode == "count") print "HELD " heldnr " " line > "/dev/stderr"
      } else {
        closed++
        if (looks_like_failed(nextline) && mode == "count")
          print "NEARMISS " (heldnr + 1) " " nextline > "/dev/stderr"
        if (mode == "flip") {
          sub(/^- \[ \]/, "- [x]", line)
          sub(/^- \[\/\]/, "- [x]", line)
        }
      }
    } else if (is_failed(line) && !is_open_task(prevline)) {
      # An annotation attached to nothing — a blank line above it, or a line
      # that is not a task. It protects no task, and before this it was
      # indistinguishable from no annotation at all.
      if (mode == "count") print "ORPHAN " heldnr " " line > "/dev/stderr"
    }
  }
  prevline = line
  if (mode == "flip") print line
}
{ emit($0); heldline = $0; heldnr = NR; held = 1 }
END { emit(""); if (mode == "count") printf "%d %d\n", closed + 0, failed + 0 }
'

DRY_RUN=false
FORCE=false
BATCH_NUMS=()

# Parse arguments
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  elif [[ "$arg" == "--force" ]]; then
    FORCE=true
  elif [[ "$arg" =~ ^([Bb][Aa][Tt][Cc][Hh]-)?([0-9]+)$ ]]; then
    # Normalise the claim-ID form and any leading zeros. Both matter for the
    # lock: `007` reaches review_index.py as batch 7 and closes it, but would
    # look for BATCH-007.lock and report "no lock" — closing the batch while
    # stranding its lock. batch_work.sh normalises the same two forms.
    BATCH_NUMS+=("$((10#${BASH_REMATCH[2]}))")
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

# ── Helper: resolve the canonical sysop/runtime/locks/ ────────
# Locks live under the MAIN repo (Phase 32). `git rev-parse --git-common-dir`
# returns the `.git` DIRECTORY — the repo root is its dirname — and answers
# with the relative `.git` from a main checkout, which needs absolutising.
# Deliberate duplicate of the resolution in batch_work.sh / claim_task.sh /
# next_task.py / validate_tasks.py / scope_overlap.py, each of which names the
# others: these files are delivered independently, so a sourced helper missing
# from a partial install would be a worse failure than the duplication.
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

# True only when this close committed to `main` in the MAIN checkout — the one
# state in which the batch is really merged and its lock is really dead.
close_landed_on_main() {
  local main_root here branch
  main_root="$(resolve_main_root 2>/dev/null)" || return 1
  main_root="$(cd "$main_root" && pwd -P 2>/dev/null)" || return 1
  here="$(cd "$REPO_ROOT" && pwd -P 2>/dev/null)" || return 1
  [[ "$here" == "$main_root" ]] || return 1
  branch="$(git symbolic-ref --short HEAD 2>/dev/null)" || return 1
  [[ "$branch" == "main" ]]
}

# ── Helper: remove a closed batch's lock ──────────────────────
# `batch_work.sh` writes `BATCH-<N>.lock` at claim time; a merged batch is no
# longer in flight, so the lock has to go — a write with no removal path would
# make every batch permanently unclaimable after its first claim (next_task.py
# skips a locked batch, and nothing else has ever cleared one).
#
# Reports either way: a removal that is silent when the file is absent cannot
# be told apart from one that never ran.
remove_batch_lock() {
  local batch_num="$1"
  local locks_dir lock_file

  if ! locks_dir="$(resolve_locks_dir)"; then
    echo "   ⚠️  Could not resolve sysop/runtime/locks/ — lock for Batch ${batch_num} not removed." >&2
    return 0
  fi

  lock_file="${locks_dir}/BATCH-${batch_num}.lock"
  if [[ -f "$lock_file" ]]; then
    rm -f "$lock_file"
    echo "   ✅ Removed batch lock ${lock_file}"
  else
    echo "   ℹ️  No batch lock at ${lock_file} (claimed before batch locks shipped, or already released)."
  fi
}

# ── Process each batch ────────────────────────────────────────
CLOSED=()
SKIPPED=()
MERGED_UNLOCK=()
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
    # ...but a Merged batch must not hold a lock. `batch_work.sh <N>` lets a
    # Merged batch through for follow-up work and writes one, and every other
    # removal path refuses a Merged batch — so without this the lock is
    # unremovable by any shipped command, and scope_overlap counts it as
    # in-flight forever. Clearing is unconditionally safe here: the record
    # already says Merged, so nothing is being decided, only tidied. This is
    # also the recovery path when the close commit landed on an integration
    # branch (`pr` policy) and a later run on main finds the batch Merged.
    MERGED_UNLOCK+=("${BATCH_NUM}")
    continue
  fi

  # Allowlist BATCH_STATUS before interpolating into sed patterns. A
  # malformed status (e.g., containing the sed delimiter) would otherwise
  # break the substitution silently.
  case "$BATCH_STATUS" in
    Pending|"In Progress"|"Review Ready") ;;
    Complete|"Ready for Review")
      # Finished, but not by this script's transition. Nothing to flip — yet a
      # lock here is unremovable by every other path (`--release` refuses a
      # finished batch and names THIS script as the owner), so shed it.
      echo "   ℹ️  Batch ${BATCH_NUM} is '${BATCH_STATUS}' — no flip to make."
      SKIPPED+=("${BATCH_NUM}:${BATCH_STATUS}")
      MERGED_UNLOCK+=("${BATCH_NUM}")
      continue
      ;;
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

  # Count tasks that will be closed (for Grand Total adjustment) and, separately,
  # those a FAIL verdict left unfinished. Only the first number reaches the
  # Grand Total, so a failed task is never counted as done.
  BATCH_DIAG="${TASKS_FILE}.diag"
  BATCH_COUNTS=$(awk -v s="$BATCH_START" -v e="$BATCH_END" -v mode=count \
    "$CLOSE_AWK" "$TASKS_FILE" 2>"$BATCH_DIAG")
  TASKS_IN_BATCH=${BATCH_COUNTS%% *}
  TASKS_FAILED_IN_BATCH=${BATCH_COUNTS##* }

  # Say what was held and what was nearly held. Before this, both directions of
  # the annotation decision were silent: a task held open on a stray quoted
  # `> Failed:` line vanished from the Grand Total with no notice, and an
  # annotation the matcher did not recognise closed the task with its failure
  # note left sitting underneath — the exact rendering upstream #207 reported.
  # A dead item and a clean one must not produce identical evidence.
  while IFS=' ' read -r KIND LNO TEXT; do
    case "$KIND" in
      HELD)     echo "   ⏸  held open (line ${LNO}): ${TEXT}" ;;
      NEARMISS) echo "   ⚠️  line ${LNO} looks like a failure note but was NOT recognised — the task above it was CLOSED: ${TEXT}" >&2 ;;
      ORPHAN)   echo "   ⚠️  line ${LNO} is a failure note attached to no open task — it protects nothing: ${TEXT}" >&2 ;;
    esac
  done < "$BATCH_DIAG"
  rm -f "$BATCH_DIAG"

  if $DRY_RUN; then
    echo "   [dry-run] Would update:"
    echo "     - Batch header: '${BATCH_STATUS}' → 'Merged'"
    echo "     - Task checkboxes: ${TASKS_IN_BATCH} tasks → [x]"
    if [[ $TASKS_FAILED_IN_BATCH -gt 0 ]]; then
      echo "     - Failed tasks: ${TASKS_FAILED_IN_BATCH} left open (\`> Failed:\` annotated)"
    fi
    echo "     - Statistics table row: → Merged"
    if DRY_LOCKS_DIR="$(resolve_locks_dir)" && [[ -f "${DRY_LOCKS_DIR}/BATCH-${BATCH_NUM}.lock" ]]; then
      echo "     - Batch lock: would remove ${DRY_LOCKS_DIR}/BATCH-${BATCH_NUM}.lock"
    else
      echo "     - Batch lock: none present"
    fi
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
  # sed handles the line-addressed header + statistics-row edits; awk handles the
  # checkboxes, which need lookahead (see CLOSE_AWK). sed changes no line count,
  # so the line numbers awk is given still hold downstream of the pipe.
  # `pipefail` is set, so a failure in either stage aborts before the `mv`.
  sed -e "${BATCH_START}s#\`${BATCH_STATUS}\`#\`Merged\`#" \
      -e "/Batch ${BATCH_NUM})/s#| ${BATCH_STATUS} |#| Merged |#" \
      -e "/Batch ${BATCH_NUM})/s#| ${BATCH_STATUS}\$#| Merged#" \
      "$TASKS_FILE" \
    | awk -v s="$BATCH_START" -v e="$BATCH_END" -v mode=flip "$CLOSE_AWK" > "$TMP_FILE"

  # `pipefail` catches a stage that *reports* failure; it cannot catch one that
  # exits 0 having written short. That is not hypothetical here — the rewrite is
  # a two-process pipeline, so there are two chances for a silent short write,
  # and the `mv` below is unrecoverable. Assert the output is at least as long
  # as the input before installing it. Not an equality check: awk appends a
  # final newline when the source lacks one, so the count can legitimately grow
  # by one, but it can never legitimately shrink — no expression here deletes a
  # line.
  if [[ ! -s "$TMP_FILE" ]] || \
     [[ "$(wc -l < "$TMP_FILE")" -lt "$(wc -l < "$TASKS_FILE")" ]]; then
    echo "❌ Rewrite of review_tasks.md produced short output — refusing to install it." >&2
    echo "   ${TASKS_FILE} is unchanged. Tempfile kept for inspection: ${TMP_FILE}" >&2
    trap - EXIT
    exit 1
  fi

  mv -- "$TMP_FILE" "$TASKS_FILE"
  trap - EXIT

  TOTAL_TASKS_CLOSED=$((TOTAL_TASKS_CLOSED + TASKS_IN_BATCH))
  if [[ $TASKS_FAILED_IN_BATCH -gt 0 ]]; then
    echo "   ✅ Marked as Merged (${TASKS_IN_BATCH} tasks closed, ${TASKS_FAILED_IN_BATCH} failed — still open)."
  else
    echo "   ✅ Marked as Merged (${TASKS_IN_BATCH} tasks closed)."
  fi
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
  git -C "$REPO_ROOT" add -- review_tasks.md
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

  # Release each closed batch's lock — AFTER the commit, so a commit failure
  # (which exits above) leaves the locks in place and the batches still reading
  # as claimed, rather than half-closed and claimable.
  echo ""
  echo "── Batch locks ──"
  # Only release when the close actually landed on `main` in the MAIN checkout.
  # The lock lives under the main repo and is deleted immediately; the `Merged`
  # flip lives on whatever branch is checked out. Under `pr` policy those are
  # different things — /review-close Step 4b runs here with `--force` on the
  # integration branch, and Step 4d-1 documents that a blocked PR must leave
  # `sysop/runtime/locks/` intact so the work stays recoverable. Releasing here
  # would strip the lock while `main` still reads the batch `Pending`, and
  # /next-task would hand the batch to a second agent while the finished work
  # sat on a blocked PR (reproduced by this phase's adversarial round).
  #
  # Deferring is the safe direction: a lock outliving its merge is a leftover
  # that /sitrep reports and the already-finished sweep below clears on the next
  # run from main, whereas releasing early is a double-claim.
  CLOSE_ON_MAIN=false
  close_landed_on_main && CLOSE_ON_MAIN=true
  CB_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null)" || CB_BRANCH=""
  # `|| true`: this is a best-effort post-commit tidy. The commit has already
  # landed, and `set -e` aborting here would skip the Summary and the terminal
  # one-liner that /review-close Step 4b reads as proof the script completed —
  # making a successful close look like a silent mid-flow abort (ISSUE-0039).
  if $CLOSE_ON_MAIN; then
    for n in "${CLOSED[@]}"; do
      remove_batch_lock "$n" || true
    done
  else
    echo "   ⏸  Close committed on '${CB_BRANCH:-detached HEAD}', not main in the main checkout."
    echo "      Locks kept — the batch is not merged yet, and a lock removed now would let"
    echo "      /next-task re-offer a batch whose work is sitting on an unmerged branch."
    echo "      They are released by the next close run from main: bash sysop/scripts/close_batch.sh ${CLOSED[*]}"
  fi
fi

# A batch that is already finished (Merged / Complete / Ready for Review) sheds
# its lock whether or not this run closed anything: `batch_work.sh <N>` lets a
# finished batch through for follow-up work and writes a lock, and every other
# removal path refuses a finished batch, so without this the lock is unremovable
# by any shipped command. This is also the recovery path for the deferred case
# above — once the PR merges and `main` reads `Merged`, re-running here clears it.
#
# Resolved independently of the commit block, since that block may not have run.
FINISHED_UNLOCK_OK=false
if [[ ${#MERGED_UNLOCK[@]} -gt 0 ]] && ! $DRY_RUN; then
  close_landed_on_main && FINISHED_UNLOCK_OK=true
fi
if $FINISHED_UNLOCK_OK; then
  echo ""
  echo "── Batch locks (already finished) ──"
  for n in "${MERGED_UNLOCK[@]}"; do
    remove_batch_lock "$n" || true
  done
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
