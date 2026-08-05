#!/usr/bin/env bash
# self_check.sh — one-command post-install health check (Phase 133).
#
# Usage:  bash sysop/scripts/self_check.sh
#
# Verifies the environment a fresh Sysop install depends on and reports one
# line per probe (round-4 cold-read request: bash version + PyYAML + hooks in
# a single command instead of discovery-by-failure):
#   1. git repo + install lock (.claude/sysop.lock) + install mode
#   2. bash version (3.2+ supported; 4+ reported)
#   3. a python3 that can `import yaml` (the validator / checks dependency),
#      probed in the installer's own order: .venv → venv → PATH
#   4. git hooks armed (pre-commit / pre-merge-commit present + executable)
#   5. optional scanners (semgrep, pip-audit, pyright) — advisory only
#   6. review-round evidence (Phase 143): stale pending markers + asymmetric
#      round history — the outer half of the refusal/abandonment check, which
#      must live outside the round to see a round that never started
#
# Exit 0 when every hard prereq passes (1–3; hooks and scanners are reported
# but never fail the check — loop-mode consumers may run checks via CI only).
# Probe 6 splits: a STALE MARKER fails the check (a round demonstrably started
# and never finished — unambiguous), while an ASYMMETRIC round history is
# advisory only (indistinguishable from "hasn't been run here yet").
set -uo pipefail

PASS=0
FAIL=0

ok()   { printf '  ✓ %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '  ✗ %s\n' "$1"; FAIL=$((FAIL + 1)); }
info() { printf '  · %s\n' "$1"; }

printf 'Sysop self-check\n\n'

# ── 1. repo + lock ──────────────────────────────────────────────────────────
if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  ok "git repository: $REPO_ROOT"
else
  bad "not inside a git repository — run from your project root"
  printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
  exit 1
fi

LOCK="$REPO_ROOT/.claude/sysop.lock"
if [[ -f "$LOCK" ]]; then
  MODE="$(sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$LOCK" | head -1)"
  ok "install lock present (mode: ${MODE:-unknown})"
else
  bad "no .claude/sysop.lock — is Sysop installed here? (bash install.sh <target>)"
fi

# ── 2. bash ─────────────────────────────────────────────────────────────────
if [[ "${BASH_VERSINFO[0]:-0}" -ge 4 ]]; then
  ok "bash ${BASH_VERSION}"
elif [[ "${BASH_VERSINFO[0]:-0}" -eq 3 && "${BASH_VERSINFO[1]:-0}" -ge 2 ]]; then
  ok "bash ${BASH_VERSION} (companion scripts run on 3.2; install/update runs need bash 4+ — brew install bash)"
else
  bad "bash ${BASH_VERSION:-unknown} — Sysop scripts need bash 3.2+"
fi

# ── The main checkout ───────────────────────────────────────────────────────
# Resolved once, here, because two probes below need it. A worktree carries the
# scripts but never a `.venv`, and run_checks.sh anchors on the main root via
# git-common-dir, so anything asking "what will run_checks use" must anchor the
# same way. Hoisted from probe 6 by Phase 182 — the round found probe 3 still
# reading `$REPO_ROOT`, which is the *same* defect Phase 143 fixed for probe 6
# and left here.
MAIN_ROOT="$REPO_ROOT"
_cd="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null)"
if [[ -n "$_cd" ]]; then
  case "$_cd" in /*) : ;; *) _cd="$REPO_ROOT/$_cd" ;; esac
  MAIN_ROOT="$(cd "$_cd/.." 2>/dev/null && pwd)" || MAIN_ROOT="$REPO_ROOT"
fi

# ── 3. python3 + PyYAML ─────────────────────────────────────────────────────
# Probe the interpreter run_checks.sh will ACTUALLY use (its selection order:
# the MAIN checkout's .venv/bin/python3 unconditionally when executable, then
# its venv/bin via the PATH prefix, then this checkout's, then PATH python3),
# then verify PyYAML on THAT interpreter — a yaml-capable system python is no
# comfort if run_checks picks a venv python without it (adversarial-review
# finding, 2026-07-19). **From a worktree this used to answer about the
# worktree**, which has no venv, so it reported a failure run_checks.sh would
# not have had; the comment above it claimed otherwise (Phase 182).
if [[ -x "$MAIN_ROOT/.venv/bin/python3" ]]; then
  RC_PY="$MAIN_ROOT/.venv/bin/python3"
elif [[ -x "$MAIN_ROOT/venv/bin/python3" ]]; then
  RC_PY="$MAIN_ROOT/venv/bin/python3"
elif [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then
  RC_PY="$REPO_ROOT/.venv/bin/python3"
elif [[ -x "$REPO_ROOT/venv/bin/python3" ]]; then
  RC_PY="$REPO_ROOT/venv/bin/python3"
else
  RC_PY="python3"
fi
PYYAML_PY=""
if command -v "$RC_PY" >/dev/null 2>&1 && "$RC_PY" -c 'import yaml' >/dev/null 2>&1; then
  PYYAML_PY="$RC_PY"
  ok "python3 with PyYAML: $RC_PY (what run_checks.sh will use)"
else
  bad "run_checks.sh will use '$RC_PY', which lacks PyYAML (or is broken)"
  info "fix: python3 -m venv .venv && .venv/bin/pip install pyyaml   (PEP-668-safe;"
  info "     install into THAT interpreter — a yaml-capable system python won't help)"
fi

# ── 4. git hooks armed ──────────────────────────────────────────────────────
# -C anchors the (possibly relative) --git-path result to the repo root, so
# running self-check from a subdirectory doesn't misreport armed hooks.
HOOKS_DIR="$(git -C "$REPO_ROOT" rev-parse --git-path hooks 2>/dev/null)"
case "$HOOKS_DIR" in
  /*) : ;;
  *) HOOKS_DIR="$REPO_ROOT/$HOOKS_DIR" ;;
esac
# Phase 150: this check is the designated backstop now that no lifecycle script
# arms hooks, so its remedy has to be one that actually works. Under a
# configured core.hooksPath, `install_hooks.sh` deliberately skips — pointing at
# it would leave the reader unarmed with no next step. Key-set, not non-empty:
# an empty core.hooksPath means git runs no hooks at all.
HOOKS_PATH_CFG=""
HOOKS_PATH_SET=0
if HOOKS_PATH_CFG="$(git -C "$REPO_ROOT" config --get core.hooksPath 2>/dev/null)"; then
  HOOKS_PATH_SET=1
fi
if [[ "$HOOKS_PATH_SET" -eq 1 && -z "$HOOKS_PATH_CFG" ]]; then
  info "core.hooksPath is set to the empty string — git runs NO hooks at all"
fi
ARMED=0
for tmpl in "$REPO_ROOT/sysop/scripts/hooks/"*; do
  [[ -f "$tmpl" ]] || continue
  name="$(basename "$tmpl")"
  if [[ -x "$HOOKS_DIR/$name" ]]; then
    if [[ "$HOOKS_PATH_SET" -eq 1 ]]; then
      # Present, but Sysop neither wrote nor compares it — don't claim credit.
      ok "hook present: $name  (your core.hooksPath dir — yours, not Sysop-managed)"
    else
      ok "hook armed: $name"
    fi
    ARMED=$((ARMED + 1))
  elif [[ "$HOOKS_PATH_SET" -eq 1 ]]; then
    info "hook not present: $name  (core.hooksPath='${HOOKS_PATH_CFG}' — copy sysop/scripts/hooks/$name there yourself; install_hooks.sh skips by design)"
  else
    info "hook not armed: $name  (arm: bash sysop/scripts/install_hooks.sh)"
  fi
done
if [[ "$ARMED" -eq 0 ]] && [[ -d "$REPO_ROOT/sysop/scripts/hooks" ]]; then
  info "no hooks armed — enforcement runs only where you wire it (CI, or arm the hooks)"
fi

# ── 5. optional scanners (advisory) ─────────────────────────────────────────
if command -v semgrep >/dev/null 2>&1; then
  ok "semgrep on PATH (AST checks will run)"
else
  info "semgrep not on PATH — AST checks skip (brew install semgrep / pip install semgrep)"
fi
if command -v pip-audit >/dev/null 2>&1 \
   || { [[ -n "$PYYAML_PY" ]] && "$PYYAML_PY" -c 'import pip_audit' >/dev/null 2>&1; }; then
  ok "pip-audit available (dependency audit will run)"
else
  info "pip-audit not found — dependency audit skips (pip install pip-audit)"
fi
if command -v pyright >/dev/null 2>&1 || [[ -x "$REPO_ROOT/.venv/bin/pyright" ]] \
   || [[ -x "$REPO_ROOT/venv/bin/pyright" ]]; then
  ok "pyright available (Python typecheck will run)"
else
  info "pyright not found — Python typecheck skips (pip install pyright)"
fi

# ── 6. review-round evidence (Phase 143) ────────────────────────────────────
# Two independent signals that a review round was abandoned rather than clean:
#   a) a PENDING MARKER that outlived its round — the round started and died
#      (refusal after starting, crash, quota exhaustion, context death). The
#      skills write these; only a completed round clears its own.
#   b) ASYMMETRIC round history — one review skill has completed rounds while
#      the other has none. That is the signature of a model which refuses one
#      task class outright (measured: one frontier non-Claude model refuses
#      /security-audit 2/2). Symmetric absence is a not-yet-started loop, not
#      a refusal, and reports neutral.
# Neither can catch a refusal that precedes the skill's first step — nothing
# running inside the refused round can. That is why this check lives out here.
printf '\n'
# Markers, and the canonical round history, live at the MAIN checkout — the
# skills write there via --git-common-dir (Phase 32 lock precedent), and the
# other two readers (run_checks pre-scan, /sitrep) resolve the same way. Anchor
# probe 6 to the main root too, or a self-check run from inside a worktree reads
# the empty worktree copy and reports a false all-clear on an abandoned round —
# the exact silent under-report this phase exists to close (adversarial review,
# 2026-07-23, reproduced from both the mechanics and evidence lenses).
# MAIN_ROOT is resolved once, above probe 3 (Phase 182 hoisted it there so the
# PyYAML probe anchors the same way this one does).
PENDING_DIR="$MAIN_ROOT/sysop/runtime/pending-rounds"
STALE_MIN=120  # first-guess live/stale split; tune on real use. Minute
               # granularity (find -mmin) is deliberately coarse — the ~60s
               # boundary skew vs the second-based python surfaces is well
               # inside "tune on real use".
PENDING_N=0
STALE_N=0
if [[ -d "$PENDING_DIR" ]]; then
  PENDING_N=$(find "$PENDING_DIR" -maxdepth 1 -type f -name '*.pending' 2>/dev/null | wc -l | tr -d ' ')
  STALE_N=$(find "$PENDING_DIR" -maxdepth 1 -type f -name '*.pending' -mmin "+$STALE_MIN" 2>/dev/null | wc -l | tr -d ' ')
fi
if [[ "$PENDING_N" -eq 0 ]]; then
  ok "no review round left pending"
elif [[ "$STALE_N" -eq 0 ]]; then
  info "$PENDING_N review round(s) in flight (started <${STALE_MIN}m ago) — likely a live session"
else
  bad "$STALE_N review round(s) started and never completed — their results are absent or partial"
  while IFS= read -r m; do
    [[ -n "$m" ]] || continue
    started="$(sed -n 's/^started: //p' "$m" 2>/dev/null | head -1)"
    info "    $(basename "$m") — started ${started:-unknown}"
  done < <(find "$PENDING_DIR" -maxdepth 1 -type f -name '*.pending' -mmin "+$STALE_MIN" 2>/dev/null)
  info "    an abandoned round writes no review_tasks.md entries and raises no error"
  info "    re-run the skill; delete the marker only once you have confirmed the round is dead"
fi

# Last completed round per skill. Read the active file AND the archive (the
# archiver relocates whole rounds at its size threshold, so a diligent
# consumer's active file legitimately shows no security rounds), and match by
# SUBSTRING — Step 5b merges same-day rounds into a combined
# "— Code Quality Review + OWASP Security Audit" header, which a suffix-keyed
# parse would report as a round that never ran. Fail soft to "unknown".
ROUND_SRC=()
[[ -f "$MAIN_ROOT/review_tasks.md" ]] && ROUND_SRC+=("$MAIN_ROOT/review_tasks.md")
[[ -f "$MAIN_ROOT/review_tasks_archive.md" ]] && ROUND_SRC+=("$MAIN_ROOT/review_tasks_archive.md")
if [[ "${#ROUND_SRC[@]}" -eq 0 ]]; then
  info "no review_tasks.md yet — the convention loop has not run here"
else
  HEADERS="$(grep -h '^## Round ' "${ROUND_SRC[@]}" 2>/dev/null)"
  QUAL_LAST="$(printf '%s\n' "$HEADERS" | grep 'Code Quality Review'   | sed -n 's/.*(\([0-9][0-9-]*\)).*/\1/p' | sort | tail -1)"
  SEC_LAST="$( printf '%s\n' "$HEADERS" | grep 'OWASP Security Audit'  | sed -n 's/.*(\([0-9][0-9-]*\)).*/\1/p' | sort | tail -1)"
  if [[ -n "$QUAL_LAST" && -n "$SEC_LAST" ]]; then
    ok "last code-quality round: $QUAL_LAST · last security audit: $SEC_LAST"
  elif [[ -z "$QUAL_LAST" && -z "$SEC_LAST" ]]; then
    info "no completed review rounds recorded yet — nothing has run, which is not a fault"
  else
    # Advisory, NOT a failure. Round history cannot tell "the model refused this
    # task class" apart from "the human hasn't run it yet" — both leave exactly
    # this trace. Failing here would redden every adopter still working through
    # the loop, and a check that cries wolf on the healthy case is worth less
    # than no check. Name both readings and let the human decide.
    if [[ -z "$SEC_LAST" ]]; then
      info "asymmetric round history: code-quality rounds exist (last $QUAL_LAST), no security audit has completed"
      info "    either /security-audit has not been run here yet, or it is being"
      info "    refused/abandoned — see docs/loop-mode.md § What loop mode does not promise"
    else
      info "asymmetric round history: security audits exist (last $SEC_LAST), no code-quality round has completed"
      info "    either /codebase-review has not been run here yet, or it is failing silently"
    fi
  fi
fi

# Tier-0 round coverage (_shared/fanout-evidence.md). The probes above ask
# whether a round ran; this asks how much of the codebase it actually opened.
# Loop mode ships no /sitrep, so this is the only surface where a loop-mode
# consumer sees a round that finished having covered ~1% of its own declared
# scope. The line itself is always printed (it is the number a consumer came
# here for); the FAILURE is raised only on a self-contradiction — a round that
# labelled itself thin is correct and must not be reddened for it.
RECEIPT_DIR="$MAIN_ROOT/sysop/runtime/round-receipts"
if [[ -d "$RECEIPT_DIR" ]]; then
  # Newest by MTIME, not by name. Receipts are `<skill>.<epoch>-<pid>.json`, so a
  # lexical sort ranks by skill name first and would report the older skill's
  # round as "last" whenever both have run — reporting a stale round as current
  # is worse than reporting none. `ls -t` is the portable mtime sort (BSD + GNU).
  LATEST="$(cd "$RECEIPT_DIR" 2>/dev/null && ls -t -- *.json 2>/dev/null | head -1)"
  if [[ -n "$LATEST" ]]; then
    R="$RECEIPT_DIR/$LATEST"
    _rfield() { sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p" "$R" 2>/dev/null | head -1; }
    _rstr()   { sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\(.*\)\".*/\1/p"     "$R" 2>/dev/null | head -1; }
    LINE="$(_rstr line)"; KIND="$(_rstr kind)"; DONE_AT="$(_rstr completed)"
    R_MAN="$(_rfield manifest)"; R_OPEN="$(_rfield opened)"; R_GREP="$(_rfield grepped)"
    R_TRACK="$(_rfield tracked)"
    if [[ -n "$LINE" ]]; then
      info "last round coverage: $LINE${DONE_AT:+  (closed $DONE_AT)}"
    else
      info "last round closed with no coverage line recorded — see $LATEST"
    fi
    # The anchor: `manifest` is the round's own claim, `tracked` was counted at
    # close. Shown, never judged — a scoped round legitimately speaks for a
    # fraction of the repo, and so does a full round with real exclusions. It is
    # here so the reader can see which.
    if [[ -n "$R_TRACK" ]]; then
      info "    repository had $R_TRACK tracked files at close (counted, not self-reported)"
    fi
    if [[ -z "$R_OPEN" || -z "$R_MAN" ]]; then
      info "    coverage is unreported for that round — an absent number reads as a clean pass"
    elif [[ "$KIND" == Full* ]]; then
      # The self-contradiction check, matched to /sitrep's: a round that
      # declared a FULL pass but reached under a third of its own declared
      # scope. Loop mode ships no /sitrep, so without this the only loop-mode
      # surface would print the collapsed round's own self-flattering line and
      # say nothing. A Scoped/Sampled round declared its narrowness and is
      # exempt — a check that fires on the honest case gets ignored.
      if [[ "$(( ( R_OPEN + ${R_GREP:-0} ) * 3 ))" -lt "$R_MAN" ]]; then
        bad "last review round declared Full over $R_MAN files but reached $(( R_OPEN + ${R_GREP:-0} ))"
        info "    opened $R_OPEN — re-run with sub-agent dispatch, or relabel the round"
        info "    Sampled and name the basis; a Full label over 1/3 coverage overstates it"
      fi
    fi
  fi
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
