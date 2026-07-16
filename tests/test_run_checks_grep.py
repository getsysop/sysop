"""Tests for ``run_check``'s grep-dispatch finding branches and the
symlink-escape realpath guard in ``core/companion/scripts/run_checks/grep.py``.

Prior coverage (``test_run_checks.py``) exercised only the ``position_check``
dispatch and the mocked ESLint / pip-audit stages. ``run_check``'s three
grep-driven finding branches — file-level ``invert_file_check``, per-line
``negative_pattern`` filter, and simple pattern match — plus the path-
containment guard that rejects a scanned symlink resolving outside the repo
were all unpinned. These drive the real ``grep`` binary against a ``tmp_path``
tree (``grep`` is a hard dependency of the check runner, always present).

The guard test and its in-repo control are a matched pair: the control proves
``grep`` *does* surface a file reached through a command-line directory path,
so the symlink test's empty result is attributable to the containment guard
rejecting the escaping realpath — not to grep silently failing to see it.
"""

import os
import subprocess

import run_checks.grep as grep_mod
import run_checks_impl as rci


def _check(**kw):
    """Build a check dict with the required id/severity/description defaults."""
    base = {"id": "test-check", "severity": "medium", "description": "d"}
    base.update(kw)
    return base


# ── invert_file_check branch (file-level "pattern present, neg_pattern absent") ──


def test_invert_check_flags_file_missing_neg_pattern(tmp_path):
    """A file containing `pattern` but not `negative_pattern` → one file-level finding."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.py").write_text("import requests\nrequests.get(url)\n", encoding="utf-8")
    check = _check(
        pattern=r"requests\.get",
        paths=["src"],
        include=["*.py"],
        negative_pattern="timeout",
        invert_file_check=True,
    )
    findings = rci.run_check(check, str(tmp_path))
    assert len(findings) == 1, findings
    check_id, file_line, _msg = findings[0]
    assert check_id == "test-check"
    assert file_line == "src/bad.py"  # file-level: bare path, no :lineno


def test_invert_check_silent_when_neg_pattern_present(tmp_path):
    """A file containing both `pattern` and `negative_pattern` → no finding."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.py").write_text(
        "import requests\nrequests.get(url, timeout=5)\n", encoding="utf-8"
    )
    check = _check(
        pattern=r"requests\.get",
        paths=["src"],
        include=["*.py"],
        negative_pattern="timeout",
        invert_file_check=True,
    )
    assert rci.run_check(check, str(tmp_path)) == []


def test_invert_check_reports_in_repo_file_reached_via_command_line_dir(tmp_path):
    """Control for the symlink guard: an in-repo dir named in `paths` IS scanned.

    Establishes that grep surfaces `real_src/evil.py` when the path stays inside
    the repo — so the empty result in the symlink test below is the containment
    guard at work, not grep failing to reach the file. Uses the same trailing-
    slash path shape as the symlink test to keep the only difference the symlink.
    """
    repo = tmp_path / "repo"
    d = repo / "real_src"
    d.mkdir(parents=True)
    (d / "evil.py").write_text("import requests\nrequests.get(url)\n", encoding="utf-8")
    check = _check(
        pattern=r"requests\.get",
        paths=["real_src/"],
        include=["*.py"],
        negative_pattern="timeout",
        invert_file_check=True,
    )
    findings = rci.run_check(check, str(repo))
    assert len(findings) == 1, findings
    assert findings[0][1] == "real_src/evil.py"


def test_invert_check_skips_symlink_dir_escaping_repo(tmp_path):
    """A `paths` entry that is a symlink to a dir outside the repo → guard skips it.

    grep follows a symlinked directory given on the command line, so it emits
    `linked_src/evil.py`; the realpath of that path lands outside `repo_root`,
    and the containment guard rejects it before opening. With the guard removed
    this file (pattern present, `timeout` absent) would be reported.

    The trailing slash on the path is load-bearing, not cosmetic: BSD grep
    (macOS) only dereferences a command-line symlink-to-directory when the path
    ends in `/`. Without it this test is a no-op on macOS (grep never emits the
    file, so the guard is never exercised). The control test above shares the
    trailing-slash shape so the pair isolates the symlink as the only variable.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text(
        "import requests\nrequests.get(url)\n", encoding="utf-8"
    )
    os.symlink(outside, repo / "linked_src")  # command-line path escapes the repo
    check = _check(
        pattern=r"requests\.get",
        paths=["linked_src/"],
        include=["*.py"],
        negative_pattern="timeout",
        invert_file_check=True,
    )
    # Precondition (in-suite guard against a silent no-op): grep must actually
    # surface the escaping symlink path, or this test proves nothing — the
    # containment guard would never be reached and it would pass vacuously. If a
    # grep flavor stops dereferencing the command-line symlinked dir, fail loudly
    # here instead of green below. (The empty run_check result is then genuinely
    # attributable to the guard, not to grep not seeing the file.)
    raw_hits = grep_mod.run_grep(r"requests\.get", ["linked_src/"], ["*.py"], [], str(repo))
    assert any("evil.py" in h for h in raw_hits), (
        "precondition: grep did not surface the escaping symlink path; the "
        f"containment guard is not exercised by this test. hits={raw_hits}"
    )
    findings = rci.run_check(check, str(repo))
    assert findings == [], findings


# ── per-line negative_pattern filter (non-invert) ────────────────────────────


def test_per_line_negative_pattern_filters_matching_lines(tmp_path):
    """Hits are kept unless the matched line also matches `negative_pattern`."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "todos.py").write_text(
        "# TODO fix this\n# TODO (deferred) later\n", encoding="utf-8"
    )
    check = _check(
        pattern="TODO",
        paths=["src"],
        include=["*.py"],
        negative_pattern=r"\(deferred\)",
    )
    findings = rci.run_check(check, str(tmp_path))
    assert len(findings) == 1, findings  # line 2 filtered out
    _check_id, file_line, _msg = findings[0]
    assert file_line == "src/todos.py:1"


# ── simple pattern match (no invert, no negative_pattern) ─────────────────────


def test_simple_pattern_reports_every_hit(tmp_path):
    """With no negative_pattern and no invert, each grep hit becomes a finding."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "danger.py").write_text("x = eval(user_input)\ny = 1\n", encoding="utf-8")
    check = _check(pattern=r"eval\(", paths=["src"], include=["*.py"])
    findings = rci.run_check(check, str(tmp_path))
    assert len(findings) == 1, findings
    check_id, file_line, _msg = findings[0]
    assert check_id == "test-check"
    assert file_line == "src/danger.py:1"


# ── empty-valid_paths guard (fresh-install / unsubstituted placeholder paths) ──


def test_run_grep_empty_valid_paths_returns_without_scanning(tmp_path, monkeypatch):
    """When no `paths:` entry resolves under repo_root, run_grep returns [] and
    never shells out — the guard that stops a fresh install (placeholder paths
    like `<api module>/`) from triggering a CWD-wide scan that flags every file.

    A subprocess spy is the mutation-catcher: dropping the guard would call grep
    (`calls` non-empty). Asserting on `calls`, not on the result, sidesteps the
    BSD-vs-GNU grep flavor difference (BSD grep with no path operand reads empty
    stdin and returns [] regardless — the spy does not)."""
    (tmp_path / "match.py").write_text("eval(x)\n", encoding="utf-8")  # a CWD scan would hit this
    calls = []

    def _spy(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    monkeypatch.setattr(grep_mod.subprocess, "run", _spy)
    out = grep_mod.run_grep(r"eval\(", ["does_not_exist/"], ["*.py"], [], str(tmp_path))
    assert out == []
    assert calls == [], "run_grep shelled out despite no resolvable paths"
