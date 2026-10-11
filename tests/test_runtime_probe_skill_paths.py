"""The runtime-artifact probe and the skills that write under it must agree (Q-305).

`cleanup_worktrees.sh` refuses to reclaim a worktree holding anything under one
pathspec — `worktree_runtime_artifacts`, `sysop/runtime/` today — because that is
where shipped skills write gitignored records INSIDE a worktree: `/auto-build`'s
park verdict, and the pending-doc `/auto-fix`, `/auto-judge` and `/document-work`
each write for `/review-close` Step 3b to collect. Both are invisible to every
other probe in the script (gitignored), and a parked task's branch carries no
commit, so it classifies MERGED: the probe is the only thing standing between
`--clean` and the record (Q-023).

Nothing checked that the two sides agree. `tests/test_cleanup_worktrees_sh.py`
writes the path literally in its fixtures, so a skill that moved its scratch dir
— Phase 133 consolidated four of them into this home, and Phase 159b renamed one
— would leave the probe pointing at nothing while that whole module stayed green.

So both sides are DERIVED here, never retyped:

* the probe's pathspec is read out of the script's own function body;
* the write sites are read out of the shipped runner text — every
  `core/skills/*/SKILL.md` and `core/skills/_shared/*.md`, at HEAD. `REFERENCE.md`
  files are left out on purpose: they are editor-facing, and may quote a write
  as it was before a move, which is history, not an instruction anyone runs.

**The derivation grammar, stated because it is the part that can be wrong.** A
write is a write verb immediately before a path:

1. *Worktree-anchored* (any skill): `mkdir -p`, a `>` redirect, or `Write`
   followed within a few words by `<WORKTREE_PATH>/…`, `<worktree path>/…` or
   `<worktree>/…`. Reads (`test -f`, `Read`) and edits of tracked files (`Edit`)
   are not writes of scratch and are not collected.
2. *CWD-relative* (`/document-work` only): it runs with the worktree as its
   working directory, so its `mkdir -p <dir>` targets and its
   `pending_path = f"…"` literal are in-worktree writes with no anchor at all.

A path that is only an elision (`<worktree path>/…`) names nothing and is
skipped. One worktree-anchored write target is NOT scratch: the task body under `tasks/`,
which `/auto-build` and `/claim-task` tell the executor to write in the worktree
copy so it is committed on the branch. A committed file is visible to the
classifier's dirty check, so it needs no probe — it is the one allowlisted
prefix, and the allowlist is a stated weakness: a scratch dir moved under
`tasks/` would pass.

**Floors, because a derivation that finds nothing must not read as agreement.**
Zero sites fails; and each of the four writers this entry named must contribute
at least one scratch site, so a rewording the grammar no longer matches fails
here rather than quietly shrinking the checked set.

Precedents for the shape: `tests/test_install_runtime_gitignore.py`'s
`test_gitignore_append_covers_every_skill_asserted_runtime_dir` (derive tokens
from the skills, prefix-cover them, floor at one) and
`tests/test_venv_pyyaml_bootstrap.py` (copies of one fact across files, pinned).

The behavioural leg (`test_the_probe_protects_every_derived_site`) closes the
literal-fixture gap directly: each derived path is materialized in a fixture
worktree, gitignored, and the real script's `--clean` must keep every one.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/cleanup_worktrees.sh"
SKILLS = REPO_ROOT / "core/skills"

# The four writers Q-305 named, re-derived at this test's authoring (Phase 368):
# `grep -n 'runtime/' core/skills/{auto-build,auto-fix,auto-judge,document-work}/SKILL.md`.
NAMED_WRITERS = {"auto-build", "auto-fix", "auto-judge", "document-work"}
# How many in-worktree scratch writes the grammar derives per writer at authoring
# (Phase 368's round, lens 2): a floor of "at least one" let a write re-spelled out
# of the grammar's reach (`os.path.join(".pending-docs", …)`, `$WT/.auto-build/…`)
# drop out of the derivation silently while its sibling kept the floor met. A skill
# that genuinely adds or removes a write updates this, with the reason.
EXPECTED_SITES = {"auto-build": 4, "auto-fix": 2, "auto-judge": 2, "document-work": 2}
# Skills whose runner executes with the worktree as its working directory, so a
# bare relative path is an in-worktree write.
CWD_IS_WORKTREE = {"document-work"}
# Committed on the branch — see the module docstring.
TRACKED_PREFIXES = ("tasks/",)

_WT = r"<(?:WORKTREE_PATH|worktree path|worktree)>"
_PATH = r"([^\s\"`')]+)"
ANCHORED = [
    ("mkdir", re.compile(r"mkdir -p\s+\"?" + _WT + "/" + _PATH)),
    ("redirect", re.compile(r">\s*\"?" + _WT + "/" + _PATH)),
    ("Write", re.compile(r"\bWrite\b[^\n]{0,40}?`" + _WT + "/" + _PATH)),
]
CWD_RELATIVE = [
    ("mkdir", re.compile(r"mkdir -p\s+\"?([A-Za-z0-9_.][^\s\"`']*)")),
    ("pending_path", re.compile(r"pending_path\s*=\s*f?\"([^\"]+)\"")),
]

_GIT_DISCOVERY_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _env():
    return {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY_VARS}


def probe_pathspec(text: str | None = None) -> str:
    """The pathspec `worktree_runtime_artifacts` hands `git ls-files`, read from the
    function body itself."""
    text = SCRIPT.read_text() if text is None else text
    m = re.search(r"^worktree_runtime_artifacts\(\)\s*\{\n(.*?)^\}", text, re.S | re.M)
    assert m, "cleanup_worktrees.sh no longer defines worktree_runtime_artifacts()"
    specs = re.findall(r"--\s+'([^']+)'", m.group(1))
    assert len(specs) == 1, (
        f"expected exactly one quoted pathspec in worktree_runtime_artifacts(); "
        f"found {specs!r} — this guard reads it, so it must be unambiguous"
    )
    return specs[0]


def _runner_files():
    files = sorted(SKILLS.glob("*/SKILL.md")) + sorted(SKILLS.glob("_shared/*.md"))
    assert files, f"no runner text under {SKILLS}"
    return files


def derive_sites():
    """[(skill, how, path, line_no)] for every in-worktree write in the runner text."""
    sites = []
    for f in _runner_files():
        skill = f.parent.name
        for no, line in enumerate(f.read_text().splitlines(), 1):
            for how, rx in ANCHORED:
                for m in rx.finditer(line):
                    sites.append((skill, how, m.group(1), no))
            if skill in CWD_IS_WORKTREE:
                for how, rx in CWD_RELATIVE:
                    for m in rx.finditer(line):
                        sites.append((skill, how, m.group(1), no))
    return sites


def _elided(path: str) -> bool:
    """`<worktree path>/…` in prose names no path — `/auto-build` writes exactly that
    in a comment about placeholder substitution. Nothing to check, and nothing a
    move could change."""
    return path.strip("…./") == ""


def _scratch(sites):
    return [s for s in sites
            if not s[2].startswith(TRACKED_PREFIXES) and not _elided(s[2])]


def _covered(path: str, spec: str) -> bool:
    return (path.rstrip("/") + "/").startswith(spec)


def test_the_pathspec_is_read_from_the_script():
    spec = probe_pathspec()
    assert spec.endswith("/") and not spec.startswith("/"), (
        f"unexpected pathspec shape {spec!r}: the prefix comparison below assumes a "
        "repo-root-relative directory"
    )


def test_the_derivation_is_not_empty_and_reaches_every_named_writer():
    scratch = _scratch(derive_sites())
    assert scratch, (
        "derived ZERO in-worktree scratch writes from the shipped skills — the grammar "
        "no longer matches how they are written, and an empty set must not pass as "
        "agreement"
    )
    found = {s[0] for s in scratch}
    missing = NAMED_WRITERS - found
    assert not missing, (
        f"no in-worktree scratch write derived for {sorted(missing)}. Either the skill "
        "stopped writing inside the worktree (update NAMED_WRITERS, with the reason) or "
        "it is now worded in a way this grammar does not read — which would leave its "
        f"path unchecked. Derived: {sorted(set((s[0], s[2]) for s in scratch))}"
    )


def test_the_derivation_finds_exactly_the_census_per_writer():
    from collections import Counter
    got = Counter(s[0] for s in _scratch(derive_sites()))
    assert dict(got) == EXPECTED_SITES, (
        f"derived {dict(got)}, census {EXPECTED_SITES}. A drop means a write was "
        "re-worded out of the grammar's reach and its path is no longer checked; a "
        "change either way means updating EXPECTED_SITES, with the reason, after "
        "checking the new path sits under the probe."
    )


def test_every_in_worktree_scratch_write_is_under_the_probe():
    spec = probe_pathspec()
    scratch = _scratch(derive_sites())
    assert scratch  # the floor test above says why; repeated so this one cannot pass empty
    stray = [s for s in scratch if not _covered(s[2], spec)]
    assert not stray, (
        f"these skills write inside a worktree OUTSIDE the probe's pathspec {spec!r}, so "
        "cleanup_worktrees.sh --clean cannot see what they leave there and will reclaim "
        "the worktree as MERGED: "
        + "; ".join(f"{sk}/SKILL.md:{no} ({how}) {p}" for sk, how, p, no in stray)
    )


def _materialize(path: str, is_dir: bool) -> str:
    """A concrete relative file path for a derived site, placeholders filled in."""
    concrete = re.sub(r"<[^>]*>|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\{[^}]*\}", "x", path)
    concrete = concrete.rstrip("/")
    return concrete + "/probe.txt" if is_dir else concrete


def _git(cwd, *args, **kw):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          env=_env(), **kw)


def test_the_probe_protects_every_derived_site(tmp_path):
    """Run the real probe against the real derived paths, gitignored as they are in a
    consumer — not against a path a fixture typed."""
    files = sorted({_materialize(p, how == "mkdir")
                    for _sk, how, p, _no in _scratch(derive_sites())})
    assert files

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "-c", "init.defaultBranch=main", "init", "-q", str(repo), check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v, check=True)
    # Ignore each site's own directory, anchored — so a site moved anywhere is still
    # ignored here, and only the probe can be what protects it.
    ignore = sorted({"/" + str(Path(f).parent) + "/" for f in files})
    (repo / ".gitignore").write_text("".join(f"{p}\n" for p in ignore))
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-qm", "seed", check=True)

    holders = []
    for i, rel in enumerate(files):
        wt = tmp_path / f"wt-{i}"
        _git(repo, "worktree", "add", "-q", "-b", f"site/{i}", str(wt), check=True)
        target = wt / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"written where a skill writes: {rel}\n")
        # Precondition: invisible to every OTHER probe, so a pass means the runtime
        # probe saw it rather than the untracked-file arm.
        chk = _git(wt, "check-ignore", "-q", rel)
        assert chk.returncode == 0, f"fixture bug: {rel} is not ignored ({chk.stderr!r})"
        others = _git(wt, "ls-files", "--others", "--exclude-standard")
        assert others.returncode == 0 and others.stdout == "", others
        holders.append((wt, target))
    # The control: a worktree holding nothing is reclaimed, so `--clean` did run.
    control = tmp_path / "wt-control"
    _git(repo, "worktree", "add", "-q", "-b", "site/control", str(control), check=True)

    r = subprocess.run(["bash", str(SCRIPT), "--clean"], cwd=str(repo),
                       capture_output=True, text=True, env=_env())

    assert r.returncode == 0, r.stdout + r.stderr
    assert not control.exists(), f"--clean reclaimed nothing at all:\n{r.stdout}"
    lost = [str(t.relative_to(wt)) for wt, t in holders if not t.is_file()]
    assert not lost, (
        "cleanup_worktrees.sh --clean destroyed what a shipped skill writes inside a "
        f"worktree: {lost} — the probe's pathspec does not cover it"
    )
    assert f"Removed 1 worktree(s), skipped {len(holders)} active, 0 failed." in r.stdout, r.stdout


@pytest.mark.parametrize("moved, expect_stray", [
    ("<WORKTREE_PATH>/sysop/runtime/pending-docs/x.md", False),
    ("<WORKTREE_PATH>/.scratch/pending-docs/x.md", True),
])
def test_the_grammar_reads_a_moved_write(moved, expect_stray):
    """The guard's own discrimination, on a synthetic line: a write moved out from
    under the pathspec is still DERIVED (so it can fail), not silently unmatched."""
    line = f"Use the Write tool to create `{moved}`:"
    got = [m.group(1) for _how, rx in ANCHORED for m in rx.finditer(line)]
    assert got == [moved.split(">/", 1)[1]], got
    assert (not _covered(got[0], probe_pathspec())) is expect_stray
