"""Drift guards for Phase 144 — the `/security-audit` claude-security ingest step.

String-anchor guards: they pin the load-bearing wording so a future edit cannot
silently re-open a hole the two-reviewer adversarial pass closed. They cannot pin
that the mechanism *works* (the parser's own suite does that) — only that the skill
still *says* the safe thing. Each assertion cites the finding it guards.
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SECURITY = (_ROOT / "core" / "skills" / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
_SETTINGS = (_ROOT / "core" / "companion" / ".claude" / "settings.json").read_text(encoding="utf-8")
_PARSER = _ROOT / "core" / "companion" / "scripts" / "ingest_security_report.py"


def _step3c() -> str:
    start = _SECURITY.index("## Step 3c: Ingest External Scan Report")
    return _SECURITY[start : _SECURITY.index("## Step 4: Deduplicate and Organize")]


# --- the step exists and sits after 3b -----------------------------------------
def test_step_3c_exists_after_3b():
    assert "## Step 3c: Ingest External Scan Report" in _SECURITY
    # ordering: 3b before 3c before 4
    assert (_SECURITY.index("## Step 3b:")
            < _SECURITY.index("## Step 3c:")
            < _SECURITY.index("## Step 4:"))


def test_parser_ships_and_is_invoked():
    assert _PARSER.is_file(), "the ingest parser must exist"
    assert "ingest_security_report.py --root ." in _step3c()


# --- (R2-H2 / provenance) never eligible for the 3b [verified] upgrade ----------
def test_ingested_findings_excluded_from_3b_upgrade():
    body = _step3c()
    assert "never eligible for the Step 3b sample-re-read" in body, (
        "an ingested finding must not be upgradable to [verified] via 3b sampling"
    )
    assert "[reported]" in body


# --- (R2-M2) panel verification is data, never copied onto the tag --------------
def test_panel_verification_not_laundered_to_verified():
    assert "never copied onto the provenance tag" in _step3c()
    assert "never promoted to `[verified]`" in _SECURITY


# --- (R2-H2) labeled batch, not this round's delta ------------------------------
def test_ingested_findings_get_their_own_batch():
    assert "Ingested — claude-security" in _step3c()
    assert "Do **not** merge them into this round's OWASP agent batches" in _step3c()


# --- (R1-H3) out-of-scope surfaced, never silently dropped ----------------------
def test_out_of_scope_never_silently_discarded():
    body = _step3c()
    assert "out_of_scope" in body
    assert "never silently discard" in body


# --- (R1-C2 / R1-M1) trust off status/reason; verified != coverage --------------
def test_truncation_surfaced_loudly():
    body = _step3c()
    assert "floor, not a coverage claim" in body
    assert "trust.reasons" in body
    assert 'trust.status != "verified"' in body
    # verified must be described as NOT a coverage guarantee
    assert "not** that the scan covered the repo" in body or \
           "not a coverage claim" in body


# --- (R1-C3) sanitization boundary — never hand-copy the raw report -------------
def test_sanitization_boundary_stated():
    body = _step3c()
    assert "never hand-copy from the raw" in body
    assert "untrusted" in body


# --- (M1 / warn-not-halt) best-effort, never blocks the round -------------------
def test_step_is_best_effort_never_blocks():
    body = _step3c()
    assert "never block the round" in body
    # a drift/skip is surfaced, not fatal
    assert "never fatal" in body


# --- (R1-M3 + 2nd-pass) dedup vs closed tasks: archive-aware, fixed != rejected -
def test_ingested_dedup_against_closed_tasks():
    # lives in Step 4, not 3c
    step4 = _SECURITY[_SECURITY.index("## Step 4: Deduplicate and Organize"):
                      _SECURITY.index("## Step 4b:")]
    assert "must not silently re-file" in step4
    # archive-aware: aged rejections live in review_tasks_archive.md
    assert "review_tasks_archive.md" in step4
    assert "closed-task index over both files" in step4
    # a re-surfaced *fixed* site is a regression signal, not a dup to suppress
    assert "possible regression" in step4


# --- (2nd-pass) non-full rounds MUST scope-file, so a whole-repo report can't flood
def test_non_full_round_must_pass_scope_file():
    body = _step3c()
    assert "MUST pass `--scope-file`" in body
    assert "sysop/runtime/audit-scope.txt" in body


# --- (R2-C1) the full-mode permission rule ships in the master template ---------
def test_master_settings_carries_the_ingest_allow_rule():
    data = json.loads(_SETTINGS)
    allow = data["permissions"]["allow"]
    assert "Bash(python3 sysop/scripts/ingest_security_report.py:*)" in allow
    assert "Bash(.venv/bin/python3 sysop/scripts/ingest_security_report.py:*)" in allow


# --- Step 6 surfaces the ingest line -------------------------------------------
def test_step6_summary_has_ingest_line():
    assert "Ingested (claude-security):" in _SECURITY
