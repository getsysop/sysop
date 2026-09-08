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
    echo "   writers of the same tracker file strand one of them. ${consequences}." >&2
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
  # "The tracker", NOT a filename. Since Phase 261 this mutex also serializes the
  # task-index writers in `claim_task.sh`, so naming one tracker file made every
  # task-claim refusal cite a file the caller had not touched. `${what}` says which
  # operation was refused and `${consequences}` says what it would have lost, and
  # both are the caller's to supply. The phrase "locked by another Sysop process"
  # is pinned by `tests/test_tracker_write_mutex.py` at two sites — keep it.
  echo "❌ The tracker is locked by another Sysop process; waited ${max_wait}s." >&2
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

# ── git_common_dir_abs <dir> ──────────────────────────────────
#
# Prints the ABSOLUTE, symlink-resolved path of <dir>'s `--git-common-dir` and
# returns 0; prints nothing and returns 1 when <dir> is not in a repository.
#
# The common dir is a repository's IDENTITY: every linked worktree of one repo
# reports the same one (the primary's `.git`), and two different checkouts of the
# same upstream report different ones. That is the question `path_is_worktree_of`
# below needs answered, and `--show-toplevel` cannot answer it — it reports the
# tree you are standing in, which is `Q-020`/`Q-307`'s class (Phase 234).
#
# Absolutising is not optional. From a PRIMARY checkout git answers with the
# relative `.git`; from a LINKED worktree it answers with an absolute path. A
# comparison that skips this step matches two unrelated repos on the string
# `.git`, which is a false ACCEPT — the fail-open direction.
#
# **The git-env scrub is deliberate and is the one place in these scripts that
# does it.** Every other git call here asks about the repository the script is
# running in, where an ambient `GIT_DIR` is plausibly the caller's intent. These
# two helpers ask about a FOREIGN path handed to them, where it never is: with
# `GIT_DIR` exported, `git -C <foreign> rev-parse` answers about the ambient repo
# and the predicate silently grades the wrong tree.
#
# **The list is five, not three, and the last two were found by execution in this
# phase's round.** `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR` REDIRECT discovery;
# the other two STOP it. `worktree_root_parent`'s arm 2 walks UPWARD looking for
# an enclosing working tree, so `GIT_CEILING_DIRECTORIES` naming that tree makes
# the walk find nothing and the guard ACCEPT — reproduced end to end, leaving the
# `?? sandbox/` untracked content in a neighbouring checkout that `Q-406` exists
# to prevent. `GIT_DISCOVERY_ACROSS_FILESYSTEM` is the same class at a mount
# boundary. `GIT_CONFIG_*` is deliberately NOT scrubbed: the test suites set it to
# isolate themselves from the operator's global config, and removing it would
# point these probes at the real one.
git_common_dir_abs() {
  # `local CDPATH=` is load-bearing, not hygiene. From a PRIMARY checkout git
  # answers with the relative `.git`, and `cd .git` consults `CDPATH` because the
  # operand does not begin with `/`, `./` or `../`. With a `CDPATH` exported —
  # ordinary in an interactive shell's environment — this resolved to a DECOY
  # `.git` elsewhere, and `cd` also ECHOES the directory it reached that way, so
  # the function returned two lines. Both halves are harmful and the first is
  # worse: the identity test then compared the wrong repository, so `claim_task.sh`
  # and `batch_work.sh` both REFUSED the operator's own worktree, accused it of
  # belonging to another checkout, and advised removing it. Found by execution in
  # this phase's round; `local` scopes the empty value to this call and its
  # subshells without touching the caller's environment.
  local CDPATH= d="$1" cd_
  [ -d "$d" ] || return 1
  cd_="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
                 -u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM \
         git -C "$d" rev-parse --git-common-dir 2>/dev/null)" || return 1
  [ -n "$cd_" ] || return 1
  if [ "${cd_#/}" != "$cd_" ]; then
    ( cd "$cd_" 2>/dev/null && pwd -P ) || return 1
  else
    ( cd "$d" 2>/dev/null && cd "$cd_" 2>/dev/null && pwd -P ) || return 1
  fi
}

# ── path_is_worktree_of <candidate> <checkout> ────────────────
#
# 0 when <candidate> is the ROOT of a working tree belonging to the SAME
# repository as <checkout>. 1 otherwise, silently — the caller writes the
# message, because the two callers refuse for different reasons.
#
# Three tests, and each rejects a case the others let through:
#
#   1. `-e "${candidate}/.git"` — a LINKED worktree's `.git` is a file holding a
#      `gitdir:` pointer and only a primary checkout has it as a directory, so
#      `-e`, never `-d` (`batch_work.sh`'s `path_is_worktree` states this too).
#   2. toplevel `-ef` candidate — stops a SUBDIRECTORY of a working tree from
#      passing. `--is-inside-work-tree` is true anywhere inside one, so it
#      answers a different question.
#   3. common dir `-ef` common dir — the identity test, and the one nothing in
#      this tree performed before Phase 264. Without it a live worktree of
#      ANOTHER checkout of the same project passes tests 1 and 2 (measured: two
#      checkouts sharing a workspace parent, the second claim adopting the
#      first's tree, exit 0, and a lock recording a workspace whose commits
#      belong to the other checkout — `Q-405` in `claim_task.sh`, `Q-415` in
#      `batch_work.sh`).
#
# `-ef` rather than `=` throughout, for the reason `--release`'s main-worktree
# guard gives: a case-divergent or symlinked spelling must not make an identity
# test MISS.
path_is_worktree_of() {
  local CDPATH= candidate="$1" checkout="$2" top mine theirs
  [ -e "${candidate}/.git" ] || return 1
  top="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
                 -u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM \
         git -C "$candidate" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ -n "$top" ] && [ "$top" -ef "$candidate" ] || return 1
  theirs="$(git_common_dir_abs "$candidate")" || return 1
  mine="$(git_common_dir_abs "$checkout")" || return 1
  [ "$theirs" -ef "$mine" ]
}

# ── remote_identity <url> [<base-dir>] ────────────────────────
#
# Prints a comparable IDENTITY token for a git remote URL and returns 0; prints
# nothing and returns 1 when <url> is empty.
#
# The question this answers is `Q-417`'s. `claim_task.sh --clone` adopted an
# existing directory on `git -C <dir> rev-parse --git-dir`, which answers *is
# this a repository* and never *whose*: a stranger `git init` at the computed
# clone path was adopted at exit 0, told the operator "Start working!", and wrote
# a lock whose `workspace:` named a tree with one file in it. The identity test
# for a `--clone` workspace cannot be `path_is_worktree_of` above — a clone is a
# SEPARATE repository by construction, so that predicate would refuse every
# legitimate one — so it has to be identity of ORIGIN. Comparing the two
# configured strings is not enough: git spells one GitHub repository at least
# four ways (`git@host:o/r.git`, `ssh://git@host/o/r`, `https://host/o/r.git`,
# `https://user@host/o/r`), and one checkout mixing two of them is ordinary
# rather than exotic: `gh auth status` reports a `Git operations protocol`, a
# hand-written runbook prescribes whichever spelling its author used, and the two
# disagree. An exact-string test would refuse a correct clone on such a machine —
# a false ACCEPT is the defect this closes, but a false REFUSAL would be a new one.
#
# Normalisation, and the decision behind each step (Wade's call, Phase 266):
#
#   * scheme, `user@` and `:port` are dropped — they are transport, not identity.
#   * the HOST is case-folded; the PATH is NOT. Case-folding the path would
#     conflate two distinct repositories on a case-sensitive host, and the two
#     error directions are not symmetric: a false REFUSAL costs the operator one
#     message and a re-run, a false ACCEPT is the whole defect this closes.
#   * one trailing `.git` and any trailing `/` are stripped — in that order, and
#     the slashes again afterwards, because `https://h/o/r.git/` occurs.
#
# The token carries its own FORM (`url` or `path`) as a tab-separated first
# field, so a local path and a network URL can never compare equal by accident.
#
# bash 3.2: `tr` for the case fold, not `${var,,}`.
remote_identity() {
  local url="$1" base="${2:-}" rest hostport host path
  [ -n "$url" ] || return 1

  case "$url" in
    file://*)
      remote_path_identity "${url#file://}" "$base"
      return 0
      ;;
    *://*)
      rest="${url#*://}"
      case "$rest" in
        */*) hostport="${rest%%/*}" ; path="${rest#*/}" ;;
        *)   hostport="$rest"       ; path="" ;;
      esac
      ;;
    /*|./*|../*|~*)
      remote_path_identity "$url" "$base"
      return 0
      ;;
    */*:*)
      # A `/` BEFORE the colon means git reads this as a local path, not as an
      # scp-like remote (`git ls-remote a/b:c` answers "does not appear to be a
      # git repository"; `h:c` answers "could not resolve hostname"). Found by
      # the round's execution lens: without this arm `a/b:c` was parsed as
      # host `a/b`, and since the token is `host` + `/` + `path`, it collided
      # with `https://a/b/c`. The scp arm is the only way a `/` can reach the
      # host field, so this is the whole of that collision.
      remote_path_identity "$url" "$base"
      return 0
      ;;
    *:*)
      # scp-like `[user@]host:path`. No scheme and no port — everything after
      # the FIRST colon is the path, which is why this arm cannot be folded into
      # the one above: there `:` introduces a port, here it introduces a path.
      hostport="${url%%:*}"
      path="${url#*:}"
      ;;
    *)
      # No scheme, no colon: a bare relative path.
      remote_path_identity "$url" "$base"
      return 0
      ;;
  esac

  host="${hostport##*@}"
  case "$host" in
    # An IPv6 literal is bracketed (`ssh://[::1]:22/o/r`); `%%:*` on `[::1]`
    # would leave `[`. Keep the brackets, drop anything after them.
    \[*\]*) host="${host%%\]*}]" ;;
    *)      host="${host%%:*}" ;;
  esac
  host="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"

  while [ "${path#/}" != "$path" ]; do path="${path#/}"; done
  while [ "${path%/}" != "$path" ]; do path="${path%/}"; done
  path="${path%.git}"
  while [ "${path%/}" != "$path" ]; do path="${path%/}"; done

  printf 'url\t%s/%s\n' "$host" "$path"
}

# ── remote_path_identity <path> [<base-dir>] ──────────────────
#
# The LOCAL half of `remote_identity`, and it is not an edge case: every fixture
# in this tree uses a bare repository on disk as `origin`, and so does any
# consumer whose remote is a path. Compared as a PATH, never as `host/path`.
#
# Physical resolution is the point. On macOS `/tmp` is a symlink to
# `/private/tmp`, so one bare repo reached by two spellings must not read as two
# remotes — the same reason `git_common_dir_abs` above ends in `pwd -P`. A path
# that does not exist is normalised as a string and compared that way; that is a
# fail-toward-refusal, which is the safe direction here.
#
# <base-dir> resolves a RELATIVE remote, because git resolves one against the
# repository that declares it and not against the caller's CWD. With no
# <base-dir> a relative path is left as written.
#
# `.git` is deliberately NOT stripped from a path, unlike the URL arm: `.git` is
# part of a bare repository's real directory name (`/srv/origin.git`), and
# stripping it would send `cd` at a directory that does not exist.
remote_path_identity() {
  local CDPATH= p="$1" base="${2:-}" abs resolved
  while [ "${p%/}" != "$p" ] && [ "$p" != "/" ]; do p="${p%/}"; done
  case "$p" in
    # A literal `~` is left UNRESOLVED, and the honest reason is not the one the
    # first cut gave. That comment said "neither does git for a remote it
    # stores"; the round measured otherwise — git stores the tilde verbatim but
    # RESOLVES it (`git ls-remote` on a `~/x.git` origin exits 0). So the cost is
    # real and is stated rather than denied: a consumer spelling one origin
    # `/srv/git/x.git` on one side and `~/x.git` on the other gets a false
    # REFUSAL. That is the safe direction — the accept is what this exists to
    # deny — and expanding `$HOME` here would resolve it against the SCRIPT's
    # environment, not the ssh account's, which is a different bug.
    /*|~*) abs="$p" ;;
    *)     if [ -n "$base" ]; then abs="${base%/}/$p"; else abs="$p"; fi ;;
  esac
  if [ -d "$abs" ]; then
    resolved="$( cd "$abs" 2>/dev/null && pwd -P )" && abs="$resolved"
  fi
  printf 'path\t%s\n' "$abs"
}

# ── origin_identity <dir> ─────────────────────────────────────
#
# Prints <dir>'s `origin` identity token and returns 0; prints nothing and
# returns 1 when <dir> is not the ROOT of a working tree, or has no usable
# `origin`. A repository with no `origin` is UNIDENTIFIABLE, not innocent — the
# caller refuses on 1.
#
# The git-env scrub is the same five variables and the same reason as
# `git_common_dir_abs` above: this asks about a FOREIGN directory handed to the
# script, where an exported `GIT_DIR` would silently answer about the ambient
# repository instead — and here that reads a stranger's directory as ours, which
# is the fail-open direction.
#
# **The toplevel test is not decoration, and the first cut shipped without it.**
# `git -C <dir>` performs UPWARD DISCOVERY, and the scrub above actively unsets
# `GIT_CEILING_DIRECTORIES`, so an empty non-repository directory sitting inside
# some other checkout answered rc=0 with the ENCLOSING repository's origin. The
# function's own header said it returned 1 for "not a repository" and it did
# not. Two consequences, both measured by the round: a directory that is not a
# repository at all could satisfy an identity check, and the caller's refusal
# messages then stated falsehoods about it ("is a git repository with no
# 'origin'" for a plain directory; "its origin: <url>" naming a remote that
# belongs to a different repository). This is the same hazard
# `path_is_worktree_of` above documents for `--is-inside-work-tree`, and the
# same remedy — `--show-toplevel -ef <dir>`.
#
# **`config --get`, not `remote get-url`, and that is a defect fix too.**
# `git remote get-url origin` prints the remote NAME at rc=0 when
# `remote.origin.url` is unset or empty, so the first cut turned such a repo
# into a fabricated `path\t<dir>/origin` token AT SUCCESS — the one case the
# caller's no-origin message exists for. `config --get` returns 1 when the key
# is absent and prints empty when it is blank, which the `-n` test below then
# catches.
# ── path_is_worktree_root <dir> ───────────────────────────────
#
# 0 when <dir> is the ROOT of some working tree — any repository's, not
# necessarily ours. That is the weaker half of `path_is_worktree_of` above, and
# it is separate because two callers need exactly it: `origin_identity` below,
# and `claim_task.sh --clone`, whose whole question is about a directory that is
# a DIFFERENT repository by construction.
#
# It exists because `rev-parse --git-dir` — what `--clone` used to ask — answers
# yes from anywhere inside a working tree, including a plain empty subdirectory
# of an unrelated checkout. Same env scrub, same `-ef`, same reasons as above.
path_is_worktree_root() {
  local dir="$1" top
  [ -d "$dir" ] || return 1
  top="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
                 -u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM \
         git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ -n "$top" ] && [ "$top" -ef "$dir" ]
}

origin_identity() {
  local dir="$1" url
  path_is_worktree_root "$dir" || return 1
  url="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
                 -u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM \
         git -C "$dir" config --get remote.origin.url 2>/dev/null)" || return 1
  [ -n "$url" ] || return 1
  remote_identity "$url" "$dir"
}

# ── worktree_root_parent <primary-root> ───────────────────────
#
# Validates `WORKTREE_ROOT` and prints the absolute parent directory to build
# workspaces under. Returns 1 with a diagnostic on stderr when the value is
# unusable; the caller exits, so a refusal never reaches `git worktree add`.
#
# Callers MUST have established that `WORKTREE_ROOT` is non-empty. It is scoped
# to the modes that BUILD a workspace: validating it for a mode that never reads
# the path would refuse work the variable does not govern, and the variable is
# meant to live in a sandbox's persistent environment where a stale value would
# then block a mode that never touches it.
#
# Extracted from `claim_task.sh` at Phase 264 so `batch_work.sh` could honour the
# same variable (`Q-407`) without re-deriving four guards, three of which were
# defects found by EXECUTION rather than by design in Phase 262's round.
worktree_root_parent() {
  # `CDPATH` again, and here it also broke the *validate one path, use another*
  # invariant: `[ -d "$WORKTREE_ROOT" ]` resolves against the CWD while
  # `cd "$WORKTREE_ROOT"` consults `CDPATH` for a relative value, so the function
  # validated one directory and returned a different one — with the echoed path
  # making the result two lines, which is the very newline the guard at the top of
  # this function exists to refuse.
  local CDPATH= primary_root="$1" wr_abs rr_abs owner
  # A newline survives the assignment and then splits the lock's `workspace:`
  # field, which every reader parses line-anchored — `--release`'s awk and
  # /review-close's `partition(":")` both silently take the first line, so the
  # claim succeeds and the release reports success over an orphan.
  # `$'\n'` (bash 3.2 ANSI-C quoting), NOT `"$(printf '\n')"` — command
  # substitution strips trailing newlines, so that spelling yields the EMPTY
  # string and the pattern collapses to `**`, refusing every root ever set.
  # Caught by re-reading this block before running it.
  case "$WORKTREE_ROOT" in
    *$'\n'*)
      echo "❌ WORKTREE_ROOT contains a newline; the lock's workspace: field is line-anchored." >&2
      return 1
      ;;
  esac
  if [ ! -d "$WORKTREE_ROOT" ]; then
    echo "❌ WORKTREE_ROOT='${WORKTREE_ROOT}' is not an existing directory." >&2
    echo "   Create it first — this script will not mkdir a path that may be a typo." >&2
    return 1
  fi
  # Writability is checked HERE rather than left to `git worktree add`, because
  # git fails at a point where the caller has already created the branch: the
  # observed shape was rc=128, a bare `fatal: could not create leading
  # directories`, an orphan branch and no guidance. This is also the most likely
  # real failure for the variable's whole purpose — a sandbox declares a path and
  # the process cannot actually write it.
  if [ ! -w "$WORKTREE_ROOT" ]; then
    echo "❌ WORKTREE_ROOT='${WORKTREE_ROOT}' is not writable by this process." >&2
    echo "   Nothing was created. Fix the permission, or declare a different directory." >&2
    return 1
  fi
  # `pwd -P` rather than `realpath`, which stock macOS does not ship (bash 3.2).
  wr_abs="$( cd "$WORKTREE_ROOT" && pwd -P )" || return 1
  # ── Arm 1: inside THIS repository ───────────────────────────
  #
  # A worktree here shows up as untracked content in the main checkout, is not
  # covered by the `sysop/runtime/` gitignore set, and would be swept by the very
  # cleanup paths meant to remove it.
  #
  # COMPARE AGAINST THE PRIMARY CHECKOUT, not the invocation's own toplevel.
  # `git rev-parse --show-toplevel` answers "which worktree am I standing in", so
  # from inside a linked worktree the guard compared against the wrong tree and
  # ACCEPTED a root inside the main checkout — `Q-020`/`Q-307`'s class (Phase
  # 234), recurring in a guard written after it. The caller resolves the primary
  # and passes it in.
  #
  # **ARM 2 DOES NOT SUBSUME THIS ONE.** An earlier version of this comment said it
  # did, and a review lens falsified it by execution: arm 2 asks
  # `rev-parse --show-toplevel`, which inside a `.git` DIRECTORY exits 128
  # (`fatal: this operation must be run in a work tree`), so it cannot see a root
  # there at all. With this arm removed, `WORKTREE_ROOT=<repo>/.git/nested` is
  # ACCEPTED. This arm's prefix match is the only thing that refuses it.
  #
  # So arm 1 carries coverage, not merely a better message — though it carries that
  # too, and deliberately: a root inside THIS repository has a specific cause and a
  # specific remedy, and a guard that reports the nearest true reason is the one an
  # operator can act on. `test_arm_one_carries_coverage_arm_two_cannot` pins the
  # coverage half, because a test asserting only the message measures the wrong
  # property — which is exactly how the false claim survived its own battery.
  rr_abs="$( cd "$primary_root" && pwd -P )" || return 1
  case "$wr_abs" in
    "$rr_abs"|"$rr_abs"/*)
      echo "❌ WORKTREE_ROOT='${WORKTREE_ROOT}' resolves inside the repository (${rr_abs})." >&2
      echo "   A worktree there is untracked content in the main checkout. Pick a path outside it." >&2
      return 1
      ;;
  esac
  # ── Arm 2: inside ANY working tree (`Q-406`) ────────────────
  #
  # Direction ratified by the maintainer 2026-09-04. Arm 1's stated rationale —
  # untracked content in a checkout, outside the `sysop/runtime/` gitignore set,
  # swept by the cleanup paths — is repo-AGNOSTIC, so the predicate must be too.
  # Phase 262 shipped arm 1 alone and a root inside a NEIGHBOURING repository was
  # accepted, producing the same harm one repository over (its round observed the
  # resulting `?? nested/` untracked there).
  #
  # THE COST IS ACCEPTED, NOT OVERLOOKED: a consumer whose sandbox directory
  # legitimately sits inside a larger checkout — a monorepo — must now point
  # `WORKTREE_ROOT` outside it. That is the fail-closed direction, and the
  # message names the tree so the remedy is obvious rather than mysterious.
  if owner="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
                 -u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM \
              git -C "$wr_abs" rev-parse --show-toplevel 2>/dev/null)" \
     && [ -n "$owner" ]; then
    echo "❌ WORKTREE_ROOT='${WORKTREE_ROOT}' resolves inside a git working tree (${owner})." >&2
    echo "   A worktree there is untracked content in THAT checkout, which its own" >&2
    echo "   cleanup paths would sweep. Pick a path outside every repository." >&2
    return 1
  fi
  printf '%s\n' "$wr_abs"
}
