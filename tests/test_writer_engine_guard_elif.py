"""Phase 358 round (`Q-636`): every guard form of the postgres pack's
`missing-writer-engine-guard` rule is accepted as the first, second or third test of an
entry if/elif chain.

The rewritten rule first accepted a guard only as a statement of its own, so the route
shape `if not payload: return 400` / `elif not db.writer_engine: return 503` was flagged,
which the base rule had accepted. The fixtures exercise a few of the chain variants by
running semgrep; this pins that no guard form lost its variants, without semgrep.
"""
import re
from pathlib import Path

import yaml

RULE = (Path(__file__).resolve().parents[1] / "packs" / "postgres" / "companion"
        / "semgrep" / "missing_writer_engine_guard.yaml")


def _patterns():
    rule = yaml.safe_load(RULE.read_text(encoding="utf-8"))["rules"][0]
    arms = rule["patterns"][1]["pattern-either"]
    out = []
    for arm in arms:
        excl = next(p["pattern-not-inside"] for p in arm["patterns"] if "pattern-not-inside" in p)
        either = next(p["pattern-either"] for p in excl["patterns"] if "pattern-either" in p)
        out.append([p["pattern"] for p in either])
    return out


_HEAD = re.compile(r"^if (?P<g>.+):$")
_ELIF = re.compile(r"^elif (?P<g>.+):$")


def _shape(pattern):
    """('if', guard) for a lone guard; ('elif2'|'elif3', guard) for a chain."""
    lines = [ln.strip() for ln in pattern.strip().splitlines()]
    elifs = [_ELIF.match(ln).group("g") for ln in lines if _ELIF.match(ln)]
    if not elifs:
        return "if", _HEAD.match(lines[0]).group("g")
    assert lines[0] == "if $PRIOR:", pattern
    return f"elif{len(elifs) + 1}", elifs[-1]


def test_every_guard_form_has_both_chain_variants():
    arms = _patterns()
    assert len(arms) == 2, "the bare and the attribute arm"
    for pats in arms:
        shapes = [_shape(p) for p in pats]
        lone = {g for kind, g in shapes if kind == "if"}
        assert lone, "an arm with no guard forms would pass vacuously"
        for kind in ("elif2", "elif3"):
            got = {g for k, g in shapes if k == kind}
            assert got == lone, (kind, sorted(lone - got), sorted(got - lone))
        assert len(shapes) == 3 * len(lone), "one pattern per guard form and variant"


def test_a_three_test_chain_names_its_middle_test():
    """The third-test variant must keep a middle test of its own; collapsing it onto
    `$PRIOR` would make it the two-test variant again."""
    for pats in _patterns():
        for p in pats:
            if p.count("elif ") == 2:
                assert "elif $PRIOR2:" in p, p
