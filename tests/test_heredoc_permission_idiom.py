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

SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))

# The canonical venv bootstrap line every yaml-importing heredoc must carry.
BOOTSTRAP_LINE = 'sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")'

# Opener for an inline stdin heredoc driven by a literal `python3` command word.
# Tolerates a positional arg before OR after the `<<'DELIM'` redirect, and markdown
# list indentation.
_OPENER = re.compile(
    r"""^(?P<indent>[ \t]*)python3\ -\ (?:"\$[A-Za-z_][A-Za-z0-9_]*"\ )?"""
    r"""<<'(?P<delim>[A-Za-z_]+)'(?:\ "\$[A-Za-z_][A-Za-z0-9_]*")?\s*$""",
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

    Phase 126 converged 7 inline heredocs (claim-task x2, document-work x1,
    review-close x2, auto-build x2). New ones may be added, never fewer.
    """
    assert len(ALL_HEREDOCS) >= 7, (
        f"expected >=7 python3 heredocs across skills, found {len(ALL_HEREDOCS)} "
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
            if BOOTSTRAP_LINE not in body:
                offenders.append(f"{rel}:{ln}")
    assert not offenders, (
        "yaml-importing heredocs missing the venv bootstrap "
        f"`{BOOTSTRAP_LINE}`: {offenders}"
    )


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
    """
    vt = REPO_ROOT / "core" / "companion" / "scripts" / "validate_tasks.py"
    assert BOOTSTRAP_LINE in vt.read_text(encoding="utf-8"), (
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
