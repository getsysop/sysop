#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# install_hooks.sh — Copy tracked hook scripts into git's hooks directory
#
# Usage:
#   bash sysop/scripts/install_hooks.sh
#
# Run this after cloning, and after reconciling sysop/scripts/hooks/* following
# an `install.sh --update` (Phase 15 / ISSUE-0007 deliberately does not re-arm).
# A worktree does NOT need its own run — worktrees share one hooks directory,
# and arming from inside one writes that branch's templates into the shared
# directory, over the main checkout's armed hooks (Phase 150 / internal tracker #202).
# Skips entirely when core.hooksPath is configured: that directory is yours.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository." >&2
  exit 1
}

HOOKS_SRC="${REPO_ROOT}/sysop/scripts/hooks"

if [[ ! -d "$HOOKS_SRC" ]]; then
  echo "❌ No hooks found in sysop/scripts/hooks/." >&2
  exit 1
fi

# Where does git ACTUALLY look for hooks? `--git-path hooks` is the only
# resolution that honors core.hooksPath; `$(git rev-parse --git-common-dir)/hooks`
# (used here before Phase 150) does not, and would write into a .git/hooks that
# git never consults.
#
# `--git-path` returns a path relative to the CURRENT DIRECTORY, not to the
# toplevel — from `src/api/` it answers `../../.git/hooks`. Anchor the probe
# with `-C "$REPO_ROOT"` so the result is relative to the repo root and a run
# from a subdirectory cannot resolve outside the repo (or, in a repo nested
# inside another, into the OUTER repo's hooks). `install.sh:resolve_hook_dst`
# and `self_check.sh` both anchor the same way.
HOOKS_DST="$(git -C "$REPO_ROOT" rev-parse --git-path hooks 2>/dev/null)"
case "$HOOKS_DST" in
  /*) : ;;
  *)  HOOKS_DST="${REPO_ROOT}/${HOOKS_DST}" ;;
esac

# If core.hooksPath is configured, git ignores .git/hooks/ entirely and that
# directory is the consumer's. Skip, and say so. Skipped-not-failed — exit 0,
# so callers don't report a phantom install error.
#
# Guard on the key being SET, not on a non-empty value: `core.hooksPath = ""`
# makes git run no hooks at all, while `--git-path hooks` resolves it to `./` —
# so a `-n` test would fall through and drop three executables into the root of
# the consumer's working tree while reporting success.
if HOOKS_PATH_CFG="$(git -C "$REPO_ROOT" config --get core.hooksPath 2>/dev/null)"; then
  # Scope matters for the advice, not the decision. A local/worktree value
  # points at a directory in this repo (usually tracked — the reason to set it),
  # so offering the copy is right. A global/system value points at a shared
  # per-machine directory, where copying THIS project's checks would apply them
  # to every repo on the machine and a second project would silently overwrite
  # the first — so name the scope and offer nothing.
  HOOKS_PATH_SCOPE="$(git -C "$REPO_ROOT" config --get --show-scope core.hooksPath 2>/dev/null \
                      | awk 'NR==1 {print $1}' || true)"
  if [[ -n "$HOOKS_PATH_CFG" ]]; then
    echo "ℹ️  core.hooksPath is set to '${HOOKS_PATH_CFG}' — git reads hooks from"
    echo "   ${HOOKS_DST}, not .git/hooks/."
  else
    echo "ℹ️  core.hooksPath is set to the empty string — git runs NO hooks at all."
  fi
  case "$HOOKS_PATH_SCOPE" in
    global|system)
      echo "   That is a ${HOOKS_PATH_SCOPE} setting, shared by every repo on this machine."
      echo "   Sysop will not write there — its hook templates are per-project, so"
      echo "   copying them into a shared directory would apply this project's checks"
      echo "   everywhere. Unset it, or set a repo-local path:"
      echo "     git -C \"${REPO_ROOT}\" config core.hooksPath <dir-in-this-repo>"
      ;;
    *)
      echo "   Sysop will not write there: that directory is yours to manage."
      if [[ -n "$HOOKS_PATH_CFG" ]]; then
        echo "   To adopt Sysop's templates into it, copy them yourself:"
        echo "     mkdir -p \"${HOOKS_DST}\" && cp \"${HOOKS_SRC}\"/* \"${HOOKS_DST}\"/ && chmod +x \"${HOOKS_DST}\"/*"
      fi
      ;;
  esac
  exit 0
fi

INSTALLED=0
BACKED_UP=()
UNMANAGED=()
# Explicit allowlist: only these tracked filenames are ever copied into
# .git/hooks/ so stray files (.DS_Store, *.swp, README.md, accidentally
# pasted hook files) cannot get installed and executed on git events.
TMP=""
trap 'rm -f -- "${TMP:-}"' EXIT
for BASENAME in pre-commit pre-merge-commit pre-push; do
  HOOK="${HOOKS_SRC}/${BASENAME}"
  DST="${HOOKS_DST}/${BASENAME}"
  if [[ ! -f "$HOOK" ]]; then
    # Sysop ships pre-commit and pre-merge-commit; `pre-push` is in the allowlist
    # so a later release can add one without touching this loop. Until then the
    # bare `continue` this replaces made an ARMED consumer hook of that name
    # indistinguishable from no hook at all — the script reported "2 hook(s)
    # installed" and said nothing about the third, which is how a consumer comes
    # to believe every hook they run is Sysop-managed (`Q-541` leg 1).
    #
    # Sysop does not arm it. There is no documented consumer hooks directory to
    # arm FROM, and the one candidate — `scripts/hooks/` — is where Sysop's own
    # hooks lived before the Phase 128 vendor move, so reading it would risk
    # pushing a stale pre-migration template over the migrated one. That is the
    # same failure `self_check.sh` now detects, and installing it here would be
    # this script causing it.
    # `-e` alone is false for a BROKEN symlink, which is exactly the armed-but-dead
    # case this arm exists to surface — the same `-e || -L` correction Phase 142 made
    # to the obsolete-file sweep. A directory at that path is excluded: git will not
    # run it, so calling it an armed hook would be false.
    if [[ ( -e "$DST" || -L "$DST" ) && ! -d "$DST" ]]; then
      UNMANAGED+=("$BASENAME")
    fi
    continue
  fi

  # Back up any pre-existing hook that differs from the tracked version
  # so user customizations are not silently clobbered.
  if [[ -f "$DST" ]] && ! cmp -s "$HOOK" "$DST"; then
    TS=$(date -u +"%Y%m%dT%H%M%SZ")
    BACKUP="${DST}.bak.${TS}"
    cp "$DST" "$BACKUP"
    BACKED_UP+=("${BASENAME} → $(basename "$BACKUP")")
  fi

  # Atomic install: write beside the destination and mv into place so a
  # partial copy never leaves a half-written executable (the same convention
  # as the trackers' writers, CLAUDE.md § Data integrity). The name carries
  # `$$`, this shell's PID, rather than coming from `mktemp` — the device
  # `batch_work.sh` uses, on the same premise: `mktemp` creates 0600, and
  # `chmod +x` on that yields a 0711 hook under the usual umask (0700 under
  # 077) — unreadable to group and others either way — where `cp` carries the
  # source's mode under the umask and `chmod +x` lands on 0755. The PID makes
  # the name unique per process, which a
  # fixed `<hook>.tmp` was not (`Q-448`). The EXIT trap set before the loop
  # removes an in-flight copy if a step fails under `set -e`; after `mv` the
  # path no longer exists and `rm -f` is a no-op.
  TMP="${DST}.$$.tmp"
  cp "$HOOK" "$TMP"
  chmod +x "$TMP"
  mv "$TMP" "$DST"
  echo "✅ Installed: ${BASENAME}"
  INSTALLED=$((INSTALLED + 1))
done

echo ""
echo "Done. ${INSTALLED} hook(s) installed to ${HOOKS_DST}/"
if [[ ${#BACKED_UP[@]} -gt 0 ]]; then
  echo ""
  echo "⚠️  Backed up pre-existing customized hooks:"
  for BACKUP_NOTE in "${BACKED_UP[@]}"; do
    echo "   • ${BACKUP_NOTE}"
  done
fi
if [[ ${#UNMANAGED[@]} -gt 0 ]]; then
  echo ""
  echo "ℹ️  Armed here, but not Sysop's — no template in sysop/scripts/hooks/:"
  for UNMANAGED_NOTE in "${UNMANAGED[@]}"; do
    echo "   • ${UNMANAGED_NOTE}  (yours: Sysop neither installs nor updates it)"
  done
fi
