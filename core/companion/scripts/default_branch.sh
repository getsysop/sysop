#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# default_branch.sh — print the repository's default branch NAME.
#
# The ONE entry point for `_git_lib.sh`'s resolver, and it exists for exactly
# one caller: a skill body. The lifecycle *scripts* source the library
# directly and need nothing here. A skill cannot: it is markdown an agent
# executes one fenced block at a time, no skill body sources a shell library
# anywhere in the tree, and `_git_lib.sh` is underscore-prefixed precisely
# because it is a private helper with no entry point. So the skill layer needs
# something it can *call*, which is the idiom it already uses forty times over
# (`bash sysop/scripts/close_batch.sh …`, `python3 sysop/scripts/next_task.py …`).
#
# Why a skill needs this at all (`Q-377`): Phase 252 made `batch_work.sh`,
# `close_batch.sh` and `cleanup_worktrees.sh` resolve the default branch
# instead of assuming `main`, but the skill bodies that call them kept the
# literal — so on a `master`-default consumer `/claim-task` Step 4d stopped at
# `HEAD is not main` where the scripts it wraps had just started working.
#
# Usage:
#   bash sysop/scripts/default_branch.sh              # this repository
#   bash sysop/scripts/default_branch.sh <checkout>   # a specific checkout
#
# In a skill body, run it BARE and substitute the name it prints. NOT into a
# shell variable — Claude Code's permission matcher does not match an allow
# rule "past an assignment of any other variable", so
# `DEFAULT_BRANCH="$(bash sysop/scripts/default_branch.sh)"` binds NO rule and
# routes to the auto-mode classifier, while the bare command binds
# `Bash(bash sysop/scripts/default_branch.sh)` exactly. That is also why this
# prints a bare name and nothing else: the caller is an agent reading stdout,
# which is the idiom the skill layer already uses forty times over
# (`batch_work.sh`'s `Path:`/`Branch:` box is parsed the same way).
#
#   bash sysop/scripts/default_branch.sh     # → prints e.g. `master`
#   # then use that literal wherever the step says `<default branch>`
#
# Output contract, because callers substitute it into git commands:
#   success → the branch NAME on stdout (`main`, `master`, `develop`, …), a
#             LOCAL branch name and never a remote-qualified ref, exit 0.
#   failure → nothing on stdout, the library's diagnostic (which names the git
#             command that settles it) on stderr, exit 1.
#
# Empty stdout on failure is deliberate — an empty operand is never a WRONG
# branch, so nothing here can silently compare against a branch that is not
# the default one.
#
# **It is not, however, self-announcing, and an earlier version of this comment
# claimed it was.** Measured: with the name substituted as the empty string,
# `git diff --name-only ...HEAD` exits 0 and prints nothing;
# `git log --oneline ..HEAD` exits 0 and prints nothing; and
# `git rev-list --count ..<branch>` prints `0` — which is exactly the value
# `/claim-task`'s pre-delete check is told to expect before it runs
# `git branch -D`. Only two shapes fail loudly: `origin/<empty>` (exit 128) and
# the `= "<branch>"` Rule A assert. The inverted `!= "<branch>"` assert passes
# unconditionally.
#
# So the exit code is the contract, not the output shape:
# **a caller that gets a non-zero exit must STOP, not substitute.** Every skill
# step that resolves this says so; that instruction is the safety property,
# and this script cannot supply one in its place.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

if [[ $# -gt 1 ]]; then
  echo "❌ Usage: default_branch.sh [<checkout>]" >&2
  exit 1
fi

case "${1:-}" in
  -h|--help)
    echo "Usage: bash sysop/scripts/default_branch.sh [<checkout>]"
    echo "Prints the repository's default branch name; exit 1 and a diagnostic if it cannot be resolved."
    exit 0
    ;;
esac

# `--show-toplevel`, and deliberately not the primary checkout: refs are shared
# across every worktree of a repository, so any checkout gives the same answer,
# and a skill that runs this from a task worktree should not have to know that.
# Anchoring to the caller's own root rather than `.` means a fence that has
# `cd`'d into a subdirectory still resolves.
REPO_ROOT="$(git -C "${1:-.}" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository: ${1:-$PWD}" >&2
  exit 1
}

source "$(dirname "${BASH_SOURCE[0]}")/_git_lib.sh" || {
  echo "❌ _git_lib.sh is missing beside default_branch.sh — it ships with every install." >&2
  echo "   Restore the scripts directory: bash sysop/scripts/sysop-update.sh" >&2
  exit 1
}

# `resolve_default_branch`, not `require_default_branch`, for one reason: the
# library's "which script stopped" suffix reads `<name> cannot continue without
# it — every branch comparison it makes is against that branch`, and this script
# makes no branch comparisons. Its CALLER does. The diagnostic that matters —
# the one naming the git command that settles it — is printed by the resolver
# either way; only the closing line is replaced, which is exactly the line
# `require_default_branch` exists to add.
resolve_default_branch "$REPO_ROOT" || {
  echo "   The skill step that asked for the default branch cannot continue without it." >&2
  exit 1
}
