"""The seven conditions Q-011 / upstream #361 sets on any retry — each by execution.

Phase 189 built the enumeration fix (replace the directory operand with a full file
list) and its own review round withdrew it, naming seven ways it was worse than the
defect it closed. Phase 196 ships a different shape — the directory operand is KEPT
and explicit file operands are added only for the population semgrep's built-in
default ignore list eats — and this module is that shape run against each of the
seven, plus the corpus that decided it.

Every test here uses the REAL semgrep binary. #361 was invisible to every mock in
`test_run_checks_semgrep.py` for exactly that reason: the defect lives in semgrep's
own target discovery, which no stub reproduces.

The corpus population is derived from semgrep-core's compiled-in default ignore
list ("Common test paths": test/ tests/ testsuite/ *_test.go), NOT from Q-011's
summary of it, which names only test/ and tests/.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

import run_checks.semgrep as semgrep_mod
from run_checks.accounting import DEGRADED, EXECUTED, RunReport

pytestmark = pytest.mark.skipif(
    shutil.which("semgrep") is None, reason="semgrep not on PATH")

RULES = (
    "rules:\n"
    "  - id: marker\n"
    "    languages: [python]\n"
    "    severity: WARNING\n"
    "    message: marker\n"
    "    pattern: DANGER(...)\n"
    "  - id: marker-go\n"
    "    languages: [go]\n"
    "    severity: WARNING\n"
    "    message: marker go\n"
    "    pattern: DANGER(...)\n"
)
HIT = "def f():\n    DANGER(1)\n"
HIT_GO = "package main\n\nfunc f() {\n\tDANGER(1)\n}\n"

# What the default ignore list eats, at more than one depth and in all four spellings.
IGNORED = [
    "tests/b.py",
    "deep/nested/tests/c.py",      # deep PREFIX: the dir is far from the root
    "tests/nested/deep.py",        # deep SUFFIX: the file is far inside the dir
    "tests/a/b/c/far.py",          # ...and further. R-C05: the round mutated the
                                   # segment scan to one level and nothing noticed,
                                   # because every corpus entry was depth-1 INSIDE.
    "test/d.py",
    "src/tests/e.py",
    "testsuite/f.py",
    "src/handler_test.go",
]
# What it never touches — the controls that must stay scanned in every variant.
CONTROLS = ["src/a.py", "src/handler.go"]

FIXTURES_EXCLUDE = os.path.join(".claude", "semgrep", "fixtures")


def _git(repo, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                       text=True, env=env)
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} -> {r.returncode}: {r.stderr}")
    return r


def _write(repo, rel, body):
    p = os.path.join(str(repo), rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(body)
    return p


def _corpus(root, *, symlink=False, missing=False, untracked=False,
            submodule=False, fixtures=True):
    """The hostile corpus, built before the fix and unchanged by it."""
    os.makedirs(root, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _write(root, ".claude/semgrep/r.yaml", RULES)
    for rel in CONTROLS + IGNORED:
        _write(root, rel, HIT_GO if rel.endswith(".go") else HIT)
    if fixtures:
        # The bundled positive fixtures the shipped --exclude exists to suppress.
        _write(root, ".claude/semgrep/fixtures/positive.py", HIT)
        # A SIBLING whose name merely starts with the excluded prefix. It must
        # survive; a prefix test without the separator would eat it.
        _write(root, ".claude/semgrep/fixtures_x/tests/sibling.py", HIT)
    if symlink:
        os.makedirs(os.path.join(root, ".agents/skills"), exist_ok=True)
        os.symlink("../../src/a.py", os.path.join(root, ".agents/skills/link1"))
        # and one INSIDE the recovered population, which is the sharp case
        os.symlink("../src/a.py", os.path.join(root, "tests/link2.py"))
    if missing:
        _write(root, "tests/gone.py", HIT)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    if missing:
        os.unlink(os.path.join(root, "tests/gone.py"))
    if untracked:
        _write(root, "src/untracked.py", HIT)
        _write(root, "tests/untracked_test.py", HIT)
    if submodule:
        sub = root + "-sub"
        os.makedirs(sub, exist_ok=True)
        _git(sub, "init", "-q", "-b", "main")
        _write(sub, "s1.py", HIT)
        _write(sub, "tests/s2.py", HIT)
        _git(sub, "add", "-A")
        _git(sub, "commit", "-qm", "sub")
        # UNDER tests/, deliberately: at vendor/sub the path predicate rejects it
        # before the isfile filter, so `isfile -> exists` survived every mutation.
        _git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
             sub, "tests/subrepo")
        _git(root, "commit", "-qm", "add sub")
    return root


def _rel_targets(repo, exclude_rel=None):
    """Recovered operands as repo-relative paths.

    Assertions must never substring-match the ABSOLUTE operand: pytest's tmp_path
    embeds the test's own name, so `"fixtures" in target` was true for every target
    in `test_d_the_bundled_fixtures_stay_excluded` — a self-inflicted false positive
    that this helper exists to make unavailable.
    """
    targets, dropped, _failed = semgrep_mod._default_ignored_targets(
        repo, exclude_rel if exclude_rel is not None else FIXTURES_EXCLUDE)
    return [os.path.relpath(t, repo) for t in targets], dropped


def _scan(repo_root, cwd=None):
    """Run the SHIPPED stage and return (findings_rel, report, semgrep_argv)."""
    seen = {}
    real = subprocess.run

    def _spy(argv, *a, **kw):
        if argv and argv[0] == "semgrep":
            seen.setdefault("argv", []).append(list(argv))
        return real(argv, *a, **kw)

    report = RunReport([{"id": "semgrep-marker"}, {"id": "semgrep-marker-go"}])
    ids = {"semgrep-marker": {"id": "semgrep-marker"},
           "semgrep-marker-go": {"id": "semgrep-marker-go"}}
    old = os.getcwd()
    if cwd:
        os.chdir(cwd)
    try:
        import unittest.mock as m
        with m.patch("run_checks.semgrep.subprocess.run", side_effect=_spy):
            out = semgrep_mod._run_semgrep(repo_root, ids, report)
    finally:
        os.chdir(old)
    rels = sorted({fl.rsplit(":", 1)[0] for _, fl, _ in out})
    return rels, report, seen.get("argv", [])


# --------------------------------------------------------------------------
# The corpus itself: the defect, and the fix, on the SAME tree.
# --------------------------------------------------------------------------

def test_the_shipped_stage_now_scans_every_ignored_test_spelling(tmp_path):
    """The fix. All four default-ignore-list spellings come back, at every depth."""
    repo = _corpus(str(tmp_path / "r"))
    rels, report, argv = _scan(repo)
    for want in IGNORED + CONTROLS:
        assert want in rels, f"{want} not scanned — got {rels}"
    assert report.status_of("semgrep-marker") == EXECUTED


def test_the_directory_operand_alone_still_misses_them(tmp_path):
    """The control. If this ever passes, semgrep changed its default ignore list
    and every number in this phase needs re-deriving before anything is trusted."""
    repo = _corpus(str(tmp_path / "r"), fixtures=False)
    r = subprocess.run(
        ["semgrep", "scan", "--config", os.path.join(repo, ".claude/semgrep"),
         "--json", "--metrics=off", "--quiet", repo],
        cwd=repo, capture_output=True, text=True, timeout=300)
    data = json.loads(r.stdout)
    got = {os.path.relpath(x["path"], repo) for x in data.get("results", [])}
    assert got == set(CONTROLS), (
        "the directory operand no longer drops the test tree — #361's premise "
        f"has changed; scanned {got}")
    # and the omission is still traceless, which is why it needed fixing at all
    assert data["paths"].get("skipped") in ([], None)


# --------------------------------------------------------------------------
# (a) path shape follows operand shape
# --------------------------------------------------------------------------

def test_a_relative_repo_root_from_another_cwd_keeps_todays_path_shape(tmp_path):
    """Condition (a). Operands are joined onto repo_root, so they carry ITS shape.

    The failure Phase 189 hit was a second shape: relative finding paths resolved
    against the process CWD, landing as `src/src/a.py` or vanishing. Here the
    recovered operands and the directory operand are the same shape by construction,
    so a relative root behaves exactly as it does today — including its own
    pre-existing limits, which this phase does not widen.
    """
    repo = _corpus(str(tmp_path / "r"))
    abs_rels, _, _ = _scan(repo)
    # every operand carries the same shape as repo_root
    targets, _, _f = semgrep_mod._default_ignored_targets(repo, FIXTURES_EXCLUDE)
    assert targets and all(os.path.isabs(t) for t in targets)
    rel_targets, _, _f = semgrep_mod._default_ignored_targets(".", FIXTURES_EXCLUDE)
    assert rel_targets == [] or all(not os.path.isabs(t) for t in rel_targets)
    # no finding escapes as an absolute path or climbs out of the repo
    for rel in abs_rels:
        assert not os.path.isabs(rel), rel
        assert not rel.startswith(".."), rel


# --------------------------------------------------------------------------
# (b) a tracked symlink aborts the WHOLE scan
# --------------------------------------------------------------------------

def test_b_a_tracked_symlink_does_not_abort_the_scan(tmp_path):
    """Condition (b). Sysop installs `.agents/skills/*` symlinks (Phase 142); a
    consumer who commits them must not lose AST scanning. A symlink is never named
    as an operand, and the directory operand skips symlinks itself."""
    repo = _corpus(str(tmp_path / "r"), symlink=True)
    assert os.path.islink(os.path.join(repo, "tests/link2.py"))
    targets, _ = _rel_targets(repo)
    assert "tests/link2.py" not in targets, (
        "a symlink was named as an operand — that aborts the entire scan")
    rels, report, _ = _scan(repo)
    for want in IGNORED + CONTROLS:
        assert want in rels, f"{want} lost with a tracked symlink present"
    assert report.status_of("semgrep-marker") == EXECUTED


# --------------------------------------------------------------------------
# (c) a tracked file absent from the worktree
# --------------------------------------------------------------------------

def test_c_a_tracked_file_missing_from_the_worktree_does_not_abort(tmp_path):
    """Condition (c). deleted-not-staged, mid-rename, sparse checkout,
    skip-worktree — `git ls-files` lists it, the worktree does not have it."""
    repo = _corpus(str(tmp_path / "r"), missing=True)
    assert "tests/gone.py" in _git(repo, "ls-files").stdout
    assert not os.path.exists(os.path.join(repo, "tests/gone.py"))
    targets, _ = _rel_targets(repo)
    assert "tests/gone.py" not in targets
    rels, report, _ = _scan(repo)
    for want in IGNORED + CONTROLS:
        assert want in rels
    assert report.status_of("semgrep-marker") == EXECUTED


# --------------------------------------------------------------------------
# (d) --exclude stops applying to a named operand
# --------------------------------------------------------------------------

def test_d_the_bundled_fixtures_stay_excluded(tmp_path):
    """Condition (d). `--exclude` does not survive an explicit file operand, so the
    fixtures are filtered out of the recovered list instead of relying on it. The
    positive fixtures are deliberately-violating patterns; if they come back, every
    install reports them as findings."""
    repo = _corpus(str(tmp_path / "r"), fixtures=True)
    # make the fixture look like the recovered population as well
    _write(repo, ".claude/semgrep/fixtures/tests/pos2.py", HIT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fx")
    targets, _ = _rel_targets(repo)
    assert set(IGNORED) <= set(targets), (
        "positive floor first: an absence assertion is satisfied by an EMPTY "
        f"population, which is how two of these passed with the fix disabled. {targets}")
    assert not any(t == FIXTURES_EXCLUDE or t.startswith(FIXTURES_EXCLUDE + "/")
                   for t in targets), targets
    # a SIBLING of the excluded dir must survive — `startswith(exclude_rel)`
    # without the separator, and `exclude_rel in rel`, both eat it (R-B03/R-B04).
    assert ".claude/semgrep/fixtures_x/tests/sibling.py" in targets, targets
    rels, _, _ = _scan(repo)
    assert not any(r.startswith(FIXTURES_EXCLUDE + "/") for r in rels), rels


# --------------------------------------------------------------------------
# (e) untracked files stop being scanned
# --------------------------------------------------------------------------

def test_e_untracked_files_are_still_scanned(tmp_path):
    """Condition (e). The directory operand still discovers untracked files — that
    is the half a pure enumeration lost. And `--others --exclude-standard` adds the
    untracked files under test dirs, which the directory operand cannot see."""
    repo = _corpus(str(tmp_path / "r"), untracked=True)
    rels, _, _ = _scan(repo)
    assert "src/untracked.py" in rels, "untracked file lost — enumeration regression"
    assert "tests/untracked_test.py" in rels, (
        "untracked file under a default-ignored dir not recovered")


def test_e_gitignored_files_are_not_dragged_in(tmp_path):
    """The other direction of (e): `--exclude-standard` must keep honouring
    .gitignore, or the recovery starts scanning build output."""
    repo = _corpus(str(tmp_path / "r"))
    _write(repo, ".gitignore", "tests/generated/\n")
    _write(repo, "tests/generated/gen.py", HIT)
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore")
    targets, _ = _rel_targets(repo)
    assert set(IGNORED) <= set(targets), (
        "positive floor first — an empty population satisfies the line below")
    assert "tests/generated/gen.py" not in targets, targets


# --------------------------------------------------------------------------
# (f) a submodule gitlink
# --------------------------------------------------------------------------

def test_f_a_submodule_gitlink_is_never_named_as_an_operand(tmp_path):
    """Condition (f). `git ls-files` lists a gitlink as ONE entry; naming it would
    expand to many scanned files (or abort). `isfile` is False for it."""
    repo = _corpus(str(tmp_path / "r"), submodule=True)
    assert "tests/subrepo" in _git(repo, "ls-files").stdout
    targets, _ = _rel_targets(repo)
    assert targets, "empty population — the assertion below would prove nothing"
    assert not any(x == "tests/subrepo" or x.startswith("tests/subrepo/")
                   for x in targets), targets
    # the gitlink is INSIDE the recovered population, so the path predicate lets
    # it through and only `isfile` can stop it — which is the point of the move.
    assert semgrep_mod._is_ignored_test_path("tests/subrepo")
    rels, report, _ = _scan(repo)
    for want in IGNORED + CONTROLS:
        assert want in rels
    assert report.status_of("semgrep-marker") == EXECUTED


# --------------------------------------------------------------------------
# (g) the 300s timeout becomes per batch
# --------------------------------------------------------------------------

def test_g_the_scan_stays_exactly_one_semgrep_subprocess(tmp_path):
    """Condition (g). The timeout stays whole-scan because the scan stays one
    subprocess — so the `failed` detail that says 300s remains true. A batching
    fix would have made that line a lie without changing it."""
    repo = _corpus(str(tmp_path / "r"))
    _, _, argv = _scan(repo)
    assert len(argv) == 1, f"{len(argv)} semgrep invocations, expected 1"
    assert "--exclude" in argv[0], "the fixtures exclude was dropped"
    assert repo in argv[0], (
        "the directory operand is no longer present — that is Phase 189's "
        "withdrawn shape, not this one")
    # everything after the directory operand is a recovered FILE under it
    tail = argv[0][argv[0].index(repo) + 1:]
    assert tail, "no operands were recovered — the population is empty"
    for op in tail:
        assert op.startswith(repo + os.sep), op
        assert os.path.isfile(op) and not os.path.islink(op), op
    # and they are sorted, so which files a budget drops is reproducible (R-A04)
    assert tail == sorted(tail), "recovered operands are not in a stable order"


# --------------------------------------------------------------------------
# The operand budget — the condition the seven do NOT name.
# --------------------------------------------------------------------------

def test_the_operand_budget_is_reported_not_silently_applied(tmp_path):
    """semgrep 1.157.0 has no --targets-file and reads no targets from stdin, so
    the recovered population rides on the command line and ARG_MAX is a real
    ceiling. Going over it must be LOUD — silently scanning less is the defect
    this phase closes, not an acceptable way to close it."""
    repo = _corpus(str(tmp_path / "r"))
    for i in range(40):
        _write(repo, f"tests/gen/t{i}.py", HIT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "many")

    full, full_dropped = _rel_targets(repo)      # REAL budget: the candidate set
    assert full_dropped == 0 and len(full) > 40, (full_dropped, len(full))

    real_budget = semgrep_mod._operand_budget
    try:
        semgrep_mod._operand_budget = lambda: 200  # bites well before ARG_MAX
        kept, dropped = _rel_targets(repo)
        assert dropped > 0, "budget did not bite — the test proves nothing"
        _, report, _ = _scan(repo)
        rec = report._records["semgrep-marker"]
        assert rec.status == DEGRADED, (
            f"over-budget scan recorded {rec.status}, not degraded")
        # The disjunct that used to be here — `or "omitted" in detail` — is
        # unconditionally true of BOTH degraded detail strings, so the count was
        # decorative: a detail hardcoding `0` passed while 8 files were dropped.
        assert f"{dropped} test file(s) omitted" in (rec.detail or ""), rec.detail
        assert isinstance(dropped, int) and not isinstance(dropped, bool), (
            "over_budget must be a COUNT, not a flag — `bool(dropped)` keeps "
            "every `if over_budget` firing while the operator is told "
            "'True test file(s) omitted'")
        # the budget must actually be a CEILING, not just a counter: the dropped
        # files are absent from the operand list, and only real candidates count
        assert len(kept) + dropped == len(full), (
            f"{len(kept)} kept + {dropped} dropped != {len(full)} candidates — "
            "the shortfall counts files that were never candidates, or names "
            "files it also reports as omitted")
        assert not any(k.startswith(FIXTURES_EXCLUDE + "/") for k in kept)
        assert rec.reason == "targets-over-budget", (
            f"the machine-readable reason is misrouted: {rec.reason}")
    finally:
        semgrep_mod._operand_budget = real_budget

    # and with the real budget the same tree is clean
    _, dropped = _rel_targets(repo)
    assert dropped == 0
    _, report, _ = _scan(repo)
    assert report.status_of("semgrep-marker") == EXECUTED


# --------------------------------------------------------------------------
# Findings from this phase's own review round.
# --------------------------------------------------------------------------

def test_a_root_semgrepignore_switches_the_recovery_off_entirely(tmp_path):
    """A project `.semgrepignore` REPLACES the built-in default list, so there is
    nothing to recover — and an explicit operand bypasses `.semgrepignore` just as
    it bypasses the built-in list, so recovering anyway OVERRIDES the consumer.

    Found by the round: with `tests/` in their own `.semgrepignore`, the stage
    returned a file they had deliberately excluded.
    """
    repo = _corpus(str(tmp_path / "r"))
    _write(repo, ".semgrepignore", "tests/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore")

    targets, dropped = _rel_targets(repo)
    assert targets == [] and dropped == 0, (
        "the recovery ran despite a project .semgrepignore — it will override "
        f"the consumer's own exclusions: {targets}")

    rels, _, argv = _scan(repo)
    assert argv[0][-1] == repo, "operands beyond the directory were still passed"
    assert "tests/b.py" not in rels, (
        "a path the consumer excluded in .semgrepignore came back as a finding")


def test_a_nested_semgrepignore_does_not_switch_it_off(tmp_path):
    """Only a ROOT `.semgrepignore` disables the built-in list — verified against
    the binary. A nested one must not be read as consent to skip the recovery,
    or one file in one subdirectory silently reopens the whole defect."""
    repo = _corpus(str(tmp_path / "r"))
    _write(repo, "src/.semgrepignore", "# nothing\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "nested")
    targets, _ = _rel_targets(repo)
    assert "tests/b.py" in targets, targets
    rels, _, _ = _scan(repo)
    for want in IGNORED + CONTROLS:
        assert want in rels


def test_a_directory_named_like_a_go_test_file_is_recovered(tmp_path):
    """`*_test.go` has no trailing slash, so in gitignore syntax it matches a
    DIRECTORY of that name too. Found by the round — an incompleteness inside the
    four-entry block this phase scopes itself to."""
    repo = _corpus(str(tmp_path / "r"))
    _write(repo, "helpers_test.go/util.py", HIT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "godir")
    targets, _ = _rel_targets(repo)
    assert "helpers_test.go/util.py" in targets, targets
    rels, _, _ = _scan(repo)
    assert "helpers_test.go/util.py" in rels, rels


def test_the_operand_budget_is_measured_in_bytes_not_characters(tmp_path):
    """exec counts the ENCODED argv. A character-counted budget under-reports by
    up to 4x on astral-plane paths — the one shape that reaches E2BIG while the
    accounting says there is room.

    Its own minimal tree, not `_corpus`: the boundary IS the test, and any other
    candidate consuming budget first makes the absence assertion vacuous. The
    first version of this test used `_corpus` and passed because every file
    dropped — an empty list satisfies "the astral one is absent".
    """
    repo = str(tmp_path / "r")
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, ".claude/semgrep/r.yaml", RULES)
    _write(repo, "src/a.py", HIT)
    name = "\U0001F600" * 8                    # 8 chars, 32 bytes
    _write(repo, "tests/ascii.py", HIT)
    _write(repo, f"tests/{name}.py", HIT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "astral")

    ascii_abs = os.path.join(repo, "tests", "ascii.py")
    astral_abs = os.path.join(repo, "tests", f"{name}.py")
    assert len(os.fsencode(astral_abs)) > len(astral_abs), "corpus is not astral"
    # BYTE costing admits only the ascii file; CHARACTER costing admits both.
    budget = (len(os.fsencode(ascii_abs)) + 1) + (len(astral_abs) + 1)

    real = semgrep_mod._operand_budget
    try:
        semgrep_mod._operand_budget = lambda: budget
        targets, dropped = _rel_targets(repo)
        assert "tests/ascii.py" in targets, (
            f"positive floor: the ascii file must FIT at this budget — {targets}")
        assert not any(name in x for x in targets), (
            f"an astral-plane path was costed by characters, not bytes: {targets}")
        assert dropped == 1, dropped
    finally:
        semgrep_mod._operand_budget = real


def test_the_budget_is_derived_from_the_platform_not_a_flat_guess():
    """A flat 256 KiB was discarding 28% of a 5,000-file population on a platform
    whose measured usable ceiling was ~980 KiB. The budget now derives from
    SC_ARG_MAX, floored at the old constant so it can never get *smaller*."""
    b = semgrep_mod._operand_budget()
    assert b >= semgrep_mod._OPERAND_BUDGET
    limit = os.sysconf("SC_ARG_MAX")
    assert b <= limit // 2, "budget must keep at least half the exec limit spare"


def test_git_calls_do_not_inherit_a_hooks_git_env(tmp_path, monkeypatch):
    """git exports GIT_DIR/GIT_INDEX_FILE into every hook, and four other shipped
    scripts strip them for exactly this reason. Demonstrated consequence on a
    tree with gitignored-but-force-tracked tests: the recovered population goes
    from the right files to none at all, silently."""
    repo = _corpus(str(tmp_path / "r"))
    other = _corpus(str(tmp_path / "other"))
    clean, _ = _rel_targets(repo)
    assert clean, "control is empty — the test would prove nothing"
    monkeypatch.setenv("GIT_DIR", os.path.join(other, ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", os.path.join(other, ".git", "index"))
    monkeypatch.setenv("GIT_WORK_TREE", other)
    leaked, _ = _rel_targets(repo)
    assert leaked == clean, (
        f"GIT_* leaked into the target enumeration: {clean} -> {leaked}")


def test_over_budget_is_loud_on_stderr_not_only_in_the_record(tmp_path, capsys):
    """The commit message calls going over budget LOUD. Nothing asserted the
    stderr — silencing the warning entirely left every test green (R-E05)."""
    repo = _corpus(str(tmp_path / "r"))
    for i in range(40):
        _write(repo, f"tests/gen/t{i}.py", HIT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "many")
    real = semgrep_mod._operand_budget
    try:
        semgrep_mod._operand_budget = lambda: 200
        _scan(repo)
    finally:
        semgrep_mod._operand_budget = real
    err = capsys.readouterr().err
    assert "operand budget" in err and "NOT scanned" in err, err
