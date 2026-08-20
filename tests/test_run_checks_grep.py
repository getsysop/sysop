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
    check_id, file_line, _msg, _ident = findings[0]
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
    _check_id, file_line, _msg, _ident = findings[0]
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
    check_id, file_line, _msg, _ident = findings[0]
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


# ── Phase 133: exclude_dir subtree exclusion ────────────────────────────────
# The file-glob `exclude:` cannot drop a whole subtree, so a broad `paths:`
# root (a package with migrations/ inside it) couldn't be narrowed — the
# leg-5 dogfood's 17 false CRITICALs. `exclude_dir:` maps to grep
# --exclude-dir (directory-BASENAME globs, any depth) and is mirrored in the
# _iter_check_files walk used by position_check.


def _write_pkg_with_migrations(tmp_path):
    (tmp_path / "pkg" / "migrations").mkdir(parents=True)
    (tmp_path / "pkg" / "main.py").write_text('q = f"SELECT {x}"\n')
    (tmp_path / "pkg" / "migrations" / "0001_init.py").write_text(
        'q = f"SELECT {x}"\n')


def test_exclude_dir_drops_subtree_from_grep(tmp_path):
    _write_pkg_with_migrations(tmp_path)
    check = {
        "id": "sql-fstring",
        "paths": ["pkg/"],
        "include": ["*.py"],
        "exclude_dir": ["migrations"],
        "pattern": 'f"SELECT',
        "severity": "critical",
        "description": "f-string SQL",
    }
    findings = rci.run_check(check, str(tmp_path))
    hit_paths = [f[1] for f in findings]
    assert any("pkg/main.py" in p for p in hit_paths), findings
    assert not any("migrations" in p for p in hit_paths), findings


def test_without_exclude_dir_subtree_still_scanned(tmp_path):
    """Non-tautological control: the same check minus exclude_dir DOES hit the
    migrations file — proving the flag (not path resolution) does the work."""
    _write_pkg_with_migrations(tmp_path)
    check = {
        "id": "sql-fstring",
        "paths": ["pkg/"],
        "include": ["*.py"],
        "pattern": 'f"SELECT',
        "severity": "critical",
        "description": "f-string SQL",
    }
    findings = rci.run_check(check, str(tmp_path))
    assert any("migrations" in f[1] for f in findings), findings


def test_iter_check_files_honors_exclude_dirs(tmp_path):
    _write_pkg_with_migrations(tmp_path)
    got = sorted(rci._iter_check_files(
        ["pkg/"], ["*.py"], [], str(tmp_path), exclude_dirs=["migrations"]))
    assert any(p.endswith("pkg/main.py") for p in got)
    assert not any("migrations" in p for p in got)


def test_iter_check_files_skips_root_whose_basename_matches_exclude_dir(tmp_path):
    """Adversarial-review fix (2026-07-19): grep --exclude-dir also skips a
    command-line directory whose own basename matches; the walk must mirror
    that or the position-check half of a check scans what grep skipped."""
    _write_pkg_with_migrations(tmp_path)
    got = list(rci._iter_check_files(
        ["pkg/migrations"], ["*.py"], [], str(tmp_path),
        exclude_dirs=["migrations"]))
    assert got == []


def _min_check(**kw):
    c = {"id": "grep-c", "severity": "medium", "description": "d"}
    c.update(kw)
    return c


class TestUnroutableVsSkipped:
    """Phase 189's round found the shipped predicate did not match its own message: a
    check with a `position_check:` but no resolvable paths was recorded UNROUTABLE with
    the detail 'no pattern: or position_check: … cannot execute in any environment' —
    a false claim AND a false remediation, which is the mislabelling #239 exists to stop.
    It also found the sibling test pinned nothing, because the arm it covered returned
    the same Outcome either way. These two distinguish the arms."""

    def test_a_position_check_without_paths_is_a_SKIP_not_unroutable(self, tmp_path):
        from run_checks.accounting import RunReport
        r = RunReport([{"id": "grep-c"}])
        grep_mod.run_check(
            _min_check(position_check={"earlier": "a", "later": "b"}, paths=[]),
            str(tmp_path), r)
        assert r.status_of("grep-c") == "skipped", (
            "a check that declares an executable form was told it can never run"
        )

    def test_neither_pattern_nor_position_check_is_unroutable(self, tmp_path):
        from run_checks.accounting import RunReport
        r = RunReport([{"id": "grep-c"}])
        grep_mod.run_check(_min_check(paths=["src/"]), str(tmp_path), r)
        assert r.status_of("grep-c") == "unroutable"


# ── Phase 212 / Q-026: the grep hit parse ────────────────────────────────────
#
# `grep -rn` emits `path:lineno:content`, which no split can parse: a colon is
# legal in a path AND ordinary in content. The filed remedy (rsplit instead of
# split) trades the exotic failure for a common one, so `--null` is used
# instead. Each test below names the concrete way its absence went wrong.


class TestGrepHitParse:
    """Both defects the pre-212 `split(':', 2)` produced, plus their controls.

    The controls matter more than the attacks here: the repo-root case
    (`test_colon_in_repo_root_*`) FAILED SILENTLY — the branch produced zero
    findings while the accounting reported `executed`, which is the one shape
    a green run cannot be distinguished from.
    """

    def test_colon_in_source_path_keeps_the_line_number(self, tmp_path):
        """Filed shape: `src/a:b/c.py:1:code` split from the left put the
        line number in the path column and shifted the content right by one
        field, losing the line number entirely."""
        (tmp_path / "src" / "a:b").mkdir(parents=True)
        (tmp_path / "src" / "a:b" / "c.py").write_text("code here\n", encoding="utf-8")
        findings = rci.run_check(
            _check(pattern="code", paths=["src"], include=["*.py"]), str(tmp_path))
        assert len(findings) == 1, findings
        assert findings[0][1] == "src/a:b/c.py:1", findings[0][1]

    def test_colon_in_content_is_not_corrupted(self, tmp_path):
        """The control that disqualifies the filed rsplit remedy. This hit
        works correctly pre-212; rsplit(':', 2) would report the path as
        `src/d.py:1:x = "a` and the content as `c"  code`."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "d.py").write_text('x = "a:b:c"  code\n', encoding="utf-8")
        findings = rci.run_check(
            _check(pattern="code", paths=["src"], include=["*.py"]), str(tmp_path))
        assert len(findings) == 1, findings
        assert findings[0][1] == "src/d.py:1", findings[0][1]

    def test_colon_in_repo_root_still_finds_the_file(self, tmp_path):
        """The silent one, and the reason this is a gate-truth defect rather
        than a cosmetic parse bug.

        `invert_file_check` split the ABSOLUTE hit before stripping the repo
        prefix, so a colon anywhere in `repo_root` — a CI job directory named
        `job:42` is enough, no source path involved — truncated every path to a
        fragment. The containment guard then rejected all of them and the
        branch returned zero findings while reporting `executed`.
        """
        root = tmp_path / "job:42"
        (root / "src").mkdir(parents=True)
        (root / "src" / "f.py").write_text("createObjectURL(x)\n", encoding="utf-8")
        findings = rci.run_check(
            _check(pattern="createObjectURL", negative_pattern="revokeObjectURL",
                   invert_file_check=True, paths=["src"], include=["*.py"]),
            str(root))
        assert len(findings) == 1, (
            "the whole invert branch went silent on a colon-bearing checkout path"
        )

    def test_colon_free_repo_root_is_the_control(self, tmp_path):
        """Non-vacuity control for the test above: identical fixture, clean
        root. If this ever fails the sibling proves nothing."""
        root = tmp_path / "job42"
        (root / "src").mkdir(parents=True)
        (root / "src" / "f.py").write_text("createObjectURL(x)\n", encoding="utf-8")
        findings = rci.run_check(
            _check(pattern="createObjectURL", negative_pattern="revokeObjectURL",
                   invert_file_check=True, paths=["src"], include=["*.py"]),
            str(root))
        assert len(findings) == 1, findings

    def test_anchored_negative_pattern_is_not_defeated_by_a_colon_path(self, tmp_path):
        """The false POSITIVE half. With the line number stolen into the
        content column, content began `1:` — so `^SECRET` could never match and
        a line the check was configured to skip was reported as a finding."""
        (tmp_path / "a:b").mkdir()
        (tmp_path / "a:b" / "g.py").write_text("SECRET code\n", encoding="utf-8")
        findings = rci.run_check(
            _check(pattern="code", negative_pattern="^SECRET",
                   paths=["a:b"], include=["*.py"]), str(tmp_path))
        assert findings == [], (
            "an anchored negative_pattern was defeated by the stolen line number"
        )

    def test_anchored_negative_pattern_control_clean_path(self, tmp_path):
        """Non-vacuity control: same filter, colon-free path."""
        (tmp_path / "ab").mkdir()
        (tmp_path / "ab" / "g.py").write_text("SECRET code\n", encoding="utf-8")
        assert rci.run_check(
            _check(pattern="code", negative_pattern="^SECRET",
                   paths=["ab"], include=["*.py"]), str(tmp_path)) == []

    def test_path_containing_a_line_number_shape_needs_the_nul(self, tmp_path):
        """The ONE fixture that binds `--null` itself.

        Every other case here is resolvable by the colon fallback, so Phase
        212's review round deleted `--null` from the grep command and the whole
        suite stayed green — the leg's entire mechanism was unguarded by its own
        tests. A path segment shaped like `<name>:<digits>:` is genuinely
        ambiguous under any colon parse: `a:12:b/c.py:3:code` can be read as
        path `a`, line 12, or as path `a:12:b/c.py`, line 3. Only the NUL
        separator settles it, so removing the flag reds exactly this test.
        """
        d = tmp_path / "a:12:b"
        d.mkdir()
        (d / "c.py").write_text("zzz\nzzz\ncode here\n", encoding="utf-8")
        findings = rci.run_check(
            _check(pattern="code", paths=["a:12:b"], include=["*.py"]), str(tmp_path))
        assert len(findings) == 1, findings
        assert findings[0][1] == "a:12:b/c.py:3", findings[0][1]

    def test_run_grep_back_compat_shape_is_unchanged(self, tmp_path):
        """`run_grep` is the documented re-export surface. It must keep
        emitting `path:lineno:content` even though the run now uses --null,
        because an external caller parses that shape."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "d.py").write_text("code here\n", encoding="utf-8")
        lines = rci.run_grep("code", ["src"], ["*.py"], [], str(tmp_path))
        assert len(lines) == 1, lines
        assert "\0" not in lines[0], "NUL leaked into the back-compat contract"
        assert lines[0].endswith("/src/d.py:1:code here"), lines[0]


class TestParseHitUnit:
    """`parse_hit` directly, including the no-NUL fallback path that only an
    external caller or a --null-less grep can reach."""

    def test_null_form_is_split_on_the_nul(self):
        assert grep_mod.parse_hit("src/a:b/c.py\x001:x = 'q:r'") == (
            "src/a:b/c.py", "1", "x = 'q:r'")

    def test_colon_fallback_reproduces_pre_212_split_exactly(self):
        """The fallback is a COMPATIBILITY path, so its contract is sameness,
        not correctness — including the same known-wrong answer on a
        colon-bearing path.

        The first cut was greedy (last `:<digits>:` boundary wins) on the
        reasoning that colon-in-path is the thing being fixed. The round
        measured it: greedy is WORSE than what it replaces on the shapes this
        module's own commentary calls ordinary content colons. These fixtures
        are the ones that caught it; `x = 'a:b'` alone did not, because it has
        no digits between colons."""
        for hit in ("src/d.py:1:x = 'a:b'",
                    'src/d.py:1:ts = "10:30:00"',      # timestamp
                    "src/d.py:1:x = arr[1:2:3]",        # slice step
                    'src/d.py:1:u = "http://h:8080:x"'):  # host:port
            assert grep_mod.parse_hit(hit) == tuple(hit.split(":", 2)), hit

    def test_hit_with_no_line_number_still_attributes_a_file(self):
        assert grep_mod.parse_hit("src/d.py") == ("src/d.py", None, "")

    def test_null_form_without_a_line_number_keeps_the_path(self):
        """No colon after the NUL — exercises the `sep` arm."""
        assert grep_mod.parse_hit("src/d.py\x00no-number-here") == (
            "src/d.py", None, "no-number-here")

    def test_null_form_with_a_non_numeric_first_field_is_not_a_line_number(self):
        """Exercises the `.isdigit()` arm specifically, which the sibling above
        cannot reach: here a colon IS present, so `sep` is truthy and only the
        digit test can reject it. Dropping `.isdigit()` survived the round
        because every other fixture either had no colon or had real digits.

        `Binary file /x/y.py matches` is the live shape — but grep can also emit
        a hit whose first post-NUL field is non-numeric, and calling that a line
        number would put junk in a finding key."""
        assert grep_mod.parse_hit("src/d.py\x00abc:rest") == (
            "src/d.py", None, "abc:rest")

    def test_the_unparsed_remainder_is_preserved_not_discarded(self):
        """`return path, None, rest` — not `path, None, ""`. Flipping it survived
        the round because every fixture discarded the third element with `_`.
        The remainder is what a caller needs to tell `Binary file … matches`
        apart from a genuinely malformed line."""
        _p, _l, content = grep_mod.parse_hit("src/d.py\x00some remainder text")
        assert content == "some remainder text"


class TestBinaryClassifiedFileIsNotAFinding:
    """Phase 212's review round, execution lens — a regression this phase
    introduced and its round caught before merge.

    `grep` prints `Binary file <path> matches` for any file holding a NUL byte
    — a corrupt or mislabelled `.sql`/`.py` is enough. That line carries no NUL
    separator and no line number. Pre-212 the plain branch dropped it as a side
    effect of its `len(parts) >= 2` guard; the first cut of the `parse_hit`
    rewrite turned that accident into an explicit emit.

    The result was a NEW BLOCKING FINDING on a `severity: critical` check whose
    key was the literal string `Binary file /abs/path matches` — an absolute
    path, so it does not survive a move to another checkout and **cannot be
    baselined portably**. A consumer could not accept it to get green.

    SCORED, because which of these are attacks and which are controls is not
    obvious and guessing it wrong is how a battery flatters itself. Against the
    regressed commit, three fail (plain, negative_pattern, and the
    absolute-path property) and `test_invert_branch_drops_it_too` PASSES — the
    invert branch was already saved by its `realpath` containment guard, which
    rejects the mangled path for an unrelated reason. That test is therefore a
    control here, not an attack: it pins a property that must hold, and it
    happened to hold before by accident.
    """

    @staticmethod
    def _binary_fixture(root):
        (root / "src").mkdir()
        # A real NUL byte is what makes grep call this binary.
        (root / "src" / "tainted.py").write_bytes(b"GRANT SELECT on users\n\x00\n")
        (root / "src" / "clean.py").write_text("GRANT SELECT on users\n", encoding="utf-8")

    def test_plain_branch_drops_a_binary_classified_file(self, tmp_path):
        self._binary_fixture(tmp_path)
        findings = rci.run_check(
            _check(pattern="GRANT", paths=["src"], include=["*.py"]), str(tmp_path))
        assert not any("Binary file" in f[1] for f in findings), findings
        # …and the clean sibling is still reported, so this is not a blanket drop.
        assert [f[1] for f in findings] == ["src/clean.py:1"], findings

    def test_negative_pattern_branch_drops_it_too(self, tmp_path):
        self._binary_fixture(tmp_path)
        findings = rci.run_check(
            _check(pattern="GRANT", negative_pattern="nothing-matches-this",
                   paths=["src"], include=["*.py"]), str(tmp_path))
        assert not any("Binary file" in f[1] for f in findings), findings
        assert [f[1] for f in findings] == ["src/clean.py:1"], findings

    def test_invert_branch_drops_it_too(self, tmp_path):
        self._binary_fixture(tmp_path)
        findings = rci.run_check(
            _check(pattern="GRANT", negative_pattern="revoked",
                   invert_file_check=True, paths=["src"], include=["*.py"]),
            str(tmp_path))
        assert not any("Binary file" in f[1] for f in findings), findings

    def test_no_finding_key_is_ever_an_absolute_path(self, tmp_path):
        """The property that made the regression unbaselineable, asserted
        directly rather than via the one shape that produced it."""
        self._binary_fixture(tmp_path)
        for kind in ({}, {"negative_pattern": "zzz"},
                     {"negative_pattern": "zzz", "invert_file_check": True}):
            findings = rci.run_check(
                _check(pattern="GRANT", paths=["src"], include=["*.py"], **kind),
                str(tmp_path))
            for _cid, file_line, _msg, _ident in findings:
                assert not file_line.startswith("/"), (kind, file_line)
                assert str(tmp_path) not in file_line, (kind, file_line)
