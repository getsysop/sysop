#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# sysop-update.sh — project-root shim around `install.sh --update`.
#
# One command, no path arguments. Resolves:
#   - consumer root via `git rev-parse --show-toplevel`
#   - Sysop source via $SYSOP_SRC (set once in shell rc)
# then exec's `bash "$SYSOP_SRC/install.sh" "<consumer-root>" --update "$@"`.
# All flags are forwarded verbatim (`--force`, `--packs`, `--dry-run`,
# `--yes`, `--no-arm-hooks`, `--ref <tag>`, …). The exec means install.sh's
# exit code propagates to the caller; the Phase 7/8 safety net (snapshot
# commit + pre/post-overwrite divergence checks + delta table) runs unchanged.
#
# To pin an update to a reviewed release instead of the source clone's HEAD:
#   bash sysop/scripts/sysop-update.sh --ref v0.1.0
# (the tag must exist in your $SYSOP_SRC clone — release tags:
#  git -C "$SYSOP_SRC" fetch --tags). Omit --ref to track HEAD (the default).
#
# See WORKFLOW.md § 8.2b for the upgrade-flow contract.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# (1) Sysop source must be set and valid.
#     $SYSOP_SRC names the path to your local **Sysop source clone**
#     (NOT the consumer project that has Sysop installed). The Sysop
#     installer prints the exact `export SYSOP_SRC=...` line for your
#     machine at the end of the fresh-install footer (Phase 34 / ISSUE-0011);
#     re-run `bash <sysop-clone>/install.sh --help` if you missed it.
if [[ -z "${SYSOP_SRC:-}" ]]; then
  echo "❌ SYSOP_SRC is not set." >&2
  echo "   It must name your local Sysop source clone (absolute path)." >&2
  echo "   Add this to your shell rc (~/.zshrc or ~/.bashrc) and re-source:" >&2
  echo "     export SYSOP_SRC=/absolute/path/to/sysop" >&2
  echo "   (Bash does not expand a literal '~' inside env-var values;" >&2
  echo "    use an absolute path.)" >&2
  echo "   If you don't have Sysop cloned yet, see the Sysop README 'Quickstart'." >&2
  exit 1
fi

if [[ ! -d "$SYSOP_SRC" ]]; then
  echo "❌ SYSOP_SRC=$SYSOP_SRC: directory not found." >&2
  echo "   This should point at your local Sysop source clone." >&2
  echo "   Verify the path and re-export." >&2
  exit 1
fi

if [[ ! -f "$SYSOP_SRC/install.sh" ]]; then
  echo "❌ SYSOP_SRC=$SYSOP_SRC: no install.sh found at $SYSOP_SRC/install.sh." >&2
  echo "   This should point at the root of your Sysop source clone" >&2
  echo "   (the directory containing install.sh, not the consumer project)." >&2
  exit 1
fi

# install.sh --update needs to resolve sysop_commit via `git rev-parse`
# in $SYSOP_SRC, so the source must be a git working tree (not just a
# directory containing install.sh — e.g. an unpacked tarball won't work).
if ! git -C "$SYSOP_SRC" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "❌ SYSOP_SRC=$SYSOP_SRC: not a git working tree." >&2
  echo "   --update needs to resolve the upstream commit hash via git." >&2
  echo "   Point SYSOP_SRC at a clone of Sysop, not an extracted archive." >&2
  exit 1
fi

# (2) Consumer root = git toplevel of CWD.
# Let git print its own error to stderr (fatal: not a git repository …),
# then add a hint so the caller knows where to cd to.
if ! consumer_root="$(git rev-parse --show-toplevel)"; then
  echo "Hint: run this script from inside a git repo's working tree" >&2
  echo "      (the consumer project that has Sysop installed)." >&2
  exit 1
fi

# (2b) T6 (Phase 128): refuse to run a Sysop source clone that predates the
# sysop/ vendor namespace. An old installer reinstalls flat scripts/ with no
# preservation and `git rm`s every sysop/* path — silently reverting a migrated
# consumer (T1's data-loss class, in reverse). Detect via a marker only the
# post-namespace installer carries; a fresh consumer (no migration yet) is
# unaffected because that installer will simply migrate them.
if ! grep -q 'sysop/scripts' "$SYSOP_SRC/install.sh" 2>/dev/null; then
  echo "❌ Your Sysop source clone predates the sysop/ vendor namespace (Phase 128)." >&2
  echo "   Updating from it would revert your layout and delete migrated files." >&2
  echo "   Pull your Sysop source clone first, then re-run this update:" >&2
  echo "     git -C \"$SYSOP_SRC\" pull" >&2
  exit 1
fi

# (3) One-line scope note so users know the plugin path is its own update channel.
echo "Plugin path auto-updates at session start if marketplace auto-update is enabled."
echo "This script syncs bash-installer-delivered content only."
echo

# (4) Hand off. exec so install.sh's exit code is ours; "$@" preserves quoting.
exec bash "$SYSOP_SRC/install.sh" "$consumer_root" --update "$@"
