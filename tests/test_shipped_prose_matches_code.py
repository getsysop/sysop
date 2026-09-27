"""Shipped sentences that quote the code, pinned to the code they quote.

Phase 326 fixed these after a loop-bundle round found them false, and its own round
found none had a guard. Each test reads the fact from the implementation, not from a
copy of the sentence, so a correct rewording stays green and a regression does not.
Round 2 widened two of them: the first cuts matched only the one spelling that had been
fixed, and searched the runner's comments as if they were output.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_PROSE = [REPO_ROOT / "README.md", REPO_ROOT / "CONTRIBUTING.md",
                 *sorted((REPO_ROOT / "core").rglob("*.md")),
                 *sorted((REPO_ROOT / "docs").rglob("*.md")),
                 *sorted((REPO_ROOT / "docs").rglob("*.html")),
                 *sorted((REPO_ROOT / "packs").rglob("*.md"))]
INSTALLER = REPO_ROOT / "install.sh"

# Any `mode` followed by `:` or `=` and a mode value: `mode: loop`, `mode:"loop"`,
# `MODE=full`. The JSON form the installer writes, `"mode": "loop"`, has a quote between
# `mode` and the colon, so it never matches.
YAML_SHAPED_MODE = re.compile(r"(?i)\bmode\b\s*[:=]\s*['\"]?(?:loop|full)\b")
# `Scan mode: Full` is a report field, not the lock. A sentence about the lock names it.
NAMES_THE_LOCK = re.compile(r"(?i)\block\b|sysop\.lock")


def yaml_shaped_lock_lines(lines: list[str]) -> list[int]:
    return [n for n, line in enumerate(lines, 1)
            if YAML_SHAPED_MODE.search(line)
            and NAMES_THE_LOCK.search(line + " " + (lines[n - 2] if n > 1 else ""))]


def installer_messages() -> list[str]:
    """The lines `install.sh` prints, which a consumer reads like any other prose."""
    return [ln for ln in INSTALLER.read_text(encoding="utf-8").splitlines()
            if re.match(r"\s*(?:say|note|echo|warn|printf)\b", ln)]


def test_the_lock_is_described_as_the_json_install_sh_writes() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    # The fact: the lock is written with json.dump and a "mode" key.
    assert re.search(r"""["']mode["']\s*:\s*os\.environ\.get\(\s*["']SYSOP_MODE""", installer)
    assert "json.dump(data, f, indent=2)" in installer
    hits = [f"{p.relative_to(REPO_ROOT)}:{n}"
            for p in SHIPPED_PROSE
            for n in yaml_shaped_lock_lines(p.read_text(encoding="utf-8").splitlines())]
    hits += [f"install.sh message {n}" for n in yaml_shaped_lock_lines(installer_messages())]
    assert not hits, (
        f"shipped text describes the JSON lock in a YAML shape (`mode: loop`): {hits}. A "
        'literal match for that never finds `"mode": "loop"` in `.claude/sysop.lock`.'
    )


def test_the_lock_mode_check_sees_each_yaml_spelling() -> None:
    for bad in ["the lock has `mode: loop`", "the lock records mode: loop",
                "the lock has `mode: \"loop\"`", "the lock has `mode:loop`",
                "`grep -q 'mode: loop' .claude/sysop.lock`", "the lock's MODE=full"]:
        assert yaml_shaped_lock_lines([bad]) == [1], bad
    for good in ['the lock carries `"mode": "loop"`', "Scan mode:   Full / Incremental"]:
        assert yaml_shaped_lock_lines([good]) == [], good


def runner_output_strings(source: str) -> list[str]:
    """String literals the runner passes to `print` or `_record`: what it can actually
    emit. Comments and docstrings are not output, and the first cut of this guard
    searched the raw source, so a phrase only in a docstring passed."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("print", "_record"):
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        out.append(sub.value)
    return out


def test_the_quoted_pip_audit_message_is_one_the_runner_prints() -> None:
    skill = (REPO_ROOT / "core/skills/security-audit/SKILL.md").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "core/companion/scripts/run_checks/pip_audit.py").read_text(
        encoding="utf-8")
    emitted = " ".join(runner_output_strings(runner))
    quoted = re.findall(r"If Step 2b reported `([^`]+)`", skill)
    assert quoted, "security-audit no longer quotes a pip-audit message; re-derive this guard"
    missing = [q for q in quoted if q not in emitted]
    assert not missing, f"security-audit tells the executor to look for {missing}, which pip_audit.py never prints"


def test_the_runner_output_reader_skips_comments_and_docstrings() -> None:
    src = ('"""Skips if pip-audit is missing."""\n'
           '# was: print("pip-audit not available")\n'
           'print("warn: pip-audit not on PATH — skipping")\n')
    emitted = " ".join(runner_output_strings(src))
    assert "pip-audit not on PATH" in emitted
    assert "is missing" not in emitted and "not available" not in emitted


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_adversarial_reviews_phase_326_clauses_hold() -> None:
    """Two shipped clauses of `_shared/adversarial-review.md` that no verbatim pin covered."""
    text = _flat((REPO_ROOT / "core/skills/_shared/adversarial-review.md").read_text(encoding="utf-8"))
    assert ("**Name a private scratch directory in each prompt too**, one you created for that "
            "lens, and keep your own files out of it:") in text
    receipt = text[text.index("## Envelope receipt"):text.index("See `/claim-task` SKILL.md § Step 8")]
    assert "subagent-envelopes/<TASK_ID>[.<phase>].json" in receipt
    assert "`<CLAIM_ID>.plan.json`, `.review.json` and `.exec.json`, never at the bare path" in receipt
    assert "subagent-envelopes/<TASK_ID>.json`" not in receipt
