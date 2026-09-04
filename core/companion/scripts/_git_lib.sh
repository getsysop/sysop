#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# _git_lib.sh — shared git primitives for the lifecycle scripts.
#
# SOURCED, never executed. Underscore-prefixed like `_log.py`: a private helper
# with no entry point. `batch_work.sh`, `close_batch.sh` and
# `cleanup_worktrees.sh` source it from their own directory:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/_git_lib.sh" || exit 1
#
# and each fails LOUD when it is missing (the message names sysop-update.sh),
# rather than falling back to an inline copy. Every other shared piece of shell
# in this tree is duplicate-and-pin — `resolve_main_root` in two scripts,
# the fence guard in two — on the argument that "a sourced helper missing from
# a partial install would be a worse failure than the duplication". This file
# is the first sourced helper, on the maintainer's call at Phase 251's open
# (`Q-365`): the installer copies `core/companion/scripts/*` whole, so every
# full install and every `--update` carries it, and the one way to lose it is
# to hand-copy a single script, which the message then explains.
#
# bash 3.2-clean (macOS ships 3.2): no associative arrays, no `mapfile`, no
# `${var,,}`. `self_check.sh` states the floor.
#
# ── resolve_default_branch [<checkout>] ──────────────────────
#
# Prints the repository's default branch NAME (`main`, `master`, `develop`, …)
# — a local branch name, never a remote-qualified ref — and returns 0. Prints
# nothing, writes a diagnostic to stderr and returns 1 when it cannot decide.
# It never guesses: `main` was hard-coded at ten behavioural sites across the
# three scripts that source this file (plus a lock-template hint and every
# message naming the branch), and on a `master`-default repo every one of
# them was silently wrong (a claim that leaves a lock and no status flip, a
# close that skips every batch as unmerged, a cleanup that reclaims nothing),
# because `git merge-base --is-ancestor X main 2>/dev/null` on a repo with no
# `main` exits non-zero exactly like "not merged" does.
#
# Resolution order, and the reason for each step:
#
#   1. `refs/remotes/<remote>/HEAD` — the remote's own declaration, set by
#      `git clone` and by `git remote set-head`. `<remote>` is `origin`, or
#      the repository's only remote when there is exactly one and it is not
#      called `origin` (a `git clone -o upstream` consumer). Taken only when
#      the branch it names ALSO exists locally, because every caller compares
#      against or branches from the LOCAL branch of that name. When it names
#      a branch the remote HAS (`refs/remotes/<remote>/<name>` exists) but the
#      checkout has not created, that is a REFUSAL naming the one-line fix
#      (`git branch <name> <remote>/<name>`): the remote has declared a
#      default and silently substituting `main` for it is the defect this
#      file replaces. When the remote-tracking ref is absent too, the
#      declaration is stale (the branch was deleted) and step 2 decides.
#   2. Exactly one of `refs/heads/main` / `refs/heads/master` exists — that
#      one. This is the `git init` case: no remote, or a remote that was added
#      by hand and so never had its HEAD set.
#   3. An UNBORN repository — no commit yet, so no branch ref exists at all —
#      has exactly one branch, the one `HEAD` symbolically names, and that is
#      the answer. This is the `git init && bash close_batch.sh` shape a
#      fixture reaches; a repo with commits never takes this step.
#   4. Anything else — both `main` and `master` present with no remote HEAD
#      to break the tie, or neither present, or a stale remote HEAD with no
#      `main`/`master` fallback — is a refusal with the git command that
#      settles it named in the message: `git remote set-head origin <branch>`
#      (the explicit form; `--auto` fails on a bare origin whose own HEAD
#      names a branch nobody pushed — measured). There is deliberately no
#      Sysop-side setting for this: git already owns the answer, and a second
#      place to declare the same fact is a second place for it to be wrong.
#
# The Python twin is `sitrep_survey.resolve_default_branch()`, kept to the
# same steps and pinned to this one by `tests/test_default_branch_resolution.py`
# (behavioural, over fixture repos — not a source-text pin).
#
# The <checkout> operand defaults to `.`. Refs are shared across every worktree
# of a repository, so any checkout of the repo gives the same answer; callers
# pass the checkout they already resolved (`$REPO_ROOT` or `$MAIN_ROOT`) so the
# probe is anchored rather than CWD-relative.
resolve_default_branch() {
  local dir="${1:-.}" remote="" remote_head="" name="" have_main=0 have_master=0 n_remotes=0

  # `origin`, or the only remote. `git remote` prints one name per line.
  # `symbolic-ref`, not `show-ref --verify`: a dangling origin/HEAD (its target
  # deleted) still names the remote, and the stale-declaration message below
  # should say so rather than "no remote HEAD".
  if git -C "$dir" symbolic-ref --quiet refs/remotes/origin/HEAD >/dev/null 2>&1 \
     || git -C "$dir" remote 2>/dev/null | grep -qx origin; then
    remote="origin"
  else
    n_remotes="$(git -C "$dir" remote 2>/dev/null | grep -c . || true)"
    if [[ "$n_remotes" -eq 1 ]]; then
      remote="$(git -C "$dir" remote 2>/dev/null | head -1)"
    fi
  fi

  if [[ -n "$remote" ]]; then
    remote_head="$(git -C "$dir" symbolic-ref --quiet --short "refs/remotes/${remote}/HEAD" 2>/dev/null)" || remote_head=""
  fi
  if [[ -n "$remote_head" ]]; then
    name="${remote_head#"${remote}"/}"
    if git -C "$dir" show-ref --verify --quiet "refs/heads/${name}" 2>/dev/null; then
      printf '%s\n' "$name"
      return 0
    fi
    if git -C "$dir" show-ref --verify --quiet "refs/remotes/${remote}/${name}" 2>/dev/null; then
      echo "❌ Cannot resolve this repository's default branch." >&2
      echo "   ${remote}/HEAD names '${name}' and ${remote}/${name} exists, but this checkout has no local branch '${name}'." >&2
      echo "   Create it and re-run:  git branch ${name} ${remote}/${name}" >&2
      return 1
    fi
  fi

  git -C "$dir" show-ref --verify --quiet refs/heads/main 2>/dev/null && have_main=1
  git -C "$dir" show-ref --verify --quiet refs/heads/master 2>/dev/null && have_master=1
  if [[ $((have_main + have_master)) -eq 1 ]]; then
    if [[ "$have_main" -eq 1 ]]; then
      printf '%s\n' main
    else
      printf '%s\n' master
    fi
    return 0
  fi

  if [[ $((have_main + have_master)) -eq 0 ]] \
     && ! git -C "$dir" rev-parse --verify --quiet HEAD >/dev/null 2>&1; then
    name="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null)" || name=""
    if [[ -n "$name" ]]; then
      printf '%s\n' "$name"
      return 0
    fi
  fi

  echo "❌ Cannot resolve this repository's default branch." >&2
  if [[ -n "$remote_head" ]]; then
    echo "   ${remote}/HEAD names '${name}', but neither a local nor a remote-tracking branch '${name}' exists (stale)." >&2
  elif [[ "$have_main" -eq 1 && "$have_master" -eq 1 ]]; then
    echo "   Both 'main' and 'master' exist locally and no remote HEAD breaks the tie." >&2
  else
    echo "   Neither 'main' nor 'master' exists locally and no remote HEAD names the branch." >&2
  fi
  echo "   Declare it to git and re-run:  git remote set-head origin <branch>" >&2
  echo "   (with no remote:  git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/<branch>" >&2
  echo "    — a claim does NOT require a remote: with no origin the claim path skips" >&2
  echo "      its pre-claim pull and still flips, locks and branches normally. What has" >&2
  echo "      to be decided here is the branch NAME, which only git can settle.)" >&2
  return 1
}

# ── require_default_branch [<checkout>] ──────────────────────
#
# `resolve_default_branch` for callers that cannot proceed without an answer:
# the same output on success, and on failure the same diagnostic plus one line
# saying which script stopped. The caller decides what stopping means:
#
#   DEFAULT_BRANCH="$(require_default_branch "$MAIN_ROOT")" || exit 1
#
# Kept separate from `resolve_default_branch` so a caller that CAN proceed
# without the name (`close_batch.sh` with an explicit `--merge-target`) can
# probe quietly and only fail at the site that needs it.
require_default_branch() {
  local name=""
  name="$(resolve_default_branch "${1:-.}")" || {
    echo "   ${0##*/} cannot continue without it — every branch comparison it makes is against that branch." >&2
    return 1
  }
  printf '%s\n' "$name"
}

# ── tracker_lock_acquire <locks_dir> <what> [<consequences>] ─
# ── tracker_lock_release ─────────────────────────────────────
#
# A mutual-exclusion gate over the read-modify-write-commit of
# `review_tasks.md` in the PRIMARY checkout. `Q-387`, Phase 258.
#
# WHY A LOCK AND NOT A COMPARE-AND-SWAP. The filing offered both shapes. CAS on
# the tracker blob is refuted by the actual failure path, which was measured
# rather than reasoned about: two claims share one working tree, so claim B's
# `sed` reads the file INCLUDING claim A's uncommitted flip and writes both back,
# and A's pathspec `git commit -- review_tasks.md` then commits BOTH. B's commit
# has nothing left to commit, exits non-zero, prints "the claim was rolled back,
# nothing was claimed", and its `git checkout --` restores from a state that
# already contains B's flip. There is no point in that sequence where B holds a
# blob it could have compared and swapped — its edit was swallowed before it ever
# reached a commit. The corruption vector is the shared worktree, so the fix has
# to serialize the whole critical section, not just the commit.
#
# WHY HERE. Both writers of `review_tasks.md` — `batch_work.sh` (the claim) and
# `close_batch.sh` (the close) — already source this file, and a mutex that only
# one of two writers acquires is not a mutex. Phase 251 established this file as
# the one sourced helper for exactly this reason (see the header).
#
# WHY `set -C`. `flock` does not exist on macOS and this tree has a hard bash 3.2
# floor, so the portable exclusive create is noclobber. `claim_task.sh`'s lock
# write — the `( set -C; printf ... > "$LOCK_FILE" )` subshell — is the
# in-repo precedent, and this borrows its discriminate-before-naming-a-cause
# discipline: noclobber refuses because the file EXISTS, everything else (EACCES,
# read-only fs, ENOSPC) refuses because the write could not happen at all, and
# reporting a rival that does not exist sends the operator hunting for nothing.
#
# WHY NOT IN `locks/`. `scope_overlap.py`, `sitrep_survey.py` and `next_task.py`
# all glob `sysop/runtime/locks/*.lock`
# and parse each hit as a YAML task lock. A mutex dropped in there would be read
# as an in-flight claim — the exact defect `batch_work.sh`'s lock-template comment
# warns about, where a lock that does not parse silently drops a batch out of the
# in-flight set. So it sits one level up, in `sysop/runtime/`, which is gitignored
# wholesale and outside every one of those globs.
#
# `validate_tasks.py` is deliberately NOT in that list, though it is the fourth lock
# reader: Invariant 9 builds `locks_dir / "<task id>.lock"` and asks `is_file()` — a
# keyed lookup no extra file in the directory can perturb. An earlier draft of this
# comment named it with the other three and was wrong; the author-side pass caught it.
#
# STALE LOCKS ARE NOT BROKEN AUTOMATICALLY. The operator makes that call, not this
# function. An auto-break is a path a reviewer has to trust on every run to save a
# hand-removal that happens almost never, and a PID liveness check is unsound the
# moment a checkout is shared across containers. So: bounded wait, then refuse
# LOUDLY, naming the holder and the exact command that clears it.
#
# THE WAIT IS 120s, NOT A FEW, AND THE SECTION IS NOT SHORT. An earlier draft of
# this comment said "the critical section is milliseconds, so a lock older than the
# wait is a corpse" and used a 10s wait on that basis. **That is false three times
# over, and each was measured rather than argued.** `claim_batch`'s section contains
# `git pull --ff-only origin <default>`, which is network-bound. Both writers'
# sections contain `git commit`, which fires the consumer's pre-commit hook — Sysop
# ships one — and a reviewer wedged a claim behind a 12-second hook. And
# `close_batch.sh` holds it from before its batch loop to process exit, spanning
# every batch's parse and rewrite plus the final commit. A holder legitimately
# outlasting a short wait is the ordinary case, not the pathological one. At 10s a *legitimate* holder was outlasted
# by its own pull, and the loser then printed a refusal inviting the operator to
# `rm -f` a lock whose holder was alive and mid-fetch — the one outcome this whole
# phase exists to prevent, arrived at from the other side. 120s covers a slow fetch;
# a genuinely dead holder costs one 120s wait, once, against a message that tells the
# operator exactly what to do. `SYSOP_TRACKER_LOCK_WAIT` overrides it, which is how
# the tests exercise the refusal without paying for it.
#
# The waiting notice is not cosmetic. Without it a contended claim looks hung for two
# minutes with no output, and an operator who Ctrl-Cs at that point loses nothing —
# the INT trap releases — but has no idea why they waited.
#
# THE ARGUMENT IS THE LOCKS DIR, NOT A REPO ROOT, and that is load-bearing.
# `batch_work.sh` resolves two different roots on purpose: `resolve_primary_worktree`
# for `$TASKS_FILE`, and `resolve_main_root` (git-common-dir) for the lock
# directory. Its § "Helper: resolve the PRIMARY WORKING TREE" comment says why the
# second must not be "fixed" in one script alone: two scripts whose locks land in
# different places is worse than two scripts that are wrong but agree.
#
# WHERE THEY ACTUALLY DIVERGE, because an earlier draft of this comment named the
# wrong layout and a reviewer measured it: **a linked worktree is the one place
# they provably AGREE** — `dirname` of `--git-common-dir` and
# `git worktree list --porcelain`'s first entry both return the primary. They
# diverge under `git init --separate-git-dir` (`<x>` vs `<x>/work`) and inside a
# submodule (`<super>/.git/modules/<name>` vs `<super>/<name>`), which is exactly
# what `batch_work.sh`'s own comment says and what this phase's behavioural test
# uses. The draft said "linked worktree" and was simply wrong.
#
# A mutex whose holders compute different paths is not a mutex, so this takes the
# LOCKS dir both writers already share and puts the file beside it. Agreement is
# then structural: if the batch locks agree, this agrees.
#
# Usage — the release MUST be trapped, or an early exit strands the mutex:
#
#   tracker_lock_acquire "$(resolve_locks_dir)" "claim Batch 3" || return 1
#   trap 'tracker_lock_release' EXIT
#
TRACKER_LOCK_FILE=""

tracker_lock_acquire() {
  local locks_dir="$1" what="$2"
  local runtime_dir=""
  if [ -z "$locks_dir" ]; then
    echo "❌ Could not resolve the runtime directory — refusing to serialize the tracker write." >&2
    echo "   Refusing ${what} — nothing was written." >&2
    return 1
  fi
  runtime_dir="$(dirname "$locks_dir")"
  local lock_file="${runtime_dir}/tracker.write.lock"
  # `what` describes the caller's operation; `consequences` describes what a
  # refusal costs, because a claim and a close lose different things and one
  # hard-coded sentence was wrong for the close (it named a branch, a worktree
  # and a lock, none of which a close creates).
  local consequences="${3:-nothing was written}"

  # A NON-REGULAR file here wedges every claim and close and the printed remedy
  # cannot clear it: `rm -f <dir>` fails with "is a directory", so the operator is
  # told to run a command that does not work, forever. `batch_work.sh` already
  # ships exactly this guard for the batch lock; this is the same class at the
  # mutex path, and it was missed until a reviewer put a directory there.
  if [ -e "$lock_file" ] && [ ! -f "$lock_file" ]; then
    echo "❌ ${lock_file} exists but is NOT a regular file." >&2
    echo "   Refusing ${what} — ${consequences}." >&2
    echo "   The tracker mutex must be a regular file. Inspect and remove it:" >&2
    ls -la "$lock_file" >&2 2>/dev/null || true
    echo "     rm -rf ${lock_file}      # -rf, not -f: -f alone cannot remove a directory" >&2
    return 1
  fi
  local waited=0 holder=""
  local max_wait="${SYSOP_TRACKER_LOCK_WAIT:-120}"
  local notified=0

  if ! mkdir -p "$runtime_dir" 2>/dev/null; then
    echo "❌ Could not create ${runtime_dir} — refusing to serialize the tracker write." >&2
    echo "   Proceeding without the lock is what ${what} must not do: two concurrent" >&2
    echo "   writers of review_tasks.md strand one of them. ${consequences}." >&2
    return 1
  fi

  # Whole seconds, because `sleep 0.2` is not portable to every /bin/sh this
  # tree targets and the wait only has to outlast a millisecond-scale section.
  while [ "$waited" -lt "$max_wait" ]; do
    if ( set -C; printf '%s\n' \
           "holder_pid: $$" \
           "holder: ${0##*/}" \
           "what: ${what}" \
           "since: $(date -u +"%Y-%m-%dT%H:%M:%SZ")" > "$lock_file" ) 2>/dev/null; then
      TRACKER_LOCK_FILE="$lock_file"
      return 0
    fi
    # Discriminate before naming a cause, exactly as claim_task.sh does: an
    # absent file here means the WRITE failed, not that a rival holds it.
    if [ ! -e "$lock_file" ]; then
      echo "❌ Could not write the tracker lock ${lock_file} — no rival holder;" >&2
      echo "   the write itself failed. Check that ${runtime_dir} is writable and" >&2
      echo "   that the filesystem is not full or read-only." >&2
      echo "   Refusing ${what} — ${consequences}." >&2
      return 1
    fi
    if [ "$notified" -eq 0 ] && [ "$waited" -ge 3 ]; then
      echo "⏳ Waiting for the tracker lock (${what})…" >&2
      sed 's/^/     /' "$lock_file" >&2 2>/dev/null || true
      notified=1
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done

  holder="$(sed 's/^/     /' "$lock_file" 2>/dev/null)" || holder="     (unreadable)"
  echo "❌ review_tasks.md is locked by another Sysop process; waited ${max_wait}s." >&2
  echo "   Refusing ${what} — ${consequences}." >&2
  echo "   The holder:" >&2
  echo "${holder}" >&2
  echo "" >&2
  echo "   If that process is gone, the lock is stale and safe to remove by hand." >&2
  echo "   CHECK FIRST — a claim's critical section includes a network 'git pull', so a" >&2
  echo "   live holder on a slow remote can legitimately hold it this long. It is NOT" >&2
  echo "   removed automatically, because breaking it blind is the same lost-update this" >&2
  echo "   lock exists to prevent." >&2
  echo "     rm -f ${lock_file}" >&2
  return 1
}

tracker_lock_release() {
  [ -n "$TRACKER_LOCK_FILE" ] || return 0
  # Unlink the lock THIS process took, not whatever now sits at the path. A
  # reviewer walked the cascade: the refusal invites a hand `rm -f`, an operator
  # takes it while the holder is alive, a third process acquires the now-free
  # path, and the original holder's release then deletes the NEW holder's lock —
  # leaving that one running unprotected. Checking the pid we wrote costs one
  # grep and makes a stolen lock a no-op instead of a silent hand-off.
  if grep -q "^holder_pid: $$\$" "$TRACKER_LOCK_FILE" 2>/dev/null; then
    rm -f "$TRACKER_LOCK_FILE" 2>/dev/null || true
  fi
  TRACKER_LOCK_FILE=""
}
