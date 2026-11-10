"""`/security-audit` and `/codebase-review` Step 2a: a map section glob resolves with `:(glob)`.

THE DEFECT. Both skills' unmatched-file checks (2a-1, 2a-2) told the runner to match files to map
sections by "derived-root prefix + extension", because a plain pathspec has no `**`: handed
`api/**/*.py`, `git ls-files` drops the direct child `api/server.py`. The premise was true and the
workaround coarser than the glob in both directions — prefix plus extension cannot tell `src/*.py`'s
`src/top.py` from `src/a/b.py`. Git's `:(glob)` magic means what the map means, and
`security_partition.py`'s `resolve_glob` already used it, so two resolvers with different semantics
read the same maps. The stale-section sweep ran the plain pathspec as written, so a section whose
files were all direct children of a `**/` glob read as stale.

WHAT THIS PINS. The command each skill now prescribes is read OUT OF the skill text, not retyped
here, expanded over a fixture map and run in a fixture repo. So the test fails if the prescribed
command is removed, loses `:(glob)`, or stops returning exactly the files outside every glob —
direct children and nested files matched, `src/a/b.py` against `src/*.py` unmatched, a file
outside every root never listed. It also checks that the one-command form equals the union form
(root listing minus `security_partition.resolve_glob` over every concrete glob), which is the
agreement the change exists to buy, and that the two skills carry one resolution paragraph.

WHAT IT CANNOT DO. It reads the prescribed shapes, not how a runner derives roots from a map; the
roots here are given. Brace expansion and placeholder dropping are the runner's work, done by this
test's expander the way the paragraph says, so a paragraph that stopped saying so would be caught
only by the text assertions.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = {
    name: ROOT / "core" / "skills" / name / "SKILL.md"
    for name in ("security-audit", "codebase-review")
}
PARTITION = ROOT / "core" / "companion" / "scripts" / "security_partition.py"

_SPAN = re.compile(r"`(git ls-files -- [^`]+)`")
_STALE = re.compile(r"run `(?P<cmd>git ls-files -- [^`]*:\(glob\)[^`]*)` over its concrete globs")
_PARA = re.compile(r"^\*\*Resolving a section glob\.\*\*.*$", re.M)


def _text(name: str) -> str:
    return SKILLS[name].read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.index("\n### ", start + 1)
    return text[start:end]


def _unmatched_command(name: str) -> str:
    """The command 2a-1 prescribes, verbatim (an inline span: a second ```bash block holding
    `git ls-files` would break 2a-0's own extractor in `test_skill_positional_substitution.py`)."""
    sec = _section(_text(name), "### 2a-1. ")
    cmds = [c for c in _SPAN.findall(sec) if c.startswith("git ls-files") and "exclude" in c]
    assert len(cmds) == 1, (
        f"{name}: 2a-1 must prescribe exactly one `git ls-files … ':(glob,exclude)<glob>' …` "
        f"command; found {cmds!r}"
    )
    return cmds[0]


def _stale_command(name: str) -> str:
    text = _text(name)
    hits = _STALE.findall(text)
    assert len(hits) == 1, f"{name}: the stale-section sweep's `:(glob)` command is missing: {hits!r}"
    return hits[0]


def _expand_braces(glob: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", glob)
    if not m:
        return [glob]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out += _expand_braces(glob[: m.start()] + alt + glob[m.end():])
    return out


def _concrete(globs: list[str]) -> list[str]:
    """What the paragraph tells the runner to do: drop `<…>` globs per glob, expand braces."""
    out: list[str] = []
    for g in globs:
        if "<" in g:
            continue
        out += _expand_braces(g)
    return out


def _argv(template: str, slots: dict[str, list[str]]) -> list[str]:
    """Expand a prescribed template: a quoted word holding `<slot>` repeats per value; `…` drops."""
    words = template.split()
    assert words[:3] == ["git", "ls-files", "--"], template
    argv = ["git", "ls-files", "--"]
    for w in words[3:]:
        if w == "…":
            continue
        assert w.startswith("'") and w.endswith("'"), f"unquoted pathspec word {w!r} in {template!r}"
        inner = w[1:-1]
        slot = next((s for s in slots if f"<{s}>" in inner), None)
        assert slot is not None, f"pathspec word {w!r} names no slot"
        argv += [inner.replace(f"<{slot}>", v) for v in slots[slot]]
    return argv


def _git(repo: Path, *argv: str) -> list[str]:
    out = subprocess.run(list(argv), cwd=repo, capture_output=True, check=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\n") if p)


# A map whose sections exercise each rule the paragraph states.
SECTION_GLOBS = [
    ["api/**/*.py", "<api module>/rate_limiting.py"],   # mixed header: the concrete glob binds
    ["api/routes/**/*.py"],                              # direct children only exist below
    ["src/*.py"],                                        # `*` must not cross a directory
    ["web/*.{ts,tsx}"],                                  # brace list, expanded first
    [r"app/\[id\]/*.tsx"],                               # a literal bracket, escaped in the map
    ["<frontend>/**/*.tsx"],                             # placeholder-only: binds nothing
]
ROOTS = ["api", "src", "web", "app"]

FILES = [
    "api/server.py",              # direct child of api/**/*.py
    "api/routes/foo.py",          # direct child of api/routes/**/*.py
    "api/routes/v1/bar.py",       # nested
    "api/other.ts",               # inside a root, outside every glob
    "src/top.py",
    "src/a/b.py",                 # src/*.py must NOT match it
    "web/a.ts",
    "web/b.tsx",
    "web/c.js",                   # outside the expanded braces
    "app/[id]/page.tsx",
    "app/i/page.tsx",             # what an unescaped `[id]` class would wrongly match
    "docs/notes.py",              # outside every root: never listed
]
EXPECTED_UNMATCHED = ["api/other.ts", "app/i/page.tsx", "src/a/b.py", "web/c.js"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    for argv in (["git", "init", "-q", "-b", "main"],
                 ["git", "config", "user.name", "t"],
                 ["git", "config", "user.email", "t@example.invalid"]):
        subprocess.run(argv, cwd=r, check=True)
    for rel in FILES:
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=r, check=True)
    return r


def _partition():
    spec = importlib.util.spec_from_file_location("security_partition_p476", PARTITION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_the_prescribed_command_lists_exactly_the_files_no_glob_matches(name: str, repo: Path):
    globs = _concrete([g for sec in SECTION_GLOBS for g in sec])
    argv = _argv(_unmatched_command(name), {"root": ROOTS, "glob": globs})
    got = _git(repo, *argv)
    assert got == EXPECTED_UNMATCHED, (
        f"{name}: 2a-1's command reported {got}, not {EXPECTED_UNMATCHED} — a direct child of a "
        "`**/` glob, a nested file, or a file outside every root was misread"
    )


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_the_one_command_form_equals_the_root_listing_minus_the_partition_union(name, repo):
    """The coverage audit and the residual partition must agree on what a section binds."""
    mod = _partition()
    globs = _concrete([g for sec in SECTION_GLOBS for g in sec])
    union: set[str] = set()
    for g in globs:
        union |= mod.resolve_glob(str(repo), g)
    under_roots = set(_git(repo, "git", "ls-files", "--", *ROOTS))
    argv = _argv(_unmatched_command(name), {"root": ROOTS, "glob": globs})
    assert set(_git(repo, *argv)) == under_roots - union


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_the_stale_sweep_binds_a_section_of_direct_children(name: str, repo: Path):
    template = _stale_command(name)
    # api/routes/**/*.py over a tree holding only direct children: not stale.
    (repo / "api/routes/v1/bar.py").unlink()
    subprocess.run(["git", "rm", "-q", "--cached", "api/routes/v1/bar.py"], cwd=repo, check=True)
    assert _git(repo, *_argv(template, {"glob": ["api/routes/**/*.py"]})) == ["api/routes/foo.py"]
    # The plain pathspec the sweep used to run reads that section as stale.
    assert _git(repo, "git", "ls-files", "--", "api/routes/**/*.py") == []
    # src/*.py does not stay live on a nested file alone.
    assert _git(repo, *_argv(template, {"glob": ["src/*.py"]})) == ["src/top.py"]


def test_both_skills_carry_one_resolution_paragraph():
    paras = {name: _PARA.findall(_text(name)) for name in SKILLS}
    for name, found in paras.items():
        assert len(found) == 1, f"{name}: expected one 'Resolving a section glob' paragraph"
    a, b = (paras[n][0] for n in sorted(SKILLS))
    assert a == b, "the two skills' 'Resolving a section glob' paragraphs drifted apart"
    for clause in ("**zero or more**", "per glob, not per section", "Expand a brace list first",
                   r"\[id\]", "report the map unlocalized", "Pass the rest verbatim"):
        assert clause in a, f"the resolution paragraph lost {clause!r}"


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_the_prefix_and_extension_approximation_is_gone(name: str):
    text = _text(name)
    for retired in ("prefix + extension", "Prefix+extension", "Glob-matching caveat"):
        assert retired not in text, f"{name}: the retired approximation is back ({retired!r})"
    # 2a-2 resolves the other map the same way, not by its own matching rule.
    second = _section(text, "### 2a-2. ")
    assert "2a-1's command" in second and "check each code file against" not in second
    # Nor by an extension rule of its own (Phase 476's round, lens 2, L09).
    assert "extension" not in second, f"{name}: 2a-2 names an extension rule again"
    # 2a-0 (a)'s subtree test points at the same resolution (lens 2, L07).
    assert "resolved with `:(glob)`, as 2a-1 says" in _section(text, "### 2a-0. "), (
        f"{name}: 2a-0 (a) no longer says how a section glob resolves")
    # The runner passes `[…]` as git reads it; it does not escape brackets itself (lens 2, L08).
    para = _PARA.findall(text)[0]
    assert not re.search(r"escape (?:each|every|the|a)?\s*`?\[", para, re.I), (
        f"{name}: the paragraph tells the runner to escape brackets itself")
