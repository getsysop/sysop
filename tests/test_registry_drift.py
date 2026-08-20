"""Wires tools/registry_drift.py into pytest (Phase 212 round, `Q-248`).

WHY A TEST AND NOT JUST A SCRIPT. Phase 127 instituted a GDP backport-sweep
*convention*. It last ran 2026-06-24, and in the gap GDP shipped a `sql-fstring`
widening that Phase 212 then re-derived from scratch as a discovery. A
convention with no runner does not run — which is this project's own thesis
("machine checks, not more prompt text") turned on itself.

WHAT IT CAN AND CANNOT REACH, stated rather than implied. The comparison needs a
GDP checkout, which CI does not have, so in CI this **skips** and is worth
nothing. It is a maintainer-side ratchet: on a machine with the sibling repo it
runs on every suite invocation, which is the only cadence that does not depend
on someone remembering. A skip here is honest, not a pass.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "registry_drift.py"

sys.path.insert(0, str(REPO_ROOT / "tools"))

# `tools/` is stripped by the public mirror, so in a sterilized tree this module
# has nothing to import. Skip rather than error: the runbook's step 4 states the
# rule ("every test that reads a mirror-excluded file must `pytest.skip` with its
# reason"), and eleven shipped modules already follow it. Without this the import
# raises at COLLECTION, which is not a skip and not a failure but an error — it
# reddens the whole run, and on the public snapshot PR that is the required
# `pytest` check going red on a tree nobody can fix from the mirror. Excluding the
# file from the mirror instead was considered and rejected: it needs five gate
# sites rather than three, and it falsifies the "eleven arms" count at four
# maintainer-doc sites. In the source repo this line is an exact no-op.
registry_drift = pytest.importorskip(
    "registry_drift",
    reason="tools/registry_drift.py is maintainer-side and excluded from the "
           "public mirror; the GDP registry-drift ratchet only applies in the "
           "source repo",
)


def _upstream():
    return registry_drift.DEFAULT_GDP


requires_upstream = pytest.mark.skipif(
    not _upstream().is_file(),
    reason=f"no upstream registry at {_upstream()} — maintainer-side check",
)


@requires_upstream
def test_no_unaccepted_registry_divergence():
    """Every difference between Sysop's shipped checks and GDP's live ones is
    either absent or listed in ACCEPTED_DIVERGENCES with a reason.

    A failure is NOT necessarily a defect in Sysop — the divergence may be
    upstream's to adopt, or legitimately project-specific. What it is, always,
    is a decision nobody has recorded.
    """
    r = subprocess.run([sys.executable, str(SCRIPT)],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_drift_script_runs_and_is_honest_when_upstream_is_absent(tmp_path):
    """Non-vacuity control, and it runs everywhere including CI.

    Two properties the skip above cannot establish: the script executes at all,
    and pointing it at a missing registry exits 0 with a message rather than
    crashing or — worse — reporting a clean comparison it never made.
    """
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--gdp", str(tmp_path / "nope.yml")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing to compare" in r.stdout, r.stdout
    assert "OK:" not in r.stdout, "absent upstream must not read as a clean result"


def test_compared_fields_exclude_the_ones_that_differ_by_design():
    """`paths`/`include`/`exclude` differ on EVERY check by construction — Sysop
    ships placeholder vocabulary and a consumer localizes it. Comparing them
    would produce 40 rows of noise and the report would stop being read, which
    is how a check gets deleted."""
    import registry_drift
    for noisy in ("paths", "include", "exclude", "notes", "description"):
        assert noisy not in registry_drift.COMPARED_FIELDS, noisy
    assert "pattern" in registry_drift.COMPARED_FIELDS


def test_every_accepted_divergence_names_a_reason_and_a_real_check():
    """The allowlist is the only cheap way to silence this, so it is guarded the
    way `test_check_pattern_quotes.py::_EXEMPT` is: an entry must name a check
    Sysop actually ships, a field actually compared, and carry a real reason.
    A stale entry then fails loudly instead of silently covering nothing."""
    import registry_drift
    shipped = registry_drift.sysop_checks()
    for (cid, field), reason in registry_drift.ACCEPTED_DIVERGENCES.items():
        assert cid in shipped, f"accepted divergence names an unknown check: {cid}"
        assert field in registry_drift.COMPARED_FIELDS, f"{cid}.{field} is not compared"
        assert len(reason) > 40, f"{cid}.{field} needs a real reason, got {reason!r}"


@pytest.mark.parametrize("key", sorted(
    __import__("registry_drift").FILED_DIVERGENCES))
def test_every_filed_divergence_names_a_real_open_queue_entry(key):
    """FILED suppresses the gate, so it is the cheap way to silence a real
    finding. Each entry must therefore point at a queue id that EXISTS and is
    still OPEN — otherwise "filed" becomes a word rather than a commitment, and
    the debt stops being walkable the moment someone is in a hurry.

    Also catches the stale direction: once the entry is resolved and ticked,
    this reds and forces the suppression to come out with it.
    """
    import re
    import registry_drift
    reason = registry_drift.FILED_DIVERGENCES[key]
    ids = re.findall(r"\bQ-\d{3}\b", reason)
    assert ids, f"{key} is suppressed as 'filed' but names no queue id: {reason!r}"
    checklist = (REPO_ROOT / "REVIEW_CHECKLIST.md").read_text(encoding="utf-8")
    for qid in ids:
        assert f"<!-- id: {qid} -->" in checklist, (
            f"{key} cites {qid}, which is not in REVIEW_CHECKLIST.md"
        )
        assert f"- [ ] <!-- id: {qid} -->" in checklist, (
            f"{key} is still suppressed but {qid} is ticked closed — remove the "
            "FILED_DIVERGENCES entry along with the fix"
        )
