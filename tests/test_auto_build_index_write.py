"""`/auto-build` Step 5.1 and 5.4 — asserted by RUNNING them, not by reading them.

Phase 263, `Q-404`. Step 5.1 was the last writer of `tasks/index.yml` that
truncated in place, which made it a torn-read source for every concurrent
reader; Step 5.4 hand-rolled the commit that `/claim-task` Step 4d had already
moved inside `claim_task.sh --commit-claim` (Phase 261, `Q-397`).

The execution tests here exist because the OBVIOUS pin cannot see the defect this
conversion was one line away from shipping. Step 5.1's PyYAML bootstrap does
`import glob, os, subprocess` INSIDE its `except ImportError:` arm, so on the
happy path — PyYAML present, which is every working consumer — `os` is unbound.
Copying Step 4a's atomic block without hoisting the import raises `NameError` on
exactly the configuration that works, while every grep for `os.replace(` stays
green. A string pin CAN be written for it once you know it exists — this module
ships one, `test_step51_imports_os_outside_the_bootstrap_arm` — but you have to
have run the block to know to write it. An earlier draft of this paragraph said
"no string-shaped guard could have seen it", which its own neighbour refutes.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core/skills/auto-build/SKILL.md"

HEREDOC_OPEN = "python3 - <<'PY' \"<TASK_ID>\""


def _step5_fence() -> str:
    """The whole Step 5 bash fence — 5.1 through 5.4 live in one block."""
    text = SKILL.read_text(encoding="utf-8")
    start = text.index("## Step 5: Sequential Pre-Claim on Main")
    fence = text.index("```bash", start)
    end = text.index("\n```", fence)
    return text[fence:end]


def _step51_body() -> str:
    """Step 5.1's heredoc'd Python, verbatim and runnable."""
    text = SKILL.read_text(encoding="utf-8")
    found = text.count(HEREDOC_OPEN)
    assert found == 1, (
        f"Step 5.1's heredoc opener matched {found} times, not once. This extractor "
        f"keys on the exact form {HEREDOC_OPEN!r}; the equally legal "
        "`python3 - \"<TASK_ID>\" <<'PY'` (args before the redirect — the form Step 1 "
        "of this same file ships) matches ZERO times, and the old message said "
        "'no longer unique', which points at the wrong problem"
    )
    start = text.index("\n", text.index(HEREDOC_OPEN)) + 1
    return text[start:text.index("\nPY\n", start)]


def _code_only(body: str) -> str:
    """Comments stripped, so a claim written in a comment cannot satisfy a pin."""
    out = []
    for line in body.splitlines():
        out.append("" if line.lstrip().startswith("#") else line.split("#", 1)[0])
    return "\n".join(out)


def _index(status: str = "open", task_id: str = "TECH-0001") -> str:
    return (
        "schema_version: 1\n"
        "tasks:\n"
        f"- id: {task_id}\n"
        "  title: a task\n"
        f"  status: {status}\n"
        "  type: tech\n"
        "  effort: 1\n"
        "  priority: medium\n"
    )


def _run(tmp_path: Path, task_id: str = "TECH-0001"):
    """Run the shipped block the way the fence runs it: stdin script, argv[1] id."""
    return subprocess.run(
        [sys.executable, "-", task_id],
        input=_step51_body(),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_text(_index(), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- non-vacuity


def test_the_extractor_returns_the_real_block():
    body = _step51_body()
    assert "yaml.safe_dump(" in body, "extractor missed Step 5.1's write"
    assert "index_path" in body and "in_progress" in body
    assert len(body.splitlines()) > 20, "extracted block is implausibly short"


# ------------------------------------------------------------------ execution


def test_step51_flips_open_to_in_progress(repo: Path):
    r = _run(repo)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "status: in_progress" in (repo / "tasks" / "index.yml").read_text(encoding="utf-8")


def test_step51_runs_with_pyyaml_present(repo: Path):
    """The NameError catcher.

    `os` is imported inside the bootstrap's `except ImportError:` arm. With
    PyYAML importable that arm never runs, so an atomic write that reaches for
    `os.path.realpath` without a hoisted import dies here and nowhere else.
    """
    r = _run(repo)
    assert "NameError" not in r.stderr, r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0


def test_step51_refuses_a_torn_read_in_words(repo: Path):
    """A concurrent in-place writer leaves this file zero-length for a moment."""
    (repo / "tasks" / "index.yml").write_text("", encoding="utf-8")
    r = _run(repo)
    assert r.returncode == 1
    assert "read as empty" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr, "the empty read must refuse, not raise"


def test_step51_writes_through_a_symlinked_index(repo: Path):
    """`os.replace` onto the link would replace the link; `realpath` writes through."""
    real = repo / "real-index.yml"
    real.write_text(_index(), encoding="utf-8")
    link = repo / "tasks" / "index.yml"
    link.unlink()
    link.symlink_to(real)

    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert link.is_symlink(), "Step 5.1 replaced the symlink instead of writing through it"
    assert "status: in_progress" in real.read_text(encoding="utf-8")


def test_step51_preserves_the_index_mode(repo: Path):
    index = repo / "tasks" / "index.yml"
    index.chmod(0o640)
    before = stat.S_IMODE(index.stat().st_mode)

    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE(index.stat().st_mode) == before, "the index's mode was not carried across"


def test_step51_leaves_no_tempfile_residue(repo: Path):
    _run(repo)
    residue = [p.name for p in (repo / "tasks").iterdir() if p.name != "index.yml"]
    assert residue == [], f"Step 5.1 left {residue} beside the index"


def test_step51_refuses_a_status_that_is_not_open(repo: Path):
    (repo / "tasks" / "index.yml").write_text(_index(status="done"), encoding="utf-8")
    r = _run(repo)
    assert r.returncode == 1
    assert "refusing to flip status" in r.stderr
    assert "status: done" in (repo / "tasks" / "index.yml").read_text(encoding="utf-8")


def test_step51_refuses_a_task_it_cannot_find(repo: Path):
    r = _run(repo, task_id="TECH-9999")
    assert r.returncode == 1
    assert "not in index" in r.stderr
    assert "status: open" in (repo / "tasks" / "index.yml").read_text(encoding="utf-8")


# ------------------------------------------------------------------- the code


def test_step51_writes_atomically_not_in_place():
    code = _code_only(_step51_body())
    assert "os.replace(" in code, "Step 5.1 no longer replaces atomically"
    assert "dir=os.path.dirname(" in code, (
        "Step 5.1's tempfile is no longer created beside the index. mkstemp without "
        "`dir=` lands in $TMPDIR, and on any consumer whose temp dir is a different "
        "filesystem — Linux /tmp on tmpfs, Docker, a mounted volume — os.replace "
        "raises EXDEV and the claim flip is lost with a raw traceback"
    )
    assert "tempfile.mkstemp(" in code, (
        "Step 5.1 must use mkstemp, not a derived `<path>.tmp` — two writers "
        "would collide on a fixed temp name (`Q-382`'s class)"
    )
    assert 'index_path.open("w"' not in code, "Step 5.1 truncates the index in place again"
    assert 'open(real, "w"' not in code
    assert "os.path.realpath(" in code, "Step 5.1 stopped writing through a symlinked index"
    assert "os.chmod(" in code, "Step 5.1 stopped preserving the index's mode"
    # Keyed to the CALL, not to the local's name. The first version asserted the
    # literal `os.unlink(tmp)`, and the battery's N03 control — renaming `tmp` to
    # `tmpf`, a legal refactor — reddened it. A guard keyed to a variable name
    # fails on correct code, which is the over-strictness direction that reads as
    # a green test right up until someone renames something.
    assert re.search(r"os\.unlink\(\w+\)", code), (
        "Step 5.1 stopped cleaning up its tempfile on failure"
    )
    # BaseException, not Exception. Round lens 1 narrowed it and the guards stayed
    # green: KeyboardInterrupt and SystemExit derive from BaseException, so a Ctrl-C
    # mid-write left an untracked `.tmp` beside a tracked path — the residue hazard
    # the cleanup arm exists for, reachable by the most ordinary interruption there is.
    assert "except BaseException:" in code, (
        "Step 5.1's cleanup no longer catches BaseException, so an interrupted write "
        "leaves its tempfile behind"
    )


def test_step51_imports_os_outside_the_bootstrap_arm():
    """The import must be reachable when PyYAML imports cleanly."""
    top_level = [
        line for line in _code_only(_step51_body()).splitlines()
        if line and not line[0].isspace()
    ]
    assert any(
        line.startswith("import ") and re.search(r"\bos\b", line) for line in top_level
    ), (
        "Step 5.1 binds `os` only inside the PyYAML bootstrap's `except ImportError:` "
        "arm, so the happy path raises NameError. Hoist `import os, tempfile`."
    )


def test_step51_refuses_an_empty_parse():
    code = _code_only(_step51_body())
    # Either spelling. Round lens 3's negative control replaced the check with
    # `if not isinstance(data, dict):` — strictly stronger, verified equivalent on
    # every path this block takes — and the pin reddened. A guard that rejects a
    # better fix is over-strictness wearing a green test's clothes.
    assert "if data is None:" in code or "isinstance(data, dict)" in code, (
        "Step 5.1 lost the guard that turns a mid-write read into words "
        "instead of a raw AttributeError"
    )


def test_step54_commits_through_the_owner():
    # Read against the CODE. Step 5.4's own comment explains the conversion, so a
    # raw-fence assertion is satisfied by the explanation while the code below it
    # hand-rolls the commit again — the "satisfied by an incidental substring"
    # class, and this guard shipped with it until the author-side pass ran.
    fence = _code_only(_step5_fence())
    # The whole INVOCATION, not the flag. Round lens 1 dropped the `"<TASK_ID>"`
    # operand and this guard stayed green over a step that exits 1 with a usage
    # error on every task — a substring pin proving the flag is mentioned, not
    # that the command can run.
    assert 'claim_task.sh --commit-claim "<TASK_ID>"' in fence, (
        "Step 5.4 no longer commits through claim_task.sh — the mutex, the "
        "in-critical-section HEAD check and the re-flip repair all go with it"
    )
    assert 'git commit -m "claim: mark' not in fence, (
        "Step 5.4 hand-rolls the claim commit again, outside the tracker mutex"
    )
    assert "git add tasks/index.yml" not in fence, (
        "Step 5 stages the index itself again. The pin used to be keyed to the "
        "`&&` compound, so re-adding the same command on its own line walked it"
    )
    commit_line = [ln for ln in fence.splitlines() if "--commit-claim" in ln]
    assert len(commit_line) == 1, f"expected one --commit-claim line, got {commit_line}"
    assert not re.search(r"(\|\||;)\s*(true|:)\s*$", commit_line[0]), (
        f"Step 5.4's exit status is swallowed by {commit_line[0].strip()!r}. Its own "
        "comment says to STOP on a non-zero exit, and nothing enforced that"
    )
    for literal in ("= \"main\"", "= \"master\"", "= \"trunk\"", "= \"develop\""):
        assert literal not in fence, (
            f"Step 5 compares HEAD against the literal {literal} again — the shape "
            "that halted this loop on a master-default consumer (`Q-377`). The "
            "placeholder pin below cannot see a literal, only a placeholder"
        )


def test_step5_refuses_to_run_outside_the_primary_checkout():
    """The guard that deleting the inline HEAD test removed.

    5.1 writes cwd-relative and 5.4 commits primary-relative, so from a linked
    worktree the claim lands in a tree the operator is not standing in and the
    worktree is left dirty. The old inline HEAD test caught this by accident;
    this asserts the explicit replacement is present and keyed to the property
    that actually distinguishes a worktree, not to a branch name.
    """
    fence = _code_only(_step5_fence())
    assert "--git-common-dir" in fence and "--git-dir" in fence, (
        "Step 5 lost its primary-checkout preflight; a run from a linked worktree "
        "commits the claim into the primary tree and leaves this one dirty"
    )
    guard = [ln for ln in fence.splitlines() if "--git-common-dir" in ln]
    assert guard and guard[0].lstrip().startswith("test "), (
        "the preflight is no longer an executable test, only prose"
    )


def test_step5_no_longer_substitutes_a_default_branch():
    """`--commit-claim` resolves it, so the operator no longer can get it wrong.

    Read against the CODE. Step 5.4's comment explains that the substitution is
    gone, and a fence-wide grep is satisfied — in the wrong direction — by that
    sentence alone.
    """
    assert "<default branch>" not in _code_only(_step5_fence()), (
        "Step 5 asks for a <default branch> substitution again; the literal `main` "
        "halted this loop on a master-default repo (`Q-377`)"
    )


# ------------------------------------------------------------ collection guard


def _function_source(name: str) -> str:
    """One function's source, COMMENTS STRIPPED, so a pin cannot satisfy itself.

    Scoping to the function was not enough: `_function_source` returned raw
    source, so the historic form of a pinned comparison could be parked in a
    comment inside the very function being searched and the pin passed with the
    live assertion weakened. Round lens 3 demonstrated it, then starved the
    control, and the whole module went green over a measurement that certified
    nothing. Comments are the haystack's own hiding place; drop them.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    start = src.index(f"def {name}(")
    end = src.find("\ndef ", start + 1)
    body = src[start:] if end == -1 else src[start:end]
    return "\n".join(
        "" if ln.lstrip().startswith("#") else ln.split("  #", 1)[0]
        for ln in body.splitlines()
    )


def test_the_property_tests_preconditions_are_not_weakened():
    """A11/A12 from this phase's battery: both survived, and this is the close.

    `test_the_atomic_write_closes_the_torn_read_window` rests on two preconditions
    — that the control actually reproduced (`> 0`, not `>= 0`) and that the two
    arms sampled comparably (a bounded ratio, not an unbounded one). Weakening
    either turns a VOID run into a certification, and nothing else in the suite
    can see that: the test still passes, so no assertion fires. Pinning the
    comparisons is the only close available in kind — the mutation edits a
    predicate that is itself the oracle, so no deeper oracle exists to catch it.
    """
    # Scoped to the property test's OWN body. The first version searched the whole
    # module for the literal it wanted — and that literal appears in this guard, as
    # the search string. So the pin matched itself and passed with the arm
    # weakened: the battery scored A11 and A12 as survivors twice, and the second
    # time it was this guard, not the absence of one. A needle that occurs inside
    # its own haystack is rule 1's "satisfied by an incidental use of that
    # substring", written by the person guarding against it.
    body = _function_source("test_the_atomic_write_closes_the_torn_read_window")
    assert 'control["torn"] ' + "> 0" in body, (
        "the control-must-reproduce arm was weakened; a control that reproduces "
        "nothing would then certify the fix"
    )
    assert "0.25 < ratio " + "< 4.0" in body, (
        "the sampler-bias bound was widened; comparing arms that sampled at "
        "wildly different rates is how this phase's first number came out 99.9%"
    )


def test_this_module_still_runs_its_execution_tests():
    """Phase 262's lesson: deleting a new module's tests reddened almost nothing."""
    src = Path(__file__).read_text(encoding="utf-8")
    required = (
        "test_step51_runs_with_pyyaml_present",
        "test_step51_refuses_a_torn_read_in_words",
        "test_step51_writes_through_a_symlinked_index",
        "test_step51_preserves_the_index_mode",
        "test_step54_commits_through_the_owner",
        "test_the_atomic_write_closes_the_torn_read_window",
        "test_the_property_tests_preconditions_are_not_weakened",
        "test_step5_refuses_to_run_outside_the_primary_checkout",
    )
    for name in required:
        assert src.count(f"def {name}(") == 1, f"{name} was removed from this module"
        # ...and that it still ASSERTS. Round lens 3 replaced a required test's body
        # with `pass`, kept the `def`, and this roster stayed green over a test that
        # checks nothing — a name is not a guard.
        body = _function_source(name)
        assert "assert " in body, (
            f"{name} still exists but no longer asserts anything"
        )


# ------------------------------------------------- the torn-read window itself
#
# The atomicity pins above assert the SHAPE of the write. This section asserts
# the PROPERTY the shape exists for: that a concurrent reader never observes a
# zero-length or half-written index. It is self-controlling — the control is the
# shipped block with its atomic tail reverted to the pre-263 two-liner, so it
# models what actually shipped rather than what the author imagines shipped. If
# the control reproduces nothing the test FAILS rather than passes: a fixture
# that cannot produce the defect cannot certify its absence.


# Keyed to the CALL, not to the local it binds. Round lens 3's negative control
# renamed `real` to `target` — a legal refactor it verified preserves behaviour —
# and this anchor missed, which took the property test down with it. A control
# that reddens a guard is the over-strictness direction, and it reads as green.
ATOMIC_TAIL_RE = re.compile(r"^\s*\w+ = os\.path\.realpath\(index_path\)", re.M)
REVERTED_TAIL = (
    'with index_path.open("w", encoding="utf-8") as f:\n'
    "    yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False, "
    "allow_unicode=True, width=120)\n"
)


def reverted_body() -> str:
    """The shipped block with its atomic tail swapped back to the pre-263 write."""
    body = _step51_body()
    m = ATOMIC_TAIL_RE.search(body)
    assert m, (
        "cannot build the control: the shipped block no longer has the atomic tail "
        "this reverts, so the control would model nothing"
    )
    head = body[:m.start()].splitlines()
    while head and head[-1].lstrip().startswith("#"):
        head.pop()
    control = "\n".join(head) + "\n" + REVERTED_TAIL
    assert "os.replace(" not in control, "the control still writes atomically"
    assert 'index_path.open("w"' in control, "the control does not truncate in place"
    return control


def _big_index(path: Path, n_tasks: int) -> list[str]:
    import yaml

    ids = [f"TECH-{i:04d}" for i in range(1, n_tasks + 1)]
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "tasks": [
                    {
                        "id": tid,
                        "title": f"a task with a title long enough to give the file size — {tid}",
                        "status": "open",
                        "type": "tech",
                        "effort": 1,
                        "priority": "medium",
                    }
                    for tid in ids
                ],
            },
            sort_keys=False, default_flow_style=False, allow_unicode=True, width=120,
        ),
        encoding="utf-8",
    )
    return ids


def torn_read_sample(body: str, root: Path, n_tasks: int, n_writes: int) -> dict:
    """Spin a same-cost sampler on the index while `body` runs `n_writes` times.

    EVERY SAMPLE MUST COST THE SAME. The first version of this loop parsed the
    YAML on a good read and `continue`d on an empty one, making an empty read
    ~1000x cheaper — so the sampler oversampled precisely the outcome it counted
    and reported 45,241 torn of 45,293. That number described the sampler. This
    one classifies on LENGTH only and sleeps identically either way, so the count
    is proportional to the time the file actually spends torn.
    """
    import threading
    import time

    (root / "tasks").mkdir(exist_ok=True)
    index = root / "tasks" / "index.yml"
    ids = _big_index(index, n_tasks)
    full_len = index.stat().st_size

    counts = {"samples": 0, "empty": 0, "short": 0, "writer_failures": 0, "first_error": ""}
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                raw = index.read_bytes()
            except FileNotFoundError:
                raw = b""
            counts["samples"] += 1
            if not raw:
                counts["empty"] += 1
            elif len(raw) < full_len:
                counts["short"] += 1
            time.sleep(0.0002)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for tid in ids[:n_writes]:
            r = subprocess.run(
                [sys.executable, "-", tid], input=body, cwd=str(root),
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                counts["writer_failures"] += 1
                counts["first_error"] = counts["first_error"] or r.stderr.strip()[:300]
    finally:
        stop.set()
        t.join(timeout=10)

    counts["torn"] = counts["empty"] + counts["short"]
    return counts


def test_the_atomic_write_closes_the_torn_read_window(tmp_path: Path):
    """The property, not the shape — and it fails VOID if the control is silent."""
    control_root = tmp_path / "control"
    control_root.mkdir()
    control = torn_read_sample(reverted_body(), control_root, n_tasks=60, n_writes=12)

    assert control["writer_failures"] == 0, (
        f"the control writer failed {control['writer_failures']}x — the run measures "
        f"a broken fixture, not the defect: {control['first_error']!r}"
    )
    assert control["torn"] > 0, (
        "VOID, not a pass: the reverted (in-place) writer produced no torn read, so "
        "this run cannot certify that the shipped one closes the window. Raise "
        "n_tasks — a larger index holds the window open longer."
    )

    shipped_root = tmp_path / "shipped"
    shipped_root.mkdir()
    shipped = torn_read_sample(_step51_body(), shipped_root, n_tasks=60, n_writes=12)

    assert shipped["writer_failures"] == 0, (
        f"the shipped block failed {shipped['writer_failures']}x: {shipped['first_error']!r}"
    )
    # Comparable sample counts are the evidence the sampler is unbiased; a large
    # asymmetry means one arm's reads were cheaper, which is how the first
    # version of this measurement produced a number about itself.
    ratio = shipped["samples"] / max(control["samples"], 1)
    assert 0.25 < ratio < 4.0, (
        f"sampler is biased between arms (shipped {shipped['samples']} vs control "
        f"{control['samples']} samples) — the comparison is not meaningful"
    )
    assert shipped["torn"] == 0, (
        f"the shipped Step 5.1 exposed {shipped['torn']} torn reads of "
        f"{shipped['samples']} samples — the write is not atomic"
    )
