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
# A task carrying a `> Failed:` annotation anywhere in its own block is NOT closed
# (the block is the task line plus the indented lines under it — see CLOSE_AWK):
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
# awk rather than sed because the decision needs LOOKAHEAD: a task is left open
# when its `> Failed:` annotation appears anywhere in the block the task owns.
#
# THE BLOCK IS THE UNIT, and it took an upstream report to learn why. This pass
# originally held exactly ONE line and required the annotation to be physically
# next. But nobody writes one-line tasks: /codebase-review and /security-audit
# both emit a task as a checkbox line PLUS a mandatory indented `file:line` +
# provenance continuation (their § 5c Batch Format templates), and /auto-judge
# then appends the annotation "immediately below the task" — which is two lines
# below the checkbox, not one. So on the shape the shipped writers actually
# emit, the protection could never fire: the task closed `[x]` with its own
# failure note sitting underneath it. Six failed tasks closed that way in a
# single reported round.
#
# The reader was also wrong about who to blame. The one-line shape was never
# /auto-judge's — it is the TASK CREATORS who write two lines, and the comment
# that used to attribute it to the annotator sent a fix at the wrong file.
#
# A task owns its checkbox line plus every INDENTED, non-blank line under it.
# The block ends at a blank line, at any line starting in column 0 (the next
# task bullet, a heading, ordinary prose), or at EOF. An annotation protects
# the NEAREST PRECEDING task bullet within its block and reaches no further —
# which is what keeps the old guarantee that a stray annotation cannot shield
# some arbitrary task further up the file. `is_failed` is tested BEFORE the
# block-end test so a column-0 annotation directly under a task still counts,
# as it always did.
#
# The bold-tolerance is written `[*][*]` rather than `\*\*` and the optional
# group avoids an interval (`{0,2}`), both for BSD/mawk portability; verified
# byte-identical output across one-true-awk 20200816, gawk 5.4.1 and mawk 1.3.4.
#
# `s`/`e` are the batch's 1-indexed line range. Lines outside it pass through
# untouched. Only the TASK line is range-checked, so a block that runs past `e`
# still resolves — and it can now run several lines past, not one.
#
# Under `mode=flip` every input line is reprinted exactly once and in order.
# The pending task and its buffered continuation lines are flushed in order the
# moment the block resolves, and `END` flushes whatever is still pending;
# nothing is dropped, reordered or coalesced.
readonly CLOSE_AWK='
BEGIN {
  # Q-017. `fenced` arrives as a comma-separated list of 1-based line numbers
  # from `review_index.py --fenced-lines`, which is _fenced_mask itself rather
  # than a reimplementation. Empty when there are no fences, and also when
  # python3 is unavailable -- in which case behaviour is exactly what it was
  # before this guard existed, so an absent interpreter cannot make things
  # worse here than they already were.
  # (No apostrophes in this block: it lives inside a single-quoted shell string.)
  nfz = split(fenced, fz, ",")
  for (fi = 1; fi <= nfz; fi++) if (fz[fi] != "") FENCED[fz[fi] + 0] = 1
}
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
function is_continuation(l) {
  # An indented, non-blank line: part of the task above it. Column-0 lines are
  # never continuations, which is what stops the block from running away into
  # the next task, the next heading, or ordinary prose.
  return (l ~ /^[[:space:]]/ && l !~ /^[[:space:]]*$/)
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
function out(l) { if (mode == "flip") print l }
function resolve(protected,   i) {
  # Settle the pending task, then reprint it and every line of its block, in
  # order. Called on every block end and once more at EOF.
  if (!pend) return
  # The fenced test sits HERE, on the one gate both modes share, so the count
  # and the rewrite can never disagree about which tasks are real -- the
  # "4 tasks closed" summary on a three-task batch came from this gate being
  # fence-blind. A fenced task still falls through to out() below and is
  # reprinted byte-for-byte; it is skipped, never dropped.
  if (pnr >= s && pnr <= e && !(pnr in FENCED)) {
    if (protected) {
      failed++
      if (mode == "count") print "HELD " pnr " " ptask > "/dev/stderr"
    } else {
      closed++
      # A near miss is only worth reporting when the task actually CLOSED --
      # if a real annotation turned up later in the block, the task was held
      # and saying "the task above it was CLOSED" would be a false report.
      if (nmnr > 0 && mode == "count")
        print "NEARMISS " nmnr " " nmtext > "/dev/stderr"
      if (mode == "flip") {
        sub(/^- \[ \]/, "- [x]", ptask)
        sub(/^- \[\/\]/, "- [x]", ptask)
      }
    }
  }
  out(ptask)
  for (i = 1; i <= nbuf; i++) out(buf[i])
  pend = 0; nbuf = 0; nmnr = 0
}
{
  if (pend) {
    if (is_failed($0)) { resolve(1); out($0); next }
    # Record the near miss BEFORE the continuation test, not inside it. A near
    # miss is any annotation-shaped line following a pending task, and a
    # column-0 one (`> Fail:` unindented) is not a continuation — so testing
    # this inside that branch made the warning silent for exactly the shape
    # `is_failed` is tested at column 0 to support. The first cut of this fix
    # did that, and it made a MALFORMED annotation produce evidence
    # byte-identical to a clean close: the failure this pass exists to prevent,
    # reintroduced in the other direction while the run got louder elsewhere.
    if (looks_like_failed($0)) { nmnr = NR; nmtext = $0 }
    if (is_continuation($0)) {
      nbuf++; buf[nbuf] = $0
      next
    }
    resolve(0)
  }
  if (is_open_task($0)) { pend = 1; ptask = $0; pnr = NR; nbuf = 0; nmnr = 0; next }
  if (is_failed($0) && NR >= s && NR <= e && mode == "count") {
    # An annotation attached to nothing — a blank line above it, or a line that
    # is not part of any task block. It protects no task, and before this it was
    # indistinguishable from no annotation at all.
    print "ORPHAN " NR " " $0 > "/dev/stderr"
  } else if (looks_like_failed($0) && NR >= s && NR <= e && mode == "count") {
    # The near miss in the DETACHED position, which is the one the round found
    # still silent. `nmnr` above only ever fires while a task is pending, so a
    # `> Fail:` sitting after a blank line, after a heading, or before any task
    # produced NO evidence at all — while the well-formed `> Failed:` in that
    # same position produced ORPHAN. A malformed annotation was once again
    # byte-identical to a clean close, which is the one thing this pass exists
    # to prevent. Both defects it can have are now reported together, because
    # this line is both attached to nothing AND unrecognised.
    print "STRAY " NR " " $0 > "/dev/stderr"
  }
  out($0)
}
END { resolve(0); if (mode == "count") printf "%d %d\n", closed + 0, failed + 0 }
'

DRY_RUN=false
FORCE=false
ALLOW_OPEN_FENCE=false
BATCH_NUMS=()

# Parse arguments
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  elif [[ "$arg" == "--force" ]]; then
    FORCE=true
  elif [[ "$arg" == "--allow-open-fence" ]]; then
    ALLOW_OPEN_FENCE=true
  elif [[ "$arg" =~ ^([Bb][Aa][Tt][Cc][Hh]-)?([0-9]+)$ ]]; then
    # Normalise the claim-ID form and any leading zeros. Both matter for the
    # lock: `007` reaches review_index.py as batch 7 and closes it, but would
    # look for BATCH-007.lock and report "no lock" — closing the batch while
    # stranding its lock. batch_work.sh normalises the same two forms.
    BATCH_NUMS+=("$((10#${BASH_REMATCH[2]}))")
  else
    echo "❌ Unknown argument: ${arg}" >&2
    echo "Usage: close_batch.sh [--dry-run] [--force] [--allow-open-fence] <N> [<N2> ...]" >&2
    exit 1
  fi
done

if [[ ${#BATCH_NUMS[@]} -eq 0 ]]; then
  echo "❌ No batch numbers provided." >&2
  echo "Usage: close_batch.sh [--dry-run] [--force] [--allow-open-fence] <N> [<N2> ...]" >&2
  exit 1
fi

INDEX_SCRIPT="${REPO_ROOT}/sysop/scripts/review_index.py"

# ── Helper: refuse when an unterminated fence swallows structure (Q-012) ──
#
# Byte-identical to batch_work.sh's copy and pinned equal by
# tests/test_fence_refusal.py — these scripts install standalone and source no
# shared library, so duplicate-and-pin is the only shape available (the idiom
# `_fenced_mask` already uses across four Python modules). Retiring the
# duplication is the shared-resolver question, filed separately.
refuse_on_structural_fence() {
  # $1 is "force" when the caller's own --allow-open-fence was given. It admits
  # the AMBIGUOUS case (exit 5, any unterminated fence containing a batch
  # header) and never the PROVEN one (exit 3, a fenced batch header colliding
  # with a real number). Note the mechanism differs by script and this comment
  # used to claim batch_work.sh's in both: THERE the check runs above flag
  # parsing, so no flag can reach exit 3. HERE flags are parsed at :205, well
  # above this call — what makes exit 3 unforceable is that its branch below
  # ignores `$forced` entirely. The identity pin strips comments, so it did not
  # catch the copied claim; the round did.
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

# ── Q-017: the fenced-line mask CLOSE_AWK rewrites around ─────
#
# `--range` was already fence-aware; CLOSE_AWK was not, so the index path
# rewrote a fence-aware span with a fence-blind rewriter. Measured 2026-08-16 on
# a balanced-fence tracker: "4 tasks closed" on a three-task batch, with a task
# that exists only inside a fenced documentation example marked complete. The
# grep fallback merely under-reached; the preferred path corrupted data.
#
# Computed ONCE, here, rather than per batch. That is safe because neither stage
# of the rewrite changes the line count -- the sed below is line-addressed
# substitution only (its own comment records this), and CLOSE_AWK in flip mode
# reprints every line it reads. So the numbers stay valid across every iteration
# of the per-batch loop.
#
# Empty when python3 or the index is unavailable, which reproduces exactly the
# pre-existing behaviour on that path. This deliberately does NOT introduce a
# refusal: close_batch.sh diagnoses by commit presence rather than exit code
# (see the note above the annotation summary), so a refusal added here could not
# reach its caller -- that contract is a separate problem and is not touched.
FENCED_LINES=""
# `FENCED_OK` distinguishes "the mask is empty because this tracker has no fences"
# from "the mask is empty because the probe FAILED" -- a parser crash, a damaged
# tracker, an older installed `review_index.py` without `--fenced-lines`. The `2>/dev/null`
# swallows the reason, and until Phase 233's round the two were indistinguishable
# downstream, so the Q-017 warning told an operator the range was fence-aware on a
# run where no mask had been built. That is the SAME wrong-cause conflation this
# file indicts 700 lines below -- reintroduced by the fix for it.
FENCED_OK=false
if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
  if FENCED_LINES=$(python3 "$INDEX_SCRIPT" --fenced-lines 2>/dev/null); then
    FENCED_OK=true
  else
    FENCED_LINES=""
  fi
fi

# `--dry-run` WARNS instead of refusing: it writes nothing, and a read-only
# preview that refuses is the wrong trade — the operator running it is most
# likely inspecting the very file they are mid-edit on.
fence_preflight() {
  # $FORCE is parsed at the top of this script, well above here, so unlike
  # batch_work.sh's copies this one can just read it.
  local _fence_force=""
  # `if`, not `$ALLOW_OPEN_FENCE && …`: the `&&` form returns 1 when the flag is
  # false, which is only harmless because this function is invoked in a
  # `|| exit 1` list where `set -e` is suppressed. That is a property of the
  # CALL SITE, not of this code, and it would change silently if it ever did.
  #
  # It reads its OWN flag, not `--force`. `--force` here means "skip the
  # merge-base ancestry check", and `/review-close` Step 4b mandates it for
  # EVERY `pr`-policy consumer — so binding the fence escape to it disarmed this
  # gate on the close path for exactly the consumers the gate protects. Measured
  # by the round: a `--force` close rewrote a fenced example to `Merged`,
  # flipped its illustration task to `[x]`, and corrupted the Grand Total.
  if $ALLOW_OPEN_FENCE; then _fence_force="force"; fi
  if refuse_on_structural_fence "$_fence_force"; then
    return 0
  fi
  if $DRY_RUN; then
    echo "⚠️  --dry-run: continuing anyway; the preview below may describe the" >&2
    echo "   fenced example rather than the real batch." >&2
    return 0
  fi
  return 1
}

# ── Helper: find batch section boundaries ─────────────────────
# Sets BATCH_START, BATCH_END (line numbers) for a given batch number.
# Uses the shadow JSON index for reliable parsing; falls back to grep.
# Returns 1 if batch not found.
find_batch_range() {
  local batch_num="$1"

  # Which resolver answered. Read by the caller, which is where the warning is
  # printed — see `RANGE_SOURCE` at the call site (Q-017).
  RANGE_SOURCE="index"

  # Try JSON index first.
  #
  # `RANGE_SOURCE` distinguishes the two reasons the fallback is taken, and that
  # distinction is the whole correctness of the warning at the call site. The
  # first cut set it to `fallback` on ANY empty `range_line` — which covers a
  # non-canonical header, an absent `python3`, an absent or partial
  # `$INDEX_SCRIPT`, and a parser crash — and then asserted the first cause
  # unconditionally. Reproduced by this phase's own round on a byte-perfect
  # canonical tracker with `python3` off `PATH`: the operator was told their
  # header was malformed, and pointed at a `python3` remedy that could not run.
  local range_line="" index_ran=false
  if command -v python3 &>/dev/null && [[ -f "$INDEX_SCRIPT" ]]; then
    index_ran=true
    range_line=$(python3 "$INDEX_SCRIPT" --range "$batch_num" 2>/dev/null) || true
  fi

  if [[ -n "$range_line" ]]; then
    BATCH_START=$(echo "$range_line" | cut -f1)
    BATCH_END=$(echo "$range_line" | cut -f2)
    return 0
  fi

  if $index_ran; then
    RANGE_SOURCE="fallback"          # the index ran and did not match this header
  else
    RANGE_SOURCE="fallback-no-index" # the index never ran; says nothing about the header
  fi

  # Fallback: grep-based range detection
  #
  # `awk END{print NR}`, not `wc -l`: `wc -l` counts NEWLINES, so a review_tasks.md
  # whose last line has no trailing newline reports one line short. The last batch
  # then ended one line early and its final task was silently skipped — the batch
  # header flipped to `Merged` while the task stayed `[ ]` and the count said
  # `0 tasks closed`. Worse, the JSON-index path above does NOT have this bug
  # (`review_index.py` uses `readlines()`, which returns an unterminated final
  # line), so the two resolvers disagreed on exactly this file — and this pass
  # exists to stop the count and the file it describes from drifting apart.
  local total_lines
  total_lines=$(awk 'END { print NR }' "$TASKS_FILE")

  BATCH_START=$(grep -n "^### Batch ${batch_num} " "$TASKS_FILE" | head -1 | cut -d: -f1)
  if [[ -z "$BATCH_START" ]]; then
    return 1
  fi

  # Q-017: the boundary search skips FENCED `##` lines.
  #
  # `grep -n '^##'` is kept verbatim -- it still names the boundary rule, and
  # three source-shape guards in `tests/test_flag_contract.py` pin that literal
  # (one of them because a first draft re-implemented this fallback in Python
  # and asserted against the model instead of the script). What changed is that
  # its hits are now FILTERED: a `## ` heading quoted inside a fenced example is
  # content, not structure, and bounding on it ends the batch early.
  #
  # Reproduced at Phase 233's HEAD on a near-miss header carrying a fenced
  # `## Deferred`: 1 of 3 tasks closed, the header flipped to `Merged`, TASK-2
  # and TASK-3 left `[ ]` underneath, exit 0, run committed.
  #
  # `$FENCED_LINES` is the SAME mask `CLOSE_AWK` rewrites around -- computed
  # once at the top of this script from `review_index.py --fenced-lines`, which
  # is `_fenced_mask` itself. Deliberately not a fence parser in awk: that would
  # be a sixth implementation of a rule already written four times in Python,
  # and Phase 209 refused it here for that reason.
  #
  # This changes the RANGE, never the verdict. Whether a non-canonical header
  # should close at all is a separate, ratified question (2026-08-21: keep
  # closing, stop being silent) and is untouched -- which is why this fix needs
  # none of the caller-contract change three prior passes declined.
  #
  # Availability: the mask is populated under `python3 && -f $INDEX_SCRIPT`,
  # which is EXACTLY the `fallback` arm's own precondition, so the arm where
  # this defect was measured always has it. On the `fallback-no-index` arm the
  # mask is empty and the range degrades to the pre-existing fence-blind
  # answer -- unavoidable without python3, and pinned as such by
  # `tests/test_close_awk_fence_masking.py::test_without_python3_behaviour_is_the_old_behaviour`.
  #
  # No `head -1`/early `exit`: awk reads the whole stream and reports at END.
  # An early `exit` closes the pipe under grep, and a SIGPIPE (141) would be
  # taken by `pipefail` on a bare assignment under `set -e` and abort the run.
  local offset_end
  offset_end=$(tail -n +"$((BATCH_START + 1))" "$TASKS_FILE" | grep -n '^##' \
    | awk -F: -v start="$BATCH_START" -v fenced="$FENCED_LINES" '
        BEGIN {
          n = split(fenced, fz, ",")
          for (i = 1; i <= n; i++) if (fz[i] != "") mask[fz[i] + 0] = 1
        }
        !have && !((start + $1) in mask) { have = 1; off = $1 }
        # `0` is a SENTINEL meaning "ran fine, found no unmasked boundary" -- real
        # offsets are 1-based so it cannot collide. Without it, that outcome and a
        # CRASHED awk both arrive as the empty string, and the guard below treats
        # both as failure. See the note there: that conflation made this whole fix
        # inert for the last batch of any tracker with no trailing `##` section.
        END { if (have) print off; else print 0 }
      ') || offset_end=""
  # `|| offset_end=""` is load-bearing and its absence FAILED THE WHOLE RUN.
  # This is a PIPELINE inside a command substitution on a plain assignment: under
  # `pipefail` the status is awk's, and under `set -e` a non-zero assignment aborts
  # the script. So a filter awk that EXITS non-zero -- a shimmed one, a build
  # without `-v`, an out-of-memory kill -- did not degrade, it killed the close
  # mid-run with a bare shell status. The floor only ever covered an awk that
  # exited 0 with unusable output. Found by writing the test for the floor:
  # `test_the_fence_blind_recompute_actually_recomputes` shims awk to exit 3 and
  # the script returned 3 with the batch half-processed.
  # A broken `awk` must not change this function's control flow.
  #
  # `$(( ))` on a non-numeric operand is a bash SYNTAX ERROR, not a zero, and
  # under `set -euo pipefail` it aborts the run mid-close with a raw shell
  # diagnostic and no verdict. Found by
  # `tests/test_close_batch_sh.py::TestShortWriteGuard`, which shims `awk` with
  # a lying stub: this filter made `find_batch_range` depend on awk for the
  # first time (the pre-existing `grep | head -1 | cut` did not), so a broken or
  # shadowed awk newly reached the arithmetic.
  #
  # The first cut of this guard returned 1 here. That was WRONG twice over: the
  # sole caller renders any non-zero as the FALSE "Not found in review_tasks.md"
  # with a durable `not-found` reason -- the exact laundering `Q-017` is filed
  # about -- and skipping meant the downstream short-write guard, whose whole
  # job is catching a lying awk, never ran. Two guards weakened to protect one.
  #
  # So: fall back to the pre-existing fence-BLIND computation, which is today's
  # shipped behaviour, and let the short-write guard do its job. The fence
  # filter is an improvement layered on top; when it cannot run, the floor is
  # exactly what shipped before it, never worse and never a new refusal.
  # THREE outcomes, not two. Round finding (HIGH, execute lens): the first cut of
  # this guard had only two, and collapsed the wrong pair.
  #
  #   "0"        awk ran and found no UNMASKED boundary -> the batch runs to EOF.
  #   1,2,3...   awk ran and found one -> use it.
  #   ""/garbage awk did not run correctly -> fall back, fence-blind, to what shipped.
  #
  # Treating "no boundary" as failure re-ran the fence-blind grep and restored the
  # exact bug this filter exists to fix -- silently, and *while printing the
  # fence-aware claim*. Reproduced: a non-canonical header whose only `##` is a
  # fenced example, in a tracker with no `## Statistics` section, closed 1 of 3 and
  # left TASK-2/TASK-3 `[ ]` under a `Merged` header. Not exotic: this file's own
  # comment ~150 lines below records that some consumers author no `## Statistics`
  # block at all, so for them it is the LAST BATCH on every close.
  case "$offset_end" in
    0)
      offset_end=""          # no boundary; BATCH_END falls to $total_lines below
      ;;
    ''|*[!0-9]*)
      offset_end=$(tail -n +"$((BATCH_START + 1))" "$TASKS_FILE" | grep -n '^##' | head -1 | cut -d: -f1)
      case "$offset_end" in
        *[!0-9]*) offset_end="" ;;
      esac
      ;;
  esac
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
#
# `-ef` (same device+inode), NOT `==`. `pwd -P` resolves symlinks but NOT CASE:
# `here` comes from `git rev-parse --show-toplevel` (the ON-DISK spelling) while
# `main_root` is derived by cd-ing into the path the caller entered (the ENTERED
# spelling). On a case-insensitive filesystem — every default macOS install —
# `cd ~/projects/repo` and `cd ~/Projects/repo` reach the same directory and
# compare UNEQUAL as strings. The batch-lock sweep below is gated on this, so it
# silently did not run, and the remedy the script itself prints ("released by
# the next close run from main") was unreachable. Reproduced both directions.
close_landed_on_main() {
  local main_root here branch
  main_root="$(resolve_main_root 2>/dev/null)" || return 1
  main_root="$(cd "$main_root" && pwd -P 2>/dev/null)" || return 1
  here="$(cd "$REPO_ROOT" && pwd -P 2>/dev/null)" || return 1
  [[ "$here" -ef "$main_root" ]] || return 1
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

# ── Helper: remove a closed batch's orchestrated-claim artifacts ──
# `/claim-task` claims BATCHES as well as roadmap tasks, and since Phase 171 a
# claim of either kind writes two things outside the worktree, in the MAIN
# checkout so they outlive `git worktree remove`:
#
#   sysop/runtime/claim/BATCH-<N>/<RUN_ID>/   plan.md, review.md, classification.md, ...
#   sysop/runtime/parked/BATCH-<N>__<RUN_ID>.md   the park marker, when 7c parked
#
# **Neither was removed by anything.** `/review-close` Step 4c cleans the
# roadmap half, but its `closed` list is built from `roadmap_ids` only —
# `review_task_ids` are excluded there by design — so no batch id ever reaches
# it. This function is the batch half, sited here rather than taught to Step 4c
# because Step 4c has no batch-id list to iterate and this script already owns
# every other batch-close mutation (the lock above included).
#
# Same `close_landed_on_main` gate as the lock, for the same reason: under `pr`
# policy the close commits on an integration branch while `main` still reads the
# batch `Pending`, and destroying the verdict of a park before the merge lands
# would take the one record explaining why the work stopped.
#
# Reports either way. A removal that is silent when the target is absent cannot
# be told apart from one that never ran — the rule `remove_batch_lock` states
# above, and the reason both of these print an `ℹ️` line on the empty case.
remove_claim_artifacts() {
  local batch_num="$1"
  local main_root claim_dir marker markers_removed=0

  if ! main_root="$(resolve_main_root)"; then
    echo "   ⚠️  Could not resolve the main checkout — claim artifacts for Batch ${batch_num} not removed." >&2
    return 0
  fi

  # `batch_num` reached here through the `^([Bb][Aa][Tt][Cc][Hh]-)?([0-9]+)$`
  # parse and `$((10#...))`, so it is decimal digits and nothing else. Re-assert
  # it anyway: this is the ONLY place in this script that removes a directory
  # rather than a file, and a path component that ever became empty, `.` or `..`
  # would widen the `rm -rf` below from one claim's artifacts to the whole
  # runtime tree. The guard costs one test and closes the entire class.
  if [[ ! "$batch_num" =~ ^[0-9]+$ ]]; then
    echo "   ⚠️  Refusing to remove claim artifacts — batch id '${batch_num}' is not numeric." >&2
    return 0
  fi

  # Park markers first. `-e || -L` rather than bare `-e`: `-e` follows symlinks,
  # so a DANGLING marker symlink would be skipped here while `rm -f` really does
  # remove it — a report that claims to say what this code did, saying the
  # opposite (the same trap `/review-close` Step 4c documents for the lock).
  for marker in "${main_root}/sysop/runtime/parked/BATCH-${batch_num}__"*.md; do
    [[ -e "$marker" || -L "$marker" ]] || continue
    # Report what the `rm` DID, not that it was attempted. The call sites are
    # `remove_claim_artifacts "$n" || true`, so a failing `rm` cannot abort and an
    # unconditional success line turns a read-only parked/ into a silent loss of the
    # one record explaining why the work stopped — reproduced by this phase's round,
    # against this function's own header promising it "reports either way".
    if rm -f "$marker" 2>/dev/null && [[ ! -e "$marker" && ! -L "$marker" ]]; then
      echo "   ✅ Removed park marker $(basename "$marker")"
      markers_removed=$((markers_removed + 1))
    else
      echo "   ⚠️  Could NOT remove park marker ${marker} — left in place." >&2
    fi
  done
  if [[ $markers_removed -eq 0 ]]; then
    echo "   ℹ️  No park markers for Batch ${batch_num}."
  fi

  # Then the per-run artifact directory. `-d` follows symlinks and `rm -rf` on a
  # symlink removes the LINK, not the target — which is the safe direction here.
  claim_dir="${main_root}/sysop/runtime/claim/BATCH-${batch_num}"
  if [[ -d "$claim_dir" || -L "$claim_dir" ]]; then
    if rm -rf "$claim_dir" 2>/dev/null && [[ ! -e "$claim_dir" && ! -L "$claim_dir" ]]; then
      echo "   ✅ Removed claim artifacts ${claim_dir}"
    else
      echo "   ⚠️  Could NOT remove claim artifacts ${claim_dir} — left in place." >&2
    fi
  elif [[ -e "$claim_dir" ]]; then
    # A regular file where a directory belongs. Printing the "never ran the pipeline"
    # line here would state a specific and false cause for something that is still on
    # disk. Say what was found.
    echo "   ⚠️  ${claim_dir} exists but is not a directory — left in place." >&2
  else
    echo "   ℹ️  No claim artifacts at ${claim_dir} (batch never ran the /claim-task pipeline, or already cleaned)."
  fi
}

# ── Process each batch ────────────────────────────────────────
# Q-012: once, before the loop. Re-checking per batch would cost a subprocess
# per iteration to close a window this script cannot open on its own — its own
# mutations are checkbox flips and header status rewrites, none of which can
# introduce a fence. The residual is an external editor writing the tracker
# mid-run, which is named rather than half-guarded.
fence_preflight || exit 1

CLOSED=()
SKIPPED=()
MERGED_UNLOCK=()
TOTAL_TASKS_CLOSED=0
TOTAL_ORPHANS=0
TOTAL_NEARMISSES=0
TOTAL_FALLBACK_RANGES=0

for BATCH_NUM in "${BATCH_NUMS[@]}"; do
  echo "── Batch ${BATCH_NUM} ──"

  # ── Q-037: this script is the OTHER mutator ──────────────────
  #
  # It rewrites review_tasks.md AND commits. `batch_work.sh` refuses an
  # ambiguous number; without this, `close_batch.sh <N>` resolved the same
  # number through `--range`, which keys by number and returns the LAST header,
  # and closed the wrong batch silently. Measured: a tracker with Batch 1 in two
  # rounds closes Round 2 and commits, leaving Round 1 open under an unchanged
  # header — so an operator who merged Round 1 has just marked the wrong work
  # done. No warning was emitted on any stream, because this path calls
  # `--range` rather than `--list`.
  #
  # SKIP rather than exit, with its own explicit reason. The script's contract
  # is to report and continue (`close_batch.sh:1231-1240`: annotation warnings
  # are "deliberately NOT an exit-code change"), so aborting here would
  # abandon the other batches
  # in a multi-batch close. This is not the `find_batch_range` refusal problem —
  # that one is unreachable because its caller overwrites it with a FALSE
  # "Not found" message; this check owns its own message and its own verdict.
  if [[ -n "$FENCED_LINES" || -f "$INDEX_SCRIPT" ]] && command -v python3 &>/dev/null; then
    DUP_ERR=""
    DUP_RC=0
    DUP_ERR=$(python3 "$INDEX_SCRIPT" --check-duplicates "$BATCH_NUM" 2>&1 >/dev/null) \
      && DUP_RC=0 || DUP_RC=$?
    if [[ "$DUP_RC" -eq 4 ]]; then
      echo "$DUP_ERR" >&2
      echo "   ⚠️  Ambiguous batch number. Skipping (nothing was rewritten)."
      SKIPPED+=("${BATCH_NUM}:ambiguous")
      continue
    fi
    # rc 0 with output is the NEAR-MISS advisory (Q-242) — not a refusal, but
    # not something to swallow either. STDOUT here, per this script's own rule
    # that /review-close Step 4b reads stdout; the Python side writes it to
    # stderr so the OTHER caller's capture can see it, and this is where it
    # becomes visible to an operator reading a close.
    if [[ "$DUP_RC" -eq 0 && -n "$DUP_ERR" ]]; then
      echo "$DUP_ERR"
    fi
  fi

  # Find batch header
  if ! find_batch_range "$BATCH_NUM"; then
    echo "   ⚠️  Not found in review_tasks.md. Skipping."
    SKIPPED+=("${BATCH_NUM}:not-found")
    continue
  fi

  # ── Q-017: the fallback range stops being silent ─────────────
  #
  # `find_batch_range` prefers `review_index.py --range` and falls back to a
  # grep when the index cannot answer. On a HEALTHY install the fallback is
  # still reachable — measured: a header spelled with an ASCII hyphen where
  # `_BATCH_HEADER_RE` demands an em-dash is invisible to `--range` and matched
  # by the grep, so this script closes a batch that `batch_work.sh` refuses to
  # claim. That asymmetry is pinned as current behaviour (not endorsed) by
  # `tests/test_batch_range_offset_guard.py::test_close_still_closes_a_header_the_index_cannot_match`.
  #
  # Ratified 2026-08-21: keep closing, stop doing it silently. Retiring the
  # fallback is a caller-contract change this entry has declined three times —
  # a refusal here is overwritten by the FALSE "Not found in review_tasks.md"
  # message directly above, and this script diagnoses by commit presence rather
  # than exit code (`close_batch.sh:1231-1240`). So the honest move is to say which resolver
  # answered, because the two disagree about what a batch IS.
  #
  # STDOUT, not stderr, and that is the file's own rule ~130 lines below: NEARMISS
  # and ORPHAN used to go to stderr while /review-close Step 4b tells the operator
  # to read stdout, so the loudness was "addressed to an empty room".
  #
  # Deliberately NOT an exit-code change — see the summary-counter rule at the
  # end of this file, which states it and says why.
  case "${RANGE_SOURCE:-index}" in
    fallback)
      TOTAL_FALLBACK_RANGES=$((TOTAL_FALLBACK_RANGES + 1))
      echo "   ⚠️  Batch ${BATCH_NUM}'s range came from the GREP FALLBACK, not the index."
      echo "       review_index.py ran and could not match this batch's header, so the"
      echo "       header does not have the canonical shape:"
      echo "         ### Batch <N> — <Title> \`<Status>\`   (em-dash, backticked status)"
      if $FENCED_OK; then
        echo "       The range itself is sound: review_index.py --fenced-lines answered,"
        echo "       so the boundary search skips fenced \`## \` headings (Q-017, Phase 233)."
      else
        echo "       AND the fenced-line probe FAILED, so there is no mask and the range is"
        echo "       fence-blind: a \`## \` heading quoted inside the batch body ends it EARLY,"
        echo "       leaving tasks below open under a \`Merged\` header. Re-run:"
        echo "         python3 sysop/scripts/review_index.py --fenced-lines"
        echo "       to see the error this run discarded."
      fi
      echo "       What is NOT sound is that the readers disagree about this header --"
      echo "       /sitrep and the archiver cannot see it, /next-task offers it, and"
      echo "       batch_work.sh refuses to claim it. Fix the header."
      echo "       This batch WILL still be closed. List every such header with:"
      echo "         python3 sysop/scripts/review_index.py --check-headers"
      ;;
    fallback-no-index)
      TOTAL_FALLBACK_RANGES=$((TOTAL_FALLBACK_RANGES + 1))
      echo "   ⚠️  Batch ${BATCH_NUM}'s range came from the GREP FALLBACK, not the index."
      echo "       review_index.py did NOT run (python3 or ${INDEX_SCRIPT} is missing), so"
      echo "       this says nothing about your header — it is a partial or stale install."
      echo "       Without review_index.py there is no fenced-line mask, so this arm"
      echo "       -- and only this arm -- is still fence-blind: a \`## \` heading quoted"
      echo "       inside the batch body ends the range EARLY, leaving tasks below it"
      echo "       open under a \`Merged\` header. Measured on a 3-task batch: 1 closed,"
      echo "       2 left \`[ ]\`. This batch WILL still be closed."
      echo "       Diagnose with: bash sysop/scripts/self_check.sh"
      ;;
  esac

  # Extract current status from header line. Anchor to end-of-line so a
  # title containing backtick-quoted tokens (e.g. ``Batch 12 — fix `foo`
  # regression `In Progress` ``) yields the *trailing* status token, not
  # the first backtick block on the line.
  #
  # Two guards here, and the file already states the rule for both 40 lines
  # below at the Branch: grep (ISSUE-0044): a `grep -o` that matches nothing
  # exits 1, and under `set -euo pipefail` that aborts the whole run.
  #
  # `|| true` — without it a status the charset could not hold killed the script
  # *before* the `*)` arm written for exactly that case. Measured:
  # `close_batch.sh 1 2 8` with batch 8 at `On-Hold` flipped batches 1 and 2 to
  # `Merged` in the working tree, printed a bare `── Batch 8 ──`, exited 1 with
  # an EMPTY stderr and left review_tasks.md dirty and uncommitted.
  #
  # `[^`]+` not `[A-Za-z ]+` — the charset was the thing doing the killing, and
  # narrowing what a reader can SEE does not narrow what a consumer can WRITE.
  # Whatever sits in the trailing backticks is extracted; the allowlist `case`
  # below is what decides, and it is still the only thing that gates
  # interpolation into the sed patterns.
  BATCH_HEADER=$(sed -n "${BATCH_START}p" "$TASKS_FILE")
  BATCH_STATUS=$(echo "$BATCH_HEADER" | grep -oE '`[^`]+`[[:space:]]*$' | tr -d '`' | sed 's/[[:space:]]*$//' || true)

  if [[ "$BATCH_STATUS" == "Merged" ]]; then
    echo "   ℹ️  Already Merged. Skipping."
    SKIPPED+=("${BATCH_NUM}:already-merged")
    # ...but a Merged batch must not hold a lock. `batch_work.sh --force <N>`
    # lets a Merged batch through for follow-up work and writes one, and every
    # other removal path refuses a Merged batch — so without this the lock is
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
    "")
      # Distinct from an unrecognized status, and distinct in the remedy: there
      # is no value to correct, the header is missing its trailing `status`
      # token altogether. Naming the header is what makes that actionable —
      # `Unrecognized batch status ''` names nothing.
      echo "   ⚠️  No trailing \`status\` token in the Batch ${BATCH_NUM} header. Skipping."
      echo "      header: ${BATCH_HEADER}"
      SKIPPED+=("${BATCH_NUM}:no-status")
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
    # Verify branch is merged into the MERGE TARGET (skip with --force for
    # cherry-picked branches).
    #
    # ── Q-020, the wrong-tree class (Phase 233) ──────────────────────────
    #
    # This asked about the literal `main` while the merge it is verifying lands
    # in whatever branch is checked out. Under `§ Merge policy: pr` those are
    # different revisions: `/review-close` Step 4a merges each batch branch into
    # an INTEGRATION branch cut from `origin/main`, Step 4b runs here with that
    # branch checked out, and the PR is not squashed until Step 4d. So a
    # correctly-merged branch is not an ancestor of local `main` and never will
    # be -- and the skill's own remedy was to mandate `--force` on every
    # `pr`-policy close, which disarms the gate for exactly the consumers it
    # exists to protect. An unmerged branch was indistinguishable from a merged
    # one on the dominant path.
    #
    # Measured on a `pr`-shaped fixture (integration branch cut from main,
    # feature merged in with --no-ff):
    #   merge-base --is-ancestor feat/one main   -> FALSE  (rejects real work)
    #   merge-base --is-ancestor feat/one HEAD   -> TRUE   (correct)
    #   merge-base --is-ancestor feat/never HEAD -> FALSE  (still catches it)
    #
    # `HEAD` first, `main` retained as a fallback. That ordering is deliberately
    # WIDER than the shipped predicate and never narrower: every branch the old
    # code accepted is still accepted, so this cannot introduce a new refusal in
    # any consumer. Under `direct` policy HEAD *is* main and nothing changes.
    #
    # This is what `close_batch.sh` already promises: /review-close Step 4b says
    # it "commits to whatever branch is current". The write target was HEAD all
    # along; only the verification was pointed somewhere else.
    # STRICT containment on the HEAD arm: the branch must be inside HEAD and not BE
    # HEAD. Round finding (HIGH, execute lens) -- the first cut used plain ancestry,
    # and `--is-ancestor X HEAD` is trivially TRUE whenever HEAD sits at the branch
    # tip. Reproduced: checked out on `feat/five`, merged nowhere, `main` does not
    # contain it -- the gate printed `✓ Branch 'feat/five' verified merged.` and
    # flipped the header to `Merged`. The shipped gate refused that. So a widening
    # sold as "cannot introduce a new refusal" had introduced a new ACCEPT, in the
    # one case the check exists for, and `batch_work.sh` puts an operator exactly
    # there: it creates the batch worktree checked out ON the batch branch.
    #
    # `if`, never `[ … ] && return`: this file's own rule ~250 lines above records
    # that a false test in an AND-list returns non-zero and `set -e` kills the run.
    #
    # What this deliberately does NOT accept is the PR-REUSE shape, where HEAD *is*
    # the approved branch. That is not an oversight and not a regression -- the
    # shipped gate refused it too. Before the PR squashes there is genuinely no
    # ancestry evidence that the work landed, and this skill's own Step 6 note says
    # so outright: "After a squash there is no ancestry-shaped containment test."
    # Reuse keeps `--force`, with that as the stated reason.
    _merged_into_target() {
      local head_sha branch_sha
      head_sha="$(git rev-parse HEAD 2>/dev/null)" || head_sha=""
      branch_sha="$(git rev-parse --verify --quiet "$1^{commit}" 2>/dev/null)" || branch_sha=""
      if [[ -n "$head_sha" && -n "$branch_sha" && "$head_sha" != "$branch_sha" ]]; then
        if git merge-base --is-ancestor "$1" HEAD 2>/dev/null; then
          return 0
        fi
      fi
      if git merge-base --is-ancestor "$1" main 2>/dev/null; then
        return 0
      fi
      return 1
    }

    if git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}" 2>/dev/null; then
      if ! _merged_into_target "$BRANCH_NAME"; then
        if $FORCE; then
          echo "   ⚠️  Branch '${BRANCH_NAME}' not ancestor-merged (--force: accepting cherry-pick)."
        else
          echo "   ❌ Branch '${BRANCH_NAME}' is NOT merged into the close target (HEAD) or main. Skipping. (Use --force for cherry-picked branches.)"
          SKIPPED+=("${BATCH_NUM}:unmerged")
          continue
        fi
      else
        echo "   ✓ Branch '${BRANCH_NAME}' verified merged."
      fi
    elif git show-ref --verify --quiet "refs/remotes/origin/${BRANCH_NAME}" 2>/dev/null; then
      if ! _merged_into_target "origin/${BRANCH_NAME}"; then
        if $FORCE; then
          echo "   ⚠️  Remote branch '${BRANCH_NAME}' not ancestor-merged (--force: accepting cherry-pick)."
        else
          echo "   ❌ Remote branch '${BRANCH_NAME}' is NOT merged into the close target (HEAD) or main. Skipping. (Use --force for cherry-picked branches.)"
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
    -v fenced="$FENCED_LINES" \
    "$CLOSE_AWK" "$TASKS_FILE" 2>"$BATCH_DIAG")
  TASKS_IN_BATCH=${BATCH_COUNTS%% *}
  TASKS_FAILED_IN_BATCH=${BATCH_COUNTS##* }

  # Say what was held and what was nearly held. Before this, both directions of
  # the annotation decision were silent: a task held open on a stray quoted
  # `> Failed:` line vanished from the Grand Total with no notice, and an
  # annotation the matcher did not recognise closed the task with its failure
  # note left sitting underneath — the exact rendering internal tracker #207 reported.
  # A dead item and a clean one must not produce identical evidence.
  #
  # ALL THREE GO TO STDOUT, and that is a fix, not a style choice. NEARMISS and
  # ORPHAN used to go to stderr while /review-close Step 4b tells the operator to
  # read stdout — so the one warning that noticed the annotation had failed to
  # protect anything was written to the stream nobody was told to look at. The
  # loudness these lines exist to provide was addressed to an empty room.
  BATCH_ORPHANS=0
  BATCH_NEARMISSES=0
  while IFS=' ' read -r KIND LNO TEXT; do
    case "$KIND" in
      HELD)     echo "   ⏸  held open (line ${LNO}): ${TEXT}" ;;
      NEARMISS) echo "   ⚠️  line ${LNO} looks like a failure note but was NOT recognised — the task above it was CLOSED: ${TEXT}"
                BATCH_NEARMISSES=$((BATCH_NEARMISSES + 1)) ;;
      ORPHAN)   echo "   ⚠️  line ${LNO} is a failure note attached to no open task — it protects nothing: ${TEXT}"
                BATCH_ORPHANS=$((BATCH_ORPHANS + 1)) ;;
      STRAY)    echo "   ⚠️  line ${LNO} looks like a failure note, was NOT recognised, AND is attached to no open task — it protects nothing: ${TEXT}"
                BATCH_ORPHANS=$((BATCH_ORPHANS + 1)) ;;
    esac
  done < "$BATCH_DIAG"
  rm -f "$BATCH_DIAG"
  TOTAL_ORPHANS=$((TOTAL_ORPHANS + BATCH_ORPHANS))
  TOTAL_NEARMISSES=$((TOTAL_NEARMISSES + BATCH_NEARMISSES))

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
    | awk -v s="$BATCH_START" -v e="$BATCH_END" -v mode=flip \
        -v fenced="$FENCED_LINES" "$CLOSE_AWK" > "$TMP_FILE"

  # `pipefail` catches a stage that *reports* failure; it cannot catch one that
  # exits 0 having written short. That is not hypothetical here — the rewrite is
  # a two-process pipeline, so there are two chances for a silent short write,
  # and the `mv` below is unrecoverable. Assert the output is at least as long
  # as the input before installing it.
  #
  # `grep -c ''` on BOTH sides, not `wc -l` (Q-115, fourth site — found by Phase
  # 208's round AFTER that phase had checked this line and wrongly cleared it).
  # The old reasoning was half right: awk does append a final newline, so the
  # count can legitimately grow by one and an equality check would be wrong. What
  # it missed is that `wc -l` also UNDER-reports the *source* by one when the
  # source lacks a trailing newline — which spends the `-lt` slack in the wrong
  # direction. Measured: a 3-line source with no trailing newline (`wc -l` = 2)
  # against output that lost a line but gained a newline (`wc -l` = 2) compares
  # equal, so `-lt` is false and a one-line silent deletion installs through the
  # guard that exists to stop exactly that. Counting real lines removes the slack:
  # 3 vs 2 fires.
  #
  # NOT `awk END{print NR}`, which is this repo's usual line counter. **A guard
  # must not depend on the tool it is guarding against.** The threat here is a
  # lying `awk` in the rewrite pipeline above, and `tests/test_close_batch_sh.py`
  # ::TestShortWriteGuard proves it by shimming one onto PATH — so an awk-based
  # count is computed by the liar and the guard silently stops firing. The first
  # cut of this fix did exactly that and those two tests caught it.
  if [[ ! -s "$TMP_FILE" ]] || \
     [[ "$(grep -c '' "$TMP_FILE")" -lt "$(grep -c '' "$TASKS_FILE")" ]]; then
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
      remove_claim_artifacts "$n" || true
    done
  else
    echo "   ⏸  Close committed on '${CB_BRANCH:-detached HEAD}', not main in the main checkout."
    echo "      Locks kept, and the claim artifacts with them — the batch is not merged yet."
    echo "      A lock removed now would let /next-task re-offer a batch whose work is sitting"
    echo "      on an unmerged branch, and a park verdict removed now would destroy the record"
    echo "      of why the work stopped."
    echo "      Both are released by the next close run from main: bash sysop/scripts/close_batch.sh ${CLOSED[*]}"
  fi
fi

# A batch that is already finished (Merged / Complete / Ready for Review) sheds
# its lock whether or not this run closed anything: `batch_work.sh --force <N>`
# lets a finished batch through for follow-up work and writes a lock (the bare
# form is refused since Phase 191, but the affordance is kept precisely because
# this removal path is what makes it safe), and every other
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
    remove_claim_artifacts "$n" || true
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
# Per-line warnings scroll; a count in the summary does not. An operator reading
# only the tail of a 20-batch run still learns that some annotation somewhere
# protected nothing — which is the state that lost six tasks in the reported
# round. This is deliberately NOT an exit-code change: /review-close Step 4b
# diagnoses failure by commit absence, and a non-zero exit after a successful
# commit is a state its prose does not cover.
if [[ $TOTAL_ORPHANS -gt 0 ]]; then
  echo "   ⚠️  Annotations protecting nothing: ${TOTAL_ORPHANS} (see the per-line warnings above)"
fi
if [[ $TOTAL_NEARMISSES -gt 0 ]]; then
  echo "   ⚠️  Failure-note near misses not honoured: ${TOTAL_NEARMISSES} (see the per-line warnings above)"
fi
# Same argument as the two counters above: per-batch warnings scroll, a summary
# count does not. An operator reading only the tail of a 20-batch run still
# learns that some batch was closed on a range the index could not produce.
if [[ $TOTAL_FALLBACK_RANGES -gt 0 ]]; then
  # The cause is split two ways and this line must not pick one. The counter is
  # incremented by BOTH arms: `fallback` (the index ran and could not match the
  # header) and `fallback-no-index` (python3 or the index script is missing,
  # which says nothing about the header). Asserting "not canonical" here told
  # an operator with a byte-perfect tracker and no python3 that their header was
  # malformed -- the same wrong-cause conflation Phase 220's round fixed in the
  # per-batch message above and left standing in this line.
  echo "   ⚠️  Batches closed via the grep fallback: ${TOTAL_FALLBACK_RANGES} (see the per-batch warnings above for which cause applied)"
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
