"""The LSP and semgrep checks leave Sysop's vendored `sysop/` out of their findings (`Q-289`, ruled
(c); widened to the semgrep checks by `Q-702`, Wade 2026-10-22).

On a fresh install every pyright check's `paths:` are placeholders, `check_paths_by_id`
strips them as "not yet localized", and the stage scans whole-tree, so the first run
reported `[pyright-missing-imports] HIGH sysop/scripts/run_checks/semgrep.py:272` against
Sysop's own code. Wade's ruling (2026-10-21): a default `exclude_dir:` on the LSP checks;
the same run still printed `[semgrep-recompile-inside-def] MEDIUM sysop/scripts/round_receipt.py`,
and `Q-702` widened it to every shipped semgrep check. Run through the REAL `check_paths_by_id` + `finding_in_scope` over the REAL shipped
fragments, because the mechanism is their interaction: the placeholder strip leaves
`exclude_dir:` standing. A test that asserted the YAML key exists would pass with a
spelling `finding_in_scope` never matches (`"sysop/"`: fnmatch takes the slash literally).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "core" / "companion" / "scripts"))
from run_checks.config import check_paths_by_id, finding_in_scope  # noqa: E402

# Every shipped fragment, so an LSP check a pack adds later is held to the same rule (round 1,
# lens B: a population of the two files that carry one today stayed green over a third).
FRAGMENTS = sorted([_ROOT / "core" / "companion" / "checks.yml.fragment",
                    *(_ROOT / "packs").glob("*/companion/checks.yml.fragment")])
ALL = [c for f in FRAGMENTS for c in (yaml.safe_load(f.read_text()) or {}).get("checks") or []]
CHECKS = {c["id"]: c for c in ALL}
LSP = {cid: c for cid, c in CHECKS.items() if cid.startswith(("pyright-", "tsc-"))}
SCOPES = check_paths_by_id(LSP)
SEMGREP = {cid: c for cid, c in CHECKS.items() if cid.startswith("semgrep-")}
SEMGREP_SCOPES = check_paths_by_id(SEMGREP)
# What each semgrep check excluded before `Q-702`, so the vendor entry is the only addition.
SEMGREP_OWN = {"semgrep-recompile-inside-def": {"test", "tests", "testsuite"},
               "semgrep-missing-fetch-redirect": {"__tests__"}}
VENDOR = "sysop/scripts/run_checks/semgrep.py"
VENDOR_PATHS = (VENDOR, "sysop/runtime/x.py", "sysop/docs/conf.py")


def test_the_population_is_the_shipped_lsp_checks():
    assert len(FRAGMENTS) > 2, "the fragment glob found almost nothing"
    # A dict keyed by id keeps the last definition, so a second copy of an LSP check in a pack
    # that sorts first would be invisible here (round 2, lens D).
    ids = [c["id"] for c in ALL if c["id"].startswith(("pyright-", "tsc-"))]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert sorted(LSP) == ["pyright-general-warning", "pyright-missing-imports",
                           "pyright-undefined-variable", "pyright-unused-import",
                           "pyright-unused-variable", "tsc-type-error"]


@pytest.mark.parametrize("cid", sorted(LSP))
def test_a_fresh_install_drops_findings_in_the_vendor_dir(cid):
    # Exactly the vendor directory: a wider list would drop a consumer directory that happens to
    # share a name with what else it holds (round 1, lens B: `["sysop", "lib"]` passed).
    assert LSP[cid].get("exclude_dir") == ["sysop"], (
        f"{cid}'s exclude_dir is {LSP[cid].get('exclude_dir')!r}. A widened list is a deliberate "
        "change to what a consumer's own code reports: update this assertion with it.")
    assert SCOPES[cid]["paths"] == [], "a shipped LSP check is no longer placeholder-scoped"
    for rel in VENDOR_PATHS:
        assert not finding_in_scope(rel, SCOPES[cid]), rel


@pytest.mark.parametrize("cid", sorted(LSP))
def test_the_consumers_own_code_is_still_read(cid):
    """The vacuity control: an exclusion that dropped everything would pass the test above."""
    for rel in ("app/main.py", "src/pkg/mod.py", "web/src/page.tsx", "sysop_tools/x.py",
                "scripts/build.py"):
        assert finding_in_scope(rel, SCOPES[cid]), rel


def test_a_localized_check_keeps_the_exclusion():
    """Substituting a placeholder for `.` (a small repo's whole tree) must not reopen it."""
    spec = dict(LSP["pyright-missing-imports"], paths=["./"])
    scope = check_paths_by_id({"pyright-missing-imports": spec})["pyright-missing-imports"]
    assert not finding_in_scope(VENDOR, scope)
    assert finding_in_scope("app/main.py", scope)


def test_the_stale_baseline_hint_names_a_narrowed_scope(capsys):
    """After an update ships this key, a baselined vendor finding reads as a stale entry; the
    hint names that cause beside grep's binary skip and semgrep's size limit (round 1, lens A)."""
    from run_checks.cli import _print_unmatched
    _print_unmatched([("pyright-missing-imports|sysop/scripts/x.py:1|abc", True)])
    err = " ".join(capsys.readouterr().err.split())
    assert "a narrowed `paths:` or `exclude_dir:`, yours or one an update shipped" in err


def test_the_semgrep_population_is_every_shipped_rule():
    ids = [c["id"] for c in ALL if c["id"].startswith("semgrep-")]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert len(SEMGREP) == 12, sorted(SEMGREP)
    assert set(SEMGREP_OWN) <= set(SEMGREP)


@pytest.mark.parametrize("cid", sorted(SEMGREP))
def test_a_fresh_install_drops_semgrep_findings_in_the_vendor_dir(cid):
    """The semgrep stage post-filters with the same `finding_in_scope` (`run_checks/semgrep.py`)."""
    ex = SEMGREP[cid].get("exclude_dir") or []
    assert ex.count("sysop") == 1 and set(ex) == SEMGREP_OWN.get(cid, set()) | {"sysop"}, (
        f"{cid}'s exclude_dir is {ex!r}: the vendor directory is the only entry `Q-702` adds.")
    assert SEMGREP_SCOPES[cid]["paths"] == [], "a shipped semgrep check is no longer placeholder-scoped"
    for rel in VENDOR_PATHS:
        assert not finding_in_scope(rel, SEMGREP_SCOPES[cid]), rel


@pytest.mark.parametrize("cid", sorted(SEMGREP))
def test_a_semgrep_check_still_reads_the_consumers_code(cid):
    for rel in ("app/main.py", "src/pkg/mod.py", "web/src/page.tsx", "sysop_tools/x.py",
                "scripts/build.py"):
        assert finding_in_scope(rel, SEMGREP_SCOPES[cid]), rel
