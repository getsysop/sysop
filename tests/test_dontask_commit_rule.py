"""`Q-665` / `Q-079` (Phase 420): the seeded `docs:` commit rule binds the commits the skills send.

Until Phase 420 the template seeded `Bash(git commit -m docs:*)`, and under `dontAsk` it bound no
spelling of a `docs:` commit (probes c2, u1, u2). The rule is now `Bash(git commit -m "docs: *)`,
and the promotion and demotion commits, which wrapped their message over three lines and were
denied even under the new rule (n3), pass their body as a second `-m` (n6).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from _bash_rule_match import binds

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "core" / "companion" / ".claude" / "settings.json"
SKILLS = REPO / "core" / "skills"
DOCS_RULE = 'Bash(git commit -m "docs: *)'
RETIRED_RULE = "Bash(git commit -m docs:*)"

# (probe, rule seeded beside the template's, command, admitted) — PHASE_LOG.md § Phase 420.
MEASURED = [
    ("c2", RETIRED_RULE, 'git commit -m "docs: probe c2"', False),
    ("u1", RETIRED_RULE, "git commit -m docs:probe-u1", False),
    ("u2", RETIRED_RULE, "git commit -m docs: probe u2", False),
    ("r1", 'Bash(git commit -m "docs:*)', 'git commit -m "docs: probe r1"', False),
    ("r2", DOCS_RULE, 'git commit -m "docs: probe r2"', True),
    ("n1", DOCS_RULE, 'git commit -m "fix: probe n1"', False),
    ("n3", DOCS_RULE, 'git commit -m "docs: promote 2 conventions from Round 3\n\n'
                      'Promotion summary: 2 total (1 mechanical / 1 prose)"', False),
    ("n5", DOCS_RULE, 'git commit -m "docs: probe $(touch pwned5)"', False),
    ("n6", DOCS_RULE, 'git commit -m "docs: promote 2 conventions from Round 3" '
                      '-m "Promotion summary: 2 total (1 mechanical / 1 prose)"', True),
    ("n7", DOCS_RULE, 'git commit -m "docs: probe n7" -m "body $(touch pwned7)"', False),
    ("n8", "Bash(git commit -m:*)", 'git commit -m "docs: probe n8\n\nbody line"', True),
    ("g1", "Bash(gh pr list:*)", 'gh pr list --head "feat/x" --base main --state open \\\n'
     "  --json number,isDraft,isCrossRepository \\\n"
     "  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]\n"
     "        | if length == 1 then .[0] else empty end'", True),
    ("g3", "Bash(gh pr list:*)", 'gh pr list --head "$(git branch --show-current)" --base main '
     "--state open --json number --jq '.[] | .number'", False),
]


@pytest.mark.parametrize("probe,rule,command,admitted", MEASURED, ids=[m[0] for m in MEASURED])
def test_the_model_reproduces_each_probe(probe, rule, command, admitted):
    assert binds(rule, command) is admitted, f"{probe}: the model disagrees with the measurement"


def test_the_model_refuses_an_unquoted_redirect_or_pipe():
    # Phase 380's round measured a redirect denied; a `|` outside quotes is a split the caller
    # owes (Phase 420's round, lens B). Inside quotes neither splits (g1).
    assert not binds(DOCS_RULE, 'git commit -m "docs: x" > sysop/runtime/commit.log')
    assert not binds(DOCS_RULE, 'git commit -m "docs: x" | cat')
    assert binds(DOCS_RULE, 'git commit -m "docs: x > y | z"')


def _template_allow() -> list[str]:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))["permissions"]["allow"]


def test_the_template_seeds_the_rule_that_binds_and_not_the_retired_one():
    allow = _template_allow()
    assert DOCS_RULE in allow
    assert RETIRED_RULE not in allow, "the retired rule binds no docs: commit (probes c2, u1, u2)"


# A `docs:` commit in any spelling: either quote or none, flags before `-m` (Phase 420's round,
# lens A: a single-quoted message or a `--no-verify` before `-m` walked past a scan keyed to
# `git commit -m "docs: `).
_DOCS_COMMIT = re.compile(r"""^git commit\b(?:\s+--?[\w-]+)*\s+-m\s*['"]?docs:""", re.I)


def _fenced_commit_lines():
    """Each `git commit` part of a line in any fence of a shipped skill file, labelled or not."""
    out = []
    for path in sorted(SKILLS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for fence in re.findall(r"```[\w-]*\n(.*?)```", text, re.S):
            for line in fence.splitlines():
                for part in re.split(r"\s*(?:&&|\|\||;|\|)\s*", line.strip()):
                    if part.startswith("git commit"):
                        out.append((path.relative_to(REPO).as_posix(), part))
    return out


def _docs_commits():
    return [c for c in _fenced_commit_lines() if _DOCS_COMMIT.match(c[1])]


def test_the_scan_finds_the_docs_commits():
    # 15 at Phase 420. A floor below the count let the loss of one pass (Phase 420's round).
    assert len(_docs_commits()) >= 15, f"the fence scan lost docs commits: {len(_docs_commits())}"


def test_the_docs_commit_pattern_reads_every_spelling():
    for spelling in ('git commit -m "docs: x"', "git commit -m 'docs: x'", "git commit -m docs:x",
                     'git commit --no-verify -m "docs: x"', 'git commit -q -m "docs: x"'):
        assert _DOCS_COMMIT.match(spelling), spelling
    assert _DOCS_COMMIT.match('git commit -m "Docs: x"'), "a capitalised prefix is still a docs commit"
    assert not _DOCS_COMMIT.match('git commit -m "fix: docs: x"')


@pytest.mark.parametrize("path,command", _docs_commits())
def test_every_docs_commit_binds_the_seeded_rule(path, command):
    assert command.count('"') % 2 == 0, (
        f"{path}: {command!r} opens a message it does not close on the line; a message over "
        "several lines does not bind a ` *` rule under dontAsk (probe n3). "
        "Pass the body as a second -m."
    )
    assert binds(DOCS_RULE, command), f"{path}: {command!r} does not bind {DOCS_RULE}"
