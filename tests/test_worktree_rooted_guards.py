"""A guard must judge the tree under review, not the sandbox it runs in (`Q-366`).

`CLAUDE.md` mandates `isolation: "worktree"` for every review agent — the
Phase-153 precedent, where a reviewer ran `git checkout main` mid-round and
corrupted its siblings' reads — and the harness places those worktrees under
`.claude/worktrees/`. So a reviewer's `REPO_ROOT` is *itself* inside a
`.claude` directory, and any guard that inspects **absolute** path components
for `.claude` is red for that reviewer no matter what the tree contains.

`test_semgrep_fixture_proofs.test_no_guard_population_reaches_into_a_worktree`
was exactly that, and it fired on every round, for every reviewer. The cost is
not the noise: the round's method is *the suite is green, therefore the mutation
survived*, so a permanently-red module teaches a reviewer to discount reds,
which is how a real one gets missed. Three of Phase 248's reviewers hit it
simultaneously.

**Measured, so the class is not left implied.** The full suite was run from a
worktree under `.claude/worktrees/` at `438da3a` (the tree this phase opened
against): `1 failed, 5444 passed, 172 skipped`, and the one failure was the
guard above. The filed single site really was a single site — this file exists
to keep it that way, and the last test here is the class check.
"""
import ast
import re
from pathlib import Path

import pytest

import test_semgrep_fixture_proofs as sfp

REPO_ROOT = Path(__file__).resolve().parents[1]

RULE = "rules:\n  - id: demo\n    pattern: $X\n    message: m\n    languages: [python]\n    severity: INFO\n"


def _tree(root: Path):
    """A miniature shipped tree: one pack rule and one core rule."""
    (root / "packs" / "demo" / "companion" / "semgrep").mkdir(parents=True)
    (root / "packs" / "demo" / "companion" / "semgrep" / "r.yaml").write_text(RULE)
    (root / "core" / "companion" / "semgrep").mkdir(parents=True)
    (root / "core" / "companion" / "semgrep" / "c.yaml").write_text(RULE)
    (root / "packs" / "demo" / "companion").joinpath("checks.yml.fragment").write_text("checks: []\n")
    return root


def test_the_guard_passes_when_the_checkout_is_itself_under_dot_claude(tmp_path, monkeypatch):
    """The `Q-366` case, driven against the real function.

    The root is `<tmp>/.claude/worktrees/agent-x`, the shape the harness
    creates. Every absolute path below it contains `.claude`; no path
    *relative to it* does. Reverting the guard to `p.parts` fails this.
    """
    root = _tree(tmp_path / ".claude" / "worktrees" / "agent-x")
    monkeypatch.setattr(sfp, "REPO_ROOT", root)

    assert ".claude" in root.parts, "fixture does not reproduce the reported shape"
    sfp.test_no_guard_population_reaches_into_a_worktree()


def test_the_guard_still_catches_a_stale_rule_inside_a_nested_checkout(tmp_path, monkeypatch):
    """The other direction, for the RULE arm — the property is unweakened.

    **Real files, and no monkeypatched derivation.** The first cut of this
    control replaced `_rule_files` with an unscoped glob, which meant the
    fragment arm below was never exercised at all: the author-side battery
    gutted that arm to `assert frag is not None` and this module stayed green.
    A nested checkout planted *inside* `packs/` is reached by the shipped
    `rglob`, so both arms are driven by the code they are the control for.
    """
    root = _tree(tmp_path / "repo")
    nested = root / "packs" / "demo" / ".claude" / "worktrees" / "agent-y" / "companion" / "semgrep"
    nested.mkdir(parents=True)
    (nested / "stale.yaml").write_text(RULE)
    monkeypatch.setattr(sfp, "REPO_ROOT", root)

    assert any(".claude" in p.parts for p in sfp._rule_files()), (
        "the shipped derivation does not reach the planted copy — this control "
        "would pass without testing anything"
    )
    with pytest.raises(AssertionError):
        sfp.test_no_guard_population_reaches_into_a_worktree()


def test_the_guard_still_catches_a_stale_fragment_inside_a_nested_checkout(tmp_path, monkeypatch):
    """The same control for the CHECKS-FRAGMENT arm, which had none.

    Gutting this arm survived the author-side battery: every existing case
    stopped at the rule arm's assertion, so the second loop was never the
    thing under test.
    """
    root = _tree(tmp_path / "repo")
    nested = root / "core" / ".claude" / "worktrees" / "agent-z" / "companion"
    nested.mkdir(parents=True)
    (nested / "checks.yml.fragment").write_text("checks: []\n")
    monkeypatch.setattr(sfp, "REPO_ROOT", root)

    # The rule arm must be CLEAN here, or this proves nothing about the second.
    assert not any(".claude" in p.parts for p in sfp._rule_files())
    with pytest.raises(AssertionError):
        sfp.test_no_guard_population_reaches_into_a_worktree()


# The one module exempt from the class check below, and the reason.
#
# THIS file asserts `".claude" in root.parts` deliberately, twice: once to
# prove the fixture reproduces the reported shape, once to prove the shipped
# derivation reaches a planted copy. Both are statements ABOUT the class, made
# by its control, and neither is a containment guard. Everything else in the
# repo is in scope.
_CLASS_CHECK_EXEMPT = {"test_worktree_rooted_guards.py"}

_CLASS_CHECK_ROOTS = ("tests", "tools", "core/companion/scripts")


def _dot_claude_containment_offenders():
    """Every `<something> in/not in <path-ish>` test for `.claude`, unscoped.

    **A property, not a spelling.** The first cut of this check matched the
    literal text ``".claude" not in <name>.parts`` — one of at least eight ways
    to write the same claim. Phase 251's own round planted the other seven and
    watched every one survive: single quotes, `str(p)`, `p.resolve().parts`,
    `not (… in …)`, an attribute receiver, and an `if … : raise` that is not an
    `ast.Assert` at all. An enumeration of spellings is the answer `Q-374` and
    Phase 179's 0-of-21 both say is wrong.

    So the predicate is structural: a membership test whose literal side names
    `.claude` and whose container side is a path's `.parts` or its `str()`,
    with no `relative_to` in the expression. Quote style, negation, receiver
    depth and enclosing statement are all irrelevant to it.

    **Declared limit, because a check like this always has one.** A containment
    claim expressed some third way — a helper that hides the comparison, a
    regex over the string form, a `startswith` — is out of reach *in kind*, and
    the real guard against `Q-366` is the two behavioural tests above, which
    drive the shipped function under a `.claude`-nested root. This one stops the
    class re-entering by the routes anyone has actually written.
    """
    offenders = []
    for rel in _CLASS_CHECK_ROOTS:
        for path in sorted((REPO_ROOT / rel).rglob("*.py")):
            if path.name in _CLASS_CHECK_EXEMPT or "__pycache__" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            if ".claude" not in src:
                continue
            offenders += _offenders_in(src, path.name)
    return offenders


def _offenders_in(src, label):
    """The predicate itself, factored out so a control can drive it directly."""
    found = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            continue
        segment = ast.get_source_segment(src, node) or ""
        if ".claude" not in segment or "relative_to" in segment:
            continue
        # The container side must look like a PATH, or this fires on every
        # `".claude/x" in some_output_string` in the installer tests.
        if not any(_is_path_shaped(c) for c in node.comparators):
            continue
        found.append(f"{label}:{node.lineno}: {segment.strip()}")
    return found


def _is_path_shaped(node):
    """`<expr>.parts`, or `str(<expr>)` — the two ways a path is asked."""
    if isinstance(node, ast.Attribute) and node.attr == "parts":
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id == "str"
    return False


def test_no_shipped_guard_judges_an_absolute_path_for_dot_claude():
    """The class check (`Q-366`), over `tests/`, `tools/` and the shipped scripts."""
    offenders = _dot_claude_containment_offenders()
    assert not offenders, (
        "a guard is judging an ABSOLUTE path for `.claude`, which is red by "
        "construction for every reviewer working under `.claude/worktrees/` "
        "(Q-366). Compare the path relative to its root instead:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("shape", [
    'assert ".claude" not in p.parts',
    "assert '.claude' not in p.parts",
    'assert ".claude" not in str(p)',
    'assert ".claude" not in p.resolve().parts',
    'assert not (".claude" in p.parts)',
    'assert ".claude" not in h.p.parts',
    'if ".claude" in p.parts:\n    raise AssertionError(p)',
    'assert ".claude" in p.parts',
])
def test_the_class_check_can_actually_fail(shape):
    """The vacuity control, and the eight shapes that survived the first cut.

    A class check with no planted offender is indistinguishable from one whose
    population went empty — and narrowing `glob("*.py")` to a single filename
    survived Phase 251's round precisely because nothing here planted one.
    """
    assert _offenders_in(shape, "planted.py"), f"the predicate cannot see: {shape!r}"


@pytest.mark.parametrize("shape", [
    'assert ".claude" not in p.relative_to(ROOT).parts',
    'assert ".claude/settings.json" in dry_run_output',
    'assert (target / ".claude").is_dir()',
    'assert out.count(".claude/settings.json:") <= 2',
])
def test_the_class_check_does_not_fire_on_legitimate_shapes(shape):
    """The other direction. Over-strictness is the direction that hides.

    The fixed form must pass, and so must the three shapes the repo's installer
    tests already use — a membership test against a captured *string*, a path
    being CONSTRUCTED, and a count. Firing on those would make the check noise.
    """
    assert not _offenders_in(shape, "planted.py"), f"false positive on: {shape!r}"
