"""`Q-278` (Phase 370): a timed-out git is not a missing git.

`run_checks/cli.py` resolved the repo root with `git rev-parse --show-toplevel`
and caught `(FileNotFoundError, subprocess.TimeoutExpired)` together, falling
back to `os.getcwd()` for both — no record, no `failed`, while
`run_checks/accounting.py` states that a timeout is `failed` (work was lost,
not declined). Reproduced at `12e8285`: with the probe timing out and the cwd a
*different* configured root, the run printed that root's findings and
`0 failed`, exit 0.

The fix splits the arm: a timeout refuses (exit 1, naming `--repo-root`), while
"not a git repo" (non-zero exit) and "no git binary" (`FileNotFoundError`) keep
the cwd fallback. The two controls are what stop the refusal being widened onto
the cases that are genuinely absence, not failure.

The same swallow sat in `_pending_rounds_note`, where `TimeoutExpired` (a
`SubprocessError`) returned the `None` that means "looked, found nothing". It
now returns a note that the probe did not run.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from run_checks import cli

_YML = """\
checks:
  - id: todo-x
    severity: low
    paths: ["."]
    include: ["*.txt"]
    pattern: 'TODO'
    description: "todo marker"
    used_by: [codebase-review]
"""

_REAL_RUN = subprocess.run


@pytest.fixture()
def other_root(tmp_path):
    """A configured root that is NOT the repo being asked about — the cwd."""
    root = tmp_path / "other"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "checks.yml").write_text(_YML)
    (root / "a.txt").write_text("TODO from the other project\n")
    return root


def _fake_toplevel(monkeypatch, behaviour):
    """Replace only the `--show-toplevel` call; every other subprocess is real,
    so the grep stage still runs exactly as it would."""
    def fake(cmd, *args, **kwargs):
        if list(cmd[:3]) == ["git", "rev-parse", "--show-toplevel"]:
            return behaviour(cmd)
        return _REAL_RUN(cmd, *args, **kwargs)
    monkeypatch.setattr(cli.subprocess, "run", fake)


def _main(monkeypatch, cwd, *extra):
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["run_checks", "--mode", "both", *extra])
    try:
        cli.main()
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


def _timeout(cmd):
    raise subprocess.TimeoutExpired(cmd, 10)


def test_a_timed_out_toplevel_refuses_instead_of_scanning_the_cwd(
    other_root, monkeypatch, capsys
):
    _fake_toplevel(monkeypatch, _timeout)
    code = _main(monkeypatch, other_root)
    out = capsys.readouterr()
    assert code == 1, out
    assert "timed out" in out.err and "--repo-root" in out.err, out.err
    # The defect's signature: the cwd project's finding and a clean summary.
    assert "todo-x" not in out.out, out.out
    assert "0 failed" not in out.err, out.err


def test_a_non_git_cwd_still_falls_back_to_the_cwd(other_root, monkeypatch, capsys):
    """Control: `rev-parse` exiting non-zero is absence, and keeps the fallback."""
    _fake_toplevel(monkeypatch, lambda cmd: subprocess.CompletedProcess(
        cmd, 128, stdout="", stderr="fatal: not a git repository"))
    code = _main(monkeypatch, other_root)
    out = capsys.readouterr()
    assert code == 0, out
    assert "[todo-x]" in out.out, out.out


def test_a_missing_git_binary_still_falls_back_to_the_cwd(
    other_root, monkeypatch, capsys
):
    """Control: no git at all is absence too — not the timeout's refusal."""
    def missing(cmd):
        raise FileNotFoundError(2, "No such file or directory", "git")
    _fake_toplevel(monkeypatch, missing)
    code = _main(monkeypatch, other_root)
    out = capsys.readouterr()
    assert code == 0, out
    assert "[todo-x]" in out.out, out.out
    assert "timed out" not in out.err, out.err


def test_an_explicit_repo_root_never_probes_git(other_root, monkeypatch, capsys):
    """The remedy the refusal names must actually bypass the probe."""
    _fake_toplevel(monkeypatch, _timeout)
    code = _main(monkeypatch, other_root.parent, "--repo-root", str(other_root))
    out = capsys.readouterr()
    assert code == 0, out
    assert "[todo-x]" in out.out, out.out


# ── the pending-rounds probe ────────────────────────────────────────────────


def _fake_common_dir(monkeypatch, exc):
    def fake(cmd, *args, **kwargs):
        if list(cmd[:3]) == ["git", "rev-parse", "--git-common-dir"]:
            raise exc
        return _REAL_RUN(cmd, *args, **kwargs)
    monkeypatch.setattr(cli.subprocess, "run", fake)


def test_a_timed_out_pending_rounds_probe_says_it_did_not_run(tmp_path, monkeypatch):
    _fake_common_dir(monkeypatch, subprocess.TimeoutExpired(["git"], 10))
    note = cli._pending_rounds_note(str(tmp_path))
    assert note is not None, "a timeout read as 'no stale rounds'"
    assert "did not run" in note and "timed out" in note, note
    # The /review-close Exit-0 arm reads this block for its own marker; the
    # note must stay a `⚠` line that is not a blocking-check marker.
    assert "⚠" in note and "BLOCKING CHECK" not in note, note


def test_a_missing_git_still_gives_the_pending_rounds_probe_no_note(
    tmp_path, monkeypatch
):
    """Control: the timeout arm must not swallow the other OSErrors' `None`."""
    _fake_common_dir(monkeypatch, FileNotFoundError(2, "No such file", "git"))
    assert cli._pending_rounds_note(str(tmp_path)) is None


def test_the_timeout_note_reaches_the_prescan_summary(other_root, monkeypatch, capsys):
    """End to end: the note is appended to the summary a consumer reads."""
    _fake_common_dir(monkeypatch, subprocess.TimeoutExpired(["git"], 10))
    code = _main(monkeypatch, other_root, "--repo-root", str(other_root))
    out = capsys.readouterr()
    assert code == 0, out
    assert "review-round probe did not run" in out.err, out.err
