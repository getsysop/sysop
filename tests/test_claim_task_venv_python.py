"""`claim_task.sh` must find a PyYAML-capable interpreter before it fails (Phase 182).

Four sites in `claim_task.sh` reach PyYAML through a bare `python3`: the
`--entry-state` gate and the heredoc it guards, and the `--release` preflight
and its flip heredoc. On a PEP-668 host — every modern distro, and Homebrew
macOS — `pip install` into the system interpreter is an *error*, so PyYAML
lives only in the project venv. Both paths therefore died on hosts that are
perfectly well provisioned:

  * `--entry-state` exits 3 (`/claim-task` Step 2's *first* command), and the
    skill's contract for a non-zero exit is "the question could not be answered
    at all — surface stderr verbatim and **stop**", so the claim never starts;
  * `--release` exits 1 having mutated nothing, printing a manual recipe.

The fail-closed contract is still right when **no** interpreter has PyYAML —
what changes is that a venv-only host is no longer that case. So this module
pins both halves: the degradation when nothing can be resolved, and the
resolution when something can.

Scope note, so the fixture is not over-read. `_yamlless_py3` is a real
interpreter with `yaml` shadowed by a raising stub, not a shim that `exit 1`s
for every invocation. That distinction is load-bearing: against an `exit 1`
shim a fix that *deleted* the probe and let the heredoc crash would still look
green, because both the probe and the run fail. Against this one only a fix
that actually resolves an interpreter passes.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/claim_task.sh"

# Same isolation as tests/test_claim_task_sh.py — a contributor's global
# core.hooksPath or commit signing must not reach these repos.
_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

_INDEX = "schema_version: 1\ntasks:\n  - id: FEAT-0001\n    status: open\n"


# ── fixture plumbing ────────────────────────────────────────────────────────

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _repo(root, index=_INDEX, status=None):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# seed\n")
    (root / "tasks").mkdir(exist_ok=True)
    body = index if status is None else index.replace("status: open", f"status: {status}")
    (root / "tasks" / "index.yml").write_text(body, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args, path=None, extra_env=None):
    e = dict(os.environ)
    e.update(_GIT_ISOLATION)
    if path is not None:
        e["PATH"] = str(path)
    if extra_env:
        e.update(extra_env)
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=e)


def _write_shim(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def _capable_py3(bin_dir: Path) -> Path:
    """A `python3` that is this test's interpreter, so PyYAML is guaranteed."""
    return _write_shim(bin_dir / "python3",
                       f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')


def _tagged_py3(bin_dir: Path, tag_file: Path) -> Path:
    """A capable `python3` that records the fact it was probed.

    Order is invisible when only one candidate can import yaml — the probe just
    falls through to the one that works, so reversing the candidate list stays
    green. The round walked two such reorderings through every earlier
    assertion for exactly that reason. Recording each probe makes the order a
    property you can assert instead of a comment you have to trust.
    """
    return _write_shim(bin_dir / "python3",
                       f'#!/bin/sh\necho "{bin_dir}" >> "{tag_file}"\n'
                       f'exec "{sys.executable}" "$@"\n')


def _yamlless_py3(bin_dir: Path, blocker: Path) -> Path:
    """A fully-working `python3` that cannot `import yaml`.

    Shadows `yaml` with a module that raises on import, via PYTHONPATH — which
    is searched before site-packages. Everything else about the interpreter
    still works, which is what makes this fixture hostile: a fix that removed
    the probe instead of resolving an interpreter fails here and passes against
    a shim that simply `exit 1`s.
    """
    blocker.mkdir(parents=True, exist_ok=True)
    (blocker / "yaml.py").write_text("raise ImportError(\"No module named 'yaml'\")\n")
    return _write_shim(bin_dir / "python3",
                       f'#!/bin/sh\nPYTHONPATH="{blocker}" exec "{sys.executable}" "$@"\n')


@pytest.fixture(scope="session")
def toolbox(tmp_path_factory):
    """A PATH dir carrying every real tool EXCEPT any python.

    Built by mirroring the ambient PATH rather than by naming the tools the
    script happens to use today — naming them would make this fixture rot the
    moment `claim_task.sh` calls something new, and rot in the direction of a
    false green (a missing tool would read as the failure under test).
    """
    box = tmp_path_factory.mktemp("toolbox")
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith("python") or name.startswith("pypy"):
                continue
            dst = box / name
            if dst.exists() or dst.is_symlink():
                continue
            try:
                dst.symlink_to(Path(d) / name)
            except OSError:
                pass
    assert (box / "git").exists(), "toolbox must carry git"
    assert not (box / "python3").exists(), "toolbox must NOT carry python3"
    return box


def _path_with(toolbox, *bins) -> str:
    return os.pathsep.join([*(str(b) for b in bins), str(toolbox)])


def _claim(repo, task_id="FEAT-0001", prefix="wt"):
    """Claim with a lock + worktree. Pure bash — needs no interpreter."""
    r = _run(repo, "--lock", task_id, "feat/x", extra_env={"WORKTREE_PREFIX": prefix})
    assert r.returncode == 0, r.stderr
    return r


# ── the degradation half: nothing can be resolved, so fail closed ───────────

class TestNoInterpreterAnywhere:
    """The Phase-165 contract, kept: when NOTHING has PyYAML, refuse and mutate
    nothing. Both revised deliberate tests live here in their honest form."""

    def test_entry_state_exits_3_when_no_python3_exists_at_all(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox))
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        assert "PyYAML" in r.stderr

    def test_entry_state_exits_3_when_python3_lacks_yaml_and_no_venv(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r")
        bins = tmp_path / "sysbin"
        _yamlless_py3(bins, tmp_path / "blocker")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, bins))
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        assert "PyYAML" in r.stderr

    def test_entry_state_error_names_the_venv_remedy(self, tmp_path, toolbox):
        """The shipped text named no remedy at all, which is why the reporter's
        workaround was undiscoverable from it."""
        repo = _repo(tmp_path / "r")
        bins = tmp_path / "sysbin"
        _yamlless_py3(bins, tmp_path / "blocker")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, bins))
        # Both lines, separately. The round showed a lone `".venv" in stderr`
        # was satisfied by either one, so the remedy line — the whole point of
        # the phase, since exit 3 previously "named no remedy" — was deletable
        # with the suite green.
        assert "Tried .venv/bin/python3" in r.stderr, r.stderr
        assert ".venv/bin/pip install pyyaml" in r.stderr, r.stderr

    def test_release_degrades_without_mutating_when_nothing_has_yaml(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r", status="in_progress")
        _claim(repo)
        bins = tmp_path / "sysbin"
        _yamlless_py3(bins, tmp_path / "blocker")
        r = _run(repo, "--release", "FEAT-0001", path=_path_with(toolbox, bins))
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert "PyYAML" in r.stderr
        assert "Tried .venv/bin/python3" in r.stderr, r.stderr
        assert ".venv/bin/pip install pyyaml" in r.stderr, r.stderr
        assert (tmp_path / "wt-feat-0001").is_dir(), "worktree removed on a refusal"
        assert (repo / "sysop/runtime/locks/FEAT-0001.lock").is_file()
        assert "status: in_progress" in (repo / "tasks/index.yml").read_text()

    def test_release_degrades_without_mutating_when_no_python3_at_all(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r", status="in_progress")
        _claim(repo)
        r = _run(repo, "--release", "FEAT-0001", path=_path_with(toolbox))
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert (tmp_path / "wt-feat-0001").is_dir()
        assert (repo / "sysop/runtime/locks/FEAT-0001.lock").is_file()
        assert "status: in_progress" in (repo / "tasks/index.yml").read_text()


# ── the resolution half: a venv-only host is no longer that case ────────────

class TestVenvOnlyHost:
    """PATH `python3` cannot import yaml; the project venv can. Every one of the
    four sites must reach the venv interpreter."""

    @pytest.mark.parametrize("venv_dir", [".venv", "venv"])
    def test_entry_state_resolves_the_project_venv(self, tmp_path, toolbox, venv_dir):
        repo = _repo(tmp_path / "r")
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / venv_dir / "bin")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "claimable", (r.stdout, r.stderr)

    def test_entry_state_resolves_the_venv_with_no_python3_on_path_at_all(
            self, tmp_path, toolbox):
        """A venv is a complete answer — the gate must not additionally require
        a system `python3` it never uses."""
        repo = _repo(tmp_path / "r")
        _capable_py3(repo / ".venv/bin")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "claimable"

    def test_entry_state_emits_exactly_one_token_on_stdout(self, tmp_path, toolbox):
        """The one-token stdout contract (the reason stderr gets its own file)
        must survive the venv path — a venv's sitecustomize or a .pth that
        prints would otherwise be prepended to the token."""
        repo = _repo(tmp_path / "r")
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / ".venv/bin")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.stdout.split() == ["claimable"], r.stdout

    def test_release_flips_the_index_via_the_venv(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r", status="in_progress")
        _claim(repo)
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / ".venv/bin")
        r = _run(repo, "--release", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert not (tmp_path / "wt-feat-0001").exists(), "worktree not removed"
        assert not (repo / "sysop/runtime/locks/FEAT-0001.lock").exists(), "lock not removed"
        idx = (repo / "tasks/index.yml").read_text()
        assert "status: open" in idx and "in_progress" not in idx


class TestAnchoredOnTheMainCheckoutNotTheCwd:
    """`--release` may be run from anywhere and `--entry-state` is routinely run
    from a worktree, so a CWD-relative venv probe answers the wrong question."""

    def test_entry_state_from_a_linked_worktree_finds_mains_venv(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r")
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / ".venv/bin")
        _claim(repo)  # creates ../wt-feat-0001 on feat/x
        wt = tmp_path / "wt-feat-0001"
        assert not (wt / ".venv").exists(), "fixture invalid: worktree has its own venv"
        r = _run(wt, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        # A live status plus the lock this claim wrote.
        assert r.stdout.strip() == "held", (r.stdout, r.stderr)

    def test_entry_state_from_a_subdirectory_finds_the_repo_venv(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r")
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / ".venv/bin")
        sub = repo / "src" / "deep"
        sub.mkdir(parents=True)
        r = _run(sub, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "claimable"

    def test_release_from_a_subdirectory_finds_the_repo_venv(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r", status="in_progress")
        _claim(repo)
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / ".venv/bin")
        sub = repo / "src" / "deep"
        sub.mkdir(parents=True)
        r = _run(sub, "--release", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert "status: open" in (repo / "tasks/index.yml").read_text()


class TestVenvIsPreferredButNotBlindly:
    """A blind `PATH=.venv/bin:$PATH` prepend would *shadow* a capable system
    interpreter with an incapable venv one — trading the reported failure for
    its mirror image. `self_check.sh` documents this hazard in the opposite
    direction; the resolution must probe, not assume."""

    def test_a_yamlless_venv_does_not_shadow_a_capable_system_python3(
            self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r")
        sysbin = tmp_path / "sysbin"
        _capable_py3(sysbin)
        _yamlless_py3(repo / ".venv/bin", tmp_path / "blocker")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "claimable"

    def test_release_is_not_shadowed_by_a_yamlless_venv_either(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r", status="in_progress")
        _claim(repo)
        sysbin = tmp_path / "sysbin"
        _capable_py3(sysbin)
        _yamlless_py3(repo / ".venv/bin", tmp_path / "blocker")
        r = _run(repo, "--release", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert "status: open" in (repo / "tasks/index.yml").read_text()

    def test_a_non_executable_venv_python3_is_skipped(self, tmp_path, toolbox):
        """A `.venv/bin/python3` left non-executable (a botched copy, a
        restored-from-archive tree) must not swallow the resolution."""
        repo = _repo(tmp_path / "r")
        sysbin = tmp_path / "sysbin"
        _capable_py3(sysbin)
        broken = repo / ".venv/bin/python3"
        broken.parent.mkdir(parents=True)
        broken.write_text("#!/bin/sh\nexit 0\n")
        broken.chmod(0o644)
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "claimable"


class TestTheCandidateOrderIsPinned:
    """The shell half of the resolution had its *order* unguarded — the round
    walked three reorderings straight through. The Python half pins its order
    inside the drift regex; nothing did the same here, so the two could silently
    disagree about which venv wins."""

    def _two_venvs(self, tmp_path, repo, main_ok: bool):
        """A main checkout and a worktree, each with a venv; only one has yaml."""
        good, bad = (repo, None), (None, repo)
        return good if main_ok else bad

    def test_main_is_probed_before_the_current_checkout(self, tmp_path, toolbox):
        """Both capable, so only the probe ORDER distinguishes them."""
        repo = _repo(tmp_path / "r")
        tags = tmp_path / "probed.txt"
        _tagged_py3(repo / ".venv/bin", tags)
        _claim(repo)
        wt = tmp_path / "wt-feat-0001"
        _tagged_py3(wt / ".venv/bin", tags)
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        r = _run(wt, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        probed = tags.read_text().split()
        assert probed[0] == str(repo / ".venv/bin"), (
            "the current checkout was probed before the main one — claims are "
            f"committed on main, so main's interpreter is the right answer: {probed}")

    def test_dot_venv_is_probed_before_plain_venv(self, tmp_path, toolbox):
        """Both capable, so only the probe ORDER distinguishes them. `.venv` is
        what every other resolver in the tree tries first."""
        repo = _repo(tmp_path / "r")
        tags = tmp_path / "probed.txt"
        _tagged_py3(repo / ".venv/bin", tags)
        _tagged_py3(repo / "venv/bin", tags)
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        probed = tags.read_text().split()
        assert probed[0] == str(repo / ".venv/bin"), probed

    def test_the_main_checkout_beats_the_current_one(self, tmp_path, toolbox):
        """`--entry-state` runs from a worktree routinely, and claims are
        committed on main, so main's interpreter is the right answer. Reversing
        the two roots survived every prior assertion."""
        repo = _repo(tmp_path / "r")
        _capable_py3(repo / ".venv/bin")
        _claim(repo)
        wt = tmp_path / "wt-feat-0001"
        # The worktree gets a venv that CANNOT import yaml. If the resolution
        # preferred the current checkout, it would pick this one and fail.
        _yamlless_py3(wt / ".venv/bin", tmp_path / "wtblock")
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        r = _run(wt, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "held", (r.stdout, r.stderr)

    def test_dot_venv_beats_plain_venv(self, tmp_path, toolbox):
        """A stale `venv/` beside a live `.venv/` must not win. `.venv` is the
        layout every other resolver in the tree probes first."""
        repo = _repo(tmp_path / "r")
        _capable_py3(repo / ".venv/bin")
        _yamlless_py3(repo / "venv/bin", tmp_path / "staleblock")
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        r = _run(repo, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "claimable", (r.stdout, r.stderr)

    def test_the_current_checkout_is_still_a_candidate(self, tmp_path, toolbox):
        """Main-first must not mean main-only: a consumer whose venv lives in the
        worktree and not the main checkout still gets an answer. Dropping this
        arm survived every prior assertion."""
        repo = _repo(tmp_path / "r")
        _claim(repo)
        wt = tmp_path / "wt-feat-0001"
        _capable_py3(wt / ".venv/bin")
        assert not (repo / ".venv").exists(), "fixture invalid: main has a venv"
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        r = _run(wt, "--entry-state", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert r.stdout.strip() == "held", (r.stdout, r.stderr)


class TestTheValidatorCallRidesAlong:
    """`:409` runs `validate_tasks.py` under a bare `python3` after a `cd` to
    the main checkout, and is a NON-instance because `:291`'s guard has already
    hard-exited on the broken path, so `:409` is unreachable in that state
    regardless. (The docstring used to credit the script's own `sys.path`
    bootstrap and call it *CWD-relative* — that was the pre-Phase-182 shape,
    written into this file by Phase 182 itself; the bootstrap is
    script-anchored first and only then CWD.) It must keep working when the
    only capable interpreter is the venv, and it must not become the thing that
    fails a release the flip already completed."""

    def test_release_completes_and_validates_on_a_venv_only_host(self, tmp_path, toolbox):
        repo = _repo(tmp_path / "r", status="in_progress")
        (repo / "sysop" / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "sysop/scripts/validate_tasks.py").write_text(
            "import yaml, sys\nprint('validator ran')\nsys.exit(0)\n")
        _claim(repo)
        sysbin = tmp_path / "sysbin"
        _yamlless_py3(sysbin, tmp_path / "blocker")
        _capable_py3(repo / ".venv/bin")
        r = _run(repo, "--release", "FEAT-0001", path=_path_with(toolbox, sysbin))
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert "validator ran" in r.stdout, r.stdout
