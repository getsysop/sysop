#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# cleanup_worktrees.sh — List and clean up git worktrees.
#
# Usage:
#   bash sysop/scripts/cleanup_worktrees.sh            # List all worktrees with status
#   bash sysop/scripts/cleanup_worktrees.sh --clean    # Remove merged/stale worktrees (ACTIVE skipped)
#   bash sysop/scripts/cleanup_worktrees.sh --force    # Remove ALL non-main worktrees, ACTIVE included
#
# There is NO path operand — every mode here acts on the whole worktree set.
# To remove ONE worktree:
#   git worktree remove <path>                            # refuses on uncommitted or untracked
#                                                         #   changes — but NOT on gitignored ones;
#                                                         #   it deletes sysop/runtime/ content
#                                                         #   without asking (measured)
#   bash sysop/scripts/claim_task.sh --release <TASK_ID>  # also releases the lock and flips the status
#   bash sysop/scripts/batch_work.sh --release <N>        # the review-batch equivalent
#
# What this script does and does not touch: it removes worktrees, deletes their
# branches with the safe `git branch -d` (both modes), and runs `git worktree
# prune` (every mode, including the bare listing one — so even a "list" run
# mutates the worktree admin DB). It READS `sysop/runtime/locks/` and never
# writes it: a claimed worktree is ACTIVE, and one `--force` removes leaves its
# `<ID>.lock` behind, with the release command printed.
#
# Classification:
#   MAIN   — the repo's PRIMARY worktree (never touched). Resolved via
#            git-common-dir, so it is the same worktree no matter which one
#            this script is run from.
#   MERGED — branch is ancestor of the default branch (safe to remove)
#   ACTIVE — has uncommitted changes, holds sysop/runtime/ artifacts,
#            contains another worktree's directory, or is claimed by a lock
#            (skipped by --clean)
#   STALE  — directory missing (pruned automatically)
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

# ── The primary checkout ─────────────────────────────────────────
# `--show-toplevel` answers with the CWD's worktree, not the repo's primary, so
# a run from inside a linked worktree labelled THAT worktree MAIN — and let the
# real primary fall through to MERGED, not ACTIVE, because main is trivially an
# ancestor of main. `--clean` then skipped the worktree it was pointed at and
# targeted the primary instead; git refuses (`fatal: … is a main working tree`),
# so nothing was ever lost, but the run exited 1 having cleaned nothing.
#
# That was the prescribed path, not an edge case: `batch_work.sh`'s claim summary
# box prints `cd ${WORKTREE_DIR}` under "Next steps" and names this script a few
# lines below it as the cleanup command, so an operator following those steps in
# one shell hit it every time.
#
# Cited by NAME rather than by line on purpose. Phase 256 re-pointed these two
# anchors three times in one phase as `batch_work.sh` grew, which is the signal
# `tests/test_intra_repo_citations.py` exists to produce and the point at which
# its own guidance says to stop citing lines. `grep -n 'Next steps' batch_work.sh`
# finds the block in one command.
#
# Resolution, and why it is deliberately NOT the
# `dirname "$(git rev-parse --git-common-dir)"` idiom five sibling SHELL scripts use
# for the LOCK path (batch_work, claim_task, close_batch, run_checks, self_check;
# shipped Python scripts use it too — `git grep -l -e --git-common-dir --
# 'core/companion/scripts/*.py'` lists them; install_hooks.sh names the idiom only to reject it, since
# `--git-common-dir`/hooks ignores core.hooksPath, which is why Q-307 said six):
# that arithmetic is correct only when the git dir is literally
# `<root>/.git`. Measured in this phase's own review round — inside a submodule it
# yields `<super>/.git/modules/<name>`, and under `git init --separate-git-dir` it
# yields the git dir's PARENT. Both are real directories, so an existence check
# passes and the wrong answer is used: the first re-rooted this whole script at the
# SUPERPROJECT and removed ITS worktrees, `--force` destroying uncommitted work in
# one; the second killed even a read-only `list` run at exit 128, where it had
# exited 0 before this phase touched it.
#
# So narrow the question to the single case the defect lives in. `--git-dir` and
# `--git-common-dir` are equal exactly when the caller IS the primary — true of a
# plain checkout, a submodule and a separate-git-dir layout alike — and differ only
# from inside a linked worktree. Only then is the primary somebody else, and it is
# `git worktree list --porcelain`'s FIRST entry, which git documents as the main
# worktree and which is the very list `classify_worktree` compares against, so the
# two cannot disagree about how a path is spelled. A first entry marked `bare` means
# there is no main working tree at all; protect the caller's own, as before.
#
# Fail closed. Every mode below decides what it must never touch by comparing
# against this value, so an unanswerable probe means the script cannot tell the
# primary from a linked worktree at the moment it is about to remove worktrees.
# `claim_task.sh`'s `--entry-state` block exits on the same class of failure for
# the same reason — cited by NAME, not by line: the line numbers moved when
# Phase 261 added `--commit-claim`, and a pinned range is a citation that goes
# stale on any edit above it.
#
# ── Reading `git worktree list` ───────────────────────────────
# Both readers of the list — the primary probe just below and the collection
# loop further down — read it through `worktree_list_nul`, which prints one
# porcelain line per NUL-terminated field. Plain `--porcelain` is newline-
# separated and does NOT quote a newline inside a path (measured on git 2.50.1),
# so a worktree at `…/wt\nx` was read as the path `…/wt`: it classified STALE,
# and `--clean` exited 1 on `fatal: '…/wt' is not a working tree`. That failed
# safe — nothing was removed — but it also never reclaimed the worktree, and a
# truncated path that happens to name ANOTHER worktree is classified and removed
# as if it were this record's.
#
# `-z` is the fix git itself shipped for this (2.36 release notes: porcelain
# "did not c-quote pathnames … with unsafe bytes correctly", worked around "by
# introducing NUL terminated output format with -z"). This repo states no
# minimum git version (`_git_lib.sh` says so where it avoids
# `--absolute-git-dir`), so `-z` is probed once rather than assumed, and an
# older git gets today's newline parse translated into the same NUL stream —
# its exact pre-fix behaviour, newline paths included, through one parser. The
# probe is a separate call because a NUL-separated answer cannot be captured in
# a shell variable: command substitution drops the NULs.
#
# The trailing `printf '\0'` is the flush the collection loop's `echo ""` used to
# be: it guarantees the last record is followed by an empty field, which is what
# closes a record.
WT_LIST_NUL=0
if git -C "$REPO_ROOT" worktree list --porcelain -z >/dev/null 2>&1; then
  WT_LIST_NUL=1
fi
worktree_list_nul() {
  if [[ "$WT_LIST_NUL" == 1 ]]; then
    git -C "$1" worktree list --porcelain -z
  else
    git -C "$1" worktree list --porcelain | tr '\n' '\0'
  fi
  printf '\0'
}

MAIN_ROOT="$REPO_ROOT"
_git_dir="$(git -C "$REPO_ROOT" rev-parse --git-dir 2>/dev/null)" || _git_dir=""
_common_dir="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null)" || _common_dir=""
if [[ -z "$_git_dir" || -z "$_common_dir" ]]; then
  echo "❌ git rev-parse could not describe this checkout — cannot tell the primary" >&2
  echo "   from a linked worktree, and every mode here decides what to skip on that." >&2
  exit 1
fi
# Both answers come from the same `-C`, so a plain string compare is enough and no
# absolutising is needed — which also keeps this off `--path-format`, a flag older
# git does not have.
if [[ "$_git_dir" != "$_common_dir" ]]; then
  # The first record only: its `worktree` line, and whether it is marked `bare`.
  _primary=""
  _primary_bare=""
  _records=0
  while IFS= read -r -d '' _field; do
    if [[ "$_field" =~ ^worktree[[:space:]]+(.*) ]]; then
      _records=$((_records + 1))
      if [[ $_records -gt 1 ]]; then
        break
      fi
      _primary="${BASH_REMATCH[1]}"
    elif [[ "$_field" == "bare" ]]; then
      _primary_bare="bare"
    fi
  done < <(worktree_list_nul "$REPO_ROOT" 2>/dev/null)
  if [[ -z "$_primary" ]]; then
    echo "❌ git worktree list named no worktree — refusing to guess which checkout" >&2
    echo "   must never be removed." >&2
    exit 1
  fi
  [[ "$_primary_bare" == "bare" ]] || MAIN_ROOT="$_primary"
fi
if [[ ! -d "$MAIN_ROOT" ]]; then
  echo "❌ Resolved primary checkout '${MAIN_ROOT}' is not a directory." >&2
  exit 1
fi

# ── The default branch (`Q-365`) ──────────────────────────────
# `classify_worktree` hard-coded `main` as the branch a worktree's branch had to
# be an ancestor of, and both removal modes hard-coded it as the one branch
# never to `git branch -d`. On a `master`-default repo `--is-ancestor X main`
# errors, the error is swallowed, and every worktree classified ACTIVE — so
# `--clean` reclaimed nothing and said nothing. Required in every mode, like
# the primary-checkout probe above: the listing's MERGED/ACTIVE column is the
# same predicate the removal modes act on, and a listing that cannot compute
# it would print a verdict it does not have.
_SYSOP_GIT_LIB="$(dirname "${BASH_SOURCE[0]}")/_git_lib.sh"
# `-f`/`-r` before `source` (Phase 368): under `set -e`, bash 3.2 (macOS's
# /bin/bash) exits on a failed `source` of a missing or unreadable file before the
# `||` arm runs, so the remedy below printed only on bash 4+.
{ [[ -f "$_SYSOP_GIT_LIB" && -r "$_SYSOP_GIT_LIB" ]] && source "$_SYSOP_GIT_LIB"; } || {
  echo "❌ _git_lib.sh is missing or unreadable beside cleanup_worktrees.sh — it ships with every install." >&2
  echo "   Restore the scripts directory: bash sysop/scripts/sysop-update.sh" >&2
  exit 1
}
DEFAULT_BRANCH="$(require_default_branch "$MAIN_ROOT")" || exit 1

# Anchor the process at the primary before anything removes a directory. A
# worktree is removable while it IS the current directory — git exits 0 and
# deletes it (measured) — and the bare `git worktree prune` closing each
# removal mode then dies `fatal: Unable to read current working directory`,
# exit 128, under `set -e`: after the removals, so the run reports nothing it
# did. Every path used below is absolute or `git -C`-anchored, so this changes
# no other behaviour. `$REPO_ROOT` is kept as the invocation's own worktree —
# the removal modes report when that is the one they just deleted.
cd "$MAIN_ROOT"

ACTION="${1:-list}"

# ── Refuse a path operand ─────────────────────────────────────
# Only $1 is ever read, and every mode acts on ALL worktrees. So a caller who
# writes `--force <path>` meaning "remove that one orphan" silently gets "remove
# every non-main worktree, uncommitted work included".
#
# Honest scoping of what this guard is worth: the three skill sites that
# prescribed `--force` as a single-orphan rollback until Phase 165 wrote it BARE,
# with the targeting only in their prose ("on the orphan", "to drop it") — and the
# bare form destroys exactly as much, so this check does not block the shape they
# used. What closed that defect was reshaping those sites and the § 8.4 row. This
# is defence-in-depth against the natural next move of a reader who believes such
# prose: appending the path. Cheap, fails closed, and no legitimate caller pays.
if [[ $# -gt 1 ]]; then
  echo "❌ cleanup_worktrees.sh takes no path operand (got: ${2})." >&2
  echo "   Every mode here acts on ALL worktrees. To remove ONE worktree:" >&2
  echo "     git worktree remove <path>                              # refuses on uncommitted work — but NOT" >&2
  echo "                                                             #   on gitignored sysop/runtime/ content" >&2
  echo "     bash sysop/scripts/claim_task.sh --release <TASK_ID>    # also releases the lock + flips the status" >&2
  echo "     bash sysop/scripts/batch_work.sh --release <N>          # the review-batch equivalent" >&2
  exit 1
fi

# ── Prune stale worktrees first ───────────────────────────────
# Surface stderr so prune failures (corrupt worktree DB, permission errors)
# are visible — silently no-oping leaks STALE entries into the classifier.
git worktree prune

# ── Parse worktree list ───────────────────────────────────────
# git worktree list --porcelain gives structured output, one field per line
# (per NUL-terminated field as `worktree_list_nul` delivers it):
#   worktree /path
#   HEAD <sha>
#   branch refs/heads/<name>
#   (empty field — ends the record)

# ── Helper: Sysop runtime artifacts held INSIDE a worktree ────
# Every other probe in this script — `status --porcelain` below, `ls-files
# --others --exclude-standard` in the classifier — EXCLUDES gitignored content,
# and `sysop/runtime/` is gitignored by construction: it is the first of the three
# entries `install.sh`'s `ensure_runtime_gitignore` appends (see that function; the
# others are `.claude/review_index.json` and `sysop/**/__pycache__/`). So the park record
# `/auto-build` writes inside the worktree — `sysop/runtime/auto-build/review.md`,
# and before Phase 344 `plan.md` beside it — was invisible to all of them. A parked task's branch carries
# no commit, which makes it an ancestor of main, which classifies MERGED: the
# record was removed by `--clean`, with its deliberately non-force
# `git worktree remove`, without any refusal at all (Q-023, reproduced end to end).
#
# Scope is `sysop/runtime/` and NOTHING wider, deliberately. Counting all ignored
# content would classify nearly every real worktree ACTIVE — venvs, build output
# and node_modules are all ignored — so `--clean` would refuse on the common case.
# That is the same cry-wolf failure the `--force` warning below had to be reshaped
# to avoid in Phase 165, and keying the classifier on all ignored content would
# have reintroduced it one level up. Note what that means: the probe scope is
# NARROWER than the installer's ignore scope, deliberately — `sysop/**/__pycache__/`
# is ignored inside a worktree's `sysop/` tree and is not counted here, because
# bytecode is not work. So these are two lists, and they can drift; what stops the
# drift mattering is that only the runtime home holds anything unrecoverable.
#
# A pathspec matching nothing is not an error: `ls-files` exits 0 with empty
# output when the directory is absent, which is the common case. `| head -1`
# matches the existing untracked probe — this is an existence test, not a listing.
worktree_runtime_artifacts() {
  local wt_path="$1"
  git -C "$wt_path" ls-files --others --ignored --exclude-standard \
    -- 'sysop/runtime/' 2>/dev/null | head -1
}

# ── Helper: did we just delete the caller's own directory? ────
# The removal modes are anchored at the primary (see the `cd` above), so the run
# itself survives — but the caller's shell does not follow, and a prompt sitting
# in a deleted directory reports confusing errors for every later command. This
# is reachable on the prescribed path, not a corner: `batch_work.sh` tells the
# operator to `cd` into the worktree and then to run this script.
note_if_invocation_worktree() {
  local wt_path="$1"
  [[ "$wt_path" == "$REPO_ROOT" ]] || return 0
  echo "   ℹ️  That was the worktree you invoked from — this shell's directory is"
  echo "      now gone. cd ${MAIN_ROOT} (or anywhere) before running more commands."
}

# ── Helper: another registered worktree INSIDE this one ───────
# `git worktree remove` deletes the whole directory, and a worktree nested in
# another's gitignored subdirectory (`git worktree add <A>/.claude/worktrees/x`
# is the natural way to get one) is invisible to every content probe here —
# git sees an ignored directory, not a repository. Before this arm, `--clean`
# classified the parent MERGED, removed it, and took the child's working tree
# with it, uncommitted work included — while printing `Skipping ACTIVE
# worktree` for that same child, because the child was classified before
# anything was removed (reproduced end to end). Checked against the list git
# itself printed, so both sides are spelled the same way: git records a
# worktree's resolved path, so a child added through a symlink is still seen
# under its real parent (measured). Prints the first nested path found whose
# directory still exists; one already removed earlier in the loop has nothing
# left to lose. **Its reach is the registered list, not the disk** (the round's
# lens 1): a nested worktree whose `.git` file was deleted is pruned by the
# opening `git worktree prune`, so it is not in `WT_PATHS`, its parent can
# classify MERGED, and `--clean` removes the directory with the child's files in
# it — where a top-level worktree in the same state is pruned and left on disk.
# Reaching it means someone deleted a `.git` file by hand; it is stated, not
# probed, because walking every directory for orphaned work is the all-ignored-
# content scope the runtime probe above rejects.
worktree_nested_worktree() {
  local wt_path="$1" other
  for other in "${WT_PATHS[@]}"; do
    if [[ "$other" == "$wt_path"/* && -d "$other" ]]; then
      printf '%s\n' "$other"
      return 0
    fi
  done
  return 0
}

# ── Claims: the locks under sysop/runtime/locks/ (`Q-120`) ────
# A fresh claim's branch has no commit of its own, so it is an ancestor of the
# default branch and classified MERGED: `--clean` removed a worktree
# `claim_task.sh --lock` had just made, right after `/auto-build` Step 5, and
# left the task `in_progress` with its lock and nowhere to work (reproduced in
# Phase 392's round). So a worktree a lock names is ACTIVE.
#
# The directory is resolved as the writers resolve it — the parent of the
# absolute git common dir (`claim_task.sh`, `batch_work.sh`'s
# `resolve_locks_dir`) — not from `$MAIN_ROOT`, which this script resolves
# differently on purpose (see the primary probe above). The two agree on a plain
# checkout; under `--separate-git-dir` or in a submodule they do not, and the
# writers' location is the one a lock is in (`Q-682`).
#
# A lock names its worktree twice, and either key matches: `branch:` (a
# `refs/heads/` prefix stripped) and `workspace:`, compared with `-ef` so a
# symlinked or differently spelled path still matches the path git lists.
# A lock this run cannot read could name any worktree, so `--clean` refuses
# before removing anything; the listing and `--force` say so and go on.
#
# Not covered: `claim_task.sh` adds the worktree before it writes the lock, so a
# `--clean` from another session in that window still sees no claim.
# The first `branch:` and `workspace:` values, one per line. A value is read as
# YAML would read a scalar: one pair of matching quotes removed, or else a
# trailing ` # comment` dropped; trailing whitespace and a CR are stripped.
_LOCK_KEYS_AWK='
function val(s) {
  sub(/^[^:]*:[ \t]*/, "", s); sub(/[ \t\r]+$/, "", s)
  if (length(s) >= 2 && (s ~ /^".*"$/ || s ~ ("^" q ".*" q "$"))) s = substr(s, 2, length(s) - 2)
  else sub(/[ \t]+#.*$/, "", s)
  return s
}
/^branch:/ && !hb { b = val($0); hb = 1 }
/^workspace:/ && !hw { w = val($0); hw = 1 }
END { print b; print w }'
LOCK_IDS=()
LOCK_BRANCHES=()
LOCK_WORKSPACES=()
LOCKS_UNREADABLE=""
LOCKS_DIR=""
if _locks_common="$(git_common_dir_abs "$MAIN_ROOT")"; then
  LOCKS_DIR="$(dirname "$_locks_common")/sysop/runtime/locks"
else
  LOCKS_UNREADABLE="the git common dir of ${MAIN_ROOT} could not be resolved"
fi
if [[ -n "$LOCKS_DIR" && -e "$LOCKS_DIR" ]]; then
  if [[ ! -d "$LOCKS_DIR" || ! -r "$LOCKS_DIR" || ! -x "$LOCKS_DIR" ]]; then
    LOCKS_UNREADABLE="${LOCKS_DIR} is not a readable directory"
  else
    for _lock in "$LOCKS_DIR"/*.lock; do
      [[ -e "$_lock" ]] || continue
      # One read of both keys, so a lock released between the tests and the read
      # (a concurrent `--release` or close) is one failed read, not two. A lock
      # that is gone names nothing and is skipped; one still present that cannot
      # be read is unreadable.
      if [[ ! -f "$_lock" || ! -r "$_lock" ]] \
         || ! _kv="$(awk -v q="'" "$_LOCK_KEYS_AWK" "$_lock" 2>/dev/null)"; then
        [[ -e "$_lock" ]] && LOCKS_UNREADABLE="${_lock} is not a readable file"
        continue
      fi
      { IFS= read -r _lb; IFS= read -r _lw; } <<<"$_kv" || true
      LOCK_IDS+=("$(basename "$_lock" .lock)")
      LOCK_BRANCHES+=("${_lb#refs/heads/}")
      LOCK_WORKSPACES+=("$_lw")
    done
  fi
fi

# Prints the id of the first lock naming this worktree; prints nothing if none.
worktree_lock_id() {
  local wt_path="$1" wt_branch="$2" i
  for i in "${!LOCK_IDS[@]}"; do
    if [[ -n "$wt_branch" && "${LOCK_BRANCHES[$i]}" == "$wt_branch" ]] \
       || [[ -n "${LOCK_WORKSPACES[$i]}" && "${LOCK_WORKSPACES[$i]}" -ef "$wt_path" ]]; then
      printf '%s\n' "${LOCK_IDS[$i]}"
      return 0
    fi
  done
  return 0
}

# The command that releases a lock: a batch's is `batch_work.sh`'s, because it
# also reverts review_tasks.md, and `claim_task.sh --release` refuses one.
lock_release_command() {
  local id="$1"
  if [[ "$id" =~ ^[Bb][Aa][Tt][Cc][Hh]-([0-9]+)$ ]]; then
    printf 'bash sysop/scripts/batch_work.sh --release %s\n' "$((10#${BASH_REMATCH[1]}))"
  else
    # `%q`: the id is a file name, and this line is printed to be pasted.
    printf 'bash sysop/scripts/claim_task.sh --release %q\n' "$id"
  fi
}

classify_worktree() {
  local wt_path="$1"
  local wt_branch="$2"
  local main_branch="$DEFAULT_BRANCH"

  # The primary worktree. `$MAIN_ROOT`, never `$REPO_ROOT`: the latter is
  # whichever worktree the caller happened to be standing in, which is how this
  # arm used to crown a linked worktree and demote the real primary to MERGED.
  if [[ "$wt_path" == "$MAIN_ROOT" ]]; then
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

  # Holds Sysop runtime artifacts? Gitignored, so both probes above are blind to
  # them. This arm has to sit BEFORE the MERGED check, because MERGED is exactly
  # the verdict it exists to prevent: a parked worktree's branch has no commit of
  # its own, so it is an ancestor of main and would be reclaimed as safe.
  if [[ -n "$(worktree_runtime_artifacts "$wt_path")" ]]; then
    echo "ACTIVE"
    return
  fi

  # Holds another registered worktree? Removing this one would delete that one's
  # directory too, whatever that one's own class — see the helper. Before MERGED
  # for the same reason as the arm above.
  if [[ -n "$(worktree_nested_worktree "$wt_path")" ]]; then
    echo "ACTIVE"
    return
  fi

  # Claimed by a lock? Before MERGED, because a fresh claim IS merged — see the
  # lock collection above.
  if [[ -n "$(worktree_lock_id "$wt_path" "$wt_branch")" ]]; then
    echo "ACTIVE"
    return
  fi

  # Branch merged into the default branch?
  if [[ -n "$wt_branch" ]] && git merge-base --is-ancestor "refs/heads/$wt_branch" "$main_branch" 2>/dev/null; then
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

# Two passes: collect every record, THEN classify. The nested-worktree arm needs
# the whole list, and a record classified mid-parse could only see the ones
# before it.
while IFS= read -r -d '' line; do
  if [[ "$line" =~ ^worktree[[:space:]]+(.*) ]]; then
    current_path="${BASH_REMATCH[1]}"
  elif [[ "$line" =~ ^branch[[:space:]]+refs/heads/(.*) ]]; then
    current_branch="${BASH_REMATCH[1]}"
  elif [[ -z "$line" && -n "$current_path" ]]; then
    WT_PATHS+=("$current_path")
    WT_BRANCHES+=("$current_branch")
    current_path=""
    current_branch=""
  fi
done < <(worktree_list_nul "$MAIN_ROOT")

for i in "${!WT_PATHS[@]}"; do
  WT_CLASSES+=("$(classify_worktree "${WT_PATHS[$i]}" "${WT_BRANCHES[$i]}")")
done

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

    # Shorten path for display. A newline in a path (legal, and parsed whole
    # since Phase 368) would split the table row, so it is shown as `?` here only.
    display_path="${wt_path/$HOME/~}"
    display_path="${display_path//$'\n'/?}"
    printf "│ %s%-5s │ %-26s │ %-26s │\n" "$icon" "$wt_class" "${wt_branch:0:26}" "${display_path: -26}"
  done

  echo "└────────┴────────────────────────────┴────────────────────────────┘"
  echo ""
  echo "Legend: 🏠 MAIN (never removed) · ✅ MERGED (safe to clean) · 🔵 ACTIVE (has changes) · 💀 STALE (pruned)"
  if [[ -n "$LOCKS_UNREADABLE" ]]; then
    echo "⚠️  Claims could not be read (${LOCKS_UNREADABLE}): a claimed worktree may be listed MERGED."
  fi
  exit 0
fi

# ── Mode: --clean ─────────────────────────────────────────────
if [[ "$ACTION" == "--clean" ]]; then
  if [[ -n "$LOCKS_UNREADABLE" ]]; then
    echo "❌ Claims could not be read (${LOCKS_UNREADABLE})." >&2
    echo "   A claimed worktree reads MERGED until its first commit, so --clean would remove" >&2
    echo "   live claims. Nothing was removed. Fix the lock directory, or remove one worktree" >&2
    echo "   with git worktree remove <path>." >&2
    exit 1
  fi
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
      nested="$(worktree_nested_worktree "$wt_path")"
      if [[ -n "$nested" ]]; then
        echo "   ℹ️  It contains another worktree (${nested}); removing it would delete that one too."
      fi
      lock_id="$(worktree_lock_id "$wt_path" "$wt_branch")"
      if [[ -n "$lock_id" ]]; then
        echo "   ℹ️  It is claimed (${lock_id}.lock). To drop the claim: $(lock_release_command "$lock_id")"
      fi
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
        note_if_invocation_worktree "$wt_path"
      else
        echo "   ⚠️  Failed to remove worktree at ${wt_path} (re-run with --force to override)"
        FAILED=$((FAILED + 1))
        continue
      fi

      # Delete merged branch (safe -d, not -D)
      if [[ -n "$wt_branch" && "$wt_branch" != "$DEFAULT_BRANCH" ]]; then
        git branch -d "$wt_branch" 2>/dev/null && \
          echo "   🌿 Deleted merged branch: ${wt_branch}" || \
          echo "   ℹ️  Branch '${wt_branch}' not deleted (not fully merged or still in use)"
      fi
    fi
  done

  # This closing prune has NO deterministic observer, and a mutation run measured that
  # deleting it fails nothing — so this says why it stays rather than leaving the
  # next reader to infer coverage. Every admin entry the loop could leave behind
  # is ACTIVE (directory intact), locked (prune skips locked entries), or a
  # corrupt-pointer STALE whose removal failed (directory and `.git` file intact,
  # so not prunable); and `git worktree remove` on an already-missing directory
  # exits 0 and clears its own entry (measured), so a removal leaves nothing to
  # prune either. The one single-process route to a prunable leftover — a
  # worktree nested in a removed one's directory — is closed by the nested arm in
  # `classify_worktree`. What remains is a directory deleted by another process
  # mid-run, which § 4.4's concurrent sessions make possible and no test here can
  # stage. Cheap, idempotent, and it leaves the admin DB as `list` would show it.
  git worktree prune
  echo ""
  echo "Done. Removed ${REMOVED} worktree(s), skipped ${SKIPPED} active, ${FAILED} failed."
  [[ $FAILED -gt 0 ]] && exit 1
  exit 0
fi

# ── Mode: --force ─────────────────────────────────────────────
if [[ "$ACTION" == "--force" ]]; then
  echo "⚠️  Force-removing ALL non-main worktrees..."
  if [[ -n "$LOCKS_UNREADABLE" ]]; then
    echo "⚠️  Claims could not be read (${LOCKS_UNREADABLE}): a removed worktree's lock is not named below."
  fi
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

    # `--force` deliberately does NOT inherit `--clean`'s ACTIVE skip — that is
    # the whole point of the flag, and skipping would leave no way to do what it
    # advertises. But a destructive op that is silent about its blast radius is
    # the other half of the Phase 165 defect, so name the loss as it happens.
    #
    # Ask git directly rather than keying on `$wt_class`: ACTIVE is the
    # classifier's *fallthrough* (`classify_worktree` returns it for anything
    # not MAIN/STALE/MERGED), so a pristine worktree on an unmerged branch and a
    # pristine detached HEAD are both ACTIVE with nothing to lose. Keying on the
    # class made this warning fire on every clean unmerged worktree — including
    # the /auto-build EXECUTED ones whose work is safely committed — and a
    # warning that cries wolf on the common case is one operators learn to skip.
    # `status --porcelain` covers modified, staged and untracked; it does NOT
    # count gitignored content. That half is reported on its own line below.
    if [[ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null)" ]]; then
      echo "🗑️  Removing worktree with UNCOMMITTED WORK — it will be LOST: ${wt_path} (${wt_branch})"
    else
      echo "🗑️  Removing: ${wt_path} (${wt_branch})"
    fi

    # The gitignored half of the blast radius (Q-023). A SEPARATE line rather
    # than a third arm of the branch above, because these are two independent
    # losses with different remedies — a worktree can hold both, one, or neither,
    # and folding them together would make one of them unreportable.
    #
    # Do NOT upgrade "may exist" to a promise. `/auto-build` writes the
    # project-root mirror in Phase 6d, but a Phase 6a park (a planner commit or a
    # missing plan) writes `review.md` and then skips 6b-6e outright, so that path leaves no
    # mirror and the in-worktree copy is the only record that the run ever
    # existed. `--force` cannot tell the two parks apart, so it must not claim
    # a survivor it has not seen.
    #
    # And the two classes need SEPARATE pointers, because `sysop/runtime/parked/`
    # structurally never holds a pending-doc — that directory is the park archive.
    # An earlier version of this message offered it as the recovery location for
    # everything the warning fires on, which sent an operator who had just lost a
    # branch's documentation to a directory that could not contain it.
    if [[ -n "$(worktree_runtime_artifacts "$wt_path")" ]]; then
      echo "   ⚠️  Also holds sysop/runtime/ artifacts — the in-worktree copy will be LOST."
      echo "      A parked task's review.md: a mirror may exist under"
      echo "      sysop/runtime/parked/ at the project root — not every park writes one."
      echo "      A pending-doc: NOT mirrored anywhere until /review-close Step 3b"
      echo "      collects it at merge time. Check the worktree before you confirm."
    fi
    # A worktree nested inside this one goes with it, before its own turn in this
    # loop comes — so its own UNCOMMITTED WORK line, computed then against a
    # directory already gone, would never print. Name it here instead.
    nested="$(worktree_nested_worktree "$wt_path")"
    if [[ -n "$nested" ]]; then
      echo "   ⚠️  Contains another worktree (${nested}) — its directory, and any"
      echo "      uncommitted work in it, will be LOST with this one."
    fi
    lock_id="$(worktree_lock_id "$wt_path" "$wt_branch")"
    if git worktree remove --force "$wt_path"; then
      REMOVED=$((REMOVED + 1))
      note_if_invocation_worktree "$wt_path"
      # The lock and the claimed status stay behind: this script writes neither.
      if [[ -n "$lock_id" ]]; then
        echo "   ⚠️  It was claimed (${lock_id}.lock); the claim is still recorded. Release it:"
        echo "      $(lock_release_command "$lock_id")"
      fi
    else
      echo "   ⚠️  Failed to remove worktree at ${wt_path}"
      FAILED=$((FAILED + 1))
      continue
    fi

    if [[ -n "$wt_branch" && "$wt_branch" != "$DEFAULT_BRANCH" ]]; then
      git branch -d "$wt_branch" 2>/dev/null && \
        echo "   🌿 Deleted branch: ${wt_branch}" || \
        echo "   ℹ️  Branch '${wt_branch}' not deleted (not fully merged)"
    fi
  done

  # Defence for a directory deleted by another process mid-run; see the matching
  # prune closing `--clean` for why nothing in the loop itself leaves one. Here
  # the nested arm does not apply (`--force` ignores the class), but a nested
  # worktree whose directory went with its parent still gets its own turn, and
  # `git worktree remove --force` on a missing directory exits 0 and clears it.
  git worktree prune
  echo ""
  echo "Done. Force-removed ${REMOVED} worktree(s), ${FAILED} failed."
  [[ $FAILED -gt 0 ]] && exit 1
  exit 0
fi

echo "❌ Unknown action: ${ACTION}" >&2
echo "Usage: cleanup_worktrees.sh [--clean | --force]" >&2
echo "   No path operand — every mode acts on ALL worktrees. For one worktree:" >&2
echo "   git worktree remove <path>, or" >&2
echo "   bash sysop/scripts/claim_task.sh --release <TASK_ID> (also releases the lock)." >&2
exit 1
