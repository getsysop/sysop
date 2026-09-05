#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# claim_task.sh — Create an isolated workspace for an agent task.
#
# Usage:
#   bash sysop/scripts/claim_task.sh <TASK_ID> <BRANCH_NAME> [AGENT_NAME]
#   bash sysop/scripts/claim_task.sh --branch <TASK_ID> <BRANCH_NAME> [AGENT_NAME]
#   bash sysop/scripts/claim_task.sh --clone <TASK_ID> <BRANCH_NAME> [AGENT_NAME]
#   bash sysop/scripts/claim_task.sh --lock <TASK_ID> <BRANCH_NAME> [AGENT_NAME]
#   bash sysop/scripts/claim_task.sh --release [--delete-branch] [--force] <TASK_ID>
#   bash sysop/scripts/claim_task.sh --commit-claim <TASK_ID>
#
# Modes:
#   (default)    Create a git worktree at ../<project basename>-<TASK_ID>
#                on the branch. Override the leaf name by exporting
#                WORKTREE_PREFIX (e.g. WORKTREE_PREFIX=foo → ../foo-<TASK_ID>),
#                and the parent directory by exporting WORKTREE_ROOT
#                (e.g. WORKTREE_ROOT=/w → /w/<basename>-<TASK_ID>). Unset,
#                WORKTREE_ROOT keeps the historical `..`. It must name an
#                existing directory outside the repository; both are checked.
#                This is the safe default for parallel sessions.
#   --branch     Create branch in current workspace (no isolation — use only
#                when you are the sole session working in this directory).
#   --clone      Clone the repo to ../<project basename>-<TASK_ID> and
#                checkout the branch.
#   --release    Reverse a claim (un-claim): remove the worktree recorded in
#                the lock, flip the task's `status: in_progress` → `open` in
#                tasks/index.yml (via a PyYAML round-trip — never a hand-edit),
#                and delete the lock. The sanctioned inverse of a claim, so a
#                human who changes their mind has an owner for both halves —
#                the status flip and the lock release. Reads the branch and
#                workspace from the lock, so only <TASK_ID> is required. Runs
#                validate_tasks.py and prints the commit command; never commits.
#   --commit-claim  Commit the forward claim: ensure <TASK_ID> is in_progress in
#                tasks/index.yml and commit that one path on the default branch,
#                all under the tracker write mutex. This is `/claim-task` Step 4d,
#                and it is the ONE mode here that commits. It re-flips if the
#                status came back `open`, so a rival that clobbered Step 4a's
#                uncommitted edit cannot leave the claim silently un-made
#                (`Q-397`, Phase 261).
#
# Options:
#   --lock           Also create a sysop/runtime/locks/<TASK_ID>.lock file for multi-agent
#                    coordination. Off by default for solo workflows.
#   --delete-branch  (--release only) Also delete the feature branch. Off by
#                    default — a claim leaves the branch, so un-claim does too.
#   --force          (--release only) Pass --force to `git worktree remove` so
#                    a worktree with uncommitted changes is discarded. Without
#                    it, a dirty worktree aborts the release untouched.
#
# Lock location (Phase 32, 2026-05-22):
#   Lock files always live under the main repo's sysop/runtime/locks/ — resolved via
#   `git rev-parse --git-common-dir`, so the path is canonical whether the
#   script is invoked from the main checkout or from any worktree. The
#   validator (sysop/scripts/validate_tasks.py) uses the same resolution, so
#   callers from any cwd see the same lock state.
#
# Examples:
#   bash sysop/scripts/claim_task.sh FEAT-STRIPE feat/stripe "Agent-7"
#   bash sysop/scripts/claim_task.sh --lock FEAT-STRIPE feat/stripe "Agent-7"
#   bash sysop/scripts/claim_task.sh --branch FEAT-STRIPE feat/stripe "Agent-7"
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# ── Parse flags ──────────────────────────────────────────────
MODE="worktree"
USE_LOCK=false
RELEASE=false
DELETE_BRANCH=false
FORCE=false
ENTRY_STATE=false
COMMIT_CLAIM=false
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --worktree)      MODE="worktree"; shift ;;
    --branch)        MODE="branch"; shift ;;
    --clone)         MODE="clone"; shift ;;
    --lock)          USE_LOCK=true; shift ;;
    --release)       RELEASE=true; shift ;;
    --commit-claim)  COMMIT_CLAIM=true; shift ;;
    --entry-state)   ENTRY_STATE=true; shift ;;
    --delete-branch) DELETE_BRANCH=true; shift ;;
    --force)         FORCE=true; shift ;;
    *) echo "❌ Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ── The tracker write mutex (Phase 261, `Q-397`) ──────────────
# Sourced for `tracker_lock_acquire`/`tracker_lock_release`, which serialize the
# two paths in this script that read-modify-write `tasks/index.yml` — the claim
# commit (`--commit-claim`) and the un-claim (`--release`). Before Phase 261 this
# script took no tracker mutex at all, and neither did `/claim-task` Steps 4a+4d;
# measured by a maintainer-side concurrency harness that never ships, two concurrent
# claims left one task open at HEAD while its own claim process exited 0 in 6 to 25 of 100
# trials — two claims starting together with nothing between Steps 4a and 4d. With 4b and
# 4c in between the same harness measured 0 of 100, so quote the WINDOW with the rate.
# Post-fix: 0 of 100 in both windows, serial control clean, same harness driving both.
#
# The mutex path is derived from the LOCKS DIR, not from a repo root, and that is
# load-bearing: `_git_lib.sh` § tracker_lock_acquire records that anchoring per
# script would ship two mutexes at two paths under `--separate-git-dir` and inside
# submodules. The `git-common-dir` derivation below is the same one this file
# already uses twice for `sysop/runtime/locks/`, and the same one `batch_work.sh`
# and `close_batch.sh` reach through their own `resolve_main_root`.
source "$(dirname "${BASH_SOURCE[0]}")/_git_lib.sh" || {
  echo "❌ _git_lib.sh is missing beside claim_task.sh — it ships with every install." >&2
  echo "   Restore the scripts directory: bash sysop/scripts/sysop-update.sh" >&2
  exit 1
}

# Resolve the primary checkout via git-common-dir — NOT `--show-toplevel`, which
# answers which worktree the caller stands in (`Q-234`). Both the mutex and the
# index this script writes are main-side records.
resolve_primary_root() {
  local common_dir
  common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$common_dir" ]] || return 1
  if [[ "$common_dir" = /* ]]; then
    dirname "$common_dir"
  else
  # `CDPATH= cd`, not bare `cd`: git answers with the RELATIVE `.git` from a
  # primary checkout, and `cd .git` consults `CDPATH` because the operand starts
  # with neither `/`, `./` nor `../`. An exported `CDPATH` therefore resolved this
  # to a decoy elsewhere AND made `cd` echo the directory it reached, doubling the
  # value. Found by execution in Phase 264's round, in the guard path that made
  # this helper newly load-bearing.
    dirname "$(CDPATH= cd "$common_dir" && pwd)"
  fi
}

# ── PyYAML interpreter resolution (Phase 182) ────────────────
# Four sites below read tasks/index.yml through PyYAML. On a PEP-668 host —
# every modern distro, and Homebrew macOS — `pip install` into the system
# interpreter is an *error*, so PyYAML lives only in the project venv. A bare
# `python3` therefore failed on hosts that are perfectly well provisioned:
# `--entry-state` (Step 2's FIRST command) exited 3 and named no remedy, and
# `--release` exited 1 with a manual recipe. Internal tracker #321.
#
# Three properties are deliberate:
#
#   * It PROBES rather than assuming. A blind `PATH=.venv/bin:$PATH` prepend
#     would shadow a capable system interpreter with an incapable venv one —
#     trading the reported failure for its mirror image. self_check.sh:77-85
#     documents the same hazard, named from the probe side. (Phase 182 wrote
#     this citation against :61-66 and then, in the same commit, hoisted
#     MAIN_ROOT above probe 3 — moving the text it points at. It also said
#     "the other direction", which that phase's own round refuted. Both
#     corrected in Phase 184; the range is pinned by
#     tests/test_intra_repo_citations.py so the next hoist reddens.)
#   * It PREPENDS the winner's bin dir instead of binding a `$PY` variable, so
#     every call site keeps a literal `python3` command word. (Script-internal
#     commands are permission-exempt — the matcher only sees `bash …
#     claim_task.sh` — so this buys consistency with the shipped Phase-126
#     idiom rather than an allow-rule match. Stated plainly because the filing
#     recorded the allow-rule as the binding reason, and here it is not.)
#   * It anchors on the MAIN checkout before the current one. `--entry-state`
#     is routinely run from a worktree and `--release` may be run from any
#     subdirectory, so a CWD-relative probe answers the wrong question — and
#     worktrees do not carry their own .venv.
#
# Returns 0 when some interpreter on the resulting PATH can `import yaml`, 1
# when none can. Callers MUST invoke it in a conditional: fail-closed is still
# the right answer when nothing has PyYAML, and only the venv-only host stops
# being that case.
resolve_yaml_python() {
  local root candidate seen=""
  for root in "${MAIN_REPO_ROOT:-}" "${REPO_ROOT:-}"; do
    [[ -n "$root" ]] || continue
    # Every non-worktree invocation has REPO_ROOT == MAIN_REPO_ROOT, so without
    # this the refusal path launches four interpreters instead of two.
    [[ "$root" == "$seen" ]] && continue
    seen="$root"
    for candidate in "${root}/.venv/bin" "${root}/venv/bin"; do
      [[ -x "${candidate}/python3" ]] || continue
      "${candidate}/python3" -c "import yaml" >/dev/null 2>&1 || continue
      export PATH="${candidate}:${PATH}"
      return 0
    done
  done
  command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" >/dev/null 2>&1
}

# ── Path containment (case-safe) ─────────────────────────────
# True when the current directory IS $1 or sits underneath it.
#
# The obvious form — `[[ "$CWD" == "$DIR" || "$CWD" == "$DIR"/* ]]` — is a
# STRING test, and `pwd -P` resolves symlinks but not case. Two spellings that
# differ only in case reach the same directory on any case-insensitive
# filesystem (every default macOS install: `~/projects/repo` vs the on-disk
# `~/Projects/repo`), so the test says "not inside" while you are standing in
# it. That is the direction that fails open: the caller then removes the
# worktree the operator is currently in.
#
# `-ef` compares device+inode, which is what "the same directory" actually
# means, but it cannot express a prefix — so walk up from the cwd and ask the
# question at each level. Bounded by the walk to `/`, and `dirname` of `/` is
# `/`, so the loop terminates on the root as well.
cwd_is_inside() {
  local target="$1" d prev
  [[ -n "$target" && -d "$target" ]] || return 1
  d="$(pwd -P)"
  while :; do
    [[ "$d" -ef "$target" ]] && return 0
    prev="$d"
    d="$(dirname "$d")"
    [[ "$d" == "$prev" ]] && return 1
  done
}

# ── Entry state (read-only claim triage) ─────────────────────
# Answers ONE question — "what happens if I claim <TASK_ID> right now?" — and
# mutates nothing. It exists so the decision lives in testable, allow-ruled
# code instead of in /claim-task Step 2's prose. Two of the four roadmap-side
# re-entry guards lived in that prose (the metadata heredoc's status check and
# Step 2's lock check); the other two are Step 4a's flip refusal and this
# script's own lock refusal. Only the two STATUS guards blocked re-entry for a
# task with no lock — the two lock guards cannot fire in that state at all.
#
# Prints exactly one token on stdout:
#   claimable      status: open, no lock            → an ordinary fresh claim
#   resumable      status: in_progress, NO lock     → AMBIGUOUS, see below
#   held           status open/in_progress + lock   → something holds it
#   closed:<s>     status: done / deferred / …      → not claimable at all
#   absent         no such id in tasks/index.yml
#
# `resumable` is NOT an identity claim, and it is NOT "safe to resume".
# AGENT_NAME defaults to "anonymous" (see the positional parse below), so the
# lock records no usable owner and nothing here can tell "my abandoned claim"
# from "a colleague's". Worse, the same signature is produced by a task that is
# FINISHED: under `pr` merge policy /review-close Step 4c unlinks the lock on
# the integration branch before the PR merges, while the `done` flip rides that
# PR — so on main the task reads in_progress with no lock for the PR's whole
# life (review-close/SKILL.md § Lock-as-real-time-signal invariant). The caller
# must treat `resumable` as a question, not an answer; /claim-task Step 2 stops
# and asks. Note also that validate_tasks.py Invariant 9 treats this state as a
# blocking error and sitrep_survey.py reports it as index drift.
#
# Exit 0 on every RESOLVED state (read the token). Non-zero only when the
# question could not be answered at all.
if $ENTRY_STATE; then
  TASK_ID="${1:?Usage: claim_task.sh --entry-state <TASK_ID>}"

  # Review batches: refused on purpose, mirroring --release. A batch's claim
  # state is two-part — `review_tasks.md`'s status plus the lock — and that file
  # is not tasks/index.yml, so answering from here would report `absent` for
  # every batch that exists. batch_work.sh owns both halves.
  # Both spellings: the normalised `BATCH-<N>` form AND the bare integer a
  # human types (`/claim-task 116`). Step 1 normalises the latter, but this
  # script is also called directly, and a bare integer is precisely the
  # claim-kind confusion the <CLAIM_ID> vocabulary exists to remove — returning
  # `absent` for it would be the same "reads as not claimed" answer for every
  # batch that Phase 156 fixed elsewhere.
  if [[ "$TASK_ID" =~ ^[Bb][Aa][Tt][Cc][Hh]-([0-9]+)$ ]] || [[ "$TASK_ID" =~ ^([0-9]+)$ ]]; then
    echo "❌ ${TASK_ID} is a review batch; its claim state lives in review_tasks.md, not tasks/index.yml." >&2
    echo "   Read the batch's status there (and sysop/runtime/locks/BATCH-${BASH_REMATCH[1]}.lock) instead;" >&2
    echo "   /claim-task Step 2's review-batch branch already does exactly that." >&2
    exit 1
  fi

  REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "❌ Not inside a git repository." >&2
    exit 1
  }
  GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
  if [[ -z "$GIT_COMMON_DIR" ]]; then
    echo "❌ git rev-parse --git-common-dir failed; cannot resolve canonical sysop/runtime/locks/ location." >&2
    exit 1
  fi
  if [[ "$GIT_COMMON_DIR" = /* ]]; then
    MAIN_REPO_ROOT="$(dirname "$GIT_COMMON_DIR")"
  else
    MAIN_REPO_ROOT="$(dirname "$(CDPATH= cd "$GIT_COMMON_DIR" && pwd)")"
  fi

  HAS_LOCK=false
  [[ -f "${MAIN_REPO_ROOT}/sysop/runtime/locks/${TASK_ID}.lock" ]] && HAS_LOCK=true

  # The index is canonical for CLOSED states even when a lock is present: a
  # done/deferred task with a leftover lock is stale-lock cleanup, not a live
  # claim, and reporting `held` there sends the operator to takeover instead.
  # For every other state the lock wins — including a task absent from the
  # index, where a lock is the only evidence there is.
  #
  # Resolved against the MAIN checkout, not $REPO_ROOT: claims are committed on
  # main (Step 4d) and locks resolve via git-common-dir, so a worktree asking
  # "can I claim this?" must get main's answer or two branches' index copies
  # adjudicate one claim.
  INDEX="${MAIN_REPO_ROOT}/tasks/index.yml"
  if [[ ! -f "$INDEX" ]]; then
    echo "❌ ${INDEX} not found — consumer not bootstrapped, or wrong repo." >&2
    exit 2
  fi
  # Resolves the project venv first, so PyYAML need not be installed into a
  # PEP-668 system interpreter. Only a host where NOTHING can import yaml
  # reaches the refusal — and that refusal now names a remedy, which the
  # original did not, leaving the reporter's workaround undiscoverable.
  if ! resolve_yaml_python; then
    echo "❌ python3 + PyYAML is required to read tasks/index.yml." >&2
    echo "   Tried .venv/bin/python3 and venv/bin/python3 under ${MAIN_REPO_ROOT} then ${REPO_ROOT}, then python3 on PATH." >&2
    echo "   fix: python3 -m venv .venv && .venv/bin/pip install pyyaml   (PEP-668-safe)" >&2
    exit 3
  fi

  # stderr goes to its OWN file, never merged into the captured stdout. The
  # contract is "exactly one token on stdout", and a consumer sitecustomize.py,
  # a printing .pth, a conda/mise shim or a future PyYAML DeprecationWarning
  # would otherwise be prepended to the token and break every caller.
  ES_ERR="$(mktemp -t claim_es_err.XXXXXX)" || {
    echo "❌ Could not create a temp file for entry-state diagnostics." >&2
    exit 4
  }
  ES_OUT=$(HAS_LOCK="$HAS_LOCK" TASK_ID="$TASK_ID" INDEX_PATH="$INDEX" python3 - 2>"$ES_ERR" <<'PY'
import os, sys, yaml
try:
    with open(os.environ["INDEX_PATH"], encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    tid = os.environ["TASK_ID"]
    has_lock = os.environ.get("HAS_LOCK") == "true"
    for t in (data.get("tasks") or []):
        if t.get("id") == tid:
            status = str(t.get("status", "")).strip()
            if status in ("open", "in_progress"):
                # A live status plus a lock means something holds it.
                if has_lock:
                    print("held")
                else:
                    print("claimable" if status == "open" else "resumable")
            else:
                # Closed wins over a leftover lock — that is stale-lock
                # cleanup, not a live claim.
                print(f"closed:{status or 'unknown'}")
            break
    else:
        # Not in the index at all. A lock is then the only evidence there is.
        print("held" if has_lock else "absent")
except Exception as exc:  # noqa: BLE001 — any parse failure is unresolvable
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
PY
  ) || {
    echo "❌ Could not read ${INDEX}:" >&2
    cat "$ES_ERR" >&2
    rm -f "$ES_ERR"
    exit 4
  }
  # Succeeded, but do not swallow whatever the interpreter said on the way —
  # a printing sitecustomize.py or a deprecation warning is exactly the kind of
  # thing that should stay visible (Phase 135: a silent abort and a clean run
  # must not look identical). It goes to stderr, so the stdout contract holds.
  [[ -s "$ES_ERR" ]] && cat "$ES_ERR" >&2
  rm -f "$ES_ERR"
  echo "$ES_OUT"
  exit 0
fi

# ── Commit the claim (`/claim-task` Step 4d) ─────────────────
# Phase 261, `Q-397`. Replaces the bash block Step 4d used to print, which did an
# unlocked `git add` + `git commit` over an index Step 4a had rewritten in place.
#
# TWO properties, and the second is why this is not just "4d with a lock":
#
#  1. SERIALIZED. The whole read-modify-write-commit runs under the tracker write
#     mutex, so two concurrent claims cannot interleave.
#  2. SELF-HEALING, which is what makes the fix work without reordering the steps.
#     Step 4a's flip is uncommitted and lives on disk between 4a and 4d, where a
#     rival's whole-file `safe_dump` can still clobber it — the mutex here cannot
#     retroactively protect a write that already happened outside it. So this mode
#     RE-READS the index and re-flips if this task came back `open`. Whatever
#     happened in the gap, the task is `in_progress` and committed when this
#     returns, or the mode fails loudly. Measured: that is the difference between
#     6-25 of 100 claims exiting 0 with the task still open, and 0 of 100.
#
# The commit is pathspec-scoped (`-- tasks/index.yml`). Step 4d's bare `git commit`
# swept in whatever else happened to be staged in the shared primary checkout,
# which under concurrency is another agent's work.
if $COMMIT_CLAIM; then
  TASK_ID="${1:?Usage: claim_task.sh --commit-claim <TASK_ID>}"
  shift || true
  if [[ "${1:-}" == --* ]]; then
    echo "❌ Flags must come before <TASK_ID> (e.g. claim_task.sh --commit-claim ${TASK_ID})." >&2
    echo "   Saw trailing flag: $1" >&2
    exit 1
  fi

  # A review batch's claim is a different record with a different owner, and
  # committing an index.yml flip for it would strand the batch (Phase 156).
  if [[ "$TASK_ID" =~ ^[Bb][Aa][Tt][Cc][Hh]-([0-9]+)$ ]]; then
    echo "❌ ${TASK_ID} is a review batch; its claim lives in review_tasks.md, not tasks/index.yml." >&2
    echo "   Use the script that owns both halves:" >&2
    echo "     bash sysop/scripts/batch_work.sh ${BASH_REMATCH[1]}" >&2
    exit 1
  fi

  if ! MAIN_REPO_ROOT="$(resolve_primary_root)"; then
    echo "❌ git rev-parse --git-common-dir failed; cannot resolve the primary checkout." >&2
    exit 1
  fi
  CC_INDEX="${MAIN_REPO_ROOT}/tasks/index.yml"
  if [[ ! -f "$CC_INDEX" ]]; then
    echo "❌ ${CC_INDEX} not found — there is no task index to commit a claim into." >&2
    exit 1
  fi

  # Fail-closed before taking the mutex: a held lock that then discovers it has no
  # interpreter would refuse every other writer for the duration of a doomed run.
  if ! resolve_yaml_python; then
    echo "❌ python3 + PyYAML is required to flip tasks/index.yml (a hand-edit risks a" >&2
    echo "   lock/status desync). Nothing was written." >&2
    echo "   fix: python3 -m venv .venv && .venv/bin/pip install pyyaml   (PEP-668-safe)" >&2
    exit 1
  fi

  CC_LOCKS_DIR="${MAIN_REPO_ROOT}/sysop/runtime/locks"
  tracker_lock_acquire "$CC_LOCKS_DIR" "the claim commit for ${TASK_ID}" \
    "nothing was written: no status flip, no commit" || exit 1
  # EXIT covers HUP/TERM/INT together; the INT/TERM arm exists only to set 130.
  # `tracker_lock_release` is idempotent, so the EXIT trap is left armed.
  trap 'tracker_lock_release' EXIT
  trap 'tracker_lock_release; exit 130' INT TERM

  # `main-push-guard.md` Rule A, INSIDE the critical section — outside it, HEAD
  # could move between the check and the commit. The branch is resolved, never
  # asserted as the literal `main` (`Q-377`).
  # NO `2>/dev/null`. `resolve_default_branch` refuses with six lines naming the
  # exact `git remote set-head` command that fixes an ambiguous main/master repo,
  # and swallowing them left the operator a dead end — worse here than elsewhere,
  # because this step no longer prints `default_branch.sh` for them to run bare.
  if ! CC_DEFAULT_BRANCH="$(resolve_default_branch "$MAIN_REPO_ROOT")"; then
    echo "❌ Refusing to commit the claim until the default branch is unambiguous." >&2
    echo "   Nothing was written." >&2
    exit 1
  fi
  CC_HEAD="$(git -C "$MAIN_REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ "$CC_HEAD" != "$CC_DEFAULT_BRANCH" ]]; then
    echo "❌ The primary checkout is on '${CC_HEAD}', not '${CC_DEFAULT_BRANCH}' — STOP." >&2
    echo "   A concurrent actor moved HEAD. Reconcile via git reflog rather than" >&2
    echo "   committing this claim onto the wrong branch. Nothing was written." >&2
    exit 1
  fi

  set +e
  CC_OUT=$(TASK_ID="$TASK_ID" INDEX_PATH="$CC_INDEX" MAIN_ROOT="$MAIN_REPO_ROOT" python3 - <<'PY' 2>&1
import os, sys, tempfile

try:
    import yaml
except ImportError:
    print("PYYAML_MISSING", file=sys.stderr)
    sys.exit(1)

task_id = os.environ["TASK_ID"]
# realpath BOTH sides. On macOS `/tmp` is a symlink to `/private/tmp`, so
# resolving only the index yields a relpath that escapes the repo and `git add`
# refuses with "is outside repository" — which is how the first cut of this fix
# broke all three index shapes at once, loudly.
main_root = os.path.realpath(os.environ["MAIN_ROOT"])
# Resolve ONCE, here, and hand the answer back to the shell. The writer and the
# committer used to disagree about which file "tasks/index.yml" names: this side
# followed the symlink, while `git diff HEAD -- tasks/index.yml` and
# `git commit -- tasks/index.yml` saw only the tracked path. On a symlinked index
# the two never met, so the mode reported "nothing to commit (resume path)" and
# exited 0 over an uncommitted flip — the exact Q-397 signature it exists to
# prevent, found by Phase 261's own review round.
index_path = os.path.realpath(os.environ["INDEX_PATH"])
rel = os.path.relpath(index_path, main_root)

with open(index_path, encoding="utf-8") as f:
    data = yaml.safe_load(f)

# `or {}` here reported a mid-truncate read as NOT_FOUND — "TECH-0001 not found in
# tasks/index.yml" for a task plainly present — which is the misdiagnosis this whole
# phase exists to remove, in the code written to remove it. Step 4a refuses the same
# condition in words; so does this. (Phase 261's own review round.)
if data is None:
    print("EMPTY_READ")
    sys.exit(0)

found = changed = False
for t in data.get("tasks", []):
    if t.get("id") == task_id:
        found = True
        cur = t.get("status")
        if cur == "in_progress":
            pass
        elif cur == "open":
            t["status"] = "in_progress"
            changed = True
        else:
            print(f"UNEXPECTED:{cur}")
            sys.exit(0)
        break

if not found:
    print("NOT_FOUND")
    sys.exit(0)

if changed:
    # tempfile + os.replace (Phase 201's shape), NOT a truncate in place. This used
    # to cite `/review-close` Step 7's roster of writers "still truncating"; the roster
    # is in Step 4c, not Step 7, and Phase 263 converted the last of them, so no writer
    # of tasks/index.yml truncates in place any more (`Q-404`, whose open half is the
    # MUTEX). mkstemp rather than a fixed `<path>.tmp` so the name cannot
    # collide the way `Q-382` describes. Same directory, so the replace is atomic.
    # `realpath` above means a symlinked index is written THROUGH, not replaced,
    # and the mode is carried across.
    mode = os.stat(index_path).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(index_path),
                               prefix=os.path.basename(index_path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False,
                           allow_unicode=True, width=120)
        os.chmod(tmp, mode)
        os.replace(tmp, index_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print("FLIPPED:" + rel)
else:
    print("ALREADY_IN_PROGRESS:" + rel)
PY
)
  CC_RC=$?
  set -e
  # Read the SENTINEL off the last line, not the whole capture. `2>&1` folds any
  # interpreter chatter — a sitecustomize.py print, a DeprecationWarning, a locale
  # warning, a .pth import — into $CC_OUT, and an exact match against the whole
  # thing then reported "Could not update" over a flip that had in fact succeeded.
  # Anything the interpreter said is still surfaced below rather than swallowed
  # (Phase 135: a silent abort and a clean run must not look identical).
  CC_SENTINEL=$(printf '%s\n' "$CC_OUT" | tail -n 1)
  CC_CHATTER=$(printf '%s\n' "$CC_OUT" | sed '$d')
  [[ -n "$CC_CHATTER" ]] && printf '%s\n' "$CC_CHATTER" >&2
  CC_REL="${CC_SENTINEL#*:}"
  case "$CC_SENTINEL" in
    FLIPPED:*)
      # The re-flip arm. Reaching it means Step 4a's flip was lost between 4a and
      # here — say so, because a silent repair looks identical to a clean run.
      echo "✅ ${TASK_ID} → in_progress in ${CC_REL} (re-flipped: the Step 4a edit was not on disk)." ;;
    ALREADY_IN_PROGRESS:*)
      echo "ℹ️  ${TASK_ID} is already in_progress in ${CC_REL}." ;;
    EMPTY_READ)
      echo "❌ tasks/index.yml read as empty — a concurrent writer was mid-write." >&2
      echo "   Nothing was written; re-run this step." >&2; exit 1 ;;
    NOT_FOUND)
      echo "❌ ${TASK_ID} not found in tasks/index.yml. Nothing was written." >&2; exit 1 ;;
    UNEXPECTED:*)
      echo "❌ ${TASK_ID} status is '${CC_SENTINEL#UNEXPECTED:}', not open or in_progress — refusing to claim." >&2
      echo "   Nothing was written." >&2; exit 1 ;;
    *)
      echo "❌ Could not update tasks/index.yml (rc=${CC_RC}): ${CC_OUT}" >&2
      echo "   Nothing was committed." >&2; exit 1 ;;
  esac

  # Compare the working tree against HEAD for this path only, so the resume path
  # (Step 4a wrote nothing, status already in_progress) is a clean no-op rather
  # than a `git commit` that aborts with "nothing to commit" and reads as a
  # failed claim — the idempotence Step 4d's `--quiet ||` test bought.
  # `git add` FIRST, and on `$CC_REL`. Two reasons, both measured by the round:
  # `git add` follows a symlinked path to the file that actually changed, and it
  # is the only thing that brings an UNTRACKED index into the index at all — the
  # deleted Step 4d block did this and got both cases right, so dropping it was a
  # regression, not a simplification. The staged diff is then the honest probe.
  git -C "$MAIN_REPO_ROOT" add -- "$CC_REL" || {
    echo "❌ Could not stage ${CC_REL}. Nothing was committed." >&2; exit 1; }
  if git -C "$MAIN_REPO_ROOT" diff --cached --quiet -- "$CC_REL"; then
    echo "ℹ️  ${CC_REL} already matches HEAD — nothing to commit (resume path)."
  else
    git -C "$MAIN_REPO_ROOT" commit -q -m "claim: mark ${TASK_ID} as in-progress" \
      -- "$CC_REL" || {
        echo "❌ git commit failed — the flip is on disk but uncommitted." >&2
        echo "   Re-run: bash sysop/scripts/claim_task.sh --commit-claim ${TASK_ID}" >&2
        exit 1; }
    echo "✅ Committed the claim for ${TASK_ID} on ${CC_DEFAULT_BRANCH}."
  fi
  tracker_lock_release
  exit 0
fi

# ── Release (un-claim) ───────────────────────────────────────
# The sanctioned inverse of a claim. Mutations are ordered so any early exit
# leaves a validator-consistent state: pre-flight the index.yml flip (bail
# before touching anything if we can't do it safely) → remove the worktree
# (abort untouched if it's dirty and --force wasn't passed) → flip index.yml →
# remove the lock. A dirty-worktree abort leaves the full claim intact; a
# freak failure after the worktree is gone leaves an orphaned-but-consistent
# claim that re-running --release recovers.
if $RELEASE; then
  TASK_ID="${1:?Usage: claim_task.sh --release [--delete-branch] [--force] <TASK_ID>}"
  shift || true
  # Flags are only consumed *before* the positional, so a trailing flag
  # (e.g. `--release FEAT-X --force`) would silently no-op — reject it loudly
  # rather than abort a dirty-worktree release and tell the user to add the very
  # flag they already passed.
  if [[ "${1:-}" == --* ]]; then
    echo "❌ Flags must come before <TASK_ID> (e.g. claim_task.sh --release --force ${TASK_ID})." >&2
    echo "   Saw trailing flag: $1" >&2
    exit 1
  fi

  # A batch claim has a second half this script does not own. `batch_work.sh`
  # committed `Pending` → `In Progress` in review_tasks.md, and releasing the
  # lock without reverting that would leave the batch reading as claimed with
  # nothing holding it — the half-revert that strands a batch. Refuse and point
  # at the script that owns both halves. (Phase 156.)
  if [[ "$TASK_ID" =~ ^[Bb][Aa][Tt][Cc][Hh]-([0-9]+)$ ]]; then
    echo "❌ ${TASK_ID} is a review batch, and its claim lives in review_tasks.md, not tasks/index.yml." >&2
    echo "   Releasing only the lock here would leave the batch marked 'In Progress' forever." >&2
    echo "   Use the script that owns both halves:" >&2
    echo "     bash sysop/scripts/batch_work.sh --release ${BASH_REMATCH[1]}" >&2
    exit 1
  fi

  REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "❌ Not inside a git repository." >&2
    exit 1
  }

  # Resolve the canonical sysop/runtime/locks/ under the main repo (same as the claim path).
  GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
  if [[ -z "$GIT_COMMON_DIR" ]]; then
    echo "❌ git rev-parse --git-common-dir failed; cannot resolve canonical sysop/runtime/locks/ location." >&2
    exit 1
  fi
  if [[ "$GIT_COMMON_DIR" = /* ]]; then
    MAIN_REPO_ROOT="$(dirname "$GIT_COMMON_DIR")"
  else
    MAIN_REPO_ROOT="$(dirname "$(CDPATH= cd "$GIT_COMMON_DIR" && pwd)")"
  fi
  LOCKS_DIR="${MAIN_REPO_ROOT}/sysop/runtime/locks"
  LOCK_FILE="${LOCKS_DIR}/${TASK_ID}.lock"

  if [[ ! -f "$LOCK_FILE" ]]; then
    echo "❌ Task ${TASK_ID} is not locked — nothing to release." >&2
    echo "   (No lock at ${LOCK_FILE}.)" >&2
    echo "   If tasks/index.yml still shows it in_progress, that's a stale-claim" >&2
    echo "   desync — reconcile it by hand or via /sitrep, not with --release." >&2
    exit 1
  fi

  # Recorded at claim time — so the operator supplies only <TASK_ID>.
  LOCK_BRANCH=$(awk '/^branch:/{sub(/^branch: */, ""); print; exit}' "$LOCK_FILE")
  LOCK_WORKSPACE=$(awk '/^workspace:/{sub(/^workspace: */, ""); print; exit}' "$LOCK_FILE")
  # `mode:` has been written by every claim since it existed and read back by
  # NOTHING until Phase 220. That was harmless while `--clone` could not
  # complete a claim (it aborted before the lock block), so no clone lock
  # existed to release. Phase 220 fixed the claim, which made the release
  # reachable — and `git worktree remove` fatals on a clone, so `--release`
  # owned neither half of the reversal for exactly the mode this phase enabled.
  # Found by the round, which is the "run the consumers, not just the change"
  # rule doing its job one step downstream.
  LOCK_MODE=$(awk '/^mode:/{sub(/^mode: */, ""); print; exit}' "$LOCK_FILE")

  echo "🔓 Releasing ${TASK_ID}"
  echo "   branch:    ${LOCK_BRANCH:-<none recorded>}"
  echo "   workspace: ${LOCK_WORKSPACE:-<none recorded>}"
  echo ""

  INDEX="${MAIN_REPO_ROOT}/tasks/index.yml"

  # Pre-flight the status flip. If there's an index.yml to update but we can't
  # do a safe PyYAML round-trip here, mutate NOTHING — removing the lock while
  # leaving index.yml in_progress would create exactly the desync the validator
  # flags. Hand off the whole reversal to the operator's venv python.
  if [[ -f "$INDEX" ]]; then
    # Same resolution as --entry-state: prefer the project venv (anchored on
    # the MAIN checkout, since --release may be run from any subdirectory),
    # fall back to PATH, and only refuse when nothing can import yaml.
    if ! resolve_yaml_python; then
      echo "❌ tasks/index.yml exists but python3 + PyYAML isn't available here, so I" >&2
      echo "   can't safely flip its status (a hand-edit risks a lock/status desync)." >&2
      echo "   Tried .venv/bin/python3 and venv/bin/python3 under ${MAIN_REPO_ROOT} then ${REPO_ROOT}, then python3 on PATH." >&2
      echo "   fix: python3 -m venv .venv && .venv/bin/pip install pyyaml   (PEP-668-safe)" >&2
      echo "   Or run the manual reversal with an interpreter that has PyYAML:" >&2
      if [[ "$LOCK_MODE" == "clone" ]]; then
        # `git worktree remove` fatals on a clone, so printing it here would
        # hand the operator a command that cannot work — the same defect the
        # release path itself carried until this phase's round.
        echo "     rm -rf ${LOCK_WORKSPACE:-<clone dir>}   # a full clone, not a linked worktree" >&2
      else
        echo "     git worktree remove ${LOCK_WORKSPACE:-<worktree>}   # add --force to discard uncommitted work" >&2
      fi
      echo "     rm ${LOCK_FILE}" >&2
      echo "     # then flip ${TASK_ID}'s status: in_progress → open in tasks/index.yml" >&2
      # Bare python3, NOT .venv/bin/python3: validate_tasks.py self-resolves venv
      # PyYAML itself (Phase 182), so this line works once the fix above lands a
      # venv — under any layout — whereas a .venv/bin/python3 command word is
      # `command not found` on the venv/, poetry and conda consumers, and this
      # branch is reached only where no interpreter on the host has PyYAML yet.
      echo "     python3 sysop/scripts/validate_tasks.py   # after the fix above" >&2
      exit 1
    fi
  fi

  # ── Take the tracker write mutex before the first mutation (Phase 261) ──
  # Everything above this line is a refusal that writes nothing, so the mutex is
  # taken as late as possible and never held across a doomed run. Everything below
  # it mutates: the worktree, then `tasks/index.yml`, then the lock. `--release`
  # read-modify-writes the same index the claim path does, so without this it
  # raced a concurrent claim exactly as two claims raced each other (`Q-397`).
  # The EXIT trap covers every `exit 1` in the mutation region below.
  tracker_lock_acquire "$LOCKS_DIR" "the release of ${TASK_ID}" \
    "nothing was released — the claim is intact" || exit 1
  trap 'tracker_lock_release' EXIT
  trap 'tracker_lock_release; exit 130' INT TERM

  # ── Remove the worktree (never the main worktree) ──
  if [[ "$LOCK_MODE" == "clone" ]]; then
    # A clone is not a linked worktree: `git worktree remove` fatals on it
    # ("is not a working tree"), with or without --force, and the claim is
    # then left un-released with its lock intact — the state Phase 91 built
    # --release to prevent. Release the lock and hand the directory back to
    # the operator rather than deleting a full checkout that may hold work
    # this script never saw.
    if [[ -n "$LOCK_WORKSPACE" && -d "$LOCK_WORKSPACE" ]]; then
      echo "ℹ️  Clone workspace ${LOCK_WORKSPACE} is a full clone, not a linked worktree."
      echo "   The lock and the task status are being released; the directory is left in"
      echo "   place because it can hold commits this repository has never seen."
      echo "   Delete it yourself when you are sure: rm -rf ${LOCK_WORKSPACE}"
    else
      echo "ℹ️  No clone directory recorded, or already gone."
    fi
  elif [[ -n "$LOCK_WORKSPACE" && -d "$LOCK_WORKSPACE" ]]; then
    WS_REAL="$(cd "$LOCK_WORKSPACE" && pwd -P 2>/dev/null || echo "$LOCK_WORKSPACE")"
    MAIN_REAL="$(cd "$MAIN_REPO_ROOT" && pwd -P 2>/dev/null || echo "$MAIN_REPO_ROOT")"
    # `-ef` and `cwd_is_inside`, not string compares. `pwd -P` resolves symlinks
    # but NOT case, and these three paths reach the shell from three different
    # places — the lock file, `git rev-parse`, and the user's own `cd` — so on a
    # case-insensitive filesystem two of them can name the same directory and
    # compare unequal. Both guards below fail OPEN in that state: the first
    # stops protecting the main worktree, and the second stops noticing that you
    # are standing in the directory about to be removed.
    if [[ "$WS_REAL" -ef "$MAIN_REAL" ]]; then
      echo "⚠️  Recorded workspace is the main worktree — refusing to remove it."
    elif cwd_is_inside "$WS_REAL"; then
      echo "❌ You're inside the worktree being released (${WS_REAL})." >&2
      echo "   cd to the main checkout (${MAIN_REAL}) and re-run." >&2
      exit 1
    elif $FORCE; then
      if git worktree remove --force "$WS_REAL"; then
        echo "✅ Removed worktree ${WS_REAL} (--force)."
      else
        echo "⚠️  Could not remove worktree ${WS_REAL} even with --force (see git message above)." >&2
        echo "    Nothing was released — the claim is intact." >&2
        exit 1
      fi
    elif git worktree remove "$WS_REAL"; then
      echo "✅ Removed worktree ${WS_REAL}."
    else
      echo "⚠️  Could not remove worktree ${WS_REAL} (uncommitted changes? see git message above)." >&2
      echo "    Re-run with --force to discard, or commit/stash the work first." >&2
      echo "    Nothing was released — the claim is intact." >&2
      exit 1
    fi
  else
    echo "ℹ️  No linked worktree to remove (branch/lock-only claim, or already gone)."
  fi

  # ── Flip index.yml status in_progress → open (PyYAML round-trip, mirrors
  #    /claim-task Step 4a in reverse) ──
  if [[ -f "$INDEX" ]]; then
    # A single-quoted heredoc inside $() can't carry a trailing `|| …` on the
    # opener line, so fence set -e instead: python exits 0 on every handled
    # outcome (sentinel on stdout), and only a genuine crash exits non-zero —
    # its traceback lands in FLIP_OUT and falls through to the `*)` guard.
    set +e
    FLIP_OUT=$(TASK_ID="$TASK_ID" INDEX_PATH="$INDEX" python3 - <<'PY' 2>&1
import os, sys, tempfile, yaml

task_id = os.environ["TASK_ID"]
index_path = os.environ["INDEX_PATH"]

with open(index_path, encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

found = False
for t in data.get("tasks", []):
    if t.get("id") == task_id:
        found = True
        cur = t.get("status")
        if cur == "open":
            print("ALREADY_OPEN"); sys.exit(0)
        if cur != "in_progress":
            print(f"UNEXPECTED:{cur}"); sys.exit(0)
        t["status"] = "open"
        break

if not found:
    print("NOT_FOUND"); sys.exit(0)

# tempfile + os.replace, NOT a truncate in place — the same conversion Phase 261
# made to Step 4a and `--commit-claim`, for the same reason: a truncate makes every
# concurrent READER see a zero-length file. `mkstemp` rather than a fixed
# `<path>.tmp` so two writers cannot collide on the temp name (`Q-382`'s class).
# `realpath` so a symlinked index is written THROUGH, and the mode is carried over.
_real = os.path.realpath(index_path)
_mode = os.stat(_real).st_mode & 0o7777
_fd, _tmp = tempfile.mkstemp(dir=os.path.dirname(_real),
                             prefix=os.path.basename(_real) + ".", suffix=".tmp")
try:
    with os.fdopen(_fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f,
            sort_keys=False, default_flow_style=False, allow_unicode=True, width=120,
        )
    os.chmod(_tmp, _mode)
    os.replace(_tmp, _real)
except BaseException:
    if os.path.exists(_tmp):
        os.unlink(_tmp)
    raise
print("FLIPPED")
PY
)
    set -e
    case "$FLIP_OUT" in
      FLIPPED)      echo "✅ Flipped ${TASK_ID} → open in tasks/index.yml." ;;
      ALREADY_OPEN) echo "ℹ️  ${TASK_ID} was already open in tasks/index.yml." ;;
      NOT_FOUND)    echo "⚠️  ${TASK_ID} not found in tasks/index.yml (releasing the lock anyway)." ;;
      UNEXPECTED:*) echo "⚠️  ${TASK_ID} status is '${FLIP_OUT#UNEXPECTED:}', not in_progress — not flipping (releasing the lock anyway)." ;;
      *)
        echo "❌ Could not update tasks/index.yml (${FLIP_OUT})." >&2
        echo "   The worktree is gone but the lock is kept so state stays consistent." >&2
        echo "   Flip ${TASK_ID}'s status by hand, then re-run --release to clear the lock." >&2
        exit 1
        ;;
    esac
  fi

  # ── Remove the lock ──
  rm -f "$LOCK_FILE"
  echo "✅ Removed lock ${LOCK_FILE}."

  # ── Optionally delete the branch ──
  if $DELETE_BRANCH && [[ -n "$LOCK_BRANCH" ]]; then
    CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
    if [[ "$LOCK_BRANCH" == "$CUR_BRANCH" ]]; then
      echo "⚠️  ${LOCK_BRANCH} is the current branch — not deleting it. Check out another branch first, then: git branch -D ${LOCK_BRANCH}"
    elif git show-ref --verify --quiet "refs/heads/${LOCK_BRANCH}"; then
      git branch -D "$LOCK_BRANCH"
      echo "✅ Deleted branch ${LOCK_BRANCH}."
    else
      echo "ℹ️  Branch ${LOCK_BRANCH} already gone."
    fi
  fi

  # ── Validate + commit hint (never commit) ──
  echo ""
  if [[ -f "${MAIN_REPO_ROOT}/sysop/scripts/validate_tasks.py" && -f "$INDEX" ]]; then
    if (cd "$MAIN_REPO_ROOT" && python3 sysop/scripts/validate_tasks.py); then
      echo "✅ Queue validates."
    else
      echo "⚠️  validate_tasks.py reported issues (see above) — resolve before committing."
    fi
  fi

  echo ""
  echo "📝 Next step — commit the release (claim_task.sh never commits for you):"
  echo "   cd ${MAIN_REPO_ROOT}"
  echo "   git add tasks/index.yml && git commit -m \"chore: release ${TASK_ID}\""
  # Explicit release on the success path; the EXIT trap stays armed and is a
  # no-op once this has run (`tracker_lock_release` is idempotent).
  tracker_lock_release
  exit 0
fi

TASK_ID="${1:?Usage: claim_task.sh [--branch|--clone|--lock] <TASK_ID> <BRANCH_NAME> [AGENT_NAME]}"
BRANCH_NAME="${2:?Usage: claim_task.sh [--branch|--clone|--lock] <TASK_ID> <BRANCH_NAME> [AGENT_NAME]}"
AGENT_NAME="${3:-anonymous}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

TASK_LOWER=$(echo "$TASK_ID" | tr '[:upper:]' '[:lower:]')
# Where the workspace goes. `WORKTREE_ROOT` (Phase 262) names the PARENT
# DIRECTORY; `WORKTREE_PREFIX` names the leaf. Unset, the root is the repo's own
# parent, which is the behaviour every prior release had, byte for byte.
#
# The reason it exists is a sandboxed harness: Codex is given a writable-path
# allow-list, and the default construction forces that list to include the repo's
# whole parent directory — every sibling checkout with it. `WORKTREE_ROOT` lets a
# consumer declare one directory instead.
#
# Downstream readers need no change and get none, but the reason splits in two
# and only one half is unconditional. VERIFIED by execution, both halves:
#
#   * git itself. `cleanup_worktrees.sh` and `/sitrep` arm (i) call
#     `git worktree list --porcelain`, which reports the absolute path of every
#     linked worktree wherever it sits. Location-agnostic ALWAYS.
#   * the lock's `workspace:`. `/sitrep` arm (ii), `scope_overlap.py` and
#     `--release` here read it, and it records the absolute path this variable
#     produced. But the lock is written ONLY under `--lock` (see the write below),
#     so this half is location-agnostic only when a lock exists. That is not a
#     regression `WORKTREE_ROOT` introduces: without `--lock` there is no lock for
#     those three to read today either, whatever the path.
#
# THREE sites RECONSTRUCT `../<prefix>-<task>` as a fallback, all of them for a
# lock with a blank or damaged `workspace:`: `sitrep_survey.py`'s arm (iii), and
# /review-close's Step 3b arm (iii) and Step 3c pre-gate globs. (An earlier
# version of this comment said "one site" and the phase's own record said "two" —
# the count was asserted, not grepped.) All three already cannot see
# `WORKTREE_PREFIX`, and `WORKTREE_ROOT` joins that same stated limit for the
# same reason: neither is recorded as such, so with the `workspace:` gone there
# is nothing to reconstruct the override from.
WORKTREE_PARENT="${WORKTREE_ROOT:-${REPO_ROOT}/..}"
# Scoped to the modes that BUILD a workspace. `--branch` never reads WORKTREE_DIR,
# and `--entry-state` / `--release` / `--commit-claim` exit before this point, so
# validating the variable for them would refuse work it does not govern — the
# variable is meant to live in a sandbox's persistent environment, where a stale
# value would then block a mode that never touches it.
#
# The four guards (newline / exists / writable / not inside a working tree) moved
# to `worktree_root_parent` in `_git_lib.sh` at Phase 264, so `batch_work.sh`
# could honour the same variable (`Q-407`) without re-deriving them. Three of the
# four were defects found by EXECUTION in Phase 262's round, not by design, which
# is why the instruction on `Q-407` was to reuse rather than re-derive.
#
# `resolve_primary_root`, not `$REPO_ROOT`: the containment arm has to compare
# against the PRIMARY checkout, because `--show-toplevel` answers "which worktree
# am I standing in" and claiming from a worktree is a prescribed invocation.
if [[ -n "${WORKTREE_ROOT:-}" && ( "$MODE" = "worktree" || "$MODE" = "clone" ) ]]; then
  _primary_root="$(resolve_primary_root)" || _primary_root="$REPO_ROOT"
  WORKTREE_PARENT="$(worktree_root_parent "$_primary_root")" || exit 1
fi
WORKTREE_DIR="${WORKTREE_PARENT}/${WORKTREE_PREFIX:-$(basename "$REPO_ROOT")}-${TASK_LOWER}"

# ── Lock: guard against already-locked task ──────────────────
# Locks live under the main repo's sysop/runtime/locks/, resolved via git-common-dir so
# the canonical location is the same whether this script runs from the main
# checkout or from a worktree. The validator uses the same resolution.
if $USE_LOCK; then
  GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
  if [[ -z "$GIT_COMMON_DIR" ]]; then
    echo "❌ git rev-parse --git-common-dir failed; cannot resolve canonical sysop/runtime/locks/ location." >&2
    exit 1
  fi
  if [[ "$GIT_COMMON_DIR" = /* ]]; then
    MAIN_REPO_ROOT="$(dirname "$GIT_COMMON_DIR")"
  else
    MAIN_REPO_ROOT="$(dirname "$(CDPATH= cd "$GIT_COMMON_DIR" && pwd)")"
  fi
  LOCKS_DIR="${MAIN_REPO_ROOT}/sysop/runtime/locks"
  LOCK_FILE="${LOCKS_DIR}/${TASK_ID}.lock"

  if [[ -f "$LOCK_FILE" ]]; then
    echo "❌ Task ${TASK_ID} is already locked:"
    cat "$LOCK_FILE"
    exit 1
  fi

  # Show any existing locks (NUL-delimited; safe for paths with spaces).
  if [[ -d "$LOCKS_DIR" ]]; then
    HAS_LOCKS=false
    while IFS= read -r -d '' f; do
      if ! $HAS_LOCKS; then
        echo "ℹ️  Currently active locks:"
        HAS_LOCKS=true
      fi
      # Anchor on the first `status:` line and emit only the value token
      # so a malformed lock (e.g. `# status: ...` comment, or a later line
      # like `notes: status: foo`) doesn't bleed into the displayed status.
      # `awk` with `exit` after the first match avoids the `grep | sed`
      # pipefail trap (pipefail + empty grep match = command failure under
      # `set -euo pipefail`).
      LOCK_STATUS=$(awk '/^status:/{sub(/^status: */, ""); print; exit}' "$f")
      LOCK_STATUS="${LOCK_STATUS:-unknown}"
      LOCK_BRANCH=$(awk '/^branch:/{sub(/^branch: */, ""); print; exit}' "$f")
      echo "   • $(basename "$f" .lock) [${LOCK_STATUS}] — ${LOCK_BRANCH}"
      while IFS= read -r line; do
        echo "     ${line}"
      done < <(grep '^  - ' "$f" 2>/dev/null || true)
    done < <(find "$LOCKS_DIR" -name "*.lock" -not -name '.gitkeep' -print0 2>/dev/null)
    if $HAS_LOCKS; then echo ""; fi
  fi
fi

# ── Worktree identity preflight (`Q-405`) ────────────────────
#
# Runs HERE — after the lock refusal, before the branch is created — so an
# invocation that is going to be refused leaves NOTHING behind. The first cut of
# this fix put the check in the mode block below, where the branch already
# exists: the refusal then stranded an orphan local ref every time. `--clone`
# states the same principle for its own refusals ("an invocation that is going to
# be refused does not first publish a branch"); this one applies it to the local
# ref as well.
#
# After the lock block, not before it: when a task is BOTH already locked and
# pointed at a foreign directory, "already locked" is the more actionable
# message, and it is the one that was reachable first before this existed.
# `-e || -L`, not `-d`: `-e` FOLLOWS the link, so a DANGLING symlink at this path
# is invisible to it — and a regular file is not a directory either. Both slipped
# past the first cut of this preflight and reached `git worktree add`, which
# lstats, refuses with a bare `fatal: ... already exists` at rc=128, and leaves the
# branch this block exists to protect. `batch_work.sh`'s own preflight had already
# learned this ("`-L` is what sees the link itself"); the asymmetry was the defect,
# found by execution in this phase's round rather than by reading the neighbour.
if [[ "$MODE" == "worktree" ]] \
   && { [[ -e "$WORKTREE_DIR" ]] || [[ -L "$WORKTREE_DIR" ]]; } \
   && ! path_is_worktree_of "$WORKTREE_DIR" "$REPO_ROOT"; then
  echo "❌ '${WORKTREE_DIR}' already exists and is not a worktree of this repository." >&2
  echo "   Adopting it would record another checkout's tree as this claim's" >&2
  echo "   workspace, and this repository cannot release what it never created:" >&2
  echo "   'git worktree remove' answers 'is not a working tree' even with --force," >&2
  echo "   so the lock and the in_progress status would strand permanently." >&2
  echo "   Remove that directory, or set WORKTREE_ROOT / WORKTREE_PREFIX to a path" >&2
  echo "   this checkout does not share with another one, then re-run." >&2
  echo "   Nothing was created." >&2
  exit 1
fi

# ── Create branch (if needed) ────────────────────────────────
if git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}" 2>/dev/null; then
  echo "ℹ️  Branch '${BRANCH_NAME}' already exists."
else
  git branch "$BRANCH_NAME"
  echo "✅ Created branch '${BRANCH_NAME}'."
fi

# ── Mode-specific setup ──────────────────────────────────────
WORKSPACE_PATH="$REPO_ROOT"

if [[ "$MODE" == "worktree" ]]; then
  if [[ -d "$WORKTREE_DIR" ]]; then
    # Reaching here means the preflight above verified this directory is a
    # worktree of THIS repository (`Q-405`) — it is a resume, not an adoption of
    # a stranger's tree. The verification lives up there, not here, so that a
    # refusal happens before the branch is created.
    echo "ℹ️  Worktree directory '${WORKTREE_DIR}' already exists (this repository's — resuming)."
  else
    git worktree add "$WORKTREE_DIR" "$BRANCH_NAME"
    echo "✅ Created worktree at '${WORKTREE_DIR}' on branch '${BRANCH_NAME}'."
  fi
  WORKSPACE_PATH="$WORKTREE_DIR"

  # Deliberately NO hook install here (Phase 150 / internal tracker #202).
  #
  # Worktrees share the main repo's hooks directory ($GIT_COMMON_DIR/hooks), so
  # a worktree never needs its own arm — it already runs whatever the main
  # checkout has armed. Arming from here was worse than redundant:
  # install_hooks.sh resolves its SOURCE from the worktree's toplevel, so this
  # pushed the claimed branch's sysop/scripts/hooks/* into the MAIN checkout's
  # hooks — silently replacing a consumer's armed checks with the shipped
  # skeletons, outside the worktree the claim was supposed to be isolated to.
  #
  # Every case where this call could still change something is a case where it
  # must not: after a fresh install the hooks are already armed; --no-arm-hooks
  # means the consumer opted out on purpose; and during an --update reconcile
  # window Phase 15 / ISSUE-0007 skips arming on purpose. Arm explicitly from
  # the main checkout with `bash sysop/scripts/install_hooks.sh` — the unarmed
  # state is reported by `bash sysop/scripts/self_check.sh`.

elif [[ "$MODE" == "clone" ]]; then
  # ── Q-276: the documented invocation used to abort here ──────
  #
  # Reproduced by execution, both directions, before this fix. The branch is
  # created LOCALLY above and never pushed; a clone of `origin` therefore has no
  # such ref, `git checkout "$BRANCH_NAME"` failed with `pathspec ... did not
  # match`, and `set -euo pipefail` exited 1 — AFTER creating the branch and the
  # clone directory and BEFORE the lock block, so nothing recorded `mode:` or
  # `workspace:`. The only `--clone` workspace that ever worked came from a
  # branch someone had pushed out of band.
  #
  # A SECOND shape was found in the same pass and is the worse of the two,
  # because it exits 0: with the clone directory already present the block
  # short-circuited on "already exists" and never checked anything out, so the
  # script printed `✅ Created branch` and `✅ Lock created`, wrote a lock naming
  # `branch: <BRANCH_NAME>` and `workspace: <dir>`, and told the operator to
  # start working — in a clone still sitting on `main`. `/review-close` Step 0
  # arm (ii) resolves exactly that lock, and Step 3b then collects from it. A
  # push-before-clone fix alone is INERT for this path, which is why both legs
  # are here.
  REMOTE_URL=$(git remote get-url origin 2>/dev/null) || {
    echo "❌ No 'origin' remote found. Cannot clone." >&2
    exit 1
  }

  # Publish the branch so the clone can see it. `--clone` is the one mode whose
  # workspace reads from `origin` rather than from this repository's object
  # store, so publishing is inherent to the mode, not an extra policy: a branch
  # that exists only locally cannot be cloned by definition.
  #
  # Consequence worth stating rather than discovering: the branch is now a
  # PUBLISHED branch, so `/review-close` Step 4a takes its published arm (the
  # `--no-ff` merge, Phase 219 `Q-265`) instead of the local-only arm. That is
  # the correct routing for a branch that really is on the remote.
  # The directory refusals run BEFORE the push, so an invocation that is going
  # to be refused does not first publish a branch. The first cut pushed at the
  # top of the block, so `--clone` against an existing non-git directory left a
  # new branch on origin and then exited 1 — a remote-side side effect of a
  # command that did nothing locally. Pre-220 a claim never touched origin at
  # all, so this is a new surface and worth ordering deliberately.
  if [[ -d "$WORKTREE_DIR" ]]; then
    echo "ℹ️  Clone directory '${WORKTREE_DIR}' already exists."
    # Reporting success over a workspace on the wrong branch is the defect
    # above. Verify, correct if we can, refuse if we cannot — never assume.
    if ! git -C "$WORKTREE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
      echo "❌ '${WORKTREE_DIR}' exists but is not a git repository." >&2
      echo "   Remove it or pick another branch name, then re-run." >&2
      exit 1
    fi
  fi

  # **Identity, not name.** The first cut probed only whether a branch of this
  # NAME existed on origin and skipped the push if so — which is a different
  # question from whether it is THIS branch. Reproduced by the round: claim with
  # `--clone`, `--release --delete-branch` (which runs `git branch -D`, deleting
  # the LOCAL ref only and leaving origin's), then re-claim. The local branch is
  # recreated at `main`; origin still carries the abandoned one; the name probe
  # passes, the push is skipped, and the clone checks out the ABANDONED commits.
  # The operator is told "Start working!" on resurrected work, and
  # /review-close Step 0 arm (ii) resolves that lock.
  #
  # This block was already written to verify-or-refuse the DIRECTORY ("never
  # assume"); it assumed for the ref. Same rule, applied to both.
  REMOTE_SHA=$(git ls-remote --exit-code --heads origin "$BRANCH_NAME" 2>/dev/null | awk '{print $1; exit}') || REMOTE_SHA=""
  LOCAL_SHA=$(git rev-parse --verify --quiet "refs/heads/${BRANCH_NAME}") || LOCAL_SHA=""
  if [[ -n "$REMOTE_SHA" && "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
    echo "ℹ️  Branch '${BRANCH_NAME}' is already on origin at the same commit."
  elif [[ -n "$REMOTE_SHA" ]]; then
    echo "❌ origin already has a DIFFERENT '${BRANCH_NAME}'." >&2
    echo "   local:  ${LOCAL_SHA:-<none>}" >&2
    echo "   origin: ${REMOTE_SHA}" >&2
    echo "   Cloning it would hand you someone else's work — or your own" >&2
    echo "   abandoned work, if this name was released with --delete-branch" >&2
    echo "   (which deletes the local ref and leaves origin's)." >&2
    echo "   Pick another branch name, or reconcile the two refs first." >&2
    exit 1
  else
    git push -u origin "$BRANCH_NAME" || {
      echo "❌ Could not push '${BRANCH_NAME}' to origin." >&2
      echo "   --clone builds its workspace by cloning origin, so the branch has" >&2
      echo "   to exist there. Push it yourself, or use --worktree instead," >&2
      echo "   which needs no remote." >&2
      exit 1
    }
    echo "✅ Pushed '${BRANCH_NAME}' to origin."
  fi

  if [[ -d "$WORKTREE_DIR" ]]; then
    EXISTING_BRANCH=$(git -C "$WORKTREE_DIR" branch --show-current 2>/dev/null || echo "")
    if [[ "$EXISTING_BRANCH" == "$BRANCH_NAME" ]]; then
      echo "✅ Existing clone is already on '${BRANCH_NAME}'."
    else
      git -C "$WORKTREE_DIR" fetch origin "$BRANCH_NAME" >/dev/null 2>&1 || true
      if git -C "$WORKTREE_DIR" checkout "$BRANCH_NAME" >/dev/null 2>&1; then
        echo "✅ Existing clone moved from '${EXISTING_BRANCH:-<detached>}' to '${BRANCH_NAME}'."
      else
        echo "❌ '${WORKTREE_DIR}' exists but is on '${EXISTING_BRANCH:-<detached>}'," >&2
        echo "   and '${BRANCH_NAME}' could not be checked out there." >&2
        echo "   Refusing to record it as this claim's workspace: a lock naming a" >&2
        echo "   workspace on the wrong branch sends /review-close Step 3b to" >&2
        echo "   collect from it. Resolve the directory, then re-run." >&2
        exit 1
      fi
    fi
  else
    git clone "$REMOTE_URL" "$WORKTREE_DIR"
    git -C "$WORKTREE_DIR" checkout "$BRANCH_NAME"
    echo "✅ Cloned to '${WORKTREE_DIR}' and checked out '${BRANCH_NAME}'."
  fi
  WORKSPACE_PATH="$WORKTREE_DIR"
fi

# ── Write lock file (only if --lock) ────────────────────────
if $USE_LOCK; then
  mkdir -p "$LOCKS_DIR"
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # Expiry = 4 hours from now (macOS-compatible). Fall back to POSIX
  # shell-arithmetic (`date +%s` + 14400 seconds → reformat) so a `date`
  # variant that supports neither BSD `-v` nor GNU `-d` still produces a valid
  # timestamp rather than a blank `expires:` field. Abort with a clear error if
  # all three paths fail.
  #
  # **Why, stated correctly.** This comment used to claim, **incorrectly**, that a
  # blank `expires:` is what "downstream lock-validator tooling treats as
  # malformed". **No such
  # tooling exists, and none ever has** — the field is read by NO runtime
  # consumer: `sitrep_survey.py` parses it into a `Lock` dataclass field that
  # nothing reads, and lock staleness is decided from `started:` alone
  # (`_classify_task`'s stale check). An earlier draft of this comment added
  # "and mtime", which is false for locks — the only `st_mtime` reads in that
  # file are pending-round markers and round receipts. Correcting a falsehood
  # is exactly when a new one gets written in; its own round caught this.
  # A reader who believed the old sentence would go looking for a validator to
  # satisfy, or would decide the field is load-bearing and preserve it for the
  # wrong reason.
  #
  # The fallback chain stays, on the two reasons that are real. (1) The lock is
  # a **human-readable record**: `/claim-task`, `/sitrep`'s stale-claim report
  # and `--entry-state` all print or surface it, and a field that is blank on
  # exactly the consumers with the least common `date` is a record that degrades
  # silently where it is hardest to debug. (2) The field is **pinned by tests**
  # (`tests/test_claim_task_sh.py`, `tests/test_batch_claim_kinds.py`), so it is
  # part of the lock's shipped shape whether or not runtime reads it — removing
  # or blanking it is a contract change, not a cleanup.
  if date -v+4H +"%Y-%m-%dT%H:%M:%SZ" &>/dev/null; then
    EXPIRES_TIMESTAMP=$(date -u -v+4H +"%Y-%m-%dT%H:%M:%SZ")
  elif EXPIRES_TIMESTAMP=$(date -u -d "+4 hours" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null); then
    : # GNU date succeeded
  else
    EXPIRY_EPOCH=$(( $(date +%s) + 14400 ))
    EXPIRES_TIMESTAMP=$(date -u -r "$EXPIRY_EPOCH" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
      || date -u "+%Y-%m-%dT%H:%M:%SZ" -d "@$EXPIRY_EPOCH" 2>/dev/null \
      || echo "")
    if [[ -z "$EXPIRES_TIMESTAMP" ]]; then
      echo "❌ Unable to compute lock expiry timestamp — no compatible \`date\` variant found." >&2
      exit 1
    fi
  fi

  # ── Atomic create — closes the claim-time TOCTOU ──────────
  # The existence guard (`if [[ -f "$LOCK_FILE" ]]` near the top of the claim
  # path) runs ~200 lines BEFORE this write, and the window between them is not
  # a few instructions: branch creation and `git worktree add` both sit inside
  # it, so it is wide in wall-clock terms, not just in theory. Two agents that
  # each passed the guard both arrived here, and a plain `cat >` truncates —
  # the second claimant silently OVERWROTE the first's lock. The result is two
  # worktrees on one task with a single lock naming only the second agent, which
  # is precisely the double-claim every reader of this file exists to prevent
  # (`next_task.py` skips a locked task; `/sitrep` reports one owner).
  #
  # `set -C` (noclobber) makes `>` open the file O_EXCL, so the create either
  # wins outright or fails — there is no truncate-an-existing-file outcome. The
  # subshell scopes the option so the rest of this script is unaffected, and
  # stderr is dropped because the shell's own noclobber message ("cannot
  # overwrite existing file") describes a redirection, not a lost claim.
  #
  # Building the content first and writing it in one `printf` also removes a
  # second failure the heredoc form had: a death mid-heredoc left a PARTIAL lock
  # on disk, which parses as a lock with missing fields rather than as no lock.
  LOCK_CONTENT=$(cat <<EOF
task_id: ${TASK_ID}
status: in_progress
agent: ${AGENT_NAME}
branch: ${BRANCH_NAME}
mode: ${MODE}
workspace: ${WORKSPACE_PATH}
started: ${TIMESTAMP}
expires: ${EXPIRES_TIMESTAMP}
files_impacted:
  - (update manually or via git diff --name-only main...HEAD)
plan_summary: (update with a one-line description of the work)
notes:
EOF
)
  if ! ( set -C; printf '%s\n' "$LOCK_CONTENT" > "$LOCK_FILE" ) 2>/dev/null; then
    echo "" >&2
    # Two very different failures reach here and `2>/dev/null` has just discarded
    # the shell's own message, so DISCRIMINATE before naming a cause. noclobber
    # refuses because the file exists; everything else (EACCES on the locks dir, a
    # read-only filesystem, ENOSPC) refuses because the write could not happen at
    # all. Reporting "claimed by another agent" for a read-only locks/ sends the
    # operator hunting for a rival that does not exist — this phase's round produced
    # exactly that, with no second claimant anywhere.
    if [[ -e "$LOCK_FILE" ]]; then
      echo "❌ Task ${TASK_ID} was claimed by another agent while this claim was setting up." >&2
      echo "   Their lock (${LOCK_FILE}):" >&2
      sed 's/^/     /' "$LOCK_FILE" >&2 2>/dev/null || echo "     (unreadable)" >&2
    else
      echo "❌ Could not write the lock file ${LOCK_FILE} — no rival claim; the write itself failed." >&2
      echo "   Check that ${LOCKS_DIR} exists and is writable, and that the filesystem is not full or read-only." >&2
    fi
    echo "" >&2
    # The recovery is NOT `--release`: that path refuses when the caller does
    # not hold the lock ("not locked — nothing to release" only fires on an
    # ABSENT lock, and here the lock exists and belongs to the winner), so
    # pointing at it would hand the loser a command that either refuses or —
    # worse — releases the winner's claim. Name the objects this run actually
    # created instead — and branch on MODE, because `git worktree remove` fatals
    # on a clone AND on the main checkout. In `--branch` mode no worktree was
    # created at all and WORKSPACE_PATH is the MAIN CHECKOUT, so the unbranched
    # form printed the main working tree at the operator: `fatal: is a main
    # working tree`, verified. This file already branches on mode at the
    # PyYAML-missing reversal above; the first cut of this block did not, which
    # re-minted the very defect that guard exists to prevent.
    case "$MODE" in
      worktree)
        echo "   This run already created a branch and a worktree. Remove them by hand:" >&2
        echo "     git worktree remove \"${WORKSPACE_PATH}\"   # add --force to discard uncommitted work" >&2
        echo "     git branch -D \"${BRANCH_NAME}\"" >&2
        ;;
      clone)
        echo "   This run already created a branch and a clone. Remove them by hand:" >&2
        echo "     rm -rf \"${WORKSPACE_PATH}\"   # a full clone, not a linked worktree" >&2
        echo "     git branch -D \"${BRANCH_NAME}\"" >&2
        ;;
      *)
        echo "   This run already created a branch (no worktree — --branch mode). Remove it by hand:" >&2
        echo "     git branch -D \"${BRANCH_NAME}\"" >&2
        ;;
    esac
    exit 1
  fi

  echo ""
  echo "✅ Lock created: ${LOCK_FILE}"
  echo ""
  cat "$LOCK_FILE"
fi

# ── Print summary ────────────────────────────────────────────
echo ""
echo "📝 Next steps:"
if [[ "$MODE" == "branch" ]]; then
  echo "   1. Check out the branch: git checkout ${BRANCH_NAME}"
  echo "   ⚠️  Branch mode has no filesystem isolation. Other sessions sharing"
  echo "      this directory will see your checkout. Use worktree mode (the default)"
  echo "      if multiple sessions may run concurrently."
  echo "   2. Start working!"
else
  echo "   1. Work in: ${WORKSPACE_PATH}"
  echo "   2. Start working!"
fi
