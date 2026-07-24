"""Drift guard — WORKFLOW.md § 8.4 documents every script Sysop ships.

Why this exists (the drift it caught, in the workflow's own terms): the § 8.4
scripts table is the canonical description of `sysop/scripts/`, but nothing
forced a new script to appear in it. By 2026-07-24 it had fallen **eight rows**
behind the shipping tree — `next_task.py` (Phase 45a), `pr_dependabot.py`
(Phase 53), `sitrep_survey.py` (Phase 82), `self_check.sh` (Phase 133),
`ingest_security_report.py` (Phase 144), plus `validate_tasks.py`,
`backfill_completed_dates.py`, and `_log.py`.

`self_check.sh` is the shape of the problem: the install footer and the
quickstart both tell a consumer to run it, while the canonical table did not
list it at all. Documentation drift of this class is silent by construction —
an absent row looks exactly like a script that doesn't exist — which is the
same "silence is indistinguishable from a clean result" failure the security
map's inventory-completeness invariant exists to kill (Phase 141). Same fix,
smaller scope: make the absence mechanical.

Scope notes, both deliberate:
- **Top-level only.** `run_checks/` is a package (Phase 49), not a set of
  entry points; the table documents its two entry points (`run_checks.sh`,
  `run_checks_impl.py`) and that is the right altitude.
- **Private helpers are exempt but enumerated.** Underscore-prefixed files
  aren't entry points, so they don't need a row — but the exemption list is
  asserted exactly, so a new private helper forces a deliberate call instead
  of inheriting the exemption silently.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
SCRIPTS_DIR = REPO_ROOT / "core/companion/scripts"

# Underscore-prefixed shared helpers — imported by other scripts, never invoked
# directly. Exempt from the row requirement; both are in fact described (`_log.py`
# has its own row, `_model_roles.py` inside the `resolve_skill_models.py` row).
PRIVATE_HELPERS = {"_log.py", "_model_roles.py"}

# First cell of a table row, e.g. "| `claim_task.sh <TASK_ID> <BRANCH>` | ..." —
# the name may carry a usage signature, so match only the filename that starts it.
ROW_SCRIPT = re.compile(r"^\|\s*`([A-Za-z0-9_.-]+\.(?:py|sh))\b")


def _section_8_4():
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^### 8\.4 .*?$(.*?)^### 8\.5 ", text, re.M | re.S)
    assert match, (
        "WORKFLOW.md § 8.4 (the scripts table) could not be located — if the "
        "section was renumbered, update this guard rather than deleting it"
    )
    return match.group(1)


def _documented_scripts():
    return {
        m.group(1)
        for line in _section_8_4().splitlines()
        if (m := ROW_SCRIPT.match(line))
    }


def _shipped_scripts():
    return {
        p.name
        for p in SCRIPTS_DIR.iterdir()
        if p.is_file() and p.suffix in (".py", ".sh")
    }


def test_every_shipped_script_has_a_table_row():
    """A script that ships without a row is invisible to the consumer reading the spec."""
    expected = {s for s in _shipped_scripts() if not s.startswith("_")}
    missing = sorted(expected - _documented_scripts())
    assert not missing, (
        f"These scripts ship in sysop/scripts/ but have no row in WORKFLOW.md "
        f"§ 8.4: {missing}. Add a row describing what each does (and any "
        f"constraint a consumer would otherwise learn by failure) — the table "
        f"is the canonical description of the scripts directory."
    )


def test_table_names_no_script_that_does_not_ship():
    """The backward half: a row for a deleted/renamed script is a dead referent."""
    stale = sorted(_documented_scripts() - _shipped_scripts())
    assert not stale, (
        f"WORKFLOW.md § 8.4 documents scripts that no longer ship: {stale}. "
        f"Remove the rows, or restore the scripts if the deletion was the bug."
    )


def test_private_helper_exemption_is_explicit():
    """A new underscore helper must be a deliberate call, not a silent exemption."""
    shipped_private = {s for s in _shipped_scripts() if s.startswith("_")}
    assert shipped_private == PRIVATE_HELPERS, (
        f"The set of private (underscore-prefixed) helpers in sysop/scripts/ "
        f"changed: expected {sorted(PRIVATE_HELPERS)}, found "
        f"{sorted(shipped_private)}. Decide explicitly whether the new file is "
        f"a private helper (add it here) or an entry point (give it a § 8.4 row)."
    )
