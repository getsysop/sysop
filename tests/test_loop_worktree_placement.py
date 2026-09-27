"""`Q-588` (Phase 333) — a loop-shipped skill's `git worktree` command must have a loop rule.

THE DEFECT. `/codebase-review` and `/security-audit` both tell the runner to place each
isolated agent with `git worktree add <dir> --detach <sha>` when run off the default branch
(`Q-489`'s rule). Both skills ship in loop mode, and `install.sh`'s `LOOP_ALLOW` carried no
`git worktree` rule, so on a loop install the placement command was denied under `dontAsk`
and prompted everywhere else. The full-mode template had the rules all along.

WHY `test_prescribed_command_coverage.py` DID NOT CATCH IT. That module sweeps
`sysop/scripts/<script>` invocations inside fenced code blocks. The placement command is
neither: it is a `git` subcommand, written inline in a prose paragraph. Widening that module
to every `git` command in every shipped file was not taken: most `git` verbs a skill names
are read-only forms whose auto-approval the docs describe only as a non-exhaustive category
(`tests/test_permission_surface_drift.py`'s READ_ONLY_GIT_VERBS note), so a general sweep
would have to guess which ones need a rule, and inline prose mixes prescriptions with
descriptions. This module is the narrow version that needs no guess: every `git worktree`
subcommand a loop-shipped runner names must be covered by `LOOP_ALLOW`, because no
`git worktree` subcommand that writes is read-only.

WHAT THE DECIDED TEXT IS GUARDED BY. Wade's decisions on the placement paragraph (placement
applies off the default branch; a denied placement falls back to no isolation with a status and
`HEAD` snapshot; a refused removal is forced only over the runner's own `.venv`; a denied removal
leaves the checkout) and the pre-flight's conditional note are hash-pinned in
`tests/test_fix_in_branch_tier.py`'s `PINNED_SPANS`, each from its paragraph's opener to the next
paragraph's lead. Round 1 replaced the prose predicates that stood here first; round 2 widened the
pins after a sentence placed before them and a paragraph placed after them each reversed a
decision with every test green. What stays here is executable: a parse of the commands, the rule
sets, and the pre-flight's hard-stop list items.

WHAT IT READS AS A COMMAND. Every inline code span, and every non-comment line of a fenced
block, that contains `worktree <subcommand>`. Permission-rule spans (`Bash(git worktree add:*)`)
are not commands and are skipped -- counting them let a skill with every real command deleted
pass. A command counts as BARE only if, whitespace-flattened, it begins with exactly
`git worktree <sub>`. Anything else in front -- a global option (`-C <main checkout>`,
`-c user.name="Sysop Bot"`, `--git-dir=…`), a command substitution, a quoted variable, a
backslash continuation, an assignment prefix, a `cd … &&` compound -- is refused, because a
permission rule's prefix is matched literally and binds only the bare form.

WHAT THIS CANNOT DO.

* A `git worktree` command written in plain prose, outside any code span or fence, is not read.
  None exists in these skills today; every command they prescribe is in backticks.
* It counts descriptive spans as well as prescriptive ones, on purpose: the error is a loud red
  naming the rule, never a silent pass.
* It reads `SKILL.md` runners only, not `REFERENCE.md` (editor-facing) nor the `_shared/`
  partials: `_shared/adversarial-review.md` names `git worktree list` in a narrative about a
  past round, and no loop skill prescribes `list`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_fix_in_branch_tier as T  # noqa: E402
from _prose_guard_helpers import _fence_state  # noqa: E402
from test_permission_surface_drift import declared_required, satisfied  # noqa: E402
from test_prescribed_command_coverage import _loop_allow, _template_rules  # noqa: E402
from _reversal import slice_between  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "core" / "skills"
INSTALLER = REPO / "install.sh"
REVIEW_SKILLS = {
    "codebase-review": SKILLS / "codebase-review" / "SKILL.md",
    "security-audit": SKILLS / "security-audit" / "SKILL.md",
}
PLACEMENT_PIN = "placement paragraph"
PREFLIGHT_PIN = "pre-flight stop and worktree note"

SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
WORKTREE_SUB = re.compile(r"\bworktree\s+([a-z][a-z-]*)")
BARE = re.compile(r"git worktree [a-z]")
SHELL_COMMENT = re.compile(r"(?:^|\s)#.*$")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _loop_skill_runners() -> dict[str, Path]:
    """Every `SKILL.md` a loop install ships, derived from install.sh's exclude list."""
    m = re.search(r'^LOOP_EXCLUDE_SKILLS="([^"]*)"', INSTALLER.read_text(encoding="utf-8"), re.M)
    assert m, "LOOP_EXCLUDE_SKILLS is no longer a quoted string in install.sh"
    excluded = set(m.group(1).split())
    return {
        p.parent.name: p
        for p in sorted(SKILLS.glob("*/SKILL.md"))
        if not p.parent.name.startswith("_") and p.parent.name not in excluded
    }


def worktree_commands(text: str) -> list[str]:
    """Every command in `text` that names `worktree <sub>`, whitespace-flattened.

    Fenced lines are read one per line, with a shell comment stripped; the rest of the text
    is read as inline code spans (which may cross a soft line break).
    """
    lines = text.split("\n")
    out, prose = [], []
    for i, fenced in _fence_state(lines):
        if fenced:
            code = SHELL_COMMENT.sub("", lines[i])
            if WORKTREE_SUB.search(code):
                out.append(_flat(code))
            prose.append("")
        else:
            prose.append(lines[i])
    for m in SPAN.finditer("\n".join(prose)):
        body = _flat(m.group(2))
        if body.startswith("Bash(") or not WORKTREE_SUB.search(body):
            continue
        out.append(body)
    return out


def subcommands(text: str) -> set[str]:
    return {sub for cmd in worktree_commands(text) for sub in WORKTREE_SUB.findall(cmd)}


def uncovered(text: str, rules: set[str]) -> list[str]:
    """Subcommands `text` names that `rules` does not cover, as the rule each one needs."""
    need = {f"Bash(git worktree {sub}:*)" for sub in subcommands(text)}
    return sorted(r for r in need if not satisfied(r, rules))


def non_bare_spellings(text: str) -> list[str]:
    return [cmd for cmd in worktree_commands(text) if not BARE.match(cmd)]


# ── population floors: every check below is vacuous if these fail ──

def test_both_review_skills_are_loop_shipped():
    runners = _loop_skill_runners()
    assert set(REVIEW_SKILLS) <= set(runners), (
        f"the loop runner set {sorted(runners)} no longer contains both review skills; the "
        "coverage check below would read neither of the files Q-588 is about"
    )


def test_both_review_skills_name_add_and_remove_as_commands():
    for name, path in REVIEW_SKILLS.items():
        subs = subcommands(path.read_text(encoding="utf-8"))
        assert {"add", "remove"} <= subs, (
            f"{name}: expected the placement (`git worktree add`) and its cleanup "
            f"(`git worktree remove`) as commands, not only as rule names; found {sorted(subs)}"
        )


# ── the guard ──

def test_every_loop_runner_worktree_command_has_a_loop_rule():
    rules = _loop_allow()
    missing = {
        name: gap
        for name, path in _loop_skill_runners().items()
        if (gap := uncovered(path.read_text(encoding="utf-8"), rules))
    }
    assert not missing, (
        "loop-shipped skills name `git worktree` subcommands that install.sh's LOOP_ALLOW "
        f"does not cover, so a loop install denies or prompts on them: {missing}"
    )


def test_the_full_template_covers_them_too():
    rules = _template_rules()
    missing = {
        name: gap
        for name, path in _loop_skill_runners().items()
        if (gap := uncovered(path.read_text(encoding="utf-8"), rules))
    }
    assert not missing, f"the full-mode template does not cover: {missing}"


def test_every_loop_runner_worktree_command_is_bare():
    offenders = {
        name: bad
        for name, path in _loop_skill_runners().items()
        if (bad := non_bare_spellings(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        "a `worktree` command that does not begin with exactly `git worktree` binds no "
        f"`Bash(git worktree …:*)` rule -- the prefix is matched literally: {offenders}"
    )


def test_pre_flight_does_not_hard_stop_on_the_worktree_rules():
    """Wade's decision: the default-branch run places no agent and must not be stopped for a
    rule it never uses, and a missing rule now falls back rather than stopping anything.
    The note that says so is pinned; this is the executable half -- the list items that stop.
    `declared_required()` reads every list-item marker (`-`, `*`, `+`, `1.`, `1)`)."""
    declared = declared_required()
    for name in REVIEW_SKILLS:
        hard = [r for r in declared.get(name, []) if "worktree" in r]
        assert not hard, f"{name} hard-requires {hard} in its pre-flight list"


def _worktree_note(path: Path) -> str:
    """The pre-flight's `Not checked here` note, from its lead to the end of its line."""
    text = path.read_text(encoding="utf-8")
    assert text.count("**Not checked here:**") == 1, f"{path.parent.name}: expected one note"
    at = text.index("**Not checked here:**")
    return text[at:text.index("\n", at)]


def test_the_decided_text_is_pinned_in_both_skills_identically():
    """The pins exist and point at the right files; the placement paragraph hashes equal across
    the two skills, and the pre-flight note (inside a span that also carries each skill's own
    one-line reason) is the same string in both."""
    placement = {}
    for name, path in REVIEW_SKILLS.items():
        for kind in (PLACEMENT_PIN, PREFLIGHT_PIN):
            label = f"{name} {kind}"
            assert label in T.PINNED_SPANS and label in T.PIN_HASHES, f"{label} is not pinned"
            assert T.PINNED_SPANS[label][0] == path, f"{label} is pinned against the wrong file"
        placement[name] = T._pin_hash(T._span(f"{name} {PLACEMENT_PIN}"))
    assert len(set(placement.values())) == 1, (
        f"the placement paragraph has diverged between the two review skills: {placement}"
    )
    notes = {name: _worktree_note(path) for name, path in REVIEW_SKILLS.items()}
    assert len(set(notes.values())) == 1, f"the pre-flight worktree note has diverged: {notes}"


# Both arms that dispatch agents into the runner's OWN checkout must snapshot all three things an
# agent can change there. Measured (Phase 333's round 3, git 2.50.1): `git switch -qc <new>` leaves
# the status AND the commit unchanged and only the branch moves -- and the runner's next commit then
# lands on the agent's branch; `git checkout <other>` moves commit and branch with the status
# unchanged. So the status diff alone, or status plus commit, reads either as a clean round.
SNAPSHOTS = ("`git status --porcelain -uall`", "`git rev-parse HEAD`", "`git symbolic-ref -q HEAD`")
UNISOLATED_ARMS = {
    "no-isolation harness": ("Where it does not, snapshot", "`/review-close` Step 2b prescribes"),
    "add-denied fallback": ("**If `git worktree add` is denied", "Never dispatch an isolated agent"),
}


def snapshot_gaps(text: str) -> dict[str, list[str]]:
    """arm -> the snapshot commands that arm does not name. Slices fail closed on a lost anchor."""
    gaps = {}
    for arm, (start, end) in UNISOLATED_ARMS.items():
        flat = _flat(slice_between(text, start, end, arm))
        missing = [cmd for cmd in SNAPSHOTS if cmd not in flat]
        if missing:
            gaps[arm] = missing
    return gaps


def test_both_unisolated_arms_snapshot_status_commit_and_branch():
    for name, path in REVIEW_SKILLS.items():
        gaps = snapshot_gaps(path.read_text(encoding="utf-8"))
        assert not gaps, (
            f"{name}: an arm that dispatches into the runner's own checkout does not snapshot "
            f"everything an agent can change there: {gaps}"
        )


# ── controls: each predicate fires on the defect it is for, and stays green on legal text ──

def test_controls_snapshot_gaps_fires_per_arm_and_tolerates_a_rewrap():
    text = REVIEW_SKILLS["codebase-review"].read_text(encoding="utf-8")
    assert snapshot_gaps(text) == {}
    # The population is fixed here, not read off the table it checks: dropping an arm from
    # UNISOLATED_ARMS walked through a loop over that same table (round-3 battery, G3).
    fixed = {
        "no-isolation harness": ("Where it does not, snapshot", "`/review-close` Step 2b prescribes"),
        "add-denied fallback": ("**If `git worktree add` is denied", "Never dispatch an isolated agent"),
    }
    assert UNISOLATED_ARMS == fixed, "the guard no longer reads both unisolated arms"
    # Drop the branch snapshot from each arm in turn; only that arm may report it.
    for arm, (start, end) in fixed.items():
        span = slice_between(text, start, end, arm)
        cut = span.replace("`git symbolic-ref -q HEAD`", "the branch")
        assert cut != span, f"{arm}: the control did not apply"
        assert snapshot_gaps(text.replace(span, cut)) == {arm: ["`git symbolic-ref -q HEAD`"]}
    rewrapped = text.replace("`git symbolic-ref -q HEAD`", "`git symbolic-ref\n-q HEAD`")
    assert snapshot_gaps(rewrapped) == {}, "a re-wrap inside the code span reddened the check"


def test_controls_uncovered_fires_on_a_missing_rule():
    text = "Place it: `git worktree add <dir> --detach <sha>`."
    assert uncovered(text, {"Bash(git add:*)"}) == ["Bash(git worktree add:*)"]
    assert uncovered(text, {"Bash(git worktree add:*)"}) == []
    assert uncovered(text, {"Bash(git worktree:*)"}) == [], "a broader rule must count"
    assert uncovered(text, {"Bash(git worktree add)"}) == ["Bash(git worktree add:*)"], (
        "a wildcard-less exact rule binds only the bare invocation, not the placement command"
    )


def test_controls_rule_names_are_not_commands():
    only_rules = "add `Bash(git worktree add:*)` and `Bash(git worktree remove:*)` to settings"
    assert worktree_commands(only_rules) == [], (
        "a rule name was counted as a command -- deleting every real command would pass"
    )


def test_controls_a_rewrap_keeps_the_match():
    wrapped = "Place it with `git\n   worktree\nadd <dir> --detach <sha>`."
    assert worktree_commands(wrapped) == ["git worktree add <dir> --detach <sha>"]
    assert not non_bare_spellings(wrapped)


def test_controls_fenced_commands_are_read_and_comments_are_not():
    text = ("```bash\n# destroyed by `git worktree remove`\n"
            "git -C /repo worktree prune\n```\n")
    assert worktree_commands(text) == ["git -C /repo worktree prune"]
    assert subcommands(text) == {"prune"}


def test_controls_every_non_bare_spelling_is_refused_and_bare_is_not():
    for spelling in (
        "git -C /repo worktree add x --detach y",
        "git -C <main checkout> worktree add <dir> --detach <sha>",
        'git -C "$(git rev-parse --show-toplevel)" worktree add <dir> --detach <sha>',
        'git -C "$ROOT" worktree add <dir>',
        'git -c user.name="Sysop Bot" worktree add <dir> --detach <sha>',
        "git -c core.hooksPath=/dev/null worktree remove <dir>",
        "git --git-dir=/repo/.git worktree add x",
        "git --work-tree /repo worktree remove x",
        "git --no-pager worktree remove x",
        "git \\\n    worktree remove x",
        "GIT_DIR=x git worktree add <dir>",
        "cd <main checkout> && git worktree add <dir> --detach <sha>",
    ):
        assert non_bare_spellings(f"run `{spelling}` now"), f"not refused: {spelling!r}"
    assert not non_bare_spellings("run `git worktree add x --detach y` now")
    assert not non_bare_spellings("run `git worktree remove --force <dir>` now"), (
        "an option AFTER the subcommand is the bare form, and the rule binds it"
    )


def test_controls_a_commented_out_rule_is_not_read_as_live():
    """W1b: the quoted-string scan this parser replaced read `# "Bash(...)",` as a live rule."""
    text = 'LOOP_ALLOW = {\n    # "Bash(git worktree add:*)",\n    "Bash(git add:*)",  # "Bash(x:*)"\n}\n'
    assert _loop_allow(text) == {"Bash(git add:*)"}


def test_controls_a_computed_loop_allow_element_fails_naming_loop_allow():
    text = 'LOOP_ALLOW = {\n    "Bash(git worktree " + "add:*)",\n}\n'
    try:
        _loop_allow(text)
    except AssertionError as exc:
        assert "LOOP_ALLOW" in str(exc), f"the failure does not name LOOP_ALLOW: {exc}"
    else:
        raise AssertionError("a computed LOOP_ALLOW element was accepted by the parser")
