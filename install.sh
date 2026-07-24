#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Sysop installer
#
# Installs the Sysop workflow (core + selected packs) into a
# target project. Companion content (docs, scripts, git hooks,
# convention maps, security maps, checks registry, semgrep rules)
# lands under <target>/.claude/ and the <target>/sysop/ vendor dir
# (sysop/scripts/, sysop/scripts/hooks/, sysop/docs/) per WORKFLOW.md § 8.
# The teachable boundary (Phase 128): sysop/ is Sysop's; everything else
# (tasks/, CLAUDE.md, .gitignore) is the consumer's.
#
# Modes:
#   (default)        Fresh install. Refuses if the target tree has
#                    uncommitted changes (override with --force).
#   --update         Upgrade a tracked install. Reads the existing
#                    .claude/sysop.lock, snapshots dirty managed
#                    paths into a single commit, overwrites managed
#                    files with the upstream version, refreshes the
#                    lock. Does NOT auto-commit the update — review
#                    via `git diff <snapshot>..HEAD` and commit
#                    intentionally. (WORKFLOW.md § 8.2b)
#   --adopt          One-time backfill for consumers installed before
#                    Phase 7. Writes + commits a .claude/sysop.lock
#                    matching the current install state; future runs
#                    can use --update.
#   --check          Read-only: report how many upstream commits the
#                    target is behind on managed paths. Requires
#                    --source <path-to-sysop-clone>.
#
# Usage:
#   bash install.sh [TARGET] [OPTIONS]
#
# See: bash install.sh --help
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# Requires bash 4+ (associative arrays). macOS ships /bin/bash 3.2 by default;
# users should `brew install bash` or invoke via `bash install.sh` from a PATH
# where a modern bash takes precedence.
if (( ${BASH_VERSINFO[0]:-0} < 4 )); then
  echo "❌ install.sh requires bash 4 or newer (you have ${BASH_VERSION:-unknown})." >&2
  echo "   On macOS: brew install bash, then invoke as 'bash install.sh ...'." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

# Packs available in this repo (must match packs/<name>/ dirs).
ALL_PACKS=(python postgres nextjs-react llm beancount flutter kotlin mcp-server pandas streamlit swift-ios)

# Pack-name validation regex (also used to reject path-traversal).
PACK_NAME_RE='^[a-z][a-z0-9-]*$'

# Defaults
TARGET=""
PACKS_ARG=""
# Phase 75: distinguishes "--packs was given (any value, incl. '' or 'auto')"
# from "no --packs at all". Load-bearing so that an explicit --packs '' (core
# only) or a --packs auto that detects nothing does NOT silently fall through
# to the interactive picker.
PACKS_PROVIDED=0
DRY_RUN=0
FORCE=0
ASSUME_YES=0
ARM_HOOKS=1   # arm git hooks by default; --no-arm-hooks to skip
UPDATE_MODE=0
ADOPT_MODE=0
CHECK_MODE=0
CHECK_SOURCE=""
ANCHOR_OVERRIDE=""

# Phase 123: install shape. `full` (default) ships the whole workflow (planning,
# task queue, worktrees, merge gate). `loop` ships only the convention loop
# (audit/review skills + maps + checks + the review_tasks.md ledger) into a repo
# whose owner keeps their own branching/merge workflow — no tasks/ scaffold, no
# root workflow docs, a filtered skill/script/permission set. Recorded in the
# lock; --update re-resolves the recorded mode (upgrade loop→full via
# `--update --mode full`; full→loop downgrade is out of scope — reinstall fresh).
# The exclude lists below are asserted exact by tests/test_install_loop_mode.py:
# a new lifecycle skill/script must be added here or the test fails.
INSTALL_MODE="full"
MODE_PROVIDED=0
# Skills excluded from loop mode (the lifecycle set). The loop bundle is the
# complement: codebase-review, security-audit, test-audit, report-issues,
# contribute-convention (+ _shared, partial-filtered below).
LOOP_EXCLUDE_SKILLS="intake add-task claim-task auto-build auto-fix auto-judge next-task roadmap sitrep triage plan-review document-work review-close onboard daily-summary release share-wins pr-dependabot"
# _shared/ partials NOT in the five loop skills' closure (leg-1 audit). Kept:
# adversarial-review, permission-guard, promotion-write-target, test-assessment-rubric.
LOOP_EXCLUDE_SHARED="decomposition-rubric guided-mode main-push-guard ui-verify"
# Companion scripts excluded from loop mode (lifecycle-coupled). Kept: run_checks*
# (+ run_checks/ dir), _log.py, review_index.py, archive_review_tasks.py,
# install_hooks.sh, sysop-update.sh, and the model-role set (_model_roles.py,
# resolve/check/migrate_skill_model.py — mode-agnostic; operate on shipped skills).
LOOP_EXCLUDE_SCRIPTS="backfill_completed_dates.py batch_work.sh claim_task.sh cleanup_worktrees.sh close_batch.sh next_task.py parse_subagent_envelope.py permission_denied_hook.py pr_dependabot.py scope_overlap.py sitrep_survey.py validate_tasks.py"
# Phase 111: --ref pins the install/update source to a git tag/rev (a reviewed
# release) instead of the source clone's live HEAD. REF_WORKTREE holds the
# materialised-rev worktree; SYSOP_SRC_CLONE holds the original clone (needed to
# remove that worktree on exit, since a worktree can't cleanly remove itself).
REF_OVERRIDE=""
REF_WORKTREE=""
SYSOP_SRC_CLONE=""

# Phase 142: Codex-native skill registration. The installer emits two RELATIVE
# symlinks under <target>/.agents/skills/ pointing at the shipped review-skill
# dirs, so a Codex CLI session discovers and selects them natively (and gets the
# $codebase-review / $security-audit selectors) with no converted or duplicated
# files — one source of truth, zero drift surface. Both install modes: full mode
# installs the same two skill dirs at the same paths, so splitting on mode would
# buy nothing.
#
# Default on; --no-codex-links opts out and the choice is PERSISTED in the lock
# (codex_links), so the documented one-line `sysop/scripts/sysop-update.sh`
# honors a prior opt-out without retyping the flag. CODEX_LINKS_PROVIDED
# distinguishes "a flag was given this run" from "inherit the lock".
CODEX_LINKS=1
CODEX_LINKS_PROVIDED=0
# Set by preflight_codex_links when the capability probe fails: link CREATION is
# disabled for this run, but links that already exist and are still ours stay
# recorded and managed. That asymmetry is load-bearing — a transient mid-update
# probe failure must not drop the paths from MANAGED_PATHS and feed a consumer's
# working links to the obsolete sweep.
CODEX_LINKS_CREATE_DISABLED=0
# Target-local probe dir; cleaned inline and by the EXIT trap.
CODEX_PROBE_TMP=""
# The skills exposed natively. Deliberately just the two review skills: the other
# loop-mode skills have no Codex activation/runtime evidence, and adding one is a
# separate decision, not a default.
CODEX_SKILLS=(codebase-review security-audit)

# Location of the install manifest, relative to <target>.
LOCK_REL=".claude/sysop.lock"
LOCK_VERSION=1

# Populated by copy_file / concat_files / install_permissions during install.
# Paths are stored relative to <target>. Drives lock-file `managed_paths` and
# the --update mode's snapshot + deletion logic.
MANAGED_PATHS=()

# Resolved pack list. Declared empty here (not just inside resolve_selected_packs)
# so it is always a set-but-empty array: the lockless-fresh old-layout guard reads
# it via _ns_vendor_basenames BEFORE resolve_selected_packs runs, and an unset
# array would trip `set -u`. resolve_selected_packs fully reassigns it later.
SELECTED_PACKS=()

# Phase 24a: pick a python3 that can `import yaml`. Tries the consumer's
# project venv first (`.venv/bin/python3`) since that's where pyyaml lives
# in the existing Sysop setup (validate_tasks.py runs via .venv/bin/python3
# from the pre-commit hook). Falls back to system python3. Returns empty if
# neither works. Caller decides how to react.
pick_python_with_yaml() {
  local candidate
  for candidate in "$TARGET/.venv/bin/python3" "$TARGET/venv/bin/python3" "python3"; do
    if [[ "$candidate" == */* ]] && [[ ! -x "$candidate" ]]; then continue; fi
    if "$candidate" -c "import yaml" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

# Phase 24a: concat-file project suffixes. Maps a concat-style managed path
# (target-relative) to its consumer-authored `*.project.<ext>` sibling. When
# the sibling exists in the target tree, concat_files appends (markdown) or
# YAML-merges (checks.yml) it AFTER the regenerated core+pack body — so
# consumer-specific sections survive every `--update` regeneration. The
# `*.project.<ext>` files are NEVER written by the installer and are NOT in
# MANAGED_PATHS; same protection property as `tasks/index.yml` (Phase 16)
# and `SYSOP_ISSUES.md` (Phase 13). See WORKFLOW.md § 8.2c.
declare -A SYSOP_PROJECT_SUFFIXES=(
  [".claude/convention_map.md"]=".claude/convention_map.project.md"
  [".claude/security_map.md"]=".claude/security_map.project.md"
  [".claude/checks.yml"]=".claude/checks.project.yml"
)

# Phase 25 (BeanRider ISSUE-0026): consumer-authored placeholder substitution.
# Pack `checks.yml.fragment` files ship `paths:` lists with placeholder tokens
# (`<api module>/`, `<scripts dir>/`, `<datajobs dir>/`, etc.) that name the
# project layout abstractly. Without substitution, consumers either hand-edit
# `.claude/checks.yml` after every `--update` (regression channel) or restate
# every check in `.claude/checks.project.yml` (verbose, loses upstream
# comments). Phase 25 lets consumers author one YAML file mapping each token
# to its concrete project path; `concat_files` applies the map to the
# regenerated body AFTER concat + BEFORE suffix-file append. Same protection
# property as Phase 24a's suffix files — never written by the installer, NOT
# in MANAGED_PATHS, byte-faithful to consumer authoring. See WORKFLOW.md
# § 8.2c (Phase 25 paragraph).
SYSOP_SUBSTITUTIONS_FILE=".claude/substitutions.project.yml"
SUBSTITUTION_KEYS_LOADED=0
SUBSTITUTION_KEYS_LIST=()
declare -A SUBSTITUTION_USAGE_COUNT=()

# Phase 24b: shadow target lifecycle + preservation state. The shadow worktree
# Phase 8 already builds via reconstruct_old_install() is hoisted to module
# scope so copy_file() can per-file diff against it during the install
# pipeline. Set during `--update` non-`--force`; empty otherwise (preservation
# short-circuits). PRESERVED_PATHS captures paths whose overwrite was skipped
# because the consumer modified them since the lock's sysop_commit;
# ACCEPT_UPSTREAM is a set of target-relative paths the consumer explicitly
# opted to take upstream content for (via --accept-upstream / -list). See
# WORKFLOW.md § 8.2c (Phase 24b paragraph) and PHASE_24_HANDOFF.md § 4.5.
DIVERGENCE_SHADOW=""
OLD_COMMIT=""
PRESERVED_PATHS=()
declare -A ACCEPT_UPSTREAM=()
# Phase 128: sysop/ namespace migration state. MIGRATION_MODE is set when the
# --update flow detects an old-layout tree OR an old-spelled lock. NS_MOVE_OLD/NEW
# hold the FULL old→new move map (index-aligned) — every moved-prefix path in the
# new managed set, independent of on-disk state, so _ns_move_tree's per-file guards
# stay idempotent and a crash-resume shadow move can realign an already-moved tree.
# NS_MOVE_PENDING counts the moves that still have real working-tree work (old
# present, new absent); it gates the migration preflight. NS_STALE_REFS accumulates
# the T4 stale-reference findings.
MIGRATION_MODE=0
NS_MOVE_OLD=()
NS_MOVE_NEW=()
NS_MOVE_PENDING=0
NS_STALE_REFS=()
NS_SWEPT_COUNT=0
# Phase 123: temp file holding the loop-mode-filtered settings.json template
# (cleaned by _cleanup_install_temp on the EXIT trap).
LOOP_SETTINGS_TMP=""

usage() {
  cat <<'EOF'
Usage: bash install.sh [TARGET] [OPTIONS]

Install Sysop into a target project.

Arguments:
  TARGET                Path to target project. Prompted for if omitted.

Options:
  --packs LIST          Comma-separated pack list (e.g. python,postgres,nextjs-react),
                        or the literal 'auto' to detect the stack from the target tree,
                        or '' for core only. If omitted, runs the interactive pack picker
                        (fresh install, which offers the detected stack as the default) or
                        reads packs from .claude/sysop.lock (--update / --adopt).
  --mode loop|full      Install shape (default full). 'full' is the whole workflow
                        (planning, task queue, worktrees, merge gate). 'loop' installs
                        only the convention loop — audit/review skills, maps, checks,
                        and the review_tasks.md ledger — into a repo whose owner keeps
                        their own branching/merge workflow (no tasks/ scaffold, no root
                        workflow docs). Recorded in the lock; --update re-applies it.
                        Upgrade loop→full: --update --mode full (additive). Downgrade:
                        reinstall fresh. Not valid with --adopt/--check.
  --dry-run             Print planned operations without writing.
  --force               Fresh install: allow uncommitted changes in the target tree.
                        --update: skip the pre-update snapshot step (overwrite directly).
  --no-arm-hooks        Don't copy hook templates into .git/hooks/. (Templates still land
                        in <target>/sysop/scripts/hooks/; run sysop/scripts/install_hooks.sh later.)
  --no-codex-links      Skip the two .agents/skills/ symlinks that register the review
                        skills natively with the Codex CLI. They are created by default
                        in both modes (they point at .claude/skills/, so there are no
                        duplicated files). The choice is RECORDED IN THE LOCK, so a later
                        plain `sysop/scripts/sysop-update.sh` honors it without the flag.
                        Use --codex-links to turn them back on. If a path already exists
                        there and isn't ours, the install stops rather than clobber it.
  --codex-links         Re-enable the Codex skill links after a prior --no-codex-links
                        (the links reappear on the next install/update).
  --update              Upgrade a tracked install. Reads .claude/sysop.lock, snapshots
                        any dirty managed paths into a commit (so the user can git-diff
                        against it later), overwrites managed files with this checkout's
                        version, refreshes the lock. Does NOT auto-commit the update.
  --adopt               One-time backfill: write + commit .claude/sysop.lock for an
                        existing install that pre-dates the update mechanism. Use --packs
                        to declare which packs were originally installed.
  --check               Report N-commits-behind on managed paths. Requires --source.
                        Writes nothing.
  --source PATH         Path to a Sysop clone (for --check). Required by --check.
  --anchor REV          For --adopt: record this commit as the install anchor in
                        sysop.lock instead of the source clone's HEAD. Useful
                        when adopting a pre-Phase-7 install that doesn't match
                        current HEAD (e.g., installer source has been updated
                        since the original install). Accepts any rev parseable
                        by the source clone (sha, short sha, tag, branch).
  --ref REV             (Fresh install or --update) Pin the install to a git
                        tag/rev — a reviewed *release* — instead of the source
                        clone's live HEAD. Copies from the rev and records its
                        commit in the lock; a later --check then reports how far
                        behind HEAD you are. The rev must exist in your source
                        clone (release tags: git -C <clone> fetch --tags). Omit
                        to track HEAD (the default). Not valid with --adopt/--check.
  --accept-upstream PATH
                        (Phase 24b, --update only) Take upstream content for the
                        target-relative PATH even if it has been modified by the
                        consumer since the lock's sysop_commit. Repeatable.
                        Out-of-scope paths (not under sysop/scripts/* or sysop/scripts/hooks/*)
                        ignore the flag — they always overwrite anyway.
  --accept-upstream-list FILE
                        (Phase 24b) Same as --accept-upstream, but reads one
                        target-relative path per line from FILE. Blank lines and
                        # comments ignored.
  -y, --yes             Skip the final confirmation prompt.
  -h, --help            Show this help.

Available packs:
  python, postgres, nextjs-react, llm, beancount      (populated)
  flutter, kotlin, mcp-server, pandas,                (placeholder — manifest only, no companion content yet)
  streamlit, swift-ios

Examples:
  bash install.sh ~/Projects/myapp --packs python,postgres
  bash install.sh ~/Projects/myapp --packs auto          # detect the stack, pre-select packs
  bash install.sh ~/Projects/myapp                       # interactive picker (offers detected stack)
  bash install.sh                                        # interactive everything
  bash install.sh ~/Projects/myapp --packs python --dry-run
  # Smallest install — just the convention loop (audit/review + checks + ledger):
  bash install.sh ~/Projects/myapp --packs python --mode loop

  # Update an existing install to this checkout's version:
  bash install.sh ~/Projects/myapp --update
  # Upgrade a loop install to the full workflow (additive):
  bash install.sh ~/Projects/myapp --update --mode full
  # Pin a fresh install (or update) to a reviewed release tag instead of HEAD:
  bash install.sh ~/Projects/myapp --packs python --ref v0.1.0
  bash install.sh ~/Projects/myapp --update --ref v0.1.0
  # Adopt update tracking for a pre-Phase-7 install:
  bash install.sh ~/Projects/myapp --adopt --packs python,postgres
  # Preview pending upstream changes (read-only):
  bash install.sh ~/Projects/myapp --check --source ~/Projects/sysop

After install:
  cd <target>
  bash sysop/scripts/install_hooks.sh        # arm git hooks (skipped if --no-arm-hooks)
  bash sysop/scripts/run_checks.sh           # smoke-test the check registry
EOF
}

# ─── arg parsing ──────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)     usage; exit 0 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    --force)       FORCE=1; shift ;;
    --no-arm-hooks) ARM_HOOKS=0; shift ;;
    --update)      UPDATE_MODE=1; shift ;;
    --adopt)       ADOPT_MODE=1; shift ;;
    --check)       CHECK_MODE=1; shift ;;
    --source)      CHECK_SOURCE="${2:-}"; shift 2 ;;
    --source=*)    CHECK_SOURCE="${1#--source=}"; shift ;;
    --anchor)      ANCHOR_OVERRIDE="${2:-}"; shift 2 ;;
    --anchor=*)    ANCHOR_OVERRIDE="${1#--anchor=}"; shift ;;
    --ref)
                   # Guard a missing value AND a flag-shaped next token (the
                   # "forgot the tag, the next flag got consumed" mistake). Git
                   # refs never start with '-', so rejecting -* is safe.
                   if [[ -z "${2:-}" || "${2:-}" == -* ]]; then
                     echo "❌ --ref requires a tag/rev value (e.g. --ref v0.1.0)" >&2; exit 2
                   fi
                   REF_OVERRIDE="$2"; shift 2 ;;
    --ref=*)       REF_OVERRIDE="${1#--ref=}"
                   if [[ -z "$REF_OVERRIDE" ]]; then
                     echo "❌ --ref requires a tag/rev (e.g. --ref=v0.1.0)" >&2; exit 2
                   fi
                   shift ;;
    --accept-upstream)
                   if [[ -z "${2:-}" ]]; then
                     echo "❌ --accept-upstream requires a target-relative path" >&2; exit 2
                   fi
                   ACCEPT_UPSTREAM[$2]=1; shift 2 ;;
    --accept-upstream=*)
                   ACCEPT_UPSTREAM["${1#--accept-upstream=}"]=1; shift ;;
    --accept-upstream-list)
                   if [[ ! -f "${2:-}" ]]; then
                     echo "❌ --accept-upstream-list requires a readable file (got: ${2:-<empty>})" >&2; exit 2
                   fi
                   while IFS= read -r _line || [[ -n "$_line" ]]; do
                     # Skip blank lines and # comments.
                     [[ -z "${_line//[[:space:]]/}" ]] && continue
                     [[ "${_line#"${_line%%[![:space:]]*}"}" == \#* ]] && continue
                     # Trim leading/trailing whitespace.
                     _line="${_line#"${_line%%[![:space:]]*}"}"
                     _line="${_line%"${_line##*[![:space:]]}"}"
                     ACCEPT_UPSTREAM[$_line]=1
                   done < "$2"
                   unset _line
                   shift 2 ;;
    --no-codex-links) CODEX_LINKS=0; CODEX_LINKS_PROVIDED=1; shift ;;
    --codex-links)    CODEX_LINKS=1; CODEX_LINKS_PROVIDED=1; shift ;;
    -y|--yes)      ASSUME_YES=1; shift ;;
    --packs)       PACKS_ARG="${2:-}"; PACKS_PROVIDED=1; shift 2 ;;
    --packs=*)     PACKS_ARG="${1#--packs=}"; PACKS_PROVIDED=1; shift ;;
    --mode)        # Guard a missing value / flag-shaped next token.
                   if [[ -z "${2:-}" || "${2:-}" == -* ]]; then
                     echo "❌ --mode requires a value: loop or full" >&2; exit 2
                   fi
                   INSTALL_MODE="$2"; MODE_PROVIDED=1; shift 2 ;;
    --mode=*)      INSTALL_MODE="${1#--mode=}"; MODE_PROVIDED=1; shift ;;
    --)            shift; break ;;
    -*)            echo "❌ Unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -z "$TARGET" ]]; then
        TARGET="$1"
      else
        echo "❌ Unexpected extra positional argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

# At most one of --update / --adopt / --check.
if (( UPDATE_MODE + ADOPT_MODE + CHECK_MODE > 1 )); then
  echo "❌ --update, --adopt, and --check are mutually exclusive." >&2
  exit 2
fi

# --anchor is adopt-only — for fresh install / --update the recorded commit
# should reflect the source HEAD that was just installed.
if [[ -n "$ANCHOR_OVERRIDE" ]] && (( ADOPT_MODE == 0 )); then
  echo "❌ --anchor is only valid with --adopt." >&2
  exit 2
fi

# --ref pins the source to a git tag/rev; it applies only where files are
# actually copied FROM the source — a fresh install or --update. The read-only
# --check reads HEAD via --source; --adopt only writes a lock (record a rev
# there with --anchor). Reject early so the intent isn't silently ignored.
if [[ -n "$REF_OVERRIDE" ]] && (( ADOPT_MODE == 1 || CHECK_MODE == 1 )); then
  echo "❌ --ref is only valid for a fresh install or --update (not --adopt/--check)." >&2
  echo "   For --adopt, record a specific rev in the lock with --anchor." >&2
  exit 2
fi

# Phase 123: --mode value + applicability. loop|full only; a fresh-install /
# --update choice. --check is read-only; --adopt backfills a lock for a pre-loop
# install (always full), so --mode is rejected there.
if [[ "$INSTALL_MODE" != "loop" && "$INSTALL_MODE" != "full" ]]; then
  echo "❌ --mode must be 'loop' or 'full' (got: '$INSTALL_MODE')." >&2
  exit 2
fi
if [[ "$MODE_PROVIDED" -eq 1 ]] && (( ADOPT_MODE == 1 || CHECK_MODE == 1 )); then
  echo "❌ --mode is only valid for a fresh install or --update (not --adopt/--check)." >&2
  exit 2
fi

# ─── helpers ──────────────────────────────────────────────────
say()  { printf '%s\n' "$*"; }
note() { printf '  • %s\n' "$*"; }
err()  { printf '❌ %s\n' "$*" >&2; }
hdr()  { printf '\n── %s ──\n' "$*"; }

# Phase 123: word-in-space-separated-list membership (loop-mode filters).
_loop_excludes() {  # $1=word  $2=space-separated list → exit 0 if word ∈ list
  local w="$1" x
  for x in $2; do [[ "$w" == "$x" ]] && return 0; done
  return 1
}

# Run a command unless --dry-run is set. Echoes the action regardless.
do_or_say() {
  local action="$1"; shift
  note "$action"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

# Unified EXIT-trap cleanup for the two temp resources the installer may create:
# the Phase 8/24b divergence shadow (a temp dir) and the Phase 111 --ref pin
# worktree. Each is guarded so it fires only if set. Set once as the EXIT trap in
# main(); a single trap avoids the two sites clobbering each other's trap.
_cleanup_install_temp() {
  [[ -n "$DIVERGENCE_SHADOW" ]] && rm -rf "$DIVERGENCE_SHADOW"
  [[ -n "$LOOP_SETTINGS_TMP" ]] && rm -f "$LOOP_SETTINGS_TMP"
  # Phase 142: the Codex symlink probe writes a dir INSIDE the target (it must
  # test the consumer's filesystem, not /tmp's). A mid-probe crash would
  # otherwise strand it and trip the next install's dirty-tree check.
  [[ -n "$CODEX_PROBE_TMP" ]] && rm -rf "$CODEX_PROBE_TMP"
  if [[ -n "$REF_WORKTREE" ]] && [[ -n "$SYSOP_SRC_CLONE" ]]; then
    git -C "$SYSOP_SRC_CLONE" worktree remove --force "$REF_WORKTREE" >/dev/null 2>&1 || true
  fi
  return 0
}

# Pack dir name → plugin name (sysop- prefix).
pack_plugin_name() { printf 'sysop-%s' "$1"; }
# Plugin name → pack dir name (strip sysop- prefix). Returns empty for core.
plugin_to_pack() {
  local p="$1"
  case "$p" in
    sysop)       printf '' ;;
    sysop-*)     printf '%s' "${p#sysop-}" ;;
    *)               printf '%s' "$p" ;;
  esac
}

# True if argv[1] is in ALL_PACKS.
is_known_pack() {
  local name="$1" p
  for p in "${ALL_PACKS[@]}"; do
    [[ "$p" == "$name" ]] && return 0
  done
  return 1
}

# True if a pack has any companion content.
pack_has_companion() {
  local pack="$1"
  [[ -d "$REPO_ROOT/packs/$pack/companion" ]] \
    && [[ -n "$(ls -A "$REPO_ROOT/packs/$pack/companion" 2>/dev/null || true)" ]]
}

# Read a pack's dependencies from its plugin.json (one plugin name per line).
# Falls back to no-deps if jq absent and python3 absent.
pack_dependencies() {
  local pack="$1"
  local manifest="$REPO_ROOT/packs/$pack/.claude-plugin/plugin.json"
  [[ -f "$manifest" ]] || return 0
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$manifest" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for d in data.get("dependencies", []) or []:
    print(d)
PY
  fi
}

# Resolve pack deps transitively from CSV input → space-separated unique pack list,
# topologically ordered (deps before dependents).
resolve_packs() {
  local csv="$1"
  local -a queue=()
  local -a ordered=()
  local p tok

  IFS=',' read -r -a queue <<< "$csv"

  declare -A seen=()
  declare -A in_order=()

  local i=0
  while (( i < ${#queue[@]} )); do
    tok="${queue[$i]}"
    i=$((i + 1))
    tok="${tok// /}"
    [[ -z "$tok" ]] && continue
    if ! [[ "$tok" =~ $PACK_NAME_RE ]]; then
      err "Invalid pack name: '$tok' (must match $PACK_NAME_RE)"
      return 1
    fi
    if ! is_known_pack "$tok"; then
      err "Unknown pack: '$tok'. Run with --help to see available packs."
      return 1
    fi
    [[ -n "${seen[$tok]:-}" ]] && continue
    seen[$tok]=1

    # Pull deps first.
    local dep_plugin dep
    while IFS= read -r dep_plugin; do
      [[ -z "$dep_plugin" ]] && continue
      dep="$(plugin_to_pack "$dep_plugin")"
      [[ -z "$dep" ]] && continue   # Sysop core is always installed
      if [[ -z "${seen[$dep]:-}" ]]; then
        queue+=("$dep")
      fi
    done < <(pack_dependencies "$tok")
  done

  # Second pass: emit deps before dependents (recursive walk).
  emit_pack() {
    local pk="$1"
    [[ -n "${in_order[$pk]:-}" ]] && return 0
    local dep_plugin dep
    while IFS= read -r dep_plugin; do
      [[ -z "$dep_plugin" ]] && continue
      dep="$(plugin_to_pack "$dep_plugin")"
      [[ -z "$dep" ]] && continue
      emit_pack "$dep"
    done < <(pack_dependencies "$pk")
    in_order[$pk]=1
    ordered+=("$pk")
  }

  for tok in "${!seen[@]}"; do
    emit_pack "$tok"
  done

  printf '%s\n' "${ordered[@]}"
}

# ─── stack auto-detection (Phase 75) ─────────────────────────
# Scan a project tree for high-precision stack signals and echo a CSV of
# detected *populated* packs (dependency resolution is left to resolve_packs).
# Design: precision over recall — a wrong pre-selection is worse than none, so
# probes are marker-file-first and file-content globs are depth-bounded +
# vendor-pruned. Every probe is guarded and best-effort: detection failure
# yields "" (→ core only), never an install abort. Only populated packs carry
# signals; when a placeholder pack grows companion content, add its block to
# detect_packs(). Callers own all human-facing messaging — these functions put
# ONLY the result on stdout so `$(...)` capture stays clean.

# Depth-bounded, vendor-pruned file probe. Prints "<path>" on the first match
# (empty on none). Args: <dir> <maxdepth> <glob> [<glob> ...].
_detect_has_file() {
  local dir="$1" depth="$2"; shift 2
  local -a nameexpr=()
  local g
  for g in "$@"; do
    if (( ${#nameexpr[@]} )); then nameexpr+=(-o -name "$g"); else nameexpr+=(-name "$g"); fi
  done
  find "$dir" -maxdepth "$depth" \
    \( -path '*/.git/*' -o -path '*/node_modules/*' -o -path '*/.venv/*' -o -path '*/venv/*' \) -prune \
    -o -type f \( "${nameexpr[@]}" \) -print 2>/dev/null | head -n1
}

# True (prints "1") if any common dependency manifest (depth 2) matches the
# regex. Args: <dir> <extended-regex>.
_detect_manifest_mentions() {
  local dir="$1" re="$2" f
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    if grep -qiE "$re" "$f" 2>/dev/null; then printf '1'; return 0; fi
  done < <(find "$dir" -maxdepth 2 \
    \( -path '*/.git/*' -o -path '*/node_modules/*' \
       -o -path '*/.venv/*' -o -path '*/venv/*' \) -prune \
    -o -type f \( -name 'requirements*.txt' -o -name 'pyproject.toml' \
                  -o -name 'package.json' -o -name 'Pipfile' \) -print 2>/dev/null)
  return 1
}

detect_packs() {
  local dir="$TARGET"
  [[ -d "$dir" ]] || return 0
  local -a hits=()

  # python — marker files first, then a depth-bounded *.py fallback.
  if [[ -f "$dir/pyproject.toml" || -f "$dir/setup.py" || -f "$dir/setup.cfg" || -f "$dir/Pipfile" ]] \
     || ls "$dir"/requirements*.txt >/dev/null 2>&1 \
     || [[ -n "$(_detect_has_file "$dir" 2 '*.py')" ]]; then
    hits+=("python")
  fi

  # postgres — explicit Postgres markers only (NOT "any .sql"): alembic, a
  # compose file (docker-compose.* or the Compose v2 compose.*) naming
  # postgres, or a *.sql under a migrations/ dir. `find -exec grep` (not a
  # two-glob `ls`, which exits non-zero when only one glob resolves) so both
  # compose filenames and paths with spaces are handled; vendor dirs pruned.
  if [[ -f "$dir/alembic.ini" ]] \
     || [[ -n "$(find "$dir" -maxdepth 2 -type f \( -name 'docker-compose*.y*ml' -o -name 'compose*.y*ml' \) \
                   -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/.venv/*' -not -path '*/venv/*' \
                   -exec grep -liE 'postgres' {} + 2>/dev/null | head -n1)" ]] \
     || [[ -n "$(find "$dir" -maxdepth 4 -type f -name '*.sql' -path '*/migrations/*' \
                   -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/.venv/*' -not -path '*/venv/*' \
                   -print 2>/dev/null | head -n1)" ]]; then
    hits+=("postgres")
  fi

  # nextjs-react — next.config.*, a package.json naming next/react, or *.tsx/*.jsx.
  if ls "$dir"/next.config.* >/dev/null 2>&1 \
     || { [[ -f "$dir/package.json" ]] && grep -qiE '"(next|react)"[[:space:]]*:' "$dir/package.json" 2>/dev/null; } \
     || [[ -n "$(_detect_has_file "$dir" 2 '*.tsx' '*.jsx')" ]]; then
    hits+=("nextjs-react")
  fi

  # llm — a dependency manifest naming a major LLM SDK/framework. Tokens are
  # boundary-anchored ((^|[^a-z0-9])…([^a-z0-9]|$)) so a substring like
  # "coherence"/"@coherentglobal" doesn't false-trip on "cohere".
  if [[ -n "$(_detect_manifest_mentions "$dir" '(^|[^a-z0-9])(anthropic|openai|langchain|llama[-_]index|cohere|mistralai)([^a-z0-9]|$)')" ]]; then
    hits+=("llm")
  fi

  # beancount — a ledger file, or a python manifest naming beancount.
  if [[ -n "$(_detect_has_file "$dir" 2 '*.beancount' '*.bean')" ]] \
     || [[ -n "$(_detect_manifest_mentions "$dir" 'beancount')" ]]; then
    hits+=("beancount")
  fi

  # Guard the empty case explicitly (no detections → print nothing): expanding
  # an empty array under `set -u` errors on bash < 4.4.
  if (( ${#hits[@]} )); then
    local IFS=,
    printf '%s\n' "${hits[*]}"
  fi
}

# ─── interactive prompts ──────────────────────────────────────
# Phase 34 / BeanRider ISSUE-0012: each prompt pre-checks /dev/tty
# readability so a non-interactive caller (agent tool subprocess, CI)
# gets an actionable error naming the flag that bypasses the prompt,
# instead of bash's cryptic "Device not configured" + a silent abort.
_require_tty_or_flag() {
  # Args: <flag-suggestion-text>
  # `[[ -r /dev/tty ]]` is unreliable — on macOS the device file passes the
  # readability test even when no controlling terminal can actually open it.
  # Attempt an open in a subshell with stderr suppressed; non-zero exit means
  # the prompt's `read -r ... < /dev/tty` would fail with "Device not
  # configured" + a silent abort.
  if ! ( : < /dev/tty ) 2>/dev/null; then
    err "Non-interactive environment (no controlling terminal)."
    err "  $1"
    exit 1
  fi
}

prompt_target() {
  _require_tty_or_flag "Re-run with a positional <target> argument, e.g.: bash install.sh /path/to/project"
  local input
  printf 'Target project path: ' >&2
  read -r input < /dev/tty
  printf '%s' "$input"
}

prompt_packs() {
  _require_tty_or_flag "Re-run with --packs <list>, e.g.: --packs python,postgres (or --packs '' for core only, or --packs auto to auto-detect)"
  # Phase 75: pre-scan the target so the picker can offer the detected stack as
  # the blank-default. Detection is advisory — the human always confirms/edits.
  # Skipped under --adopt: that flow asks which packs were *originally*
  # installed (a different question from the current stack), so it keeps the
  # historical blank = core-only default and shows no detection line.
  local detected=""
  [[ "$ADOPT_MODE" -eq 0 ]] && detected="$(detect_packs)"
  {
    say ""
    say "Available packs:"
    say "  populated:   python, postgres, nextjs-react, llm, beancount"
    say "  placeholder: flutter, kotlin, mcp-server, pandas, streamlit, swift-ios"
    say ""
    say "  Dependencies are resolved automatically (e.g., postgres pulls in python)."
    say "  Placeholder packs have no companion content yet and will be skipped."
    say ""
    if [[ -n "$detected" ]]; then
      say "  Detected in your project: ${detected//,/, }"
      printf 'Packs (comma-separated; blank = accept detected; "none" = core only): '
    else
      printf 'Packs (comma-separated, blank = core only): '
    fi
  } >&2
  local input
  read -r input < /dev/tty
  # Resolve the reply against detection: blank accepts the detected set (or ""
  # when nothing was detected — the historical core-only default); an explicit
  # "none"/"core"/"-" forces core-only even when a stack was detected; anything
  # else is taken verbatim as the override list.
  case "$(printf '%s' "$input" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')" in
    "")          printf '%s' "$detected" ;;
    none|core|-) printf '%s' "" ;;
    *)           printf '%s' "$input" ;;
  esac
}

confirm() {
  local prompt="$1" reply
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  _require_tty_or_flag "Re-run with --yes to confirm '$prompt' without an interactive prompt."
  printf '%s [y/N] ' "$prompt" >&2
  read -r reply < /dev/tty || reply=""
  [[ "$reply" =~ ^[Yy]$ ]]
}

# ─── target validation ───────────────────────────────────────
validate_target() {
  local t="$1"
  [[ -d "$t" ]] || { err "Target directory does not exist: $t"; return 1; }
  git -C "$t" rev-parse --show-toplevel >/dev/null 2>&1 \
    || { err "Target is not a git repository: $t"; return 1; }
  # --update and --adopt have their own pre-execute treatment for dirty paths
  # (snapshot or refuse-with-pointer); skip the blanket refusal here.
  if (( UPDATE_MODE == 0 && ADOPT_MODE == 0 && CHECK_MODE == 0 )); then
    if [[ "$FORCE" -eq 0 ]]; then
      if [[ -n "$(git -C "$t" status --porcelain 2>/dev/null)" ]]; then
        err "Target git tree has uncommitted changes."
        err "Commit or stash first, or re-run with --force."
        return 1
      fi
    fi
  fi
}

# Resolve target to an absolute path; also reject targets that *are* this repo.
canonicalize_target() {
  local t="$1"
  # Use python3 for portable realpath (macOS realpath quirks).
  python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$t"
}

# ─── copy / merge operations ─────────────────────────────────
# Track dirs we've already announced/created to avoid noise.
declare -A KNOWN_DIRS=()

ensure_dir() {
  local d="$1"
  if [[ -n "${KNOWN_DIRS[$d]:-}" ]]; then
    return 0
  fi
  KNOWN_DIRS[$d]=1
  if [[ "$DRY_RUN" -eq 1 ]]; then
    if [[ ! -d "$d" ]]; then
      note "mkdir -p $(rel "$d")"
    fi
  else
    mkdir -p "$d"
  fi
}

# Phase 24b: scope filter for the copy_file preservation block. Returns 0 iff
# the absolute target path falls under sysop/scripts/<file> (depth-1) or
# sysop/scripts/hooks/<file> (depth-2). Skills, workflow docs, semgrep rules, and
# tasks-scaffold templates are explicitly OUT of scope so that hand-edits to
# those paths still get overwritten by the standard pipeline (a silent prompt-
# fork channel for skills would accumulate divergence from upstream
# improvements indefinitely — see WORKFLOW.md § 8.2c). Concat targets are also
# out of scope because Phase 24a's suffix-file mechanism is the right shape
# for them; preserving them would freeze the file at its last consumer state
# and silently drop upstream improvements.
#
# Cases (one per line, in-scope vs out-of-scope):
#   sysop/scripts/foo.py            → in     (depth-1 file under sysop/scripts/)
#   sysop/scripts/hooks/pre-commit  → in     (depth-2 file under sysop/scripts/hooks/)
#   sysop/scripts/foo/bar.py        → out    (depth-2 not under hooks/)
#   sysop/scripts/hooks/sub/bar     → out    (depth-3 under hooks/)
#   .claude/skills/X/SKILL.md → out
#   WORKFLOW.md               → out
_phase_24b_in_scope() {
  local relp="${1#"$TARGET"/}"
  # sysop/scripts/<file> at depth 1 — must contain no further `/`.
  if [[ "$relp" == sysop/scripts/* ]] && [[ "$relp" != sysop/scripts/*/* ]]; then return 0; fi
  # sysop/scripts/hooks/<file> at depth 2 — must contain exactly one `/` after `sysop/scripts/hooks/`.
  if [[ "$relp" == sysop/scripts/hooks/* ]] && [[ "$relp" != sysop/scripts/hooks/*/* ]]; then return 0; fi
  return 1
}

# ─── Phase 128: sysop/ vendor-namespace migration (tools/SYSOP_NAMESPACE_SPEC.md) ───
# One consumer-install layout change: the vendor footprint moves out of the
# consumer's shared namespaces (flat scripts/ + root docs) into a labelled
# sysop/ dir. These helpers map a relpath between the OLD (flat) and NEW
# (sysop/) spellings. The move is a pure prefix remap over three managed
# prefixes; everything else (.claude/, tasks/, CLAUDE.md, review_tasks*.md,
# runtime dirs) is unmoved. Both maps are total and idempotent — a path already
# in the target spelling passes through unchanged (so resume is a no-op re-run).
_ns_old_to_new() {
  case "$1" in
    scripts/*)         printf 'sysop/%s' "$1" ;;
    WORKFLOW.md)       printf 'sysop/docs/WORKFLOW.md' ;;
    WORKFLOW_GUIDE.md) printf 'sysop/docs/WORKFLOW_GUIDE.md' ;;
    SYSOP_ISSUES.md)   printf 'sysop/SYSOP_ISSUES.md' ;;
    *)                 printf '%s' "$1" ;;
  esac
}
_ns_new_to_old() {
  case "$1" in
    sysop/scripts/*)              printf '%s' "${1#sysop/}" ;;
    sysop/docs/WORKFLOW.md)       printf 'WORKFLOW.md' ;;
    sysop/docs/WORKFLOW_GUIDE.md) printf 'WORKFLOW_GUIDE.md' ;;
    sysop/SYSOP_ISSUES.md)        printf 'SYSOP_ISSUES.md' ;;
    *)                            printf '%s' "$1" ;;
  esac
}

# Basenames of the vendor scripts Sysop installs at scripts/ (OLD layout) /
# sysop/scripts/ (NEW). Core companion scripts always; installed-pack scripts too
# (they land in the same flat scripts/ dir — packs/<p>/companion/scripts/*). One
# per line, __pycache__ skipped. Single source for the migration tree-probe, the
# T4 stale-ref scan, and the lockless-fresh old-layout guard, so all three see the
# same managed surface (a pack script left at flat scripts/ must re-trigger too).
# SELECTED_PACKS is empty when called before resolve_selected_packs (the fresh
# guard) → core-only, which is enough there since a real install always ships core.
_ns_vendor_basenames() {
  local f b pd pack
  for f in "$REPO_ROOT/core/companion/scripts"/*; do
    [[ -e "$f" ]] || continue
    b="$(basename "$f")"
    [[ "$b" == "__pycache__" ]] && continue
    printf '%s\n' "$b"
  done
  for pack in "${SELECTED_PACKS[@]}"; do
    pd="$REPO_ROOT/packs/$pack/companion/scripts"
    [[ -d "$pd" ]] || continue
    for f in "$pd"/*; do
      [[ -f "$f" ]] || continue
      b="$(basename "$f")"
      [[ "$b" == "__pycache__" ]] && continue
      printf '%s\n' "$b"
    done
  done
}

# Cheap tree-probe (T3): does an OLD-layout vendor script still sit at the flat
# scripts/ path? Enumerated from the SOURCE (core + installed packs, via
# _ns_vendor_basenames) so a partially-migrated (crashed) tree with ANY unmoved
# vendor file — a leftover pack script included — re-triggers on the next --update.
# A fully-migrated tree has no old vendor scripts → returns 1. Pairs with
# _ns_lock_is_old_spelled: this probe catches trees that still hold flat files;
# that one catches the inverse crash window (tree already moved, lock still old).
# Docs/issues are NOT probed here (they aren't Phase-24b preserve-scoped, so a
# docs-only resume gap causes no preservation loss, and a consumer's own
# WORKFLOW.md must not false-trigger); they ride the move list.
_ns_migration_pending() {
  local b
  while IFS= read -r b; do
    [[ -z "$b" ]] && continue
    [[ -e "$TARGET/scripts/$b" ]] && return 0
  done < <(_ns_vendor_basenames)
  return 1
}

# Does the lock's recorded managed set still use OLD (flat) spellings? True even
# after the working tree has moved to sysop/ — the crash-resume window where a
# migration relocated the files but died before rewriting the lock (tree NEW, lock
# OLD). Together with the tree-probe this closes that hole: the tree-probe alone
# misses it (no flat files remain) so MIGRATION_MODE would stay 0, the shadow move
# would not run, and copy_file's Phase-24b preservation would silently overwrite
# consumer edits. NOT true for the adopt-bridge case (lock already sysop/-spelled)
# — that path is caught by the tree-probe (its tree is still OLD-layout).
# Args: the lock's managed_paths.
_ns_lock_is_old_spelled() {
  local m
  for m in "$@"; do
    [[ "$(_ns_old_to_new "$m")" != "$m" ]] && return 0
  done
  return 1
}

# Corroborated old-layout evidence for the lockless-fresh guard: is $TARGET really a
# lost-lock Sysop install (refuse a plain install), or just a new consumer who owns
# ONE file at a shipped basename (proceed)? _ns_migration_pending fires on a single
# match, which a genuine new repo can trip with its own scripts/run_checks.sh. A real
# lost-lock old-layout install ships MANY vendor scripts plus other Sysop artifacts,
# so refuse only when the evidence corroborates: 2+ vendor basenames at flat scripts/
# (the strong signal), OR exactly one basename AND a second Sysop marker — old-layout
# root docs (WORKFLOW*.md) or .claude/convention_map.md, which a fresh consumer would
# not have. A tree stripped to a single vendor script with no other marker slips
# through to the plain install (a vanishing edge, accepted).
_ns_old_layout_corroborated() {
  local b n=0
  while IFS= read -r b; do
    [[ -z "$b" ]] && continue
    [[ -e "$TARGET/scripts/$b" ]] && n=$((n + 1))
    (( n >= 2 )) && return 0
  done < <(_ns_vendor_basenames)
  (( n == 0 )) && return 1
  # Exactly one vendor basename — require a corroborating Sysop artifact.
  [[ -f "$TARGET/WORKFLOW.md" ]] && return 0
  [[ -f "$TARGET/WORKFLOW_GUIDE.md" ]] && return 0
  [[ -f "$TARGET/.claude/convention_map.md" ]] && return 0
  return 1
}

# T7: is there a pre-existing $TARGET/sysop entry that this migration/install did
# not create? Case-insensitive (macOS) probe. On a fresh install any sysop/ is a
# collision; during migration a sysop/scripts/ from a prior partial run is OURS
# (resume), so callers pass whether a partial-migration state is expected.
_ns_foreign_sysop_dir() {
  local d
  for d in "$TARGET"/sysop "$TARGET"/Sysop "$TARGET"/SYSOP; do
    [[ -e "$d" ]] && { printf '%s' "$d"; return 0; }
  done
  return 1
}

copy_file() {
  local src="$1" dst="$2"
  ensure_dir "$(dirname "$dst")"

  # Phase 24b: preserve consumer-modified managed paths (scoped to sysop/scripts/*
  # and sysop/scripts/hooks/*). Out-of-scope paths take the standard overwrite.
  # Short-circuits unless: --update mode, shadow tree available, scope filter
  # says yes, the working file exists, and it differs from the ancestor.
  if [[ "$UPDATE_MODE" -eq 1 ]] && [[ -n "$DIVERGENCE_SHADOW" ]] \
     && _phase_24b_in_scope "$dst"; then
    local _relp="${dst#"$TARGET"/}"
    local _work="$dst" _anc="$DIVERGENCE_SHADOW/$_relp"
    # Phase 128: on a DRY-RUN migration NEITHER the working tree NOR the shadow has
    # been moved yet, and either may sit at the OLD or the NEW spelling depending on
    # the migration state:
    #   • normal        — tree OLD-layout,  shadow OLD-layout (pre-namespace anchor)
    #   • adopt-bridge  — tree OLD-layout,  shadow NEW-layout (post-namespace anchor)
    #   • crash-resume  — tree NEW-layout,  shadow OLD-layout (tree moved pre-crash)
    # The move is a pure rename, so the preservation DECISION is spelling-independent
    # (same bytes either side). Resolve _work and _anc INDEPENDENTLY to whichever
    # spelling actually exists on disk, so the dry-run preview matches the real run in
    # every state. The earlier code reassigned BOTH from a single `_work missing`
    # gate: it clobbered a valid NEW-spelled shadow ancestor with a nonexistent
    # old-spelled one on the adopt-bridge path (preserved → mispreviewed as overwrite),
    # and never fixed the shadow ancestor at all on crash-resume (Finding 4). Real
    # runs (DRY_RUN=0) do the actual move first, so _work/_anc already exist and
    # neither branch fires.
    if [[ "$MIGRATION_MODE" -eq 1 ]] && [[ "$DRY_RUN" -eq 1 ]] && [[ "$_relp" != "$(_ns_new_to_old "$_relp")" ]]; then
      local _old; _old="$(_ns_new_to_old "$_relp")"
      [[ ! -f "$_work" ]] && [[ -f "$TARGET/$_old" ]] && _work="$TARGET/$_old"
      [[ ! -f "$_anc" ]] && [[ -f "$DIVERGENCE_SHADOW/$_old" ]] && _anc="$DIVERGENCE_SHADOW/$_old"
    fi
    if [[ -f "$_work" ]] && [[ -f "$_anc" ]] && ! cmp -s "$_anc" "$_work"; then
      if [[ "${ACCEPT_UPSTREAM[$_relp]:-0}" == "1" ]]; then
        # Consumer explicitly opted to take upstream — record + fall through
        # to the cp below. Mark the accept-upstream slot so post-pipeline
        # accounting can flag stale entries.
        ACCEPT_UPSTREAM[$_relp]="applied"
        note "↻ accept-upstream: $_relp (consumer-modified; overwriting per --accept-upstream)"
      else
        # Skip overwrite, record as preserved. Still recorded in
        # MANAGED_PATHS so the lock stays accurate; numstat won't see this
        # path (working tree didn't change), so report_post_overwrite_deltas
        # emits a dedicated preserved-paths block above its numstat table.
        note "⚠ preserved: $_relp (consumer-modified since ${OLD_COMMIT:0:12}; use --accept-upstream $_relp to overwrite)"
        PRESERVED_PATHS+=("$_relp")
        record_managed_path "$dst"
        return 0
      fi
    fi
  fi

  do_or_say "copy: $(rel "$src") → $(rel "$dst")" cp "$src" "$dst"
  record_managed_path "$dst"
}

# Display path relative to its enclosing root (REPO_ROOT for sources, TARGET for dests).
rel() {
  local p="$1"
  if [[ "$p" == "$REPO_ROOT"/* ]]; then
    printf '%s' "${p#"$REPO_ROOT"/}"
  elif [[ "$p" == "$TARGET"/* ]]; then
    printf '<target>/%s' "${p#"$TARGET"/}"
  else
    printf '%s' "$p"
  fi
}

# ─── managed-paths + lock helpers ─────────────────────────────
# Record an absolute destination path under TARGET into MANAGED_PATHS,
# de-duplicated and stored as a target-relative path. Silently ignored
# if the path is outside TARGET (e.g., .git/hooks/ during arm).
record_managed_path() {
  local dst="$1"
  [[ -z "${TARGET:-}" ]] && return 0
  [[ "$dst" != "$TARGET"/* ]] && return 0
  local relp="${dst#"$TARGET"/}"
  local existing
  for existing in "${MANAGED_PATHS[@]}"; do
    [[ "$existing" == "$relp" ]] && return 0
  done
  MANAGED_PATHS+=("$relp")
}

iso_now() {
  python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'
}

# Current HEAD of the Sysop source repo, or "unknown" if not a git repo.
# If ANCHOR_OVERRIDE is set (from --anchor, adopt-only), resolves it against
# the source repo and returns the full sha instead.
get_sysop_commit() {
  if [[ -n "$ANCHOR_OVERRIDE" ]]; then
    local resolved
    if resolved="$(git -C "$REPO_ROOT" rev-parse --verify "${ANCHOR_OVERRIDE}^{commit}" 2>/dev/null)"; then
      printf '%s' "$resolved"
      return 0
    fi
    err "--anchor: cannot resolve '$ANCHOR_OVERRIDE' in $REPO_ROOT"
    exit 1
  fi
  if git -C "$REPO_ROOT" rev-parse HEAD >/dev/null 2>&1; then
    git -C "$REPO_ROOT" rev-parse HEAD
  else
    printf 'unknown'
  fi
}

# Read a top-level field from the target lock file. Echoes empty on miss.
# Usage: lock_field <key>
lock_field() {
  local key="$1"
  local lock_path="$TARGET/$LOCK_REL"
  [[ -f "$lock_path" ]] || return 0
  python3 - "$lock_path" "$key" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
val = data.get(sys.argv[2])
if val is None:
    pass
elif isinstance(val, list):
    for item in val:
        print(item)
else:
    print(val)
PY
}

# Write/refresh <target>/.claude/sysop.lock. Honours DRY_RUN.
# Args: <installed_at> <updated_at>
write_lock_file() {
  local installed_at="$1" updated_at="$2"
  local lock_path="$TARGET/$LOCK_REL"
  local commit; commit="$(get_sysop_commit)"

  ensure_dir "$(dirname "$lock_path")"
  note "lock: $(rel "$lock_path") (commit ${commit:0:12}, ${#MANAGED_PATHS[@]} managed paths)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi

  # Pass managed paths + packs via env to avoid argv-length limits.
  local packs_csv="" p
  for p in "${SELECTED_PACKS[@]}"; do
    if [[ -z "$packs_csv" ]]; then packs_csv="$p"; else packs_csv="$packs_csv,$p"; fi
  done
  local paths_nl=""
  if (( ${#MANAGED_PATHS[@]} > 0 )); then
    paths_nl="$(printf '%s\n' "${MANAGED_PATHS[@]}")"
  fi
  # Phase 142: persist the Codex-links choice so a --no-codex-links opt-out
  # survives into the plain one-line `sysop-update.sh` (no retyped flag).
  local codex_links_json="true"
  [[ "$CODEX_LINKS" -eq 1 ]] || codex_links_json="false"

  SYSOP_CODEX_LINKS="$codex_links_json" \
  SYSOP_LOCK_PATH="$lock_path" \
  SYSOP_LOCK_VERSION="$LOCK_VERSION" \
  SYSOP_COMMIT="$commit" \
  SYSOP_PACKS="$packs_csv" \
  SYSOP_MODE="$INSTALL_MODE" \
  SYSOP_INSTALLED_AT="$installed_at" \
  SYSOP_UPDATED_AT="$updated_at" \
  SYSOP_MANAGED_PATHS="$paths_nl" \
  python3 - <<'PY'
import json, os
packs = [p for p in os.environ.get("SYSOP_PACKS", "").split(",") if p]
managed = [p for p in os.environ.get("SYSOP_MANAGED_PATHS", "").splitlines() if p]
managed.sort()
data = {
    "version": int(os.environ["SYSOP_LOCK_VERSION"]),
    "sysop_commit": os.environ["SYSOP_COMMIT"],
    "packs": packs,
    "mode": os.environ.get("SYSOP_MODE", "full"),
    "codex_links": os.environ.get("SYSOP_CODEX_LINKS", "true") == "true",
    "installed_at": os.environ["SYSOP_INSTALLED_AT"],
    "updated_at": os.environ["SYSOP_UPDATED_AT"],
    "managed_paths": managed,
}
with open(os.environ["SYSOP_LOCK_PATH"], "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

# Snapshot dirty paths from a given set into a single commit. Echoes the new
# commit hash on stdout, or empty if nothing was dirty. Honours DRY_RUN.
# Args: <old_hash> <path1> [<path2> ...]
snapshot_managed_paths() {
  local old_hash="$1"; shift
  local -a candidates=("$@")
  (( ${#candidates[@]} == 0 )) && return 0

  # `git status --porcelain -- <paths>` shows only paths in the candidate set
  # that are dirty (modified, staged, deleted, untracked).
  local -a dirty=()
  local line status path
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    status="${line:0:2}"
    path="${line:3}"
    # T3 (Phase 128): a staged rename during a resumed namespace migration renders
    # as `R  old -> new`; ${line:3} then yields the bogus pathspec "old -> new"
    # which dies under set -e. Take the destination side.
    [[ "$path" == *" -> "* ]] && path="${path##* -> }"
    dirty+=("$path")
  done < <(git -C "$TARGET" status --porcelain -- "${candidates[@]}" 2>/dev/null)

  if (( ${#dirty[@]} == 0 )); then
    return 0
  fi

  # The function's stdout is the snapshot commit hash, captured via $(...).
  # Route progress output to stderr so it doesn't pollute the captured value.
  note "snapshot: ${#dirty[@]} dirty managed path(s) → commit" >&2
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'DRY-RUN-SNAPSHOT-HASH'
    return 0
  fi

  # Stage explicitly; `git commit -- <paths>` then commits ONLY those paths
  # from the working tree, leaving any unrelated staged changes untouched.
  git -C "$TARGET" add -- "${dirty[@]}" >&2
  git -C "$TARGET" commit \
    --no-verify \
    -m "sysop: pre-update snapshot (was at ${old_hash:0:12})" \
    -- "${dirty[@]}" >/dev/null
  git -C "$TARGET" rev-parse HEAD
}

# ─── Phase 8: committed-edit divergence safety net ───────────
# Populated by detect_committed_divergence(). Each entry is a tab-separated
# triple: <managed-path>\t<lines-added-by-consumer>\t<lines-removed-by-consumer>
# (relative to Sysop's OLD install output for that path).
DIVERGED_PATHS=()

# Reconstruct what Sysop's OLD checkout (at the lock's sysop_commit)
# would have written into the target. Spawns a temporary git worktree of
# $REPO_ROOT at $old_commit, then invokes that OLD install.sh against a shadow
# target dir. After this returns 0, $shadow holds the OLD pipeline's output.
#
# Best-effort: returns non-zero (with a note: line) if the OLD commit is not
# reachable, the worktree-add fails, or the OLD install.sh exits non-zero.
# Callers should fall through to "skip pre-overwrite detection" on failure.
#
# Args: <old_commit> <shadow_target> <packs_csv>
reconstruct_old_install() {
  local old_commit="$1" shadow="$2" packs_csv="$3"

  if [[ -z "$old_commit" ]] || [[ "$old_commit" == "unknown" ]]; then
    note "divergence detection: lock has no sysop_commit anchor — skipping" >&2
    return 1
  fi

  if ! git -C "$REPO_ROOT" rev-parse --verify "${old_commit}^{commit}" >/dev/null 2>&1; then
    note "divergence detection: ${SYSOP_SRC_CLONE:-$REPO_ROOT} missing commit ${old_commit:0:12} — skipping" >&2
    note "  (try: git -C ${SYSOP_SRC_CLONE:-$REPO_ROOT} fetch, then re-run --update)" >&2
    return 1
  fi

  local tmp_worktree; tmp_worktree="$(mktemp -d)"
  # `git worktree add` wants a non-existing path it can create.
  rmdir "$tmp_worktree"

  if ! git -C "$REPO_ROOT" worktree add --detach --quiet "$tmp_worktree" "$old_commit" 2>/dev/null; then
    note "divergence detection: failed to materialise Sysop at ${old_commit:0:12} — skipping" >&2
    return 1
  fi

  # Always clean up the worktree on exit from this function.
  local rc=0

  if [[ ! -f "$tmp_worktree/install.sh" ]]; then
    note "divergence detection: ${old_commit:0:12} pre-dates the bash installer — skipping" >&2
    rc=1
  else
    # Shadow target needs to be a clean git repo so OLD install.sh's
    # validate_target accepts it. mktemp creates the dir; init it as a repo.
    git -C "$shadow" init --quiet 2>/dev/null || true
    git -C "$shadow" commit --allow-empty --quiet -m "init" 2>/dev/null || true

    # Phase 69: the consumer's role override (served_models.local.yml) lives in
    # THEIR tree, not REPO_ROOT, so the OLD installer running against this fresh
    # shadow would resolve skills with the DEFAULT mapping — and every
    # role-overridden skill would then be misreported as a committed local edit.
    # Seed the override into the shadow so the OLD installer's resolver (if it
    # has one) resolves identically to what the consumer committed. Harmless when
    # the OLD installer predates the resolver (the file is simply ignored).
    if [[ -f "$TARGET/.claude/served_models.local.yml" ]]; then
      mkdir -p "$shadow/.claude"
      cp "$TARGET/.claude/served_models.local.yml" "$shadow/.claude/served_models.local.yml" 2>/dev/null || true
    fi

    # Run the OLD installer against the shadow target. Capture stderr so we
    # can detect known failure modes (e.g., pre-Phase-5 installers that don't
    # recognise --no-arm-hooks). --force allows it to run against an empty/
    # dirty repo; --no-arm-hooks skips hook installation (harmless against
    # the shadow but pointless); --yes skips prompts.
    local old_stderr; old_stderr="$(mktemp)"
    if ! bash "$tmp_worktree/install.sh" "$shadow" \
           --packs "$packs_csv" \
           --force --no-arm-hooks --yes \
           >/dev/null 2>"$old_stderr"; then
      # Phase 5 added --no-arm-hooks (3142128). A lock anchored at a Phase 3
      # commit (9953f11, the only pre-Phase-5 commit where install.sh existed)
      # would reject the flag. Retry once without it.
      if grep -qE "Unknown option:.*--no-arm-hooks|invalid option.*--no-arm-hooks" "$old_stderr"; then
        note "divergence detection: OLD install.sh (${old_commit:0:12}) pre-dates --no-arm-hooks — retrying without it" >&2
        if ! bash "$tmp_worktree/install.sh" "$shadow" \
               --packs "$packs_csv" \
               --force --yes \
               >/dev/null 2>"$old_stderr"; then
          note "divergence detection: OLD install.sh (${old_commit:0:12}) exited non-zero on retry — skipping" >&2
          rc=1
        fi
      else
        note "divergence detection: OLD install.sh (${old_commit:0:12}) exited non-zero — skipping" >&2
        rc=1
      fi
    fi
    rm -f "$old_stderr"
  fi

  git -C "$REPO_ROOT" worktree remove --force "$tmp_worktree" >/dev/null 2>&1 || true
  return $rc
}

# Compare consumer's HEAD content of each managed path against the
# reconstructed OLD content under $shadow. Records divergences into
# the DIVERGED_PATHS global. Skips .claude/settings.json (Phase 6 merge
# preserves user edits there) and any path missing from either side
# (additions / removals are not "consumer edits being overwritten").
#
# Args: <shadow_target> <managed_path1> [<managed_path2> ...]
detect_committed_divergence() {
  local shadow="$1"; shift
  local mp consumer_content shadow_content added removed
  for mp in "$@"; do
    [[ "$mp" == ".claude/settings.json" ]] && continue
    # If the managed path isn't tracked in HEAD, skip (it's a fresh add the
    # consumer hasn't committed yet — Phase 7 snapshot handles uncommitted).
    if ! git -C "$TARGET" cat-file -e "HEAD:$mp" 2>/dev/null; then
      continue
    fi
    # If the shadow doesn't have the path, OLD Sysop didn't write it
    # (e.g., this is a newly-added managed path from a new pack version).
    [[ -f "$shadow/$mp" ]] || continue

    consumer_content="$(git -C "$TARGET" show "HEAD:$mp" 2>/dev/null || true)"
    shadow_content="$(cat "$shadow/$mp" 2>/dev/null || true)"

    if [[ "$consumer_content" == "$shadow_content" ]]; then
      continue
    fi

    # Count lines unique to each side via `diff`.
    # `diff` exit code: 0 = no diff, 1 = differ, 2 = error. We've already
    # established they differ, so just count.
    added=$(diff <(printf '%s' "$shadow_content") <(printf '%s' "$consumer_content") \
              | grep -c '^>' 2>/dev/null || true)
    removed=$(diff <(printf '%s' "$shadow_content") <(printf '%s' "$consumer_content") \
                | grep -c '^<' 2>/dev/null || true)
    DIVERGED_PATHS+=("$mp"$'\t'"${added:-0}"$'\t'"${removed:-0}")
  done
}

# Print the pre-overwrite divergence warning block. No-op if DIVERGED_PATHS
# is empty. Coloured + framed so it's hard to miss in the agent's output.
report_pre_overwrite_divergence() {
  (( ${#DIVERGED_PATHS[@]} == 0 )) && return 0
  hdr "⚠  committed local edits in managed paths"
  say ""
  say "  These files contain committed content that differs from Sysop's"
  say "  prior install. The overwrite below will replace them; consumer-added"
  say "  content will be lost unless re-applied AFTER --update completes."
  say ""
  local entry mp added removed
  for entry in "${DIVERGED_PATHS[@]}"; do
    IFS=$'\t' read -r mp added removed <<< "$entry"
    note "$mp  (+$added / -$removed vs old Sysop install)"
  done
  say ""
  say "  Before committing the update, recover any lost content via:"
  say "    git -C $TARGET show HEAD:<path>"
  say ""
}

# Print a per-managed-path delta table from `git diff HEAD --numstat`.
# Flags any file with deletions ≥ POST_OVERWRITE_FLAG_THRESHOLD lines, and
# any file already in DIVERGED_PATHS. Always runs (no preconditions).
POST_OVERWRITE_FLAG_THRESHOLD=5

report_post_overwrite_deltas() {
  (( ${#MANAGED_PATHS[@]} == 0 )) && return 0

  # Phase 24b preserved-paths block. git diff --numstat won't see these
  # (their working tree didn't change), so they need separate accounting.
  # Emitted ABOVE the standard numstat table.
  if (( ${#PRESERVED_PATHS[@]} > 0 )); then
    hdr "preserved managed paths (Phase 24b)"
    say ""
    local pp
    for pp in "${PRESERVED_PATHS[@]}"; do
      printf '  ↻  %s   (consumer-modified; --accept-upstream to overwrite)\n' "$pp"
    done
    say ""
    say "  preserved: ${#PRESERVED_PATHS[@]} managed path(s) preserved due to consumer modification."
    say "  Re-run with --accept-upstream <relpath> (repeatable) or --accept-upstream-list <file> to override."
  fi

  # Phase 24b stale --accept-upstream surfacing. Each ACCEPT_UPSTREAM entry
  # whose value is "1" (set on the command line) but NOT "applied" (never
  # matched a preserved path during the pipeline) was a no-op. Flag those
  # so a stale list-file entry doesn't quietly accumulate over time.
  local _ap_key _ap_val
  local -a _stale=()
  for _ap_key in "${!ACCEPT_UPSTREAM[@]}"; do
    _ap_val="${ACCEPT_UPSTREAM[$_ap_key]}"
    [[ "$_ap_val" == "1" ]] && _stale+=("$_ap_key")
  done
  if (( ${#_stale[@]} > 0 )); then
    hdr "stale --accept-upstream entries (Phase 24b)"
    for _ap_key in "${_stale[@]}"; do
      note "accept-upstream: $_ap_key not in preserved set; ignored"
    done
  fi

  # Phase 128 (§5 step 7): suppress the numstat rows for MOVED paths during a
  # namespace migration. With --no-renames a mass mv renders as a wall of
  # `+N 0` adds, real content changes are indistinguishable, the ≥5-deletions
  # heuristic can never fire, and preserved files double-report.
  # _ns_migration_report replaces those rows with an honest
  # moved/preserved/swept summary. Phase 133 narrows the suppression to the
  # move set only: NON-moved managed paths (`.claude/*` concat outputs stay
  # put, so their numstat rows are still meaningful) keep their rows — in the
  # Phase-99 ancestor-unreachable fallback and the adopt-bridge path this
  # table is the LAST per-file signal for committed edits to those files, and
  # the blanket early-return removed it exactly when pre-overwrite detection
  # wasn't possible (the residual gap the Phase-128 post-open review filed).
  local -a paths=()
  local mp
  for mp in "${MANAGED_PATHS[@]}"; do
    [[ "$mp" == ".claude/settings.json" ]] && continue
    if [[ "$MIGRATION_MODE" -eq 1 ]] && [[ "$(_ns_new_to_old "$mp")" != "$mp" ]]; then
      continue   # moved path — reported by _ns_migration_report instead
    fi
    paths+=("$mp")
  done
  (( ${#paths[@]} == 0 )) && return 0

  # `git diff HEAD --numstat` against a list that may include untracked or
  # newly-renamed entries can be noisy; --no-renames keeps it path-stable.
  local numstat
  numstat="$(git -C "$TARGET" diff HEAD --numstat --no-renames -- "${paths[@]}" 2>/dev/null || true)"
  [[ -z "$numstat" ]] && return 0

  hdr "post-overwrite delta (vs HEAD)"
  say ""
  printf '  %5s  %5s  %s\n' '+lines' '-lines' 'path'
  printf '  %5s  %5s  %s\n' '------' '------' '----'

  # Build a quick lookup of paths flagged by pre-overwrite divergence.
  declare -A flagged_paths=()
  local entry diverged_mp
  for entry in "${DIVERGED_PATHS[@]}"; do
    IFS=$'\t' read -r diverged_mp _ _ <<< "$entry"
    flagged_paths[$diverged_mp]=1
  done

  local added removed path flag
  while IFS=$'\t' read -r added removed path; do
    [[ -z "$path" ]] && continue
    flag=" "
    if [[ -n "${flagged_paths[$path]:-}" ]]; then
      flag="⚠"
    elif [[ "$removed" =~ ^[0-9]+$ ]] && (( removed >= POST_OVERWRITE_FLAG_THRESHOLD )); then
      flag="⚠"
    fi
    printf '  %5s  %5s  %s %s\n' "$added" "$removed" "$flag" "$path"
  done <<< "$numstat"
  say ""
  say "  ⚠ flags files with ≥${POST_OVERWRITE_FLAG_THRESHOLD} deleted lines or pre-overwrite divergence."
  say "  Read each ⚠ file's diff before committing — Sysop's overwrite"
  say "  may have removed consumer-added content."
}

# Phase 25 (BeanRider ISSUE-0026): lazy-load substitution keys from
# `.claude/substitutions.project.yml`. Populates SUBSTITUTION_KEYS_LIST (preserves
# author order) and pre-zeroes SUBSTITUTION_USAGE_COUNT[$key] so the stale-token
# report can name typos that didn't match anywhere. Idempotent — guarded by
# SUBSTITUTION_KEYS_LOADED so repeat callers from concat_files / the end-of-run
# report do one read. Returns 1 only if the file exists but is unparseable
# (malformed YAML, missing pyyaml); absent file is a silent no-op.
_load_substitution_keys() {
  [[ "$SUBSTITUTION_KEYS_LOADED" -eq 1 ]] && return 0
  SUBSTITUTION_KEYS_LOADED=1
  local subs_path="$TARGET/$SYSOP_SUBSTITUTIONS_FILE"
  [[ ! -f "$subs_path" ]] && return 0
  local _py
  if ! _py="$(pick_python_with_yaml)"; then
    err "substitutions: cannot load $SYSOP_SUBSTITUTIONS_FILE — no python3 with pyyaml available"
    err "  tried: $TARGET/.venv/bin/python3, $TARGET/venv/bin/python3, python3"
    err "  fix:   python3 -m venv .venv && .venv/bin/pip install pyyaml"
    err "         (or 'pip install pyyaml' into whichever python3 is on PATH)"
    return 1
  fi
  local _keys
  if ! _keys="$("$_py" - "$subs_path" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f) or {}
subs = data.get('substitutions') if isinstance(data, dict) else None
if subs is None:
    sys.stderr.write("  ⚠ substitutions: top-level 'substitutions:' mapping missing or empty\n")
    sys.exit(0)
if not isinstance(subs, dict):
    sys.stderr.write("  ⚠ substitutions: 'substitutions' must be a mapping\n")
    sys.exit(0)
for k, v in subs.items():
    if not isinstance(k, str):
        sys.stderr.write("  ⚠ substitutions: skipping non-string key %r\n" % (k,))
        continue
    if not isinstance(v, str):
        sys.stderr.write("  ⚠ substitutions: skipping non-string value for %r: %r\n" % (k, v))
        continue
    if '\n' in v:
        sys.stderr.write("  ⚠ substitutions: skipping multi-line value for %r\n" % (k,))
        continue
    print(k)
PY
  )"; then
    err "substitutions: failed to parse $SYSOP_SUBSTITUTIONS_FILE (see python error above)"
    return 1
  fi
  local _k
  while IFS= read -r _k; do
    [[ -z "$_k" ]] && continue
    SUBSTITUTION_KEYS_LIST+=("$_k")
    SUBSTITUTION_USAGE_COUNT["$_k"]=0
  done <<< "$_keys"
}

# Phase 25 (BeanRider ISSUE-0026): apply the substitution map to a concat-style
# destination. Called from concat_files AFTER the upstream body is written and
# BEFORE the suffix file is appended/merged — so the substitution effect is
# bounded to upstream-shipped placeholder text. The consumer's suffix file
# content is taken byte-faithfully (consumers author concrete paths in their
# suffix; if they want a token substituted there, they substitute it themselves).
# Uses .count() + .replace() (literal string replacement, not regex) so
# placeholder vocabulary that includes special characters is handled correctly.
#
# Phase 55 (BeanRider ISSUE-0041): scoped to `paths:` values in checks.yml
# only. The substitution's purpose is routing nonexistent-directory checks to
# a sentinel (e.g. `__disabled_no_op__`) so run_checks skips them — a paths
# concern. Applying the same byte-substitution to the markdown maps rewrote
# section headers into junk (`## __disabled_no_op__/*.py — Auth`); upstream
# placeholder tokens in convention_map.md / security_map.md are accurate
# documentation and stay verbatim. Substitution is line-scoped (inline
# `paths: [...]` and block-form `paths:` items) rather than a YAML round-trip
# so comments in the assembled body survive (same posture as the ISSUE-0042
# merge fix below).
apply_substitutions() {
  local dst="$1"
  case "$dst" in
    */checks.yml) ;;
    *) return 0 ;;
  esac
  local subs_path="$TARGET/$SYSOP_SUBSTITUTIONS_FILE"
  [[ ! -f "$subs_path" ]] && return 0
  _load_substitution_keys || return 1
  [[ "${#SUBSTITUTION_KEYS_LIST[@]}" -eq 0 ]] && return 0
  local _py
  if ! _py="$(pick_python_with_yaml)"; then
    return 1
  fi
  local _counts
  if ! _counts="$("$_py" - "$subs_path" "$dst" <<'PY'
import os, re, sys, tempfile, yaml
subs_path, dst_path = sys.argv[1], sys.argv[2]
with open(subs_path) as f:
    data = yaml.safe_load(f) or {}
subs = data.get('substitutions') if isinstance(data, dict) else None
if not isinstance(subs, dict):
    sys.exit(0)
pairs = [(k, v) for k, v in subs.items()
         if isinstance(k, str) and isinstance(v, str) and '\n' not in v]
if not pairs:
    sys.exit(0)
with open(dst_path) as f:
    lines = f.readlines()
PATHS_KEY = re.compile(r'^(\s*)paths:(\s*)(\S.*)?$')
counts = {}
out = []
in_paths_block = False
block_indent = 0
for line in lines:
    substitute = False
    m = PATHS_KEY.match(line)
    if m:
        if m.group(3):              # inline flow form: paths: ["..."]
            substitute = True
            in_paths_block = False
        else:                       # block form: paths:\n  - "..."
            in_paths_block = True
            block_indent = len(m.group(1))
    elif in_paths_block:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped.startswith('-') and indent > block_indent:
            substitute = True
        elif stripped:              # dedent or a sibling key: block over
            in_paths_block = False
    if substitute:
        for k, v in pairs:
            n = line.count(k)
            if n:
                line = line.replace(k, v)
                counts[k] = counts.get(k, 0) + n
    out.append(line)
if counts:
    d = os.path.dirname(os.path.abspath(dst_path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.wf-subst.')
    try:
        with os.fdopen(fd, 'w') as f:
            f.writelines(out)
        os.replace(tmp, dst_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
for k, n in counts.items():
    print("%s\t%d" % (k, n))
PY
  )"; then
    err "substitutions: failed to apply to $(rel "$dst") (see python error above)"
    return 1
  fi
  local _total=0
  local _k _n
  while IFS=$'\t' read -r _k _n; do
    [[ -z "$_k" ]] && continue
    SUBSTITUTION_USAGE_COUNT["$_k"]=$(( ${SUBSTITUTION_USAGE_COUNT["$_k"]:-0} + _n ))
    _total=$(( _total + _n ))
  done <<< "$_counts"
  if [[ "$_total" -gt 0 ]]; then
    note "substitute: $_total token replacement(s) in $(rel "$dst") (from $SYSOP_SUBSTITUTIONS_FILE)"
  fi
}

# Phase 25 (BeanRider ISSUE-0026): post-install report of substitution keys
# that didn't match any `paths:` value in the regenerated checks.yml (Phase 55
# narrowed the substitution scope — see apply_substitutions). Likely typos
# (e.g., `<api modules>` for `<api module>`) or stale entries from a layout
# change.
# Real-run only — apply_substitutions is gated behind concat_files' dry-run
# early-return, so in dry-run SUBSTITUTION_USAGE_COUNT stays at 0 for every
# key and would produce false-positive "all stale" output. Real-run output
# (visible to the agent before they commit the absorption) is the correct
# place for this signal.
report_stale_substitutions() {
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  local subs_path="$TARGET/$SYSOP_SUBSTITUTIONS_FILE"
  [[ ! -f "$subs_path" ]] && return 0
  _load_substitution_keys || return 0
  [[ "${#SUBSTITUTION_KEYS_LIST[@]}" -eq 0 ]] && return 0
  local _stale=()
  local _k
  for _k in "${SUBSTITUTION_KEYS_LIST[@]}"; do
    if [[ "${SUBSTITUTION_USAGE_COUNT[$_k]:-0}" -eq 0 ]]; then
      _stale+=("$_k")
    fi
  done
  [[ "${#_stale[@]}" -eq 0 ]] && return 0
  say ""
  say "── stale substitutions (Phase 25 / BeanRider ISSUE-0026 safety check) ──"
  say ""
  say "  The following keys in $SYSOP_SUBSTITUTIONS_FILE did not match any"
  say "  paths: value in the regenerated .claude/checks.yml. Substitution is"
  say "  scoped to checks.yml paths: lines (Phase 55 / ISSUE-0041 — markdown"
  say "  maps are never substituted). Likely typos, stale entries from a"
  say "  layout change, or keys that only ever matched markdown prose:"
  say ""
  for _k in "${_stale[@]}"; do
    say "    $_k"
  done
  say ""
  say "  Fix: remove stale keys or correct typos. Compare against placeholder"
  say "  tokens actually present in upstream paths: values with:"
  say "    grep -E '^\\s*paths:' .claude/checks.yml | grep -oE '<[a-z][a-z _-]+>' | sort -u"
}

# Concatenate a list of source files into one destination, prepending an optional
# header to the dest and (for fragments after the first) stripping leading
# comment/blank lines up to and including the first non-comment YAML key.
#
# Strip a YAML file's leader — everything from the start through (and
# including) the first non-comment, non-blank top-level `<key>:` line (matches
# `checks:`) — and emit the remainder on stdout. Used for pack fragments after
# the first and for `*.project.yml` suffix appends.
strip_yaml_leader() {
  awk '
    BEGIN { stripping = 1 }
    stripping && /^[[:space:]]*$/  { next }
    stripping && /^[[:space:]]*#/  { next }
    stripping && /^[A-Za-z_][A-Za-z0-9_-]*:[[:space:]]*$/ { stripping = 0; next }
    { print }
  ' "$1"
}

# Usage: concat_files <dst> <strip_yaml_header_after_first:0|1> <src1> [src2 ...]
concat_files() {
  local dst="$1" strip_yaml_header="$2"
  shift 2
  ensure_dir "$(dirname "$dst")"

  local rels=""
  local s
  for s in "$@"; do rels+=" $(rel "$s")"; done
  note "concat: $rels → $(rel "$dst")"
  record_managed_path "$dst"

  # Phase 24a: announce would-be suffix append in dry-run too, so the plan
  # reflects every actual effect. Lookup-only — never reads the file.
  # Phase 25: also announce would-be substitution when the substitutions file
  # exists. Doesn't pre-resolve match counts (the upstream body isn't written
  # in dry-run), just signals that substitution will fire.
  if [[ "$DRY_RUN" -eq 1 ]]; then
    local _dst_rel="${dst#"$TARGET"/}"
    # Phase 55 (ISSUE-0041): substitution only fires for checks.yml paths.
    if [[ -f "$TARGET/$SYSOP_SUBSTITUTIONS_FILE" ]] && [[ "$_dst_rel" == */checks.yml ]]; then
      note "would substitute: tokens from $SYSOP_SUBSTITUTIONS_FILE in $(rel "$dst") paths: values"
    fi
    local _suffix_rel="${SYSOP_PROJECT_SUFFIXES[$_dst_rel]:-}"
    if [[ -n "$_suffix_rel" ]] && [[ -f "$TARGET/$_suffix_rel" ]]; then
      case "$_dst_rel" in
        */checks.yml) note "would merge: $_suffix_rel → $(rel "$dst") (by checks[*].id)" ;;
        *.md)         note "would append: $_suffix_rel → $(rel "$dst")" ;;
      esac
    fi
    return 0
  fi

  : > "$dst"
  local first=1
  for s in "$@"; do
    if [[ "$first" -eq 1 ]] || [[ "$strip_yaml_header" -eq 0 ]]; then
      cat "$s" >> "$dst"
    else
      strip_yaml_leader "$s" >> "$dst"
    fi
    printf '\n' >> "$dst"
    first=0
  done

  # Phase 25 (BeanRider ISSUE-0026): apply consumer-authored placeholder
  # substitutions to the upstream body. Runs AFTER concat (so all upstream +
  # pack content is in the dst) and BEFORE the suffix-file append (so the
  # consumer's suffix content stays byte-faithful). Hard-fails the concat on
  # malformed substitutions file or missing pyyaml — same posture as the
  # checks.project.yml merge below.
  apply_substitutions "$dst" || return 1

  # Phase 24a (BeanRider ISSUE-0023): append consumer-authored `*.project.<ext>`
  # suffix file when present. Lookup by target-relative dst; markdown targets
  # text-append with a blank-line separator, checks.yml merges by checks[*].id.
  # The suffix file is never written by the installer and is never tracked in
  # MANAGED_PATHS — `--update` is incapable of touching it.
  local dst_rel="${dst#"$TARGET"/}"
  local suffix_rel="${SYSOP_PROJECT_SUFFIXES[$dst_rel]:-}"
  if [[ -n "$suffix_rel" ]] && [[ -f "$TARGET/$suffix_rel" ]]; then
    case "$dst_rel" in
      */checks.yml)
        # YAML-aware merge by checks[*].id. Common case (no id-collision) is a
        # header-strip + text-append — preserves comments and formatting in
        # both files so the post-update diff stays signal-only. Collision case
        # falls back to a structural round-trip via pyyaml that substitutes
        # the colliding entries and emits per-collision warn lines (consumer
        # wins; the round-trip loses upstream comments by necessity — the
        # warn line surfaces this).
        local _py
        if ! _py="$(pick_python_with_yaml)"; then
          err "concat: cannot merge $suffix_rel — no python3 with pyyaml available"
          err "  tried: $TARGET/.venv/bin/python3, $TARGET/venv/bin/python3, python3"
          err "  fix:   python3 -m venv .venv && .venv/bin/pip install pyyaml"
          err "         (or 'pip install pyyaml' into whichever python3 is on PATH)"
          return 1
        fi
        # Pre-scan ids; collisions print one id per line to stdout.
        local _collisions
        if ! _collisions="$("$_py" - "$dst" "$TARGET/$suffix_rel" <<'PY'
import sys, yaml
base_path, proj_path = sys.argv[1], sys.argv[2]
with open(base_path) as f: base = yaml.safe_load(f) or {}
with open(proj_path) as f: proj = yaml.safe_load(f) or {}
base_ids = {c['id'] for c in (base.get('checks') or []) if isinstance(c, dict) and 'id' in c}
seen_in_proj, dupes = set(), []
for c in (proj.get('checks') or []):
    if not isinstance(c, dict) or 'id' not in c:
        sys.stderr.write("  ⚠ skip: project check missing 'id' field: %r\n" % (c,))
        continue
    cid = c['id']
    if cid in seen_in_proj:
        sys.stderr.write("  ⚠ duplicate id in project file: %s (last wins)\n" % cid)
    seen_in_proj.add(cid)
    if cid in base_ids:
        print(cid)
PY
        )"; then
          err "concat: pre-scan of $suffix_rel failed (see python error above)"
          return 1
        fi

        if [[ -z "$_collisions" ]]; then
          # No id-collision: header-strip the suffix file (drop leading
          # comments / blanks and the `checks:` line itself) and text-append.
          # Both files' comments survive.
          strip_yaml_leader "$TARGET/$suffix_rel" >> "$dst"
          note "append: $suffix_rel → $(rel "$dst") (text-append; no id-collision)"
        else
          # Collision(s): Phase 55 (BeanRider ISSUE-0042) text-level merge.
          # Remove the colliding entries from the upstream-assembled body,
          # then header-strip + text-append the whole project file — exactly
          # the no-collision path. Comments in BOTH files survive byte-
          # faithfully; the structural pyyaml round-trip this replaces dropped
          # every comment in the project file (including the `# OVERRIDE
          # (...):` annotations the overrides exist to explain) on every
          # update cycle. Trade-off: overridden entries live at their
          # project-file position (end of the merged file), not the upstream
          # position. The structural merge survives below as a fallback for
          # upstream bodies the line-based removal can't confidently parse.
          local _cid
          while IFS= read -r _cid; do
            [[ -z "$_cid" ]] && continue
            note "⚠ id-collision: $_cid (consumer overrides upstream)"
          done <<< "$_collisions"
          if _SYSOP_COLLISIONS="$_collisions" "$_py" - "$dst" <<'PY'
import os, re, sys, tempfile, yaml
dst_path = sys.argv[1]
target = {c.strip() for c in os.environ.get('_SYSOP_COLLISIONS', '').splitlines() if c.strip()}
with open(dst_path) as f:
    lines = f.readlines()

# Locate top-level `checks:` sequence entries by their dash lines (minimum
# dash indent in the file) and the `id:` each block declares. Exit 3 — the
# "fall back to structural merge" signal — whenever the parse is anything
# short of fully confident.
ENTRY_START = re.compile(r'^(\s*)- ')
ID_LINE = re.compile(r'''^\s*(?:- )?id:\s*["']?([^"'\s#]+)''')
dash_lines = [(i, len(m.group(1))) for i, m in
              ((i, ENTRY_START.match(l)) for i, l in enumerate(lines)) if m]
if not dash_lines:
    sys.exit(3)
min_indent = min(ind for _, ind in dash_lines)
entry_starts = [i for i, ind in dash_lines if ind == min_indent]
blocks = []
for n, si in enumerate(entry_starts):
    end = entry_starts[n + 1] if n + 1 < len(entry_starts) else len(lines)
    for j in range(si + 1, end):
        # A dedented top-level key after the sequence ends the block early.
        if re.match(r'^[A-Za-z_]', lines[j]):
            end = j
            break
    # Trim trailing blank + comment lines off the block so a section-header
    # comment introducing the NEXT entry survives this entry's removal.
    while end > si + 1 and (lines[end - 1].strip() == ''
                            or lines[end - 1].lstrip().startswith('#')):
        end -= 1
    bid = None
    for j in range(si, end):
        m = ID_LINE.match(lines[j])
        if m:
            bid = m.group(1)
            break
    blocks.append((si, end, bid))

found = {bid for _, _, bid in blocks if bid in target}
if found != target:
    sys.exit(3)
remove = [(s, e) for s, e, bid in blocks if bid in target]
keep = [l for i, l in enumerate(lines) if not any(s <= i < e for s, e in remove)]
new_text = ''.join(keep)
# Validate the removal before committing it: the body must still parse and
# must no longer contain any colliding id.
try:
    parsed = yaml.safe_load(new_text) or {}
    ids = {c.get('id') for c in (parsed.get('checks') or []) if isinstance(c, dict)}
except yaml.YAMLError:
    sys.exit(3)
if target & ids:
    sys.exit(3)
d = os.path.dirname(os.path.abspath(dst_path))
fd, tmp = tempfile.mkstemp(dir=d, prefix='.wf-merge.')
try:
    with os.fdopen(fd, 'w') as f:
        f.write(new_text)
    os.replace(tmp, dst_path)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise
PY
          then
            strip_yaml_leader "$TARGET/$suffix_rel" >> "$dst"
            note "merge: $suffix_rel → $(rel "$dst") (text-level by checks[*].id; comments preserved; overridden entries take the project-file position)"
          else
            # Fallback: structural round-trip merge. Comments in both files
            # are lost; the consumer was warned per colliding id above.
            note "⚠ text-level merge could not confidently parse $(rel "$dst") — falling back to structural merge (comments will be lost)"
            if ! "$_py" - "$dst" "$TARGET/$suffix_rel" <<'PY'
import sys, yaml
base_path, proj_path = sys.argv[1], sys.argv[2]
with open(base_path) as f: base = yaml.safe_load(f) or {}
with open(proj_path) as f: proj = yaml.safe_load(f) or {}
base_checks = [c for c in (base.get('checks') or []) if isinstance(c, dict)]
base_index = {c['id']: i for i, c in enumerate(base_checks) if 'id' in c}
for c in (proj.get('checks') or []):
    if not isinstance(c, dict) or 'id' not in c:
        continue
    cid = c['id']
    if cid in base_index:
        base_checks[base_index[cid]] = c
    else:
        base_index[cid] = len(base_checks)
        base_checks.append(c)
base['checks'] = base_checks
with open(base_path, 'w') as f:
    yaml.safe_dump(base, f, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120)
PY
            then
              err "concat: failed to merge $suffix_rel into $(rel "$dst") (see python error above)"
              return 1
            fi
            note "merge: $suffix_rel → $(rel "$dst") (structural; comments lost on collision)"
          fi
        fi
        ;;
      *.md)
        # Plain text-append with a blank-line separator. Malformed markdown in
        # the suffix file is the consumer's responsibility — append is byte-faithful.
        { printf '\n'; cat "$TARGET/$suffix_rel"; } >> "$dst"
        note "append: $suffix_rel → $(rel "$dst")"
        ;;
    esac
  fi
}

# ─── build install plan + execute ────────────────────────────
PLAN_SUMMARY=()

record() { PLAN_SUMMARY+=("$1"); }

install_workflow_docs() {
  hdr "workflow docs"
  copy_file "$REPO_ROOT/core/companion/docs/WORKFLOW.md"       "$TARGET/sysop/docs/WORKFLOW.md"
  copy_file "$REPO_ROOT/core/companion/docs/WORKFLOW_GUIDE.md" "$TARGET/sysop/docs/WORKFLOW_GUIDE.md"
  record "workflow docs: sysop/docs/WORKFLOW.md, sysop/docs/WORKFLOW_GUIDE.md"
}

install_skills() {
  hdr "skills"
  local src="$REPO_ROOT/core/skills"
  local dst="$TARGET/.claude/skills"
  if [[ ! -d "$src" ]]; then return 0; fi
  ensure_dir "$dst"
  local skill_count=0
  local d
  for d in "$src"/*/; do
    [[ -d "$d" ]] || continue
    local name; name="$(basename "$d")"
    # Loop mode: ship only the convention-loop skills (+ _shared, partial-filtered).
    if [[ "$INSTALL_MODE" == "loop" ]] && _loop_excludes "$name" "$LOOP_EXCLUDE_SKILLS"; then
      continue
    fi
    local f
    for f in "$d"*; do
      [[ -f "$f" ]] || continue
      # Loop mode: within _shared/, ship only the five skills' partial closure.
      if [[ "$INSTALL_MODE" == "loop" && "$name" == "_shared" ]] \
         && _loop_excludes "$(basename "$f" .md)" "$LOOP_EXCLUDE_SHARED"; then
        continue
      fi
      copy_file "$f" "$dst/$name/$(basename "$f")"
    done
    skill_count=$((skill_count + 1))
  done
  local _mode_note=""; [[ "$INSTALL_MODE" == "loop" ]] && _mode_note=" (loop mode: lifecycle skills excluded)"
  record "skills: $skill_count skill dir(s) copied to .claude/skills/$_mode_note"
}

# ─── Phase 142: Codex-native skill links (tools/CODEX_INTEGRATION_SPEC.md) ───
# Identity of a link is its RAW target string, never the bytes it resolves to: a
# *different* link is consumer data even when it happens to resolve to the same
# skill. Every comparison below reads `readlink` output, never the file content.
_codex_link_want() { printf '../../.claude/skills/%s' "$1"; }
_codex_link_rel()  { printf '.agents/skills/%s' "$1"; }

# 0 = the entry at <target>/$1 is exactly Sysop's link. Non-zero for absent,
# foreign symlink, file, or directory.
_codex_link_is_ours() {
  local relp="$1" name want
  name="${relp#.agents/skills/}"
  want="$(_codex_link_want "$name")"
  [[ -L "$TARGET/$relp" ]] || return 1
  [[ "$(readlink "$TARGET/$relp" 2>/dev/null || true)" == "$want" ]]
}

# Sweep guard for the .agents/ namespace. Returns 0 ("leave it alone") for
# everything there EXCEPT one case: a depth-1 `.agents/skills/<name>` entry that
# is still exactly Sysop's link, which returns 1 and sweeps normally (including
# a BROKEN link carrying our raw target — its skill was retired upstream).
#
# Default-deny is load-bearing, not caution. The sweep resolves its candidate
# with `-e`, which follows symlinks, and removes with `rm -f` — so a lock entry
# naming a path THROUGH one of our links (`.agents/skills/codebase-review/
# SKILL.md`) would delete the real skill body out of `.claude/skills/`. Only a
# hand-edited or corrupted lock produces such an entry, which is exactly the
# threat model the sibling consumer-path guard in the sweep exists for.
_codex_link_not_ours() {
  local relp="$1" name
  # Outside .agents/ entirely — not our namespace, normal sweep rules apply.
  [[ "$relp" == .agents/* ]] || return 1
  name="${relp#.agents/skills/}"
  # Anything that is not exactly a depth-1 .agents/skills/<name> entry — a path
  # through a link, `.agents/skills` itself, `.agents/anything-else` — is not
  # ours to delete.
  [[ "$relp" == ".agents/skills/$name" ]] || return 0
  [[ -n "$name" && "$name" != */* ]] || return 0
  _codex_link_is_ours "$relp" && return 1
  return 0
}

# Create (or verify) one relative skill link. NEVER exits under DRY_RUN — it runs
# inside cmd_adopt's managed-paths computation and _ns_precompute_and_derive's
# `run_install_pipeline >/dev/null 2>&1`, where a bash `exit` kills --update with
# zero output (the `|| true` catches a non-zero return, not an exit).
ensure_relative_symlink() {
  local name="$1"
  local relp; relp="$(_codex_link_rel "$name")"
  local dst="$TARGET/$relp"
  local want; want="$(_codex_link_want "$name")"

  # 1. DRY_RUN (--dry-run, adopt's compute pass, the migration precompute):
  #    classify + record only — no creation, no verification, no error.
  if [[ "$DRY_RUN" -eq 1 ]]; then
    if _codex_link_is_ours "$relp"; then
      note "link: $relp → $want (unchanged)"
      record_managed_path "$dst"
    elif [[ -L "$dst" || -e "$dst" ]]; then
      # Consumer-owned. Deliberately NOT recorded: a path Sysop doesn't own must
      # never enter managed_paths, where a later sweep would put consumer data in
      # the deletion blast radius. This is what makes `--adopt` of a genuine
      # Codex user safe — adopt records reality and moves on, and the collision
      # surfaces as a hard error the next time emission actually runs.
      note "⚠ $relp is not Sysop's link — leaving it unmanaged"
    else
      note "link: $relp → $want (capability probed at apply time)"
      record_managed_path "$dst"
    fi
    return 0
  fi

  # 3. Already ours → unchanged, but still recorded: the lock must stay accurate
  #    on re-install, and this is what makes a --force full re-apply a genuine
  #    no-op rather than a delete/recreate (inode churn).
  if _codex_link_is_ours "$relp"; then
    note "link: $relp → $want (unchanged)"
    record_managed_path "$dst"
    return 0
  fi

  # 4. Anything else present → defense in depth only. preflight_codex_links owns
  #    this failure and has already fired in every normal flow; reaching here
  #    means a direct/scripted call that bypassed it.
  if [[ -L "$dst" || -e "$dst" ]]; then
    err "Refusing to replace $relp — it is not Sysop's link."
    err "  Move it aside, or re-run with --no-codex-links."
    exit 1
  fi

  # Probe said this filesystem can't do relative dir symlinks. Nothing to create;
  # nothing recorded (there is no path to manage).
  if [[ "$CODEX_LINKS_CREATE_DISABLED" -eq 1 ]]; then
    return 0
  fi

  # 2. Absent → create. Both writes carry a guided error rather than letting
  #    `set -e` abort the pipeline on a bare mkdir/ln failure — preflight (a0)
  #    catches the reachable causes, so this is the unreachable-cause net
  #    (a race, an exotic mount) and it must still say what to do.
  note "link: $relp → $want"
  if ! mkdir -p "$(dirname "$dst")" 2>/dev/null; then
    err "Could not create $(dirname "$relp")/ for the Codex skill links."
    err "  Re-run with --no-codex-links to install without them."
    exit 1
  fi
  if ! ln -s "$want" "$dst" 2>/dev/null; then
    err "Could not create the symlink $relp."
    err "  Re-run with --no-codex-links to install without them."
    exit 1
  fi

  # 5. Post-write verify — the one chance to catch a filesystem that passed the
  #    probe but lies about real links. Reading SKILL.md THROUGH the link is the
  #    assertion that matters: it proves traversal, not just the entry.
  if ! _codex_link_is_ours "$relp" || [[ ! -r "$dst/SKILL.md" ]]; then
    err "Codex link verification failed for $relp."
    err "  The link was created but does not resolve to a readable"
    err "  .claude/skills/$name/SKILL.md. Re-run with --no-codex-links to skip."
    exit 1
  fi
  record_managed_path "$dst"
}

install_codex_links() {
  if [[ "$CODEX_LINKS" -eq 0 ]]; then
    # Opt-out on a tree that still carries the links. Under --update the
    # obsolete-path sweep owns this (it has the old lock to diff against), but a
    # plain re-install never reaches the sweep — so without this the links would
    # sit on disk forever, dropped from managed_paths yet still registering with
    # Codex: exactly the state the consumer opted out of, now unmanaged.
    # Guarded by raw target, so only ever our own link is removed.
    if [[ "$DRY_RUN" -eq 0 ]] && [[ "$UPDATE_MODE" -eq 0 ]]; then
      local _n _relp _removed=0
      for _n in "${CODEX_SKILLS[@]}"; do
        _relp="$(_codex_link_rel "$_n")"
        _codex_link_is_ours "$_relp" || continue
        (( _removed == 0 )) && hdr "codex skill links"
        _removed=1
        note "remove: $_relp (codex links disabled)"
        git -C "$TARGET" rm -f --quiet -- "$_relp" 2>/dev/null || rm -f -- "$TARGET/$_relp"
      done
      (( _removed == 1 )) && record "Codex: native skill links removed (--no-codex-links)"
    fi
    return 0
  fi
  hdr "codex skill links"
  local name
  for name in "${CODEX_SKILLS[@]}"; do
    ensure_relative_symlink "$name"
  done
  if [[ "$DRY_RUN" -eq 0 ]] && [[ "$CODEX_LINKS_CREATE_DISABLED" -eq 1 ]]; then
    record "Codex: skipped (no symlink support — see docs/install-and-update.md § Codex)"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    # The house dry-run annotation: the capability probe is apply-time, so this
    # is a plan, not an outcome — both links may still be skipped at apply time.
    record "Codex: ${#CODEX_SKILLS[@]} native skill links (.agents/skills/) (planned; probed at apply time)"
  else
    record "Codex: ${#CODEX_SKILLS[@]} native skill links (.agents/skills/)"
  fi
}

# Pinned in main() immediately after the T7 guard and strictly BEFORE the
# Phase-128 migration block — which puts it ahead of _ns_precompute_and_derive's
# hidden DRY_RUN pipeline run, the pre-update snapshot commit, the namespace tree
# moves, and the runtime-dir migration: i.e. before EVERY target mutation, in
# both fresh and update mode. Deliberately NOT --force-gated (house precedent:
# T7's genuine collision has no --force bypass; the adjacent snapshot/divergence
# steps are FORCE-gated and must not be pattern-matched here).
preflight_codex_links() {
  [[ "$CODEX_LINKS" -eq 1 ]] || return 0
  local name relp

  # (a0) Parent-component check. The leaf checks in (a) cannot see a consumer
  # FILE at .agents, or an .agents/skills we can't write into. Left to (b) and
  # the pipeline, both surface as a bare `mkdir`/`ln` failure that `set -e`
  # turns into a mid-pipeline abort — AFTER install_skills has written and,
  # under --update, after the pre-update snapshot commit: a half-applied target
  # with a stale lock. Refusing here costs nothing, and keeps the § 8.2d promise
  # ("a refused run leaves the tree byte-identical") true for parents too.
  local parent
  for parent in ".agents" ".agents/skills"; do
    [[ -e "$TARGET/$parent" || -L "$TARGET/$parent" ]] || continue
    if [[ ! -d "$TARGET/$parent" ]]; then
      err "$parent exists and is not a directory."
      err "  Sysop needs to create $parent/ to register its review skills with Codex."
      err "  Move your $parent aside, or re-run with --no-codex-links."
      exit 1
    fi
  done
  # Writability of the deepest existing ancestor — a read-only or 555 parent
  # is the other way `ln` dies mid-pipeline.
  local anchor="$TARGET"
  [[ -d "$TARGET/.agents" ]] && anchor="$TARGET/.agents"
  [[ -d "$TARGET/.agents/skills" ]] && anchor="$TARGET/.agents/skills"
  if [[ ! -w "$anchor" ]]; then
    err "$(rel "$anchor") is not writable, so the Codex skill links can't be created."
    err "  Fix its permissions, or re-run with --no-codex-links."
    exit 1
  fi

  # (a) Collision check — the SOLE owner of the collision hard-error, because
  # ensure_relative_symlink runs in three DRY_RUN contexts where an error would
  # be invisible or fatal. Read-only, so it runs under --dry-run too.
  #
  # Hard-fail rather than skip-with-a-warning is deliberate: a consumer-owned
  # .agents/skills/codebase-review means ordinary requests route to THEIR
  # workflow while a skipped install still claims Sysop is set up — the silent-
  # divergence shape the fan-out and pre-scan work exists to kill. The consumer
  # must acknowledge it, not discover it later.
  for name in "${CODEX_SKILLS[@]}"; do
    relp="$(_codex_link_rel "$name")"
    _codex_link_is_ours "$relp" && continue          # already ours
    [[ -L "$TARGET/$relp" || -e "$TARGET/$relp" ]] || continue   # absent
    err "$relp already exists and isn't Sysop's link."
    err "  Sysop registers its two review skills for Codex by linking:"
    err "    $relp → $(_codex_link_want "$name")"
    err "  Leaving your entry in place would route ordinary Codex requests to it"
    err "  while this install reported success. Pick one:"
    err "    • move or rename your $relp, then re-run; or"
    err "    • re-run with --no-codex-links (recorded in the lock, so you only"
    err "      say it once — future sysop-update.sh runs honor it)."
    exit 1
  done

}

# (b) Capability probe. Split out of the preflight and called AFTER the plan is
# confirmed, because unlike the checks above this one WRITES (a throwaway dir
# inside the target — target-local on purpose, so it tests the consumer's own
# filesystem rather than /tmp's). A run the user declines at the Proceed? prompt
# must not have touched their repo. Apply-time only, and only when a link
# actually needs creating: if both entries already exist and are ours there is
# nothing to probe, and a probe failure must never be inferred for them.
probe_codex_link_capability() {
  [[ "$CODEX_LINKS" -eq 1 ]] || return 0
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  local name need=0
  for name in "${CODEX_SKILLS[@]}"; do
    _codex_link_is_ours "$(_codex_link_rel "$name")" || { need=1; break; }
  done
  (( need == 1 )) || return 0

  # Target-local so the probe tests the CONSUMER's filesystem (the WSL / /mnt/c /
  # exotic-mount case), not the temp dir's. Registered with the EXIT trap.
  if ! CODEX_PROBE_TMP="$(mktemp -d "$TARGET/.sysop-codex-probe.XXXXXX" 2>/dev/null)"; then
    CODEX_PROBE_TMP=""
    CODEX_LINKS_CREATE_DISABLED=1
  else
    local probe_ok=1
    mkdir -p "$CODEX_PROBE_TMP/real" 2>/dev/null || probe_ok=0
    # `touch`, not `: > path`: bash applies redirections left-to-right, so a
    # failing `>` reports to the real stderr before `2>/dev/null` takes effect.
    touch "$CODEX_PROBE_TMP/real/probe" 2>/dev/null || probe_ok=0
    # Bare `ln` on purpose (not /bin/ln): the probe must exercise whatever ln the
    # environment actually resolves, and the test suite substitutes a failing one.
    if (( probe_ok == 1 )); then
      if ! ln -s "./real" "$CODEX_PROBE_TMP/link" 2>/dev/null; then
        probe_ok=0
      elif [[ ! -L "$CODEX_PROBE_TMP/link" ]]; then
        probe_ok=0
      elif [[ "$(readlink "$CODEX_PROBE_TMP/link" 2>/dev/null || true)" != "./real" ]]; then
        probe_ok=0
      elif [[ ! -f "$CODEX_PROBE_TMP/link/probe" ]]; then
        probe_ok=0
      fi
    fi
    rm -rf "$CODEX_PROBE_TMP"
    CODEX_PROBE_TMP=""
    (( probe_ok == 1 )) || CODEX_LINKS_CREATE_DISABLED=1
  fi

  # Warn loudly and keep going. A default-on garnish must not brick an install on
  # a filesystem that can't symlink — but it must never be silent either.
  if [[ "$CODEX_LINKS_CREATE_DISABLED" -eq 1 ]]; then
    hdr "⚠  Codex skill links skipped"
    note "this filesystem rejected a relative directory symlink, so the two"
    note "  .agents/skills/ entries can't be created here."
    note "What is lost: native Codex discovery of the two review skills (and"
    note "  their \$codebase-review / \$security-audit selectors). The rest of the"
    note "  install is unaffected, and Claude Code reads .claude/skills/ directly."
    note "Because .agents/ was NOT created, drop it from the documented install"
    note "  commit line — 'git add .agents/' fails on a path that doesn't exist."
    note "Manual alternative: the AGENTS.md recipe in docs/install-and-update.md § Codex"
  fi
}

install_companion_scripts() {
  hdr "companion scripts"
  local dst="$TARGET/sysop/scripts"
  ensure_dir "$dst"
  local copied=0
  local f
  for f in "$REPO_ROOT/core/companion/scripts"/*; do
    if [[ -f "$f" ]]; then
      # Loop mode: skip lifecycle-coupled scripts (run_checks/ dir ships via the
      # -d branch below; it is not in the exclude list).
      if [[ "$INSTALL_MODE" == "loop" ]] && _loop_excludes "$(basename "$f")" "$LOOP_EXCLUDE_SCRIPTS"; then
        continue
      fi
      copy_file "$f" "$dst/$(basename "$f")"
      copied=$((copied + 1))
    elif [[ -d "$f" ]]; then
      # Sub-package directory (e.g. run_checks/, introduced Phase 49 when
      # run_checks_impl.py was split). Mirror one level deep — companion
      # packages aren't expected to nest further. Add a deeper traversal
      # only when a real shape demands it.
      #
      # Skip Python's compiled-bytecode cache. The Sysop source clone
      # accumulates `__pycache__/` from local pytest runs; before the
      # Phase 49 directory-recursion, the file-only filter skipped these
      # silently. Preserve that behavior to keep .pyc files out of the
      # consumer's tree and out of the lock's `managed_paths`.
      local subdir_name
      subdir_name="$(basename "$f")"
      [[ "$subdir_name" == "__pycache__" ]] && continue
      # Loop mode: filter lifecycle sub-packages too. Today only run_checks/
      # exists (kept — not in the exclude list); this guards a future lifecycle
      # subdir from leaking, since the drift test only buckets file-level scripts.
      if [[ "$INSTALL_MODE" == "loop" ]] && _loop_excludes "$subdir_name" "$LOOP_EXCLUDE_SCRIPTS"; then
        continue
      fi
      ensure_dir "$dst/$subdir_name"
      local sub
      for sub in "$f"/*; do
        [[ -f "$sub" ]] || continue
        copy_file "$sub" "$dst/$subdir_name/$(basename "$sub")"
        copied=$((copied + 1))
      done
    fi
  done

  # Per-pack scripts (e.g., packs/python/companion/scripts/shared_cli.py).
  local pack
  for pack in "${SELECTED_PACKS[@]}"; do
    local pack_scripts="$REPO_ROOT/packs/$pack/companion/scripts"
    if [[ -d "$pack_scripts" ]]; then
      for f in "$pack_scripts"/*; do
        [[ -f "$f" ]] || continue
        copy_file "$f" "$dst/$(basename "$f")"
        copied=$((copied + 1))
      done
    fi
  done
  record "scripts: $copied file(s) copied to sysop/scripts/"
}

install_git_hooks() {
  hdr "git hooks (templates)"
  local dst="$TARGET/sysop/scripts/hooks"
  ensure_dir "$dst"
  local copied=0
  local f
  for f in "$REPO_ROOT/core/companion/git-hooks"/*; do
    [[ -f "$f" ]] || continue
    copy_file "$f" "$dst/$(basename "$f")"
    copied=$((copied + 1))
  done
  if [[ "$ARM_HOOKS" -eq 1 ]] && [[ "$UPDATE_MODE" -eq 0 ]]; then
    record "git hooks: $copied template(s) copied to sysop/scripts/hooks/ (will be armed at end of install)"
  else
    record "git hooks: $copied template(s) copied to sysop/scripts/hooks/ (use sysop/scripts/install_hooks.sh to arm)"
  fi
}

install_ci_template() {
  hdr "CI template"
  local dst="$TARGET/sysop/scripts/ci"
  ensure_dir "$dst"
  local copied=0
  local f
  # Unarmed reference file(s) — the `.example` suffix keeps GitHub from running
  # it. The consumer copies it into .github/workflows/ and marks it a required
  # check (WORKFLOW.md § Merge policy). Shipped like the git-hook templates:
  # delivered to the consumer's tree, but not activated. The consumer's live
  # copy lives in .github/workflows/ (fully unmanaged); this .example is a pure
  # upstream reference, so it refreshes on --update by design (unlike the
  # preserve-consumer-edits scope that covers sysop/scripts/ + sysop/scripts/hooks/).
  for f in "$REPO_ROOT/core/companion/ci"/*; do
    [[ -f "$f" ]] || continue
    copy_file "$f" "$dst/$(basename "$f")"
    copied=$((copied + 1))
  done
  # Loop mode ships no WORKFLOW.md — point at the loop enforcement story instead.
  local _ci_ref="see WORKFLOW.md § Merge policy"
  [[ "$INSTALL_MODE" == "loop" ]] && _ci_ref="run_checks in the CI job is your merge gate"
  record "CI template: $copied file(s) copied to sysop/scripts/ci/ (unarmed — copy to .github/workflows/ to enable; $_ci_ref)"
}

# Absolute path to $TARGET's git hooks dir, worktree-safe. `git -C "$TARGET"
# rev-parse --git-path hooks` returns a path *relative to $TARGET* (git's cwd
# under -C); used from install.sh's own CWD it armed hooks into the wrong
# directory — silently, on the documented `bash sysop/install.sh <target>`
# invocation where CWD is the clone's parent, not the target. Anchor any
# relative result to $TARGET (already-absolute worktree results pass through).
resolve_hook_dst() {
  local p
  p="$(git -C "$TARGET" rev-parse --git-path hooks 2>/dev/null)" || return 1
  case "$p" in
    /*) printf '%s\n' "$p" ;;
    *)  printf '%s\n' "$TARGET/$p" ;;
  esac
}

arm_git_hooks() {
  [[ "$ARM_HOOKS" -eq 1 ]] || return 0
  # Phase 15 / BeanRider ISSUE-0007: --update must NOT auto-arm. The install
  # pipeline has just overwritten sysop/scripts/hooks/* with upstream content; arming
  # now would silently swap the consumer's previously-armed (possibly custom)
  # hook body for the upstream skeleton during the reconcile window. The
  # consumer reconciles sysop/scripts/hooks/* via git first, then re-arms explicitly
  # via sysop/scripts/install_hooks.sh. The post-install armed-hook divergence check
  # below (check_armed_hooks_divergence) surfaces any residual mismatch so the
  # re-arm need is loud, not silent.
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    hdr "arm git hooks"
    note "skipped in --update mode (ISSUE-0007): reconcile sysop/scripts/hooks/ first, then run sysop/scripts/install_hooks.sh"
    record "git hooks: auto-arm skipped (--update mode); use sysop/scripts/install_hooks.sh after reconciling sysop/scripts/hooks/"
    return 0
  fi
  hdr "arm git hooks"
  # Resolve the hook destination via git so this works in worktrees too.
  local hook_dst
  if ! hook_dst="$(resolve_hook_dst)"; then
    note "skipping: could not resolve .git/hooks (is $TARGET a git repo?)"
    return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    note "would arm hooks → $(rel "$hook_dst")"
    record "git hooks: armed (skipped in dry-run)"
    return 0
  fi
  mkdir -p "$hook_dst"
  local armed=0
  local f
  for f in "$TARGET/sysop/scripts/hooks"/*; do
    [[ -f "$f" ]] || continue
    local base; base="$(basename "$f")"
    cp "$f" "$hook_dst/$base"
    chmod +x "$hook_dst/$base"
    note "armed: $base"
    armed=$((armed + 1))
  done
  record "git hooks: $armed armed into $hook_dst/"
}

# Phase 15 / BeanRider ISSUE-0007 safety net: after the pipeline + (in --update
# mode) the consumer's reconcile window, compare every sysop/scripts/hooks/<base>
# against .git/hooks/<base>. Differences mean the armed hook body is stale —
# either because --update intentionally skipped auto-arm (so the consumer must
# re-arm after reconciling), or because someone hand-edited .git/hooks/ out of
# band. Read-only signal; never modifies hooks. Skipped silently in dry-run.
check_armed_hooks_divergence() {
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  local hooks_src="$TARGET/sysop/scripts/hooks"
  [[ -d "$hooks_src" ]] || return 0
  local hook_dst
  hook_dst="$(resolve_hook_dst)" || return 0
  [[ -d "$hook_dst" ]] || return 0
  local -a missing=() diverged=()
  local f base
  for f in "$hooks_src"/*; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"
    if [[ ! -f "$hook_dst/$base" ]]; then
      missing+=("$base")
    elif ! cmp -s "$f" "$hook_dst/$base"; then
      diverged+=("$base")
    fi
  done
  (( ${#missing[@]} + ${#diverged[@]} == 0 )) && return 0

  hdr "armed-hook divergence (ISSUE-0007 safety check)"
  local b
  if (( ${#diverged[@]} > 0 )); then
    say "  ⚠ sysop/scripts/hooks/<base> differs from $(rel "$hook_dst")/<base>:"
    for b in "${diverged[@]}"; do
      say "      - $b"
    done
  fi
  if (( ${#missing[@]} > 0 )); then
    say "  ⚠ sysop/scripts/hooks/<base> present but not armed in $(rel "$hook_dst")/:"
    for b in "${missing[@]}"; do
      say "      - $b"
    done
  fi
  say ""
  say "  Why this matters: .git/hooks/ is not tracked by git, so a stale armed"
  say "  body fires (or doesn't) on the next commit with no diff to inspect."
  say ""
  say "  To re-arm after reconciling sysop/scripts/hooks/: bash $(rel "$TARGET")/sysop/scripts/install_hooks.sh"
}

install_convention_map() {
  hdr "convention_map.md"
  local -a srcs=("$REPO_ROOT/core/companion/convention_map.md")
  local pack
  for pack in "${SELECTED_PACKS[@]}"; do
    local f="$REPO_ROOT/packs/$pack/companion/convention_map.md"
    [[ -f "$f" ]] && srcs+=("$f")
  done
  concat_files "$TARGET/.claude/convention_map.md" 0 "${srcs[@]}"
  record "convention_map.md: core + ${#SELECTED_PACKS[@]} pack file(s) merged"
}

install_security_map() {
  hdr "security_map.md"
  local -a srcs=("$REPO_ROOT/core/companion/security_map.md")
  local pack
  for pack in "${SELECTED_PACKS[@]}"; do
    local f="$REPO_ROOT/packs/$pack/companion/security_map.md"
    [[ -f "$f" ]] && srcs+=("$f")
  done
  concat_files "$TARGET/.claude/security_map.md" 0 "${srcs[@]}"
  record "security_map.md: core + ${#SELECTED_PACKS[@]} pack file(s) merged"
}

install_checks_yml() {
  hdr "checks.yml"
  local -a srcs=("$REPO_ROOT/core/companion/checks.yml.fragment")
  local pack
  for pack in "${SELECTED_PACKS[@]}"; do
    local f="$REPO_ROOT/packs/$pack/companion/checks.yml.fragment"
    [[ -f "$f" ]] && srcs+=("$f")
  done
  concat_files "$TARGET/.claude/checks.yml" 1 "${srcs[@]}"
  record "checks.yml: core + ${#SELECTED_PACKS[@]} pack fragment(s) merged"
}

# Phase 123: build a loop-mode-filtered settings.json template. Sets the global
# LOOP_SETTINGS_TMP to the temp path (cleaned on EXIT). Call DIRECTLY, not in a
# command substitution, so the assignment survives in the parent shell. Filters
# permissions.allow to the loop subset (LOOP_ONLY_SPEC § "Leg 1 findings") and
# drops the hooks block (both Sysop hooks are lifecycle-only). Non-zero on failure.
_loop_settings_template() {
  local src="$1"
  LOOP_SETTINGS_TMP="$(mktemp "${TMPDIR:-/tmp}/sysop-loop-settings.XXXXXX")" || return 1
  python3 - "$src" "$LOOP_SETTINGS_TMP" <<'PY' || return 1
import json, sys
src, out = sys.argv[1], sys.argv[2]
# Filtering the master template by this keep-set is fail-closed: if a master rule
# string is renamed, loop mode drops it and tests/test_install_loop_mode.py catches it.
LOOP_ALLOW = {
    "Bash(git add review_tasks.md)",
    "Bash(git commit -m docs:*)",
    "Bash(bash sysop/scripts/run_checks.sh)",
    "Bash(bash sysop/scripts/run_checks.sh:*)",
    "Bash(bash sysop/scripts/install_hooks.sh)",
    "Bash(bash sysop/scripts/sysop-update.sh)",
    "Bash(bash sysop/scripts/sysop-update.sh:*)",
    "Bash(python sysop/scripts/archive_review_tasks.py:*)",
    "Bash(python3 sysop/scripts/archive_review_tasks.py:*)",
    "Bash(.venv/bin/python3 sysop/scripts/archive_review_tasks.py:*)",
    "Bash(python3 sysop/scripts/ingest_security_report.py:*)",
    "Bash(.venv/bin/python3 sysop/scripts/ingest_security_report.py:*)",
    "Bash(python3 -c:*)",
    "Bash(python3 -:*)",
    "Bash(gh issue list:*)",
    "Bash(gh issue create:*)",
}
with open(src) as f:
    tmpl = json.load(f)
allow = [r for r in tmpl.get("permissions", {}).get("allow", []) if r in LOOP_ALLOW]
# hooks intentionally omitted (loop mode: both Sysop hooks are lifecycle-only).
with open(out, "w") as f:
    json.dump({"permissions": {"allow": allow}}, f, indent=2)
    f.write("\n")
PY
}

install_permissions() {
  hdr "permissions (.claude/settings.json)"
  local src="$REPO_ROOT/core/companion/.claude/settings.json"
  local dst="$TARGET/.claude/settings.json"
  if [[ ! -f "$src" ]]; then
    note "skipping: template not found at $(rel "$src")"
    return 0
  fi
  ensure_dir "$(dirname "$dst")"

  # Phase 131 (round-4 cold read): say the allow-list's blast radius out loud at
  # install time — both cold readers flagged discovering the `git push` grants
  # only by reading the shipped JSON. Emitted on every path (fresh, merge,
  # dry-run) so no install applies the grant silently.
  if [[ "$INSTALL_MODE" == "loop" ]]; then
    note "allow-list: a small check/read-only subset, no hooks — no push, merge, or rebase grants."
    note "  It is yours to trim: review .claude/settings.json and delete any rule you don't want."
  else
    note "allow-list: pre-authorizes the agent for Sysop's lifecycle git flow WITHOUT further"
    note "  prompts — including 'git push origin' and 'git push --force-with-lease' (the"
    note "  worktree close path). Review .claude/settings.json and delete any rule you don't"
    note "  want; '--mode loop' ships a small check/read-only subset instead."
  fi

  # Loop mode: feed the copy/merge paths below a filtered template (loop
  # allow-subset, no hooks) so the existing logic is reused unchanged.
  if [[ "$INSTALL_MODE" == "loop" ]]; then
    # Under --dry-run, report the plan without building the temp (the write
    # would violate the dry-run contract, and the copy note would render the
    # raw /tmp path).
    if [[ "$DRY_RUN" -eq 1 ]]; then
      note "would write $(rel "$dst") (loop allow-subset: 16 rules, no hooks)"
      record_managed_path "$dst"
      record "permissions: would write $(rel "$dst") (loop allow-subset)"
      return 0
    fi
    # Fail CLOSED: if the filter can't be built, do NOT fall back to the full
    # master — that would over-grant the 57-rule allow-list AND re-add the hooks
    # block referencing scripts loop mode never installs (broken at runtime).
    # Skip settings.json instead (the consumer sees more permission prompts, but
    # no over-grant and no dangling hooks); the loud error keeps it visible.
    if _loop_settings_template "$src"; then
      src="$LOOP_SETTINGS_TMP"
    else
      err "loop settings-filter failed — NOT writing settings.json (refusing to ship full-mode permissions + hooks pointing at absent scripts in loop mode)."
      note "re-run the install, or add a minimal .claude/settings.json by hand."
      return 0
    fi
  fi

  if [[ ! -f "$dst" ]]; then
    do_or_say "copy: $(rel "$src") → $(rel "$dst")" cp "$src" "$dst"
    record_managed_path "$dst"
    record "permissions: wrote $(rel "$dst") (Sysop allow-list)"
    return 0
  fi

  # Existing settings.json present — merge permissions.allow (set-union, preserve
  # the user's existing rules, append Sysop rules not already present) AND
  # merge hooks.<event> entries (Phase 36: presence-keyed by Sysop's hook
  # script filename, so consumer customizations of the same event are preserved).
  note "merge: $(rel "$src") → $(rel "$dst") (existing file)"
  record_managed_path "$dst"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    record "permissions: would merge Sysop allow-list + hooks into $(rel "$dst")"
    return 0
  fi

  python3 - "$src" "$dst" <<'PY'
import json, sys
template_path, target_path = sys.argv[1], sys.argv[2]
with open(template_path) as f:
    template = json.load(f)
with open(target_path) as f:
    existing = json.load(f)

merged = dict(existing)

# --- permissions.allow set-union ---
permissions = dict(existing.get("permissions", {}))
existing_allow = list(permissions.get("allow", []))
template_allow = list(template.get("permissions", {}).get("allow", []))
seen = set(existing_allow)
combined = existing_allow + [r for r in template_allow if r not in seen]
permissions["allow"] = combined
merged["permissions"] = permissions

# --- hooks.<event> merge (Phase 36) ---
# Sysop's hook scripts are identified by filename so this stays robust
# against consumers reordering or wrapping commands. If any sub-hook entry
# under the event already references the Sysop filename, we leave the
# event alone (consumer has it / has customized it). Otherwise we append
# Sysop's template entries that reference one of our filenames.
SYSOP_HOOK_FILENAMES = ("permission_denied_hook.py", "parse_subagent_envelope.py")

def references_sysop(entry):
    for h in entry.get("hooks", []) or []:
        cmd = h.get("command", "") or ""
        if any(name in cmd for name in SYSOP_HOOK_FILENAMES):
            return True
    return False

template_hooks = template.get("hooks", {}) or {}
if template_hooks:
    existing_hooks = dict(existing.get("hooks", {}) or {})
    for event_name, template_entries in template_hooks.items():
        entries = list(existing_hooks.get(event_name, []))
        already_present = any(references_sysop(e) for e in entries)
        if already_present:
            continue
        for tmpl_entry in template_entries:
            if references_sysop(tmpl_entry):
                entries.append(tmpl_entry)
        existing_hooks[event_name] = entries
    merged["hooks"] = existing_hooks

with open(target_path, "w") as f:
    json.dump(merged, f, indent=2)
    f.write("\n")
PY
  record "permissions: merged Sysop allow-list + hooks into $(rel "$dst")"
}

install_served_models() {
  hdr "model roles (.claude/served_models.yml)"
  local src="$REPO_ROOT/core/companion/.claude/served_models.yml"
  local dst="$TARGET/.claude/served_models.yml"
  if [[ ! -f "$src" ]]; then
    note "skipping: template not found at $(rel "$src")"
    return 0
  fi
  # Sysop-owned role->model config (standard overwrite — it is Sysop's source of
  # truth for the default role mapping + served set and must refresh on a sunset;
  # copy_file records it as managed so the Phase 8 divergence check warns before
  # any consumer-edited copy is overwritten). Consumer overrides belong in the
  # never-overwritten .claude/served_models.local.yml (Sysop never writes that
  # file, so a consumer's role picks survive every update). Consumed by
  # resolve_skill_models.py (apply) and check_skill_models.py (validate).
  copy_file "$src" "$dst"
  record "model-roles: wrote $(rel "$dst") (role->model config; override in served_models.local.yml)"
}

# Phase 69: resolve the skills tree's role markers to concrete models. Skills
# ship pinning a ROLE (reasoning/mechanical/quick); this rewrites each marked
# `model:` value to whatever served_models.yml (+ the consumer's never-overwritten
# served_models.local.yml) maps that role to. Runs AFTER install_skills (tree
# present), install_companion_scripts (resolver present), and install_served_models
# (config present). Under the default mapping it is a byte-for-byte no-op, so a
# default install does not diverge from source; it does real work only when a
# consumer remaps a role. A resolver error writes nothing (skills keep their
# shipped defaults), so this can only degrade gracefully — never half-apply.
resolve_skill_models() {
  hdr "resolve model roles"
  local script="$TARGET/sysop/scripts/resolve_skill_models.py"
  local skills="$TARGET/.claude/skills"
  local config="$TARGET/.claude/served_models.yml"
  local localcfg="$TARGET/.claude/served_models.local.yml"
  if [[ ! -f "$script" || ! -d "$skills" || ! -f "$config" ]]; then
    note "skipping: resolver, skills tree, or served_models.yml not present"
    return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    note "would resolve skill model-role markers via served_models.yml (no-op under default mapping)"
    return 0
  fi
  local _py
  if ! _py="$(pick_python_with_yaml)"; then
    if [[ -f "$localcfg" ]]; then
      note "⚠ no python3 with PyYAML — your served_models.local.yml override will NOT be applied (skills keep default models). Install PyYAML and re-run."
    else
      note "skipping: no python3 with PyYAML available to resolve model roles (default mapping is a no-op anyway)"
    fi
    return 0
  fi
  local _out
  if _out="$("$_py" "$script" --root "$skills" --config "$config" --local "$localcfg" --apply --quiet 2>&1)"; then
    record "model-roles: $(printf '%s' "$_out" | tail -1)"
  else
    note "model-role resolution reported an issue (skills keep their default models):"
    printf '%s\n' "$_out" | sed 's/^/    /'
    record "model-roles: resolution skipped (see warning above)"
  fi
}

install_semgrep() {
  hdr "semgrep rules + fixtures"
  local dst="$TARGET/.claude/semgrep"
  ensure_dir "$dst"

  # Core authoring README.
  local readme="$REPO_ROOT/core/companion/semgrep/README.md"
  if [[ -f "$readme" ]]; then
    copy_file "$readme" "$dst/README.md"
  fi

  local rules=0 fixtures=0
  local pack
  for pack in "${SELECTED_PACKS[@]}"; do
    local pack_sg="$REPO_ROOT/packs/$pack/companion/semgrep"
    [[ -d "$pack_sg" ]] || continue
    local f
    for f in "$pack_sg"/*.yaml; do
      [[ -f "$f" ]] || continue
      copy_file "$f" "$dst/$(basename "$f")"
      rules=$((rules + 1))
    done
    if [[ -d "$pack_sg/fixtures" ]]; then
      ensure_dir "$dst/fixtures"
      for f in "$pack_sg/fixtures"/*; do
        [[ -f "$f" ]] || continue
        copy_file "$f" "$dst/fixtures/$(basename "$f")"
        fixtures=$((fixtures + 1))
      done
    fi
  done
  record "semgrep: $rules rule(s), $fixtures fixture(s) copied to .claude/semgrep/"
}

# ─── friction log (Phase 13) ──────────────────────────────────
# Seed <target>/sysop/SYSOP_ISSUES.md on fresh install only. The file lives
# under the sysop/ vendor dir (Phase 128; it's a log *about the tool*) and is
# intentionally NOT recorded in MANAGED_PATHS — that non-management is the
# property that protects it from --update overwriting (Phase 8's overwrite gap
# can't touch what isn't tracked). If the file already exists, skip silently —
# consumers who hand-rolled one before Phase 13 shipped (BeanRider did) keep
# their version intact even on re-install.
seed_friction_log() {
  hdr "friction log"
  local dst="$TARGET/sysop/SYSOP_ISSUES.md"
  if [[ -f "$dst" ]]; then
    note "skip: $(rel "$dst") (already exists — left untouched)"
    return 0
  fi

  # Sanitize basename for the <consumer> heading. Strip trailing slashes;
  # if the result is empty, ".", or "..", fall back to the literal placeholder.
  local consumer
  consumer="$(basename "${TARGET%/}")"
  if [[ -z "$consumer" ]] || [[ "$consumer" == "." ]] || [[ "$consumer" == ".." ]]; then
    consumer="<consumer>"
  fi

  note "seed: $(rel "$dst") (project-owned; not in managed_paths)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi

  cat > "$dst" <<EOF
# Sysop Issues — ${consumer}

> Sysop friction logged from \`${consumer}\`. This file lives at repo
> root by design — Sysop's \`install.sh --update\` never touches it.
> Project-owned after this initial seed; you can restructure freely.
>
> **What belongs here:** symptoms in sysop-shipped files, skills,
> install behavior, or workflow logic. NOT project-domain bugs (your
> parsers, your UI, your data model) — those belong in your project's
> own roadmap.
>
> **Positive signal counts too.** Something Sysop got notably right — a
> guardrail that fired correctly, a clear error, a step that just worked — is
> worth capturing so a later change doesn't quietly "fix" it. Log it as a
> \`[good]\` entry (positive-signal template below); \`/report-issues\` can
> batch these into one upstream note instead of filing each as a bug.
>
> Append entries newest-first. Numbering is local (\`ISSUE-NNNN\`); when
> referencing across repos, prefix with the project name
> (e.g., \`${consumer}#ISSUE-0001\`).

## Template

\`\`\`markdown
## ISSUE-NNNN — short title (YYYY-MM-DD)

**Status:** Open / Prompt-ready / Filed to Sysop / Fixed in ${consumer} <date> / Fixed in Sysop vX

### What happened
Repro steps + observed behavior. Quote skill names and step numbers from
the skill spec when the failure is mid-workflow. Include exact error text
where the agent can copy it.

### Diagnosis
Why this is a Sysop problem and not a project problem. Reference the
specific skill file, installer behavior, or template at fault by path.

### Proposed fix
Concrete change to Sysop. File paths, snippets, scope. If multiple
options exist, name each and pick a recommended one with reasoning.

### Verification
How Sysop's agent can confirm the fix works — usually a repro on a
fresh test repo with the broken state restored.

### Workaround in ${consumer} (if any)
What was done locally to unblock. Document so the workaround can be
reverted once Sysop ships the fix.
\`\`\`

## Template — positive signal (\`[good]\`)

\`\`\`markdown
## GOOD-NNNN — short title (YYYY-MM-DD)  [good]

**Status:** Good — keep

### What worked
What Sysop did right and why it mattered. Name the skill / installer step /
guardrail so the maintainer knows what to protect from a future change.
\`\`\`

---

<!-- Entries below. Newest first. -->
EOF
}

# Phase 123 (loop mode): emit one of the three <project>/CLAUDE.md scope sections
# the audit skills consume. Shared by the create-fresh and append-if-absent
# paths of seed_claude_md_stub so there is one source for the section bodies.
_claude_md_section() {  # $1 = scope | exclusions | security
  case "$1" in
    scope)
      cat <<'EOF'

## Scope mapping

<!-- Seeded by Sysop — fill in globs, then delete this comment.
     Map each area of the codebase to a glob so a review agent gets the right
     convention bullets. Example:
       - API / server code → `src/api/**/*.py`
       - UI components      → `src/components/**/*.tsx`
     Until you fill this in, /codebase-review has no scope to map. -->
EOF
      ;;
    exclusions)
      cat <<'EOF'

## Map coverage exclusions

<!-- Seeded by Sysop — globs the review/audit sweep should NOT flag
     as unmapped (generated code, vendored dirs, fixtures). Give each entry a
     one-line reason: Step 2a-0 checks that every top-level entry holding
     tracked code is either covered by a map section or excluded here WITH a
     reason, and reports the ones that aren't. Example:
       - `**/migrations/**` — generated by the ORM, reviewed at the model layer
       - `**/*.generated.ts` — codegen output, edit the schema instead -->
EOF
      ;;
    security)
      cat <<'EOF'

## Security-critical always-include files

<!-- Seeded by Sysop — files /security-audit must always review even
     if unchanged (auth, secrets handling, permission checks). Example:
       - `src/auth/**`
       - `src/**/permissions.py` -->
EOF
      ;;
  esac
}

# Phase 123 (loop mode), both modes since Phase 131 (round-4 cold read: the
# full-mode quickstart's `git add ... CLAUDE.md` hard-failed on bare repos, and
# the audit skills consume the same sections in full mode — /intake + the §6.1
# bootstrap append their own sections later and compose with this):
# ensure <project>/CLAUDE.md carries the three sections the
# audit skills consume — "Scope mapping" (/codebase-review + /security-audit
# Step 1), "Map coverage exclusions" (Step 2a), "Security-critical always-include
# files" (/security-audit Step 1). Two paths: create-fresh with all three when absent; otherwise
# append ONLY the sections whose header is missing (the ensure_runtime_gitignore
# append-only contract — never rewrite consumer-authored content). Header match is
# anchored so a mention in prose doesn't count as present. Fresh-install only
# (main gates on UPDATE_MODE==0). Not a managed path (project-owned).
seed_claude_md_stub() {
  hdr "CLAUDE.md scope sections"
  local dst="$TARGET/CLAUDE.md"

  if [[ ! -f "$dst" ]]; then
    note "seed: $(rel "$dst") (scope sections for the audit skills; project-owned)"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      return 0
    fi
    {
      cat <<'EOF'
# CLAUDE.md

> Seeded by Sysop. The three sections below tell the review skills
> (`/codebase-review`, `/security-audit`) what to review and what to skip.
> Fill in the globs for your repo, then delete these notes. Everything else in
> this file is yours.
EOF
      _claude_md_section scope
      _claude_md_section exclusions
      _claude_md_section security
    } > "$dst"
    return 0
  fi

  # Existing CLAUDE.md — append only the absent sections, never rewriting.
  # Known v1 edges (documented, not handled — the preconditions are rare and a
  # fence-aware markdown parser in bash is disproportionate): a `## Scope mapping`
  # line at column 0 *inside a ``` code fence* reads as present (section skipped);
  # a header with trailing text (`## Scope mapping (draft)`) reads as absent (a
  # second stub is appended). If either bites, the consumer edits CLAUDE.md by
  # hand — the sections are documented in docs/install-and-update.md § Install modes.
  local added=0 key hdr
  for key in scope exclusions security; do
    case "$key" in
      scope)      hdr="## Scope mapping" ;;
      exclusions) hdr="## Map coverage exclusions" ;;
      security)   hdr="## Security-critical always-include files" ;;
    esac
    if grep -qE "^${hdr}[[:space:]]*$" "$dst"; then
      continue
    fi
    [[ "$DRY_RUN" -eq 0 ]] && _claude_md_section "$key" >> "$dst"
    added=$((added + 1))
  done
  if (( added > 0 )); then
    note "append: $added absent scope section(s) → $(rel "$dst") (audit-skill sections; existing content untouched)"
  else
    note "skip: $(rel "$dst") already carries the three scope sections"
  fi
}

# Scaffold tasks/ hybrid task system (Phase 16). Two separate write modes:
#   1. tasks/schema.md, tasks/README.md — managed paths (Sysop owns the
#      shape). Copy on every install/update; `--update` reconcile path
#      handles consumer edits via Phase 8's divergence check.
#   2. tasks/index.yml — consumer-owned, seed-once. Same skip-if-exists
#      contract as seed_friction_log: NOT in managed_paths, never
#      overwritten on `--update`. Consumers fill in phases + tasks; the
#      `--update` overwrite gap can't touch what isn't tracked.
#   3. tasks/{open,deferred,archive}/ — directory shells with .gitkeep so
#      the layout exists from day one. The .gitkeep files are managed
#      paths but contain no semantic content; they're safe to overwrite.
# Ensure the consumer .gitignore ignores Sysop's runtime-artifact home
# (Phase 99, tester round; consolidated Phase 133). Runtime dirs hold transient
# orchestration state that a stray `git add -A` would otherwise commit into
# project history. As of Phase 133 all four live under ONE vendor-namespaced
# home, so a single ignore entry covers them:
#   sysop/runtime/subagent-envelopes/  in-flight SubagentStop envelope JSON (Phase 37)
#   sysop/runtime/auto-build/          parked-task plan + adversarial-verdict archive (Phase 65a)
#   sysop/runtime/pending-docs/        deferred documentation drafts (/document-work Step 3)
#   sysop/runtime/locks/               in-progress task locks (claim_task.sh; Phase 32)
# The guarantee must hold: /review-close Step 2a derives its `dirty` verdict
# from `git status --porcelain`, so an un-ignored lock or pending-doc makes a
# clean branch read dirty → auto-SKIP → the close silently refuses (Phase 99.1
# / tester issue #10). A drift-guard test
# (tests/test_install_runtime_gitignore.py) greps the skills for every dir they
# assert is gitignored and fails if this entry doesn't cover it.
# Loop mode uses the same entry: the audit skills' Step 8 promotion-deferral
# writes sysop/runtime/pending-docs/ (leg-5 dogfood finding), and the single
# sysop/runtime/ line adds no dead per-dir entries to the enumerated footprint.
# Idempotent + update-safe: append-only, one full-line entry each, skip any
# already present. .gitignore is CONSUMER-OWNED, so we NEVER rewrite existing
# entries — only append missing ones (a pre-133 install's four old dot-dir
# entries are left in place: dead but harmless, and removing consumer-file
# lines would break the append-only contract). Runs on fresh install AND
# --update, so a .gitignore that pre-dates the install (or was hand-edited
# later) still gets the guarantee.
ensure_runtime_gitignore() {
  hdr "runtime-artifact gitignore"
  local gi="$TARGET/.gitignore"
  local -a want=("sysop/runtime/")
  local -a missing=()
  local entry
  for entry in "${want[@]}"; do
    if [[ -f "$gi" ]] && grep -qxF "$entry" "$gi" 2>/dev/null; then
      continue
    fi
    missing+=("$entry")
  done
  if (( ${#missing[@]} == 0 )); then
    note "already ignored: ${want[*]}"
    return 0
  fi
  note "gitignore: appending ${#missing[@]} Sysop runtime dir(s) → $(rel "$gi")"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  {
    # If the file exists and its last byte is not a newline, start fresh so we
    # never glue our first entry onto the consumer's last line.
    if [[ -f "$gi" && -s "$gi" && -n "$(tail -c1 "$gi")" ]]; then
      printf '\n'
    fi
    # Add the section header only the first time (no prior Sysop block).
    if [[ ! -f "$gi" ]] || ! grep -qF "# Sysop runtime artifacts" "$gi" 2>/dev/null; then
      printf '# Sysop runtime artifacts (transient orchestration state)\n'
    fi
    for entry in "${missing[@]}"; do
      printf '%s\n' "$entry"
    done
  } >> "$gi"
}

install_tasks_scaffold() {
  hdr "tasks/ scaffold (Phase 16)"
  local tasks_dst="$TARGET/tasks"
  ensure_dir "$tasks_dst"
  ensure_dir "$tasks_dst/open"
  ensure_dir "$tasks_dst/deferred"
  ensure_dir "$tasks_dst/archive"

  # Schema docs (managed).
  copy_file "$REPO_ROOT/core/companion/tasks/schema.md" "$tasks_dst/schema.md"
  copy_file "$REPO_ROOT/core/companion/tasks/README.md" "$tasks_dst/README.md"

  # .gitkeep for each subdir (managed; tracks the directory shape).
  local sub
  for sub in open deferred archive; do
    if [[ "$DRY_RUN" -eq 0 ]] && [[ ! -f "$tasks_dst/$sub/.gitkeep" ]]; then
      : > "$tasks_dst/$sub/.gitkeep"
    fi
    record_managed_path "$tasks_dst/$sub/.gitkeep"
  done

  # index.yml — consumer-owned; skip if it already exists.
  local idx="$tasks_dst/index.yml"
  if [[ -f "$idx" ]]; then
    note "skip: $(rel "$idx") (already exists — left untouched)"
    record "tasks/: schema.md + README.md (managed); index.yml left as-is"
    return 0
  fi

  note "seed: $(rel "$idx") (project-owned; not in managed_paths)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    record "tasks/: schema.md + README.md (managed); index.yml seeded (skipped in dry-run)"
    return 0
  fi

  cat > "$idx" <<'EOF'
schema_version: 1
# schema_version: 1 keeps `blast_radius:` optional. Bump to 2 once every
# open/in_progress task declares a blast_radius value; the validator will
# then enforce its presence. See tasks/schema.md § Versioning.

# Phases — exactly one must carry `current_focus: true`.
# /next-task anchors on the current-focus phase.
phases:
  - number: 1
    title: "Initial phase"
    status: in_progress
    current_focus: true
    sprint_note: |
      Replace this with your first sprint's narrative.
      Multi-line block scalar; supports markdown.

# Tasks — one entry per discrete piece of work.
# Schema reference: tasks/schema.md
# Validator:       sysop/scripts/validate_tasks.py
#
# Example task entry (copy + populate; remove the leading `# `):
# tasks:
#   - id: FEAT-EXAMPLE
#     title: "Short human-readable title"
#     phase: 1
#     status: open                       # open | in_progress | done | deferred
#     effort: Medium                     # Low | Medium | High — how much work
#     blast_radius: single-module        # single-file | single-module | cross-module | architectural — surface area
#     user_action: false                 # true = requires console / credentials / domain reg
#     manual_smoke: false                # true = /review-close Step 3c halts for human smoke (Phase 35)
#     depends_on: []                     # other task IDs this blocks on
#     surfaced_by: []                    # IDs that filed this task (e.g., review findings)
#     body: tasks/open/FEAT-EXAMPLE.md   # required for open/in_progress/deferred
tasks: []
EOF
  record "tasks/: schema.md + README.md (managed); index.yml seeded; open/, deferred/, archive/ created"
}

# Run the install_* sequence. Populates MANAGED_PATHS as a side effect.
run_install_pipeline() {
  # Loop mode drops the two lifecycle-only steps: root workflow docs and the
  # tasks/ queue scaffold (LOOP_ONLY_SPEC § The bundle). Everything else ships.
  [[ "$INSTALL_MODE" == "loop" ]] || install_workflow_docs
  install_skills
  # Phase 142: strictly after install_skills — the link targets must exist before
  # the read-SKILL.md-through-the-link verification can pass. Both modes.
  install_codex_links
  install_companion_scripts
  install_git_hooks
  install_ci_template
  install_convention_map
  install_security_map
  install_checks_yml
  install_semgrep
  [[ "$INSTALL_MODE" == "loop" ]] || install_tasks_scaffold
  # ensure_runtime_gitignore ignores the consolidated runtime home
  # (sysop/runtime/ — subagent-envelopes, auto-build, pending-docs, locks;
  # Phase 133). One entry serves both modes: loop mode's audit skills write
  # sysop/runtime/pending-docs/ via the promotion-deferral (leg-5 dogfood
  # finding), and the single line adds no dead per-dir entries.
  ensure_runtime_gitignore
  install_permissions
  install_served_models
  resolve_skill_models
  arm_git_hooks
}

# ─── --check mode ─────────────────────────────────────────────
cmd_check() {
  hdr "Sysop --check"
  if [[ -z "$CHECK_SOURCE" ]]; then
    err "--check requires --source <path-to-sysop-clone>."
    exit 2
  fi
  CHECK_SOURCE="$(canonicalize_target "$CHECK_SOURCE")"
  if ! git -C "$CHECK_SOURCE" rev-parse HEAD >/dev/null 2>&1; then
    err "--source is not a git repository: $CHECK_SOURCE"
    exit 2
  fi

  local lock_path="$TARGET/$LOCK_REL"
  if [[ ! -f "$lock_path" ]]; then
    err "No lock file at $(rel "$lock_path"). Run with --adopt first."
    exit 1
  fi

  local installed_commit upstream_head
  installed_commit="$(lock_field sysop_commit)"
  upstream_head="$(git -C "$CHECK_SOURCE" rev-parse HEAD)"
  if [[ -z "$installed_commit" ]] || [[ "$installed_commit" == "unknown" ]]; then
    err "Lock has no sysop_commit anchor (was the lock written from a non-git source?)."
    err "Re-run --adopt from a Sysop git clone."
    exit 1
  fi

  say "  target:           $TARGET"
  say "  installed commit: ${installed_commit:0:12}"
  say "  upstream HEAD:    ${upstream_head:0:12}  ($(rel "$CHECK_SOURCE"))"

  if [[ "$installed_commit" == "$upstream_head" ]]; then
    say ""
    say "Up to date — installed commit matches upstream HEAD."
    return 0
  fi

  # Ensure the installed commit is reachable in --source.
  if ! git -C "$CHECK_SOURCE" cat-file -e "${installed_commit}^{commit}" 2>/dev/null; then
    err "Installed commit ${installed_commit:0:12} not found in $(rel "$CHECK_SOURCE")."
    err "Either --source is stale (try git fetch) or the install was anchored to a different repo."
    exit 1
  fi

  # Scope the diff to upstream paths that produce installable content.
  # Consumer-side managed_paths (e.g., `.claude/skills/X`) don't exist in the
  # Sysop source tree; the install pipeline reads from `core/` and
  # `packs/<pack>/`, so we scope the log to those upstream roots instead.
  local -a upstream_scope=("core/")
  local pack_line
  while IFS= read -r pack_line; do
    [[ -z "$pack_line" ]] && continue
    upstream_scope+=("packs/$pack_line/")
  done < <(lock_field packs)

  hdr "commits affecting managed paths"
  local total relevant
  total="$(git -C "$CHECK_SOURCE" rev-list --count "${installed_commit}..${upstream_head}" 2>/dev/null || echo "?")"
  relevant="$(git -C "$CHECK_SOURCE" rev-list --count "${installed_commit}..${upstream_head}" -- "${upstream_scope[@]}" 2>/dev/null || echo "?")"
  say "  $total upstream commit(s) total; $relevant touch installable content"

  say ""
  git -C "$CHECK_SOURCE" log --oneline "${installed_commit}..${upstream_head}" -- "${upstream_scope[@]}" \
    | sed 's/^/  /' || true

  say ""
  say "To apply: bash install.sh $TARGET --update"
}

# ─── --adopt mode ─────────────────────────────────────────────
cmd_adopt() {
  hdr "Sysop --adopt"
  # Early-validate --anchor so the error fires before the dry-run pipeline.
  if [[ -n "$ANCHOR_OVERRIDE" ]]; then
    local resolved_anchor; resolved_anchor="$(get_sysop_commit)"
    note "anchoring lock at ${resolved_anchor:0:12} (override via --anchor=$ANCHOR_OVERRIDE)"
  fi
  local lock_path="$TARGET/$LOCK_REL"
  local _readopt=0
  if [[ -f "$lock_path" ]]; then
    # ISSUE-0047 recovery: a lock whose sysop_commit anchor is missing
    # (empty/"unknown") is malformed — --update fails closed on it (git source),
    # and its only sanctioned rebuild is here. Adopt's job is to (re)establish
    # tracking; a lock with no valid anchor has none, so re-adopt in place rather
    # than dead-ending the user in a --update↔--adopt loop. A lock with a VALID
    # anchor still routes to --update (unchanged).
    local _existing_anchor; _existing_anchor="$(lock_field sysop_commit)"
    if [[ -n "$_existing_anchor" ]] && [[ "$_existing_anchor" != "unknown" ]]; then
      err "Lock already exists at $(rel "$lock_path"). Use --update for upgrades."
      exit 1
    fi
    _readopt=1
    note "re-adopting: existing lock has no valid sysop_commit anchor — rebuilding it in place"
  fi

  # --adopt only backfills a lock for an install that predates the lock
  # mechanism; such a target already has a populated .claude/ from that install.
  # Adopting a target with no .claude/ has nothing to adopt — proceeding would
  # mint a lock referencing managed paths that were never actually written (the
  # managed_paths below come from a DRY_RUN pipeline). Fail with a pointer
  # instead of the raw FileNotFoundError the lock write would otherwise raise.
  if [[ ! -d "$TARGET/.claude" ]]; then
    err "No existing Sysop install found at $TARGET (.claude/ is absent)."
    say "  --adopt backfills the lock for an install that predates the lock"
    say "  mechanism. For a new target, run a normal install first:"
    say "    bash install.sh $TARGET --packs <packs>"
    exit 1
  fi

  # Packs (from --packs or interactive). PACKS_PROVIDED gates the picker so an
  # explicit `--packs ''`/`--packs auto` records core-only without prompting.
  local packs_input="$PACKS_ARG"
  if [[ -z "$packs_input" ]] && [[ "$PACKS_PROVIDED" -eq 0 ]]; then
    if [[ "$_readopt" -eq 1 ]]; then
      # Re-adopt: recover the pack selection from the existing lock so the
      # consumer isn't re-prompted for what they already chose.
      local _pack_line
      while IFS= read -r _pack_line; do
        [[ -z "$_pack_line" ]] && continue
        if [[ -z "$packs_input" ]]; then packs_input="$_pack_line"
        else packs_input="$packs_input,$_pack_line"; fi
      done < <(lock_field packs)
      note "packs recovered from existing lock: ${packs_input:-(core only)}"
    else
      say ""
      say "Which packs were originally installed? (will be recorded in the lock for"
      say "future --update runs to know what fragments to re-merge)"
      packs_input="$(prompt_packs)"
    fi
  fi
  resolve_selected_packs "$packs_input"

  # Compute managed_paths by running the pipeline under DRY_RUN (writes nothing,
  # but copy_file/concat_files still call record_managed_path).
  hdr "computing managed_paths"
  local saved_dry="$DRY_RUN"
  DRY_RUN=1
  MANAGED_PATHS=()
  run_install_pipeline
  DRY_RUN="$saved_dry"

  hdr "plan"
  say "  target:  $TARGET"
  if (( ${#SELECTED_PACKS[@]} > 0 )); then
    say "  packs:   ${SELECTED_PACKS[*]}"
  else
    say "  packs:   (core only)"
  fi
  say "  paths:   ${#MANAGED_PATHS[@]} managed path(s) recorded"
  say "  action:  write $(rel "$lock_path") + commit"

  if [[ "$DRY_RUN" -eq 0 ]]; then
    if ! confirm "Proceed?"; then
      say "Aborted."
      exit 0
    fi
  fi

  local now; now="$(iso_now)"
  write_lock_file "$now" "$now"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    say ""
    say "Dry-run complete. Re-run without --dry-run to apply."
    return 0
  fi

  # Commit the lock so future --update runs have a clean anchor.
  local commit; commit="$(get_sysop_commit)"
  git -C "$TARGET" add -- "$LOCK_REL"
  git -C "$TARGET" commit \
    --no-verify \
    -m "sysop: adopt update tracking (lock anchored at ${commit:0:12})" \
    -- "$LOCK_REL" >/dev/null

  say ""
  say "Done. Lock committed: $(rel "$lock_path")"
  say "Future upgrades: bash install.sh $TARGET --update"
}

# Resolve PACKS_ARG-style csv into SELECTED_PACKS, filtering placeholder packs.
resolve_selected_packs() {
  local packs_input="$1"
  if [[ -z "$packs_input" ]]; then
    SELECTED_PACKS=()
    say "  → No packs selected; core only."
    return 0
  fi
  local resolved
  if ! resolved="$(resolve_packs "$packs_input")"; then
    exit 1
  fi
  SELECTED_PACKS=()
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] && SELECTED_PACKS+=("$line")
  done <<< "$resolved"

  local -a effective=()
  local p
  for p in "${SELECTED_PACKS[@]}"; do
    if pack_has_companion "$p"; then
      effective+=("$p")
    else
      say "  → Skipping pack '$p': no companion content yet (placeholder)."
    fi
  done
  SELECTED_PACKS=("${effective[@]}")
}

# ─── Phase 128: sysop/ namespace migration (§5 algorithm) ─────
# The migration is a delta on the existing --update flow: divergence detection
# still runs on OLD paths, then BOTH the working tree and the reconstructed
# shadow move to the new layout, then the standard pipeline runs layout-blind.
# All functions are idempotent so a crashed run resumes cleanly on re-invocation.

# §5 step 3: run the pipeline under DRY_RUN to get the authoritative NEW managed
# set (captures version-bump additions/removals), then derive the FULL old→new
# move map (every new-set path whose spelling changed) plus NS_MOVE_PENDING (the
# subset with real working-tree work left). Also clears the global state the
# DRY_RUN run dirtied
# (KNOWN_DIRS memoises dir creation even in dry-run; leaving it set would make
# the REAL pipeline skip every mkdir). DIVERGENCE_SHADOW is blanked for the
# probe so copy_file's preservation branch can't fire here.
_ns_precompute_and_derive() {
  local _saved_dry="$DRY_RUN" _saved_shadow="$DIVERGENCE_SHADOW"
  local -a _saved_managed=("${MANAGED_PATHS[@]}")
  # PLAN_SUMMARY is appended by record() throughout the pipeline; without saving
  # it the dry-run probe's entries survive and the REAL pipeline appends a second
  # copy, so the whole summary block prints twice (adversarial review Finding).
  local -a _saved_plan=("${PLAN_SUMMARY[@]}")
  DRY_RUN=1; DIVERGENCE_SHADOW=""; MANAGED_PATHS=(); KNOWN_DIRS=()
  run_install_pipeline >/dev/null 2>&1 || true
  local -a _new=("${MANAGED_PATHS[@]}")
  # Restore everything the probe touched.
  DRY_RUN="$_saved_dry"; DIVERGENCE_SHADOW="$_saved_shadow"
  MANAGED_PATHS=("${_saved_managed[@]}"); KNOWN_DIRS=()
  PLAN_SUMMARY=("${_saved_plan[@]}")

  # Build the FULL old→new map (every moved-prefix path in the new managed set),
  # NOT filtered by on-disk state. _ns_move_tree's per-file guards make the working
  # -tree move idempotent, and the SHADOW move needs the full map to realign an
  # old-layout ancestor on a crash-resume (working tree already at sysop/). Track
  # NS_MOVE_PENDING separately = the moves with real working-tree work left (old
  # present, new absent); it gates the preflight so a pure resume can't demand a
  # quiet queue (Finding 3), and an empty pending set is legal (Finding 1).
  NS_MOVE_OLD=(); NS_MOVE_NEW=(); NS_MOVE_PENDING=0
  local np old
  for np in "${_new[@]}"; do
    old="$(_ns_new_to_old "$np")"
    [[ "$old" == "$np" ]] && continue                 # unmoved prefix
    NS_MOVE_OLD+=("$old"); NS_MOVE_NEW+=("$np")
    if [[ -e "$TARGET/$old" ]] && [[ ! -e "$TARGET/$np" ]]; then
      NS_MOVE_PENDING=$((NS_MOVE_PENDING + 1))
    fi
  done
  (( ${#NS_MOVE_OLD[@]} > 0 ))
}

# §5 step 4/5: move the derived list under one tree root. Idempotent. $2="git"
# stages renames in the tracked working tree (plain-mv fallback for untracked);
# "plain" is for the ephemeral shadow.
_ns_move_tree() {
  local root="$1" how="$2" i old new
  for (( i=0; i<${#NS_MOVE_OLD[@]}; i++ )); do
    old="${NS_MOVE_OLD[$i]}"; new="${NS_MOVE_NEW[$i]}"
    [[ -e "$root/$old" ]] || continue        # already moved (resume) / absent in shadow
    [[ -e "$root/$new" ]] && continue         # dst present — skip
    mkdir -p "$(dirname "$root/$new")"
    if [[ "$how" == "git" ]]; then
      git -C "$root" mv -- "$old" "$new" 2>/dev/null || mv -- "$root/$old" "$root/$new"
    else
      mv -- "$root/$old" "$root/$new"
    fi
  done
}

# §5 step 4: move the unmanaged SYSOP_ISSUES.md (working tree only — it carries
# consumer content, is never in the managed set, so it rides outside the derived
# list). Loop installs keep it lazy, so absence is a normal no-op.
_ns_move_issues_log() {
  local old="SYSOP_ISSUES.md" new="sysop/SYSOP_ISSUES.md"
  [[ -e "$TARGET/$old" ]] || return 0
  [[ -e "$TARGET/$new" ]] && return 0
  mkdir -p "$TARGET/sysop"
  git -C "$TARGET" mv -- "$old" "$new" 2>/dev/null || mv -- "$TARGET/$old" "$TARGET/$new"
}

# §5 step 5 tail: remap DIVERGED_PATHS from old→new spelling so the post-overwrite
# delta report (which runs after the move) joins against new-layout paths, and
# copy_file's preservation (keyed on the moved shadow ancestor) lines up. Called
# AFTER report_pre_overwrite_divergence (which needs old spellings for its
# `git show HEAD:<path>` recovery hints).
_ns_remap_diverged_paths() {
  (( ${#DIVERGED_PATHS[@]} == 0 )) && return 0
  local i entry mp added removed
  for (( i=0; i<${#DIVERGED_PATHS[@]}; i++ )); do
    IFS=$'\t' read -r mp added removed <<< "${DIVERGED_PATHS[$i]}"
    DIVERGED_PATHS[$i]="$(_ns_old_to_new "$mp")"$'\t'"$added"$'\t'"$removed"
  done
}

# Finding 2: normalize --accept-upstream keys from the OLD (flat scripts/) spelling
# to the NEW (sysop/) spelling. A pre-migration consumer names the path that exists
# in their tree NOW (scripts/run_checks.sh) — the spelling any pre-migration message
# used — but copy_file keys its preservation lookup on the post-move dst-relative
# path (sysop/scripts/run_checks.sh), so an old-spelled key never matches: the
# requested overwrite silently no-ops (file preserved instead) and the run ends with
# a spurious stale-accept warning. Mirrors _ns_remap_diverged_paths / the managed-path
# normalization. Idempotent (a NEW-spelled key passes through _ns_old_to_new
# unchanged); a non-vendor key (.claude/foo) also passes through. Each entry's value
# is carried over so the post-pipeline stale-accept accounting stays accurate.
_ns_remap_accept_upstream() {
  (( ${#ACCEPT_UPSTREAM[@]} == 0 )) && return 0
  local k nk
  local -A _remapped=()
  for k in "${!ACCEPT_UPSTREAM[@]}"; do
    nk="$(_ns_old_to_new "$k")"
    _remapped[$nk]="${ACCEPT_UPSTREAM[$k]}"
  done
  ACCEPT_UPSTREAM=()
  for k in "${!_remapped[@]}"; do
    ACCEPT_UPSTREAM[$k]="${_remapped[$k]}"
  done
}

# T2: migrate a consumer settings file — drop the OLD shipped allow-rules (so the
# now-dead flat-scripts/ rules don't linger and silently auto-approve a future
# consumer file at that path) and re-path the two hook command strings. The
# normal install_permissions merge then appends the new sysop/ rules. Applies to
# BOTH .claude/settings.json and .claude/settings.local.json (the harness writes
# the latter most often, and it carries shipped-script rules live in GDP).
# Old-rule source priority: shadow (exact) → git-show OLD → tertiary inverse-map
# of the current template (loses only upstream-deleted rules; degraded path).
_ns_migrate_settings() {
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  local template="$REPO_ROOT/core/companion/.claude/settings.json"
  [[ -f "$template" ]] || return 0
  local old_src=""
  if [[ -n "$DIVERGENCE_SHADOW" && -f "$DIVERGENCE_SHADOW/.claude/settings.json" ]]; then
    old_src="$DIVERGENCE_SHADOW/.claude/settings.json"
  elif [[ -n "$OLD_COMMIT" && "$OLD_COMMIT" != "unknown" ]]; then
    local _gs; _gs="$(mktemp)"
    if git -C "$REPO_ROOT" show "${OLD_COMMIT}:core/companion/.claude/settings.json" >"$_gs" 2>/dev/null; then
      old_src="$_gs"
    else
      rm -f "$_gs"
    fi
  fi
  local sf
  for sf in "$TARGET/.claude/settings.json" "$TARGET/.claude/settings.local.json"; do
    [[ -f "$sf" ]] || continue
    python3 - "$sf" "$template" "$old_src" <<'PY' || note "settings migration: skipped $(rel "$sf") (unparseable)"
import json, re, sys
target_path, template_path, old_src = sys.argv[1], sys.argv[2], sys.argv[3]
HOOK_FILES = ("permission_denied_hook.py", "parse_subagent_envelope.py")

def load(p):
    with open(p) as f:
        return json.load(f)

try:
    tgt = load(target_path)
except Exception:
    sys.exit(1)  # unparseable target → leave it, note printed by caller

tmpl = load(template_path)
# The removal set is the OLD (flat scripts/-spelled) shipped VENDOR-PATH rules —
# the dead spellings this migration retires — and NOTHING else. It is applied to
# BOTH .claude/settings.json AND the consumer/harness-owned .claude/settings.local.json,
# so it must never contain a still-valid rule (adversarial review Finding 1). The
# earlier `r.replace("sysop/scripts/", "scripts/")` over ALL template rules was a
# no-op for the ~20 non-path rules (Bash(gh pr merge:*), Bash(git checkout:*),
# Bash(python3 -c:*), …), so those CURRENT-VALID rules entered the removal set
# verbatim and got stripped from settings.local.json (where install_permissions
# never re-adds them) and from loop-mode settings.json (only the 16-rule LOOP_ALLOW
# subset is re-added) — auto-approved commands silently started prompting again.
# A rule is a movable vendor-path rule iff its flat and sysop/-namespaced spellings
# differ; only such a rule's flat spelling is dead. Non-path and consumer-authored
# rules map to themselves and are never included, so they survive.
#
# The current template gives the live shipped vendor rules; the shadow / git-show
# OLD settings is unioned in only to also catch vendor rules deleted upstream since
# the old install (the same predicate filters its non-vendor rules out). An
# adopt-bridge shadow is itself sysop/-spelled — taking the flat spelling of each of
# its vendor rules still yields the dead flat spelling to strip.
def _flat(r):
    return r.replace("sysop/scripts/", "scripts/")

def _is_vendor_rule(r):
    # References a vendor scripts/ path the namespace migration moves (either
    # spelling). The lookbehind leaves an already-namespaced path untouched, mirroring
    # the hook-command re-path below.
    return _flat(r) != re.sub(r"(?<!sysop/)scripts/", "sysop/scripts/", r)

old_allow = {_flat(r) for r in tmpl.get("permissions", {}).get("allow", [])
             if _is_vendor_rule(r)}
if old_src:
    old_allow |= {_flat(r) for r in load(old_src).get("permissions", {}).get("allow", [])
                  if _is_vendor_rule(r)}

perms = tgt.get("permissions")
if isinstance(perms, dict) and isinstance(perms.get("allow"), list):
    perms["allow"] = [r for r in perms["allow"] if r not in old_allow]

# Re-path hook command strings that reference a Sysop hook filename.
hooks = tgt.get("hooks")
if isinstance(hooks, dict):
    for event, entries in hooks.items():
        for entry in entries or []:
            for h in entry.get("hooks", []) or []:
                cmd = h.get("command")
                if isinstance(cmd, str):
                    # Re-path ONLY the specific `scripts/<hook filename>` token —
                    # not every `/scripts/` in the command (a consumer wrapper like
                    # `cd /opt/scripts/ && … scripts/hook.py` must keep its unrelated
                    # cd path). The negative lookbehind leaves an already-migrated
                    # `sysop/scripts/<fn>` untouched (idempotent). Adversarial review.
                    for fn in HOOK_FILES:
                        cmd = re.sub(r"(?<!sysop/)scripts/" + re.escape(fn),
                                     "sysop/scripts/" + fn, cmd)
                    h["command"] = cmd

with open(target_path, "w") as f:
    json.dump(tgt, f, indent=2)
    f.write("\n")
PY
  done
}

# T4: deterministic post-update stale-reference report — files Sysop does NOT own
# that still name old flat scripts/ paths. Never auto-edited. Scans git-tracked
# files (excluding sysop/**) plus, regardless of tracking, settings*.json,
# .git/hooks/*, and .github/workflows/* (armed hooks gate on staged-path trigger
# regexes like `^scripts/` that carry no shipped basename — after migration they
# silently stop matching, a quietly-bypassed gate). *.bak* excluded (installer
# backup noise). Populates NS_STALE_REFS for the reporting step.
_ns_scan_stale_refs() {
  NS_STALE_REFS=()
  local -a bases=()
  local f b
  # Same vendor surface the migration tree-probe uses (core + installed packs), so a
  # consumer file naming a pack script (scripts/shared_cli.py) is flagged too.
  while IFS= read -r b; do
    [[ -n "$b" ]] && bases+=("$b")
  done < <(_ns_vendor_basenames)
  local base_alt; base_alt="$(IFS='|'; printf '%s' "${bases[*]}")"
  # POSIX-ERE word boundary that BOTH `git grep -E` and `grep -E` honor — neither
  # implements `\b` (git grep -E silently matches nothing with it; adversarial
  # review Finding), so `\bscripts/` left the git-tracked scan dead AND
  # boundary-matched `sysop/scripts/`, flooding the report with the migrated file.
  # This matches scripts/ only at line start or after a non-word, non-slash char,
  # so sysop/scripts/ and companion/scripts/ (slash-preceded) never match.
  local BND='(^|[^/[:alnum:]_])'
  local tracked_pat="${BND}scripts/(${base_alt}|hooks/|ci/|run_checks)"
  local plain_pat="${BND}scripts/"

  # Finding 3 (dry-run fidelity): in a DRY-RUN migration the tree hasn't moved and the
  # settings/lock haven't been rewritten yet, so a naive scan floods with Sysop's OWN
  # files (the flat vendor scripts, old skill bodies, ~20 pre-migration allow-rules,
  # even the lock) — none of which the REAL run reports, because it moved them under
  # sysop/ (excluded by :!sysop/) and rewrote the settings + lock. Simulate that
  # post-move reality by excluding every path Sysop owns or refreshes — its charter is
  # exactly "files Sysop does NOT own". The full move map (both spellings), every
  # managed path the pipeline rewrites (both spellings — e.g. old .claude/skills bodies
  # are overwritten with sysop/-spelled refs), the lock, and the two settings files the
  # migration rewrites. Real runs (DRY_RUN=0) leave this set empty and scan the
  # already-moved tree directly, so a genuine consumer flat-settings ref is still
  # surfaced there. NS_MOVE_OLD/NEW + MANAGED_PATHS are populated by the time the
  # report runs (the dry-run pipeline ran above).
  local -A _own=()
  if [[ "$DRY_RUN" -eq 1 && "$MIGRATION_MODE" -eq 1 ]]; then
    local _p
    for _p in "${NS_MOVE_OLD[@]}"; do _own[$_p]=1; done
    for _p in "${NS_MOVE_NEW[@]}"; do _own[$_p]=1; done
    for _p in "${MANAGED_PATHS[@]}"; do
      _own[$_p]=1
      _own["$(_ns_new_to_old "$_p")"]=1
    done
    _own[".claude/sysop.lock"]=1
    _own[".claude/settings.json"]=1
    _own[".claude/settings.local.json"]=1
  fi

  local -a scan=()
  # git-tracked files (excluding sysop/**) matching the basename-scoped pattern.
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ "$f" == sysop/* ]] && continue
    [[ "$f" == *.bak* ]] && continue
    [[ -n "${_own[$f]:-}" ]] && continue
    scan+=("$f")
  done < <(git -C "$TARGET" grep -lIE "$tracked_pat" -- ':!sysop/' 2>/dev/null || true)

  # Always-scan set (may be untracked): settings files, armed hooks, CI workflows.
  # Armed hooks gate on staged-path trigger regexes (^scripts/…) that carry no
  # shipped basename, so match with the plain boundary pattern. The producer must
  # NOT abort under `set -e` — an absent settings.local.json is the common case,
  # and a leading `ls` of it would exit non-zero and kill the subshell before the
  # two `find`s ran, silently dropping .git/hooks + CI from the scan (adversarial
  # review Finding). Hence the if-guarded emission, never `ls`.
  local extra _er
  while IFS= read -r extra; do
    [[ -z "$extra" ]] && continue
    [[ "$extra" == *.bak* ]] && continue
    _er="${extra#"$TARGET"/}"
    [[ -n "${_own[$_er]:-}" ]] && continue
    if grep -IEl "$plain_pat" "$extra" >/dev/null 2>&1; then
      scan+=("$_er")
    fi
  done < <(
    for _sf in "$TARGET"/.claude/settings.json "$TARGET"/.claude/settings.local.json; do
      if [[ -f "$_sf" ]]; then printf '%s\n' "$_sf"; fi
    done
    find "$TARGET/.git/hooks" -maxdepth 1 -type f 2>/dev/null
    find "$TARGET/.github/workflows" -maxdepth 1 -type f 2>/dev/null
  )

  # Dedup + capture file:line for each hit.
  local -A seen=()
  local rel line
  for rel in "${scan[@]}"; do
    [[ -n "${seen[$rel]:-}" ]] && continue
    seen[$rel]=1
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      NS_STALE_REFS+=("$rel:$line")
    done < <(grep -nE "$plain_pat" "$TARGET/$rel" 2>/dev/null | head -20 | cut -d: -f1)
  done
}

# §5 step 7 (a)+(b): honest migration summary + the T4 stale-reference report.
# Replaces the numstat delta table (suppressed in migration mode). Runs after the
# preserved-paths block report_post_overwrite_deltas already printed.
_ns_migration_report() {
  hdr "namespace migration summary (Phase 128)"
  say ""
  note "moved:     ${#NS_MOVE_NEW[@]} vendor path(s) into sysop/"
  note "preserved: ${#PRESERVED_PATHS[@]} consumer-modified path(s) (kept at their new sysop/ location)"
  note "swept:     ${NS_SWEPT_COUNT} upstream-dropped path(s)"
  if (( ${#PRESERVED_PATHS[@]} > 0 )); then
    say ""
    say "  ⚠ Each preserved script still carries the OLD self-location idiom at its new"
    say "    path (shell \${REPO_ROOT}/scripts or Python parent.parent). Reconcile those"
    say "    against upstream (--accept-upstream <path>) or hand-patch the anchor."
  fi

  _ns_scan_stale_refs
  say ""
  if (( ${#NS_STALE_REFS[@]} == 0 )); then
    note "stale-reference scan: no consumer files reference the old scripts/ paths."
  else
    hdr "stale references to old scripts/ paths (Phase 128 — fix by hand)"
    say ""
    say "  These consumer-owned files still name flat scripts/ paths. Sysop never edits"
    say "  them; update them yourself (armed .git/hooks and CI trigger-regexes silently"
    say "  stop matching after the move):"
    local ref
    for ref in "${NS_STALE_REFS[@]}"; do
      note "$ref"
    done
  fi
}

# T7: refuse a migration that can't complete cleanly. Extra worktrees run armed
# hooks that reference sysop/scripts/ post-re-arm and would break inside a
# pre-migration worktree; in_progress claims mean live batch work; a foreign
# (non-partial-migration) sysop/ dir is the exact collision this phase removes.
# Refuse-with-guidance (no --force bypass): all three are cheap for the consumer
# to clear, and half-migrating around them is a foot-gun.
_ns_migration_preflight() {
  # Extra worktrees (beyond the main checkout).
  local wt_count
  wt_count="$(git -C "$TARGET" worktree list --porcelain 2>/dev/null | grep -c '^worktree ' || true)"
  if [[ "${wt_count:-1}" -gt 1 ]]; then
    err "Namespace migration needs a single worktree, but extra git worktrees exist."
    err "  Armed hooks in those worktrees reference sysop/scripts/ after re-arm and would"
    err "  break there. Remove them first: bash sysop/scripts/cleanup_worktrees.sh --clean"
    err "  (or 'git worktree remove'), then re-run the update."
    exit 1
  fi
  # Live task claims. The operational truth of an in-flight claim is a lock file
  # (Phase 32: locks live under the main checkout's .locks/, and /claim-task
  # always passes --lock) — grepping tasks/index.yml for `status: in_progress`
  # false-matches the always-in_progress current-focus PHASE and the commented
  # example task, so key on the lock instead.
  local locks_dir="$TARGET/.locks"
  if [[ -d "$locks_dir" ]] && compgen -G "$locks_dir/*.lock" >/dev/null 2>&1; then
    err "Namespace migration needs a quiet queue, but active task lock(s) exist in .locks/."
    err "  Finish or release the claim(s) (bash sysop/scripts/claim_task.sh --release <ID>), then re-run."
    exit 1
  fi
  # A foreign sysop/ dir with no sign of being a prior partial migration of ours.
  local existing
  if existing="$(_ns_foreign_sysop_dir)" && [[ ! -d "$TARGET/sysop/scripts" ]] \
     && [[ ! -f "$TARGET/sysop/docs/WORKFLOW.md" ]] && [[ ! -f "$TARGET/sysop/SYSOP_ISSUES.md" ]]; then
    err "A '$existing' path already exists and isn't a Sysop layout."
    err "  Phase 128 installs Sysop's vendor files under sysop/. Rename or remove your"
    err "  existing sysop/ first, then re-run."
    exit 1
  fi
}

# ─── Phase 133: runtime-dir consolidation (sysop/runtime/) ────────────────
# The four gitignored runtime dirs move under one vendor-namespaced home
# (SYSOP_NAMESPACE_SPEC § 10, the deliberately-cut Phase 128 leg):
#   .subagent-envelopes/ → sysop/runtime/subagent-envelopes/
#   .auto-build/         → sysop/runtime/auto-build/
#   .pending-docs/       → sysop/runtime/pending-docs/
#   .locks/              → sysop/runtime/locks/
# The dirs are gitignored (untracked), so the move is plain mv — no git mv,
# no lock managed_paths involvement. Phase 32 semantics are preserved: locks
# still resolve via `git rev-parse --git-common-dir` relative to the MAIN
# checkout; only the leaf path under that root changes.
RT_OLD_DIRS=(".subagent-envelopes" ".auto-build" ".pending-docs" ".locks")
RT_NEW_BASE="sysop/runtime"
RT_MOVE_PENDING=0
RT_PENDING_DIRS=()

_rt_new_name() {  # ".auto-build" → "auto-build"
  printf '%s\n' "${1#.}"
}

_rt_compute_pending() {
  RT_PENDING_DIRS=()
  local d
  for d in "${RT_OLD_DIRS[@]}"; do
    [[ -d "$TARGET/$d" ]] && RT_PENDING_DIRS+=("$d")
  done
  RT_MOVE_PENDING=${#RT_PENDING_DIRS[@]}
}

# Mixed-version split-brain guard (spec § 10 v2 — the leg must not ship
# without it): while any pre-migration worktree exists, its checked-out script
# copies write <main>/.locks/ while the migrated main checkout writes
# <main>/sysop/runtime/locks/ — two lock registries, and every "is anyone
# working on this?" answer becomes wrong. Same refuse-with-guidance posture as
# _ns_migration_preflight (no --force bypass; both states are cheap to clear).
_rt_migration_preflight() {
  local wt_count
  wt_count="$(git -C "$TARGET" worktree list --porcelain 2>/dev/null | grep -c '^worktree ' || true)"
  if [[ "${wt_count:-1}" -gt 1 ]]; then
    err "Runtime-dir consolidation needs a single worktree, but extra git worktrees exist."
    err "  Script copies checked out in those worktrees still write .locks/ at the main"
    err "  checkout while the migrated main writes sysop/runtime/locks/ — a split-brain"
    err "  lock registry. Merge or remove the worktrees first"
    err "  (bash sysop/scripts/cleanup_worktrees.sh --clean, or 'git worktree remove'),"
    err "  then re-run the update."
    exit 1
  fi
  # Live task claims — same "quiet queue" rule as the namespace preflight:
  # a lock moved mid-claim strands the claim's tooling on the old path.
  if [[ -d "$TARGET/.locks" ]] && compgen -G "$TARGET/.locks/*.lock" >/dev/null 2>&1; then
    err "Runtime-dir consolidation needs a quiet queue, but active task lock(s) exist in .locks/."
    err "  Finish or release the claim(s) (bash sysop/scripts/claim_task.sh --release <ID>), then re-run."
    exit 1
  fi
}

# Merge src dir into dst dir: move-if-absent per entry, recurse on dir/dir
# collisions (so .auto-build/parked/ archive content survives a crash-resume
# where both sides already have a parked/ — Phase 65a durability requirement),
# and never clobber an existing destination entry.
_rt_merge_dir() {
  local src="$1" dst="$2"
  local child base
  for child in "$src"/* "$src"/.[!.]* "$src"/..?*; do
    [[ -e "$child" || -L "$child" ]] || continue
    base="$(basename "$child")"
    if [[ ! -e "$dst/$base" && ! -L "$dst/$base" ]]; then
      mv "$child" "$dst/$base"
    elif [[ -d "$child" && -d "$dst/$base" && ! -L "$child" && ! -L "$dst/$base" ]]; then
      _rt_merge_dir "$child" "$dst/$base"
      rmdir "$child" 2>/dev/null || true
    fi
    # else: same-named non-dir entry on both sides — leave the old copy in
    # place; the caller reports the leftover for hand reconciliation.
  done
}

# Move-if-exists, resumable from any partial state: whole-dir mv when the
# destination is absent, recursive no-clobber merge when both sides exist
# (crash-resume), silent no-op when nothing is pending. A completed
# consolidation re-probes as "no old dirs present" → normal update.
migrate_runtime_dirs() {
  (( RT_MOVE_PENDING == 0 )) && return 0
  hdr "runtime-dir consolidation (Phase 133)"
  local d name new
  if [[ "$DRY_RUN" -eq 1 ]]; then
    for d in "${RT_PENDING_DIRS[@]}"; do
      note "would move: $d/ → $RT_NEW_BASE/$(_rt_new_name "$d")/"
    done
    return 0
  fi
  ensure_dir "$TARGET/$RT_NEW_BASE"
  for d in "${RT_PENDING_DIRS[@]}"; do
    name="$(_rt_new_name "$d")"
    new="$TARGET/$RT_NEW_BASE/$name"
    if [[ ! -e "$new" ]]; then
      mv "$TARGET/$d" "$new"
      note "moved: $d/ → $RT_NEW_BASE/$name/"
    else
      _rt_merge_dir "$TARGET/$d" "$new"
      rmdir "$TARGET/$d" 2>/dev/null || true
      if [[ -d "$TARGET/$d" ]]; then
        note "merged: $d/ → $RT_NEW_BASE/$name/ — ⚠ $d/ NOT removed: same-named"
        note "  entries exist on both sides; reconcile the leftovers by hand."
      else
        note "merged: $d/ → $RT_NEW_BASE/$name/ (crash-resume: destination already existed)"
      fi
    fi
  done
  # .gitignore hygiene: the old dot-dir entries a pre-133 install appended
  # (all four in full mode; just .pending-docs/ in loop mode) are now dead.
  # They are consumer-file lines, so we never rewrite them (append-only
  # contract) — just say so once.
  if [[ -f "$TARGET/.gitignore" ]] \
     && grep -qxE '\.(locks|pending-docs|auto-build|subagent-envelopes)/' "$TARGET/.gitignore" 2>/dev/null; then
    note "note: the old .gitignore entries (.subagent-envelopes/ .auto-build/"
    note "      .pending-docs/ .locks/) are now unused — safe to delete by hand."
  fi
  # Worktree ignore lag: a worktree only honors the COMMITTED .gitignore of
  # its checked-out branch, so until the consumer commits the sysop/runtime/
  # append, runtime writes inside a fresh worktree show up in `git status
  # --porcelain` and /review-close's dirty classifier auto-SKIPs the branch.
  note "commit the updated .gitignore before claiming new tasks — worktrees"
  note "  only see committed ignore rules (a pre-existing branch's worktree"
  note "  needs the entry rebased/merged in before its close runs clean)."
}

# ─── main ────────────────────────────────────────────────────
main() {
  hdr "Sysop installer"
  [[ "$DRY_RUN" -eq 1 ]] && say "(dry-run mode — nothing will be written)"

  # Clean any temp resources (Phase 8/24b divergence shadow, Phase 111 --ref
  # worktree) on every exit path. Both are empty until created, so this is inert
  # for the common fresh-install case.
  trap '_cleanup_install_temp' EXIT

  # Target.
  if [[ -z "$TARGET" ]]; then
    TARGET="$(prompt_target)"
  fi
  if [[ -z "$TARGET" ]]; then
    err "No target specified."
    exit 2
  fi
  TARGET="$(canonicalize_target "$TARGET")"

  if [[ "$TARGET" == "$REPO_ROOT" ]]; then
    err "Refusing to install Sysop into its own source tree."
    exit 2
  fi

  validate_target "$TARGET" || exit 1

  # Phase 75: `--packs auto` → run stack detection now that TARGET is known and
  # validated, then continue as if the detected CSV had been passed to --packs.
  # Translated centrally (before mode dispatch) so fresh/adopt paths share it;
  # PACKS_PROVIDED stays 1, so an empty detection means core-only, never a
  # surprise interactive prompt. 'auto' is standalone — reject combining it with
  # explicit packs here rather than letting resolve_packs die on "unknown pack
  # 'auto'". Skipped under --check (read-only; it reads packs from the lock).
  if [[ ",$PACKS_ARG," == *",auto,"* ]] && [[ "$PACKS_ARG" != "auto" ]]; then
    err "--packs auto must be used on its own, not combined with other packs (got: '$PACKS_ARG')."
    exit 2
  fi
  if [[ "$PACKS_ARG" == "auto" ]] && [[ "$CHECK_MODE" -eq 0 ]]; then
    PACKS_ARG="$(detect_packs)"
    if [[ -n "$PACKS_ARG" ]]; then
      say "  → auto-detected packs: ${PACKS_ARG//,/, }"
    else
      say "  → auto-detect found no populated-pack signals; installing core only."
    fi
  fi

  # Dispatch read-only and adopt modes.
  if [[ "$CHECK_MODE" -eq 1 ]]; then
    cmd_check
    return 0
  fi
  if [[ "$ADOPT_MODE" -eq 1 ]]; then
    cmd_adopt
    return 0
  fi

  # T7 (Phase 128): a fresh install writes the sysop/ vendor dir; refuse if a
  # sysop/ already exists that Sysop did NOT create (no lock present) — a
  # consumer's own directory we'd clobber with no preserve semantics. A sysop/
  # from a prior Sysop install (lock present) is a normal re-install and passes
  # through. No --force bypass for the genuine collision: clobbering is
  # unrecoverable.
  if [[ "$UPDATE_MODE" -eq 0 ]] && [[ ! -f "$TARGET/$LOCK_REL" ]]; then
    local _existing_sysop
    if _existing_sysop="$(_ns_foreign_sysop_dir)"; then
      err "A '$_existing_sysop' path already exists and isn't a Sysop install (no lock)."
      err "  Sysop installs its vendor files under sysop/. Rename or remove your existing"
      err "  sysop/ directory before installing Sysop."
      exit 1
    fi
    # Phase 128 (Finding 4): a lockless fresh install over a committed OLD-layout
    # Sysop tree (flat scripts/*, root WORKFLOW*.md) — e.g. an install whose
    # .claude/sysop.lock was lost. A plain install would write sysop/ ALONGSIDE the
    # flat tree, stranding it as an unmanaged duplicate (no migration/sweep/
    # preservation — all UPDATE_MODE-gated) and re-arming hooks over any local
    # edits. Refuse with guidance: --adopt rebuilds the lost lock, then --update
    # migrates. Requires CORROBORATED evidence (2+ vendor basenames, or one plus a
    # Sysop artifact) so a genuinely-new consumer who owns a single colliding
    # basename isn't false-refused. (SELECTED_PACKS isn't resolved yet, so this is a
    # core-only probe — enough, since every real install ships core scripts.)
    if _ns_old_layout_corroborated; then
      err "Old-layout Sysop files exist at flat scripts/ but there's no lock file."
      err "  This looks like a Sysop install whose lock was lost. A fresh install would"
      err "  write sysop/ and strand the old flat scripts/ tree as an unmanaged duplicate"
      err "  (and re-arm hooks over any local edits). Recover tracking instead:"
      err "    bash ${SYSOP_SRC_CLONE:-$REPO_ROOT}/install.sh $TARGET --adopt"
      err "  then run the migration update:"
      err "    bash ${SYSOP_SRC_CLONE:-$REPO_ROOT}/install.sh $TARGET --update"
      err "  (Or, if these flat scripts/ are NOT from Sysop, move them aside and re-run.)"
      exit 1
    fi
  fi

  # Phase 111: --ref pins the source to a reviewed release tag/rev instead of the
  # clone's live HEAD, so a cautious consumer can install/update from a
  # known-good release rather than tracking whatever HEAD happens to be. There is
  # no ref-establishment step in the copy path — every install_* reads $REPO_ROOT
  # directly — so we materialise the rev into a temp worktree (the
  # reconstruct_old_install pattern) and re-point $REPO_ROOT at it for the whole
  # pipeline. get_sysop_commit then records the rev's commit in the lock, and a
  # later --check correctly reports the consumer as N commits behind HEAD.
  # Rejected for --adopt/--check at arg-validation. Cleaned by the EXIT trap.
  if [[ -n "$REF_OVERRIDE" ]]; then
    if ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
      err "--ref requires the Sysop source to be a git clone (source: $REPO_ROOT)."
      exit 2
    fi
    local _ref_commit
    if ! _ref_commit="$(git -C "$REPO_ROOT" rev-parse --verify "${REF_OVERRIDE}^{commit}" 2>/dev/null)"; then
      err "--ref: cannot resolve '$REF_OVERRIDE' in the Sysop source ($REPO_ROOT)."
      err "  If it's a release tag your clone hasn't fetched yet:"
      err "    git -C $REPO_ROOT fetch --tags"
      exit 1
    fi
    SYSOP_SRC_CLONE="$REPO_ROOT"
    REF_WORKTREE="$(mktemp -d)"
    rmdir "$REF_WORKTREE"   # git worktree add wants a non-existing path
    if ! git -C "$SYSOP_SRC_CLONE" worktree add --detach --quiet "$REF_WORKTREE" "$REF_OVERRIDE" 2>/dev/null; then
      err "--ref: failed to materialise the Sysop source at '$REF_OVERRIDE'."
      REF_WORKTREE=""   # nothing to clean
      exit 1
    fi
    REPO_ROOT="$REF_WORKTREE"
    # Phase 128 (Finding 5): --ref re-points SOURCE content only; destination wiring
    # stays new-layout (dst=$TARGET/sysop/scripts, …). A ref cut BEFORE the sysop/
    # namespace ships OLD script bodies (flat SCRIPT_DIR / parent.parent self-
    # location) into new-layout paths — a silently broken install that still exits 0.
    # The clone-HEAD T6 shim can't catch this (it greps the live installer, not the
    # ref). Detect the era from the materialised installer (the same 'sysop/scripts'
    # marker T6 uses) and hard-refuse a pre-namespace ref.
    if ! grep -q 'sysop/scripts' "$REF_WORKTREE/install.sh" 2>/dev/null; then
      err "--ref '$REF_OVERRIDE' predates the sysop/ vendor namespace (Phase 128)."
      err "  Its scripts self-locate at flat scripts/, but this installer wires them into"
      err "  sysop/scripts/ — the result would be silently broken. Options:"
      err "    • pin a newer release tag that post-dates the sysop/ namespace, or"
      err "    • check out that tag and run ITS OWN installer instead of this one:"
      err "        git -C ${SYSOP_SRC_CLONE:-$REPO_ROOT} checkout $REF_OVERRIDE && bash install.sh $TARGET"
      exit 1
    fi
    say "  → pinned to $REF_OVERRIDE (${_ref_commit:0:12})"
  fi

  local lock_path="$TARGET/$LOCK_REL"
  local -a old_managed=()
  local old_commit="" installed_at=""

  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    if [[ ! -f "$lock_path" ]]; then
      err "No lock file at $(rel "$lock_path"). This install pre-dates Phase 7."
      err "Run with --adopt first to backfill tracking, then --update."
      exit 1
    fi
    # Load lock fields.
    old_commit="$(lock_field sysop_commit)"
    # ISSUE-0047: a lock with no sysop_commit anchor cannot anchor Phase 24b's
    # 3-way divergence detection — reconstruct_old_install() returns 1, and the
    # clean-tree fallback then overwrites in-scope consumer scripts undetected
    # (same effect as --force, but silent, exit 0). The read-only --check path
    # already hard-errors on exactly this; make the *destructive* --update at
    # least as strict — but ONLY when a real anchor was actually possible:
    #   • git source → get_sysop_commit yields a real sha, so an empty/"unknown"
    #     lock anchor is corruption (the jig→sysop migration lost it) → fail
    #     closed, and --adopt can rebuild it.
    #   • non-git source (unpacked tarball/zip — an "any agent or none" path) →
    #     the source itself can only ever yield "unknown", so a "unknown" lock
    #     anchor is NORMAL, not corruption. Failing closed there would break the
    #     documented update flow AND advertise a --adopt recovery that provably
    #     can't help (adopt would just re-write "unknown"). Leave that population
    #     on the existing Phase-99 fallback (proceed-if-clean, abort-if-dirty).
    # --force opts out of preservation deliberately, so it is exempt either way.
    # (ANCHOR_OVERRIDE is empty in --update mode — validated at arg parse — so
    # get_sysop_commit here only ever takes its HEAD-or-"unknown" branch.)
    local _src_anchor; _src_anchor="$(get_sysop_commit)"
    if [[ "$FORCE" -eq 0 ]] && [[ "$_src_anchor" != "unknown" ]] \
         && { [[ -z "$old_commit" ]] || [[ "$old_commit" == "unknown" ]]; }; then
      err "Lock at $(rel "$lock_path") has no sysop_commit anchor, so committed-edit"
      err "preservation (Phase 24b) cannot run — proceeding would overwrite in-scope"
      err "consumer scripts (sysop/scripts/*, sysop/scripts/hooks/*) undetected (BeanRider ISSUE-0047)."
      err ""
      err "  Options:"
      err "    1. Re-adopt to rebuild the anchor, then re-run the update:"
      err "         bash ${SYSOP_SRC_CLONE:-$REPO_ROOT}/install.sh $TARGET --adopt"
      err "       (--adopt rewrites a lock whose anchor is missing — no need to delete"
      err "        it first; preservation then works on the next --update. Add"
      err "        --anchor <REV> to pin a specific known rev.)"
      err "    2. Overwrite ALL managed paths without preservation (only if you have no"
      err "       local script edits to keep):"
      err "         bash sysop/scripts/sysop-update.sh --force"
      exit 1
    fi
    installed_at="$(lock_field installed_at)"
    local line
    while IFS= read -r line; do
      [[ -n "$line" ]] && old_managed+=("$line")
    done < <(lock_field managed_paths)
    # If --packs not given, take packs from the lock so the re-install matches
    # the consumer's prior pack selection.
    if [[ -z "$PACKS_ARG" ]]; then
      local pack_line
      while IFS= read -r pack_line; do
        [[ -z "$pack_line" ]] && continue
        if [[ -z "$PACKS_ARG" ]]; then
          PACKS_ARG="$pack_line"
        else
          PACKS_ARG="$PACKS_ARG,$pack_line"
        fi
      done < <(lock_field packs)
    fi

    # Phase 123: resolve the install mode. Pre-123 locks have no `mode` field →
    # empty → full (what every pre-loop install was). --update without --mode
    # re-applies the recorded mode; --update --mode full on a loop install is the
    # additive loop→full upgrade; --mode loop on a full install (downgrade) is out
    # of scope — reinstall fresh.
    local lock_mode; lock_mode="$(lock_field mode)"
    # Pre-123 locks have no `mode` (empty → full); an unknown/corrupt value (a
    # hand-edit, or a mode written by a newer installer) also normalizes to full
    # rather than flowing through as a silent non-loop with the garbage
    # re-persisted verbatim by write_lock_file.
    [[ "$lock_mode" =~ ^(loop|full)$ ]] || lock_mode="full"
    if [[ "$MODE_PROVIDED" -eq 1 ]]; then
      if [[ "$INSTALL_MODE" == "$lock_mode" ]]; then
        :
      elif [[ "$lock_mode" == "loop" && "$INSTALL_MODE" == "full" ]]; then
        say "  → upgrading loop → full (additive: adds lifecycle skills, scripts, and the tasks/ scaffold)"
      else
        err "Downgrade full → loop is out of scope."
        err "  To switch to loop mode, reinstall fresh: remove .claude/ (and the lock), then re-run with --mode loop."
        exit 2
      fi
    else
      INSTALL_MODE="$lock_mode"
    fi

  fi

  # Phase 142: re-read the Codex-links choice from the lock. Precedence is
  # CLI flag > lock > default true, with NO --update scoping — a plain
  # re-install over an existing install is a supported path (see the runtime-
  # migration comment below), and ignoring the field there would silently
  # resurrect the links, or worse, hard-error on a collision the consumer
  # already acknowledged with --no-codex-links. Pre-Codex locks have no field →
  # empty → true, so the links arrive on the next run (the intended migration).
  if [[ "$CODEX_LINKS_PROVIDED" -eq 0 ]] && [[ -f "$TARGET/$LOCK_REL" ]]; then
    local lock_codex; lock_codex="$(lock_field codex_links)"
    # lock_field renders JSON booleans through python, so it yields True/False.
    if [[ "$lock_codex" == "False" || "$lock_codex" == "false" ]]; then
      CODEX_LINKS=0
    else
      CODEX_LINKS=1
    fi
  fi

  # Packs (from --packs, lock-derived above, or interactive). PACKS_PROVIDED
  # gates the picker so an explicit `--packs ''` (or a `--packs auto` that
  # detected nothing) installs core only instead of silently prompting.
  local packs_input="$PACKS_ARG"
  if [[ -z "$packs_input" ]] && [[ "$PACKS_PROVIDED" -eq 0 ]] && [[ "$UPDATE_MODE" -eq 0 ]]; then
    packs_input="$(prompt_packs)"
  fi
  resolve_selected_packs "$packs_input"

  # Phase 142: Codex-link preflight, PINNED HERE. It must run after the lock load
  # above (which resolves CODEX_LINKS from a prior opt-out) and strictly before
  # the Phase-128 migration block below — that ordering is what puts it ahead of
  # _ns_precompute_and_derive's hidden DRY_RUN pipeline, the pre-update snapshot
  # commit, the namespace moves, and the runtime migration, i.e. before every
  # target mutation on both the fresh and update paths. Moving it later would
  # leave a consumer with a half-mutated tree behind a collision error.
  preflight_codex_links

  # Phase 128 (§5 steps 2–3): detect + prepare a sysop/ namespace migration. Only
  # relevant in --update (a fresh install already writes the new layout). Fire on
  # EITHER signal: an old-layout vendor file still at flat scripts/ (tree-probe),
  # OR an old-spelled lock even though the tree has already moved (the crash-resume
  # window — a migration that relocated the files but died before rewriting the
  # lock; Finding 1). Missing that second signal left MIGRATION_MODE=0 on resume, so
  # the shadow never moved and copy_file silently overwrote consumer edits.
  if [[ "$UPDATE_MODE" -eq 1 ]] \
     && { _ns_migration_pending || _ns_lock_is_old_spelled "${old_managed[@]}"; }; then
    # Derive the full move map + NS_MOVE_PENDING (read-only precompute). Empty
    # pending is legal: a crash-resume can leave the tree already at sysop/ with the
    # lock still old-spelled, and this re-entry must still run the shadow move,
    # settings migration, sweep normalization, and per-file preservation to finish.
    _ns_precompute_and_derive || true
    # The T7 preflight hard-refuses on extra worktrees / active locks / a foreign
    # sysop dir — all normal workflow states. Only demand a quiet queue when real
    # working-tree moves remain (Finding 3); a pure resume (nothing left to move)
    # must not block a routine --update, and it now runs AFTER the derive.
    if (( NS_MOVE_PENDING > 0 )); then
      _ns_migration_preflight
    fi
    # Enter migration mode only when there is real migration WORK: pending
    # working-tree moves, OR an old-spelled lock still to heal (crash-resume /
    # adopt-bridge). The tree-probe fires on a SINGLE flat file, so a fully-migrated
    # consumer who keeps their OWN file at a shipped basename (scripts/run_checks.sh
    # — scripts/ was the consumer's dir pre-128) trips it on every --update; without
    # this gate MIGRATION_MODE would latch permanently (pending=0, lock new-spelled),
    # suppressing the post-overwrite delta report and printing migration noise
    # forever. pending=0 + new-spelled lock ⇒ plain update. Preservation of the
    # already-migrated sysop/scripts/* is unaffected — copy_file's Phase-24b path
    # keys on UPDATE_MODE + the shadow, not MIGRATION_MODE.
    if (( NS_MOVE_PENDING > 0 )) || _ns_lock_is_old_spelled "${old_managed[@]}"; then
      MIGRATION_MODE=1
    fi
  fi

  # Phase 133: detect the runtime-dir consolidation. Fires on --update AND on
  # a plain re-install over an existing install (lock present — the T7 guard
  # deliberately lets that path through, and it installs post-133 writers, so
  # skipping the move there would strand live locks/parked archives at the old
  # paths while every new resolver reads sysop/runtime/ — the exact split-brain
  # the preflight exists to refuse; adversarial-review finding, 2026-07-19).
  # Never on a genuinely fresh target: a lock-less repo's .locks/ or
  # .pending-docs/ would be some OTHER tool's directory — not ours to move.
  # The preflight hard-refuses on extra worktrees / active locks BEFORE the
  # confirm, mirroring the namespace T7 ordering, and only when real moves
  # are pending.
  if [[ "$UPDATE_MODE" -eq 1 ]] || [[ -f "$TARGET/$LOCK_REL" ]]; then
    _rt_compute_pending
    if (( RT_MOVE_PENDING > 0 )); then
      _rt_migration_preflight
    fi
  fi

  # Plan summary.
  hdr "plan"
  say "  target:  $TARGET"
  if (( ${#SELECTED_PACKS[@]} > 0 )); then
    say "  packs:   ${SELECTED_PACKS[*]}"
  else
    say "  packs:   (core only)"
  fi
  if [[ "$INSTALL_MODE" == "loop" ]]; then
    say "  install: loop  (convention loop only — no task queue / merge gate)"
  else
    say "  install: full"
  fi
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    say "  mode:    update (was at ${old_commit:0:12})"
  else
    say "  mode:    $([[ "$DRY_RUN" -eq 1 ]] && echo "dry-run" || echo "apply")"
  fi
  if [[ "$MIGRATION_MODE" -eq 1 ]]; then
    say "  layout:  MIGRATING to the sysop/ vendor dir (Phase 128) — ${#NS_MOVE_OLD[@]} path(s) move;"
    say "           scripts/ → sysop/scripts/, WORKFLOW*.md → sysop/docs/, SYSOP_ISSUES.md → sysop/"
  fi
  if (( RT_MOVE_PENDING > 0 )); then
    say "  runtime: consolidating ${RT_MOVE_PENDING} runtime dir(s) → sysop/runtime/ (Phase 133)"
  fi

  if [[ "$DRY_RUN" -eq 0 ]]; then
    if ! confirm "Proceed?"; then
      say "Aborted."
      exit 0
    fi
  fi

  # Phase 142: the Codex symlink capability probe. Deliberately AFTER the
  # confirm — it is the one part of the Codex preflight that WRITES (a throwaway
  # dir inside the target), and a run the user declines must leave their repo
  # untouched. Still ahead of the snapshot commit and the pipeline, so its
  # verdict is settled by the time install_codex_links runs.
  probe_codex_link_capability

  # Update mode: snapshot dirty managed paths into a commit before overwriting.
  # settings.json is intentionally excluded — install_permissions merges
  # set-union rather than overwriting, so the user's edits are preserved
  # without needing a snapshot. --force skips the snapshot step entirely.
  local snapshot_hash=""
  if [[ "$UPDATE_MODE" -eq 1 ]] && [[ "$FORCE" -eq 0 ]]; then
    hdr "pre-update snapshot"
    local -a snap_candidates=()
    local mp
    for mp in "${old_managed[@]}"; do
      [[ "$mp" == ".claude/settings.json" ]] && continue
      snap_candidates+=("$mp")
    done
    # Phase 128 (adversarial review Finding 1 — HIGH data-loss guard): a migration
    # can carry a dirty vendor-script edit on EITHER spelling and the lock's
    # managed_paths above may not name the on-disk one:
    #   • adopt-bridge — lock NEW-spelled, tree still OLD-layout → the edit lives at
    #     the OLD spelling (scripts/*), unmatched by the new-spelled entries above.
    #   • crash-resume — lock OLD-spelled, tree already moved → the edit lives at the
    #     NEW spelling (sysop/scripts/*), unmatched by the old-spelled entries above.
    # Add BOTH spellings of every moving path (git status ignores the non-existent
    # side) so a dirty edit is caught → snapshot commit, or fail-closed — never the
    # silent Phase-99 clean-tree overwrite. NS_MOVE_OLD/NEW were populated by the
    # migration precompute above.
    if [[ "$MIGRATION_MODE" -eq 1 ]]; then
      (( ${#NS_MOVE_OLD[@]} > 0 )) && snap_candidates+=("${NS_MOVE_OLD[@]}")
      (( ${#NS_MOVE_NEW[@]} > 0 )) && snap_candidates+=("${NS_MOVE_NEW[@]}")
    fi
    if (( ${#snap_candidates[@]} > 0 )); then
      snapshot_hash="$(snapshot_managed_paths "$old_commit" "${snap_candidates[@]}")"
    fi
    if [[ -z "$snapshot_hash" ]]; then
      note "no dirty managed paths — skipping snapshot commit"
    else
      note "snapshot commit: ${snapshot_hash:0:12}"
    fi
  fi

  # Update mode (Phase 8 + Phase 24b): pre-overwrite divergence detection.
  # Reconstruct what Sysop's OLD checkout would have produced, then diff
  # against consumer's HEAD to find committed local edits the overwrite would
  # lose (Phase 8 — warn-and-proceed for ALL managed paths). The same shadow
  # tree is then kept alive through run_install_pipeline so copy_file() can
  # per-file-diff against it for Phase 24b's in-scope paths (warn-AND-skip
  # for sysop/scripts/* and sysop/scripts/hooks/*). --force skips both steps (same
  # semantics as the pre-update snapshot).
  #
  # Decision 11: divergence runs in dry-run too, so the plan output reflects
  # would-be preservation decisions before commitment.
  DIVERGED_PATHS=()
  OLD_COMMIT="$old_commit"   # exposed to copy_file's preservation warn line
  if [[ "$UPDATE_MODE" -eq 1 ]] && [[ "$FORCE" -eq 0 ]]; then
    hdr "pre-overwrite divergence check"
    DIVERGENCE_SHADOW="$(mktemp -d)"
    # Cleaned by _cleanup_install_temp (the unified EXIT trap set in main),
    # which also removes the Phase 111 --ref worktree. DIVERGENCE_SHADOW is set
    # once and never reassigned, so no prior dir leaks.
    local divergence_packs_csv=""
    local p
    for p in "${SELECTED_PACKS[@]}"; do
      if [[ -z "$divergence_packs_csv" ]]; then
        divergence_packs_csv="$p"
      else
        divergence_packs_csv="$divergence_packs_csv,$p"
      fi
    done
    if reconstruct_old_install "$old_commit" "$DIVERGENCE_SHADOW" "$divergence_packs_csv"; then
      # Phase 128 (adversarial review Finding 3): in migration mode the lock's
      # managed_paths may be NEW-spelled (adopt-bridge) while the consumer's HEAD
      # is still OLD-layout, so `HEAD:sysop/scripts/X` misses. Normalize each
      # entry to its on-disk (old) spelling so committed edits are actually
      # detected + reported (a pre-namespace-anchor shadow is old-layout, so both
      # sides align; an adopt-reachable shadow is new-layout and simply skips —
      # copy_file's preservation still covers that case).
      local -a _dc_managed=()
      if [[ "$MIGRATION_MODE" -eq 1 ]]; then
        local _omp _alt
        for _omp in "${old_managed[@]}"; do
          if [[ -e "$TARGET/$_omp" ]]; then
            _dc_managed+=("$_omp")
          else
            _alt="$(_ns_new_to_old "$_omp")"
            if [[ "$_alt" != "$_omp" && -e "$TARGET/$_alt" ]]; then
              _dc_managed+=("$_alt")
            else
              _dc_managed+=("$_omp")
            fi
          fi
        done
      else
        _dc_managed=("${old_managed[@]}")
      fi
      detect_committed_divergence "$DIVERGENCE_SHADOW" "${_dc_managed[@]}"
      if (( ${#DIVERGED_PATHS[@]} == 0 )); then
        note "no committed local edits detected"
      else
        note "${#DIVERGED_PATHS[@]} managed path(s) carry committed local edits"
      fi
    elif [[ -z "$snapshot_hash" ]]; then
      # Phase 99 clean-tree fallback (tester round): the OLD ancestor is
      # unreachable — the lock's sysop_commit isn't in $REPO_ROOT and can't be
      # fetched (e.g. it was force-pushed away, as in the tester snapshot-mirror
      # update flow, so a plain `git fetch` can't restore it). Without it we
      # can't 3-way-diff to detect COMMITTED local edits to in-scope scripts.
      # But the pre-update snapshot found NO dirty managed paths — the working
      # tree is clean w.r.t. every managed path — so there are no UNCOMMITTED
      # edits to preserve either, and the abort here made the documented update
      # flow unusable for a consumer who never touched a script. Proceed:
      # DIVERGED_PATHS stays empty and copy_file finds no ancestor file in the
      # (empty) shadow, so it overwrites normally — same effect as --force, but
      # snapshot-backed on the uncommitted axis. Warn about the one residual
      # case we cannot verify: a consumer who *committed* an edit to a managed
      # script would have it overwritten undetected.
      hdr "⚠  ancestor unreachable — committed-edit detection skipped"
      note "the lock's sysop_commit ${old_commit:0:12} can't be reached, so COMMITTED edits"
      note "to managed scripts can't be detected. The working tree is CLEAN for every managed"
      note "path (nothing uncommitted to preserve), so this update proceeds and overwrites"
      note "in-scope scripts from upstream."
      note "If you COMMITTED edits to sysop/scripts/*, they are overwritten here — recover them from"
      note "git history, or re-run after fetching the ancestor by SHA (host/GC permitting):"
      note "  git -C ${SYSOP_SRC_CLONE:-$REPO_ROOT} fetch origin $old_commit && bash sysop/scripts/sysop-update.sh"
    else
      # Phase 24b fail-closed: in --update without --force, abort if we can't
      # compute per-file ancestors for the in-scope preservation set AND the
      # working tree carries dirty managed paths (snapshot_hash set). Phase 8's
      # "warn and proceed" was the failure mode that motivated ISSUE-0024/0025 —
      # silent loss of customizations the consumer thought were safe. The escape
      # hatches are explicit: --force, per-file --accept-upstream, or fetching
      # the missing commit (by SHA) and retrying.
      err "Phase 24b requires a recoverable ancestor for sysop/scripts/* and sysop/scripts/hooks/* preservation."
      err "  reconstruct_old_install failed — see note: line above for the specific cause,"
      err "  and there are dirty managed paths in the working tree to preserve."
      err ""
      err "  Options:"
      err "    1. git -C ${SYSOP_SRC_CLONE:-$REPO_ROOT} fetch origin $old_commit && bash sysop/scripts/sysop-update.sh"
      err "       (fetch the lock's sysop_commit BY SHA — a plain 'git fetch' cannot restore"
      err "        a force-pushed commit; the by-SHA fetch is best-effort, working only while"
      err "        the host still serves the orphaned object. If it can't be fetched, use 2 or 3.)"
      err "    2. bash sysop/scripts/sysop-update.sh --force"
      err "       (skip preservation; overwrite all managed paths)"
      err "    3. bash sysop/scripts/sysop-update.sh --accept-upstream <relpath> [--accept-upstream ...]"
      err "       (acceptance-list per script; non-listed in-scope paths will still abort)"
      err ""
      err "  See WORKFLOW.md § 8.2c for the full preservation contract."
      exit 1
    fi

    report_pre_overwrite_divergence
  fi

  # Phase 128 (§5 steps 4–6): with divergence detected + reported on OLD paths,
  # move BOTH the working tree and the reconstructed shadow to the new layout,
  # then remap DIVERGED_PATHS and migrate the settings files. After this the
  # standard pipeline below runs layout-blind: copy_file's Phase-24b preservation
  # (keyed on the moved shadow ancestor) and the obsolete sweep both operate on
  # new-layout paths with zero special-casing. Ordering is load-bearing — the
  # remap runs AFTER report_pre_overwrite_divergence (which needs old spellings
  # for its `git show HEAD:<path>` hints) and BEFORE report_post_overwrite_deltas.
  if [[ "$MIGRATION_MODE" -eq 1 ]] && [[ "$DRY_RUN" -eq 0 ]]; then
    hdr "namespace migration (Phase 128)"
    note "moving ${#NS_MOVE_OLD[@]} vendor path(s) into sysop/"
    _ns_move_tree "$TARGET" git
    _ns_move_issues_log
    # Prune the now-empty old vendor dirs git mv leaves behind (scripts/,
    # scripts/hooks/, scripts/ci/, scripts/run_checks/). -empty protects any
    # consumer-owned files that were living alongside in scripts/.
    [[ -d "$TARGET/scripts" ]] && find "$TARGET/scripts" -depth -type d -empty -delete 2>/dev/null
    [[ -n "$DIVERGENCE_SHADOW" && -d "$DIVERGENCE_SHADOW" ]] && _ns_move_tree "$DIVERGENCE_SHADOW" plain
    _ns_remap_diverged_paths
    _ns_migrate_settings
  fi

  # Finding 2: normalize any --accept-upstream keys old→new so copy_file's new-spelled
  # preservation lookup matches a pre-migration consumer's flat-scripts/ path. Runs in
  # BOTH dry-run and apply (copy_file's preservation preview consults ACCEPT_UPSTREAM in
  # dry-run too), and independent of the tree-move above so it fires on every migration.
  [[ "$MIGRATION_MODE" -eq 1 ]] && _ns_remap_accept_upstream

  # Phase 133: consolidate the runtime dirs. Runs after the namespace move (a
  # pre-128 consumer gets both waves in one --update) and before the pipeline
  # (whose ensure_runtime_gitignore appends the new sysop/runtime/ entry).
  # Handles its own dry-run plan; no-op when nothing is pending.
  migrate_runtime_dirs

  # Execute install pipeline (populates MANAGED_PATHS; copy_file consumes
  # DIVERGENCE_SHADOW for Phase 24b per-file preservation).
  MANAGED_PATHS=()
  run_install_pipeline

  # Phase 13: seed SYSOP_ISSUES.md under sysop/ (Phase 128) on fresh install
  # only. Skip on --update / --adopt / --check (those modes don't reach here:
  # --check + --adopt return early above, and --update treats the friction log
  # as project-owned). Helper itself skips silently if the file exists.
  # Phase 123: in loop mode, SYSOP_ISSUES.md stays lazy (created by the first
  # friction capture, not at install — zero-root-footprint).
  # Phase 131 (round-4 cold read): seed_claude_md_stub now runs in BOTH modes —
  # the full-mode quickstart's `git add ... CLAUDE.md` hard-failed on bare repos
  # (exit 128, nothing staged), and the audit skills consume the same three
  # sections in full mode. The stub is section-level append-if-absent, so the
  # §6.1 bootstrap / /intake compose with it (their sections just append later).
  if [[ "$UPDATE_MODE" -eq 0 ]]; then
    seed_claude_md_stub
    [[ "$INSTALL_MODE" == "loop" ]] || seed_friction_log
  fi

  # Update mode: paths that Sysop used to manage but no longer does should
  # be removed from the consumer's working tree so the working set matches the
  # new lock. Skip settings.json (it's merge-preserved, never dropped).
  #
  # Phase 128 (§5 step 6): in migration mode the lock's spelling may be old OR new
  # (cmd_adopt writes current-pipeline locks), so "still managed" is decided by
  # normalizing each old-managed entry to its NEW spelling and testing membership
  # — a MOVED path normalizes into MANAGED_PATHS and is never deleted; only a
  # genuinely upstream-dropped file survives as a deletion. The on-disk spelling
  # is then resolved via the INVERSE map (never the forward one — that would
  # relocate onto a live moved file). The header is gated on a real on-disk hit,
  # not a non-empty candidate list (avoids announcing "obsolete files" when every
  # candidate was already moved/absent).
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    local omp still np norm ondisk alt d
    local -a to_remove=()
    for omp in "${old_managed[@]}"; do
      [[ "$omp" == ".claude/settings.json" ]] && continue
      # Defensive (adversarial review): never sweep consumer-owned files even if a
      # corrupted/hand-edited lock lists them — the backlog under tasks/, the
      # friction log, the review tracker, and the CLAUDE.md/.gitignore appends are
      # the consumer's, not Sysop's. Real locks never record these; this is a guard
      # against the blast radius, not a normal path.
      case "$omp" in
        tasks/*|CLAUDE.md|.gitignore|review_tasks.md|review_tasks_archive.md|SYSOP_ISSUES.md|sysop/SYSOP_ISSUES.md) continue ;;
      esac
      norm="$omp"
      [[ "$MIGRATION_MODE" -eq 1 ]] && norm="$(_ns_old_to_new "$omp")"
      still=0
      for np in "${MANAGED_PATHS[@]}"; do
        if [[ "$np" == "$norm" ]]; then still=1; break; fi
      done
      (( still == 1 )) && continue
      # Genuinely dropped — resolve the surviving on-disk spelling.
      # Phase 142: `-e` alone is false for a BROKEN symlink, which would strand a
      # managed Codex link whose target went away. `-e || -L` covers both. (The
      # migration-spelling probe below stays `-e`: it resolves an old/new rename,
      # never a link.)
      ondisk=""
      if [[ -e "$TARGET/$omp" || -L "$TARGET/$omp" ]]; then
        ondisk="$omp"
      elif [[ "$MIGRATION_MODE" -eq 1 ]]; then
        alt="$(_ns_new_to_old "$omp")"
        [[ "$alt" != "$omp" && -e "$TARGET/$alt" ]] && ondisk="$alt"
      fi
      if [[ -n "$ondisk" ]]; then
        # Phase 142: a lock-listed Codex link is swept only while it is still
        # OURS (raw target match — a broken link with our target still counts).
        # A consumer who repointed or replaced it owns that entry now: warn and
        # leave it rather than deleting their data on an opt-out or a drop.
        if _codex_link_not_ours "$ondisk"; then
          note "⚠ keep: $ondisk (no longer Sysop's link — yours to remove)"
        else
          to_remove+=("$ondisk")
        fi
      fi
    done
    NS_SWEPT_COUNT=${#to_remove[@]}
    if (( ${#to_remove[@]} > 0 )); then
      hdr "obsolete files"
      for d in "${to_remove[@]}"; do
        note "remove: $d"
        if [[ "$DRY_RUN" -eq 0 ]]; then
          git -C "$TARGET" rm -f --quiet -- "$d" 2>/dev/null \
            || rm -f -- "$TARGET/$d"
        fi
      done
    fi
  fi

  # Lock-file write.
  hdr "lock file"
  local now; now="$(iso_now)"
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    [[ -z "$installed_at" ]] && installed_at="$now"
    write_lock_file "$installed_at" "$now"
  else
    write_lock_file "$now" "$now"
  fi

  # Footer.
  hdr "summary"
  local item
  for item in "${PLAN_SUMMARY[@]}"; do
    note "$item"
  done

  # Update mode (Phase 8 + Phase 24b): per-file delta table after overwrite.
  # Always runs in --update (no preconditions); independent of pre-overwrite
  # detection so the agent still gets a signal when OLD-commit reconstruction
  # wasn't possible. Decision 11: also runs in --dry-run so the plan shows
  # would-be-preserved paths (numstat is empty in dry-run, so the standard
  # delta table self-suppresses; the preserved-paths block does fire).
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    report_post_overwrite_deltas
    [[ "$MIGRATION_MODE" -eq 1 ]] && _ns_migration_report
  fi

  # Phase 25 (BeanRider ISSUE-0026): post-run stale-substitution report.
  # Fires whenever .claude/substitutions.project.yml exists and any of its
  # keys didn't match any text in the regenerated concat files. Real-run
  # only — apply_substitutions doesn't fire in dry-run, so the tally would
  # be a false-positive "all stale" report (function self-guards on DRY_RUN).
  report_stale_substitutions

  if [[ "$DRY_RUN" -eq 1 ]]; then
    say ""
    say "Dry-run complete. Re-run without --dry-run to apply."
    return 0
  fi

  # Phase 15 / ISSUE-0007: armed-hook divergence check. Runs in all modes
  # (fresh install too — catches hand-edits of .git/hooks/). In --update mode,
  # arm_git_hooks deliberately skipped, so any consumer-customized sysop/scripts/hooks/
  # body that differs from the upstream-overwritten file will show up here.
  check_armed_hooks_divergence

  say ""
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    local new_commit; new_commit="$(get_sysop_commit)"
    say "Updated Sysop files in: $TARGET"
    # ISSUE-0047: only reachable under --force now (a no-anchor --update without
    # --force fails closed at lock load); label it instead of printing a blank
    # `was:` that reads as "nothing to report".
    if [[ -z "$old_commit" ]] || [[ "$old_commit" == "unknown" ]]; then
      say "  was:  (unknown — lock had no anchor)"
    else
      say "  was:  ${old_commit:0:12}"
    fi
    say "  now:  ${new_commit:0:12}"
    if [[ "$MIGRATION_MODE" -eq 1 ]]; then
      say ""
      say "▶ Namespace migration — commit this as ONE change, in this order:"
      note "1. stage everything (both sides of every move + the appends):"
      note "     git -C $TARGET add -A"
      note "2. re-arm hooks BEFORE committing — your old-path armed hook would otherwise"
      note "   fire on the migration commit and run checks over now-moved files:"
      note "     bash $TARGET/sysop/scripts/install_hooks.sh"
      note "3. commit (or bypass the still-stale hook once with --no-verify):"
      note "     git -C $TARGET commit -m 'chore(sysop): migrate to sysop/ vendor namespace'"
      note "Consumer files still naming old scripts/ paths were listed above — fix them by hand."
    fi
    say ""
    say "The update is uncommitted — review and commit intentionally."
    if (( ${#DIVERGED_PATHS[@]} > 0 )); then
      note "⚠  ${#DIVERGED_PATHS[@]} managed path(s) had committed local edits — see warning block above"
    fi
    if [[ -n "$snapshot_hash" ]]; then
      note "diff vs pre-update snapshot: git -C $TARGET diff ${snapshot_hash:0:12}..HEAD"
    fi
    note "see what changed: git -C $TARGET diff"
    note "self-check:       bash $TARGET/sysop/scripts/self_check.sh"
    note "smoke test:       bash $TARGET/sysop/scripts/run_checks.sh"
    note "re-arm git hooks after reconciling sysop/scripts/hooks/: bash $TARGET/sysop/scripts/install_hooks.sh"
  else
    say "Done. Wrote Sysop into: $TARGET"
    say ""
    say "Next steps:"
    note "cd $TARGET"
    if [[ "$ARM_HOOKS" -eq 0 ]]; then
      note "bash sysop/scripts/install_hooks.sh         # arm git hooks (--no-arm-hooks was set)"
    fi
    note "bash sysop/scripts/self_check.sh            # verify prereqs: bash, PyYAML, hooks (Phase 133)"
    note "bash sysop/scripts/run_checks.sh            # smoke-test the check registry"
    note "git status                            # review what landed"
    say ""
    # Phase 71/73/123: friction is densest at install / first round. Nudge
    # capture now, mode-aware — loop mode ships no WORKFLOW.md and keeps
    # SYSOP_ISSUES.md lazy, so it routes to the audit skills + a create-on-first
    # friction log instead.
    if [[ "$INSTALL_MODE" == "loop" ]]; then
      say "You're in loop mode — the convention loop only. Run a first round:"
      note "fill in the three scope sections seeded in CLAUDE.md (what to review / skip)"
      note "/codebase-review    # scan, promote surviving conventions, bootstrap review_tasks.md"
      note "/security-audit     # same rhythm, or before releases"
      say ""
      say "Hit Sysop friction? Log it in sysop/SYSOP_ISSUES.md (create it under sysop/);"
      note "/report-issues files the keepers upstream to Sysop"
    else
      say "See sysop/docs/WORKFLOW.md § 8.7 (Port checklist) for the bootstrap walkthrough."
      say ""
      say "Hit Sysop friction (install, permissions, first /intake)? Capture it while it's fresh:"
      note "log it in sysop/SYSOP_ISSUES.md; /report-issues files the keepers upstream to Sysop"
    fi
    say ""
    # Phase 34 / BeanRider ISSUE-0011: print the SYSOP_SRC export line at
    # install time so a fresh agent or contributor doesn't hit the shim's
    # precondition error without knowing where to set the env var.
    say "Future updates (one-line, from the consumer project root):"
    note "bash sysop/scripts/sysop-update.sh      # the recommended update entry point"
    say ""
    say "The shim requires \$SYSOP_SRC to point at this Sysop source clone."
    say "Add this line to your shell rc (~/.zshrc or ~/.bashrc) and re-source it:"
    # Under --ref, $REPO_ROOT is the ephemeral pin worktree (deleted on exit);
    # the consumer must point SYSOP_SRC at the real clone (SYSOP_SRC_CLONE).
    note "export SYSOP_SRC=\"${SYSOP_SRC_CLONE:-$REPO_ROOT}\""
    say ""
    say "Lower-level form (advanced escape hatch):"
    note "bash ${SYSOP_SRC_CLONE:-$REPO_ROOT}/install.sh $TARGET --update    # what the shim wraps"
  fi
}

main "$@"
