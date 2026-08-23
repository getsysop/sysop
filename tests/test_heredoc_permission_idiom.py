"""Drift guard for the Phase 126 Python-heredoc permission idiom (Tier C).

Every inline `python3 - <<` heredoc in a shipped skill must be auto-approvable by the
single allow-rule `Bash(python3 -:*)` with zero reliance on undocumented permission
behavior. A `claude-code-guide` probe of the official permissions doc (Phase 126)
established the load-bearing facts this guard encodes:

  * env-var *assignment prefixes* are NOT stripped by the matcher, so `VAR=... python3 -`
    and `PATH="..." python3 -` do NOT match `Bash(python3 -:*)`;
  * a `.venv/bin/python3 -` command word does not match that rule either (and there is
    no `Bash(.venv/bin/python3 -:*)` rule shipped), and it breaks on non-venv consumers;
  * a `[ -x ... ] && PATH=...` compound splits into subcommands whose auto-approval the
    docs do not confirm.

The converged idiom is therefore: command word literally `python3`, any shell values
passed as *positional args* (never env prefixes), and PyYAML resolved for venv-only
consumers by an in-heredoc `sys.path` bootstrap. These tests fail if any skill drifts
back to a prefix / `.venv/bin/python3 -` / `[ -x ] && PATH=` form, or adds a
yaml-importing heredoc without the bootstrap.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"
SETTINGS = REPO_ROOT / "core" / "companion" / ".claude" / "settings.json"

# rglob over every skill-tree markdown, not one level of SKILL.md: the round's HD-1
# planted a yaml-importing heredoc in a shipped `_shared/` partial and every check in
# this module was blind to it — agents execute those files exactly like SKILL.md bodies.
SKILL_FILES = sorted(SKILLS_DIR.rglob("*.md"))

# The canonical venv bootstrap block every yaml-importing heredoc must carry, verbatim,
# at the 4-space indent of the `except ImportError:` arm it lives in. Phase 222 (Q-100 /
# upstream #349) replaced the old one-line CWD-relative glob: `/document-work` runs in
# the task worktree, and a linked worktree never carries a `.venv`, so the CWD glob
# found nothing exactly where the skill runs. The block resolves the MAIN checkout via
# `git rev-parse --git-common-dir` (stripping git's discovery vars — the
# `tests/test_git_env_hermeticity.py` reason), probes both `.venv/` and `venv/` layouts
# there, and only then falls back to the CWD — the `validate_tasks.py` resolution order,
# ported.
BOOTSTRAP_BLOCK = '''    import glob, os, subprocess
    _sites = []
    try:
        _r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
            env={_k: _v for _k, _v in os.environ.items()
                 if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                               "GIT_COMMON_DIR", "GIT_INDEX_FILE")},
        )
        _g = _r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        _g = ""
    for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
        for _layout in (".venv", "venv"):
            _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
    sys.path[:0] = _sites'''

# One distinctive line of the block, used in failure messages and quick membership
# checks; the block-identity test below is the real pin.
BOOTSTRAP_MARKER = (
    '_sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))'
)

# Opener for an inline stdin heredoc driven by a literal `python3` command word.
# Tolerates positional args before AND/OR after the `<<'DELIM'` redirect, and markdown
# list indentation.
#
# The positional args are matched as *any* double-quoted tokens. The arg count used to
# be pinned to at most one on each side, which left ELEVEN of the twenty heredocs
# invisible to every check in this module (measured on the pre-222 tree): six
# `claim-task` multi-arg openers, both review-skill marker openers, and three
# `/review-close` openers (two `python3 - "<worktree-path>" "<branch name>" <<'PY'`,
# one `python3 - "$SMOKE_WORKTREE_DIRS" "$APPROVED_BRANCHES" <<'EOF'`),
# the last three carrying venv-bootstrap copies; Phase 222 widened it. The
# earlier version of the same lesson: the arg used to be pinned to `"$VAR"`, so
# converting the four openers to substituted `"<TASK_ID>"` literals dropped the corpus
# from 7 heredocs to 3 and the floor below caught it. A guard whose detector encodes
# one spelling of the thing it guards silently narrows to nothing when that spelling is
# fixed, so the shape question stays here (is there a quoted operand?) and the *content*
# question — a `$VAR` operand is a phantom — belongs to `test_phantom_shell_vars.py`,
# which forbids it directly.
_OPENER = re.compile(
    r"""^(?P<indent>[ \t]*)python3\ -\ (?:"[^"]*"\ )*"""
    r"""<<'(?P<delim>[A-Za-z_]+)'(?:\ "[^"]*")*\s*$""",
    re.VERBOSE,
)


def _iter_heredocs(text: str):
    """Yield (line_no, delim, dedented_body) for each `python3 - <<` heredoc."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _OPENER.match(lines[i])
        if not m:
            i += 1
            continue
        indent, delim = m.group("indent"), m.group("delim")
        body = []
        j = i + 1
        while j < len(lines):
            if lines[j].rstrip() == indent + delim or lines[j].strip() == delim:
                break
            body.append(lines[j][len(indent):] if lines[j].startswith(indent) else lines[j])
            j += 1
        yield i + 1, delim, "\n".join(body)
        i = j + 1


def _all_heredocs():
    out = []
    for f in SKILL_FILES:
        for ln, delim, body in _iter_heredocs(f.read_text(encoding="utf-8")):
            out.append((f.relative_to(REPO_ROOT), ln, delim, body))
    return out


ALL_HEREDOCS = _all_heredocs()


def test_at_least_the_known_heredocs_are_found():
    """Sanity floor so a regex regression can't make the guard vacuously pass.

    Phase 126 converged 7 inline heredocs and this floor said >=7 ever since, while
    the pre-222 opener actually saw 9. Phase 222's multi-arg widening surfaced the
    real 20-heredoc corpus: ELEVEN heredocs were invisible to every check in this
    module (derived on the pre-phase tree — six `claim-task` multi-arg openers, both
    review-skill marker openers, and three `/review-close` openers, the last three
    carrying venv-bootstrap copies). New ones may be added, never fewer.
    """
    assert len(ALL_HEREDOCS) >= 20, (
        f"expected >=20 python3 heredocs across skills, found {len(ALL_HEREDOCS)} "
        "(opener regex may have drifted)"
    )


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_venv_bin_python3_heredoc(skill):
    """`.venv/bin/python3 - <<` matches no allow-rule and breaks non-venv consumers."""
    text = skill.read_text(encoding="utf-8")
    hits = [ln for ln in text.splitlines() if ".venv/bin/python3 - <<" in ln]
    assert not hits, f"{skill.name}: forbidden `.venv/bin/python3 - <<` heredoc: {hits}"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_assignment_prefix_on_python_heredoc(skill):
    """`VAR=... python3 - <<` — an assignment prefix — does not match Bash(python3 -:*)."""
    text = skill.read_text(encoding="utf-8")
    prefix_re = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=.*\bpython3 - <<")
    hits = [ln for ln in text.splitlines() if prefix_re.match(ln)]
    assert not hits, f"{skill.name}: forbidden assignment-prefix heredoc: {hits}"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_path_prefix_guard(skill):
    """The removed `[ -x .venv/bin/python3 ] && PATH=...` venv-prefix idiom must not return."""
    text = skill.read_text(encoding="utf-8")
    hits = [ln for ln in text.splitlines() if "[ -x .venv/bin/python3 ]" in ln]
    assert not hits, f"{skill.name}: forbidden `[ -x .venv/bin/python3 ]` guard: {hits}"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_compound_before_python_heredoc(skill):
    """A `python3 - <<` opener must be a standalone command, not the tail of an
    `x && python3 - <<` / `x; python3 - <<` / `x | python3 - <<` compound — each
    subcommand is matched independently, so a preceding one could gate the whole line.
    """
    text = skill.read_text(encoding="utf-8")
    compound_re = re.compile(r"(?:&&|\|\||;|\|)\s*python3 - <<")
    hits = [ln for ln in text.splitlines() if compound_re.search(ln)]
    assert not hits, f"{skill.name}: `python3 - <<` heredoc preceded by a compound operator: {hits}"


def test_every_yaml_heredoc_carries_the_bootstrap():
    """A heredoc that imports yaml must resolve venv PyYAML via the sys.path bootstrap.

    Matches both `import yaml` and `from yaml import ...`, anchored to line start so a
    commented-out import doesn't count.
    """
    yaml_import_re = re.compile(r"^\s*(?:import yaml\b|from yaml import\b)", re.MULTILINE)
    offenders = []
    for rel, ln, _delim, body in ALL_HEREDOCS:
        if yaml_import_re.search(body):
            if BOOTSTRAP_MARKER not in body:
                offenders.append(f"{rel}:{ln}")
    assert not offenders, (
        "yaml-importing heredocs missing the venv bootstrap "
        f"`{BOOTSTRAP_MARKER}`: {offenders}"
    )


def test_every_bootstrap_is_the_canonical_block_verbatim():
    """Every bootstrap copy must be byte-identical to BOOTSTRAP_BLOCK.

    The marker check above says a bootstrap is *present*; this says it is the *same*
    bootstrap. Nine copies of a multi-line block drift one site at a time (the Q-100
    filing itself found `/review-close` had grown two copies the entry did not know
    about), and a site that half-applies a future change would still carry the marker
    line. Comparing the dedented region from the block's first line to its last keeps
    'edit one, edit all' enforceable mechanically.
    """
    first_line = BOOTSTRAP_BLOCK.splitlines()[0]
    last_line = BOOTSTRAP_BLOCK.splitlines()[-1]
    checked, offenders = 0, []
    for rel, ln, _delim, body in ALL_HEREDOCS:
        if BOOTSTRAP_MARKER not in body:
            continue
        lines = body.splitlines()
        try:
            start = next(i for i, l in enumerate(lines) if l == first_line)
            end = next(i for i, l in enumerate(lines[start:], start) if l == last_line)
        except StopIteration:
            offenders.append(f"{rel}:{ln} (block boundaries not found)")
            continue
        region = "\n".join(lines[start : end + 1])
        if region != BOOTSTRAP_BLOCK:
            offenders.append(f"{rel}:{ln} (block differs from canonical)")
        checked += 1
    assert checked >= 9, (
        f"expected >=9 bootstrap copies to compare, found {checked} — "
        "the extractor or the corpus regressed"
    )
    assert not offenders, "non-canonical bootstrap copies:\n" + "\n".join(offenders)


def test_every_heredoc_body_compiles():
    """The edited Python must be syntactically valid (heredocs have no other CI surface)."""
    failures = []
    for rel, ln, delim, body in ALL_HEREDOCS:
        try:
            compile(body, f"{rel}:{ln}", "exec")
        except SyntaxError as e:
            failures.append(f"{rel}:{ln} (<<{delim}): {e}")
    assert not failures, "heredoc Python failed to compile:\n" + "\n".join(failures)


def test_validate_tasks_self_resolves_yaml():
    """`validate_tasks.py` must keep its own venv PyYAML `sys.path` bootstrap.

    review-close Step 4c invokes it as bare `python3 scripts/validate_tasks.py` (Phase
    126 removed the shared `[ -x ] && PATH=` prefix that used to make it venv-aware). That
    bare form only serves venv-only consumers because the script self-resolves yaml; if
    this regresses, a venv-only consumer's close aborts with a false "validator rejected"
    AFTER the status flip + `git mv` already ran (adversarial-review Finding 1).

    Phase 182 widened the resolution (script-anchored first — the file's ancestors,
    then the main checkout via git-common-dir — and only then the CWD, across both
    `.venv/` and `venv/`), so the literal `BOOTSTRAP_LINE` above — still exactly right for the
    in-heredoc copies this module's other tests guard — is no longer the shape here.
    The invariant is unchanged and the canonical form is pinned by
    `tests/test_venv_pyyaml_bootstrap.py`; this assertion stays as the local
    check that the script self-resolves at all.
    """
    vt = REPO_ROOT / "core" / "companion" / "scripts" / "validate_tasks.py"
    body = vt.read_text(encoding="utf-8")
    assert "sys.path.insert(0, _site)" in body and "_layout" in body, (
        "validate_tasks.py lost its venv PyYAML sys.path bootstrap — bare "
        "`python3 scripts/validate_tasks.py` would fail on venv-only consumers"
    )


def test_settings_ships_the_load_bearing_rule():
    """The one rule the converged heredocs depend on must be present in the template."""
    text = SETTINGS.read_text(encoding="utf-8")
    assert '"Bash(python3 -:*)"' in text, (
        "settings.json is missing the Bash(python3 -:*) allow-rule that every "
        "converged `python3 - <<` heredoc relies on"
    )


# ---------------------------------------------------------------------------
# Functional proof of the Phase 222 bootstrap (Q-100 / upstream #349): the block is
# EXECUTED, not just pattern-matched. Both tests run the pinned BOOTSTRAP_BLOCK
# verbatim, so a future edit that keeps the marker line but breaks the behaviour
# reddens here rather than shipping.
# ---------------------------------------------------------------------------

import shutil
import subprocess
import sys as _sys
import textwrap


def _run_bootstrap_probe(cwd):
    """Execute the canonical block at `cwd` and report which probe module resolved."""
    script = (
        "import sys\n"
        + textwrap.dedent(BOOTSTRAP_BLOCK)
        + "\ntry:\n"
        "    import _sysop_q100_probe as p\n"
        "    print('RESOLVED', p.__file__)\n"
        "except ImportError:\n"
        "    print('UNRESOLVED')\n"
    )
    return subprocess.run(
        [_sys.executable, "-", ],
        input=script,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=60,
    )


def _plant_probe(root, marker):
    site = root / ".venv" / "lib" / "python3.99" / "site-packages"
    site.mkdir(parents=True)
    (site / "_sysop_q100_probe.py").write_text(f"MARKER = {marker!r}\n", encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_bootstrap_resolves_main_checkout_venv_from_a_linked_worktree(tmp_path):
    """The defect Q-100 filed, reproduced and then fixed: /document-work runs its
    heredoc in the task worktree, which never carries a `.venv`. The old CWD-relative
    glob found nothing there; the shipped block must reach the MAIN checkout's venv."""
    main = tmp_path / "main"
    main.mkdir()
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("GIT_")}
    env.setdefault("HOME", str(tmp_path))

    def git(*args, cwd=main):
        subprocess.run(
            ["git", *args], cwd=str(cwd), check=True, capture_output=True, env=env
        )

    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "x")
    _plant_probe(main, "main-venv")
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", str(wt), "-b", "task-branch")

    r = _run_bootstrap_probe(wt)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("RESOLVED"), (
        "bootstrap failed to resolve the main checkout's venv from a linked "
        f"worktree:\n{r.stdout}\n{r.stderr}"
    )
    assert str(main) in r.stdout, f"resolved the wrong venv: {r.stdout}"


def test_bootstrap_falls_back_to_cwd_outside_any_git_repo(tmp_path):
    """No git repo at all (or git absent): the block must degrade to the old
    CWD-relative behaviour rather than erroring — the pre-222 contract for every
    site that runs from the main checkout."""
    _plant_probe(tmp_path, "cwd-venv")
    r = _run_bootstrap_probe(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("RESOLVED"), (
        f"bootstrap lost its CWD fallback:\n{r.stdout}\n{r.stderr}"
    )
