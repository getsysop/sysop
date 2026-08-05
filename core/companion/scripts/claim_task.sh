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
#
# Modes:
#   (default)    Create a git worktree at ../<project basename>-<TASK_ID>
#                on the branch. Override the prefix by exporting
#                WORKTREE_PREFIX (e.g. WORKTREE_PREFIX=foo → ../foo-<TASK_ID>).
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
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --worktree)      MODE="worktree"; shift ;;
    --branch)        MODE="branch"; shift ;;
    --clone)         MODE="clone"; shift ;;
    --lock)          USE_LOCK=true; shift ;;
    --release)       RELEASE=true; shift ;;
    --entry-state)   ENTRY_STATE=true; shift ;;
    --delete-branch) DELETE_BRANCH=true; shift ;;
    --force)         FORCE=true; shift ;;
    *) echo "❌ Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ── PyYAML interpreter resolution (Phase 182) ────────────────
# Four sites below read tasks/index.yml through PyYAML. On a PEP-668 host —
# every modern distro, and Homebrew macOS — `pip install` into the system
# interpreter is an *error*, so PyYAML lives only in the project venv. A bare
# `python3` therefore failed on hosts that are perfectly well provisioned:
# `--entry-state` (Step 2's FIRST command) exited 3 and named no remedy, and
# `--release` exited 1 with a manual recipe. Upstream #321.
#
# Three properties are deliberate:
#
#   * It PROBES rather than assuming. A blind `PATH=.venv/bin:$PATH` prepend
#     would shadow a capable system interpreter with an incapable venv one —
#     trading the reported failure for its mirror image. self_check.sh:61-66
#     documents that hazard in the other direction.
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
    MAIN_REPO_ROOT="$(dirname "$(cd "$GIT_COMMON_DIR" && pwd)")"
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
    MAIN_REPO_ROOT="$(dirname "$(cd "$GIT_COMMON_DIR" && pwd)")"
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
      echo "     git worktree remove ${LOCK_WORKSPACE:-<worktree>}   # add --force to discard uncommitted work" >&2
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

  # ── Remove the worktree (never the main worktree) ──
  if [[ -n "$LOCK_WORKSPACE" && -d "$LOCK_WORKSPACE" ]]; then
    WS_REAL="$(cd "$LOCK_WORKSPACE" && pwd -P 2>/dev/null || echo "$LOCK_WORKSPACE")"
    MAIN_REAL="$(cd "$MAIN_REPO_ROOT" && pwd -P 2>/dev/null || echo "$MAIN_REPO_ROOT")"
    CWD_REAL="$(pwd -P)"
    if [[ "$WS_REAL" == "$MAIN_REAL" ]]; then
      echo "⚠️  Recorded workspace is the main worktree — refusing to remove it."
    elif [[ "$CWD_REAL" == "$WS_REAL" || "$CWD_REAL" == "$WS_REAL"/* ]]; then
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
import os, sys, yaml

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

with open(index_path, "w", encoding="utf-8") as f:
    yaml.safe_dump(
        data, f,
        sort_keys=False, default_flow_style=False, allow_unicode=True, width=120,
    )
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
WORKTREE_DIR="${REPO_ROOT}/../${WORKTREE_PREFIX:-$(basename "$REPO_ROOT")}-${TASK_LOWER}"

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
    MAIN_REPO_ROOT="$(dirname "$(cd "$GIT_COMMON_DIR" && pwd)")"
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
    echo "ℹ️  Worktree directory '${WORKTREE_DIR}' already exists."
  else
    git worktree add "$WORKTREE_DIR" "$BRANCH_NAME"
    echo "✅ Created worktree at '${WORKTREE_DIR}' on branch '${BRANCH_NAME}'."
  fi
  WORKSPACE_PATH="$WORKTREE_DIR"

  # Deliberately NO hook install here (Phase 150 / upstream #202).
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
  REMOTE_URL=$(git remote get-url origin 2>/dev/null) || {
    echo "❌ No 'origin' remote found. Cannot clone." >&2
    exit 1
  }
  if [[ -d "$WORKTREE_DIR" ]]; then
    echo "ℹ️  Clone directory '${WORKTREE_DIR}' already exists."
  else
    git clone "$REMOTE_URL" "$WORKTREE_DIR"
    cd "$WORKTREE_DIR"
    git checkout "$BRANCH_NAME"
    cd "$REPO_ROOT"
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
  # variant that supports neither BSD `-v` nor GNU `-d` still produces
  # a valid timestamp rather than leaving the lock file with a blank
  # `expires:` field (which downstream lock-validator tooling treats as
  # malformed). Abort with a clear error if all three paths fail.
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

  cat > "$LOCK_FILE" <<EOF
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
