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
