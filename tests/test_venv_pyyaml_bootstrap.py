"""Every shipped script that needs PyYAML must resolve the project venv (Phase 182).

The filed defect was four sites in `claim_task.sh`. Derived from the tree, the
class was larger: `sitrep_survey.py`, `next_task.py`,
`backfill_completed_dates.py` and `scope_overlap.py` all reached PyYAML through
whatever `python3` PATH produced, with no resolution of their own. On a PEP-668
host — every modern distro, and Homebrew macOS, where `pip install` into the
system interpreter is an *error* — that meant:

  * `/sitrep` was **entirely dead**: `sitrep_survey.py` is the skill's only Bash
    call, and it exited 1 on `import yaml`;
  * `/roadmap`'s survey overlay failed (loudly — that skill prescribes a
    "survey skipped" note);
  * `backfill_completed_dates.py`, documented as step 4 of the roadmap
    migration, raised a bare `ModuleNotFoundError`;
  * `scope_overlap.py` returned **exit 0 with `overlaps: []`** on the advisory
    that exists to stop wasted parallel work. Its index degrade *did* emit a
    note naming PyYAML, so it was not silent — an earlier draft of this
    docstring said it was, and the phase's own round refuted that by running
    the pre-fix script. What the note never covered is the lock side:
    `_parse_lock_file`'s `ImportError` arm returns `{}` with no note, so
    in-flight locks stayed counted with empty `workspace`/`branch`/`paths`.

`validate_tasks.py` already carried a bootstrap and is the precedent, but it had
two gaps this phase closes in the same edit: it globbed only `.venv/` (not
`venv/`, which `install.sh::pick_python_with_yaml`, `run_checks.sh` and
`self_check.sh` all support) and it globbed **CWD-relative**, so it resolved
nothing from a subdirectory or a worktree.

Two things are pinned here:

1. **The copies do not drift.** The block is inline in five files rather than
   shared, and that is a constraint rather than a preference: it must run before
   any import can be trusted, and `_log.py`'s header records that
   `validate_tasks.py` and `next_task.py` stay standalone for pre-commit. What
   makes inline duplication safe is a guard that pins the copies identical —
   the Phase-126 treatment of the heredoc idiom.
2. **It actually resolves.** Each script is executed under a real interpreter
   whose `yaml` is shadowed, against a fixture venv, from three different
   working directories.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"

# The four scripts whose bootstrap is FATAL (they cannot work without yaml).
FATAL = [
    "validate_tasks.py",
    "sitrep_survey.py",
    "next_task.py",
    "backfill_completed_dates.py",
    "clear_user_action.py",
]
# The one whose resolution is deliberately non-fatal: every yaml use in it is a
# local import on a documented degrade path.
SOFT = "scope_overlap.py"

# The resolution block, sliced between two anchors rather than matched by a
# hand-written regex. The round's guard lens showed the regex was a liability
# twice over: its match window ended at the final `break`, so a line appended
# *after* it could kill resolution outright with the suite green; and it
# reddened on a behaviour-preserving comment added inside the block.
#
# Slicing to end-of-block plus a required-token check gives the same drift
# protection without either failure mode, and without a second copy of the code
# living in the test file where it can rot independently.
_BLOCK_START = "_roots = []"
_BLOCK_END = "if _hit:"

# Semantic properties the block must have. Each is a behaviour the round proved
# was either absent or unguarded; the behavioural tests below prove they work,
# these prove they are still present in every copy.
_REQUIRED = [
    # PROBE, don't assume: commit a candidate only once yaml imports from it.
    "sys.path.insert(0, _site)",
    "sys.path.remove(_site)",
    # Both venv layouts, at EVERY root — not `.venv` or `venv` per root.
    'for _layout in (".venv", "venv"):',
    # Script-anchored roots before the CWD.
    # `list(...)` before the slice, not `parents[:3]`: slicing parents is
    # 3.10+, and this block runs only on interpreters without PyYAML —
    # stock macOS /usr/bin/python3 3.9 among them.
    "list(Path(__file__).resolve().parents)[:3]",
    "Path.cwd() not in _roots",
    # The main checkout, with git's discovery vars stripped (BR ISSUE-0048).
    '"git", "rev-parse", "--git-common-dir"',
    "cwd=str(Path(__file__).resolve().parent)",
    "timeout=5,",
    '"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",',
]


def _normalise(text: str) -> str:
    """Drop comment-only lines, then collapse leading whitespace.

    Comments are stripped because the round's negative control NC5 — adding an
    explanatory comment *inside* the loop, identically in all five files —
    reddened two tests. A byte-pin that punishes annotation is over-strict, and
    it gives the maintainer no hint that a regex is what needs updating.
    """
    kept = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    return re.sub(r"\n\s*", "\n", "\n".join(kept))


def _loop(name: str) -> str:
    """The whole resolution block, from its first line to its last."""
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert _BLOCK_START in text, (
        f"{name} has no venv PyYAML resolution block. A bare "
        f"`python3 sysop/scripts/{name}` would fail on a PEP-668 host — "
        f"upstream #321."
    )
    i = text.index(_BLOCK_START)
    # The block ends at the LAST of the three `if _hit:` guards, so the slice
    # covers every line that can affect the outcome.
    j = text.rindex(_BLOCK_END)
    j = text.index("break", j) + len("break")
    return _normalise(text[i:j])


class TestTheCopiesDoNotDrift:
    @pytest.mark.parametrize("name", [*FATAL, SOFT])
    def test_every_yaml_script_carries_the_resolution(self, name):
        block = _loop(name)
        missing = [tok for tok in _REQUIRED if tok.replace(" ", "") not in
                   block.replace(" ", "")]
        assert not missing, (
            f"{name}'s venv resolution lost required behaviour: {missing}. "
            f"Each of these was absent or unguarded when Phase 182's round ran."
        )

    def test_all_five_copies_are_identical(self):
        seen = {name: _loop(name) for name in [*FATAL, SOFT]}
        distinct = set(seen.values())
        assert len(distinct) == 1, (
            "the venv resolution has drifted between copies — fix them together:\n"
            + "\n".join(f"--- {k} ---\n{v}" for k, v in seen.items())
        )

    @pytest.mark.parametrize("name", [*FATAL, SOFT])
    def test_the_resolution_runs_only_after_import_yaml_fails(self, name):
        """Prepending a venv's site-packages ahead of a working interpreter's own
        would shadow more than yaml, so the resolution must sit on the failure
        path — never unconditionally. Checked by walking back from the loop over
        comments and blanks to the first line of real code."""
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        head = text[: text.index("_roots = []")]
        preceding = [
            ln.strip() for ln in head.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert preceding and preceding[-1] == "except ImportError:", (
            f"{name}: the resolution is not gated on an ImportError — it would "
            f"reorder sys.path on hosts that never needed it. Preceding code line "
            f"was {preceding[-1]!r}"
        )

    @pytest.mark.parametrize("name", FATAL)
    def test_the_error_names_a_pep668_safe_remedy(self, name):
        """`pip install pyyaml` is exactly what a PEP-668 host refuses, so naming
        only that is naming no remedy at all."""
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "python3 -m venv .venv" in text, name
        assert ".venv/bin/pip install pyyaml" in text, name


# ── execution: does it actually resolve? ────────────────────────────────────

@pytest.fixture(scope="session")
def yamlless_python(tmp_path_factory):
    """A real interpreter that cannot `import yaml`.

    Shadows `yaml` via PYTHONPATH, which is searched before site-packages —
    everything else about the interpreter still works. A shim that simply
    `exit 1`s would pass against a "fix" that merely deleted the probe.
    """
    d = tmp_path_factory.mktemp("yamlless")
    (d / "yaml.py").write_text("raise ImportError(\"No module named 'yaml'\")\n")
    shim = d / "python3"
    shim.write_text(f'#!/bin/sh\nPYTHONPATH="{d}" exec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return shim


@pytest.fixture
def consumer(tmp_path):
    """A consumer-shaped tree: <root>/sysop/scripts/ with the real scripts."""
    root = tmp_path / "proj"
    (root / "sysop" / "scripts").mkdir(parents=True)
    for name in [*FATAL, SOFT, "_log.py"]:
        (root / "sysop" / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=root, check=True, capture_output=True)
    # A queue with real content, so each script has something only a successful
    # YAML parse can produce. An empty queue lets a script "succeed" by doing
    # nothing, which is how a resolution failure hides.
    (root / "tasks").mkdir(exist_ok=True)
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 1\ncurrent_focus: 1\n"
        "phases:\n  - number: 1\n    name: P1\n    status: in_progress\n"
        "    current_focus: true\n"
        "tasks:\n  - id: FEAT-A\n    status: open\n    phase: 1\n"
        "    effort: Low\n    body: a.md\n")
    (root / "tasks" / "a.md").write_text("# A\n\n## Key files\n\n- `src/pay.py`\n")
    return root


def _fake_venv(root: Path, kind: str = ".venv") -> Path:
    """A venv-shaped site-packages carrying the running interpreter's PyYAML.

    Copied rather than symlinked to the real venv so the fixture cannot pass by
    accident through the interpreter's own sys.path.
    """
    tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = root / kind / "lib" / tag / "site-packages"
    site.mkdir(parents=True)
    import yaml
    src = Path(yaml.__file__).parent
    dst = site / "yaml"
    dst.mkdir()
    for f in src.iterdir():
        if f.is_file():
            (dst / f.name).write_bytes(f.read_bytes())
    # PyYAML's C extension is optional; the pure-Python loader is enough here.
    return site


# What each script PRODUCES when PyYAML really resolved. The round showed that
# nine of ten assertions here were negative (`"requires PyYAML" not in stderr`)
# and keyed on a string that lives in the script under test — so a copy edit to
# an error message silently converted nine resolution proofs into vacuous ones,
# and a line appended *after* the resolution loop (outside the drift regex's
# match window) could kill resolution outright with the suite green.
_RESOLVED = {
    "sitrep_survey.py": (0, "SITREP"),
    "next_task.py": (0, "## Next Task"),
    "backfill_completed_dates.py": (0, "done task(s) without completed_date"),
    # Phase 237. The marker is the DRY-RUN line, which names the task and the
    # transition — output only a successful parse of the index can produce.
    # A `--help` arm would pass with the resolution deleted, which is the trap
    # the backfill arm above already records.
    "clear_user_action.py": (0, "would set FEAT-UA user_action: true"),
}


def _assert_resolved(name: str, r) -> None:
    """Assert the script did its job — not merely that it stayed quiet."""
    code, marker = _RESOLVED[name]
    assert r.returncode == code, (name, r.returncode, r.stdout[-400:], r.stderr[-400:])
    assert marker in r.stdout, (name, r.stdout[:400], r.stderr[:400])


def _empty_venv(root: Path, kind: str = ".venv") -> Path:
    """A venv-shaped directory with no PyYAML in it.

    The single most productive fixture of Phase 182's round: the first fix
    stopped at the first venv-*shaped* directory, so one of these disabled the
    entire search — including the main-checkout arm that was the point of it.
    """
    tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = root / kind / "lib" / tag / "site-packages"
    site.mkdir(parents=True)
    return site


def _run(script: Path, *args, cwd: Path, py: Path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run([str(py), str(script), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env)


class TestItActuallyResolves:
    @pytest.mark.parametrize("kind", [".venv", "venv"])
    def test_validate_tasks_resolves_from_the_repo_root(self, consumer, yamlless_python, kind):
        _fake_venv(consumer, kind)
        r = _run(consumer / "sysop/scripts/validate_tasks.py", "--quiet",
                 cwd=consumer, py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, r.stderr
        assert "ModuleNotFoundError" not in r.stderr, r.stderr

    def test_validate_tasks_still_fails_loudly_with_no_venv(self, consumer, yamlless_python):
        r = _run(consumer / "sysop/scripts/validate_tasks.py", "--quiet",
                 cwd=consumer, py=yamlless_python)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "requires PyYAML" in r.stderr
        assert "python3 -m venv .venv" in r.stderr

    def test_sitrep_survey_resolves(self, consumer, yamlless_python):
        """`/sitrep`'s only Bash call. Before this, the whole skill was dead on a
        PEP-668 host."""
        _fake_venv(consumer)
        r = _run(consumer / "sysop/scripts/sitrep_survey.py", cwd=consumer,
                 py=yamlless_python)
        _assert_resolved("sitrep_survey.py", r)

    def test_next_task_resolves(self, consumer, yamlless_python):
        _fake_venv(consumer)
        r = _run(consumer / "sysop/scripts/next_task.py", cwd=consumer,
                 py=yamlless_python)
        _assert_resolved("next_task.py", r)
        assert "FEAT-A" in r.stdout, r.stdout

    def test_backfill_resolves(self, consumer, yamlless_python):
        # --dry-run, not --help: --help never touches YAML, so it would pass with
        # the resolution deleted.
        _fake_venv(consumer)
        r = _run(consumer / "sysop/scripts/backfill_completed_dates.py", "--dry-run",
                 cwd=consumer, py=yamlless_python)
        _assert_resolved("backfill_completed_dates.py", r)

    def test_clear_user_action_resolves(self, consumer, yamlless_python):
        """Phase 237's `user_action` clearing helper.

        Writes its OWN task rather than flagging the shared `FEAT-A`: that task
        is asserted on by `test_next_task_resolves`, and `user_action: true`
        would drop it out of the agent pool — a fixture edit that silently
        weakens a sibling proof is the same class this module exists to catch.
        """
        _fake_venv(consumer)
        index = consumer / "tasks" / "index.yml"
        index.write_text(
            index.read_text()
            + "  - id: FEAT-UA\n    status: open\n    phase: 1\n"
              "    effort: Low\n    user_action: true\n    body: ua.md\n"
        )
        r = _run(consumer / "sysop/scripts/clear_user_action.py", "--dry-run",
                 "FEAT-UA", cwd=consumer, py=yamlless_python)
        _assert_resolved("clear_user_action.py", r)
        assert index.read_text().count("user_action: true") == 1, (
            "--dry-run wrote to the index"
        )

    def test_clear_user_action_still_fails_loudly_with_no_venv(
            self, consumer, yamlless_python):
        r = _run(consumer / "sysop/scripts/clear_user_action.py", "FEAT-A",
                 cwd=consumer, py=yamlless_python)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "requires PyYAML" in r.stderr
        assert "python3 -m venv .venv" in r.stderr

    def test_scope_overlap_runs_under_a_resolved_interpreter(
            self, consumer, yamlless_python):
        """Scope, stated because the assertions are weaker than an earlier name
        for this test claimed: it proves the script *runs* under a resolved
        interpreter and exits 0. It does not assert anything about the advisory's
        content, so it must not be read as pinning "no false all-clear"."""
        _fake_venv(consumer)
        r = _run(consumer / "sysop/scripts/scope_overlap.py", "--json", "FEAT-A",
                 cwd=consumer, py=yamlless_python)
        assert r.returncode == 0, (r.returncode, r.stderr)
        # The content assertion is the whole point. `scope_overlap` degrades
        # non-fatally, so exit 0 is what a *broken* resolution also produces —
        # the round showed a mutation that killed resolution here surviving
        # every assertion this test used to make. `key_files` is reachable only
        # after PyYAML has parsed the index AND the body.
        got = json.loads(r.stdout)
        assert got["candidate_scope_source"] == "key_files", got
        assert got["candidate_paths"] == ["src/pay.py"], got
        assert got["notes"] == [], got

    def test_resolution_survives_a_run_from_a_subdirectory(self, consumer, yamlless_python):
        """The pre-existing glob was CWD-relative, so it found nothing from
        anywhere but the root — the gap that made it look present but inert."""
        _fake_venv(consumer)
        sub = consumer / "src" / "deep"
        sub.mkdir(parents=True)
        r = _run(consumer / "sysop/scripts/sitrep_survey.py", cwd=sub, py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, r.stderr

    def test_resolution_survives_a_run_from_a_linked_worktree(self, consumer, yamlless_python):
        """A worktree carries the scripts but never a `.venv`, so a CWD-anchored
        probe answers the wrong question there too."""
        _fake_venv(consumer)
        # The venv must not be committed, or `git worktree add` would check one
        # out and the fixture would pass without ever exercising the ancestor
        # walk. Consumers gitignore it for the same reason.
        (consumer / ".gitignore").write_text(".venv/\nvenv/\n")
        subprocess.run(["git", "add", "-A"], cwd=consumer, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=consumer, check=True,
                       capture_output=True)
        wt = consumer.parent / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=consumer, check=True, capture_output=True)
        assert not (wt / ".venv").exists()
        r = _run(wt / "sysop/scripts/sitrep_survey.py", cwd=wt, py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, r.stderr

    def test_resolution_survives_a_run_from_outside_the_repo_entirely(
            self, consumer, tmp_path, yamlless_python):
        """`python3 /abs/path/to/sysop/scripts/sitrep_survey.py` from an unrelated
        CWD. This is what pins the git probe to the *script's* directory rather
        than the caller's — with the caller's, the probe answers about whatever
        repo the operator happens to be standing in, or nothing at all."""
        _fake_venv(consumer)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        r = _run(consumer / "sysop/scripts/sitrep_survey.py", cwd=outside,
                 py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, r.stderr

    def test_the_git_probe_asks_about_the_script_not_the_caller(
            self, consumer, tmp_path, yamlless_python):
        """The one case where every other arm is exhausted: the script is a
        **worktree's** copy, invoked by absolute path, from a CWD that is not a
        git repo at all. The ancestor walk reaches only the worktree (no venv)
        and a caller-anchored probe reaches nothing — so the venv is found only
        if the probe runs in the script's own directory.

        Written because the author-side battery showed this parameter had zero
        behavioural coverage: the earlier outside-the-repo test was silently
        satisfied by the ancestor walk.
        """
        _fake_venv(consumer)
        (consumer / ".gitignore").write_text(".venv/\nvenv/\n")
        subprocess.run(["git", "add", "-A"], cwd=consumer, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=consumer, check=True,
                       capture_output=True)
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=consumer, check=True, capture_output=True)
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert not (wt / ".venv").exists()
        assert not (tmp_path / ".venv").exists(), "fixture invalid: an ancestor has a venv"
        r = _run(wt / "sysop/scripts/sitrep_survey.py", cwd=outside, py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, r.stderr

    def test_resolution_works_in_a_tree_that_is_not_a_git_repo(
            self, tmp_path, yamlless_python):
        """A tarball/zip install — a first-class "any agent or none" path — has no
        git dir, so the git probe returns nothing and the ancestor walk is the
        only thing left. Without it, `python3 sysop/scripts/…` from a
        subdirectory of such a tree resolves nothing."""
        root = tmp_path / "unpacked"
        (root / "sysop" / "scripts").mkdir(parents=True)
        for name in [*FATAL, SOFT, "_log.py"]:
            (root / "sysop" / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
        _fake_venv(root)
        sub = root / "docs"
        sub.mkdir()
        r = _run(root / "sysop/scripts/sitrep_survey.py", cwd=sub, py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, r.stderr

    # Uniform 2 since Phase 219. `sitrep_survey.py` was the one of the five that
    # exited 1 for a missing dependency — found by the round, not by this test,
    # because the exception was written INTO the parametrization. The house
    # contract is 1 = the caller's input is wrong, 2 = the environment is, and
    # `/review-close` Step 4a routes the two apart in terms.
    @pytest.mark.parametrize("name,code", [(n, 2) for n in FATAL])
    def test_every_fatal_script_names_the_pep668_remedy_when_it_gives_up(
            self, consumer, yamlless_python, name, code):
        """Behavioural twin of the text guard: the remedy must reach stderr from
        each script, not merely appear in each source file."""
        r = _run(consumer / "sysop" / "scripts" / name, cwd=consumer, py=yamlless_python)
        assert "python3 -m venv .venv" in r.stderr, (name, r.stderr)
        assert ".venv/bin/pip install pyyaml" in r.stderr, (name, r.stderr)
        assert r.returncode == code, (name, r.returncode, r.stderr)

    @pytest.mark.parametrize("name", FATAL)
    def test_every_fatal_script_resolves_a_no_dot_venv(
            self, consumer, yamlless_python, name):
        """The `venv/` arm, proved per script rather than once — the copies are
        pinned identical, but identity is not evidence that the shared shape is
        right."""
        _fake_venv(consumer, "venv")
        r = _run(consumer / "sysop" / "scripts" / name, cwd=consumer, py=yamlless_python)
        assert "requires PyYAML" not in r.stderr, (name, r.stderr)

    def test_an_empty_venv_does_not_abort_the_search(self, consumer, tmp_path,
                                                     yamlless_python):
        """A worktree with its own yaml-less `.venv`, and the real one in the
        main checkout. The block must reject the empty candidate and keep
        going — stopping there is what made the git-common-dir arm unreachable
        in the very configuration it was added for."""
        _fake_venv(consumer)
        (consumer / ".gitignore").write_text(".venv/\nvenv/\n")
        subprocess.run(["git", "add", "-A"], cwd=consumer, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=consumer, check=True,
                       capture_output=True)
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=consumer, check=True, capture_output=True)
        _empty_venv(wt)
        r = _run(wt / "sysop/scripts/sitrep_survey.py", cwd=wt, py=yamlless_python)
        _assert_resolved("sitrep_survey.py", r)

    def test_an_empty_dot_venv_does_not_shadow_a_working_plain_venv(
            self, consumer, yamlless_python):
        """Same root, both layouts, only `venv/` usable. The first fix used
        `.venv or venv`, so the empty `.venv` won and the working one was never
        looked at."""
        _empty_venv(consumer, ".venv")
        _fake_venv(consumer, "venv")
        r = _run(consumer / "sysop/scripts/sitrep_survey.py", cwd=consumer,
                 py=yamlless_python)
        _assert_resolved("sitrep_survey.py", r)

    def test_an_unrelated_cwd_venv_does_not_win_over_the_scripts_own_tree(
            self, consumer, tmp_path, yamlless_python):
        """Running a Sysop script by path from some other project's directory
        must use the script's own tree. CWD-first meant a stranger's venv was
        consulted before the consumer's — and a `uv`/`poetry` venv without
        PyYAML then failed the run outright.

        Uses `backfill_completed_dates.py` rather than `sitrep_survey.py`
        because sitrep has its own must-be-inside-a-repo precondition, which
        would fail this fixture for a reason that has nothing to do with the
        resolution."""
        _fake_venv(consumer)
        foreign = tmp_path / "someone-elses-project"
        _empty_venv(foreign)
        r = _run(consumer / "sysop/scripts/backfill_completed_dates.py", "--dry-run",
                 "--index", str(consumer / "tasks" / "index.yml"),
                 cwd=foreign, py=yamlless_python)
        _assert_resolved("backfill_completed_dates.py", r)

    @pytest.mark.parametrize("name", [*FATAL, SOFT])
    def test_a_host_that_already_has_yaml_gets_no_syspath_reordering(
            self, consumer, name):
        """Guard-the-guard: the resolution must be a no-op where it is not needed.

        Parametrized over all five by the round — it previously covered
        `scope_overlap.py` alone, and a mutation turning the `try` into an
        unconditional `raise ImportError` therefore injected a venv's
        site-packages at `sys.path[0]` in the other four with the suite green.
        That is the mirror-image hazard this phase's own design notes name.
        """
        _fake_venv(consumer)
        probe = consumer / f"probe_{name[:-3]}.py"
        probe.write_text(
            "import sys, json\n"
            f"sys.argv = ['{name}', '--help']\n"
            "sys.path.insert(0, r'%s')\n"
            "try:\n"
            f"    import {name[:-3]}\n"
            "except SystemExit:\n"
            "    pass\n"
            "leaked = [p for p in sys.path if 'site-packages' in p and 'proj' in p]\n"
            "print(json.dumps(leaked))\n" % (consumer / "sysop" / "scripts")
        )
        r = subprocess.run([sys.executable, str(probe)], cwd=str(consumer),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        leaked = json.loads(r.stdout.strip().splitlines()[-1])
        assert leaked == [], (
            f"{name} prepended a fixture venv to sys.path on an interpreter that "
            f"already had PyYAML: {leaked}"
        )


def test_sysconfig_is_not_needed_but_the_layout_assumption_is_real():
    """The glob assumes a POSIX `lib/python*/site-packages` venv layout. On
    Windows it is `Lib/site-packages` — recorded here rather than fixed, since
    Sysop documents WSL as the Windows path (README § Prerequisites)."""
    assert "lib" in sysconfig.get_paths()["purelib"].lower()
