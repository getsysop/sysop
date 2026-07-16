#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Sysop installer
#
# Installs the Sysop workflow (core + selected packs) into a
# target project. Companion content (docs, scripts, git hooks,
# convention maps, security maps, checks registry, semgrep rules)
# lands under <target>/.claude/, <target>/scripts/, and
# <target>/scripts/hooks/ per WORKFLOW.md § 8.
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
# Phase 111: --ref pins the install/update source to a git tag/rev (a reviewed
# release) instead of the source clone's live HEAD. REF_WORKTREE holds the
# materialised-rev worktree; SYSOP_SRC_CLONE holds the original clone (needed to
# remove that worktree on exit, since a worktree can't cleanly remove itself).
REF_OVERRIDE=""
REF_WORKTREE=""
SYSOP_SRC_CLONE=""

# Location of the install manifest, relative to <target>.
LOCK_REL=".claude/sysop.lock"
LOCK_VERSION=1

# Populated by copy_file / concat_files / install_permissions during install.
# Paths are stored relative to <target>. Drives lock-file `managed_paths` and
# the --update mode's snapshot + deletion logic.
MANAGED_PATHS=()

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
  --dry-run             Print planned operations without writing.
  --force               Fresh install: allow uncommitted changes in the target tree.
                        --update: skip the pre-update snapshot step (overwrite directly).
  --no-arm-hooks        Don't copy hook templates into .git/hooks/. (Templates still land
                        in <target>/scripts/hooks/; run scripts/install_hooks.sh later.)
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
                        Out-of-scope paths (not under scripts/* or scripts/hooks/*)
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

  # Update an existing install to this checkout's version:
  bash install.sh ~/Projects/myapp --update
  # Pin a fresh install (or update) to a reviewed release tag instead of HEAD:
  bash install.sh ~/Projects/myapp --packs python --ref v0.1.0
  bash install.sh ~/Projects/myapp --update --ref v0.1.0
  # Adopt update tracking for a pre-Phase-7 install:
  bash install.sh ~/Projects/myapp --adopt --packs python,postgres
  # Preview pending upstream changes (read-only):
  bash install.sh ~/Projects/myapp --check --source ~/Projects/sysop

After install:
  cd <target>
  bash scripts/install_hooks.sh        # arm git hooks (skipped if --no-arm-hooks)
  bash scripts/run_checks.sh           # smoke-test the check registry
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
    -y|--yes)      ASSUME_YES=1; shift ;;
    --packs)       PACKS_ARG="${2:-}"; PACKS_PROVIDED=1; shift 2 ;;
    --packs=*)     PACKS_ARG="${1#--packs=}"; PACKS_PROVIDED=1; shift ;;
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

# ─── helpers ──────────────────────────────────────────────────
say()  { printf '%s\n' "$*"; }
note() { printf '  • %s\n' "$*"; }
err()  { printf '❌ %s\n' "$*" >&2; }
hdr()  { printf '\n── %s ──\n' "$*"; }

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
# the absolute target path falls under scripts/<file> (depth-1) or
# scripts/hooks/<file> (depth-2). Skills, workflow docs, semgrep rules, and
# tasks-scaffold templates are explicitly OUT of scope so that hand-edits to
# those paths still get overwritten by the standard pipeline (a silent prompt-
# fork channel for skills would accumulate divergence from upstream
# improvements indefinitely — see WORKFLOW.md § 8.2c). Concat targets are also
# out of scope because Phase 24a's suffix-file mechanism is the right shape
# for them; preserving them would freeze the file at its last consumer state
# and silently drop upstream improvements.
#
# Cases (one per line, in-scope vs out-of-scope):
#   scripts/foo.py            → in     (depth-1 file under scripts/)
#   scripts/hooks/pre-commit  → in     (depth-2 file under scripts/hooks/)
#   scripts/foo/bar.py        → out    (depth-2 not under hooks/)
#   scripts/hooks/sub/bar     → out    (depth-3 under hooks/)
#   .claude/skills/X/SKILL.md → out
#   WORKFLOW.md               → out
_phase_24b_in_scope() {
  local relp="${1#"$TARGET"/}"
  # scripts/<file> at depth 1 — must contain no further `/`.
  if [[ "$relp" == scripts/* ]] && [[ "$relp" != scripts/*/* ]]; then return 0; fi
  # scripts/hooks/<file> at depth 2 — must contain exactly one `/` after `scripts/hooks/`.
  if [[ "$relp" == scripts/hooks/* ]] && [[ "$relp" != scripts/hooks/*/* ]]; then return 0; fi
  return 1
}

copy_file() {
  local src="$1" dst="$2"
  ensure_dir "$(dirname "$dst")"

  # Phase 24b: preserve consumer-modified managed paths (scoped to scripts/*
  # and scripts/hooks/*). Out-of-scope paths take the standard overwrite.
  # Short-circuits unless: --update mode, shadow tree available, target file
  # exists, scope filter says yes, and target differs from the ancestor.
  if [[ "$UPDATE_MODE" -eq 1 ]] && [[ -n "$DIVERGENCE_SHADOW" ]] \
     && [[ -f "$dst" ]] && _phase_24b_in_scope "$dst"; then
    local _relp="${dst#"$TARGET"/}"
    local _ancestor="$DIVERGENCE_SHADOW/$_relp"
    if [[ -f "$_ancestor" ]] && ! cmp -s "$_ancestor" "$dst"; then
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

  SYSOP_LOCK_PATH="$lock_path" \
  SYSOP_LOCK_VERSION="$LOCK_VERSION" \
  SYSOP_COMMIT="$commit" \
  SYSOP_PACKS="$packs_csv" \
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

  local -a paths=()
  local mp
  for mp in "${MANAGED_PATHS[@]}"; do
    [[ "$mp" == ".claude/settings.json" ]] && continue
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
  copy_file "$REPO_ROOT/core/companion/docs/WORKFLOW.md"       "$TARGET/WORKFLOW.md"
  copy_file "$REPO_ROOT/core/companion/docs/WORKFLOW_GUIDE.md" "$TARGET/WORKFLOW_GUIDE.md"
  record "workflow docs: WORKFLOW.md, WORKFLOW_GUIDE.md"
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
    local f
    for f in "$d"*; do
      [[ -f "$f" ]] || continue
      copy_file "$f" "$dst/$name/$(basename "$f")"
    done
    skill_count=$((skill_count + 1))
  done
  record "skills: $skill_count skill dir(s) copied to .claude/skills/"
}

install_companion_scripts() {
  hdr "companion scripts"
  local dst="$TARGET/scripts"
  ensure_dir "$dst"
  local copied=0
  local f
  for f in "$REPO_ROOT/core/companion/scripts"/*; do
    if [[ -f "$f" ]]; then
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
  record "scripts: $copied file(s) copied to scripts/"
}

install_git_hooks() {
  hdr "git hooks (templates)"
  local dst="$TARGET/scripts/hooks"
  ensure_dir "$dst"
  local copied=0
  local f
  for f in "$REPO_ROOT/core/companion/git-hooks"/*; do
    [[ -f "$f" ]] || continue
    copy_file "$f" "$dst/$(basename "$f")"
    copied=$((copied + 1))
  done
  if [[ "$ARM_HOOKS" -eq 1 ]] && [[ "$UPDATE_MODE" -eq 0 ]]; then
    record "git hooks: $copied template(s) copied to scripts/hooks/ (will be armed at end of install)"
  else
    record "git hooks: $copied template(s) copied to scripts/hooks/ (use scripts/install_hooks.sh to arm)"
  fi
}

install_ci_template() {
  hdr "CI template"
  local dst="$TARGET/scripts/ci"
  ensure_dir "$dst"
  local copied=0
  local f
  # Unarmed reference file(s) — the `.example` suffix keeps GitHub from running
  # it. The consumer copies it into .github/workflows/ and marks it a required
  # check (WORKFLOW.md § Merge policy). Shipped like the git-hook templates:
  # delivered to the consumer's tree, but not activated. The consumer's live
  # copy lives in .github/workflows/ (fully unmanaged); this .example is a pure
  # upstream reference, so it refreshes on --update by design (unlike the
  # preserve-consumer-edits scope that covers scripts/ + scripts/hooks/).
  for f in "$REPO_ROOT/core/companion/ci"/*; do
    [[ -f "$f" ]] || continue
    copy_file "$f" "$dst/$(basename "$f")"
    copied=$((copied + 1))
  done
  record "CI template: $copied file(s) copied to scripts/ci/ (unarmed — copy to .github/workflows/ to enable; see WORKFLOW.md § Merge policy)"
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
  # pipeline has just overwritten scripts/hooks/* with upstream content; arming
  # now would silently swap the consumer's previously-armed (possibly custom)
  # hook body for the upstream skeleton during the reconcile window. The
  # consumer reconciles scripts/hooks/* via git first, then re-arms explicitly
  # via scripts/install_hooks.sh. The post-install armed-hook divergence check
  # below (check_armed_hooks_divergence) surfaces any residual mismatch so the
  # re-arm need is loud, not silent.
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    hdr "arm git hooks"
    note "skipped in --update mode (ISSUE-0007): reconcile scripts/hooks/ first, then run scripts/install_hooks.sh"
    record "git hooks: auto-arm skipped (--update mode); use scripts/install_hooks.sh after reconciling scripts/hooks/"
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
  for f in "$TARGET/scripts/hooks"/*; do
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
# mode) the consumer's reconcile window, compare every scripts/hooks/<base>
# against .git/hooks/<base>. Differences mean the armed hook body is stale —
# either because --update intentionally skipped auto-arm (so the consumer must
# re-arm after reconciling), or because someone hand-edited .git/hooks/ out of
# band. Read-only signal; never modifies hooks. Skipped silently in dry-run.
check_armed_hooks_divergence() {
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  local hooks_src="$TARGET/scripts/hooks"
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
    say "  ⚠ scripts/hooks/<base> differs from $(rel "$hook_dst")/<base>:"
    for b in "${diverged[@]}"; do
      say "      - $b"
    done
  fi
  if (( ${#missing[@]} > 0 )); then
    say "  ⚠ scripts/hooks/<base> present but not armed in $(rel "$hook_dst")/:"
    for b in "${missing[@]}"; do
      say "      - $b"
    done
  fi
  say ""
  say "  Why this matters: .git/hooks/ is not tracked by git, so a stale armed"
  say "  body fires (or doesn't) on the next commit with no diff to inspect."
  say ""
  say "  To re-arm after reconciling scripts/hooks/: bash $(rel "$TARGET")/scripts/install_hooks.sh"
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

install_permissions() {
  hdr "permissions (.claude/settings.json)"
  local src="$REPO_ROOT/core/companion/.claude/settings.json"
  local dst="$TARGET/.claude/settings.json"
  if [[ ! -f "$src" ]]; then
    note "skipping: template not found at $(rel "$src")"
    return 0
  fi
  ensure_dir "$(dirname "$dst")"

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
  local script="$TARGET/scripts/resolve_skill_models.py"
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
# Seed <target>/SYSOP_ISSUES.md on fresh install only. The file lives
# at repo root (not under .claude/) and is intentionally NOT recorded in
# MANAGED_PATHS — that non-management is the property that protects it
# from --update overwriting (Phase 8's overwrite gap can't touch what
# isn't tracked). If the file already exists, skip silently — consumers
# who hand-rolled one before Phase 13 shipped (BeanRider did) keep their
# version intact even on re-install.
seed_friction_log() {
  hdr "friction log"
  local dst="$TARGET/SYSOP_ISSUES.md"
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
# Ensure the consumer .gitignore ignores Sysop's runtime-artifact dirs
# (Phase 99, tester round). These hold transient orchestration state that a stray
# `git add -A` would otherwise commit into project history:
#   .subagent-envelopes/  in-flight SubagentStop envelope JSON (Phase 37)
#   .auto-build/          parked-task plan + adversarial-verdict archive (Phase 65a)
#   .pending-docs/        deferred documentation drafts (/document-work Step 3)
#   .locks/               in-progress task locks (claim_task.sh; Phase 32)
# The set must stay complete: /review-close Step 2a derives its `dirty` verdict
# from `git status --porcelain`, so an un-ignored `.locks/<TASK>.lock` or
# `.pending-docs/<branch>.md` makes a clean branch read dirty → auto-SKIP → the
# close silently refuses (Phase 99.1 / tester issue #10). A drift-guard test
# (tests/test_install_runtime_gitignore.py) greps the skills for every dir they
# assert is gitignored and fails if this list doesn't cover it.
# Idempotent + update-safe: append-only, one full-line entry each, skip any
# already present. .gitignore is CONSUMER-OWNED, so we NEVER rewrite existing
# entries — only append missing ones. Runs on fresh install AND --update, so a
# .gitignore that pre-dates the install (or was hand-edited later) still gets
# the guarantee. (The old fresh-install-only append this replaces never existed
# — the dangling reference in parse_subagent_envelope.py is corrected there.)
ensure_runtime_gitignore() {
  hdr "runtime-artifact gitignore"
  local gi="$TARGET/.gitignore"
  local -a want=(".subagent-envelopes/" ".auto-build/" ".pending-docs/" ".locks/")
  local -a missing=()
  local entry
  for entry in "${want[@]}"; do
    if [[ -f "$gi" ]] && grep -qxF "$entry" "$gi" 2>/dev/null; then
      continue
    fi
    missing+=("$entry")
  done
  if (( ${#missing[@]} == 0 )); then
    note "already ignored: .subagent-envelopes/, .auto-build/, .pending-docs/, .locks/"
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
# Validator:       scripts/validate_tasks.py
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
  install_workflow_docs
  install_skills
  install_companion_scripts
  install_git_hooks
  install_ci_template
  install_convention_map
  install_security_map
  install_checks_yml
  install_semgrep
  install_tasks_scaffold
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
  if [[ -f "$lock_path" ]]; then
    err "Lock already exists at $(rel "$lock_path"). Use --update for upgrades."
    exit 1
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
    say ""
    say "Which packs were originally installed? (will be recorded in the lock for"
    say "future --update runs to know what fragments to re-merge)"
    packs_input="$(prompt_packs)"
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
  fi

  # Packs (from --packs, lock-derived above, or interactive). PACKS_PROVIDED
  # gates the picker so an explicit `--packs ''` (or a `--packs auto` that
  # detected nothing) installs core only instead of silently prompting.
  local packs_input="$PACKS_ARG"
  if [[ -z "$packs_input" ]] && [[ "$PACKS_PROVIDED" -eq 0 ]] && [[ "$UPDATE_MODE" -eq 0 ]]; then
    packs_input="$(prompt_packs)"
  fi
  resolve_selected_packs "$packs_input"

  # Plan summary.
  hdr "plan"
  say "  target:  $TARGET"
  if (( ${#SELECTED_PACKS[@]} > 0 )); then
    say "  packs:   ${SELECTED_PACKS[*]}"
  else
    say "  packs:   (core only)"
  fi
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    say "  mode:    update (was at ${old_commit:0:12})"
  else
    say "  mode:    $([[ "$DRY_RUN" -eq 1 ]] && echo "dry-run" || echo "apply")"
  fi

  if [[ "$DRY_RUN" -eq 0 ]]; then
    if ! confirm "Proceed?"; then
      say "Aborted."
      exit 0
    fi
  fi

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
  # for scripts/* and scripts/hooks/*). --force skips both steps (same
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
      detect_committed_divergence "$DIVERGENCE_SHADOW" "${old_managed[@]}"
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
      note "If you COMMITTED edits to scripts/*, they are overwritten here — recover them from"
      note "git history, or re-run after fetching the ancestor by SHA (host/GC permitting):"
      note "  git -C ${SYSOP_SRC_CLONE:-$REPO_ROOT} fetch origin $old_commit && bash scripts/sysop-update.sh"
    else
      # Phase 24b fail-closed: in --update without --force, abort if we can't
      # compute per-file ancestors for the in-scope preservation set AND the
      # working tree carries dirty managed paths (snapshot_hash set). Phase 8's
      # "warn and proceed" was the failure mode that motivated ISSUE-0024/0025 —
      # silent loss of customizations the consumer thought were safe. The escape
      # hatches are explicit: --force, per-file --accept-upstream, or fetching
      # the missing commit (by SHA) and retrying.
      err "Phase 24b requires a recoverable ancestor for scripts/* and scripts/hooks/* preservation."
      err "  reconstruct_old_install failed — see note: line above for the specific cause,"
      err "  and there are dirty managed paths in the working tree to preserve."
      err ""
      err "  Options:"
      err "    1. git -C ${SYSOP_SRC_CLONE:-$REPO_ROOT} fetch origin $old_commit && bash scripts/sysop-update.sh"
      err "       (fetch the lock's sysop_commit BY SHA — a plain 'git fetch' cannot restore"
      err "        a force-pushed commit; the by-SHA fetch is best-effort, working only while"
      err "        the host still serves the orphaned object. If it can't be fetched, use 2 or 3.)"
      err "    2. bash scripts/sysop-update.sh --force"
      err "       (skip preservation; overwrite all managed paths)"
      err "    3. bash scripts/sysop-update.sh --accept-upstream <relpath> [--accept-upstream ...]"
      err "       (acceptance-list per script; non-listed in-scope paths will still abort)"
      err ""
      err "  See WORKFLOW.md § 8.2c for the full preservation contract."
      exit 1
    fi

    report_pre_overwrite_divergence
  fi

  # Execute install pipeline (populates MANAGED_PATHS; copy_file consumes
  # DIVERGENCE_SHADOW for Phase 24b per-file preservation).
  MANAGED_PATHS=()
  run_install_pipeline

  # Phase 13: seed SYSOP_ISSUES.md at consumer-repo root on fresh install
  # only. Skip on --update / --adopt / --check (those modes don't reach here:
  # --check + --adopt return early above, and --update treats the friction log
  # as project-owned). Helper itself skips silently if the file exists.
  if [[ "$UPDATE_MODE" -eq 0 ]]; then
    seed_friction_log
  fi

  # Update mode: paths that Sysop used to manage but no longer does should
  # be removed from the consumer's working tree so the working set matches the
  # new lock. Skip settings.json (it's merge-preserved, never dropped).
  local -a deletions=()
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    local omp still=0 np
    for omp in "${old_managed[@]}"; do
      [[ "$omp" == ".claude/settings.json" ]] && continue
      still=0
      for np in "${MANAGED_PATHS[@]}"; do
        if [[ "$np" == "$omp" ]]; then still=1; break; fi
      done
      (( still == 0 )) && deletions+=("$omp")
    done
    if (( ${#deletions[@]} > 0 )); then
      hdr "obsolete files"
      local d
      for d in "${deletions[@]}"; do
        if [[ -e "$TARGET/$d" ]]; then
          note "remove: $d"
          if [[ "$DRY_RUN" -eq 0 ]]; then
            git -C "$TARGET" rm -f --quiet -- "$d" 2>/dev/null \
              || rm -f -- "$TARGET/$d"
          fi
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
  # arm_git_hooks deliberately skipped, so any consumer-customized scripts/hooks/
  # body that differs from the upstream-overwritten file will show up here.
  check_armed_hooks_divergence

  say ""
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    local new_commit; new_commit="$(get_sysop_commit)"
    say "Updated Sysop files in: $TARGET"
    say "  was:  ${old_commit:0:12}"
    say "  now:  ${new_commit:0:12}"
    say ""
    say "The update is uncommitted — review and commit intentionally."
    if (( ${#DIVERGED_PATHS[@]} > 0 )); then
      note "⚠  ${#DIVERGED_PATHS[@]} managed path(s) had committed local edits — see warning block above"
    fi
    if [[ -n "$snapshot_hash" ]]; then
      note "diff vs pre-update snapshot: git -C $TARGET diff ${snapshot_hash:0:12}..HEAD"
    fi
    note "see what changed: git -C $TARGET diff"
    note "smoke test:       bash $TARGET/scripts/run_checks.sh"
    note "re-arm git hooks after reconciling scripts/hooks/: bash $TARGET/scripts/install_hooks.sh"
  else
    say "Done. Wrote Sysop into: $TARGET"
    say ""
    say "Next steps:"
    note "cd $TARGET"
    if [[ "$ARM_HOOKS" -eq 0 ]]; then
      note "bash scripts/install_hooks.sh         # arm git hooks (--no-arm-hooks was set)"
    fi
    note "bash scripts/run_checks.sh            # smoke-test the check registry"
    note "git status                            # review what landed"
    say ""
    say "See WORKFLOW.md § 8.7 (Port checklist) for the bootstrap walkthrough."
    say ""
    # Phase 71/73: friction is densest at install / first /intake — before any
    # /review-close cycle (Step 7) exists to prompt for it. Nudge capture now,
    # while it's fresh, so testers' earliest friction reaches the log.
    say "Hit Sysop friction (install, permissions, first /intake)? Capture it while it's fresh:"
    note "log it in SYSOP_ISSUES.md (repo root); /report-issues files the keepers upstream to Sysop"
    say ""
    # Phase 34 / BeanRider ISSUE-0011: print the SYSOP_SRC export line at
    # install time so a fresh agent or contributor doesn't hit the shim's
    # precondition error without knowing where to set the env var.
    say "Future updates (one-line, from the consumer project root):"
    note "bash scripts/sysop-update.sh      # the recommended update entry point"
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
