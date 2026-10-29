"""Drift guards for the shipped semgrep authoring convention (Phase 205).

`core/companion/semgrep/README.md` § Paths tells rule authors to omit `paths:`
from new rules — path scoping belongs in the pack's `checks.yml.fragment` stub
entry (Phase 133), and a `paths.include` in the rule YAML makes `semgrep scan
--config <rule>.yaml fixtures/` skip the fixtures the rule ships to prove
itself.

Until Phase 205 the same section also asserted *"Existing rules carry `paths:`
for historical documentation reasons"*. It was written true by `c9f936b`
(2026-04-20), when rules did carry `paths:`; `e03e731` (Phase 2H, 2026-05-07)
only relocated the file in the pack split; and `6b592ec` (Phase 2I.1, the same
day, 41 minutes later) stripped `paths:` from all eight rules that had it
without sweeping the sentence it had just falsified. False since 2026-05-07 —
99 days at the time of writing, and every install since Phase 3 shipped it. A
reader following it went looking for an existing `paths:` key, found none, and
could not tell whether the rules or the doc was wrong; the filing (`Q-195`) is
exactly that reader.

The first cut of this docstring said Phase 2H wrote the sentence and that it
had been false for fifteen months. Both were wrong, taken from a summary rather
than derived, and shipped in the module built to stop a claim from rotting.
Phase 205's round caught them.

The replacement sentence states the tree's actual state, so it is a claim that
can rot the same way. These tests are what keep it from rotting silently: the
convention is now machine-checked rather than asserted in prose.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "core" / "companion" / "semgrep" / "README.md"


def _shipped_rules():
    """Every shipped semgrep rule file, derived from the tree.

    Fixtures are excluded: they are inputs a rule is run against, not rules.
    Derived by glob rather than listed, so a new pack's rules are covered the
    day they land — the population-from-an-index failure the author-side pass
    names.
    """
    roots = [REPO_ROOT / "packs", REPO_ROOT / "core" / "companion" / "semgrep"]
    out = []
    for root in roots:
        for suffix in ("yaml", "yml"):
            out += [
                p for p in root.rglob(f"*.{suffix}")
                if "fixtures" not in p.parts and p.parent.name == "semgrep"
            ]
    return sorted(set(out))


def test_the_rule_population_is_not_empty():
    """Control. A glob that matches nothing makes the guard below vacuous —
    it would report 'no rule carries paths:' over an empty set."""
    rules = _shipped_rules()
    assert len(rules) >= 8, f"semgrep rule derivation collapsed: {rules}"


def test_no_shipped_rule_carries_paths():
    """The convention itself, and the README's claim about it.

    Checks both places semgrep accepts the key — document level and per-rule —
    because a rule-level `paths:` is the form the schema actually uses, and a
    guard that only looked at the top level would pass over every real case.
    """
    offenders = []
    for path in _shipped_rules():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        if "paths" in doc:
            offenders.append(f"{path.relative_to(REPO_ROOT)} (document level)")
        for rule in doc.get("rules") or []:
            if isinstance(rule, dict) and "paths" in rule:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)} (rule {rule.get('id')!r})"
                )
    assert not offenders, (
        "these rules carry `paths:`, which the shipped README tells authors not "
        "to do and which makes the fixture run skip its own fixtures: "
        + ", ".join(offenders)
    )


def test_the_readme_does_not_reassert_the_retired_falsehood():
    """The specific sentence Phase 205 removed, and the shape of its
    replacement. Pinning the removal alone would let the claim come back
    reworded; pinning the positive statement alone would let it be deleted."""
    text = README.read_text(encoding="utf-8")
    assert "historical documentation reasons" not in text, (
        "the retired `paths:` falsehood is back in the shipped README"
    )
    assert "No shipped rule carries `paths:` today" in text, (
        "the README no longer states the tree's actual `paths:` state, so a "
        "rule author has nothing to check the convention against"
    )
    # Deliberately NOT pinned: how that sentence is worded around. The round
    # showed the pin is satisfied by a wrapper negating it ("that used to be
    # worth saying — <sentence> — but several now do"), so reading a pass here
    # as "the README is true" is exactly the over-read this module exists to
    # stop. What makes the sentence true is the parse above, not this pin.
    # The imperative that carries the whole convention must survive the edit.
    assert "Omit `paths:` from new rules" in text
