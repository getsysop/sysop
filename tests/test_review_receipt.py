"""Phase 482 (`Q-735`) — a Step 2b reviewer handed a copy by path gives a receipt, and a script checks it.

The write-once arm told its reviewer to read `sysop/runtime/2b-conventions.md` "IN FULL" and
stopped only on a missing or empty file. A consumer's copy outgrew one `Read`, and in four sightings
a reviewer read 30 or 40 lines, only the headings, or one `Read` that failed for size, then
returned `APPROVED`. Wade's rulings (2026-11-09): the receipt is the line count and the last line,
`READ: <N> lines, last: <line>`; a missing or wrong one voids the verdict and stops the close,
reported as `VOID`, never as a violation; a shipped script compares them.

The first half runs `review_pins.py receipt` as a subprocess in a scratch repository. The second
pins the runner text: the prompt's file arm pages and asks for the line, Step 2b step 4 checks it
before it records a verdict for reuse, and the twin, `4a-fix` and the prepare carry it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core" / "companion" / "scripts" / "review_pins.py"
SKILL_DIR = REPO / "core" / "skills" / "review-close"
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
ID = ("-c", "user.email=t@t", "-c", "user.name=t")
COPY = "## Prevention Conventions\n- rule one `x`\n\n## Testing Patterns\n- the last rule, `y`\n"


def g(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    g(r, "init", "-q", "-b", "main")
    g(r, *ID, "commit", "-q", "--allow-empty", "-m", "init")
    (r / "sysop" / "runtime").mkdir(parents=True)
    (r / "sysop/runtime/2b-conventions.md").write_text(COPY)
    return r


def receipt(repo: Path, path: str, body: str | None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "receipt", path], cwd=repo, env=GIT_ENV,
                          input=body, stdin=None if body is not None else subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)


# --- the script ----------------------------------------------------------------------------

def test_a_receipt_that_reached_the_end_passes(repo: Path) -> None:
    conv = str((repo / "sysop/runtime/2b-conventions.md").resolve())
    p = receipt(repo, conv, "READ: 5 lines, last: - the last rule, `y`\n")
    assert (p.returncode, p.stdout.startswith("RECEIPT OK:")) == (0, True), p.stdout


@pytest.mark.parametrize("body, why", [
    ("READ: 2 lines, last: - the last rule, `y`\n", "it says 2 lines"),
    ("READ: 5 lines, last: - rule one `x`\n", "last line is not the copy's"),
    ("READ: 2 lines, last: ## Prevention Conventions\n", "it says 2 lines"),
    ("READ: 5 lines, last: - the last\n", "last line is not the copy's"),   # a prefix of it
    ("READ: 5 lines, last: -\n", "last line is not the copy's"),
    ("READ: 3 lines, last: - the last rule, `y`\n", "it says 3 lines"),     # near, not the end
    ("READ: 4 lines, last: - the last rule, `y`\n", "it says 4 lines"),
    ("READ: 7 lines, last: - the last rule, `y`\n", "it says 7 lines"),
])
def test_a_receipt_that_stopped_early_is_a_mismatch(repo: Path, body: str, why: str) -> None:
    p = receipt(repo, "sysop/runtime/2b-conventions.md", body)
    assert p.returncode == 1 and p.stdout.startswith("MISMATCH:") and why in p.stdout, p.stdout


@pytest.mark.parametrize("body", [None, "", "VERDICT: APPROVED\nNOTES: none\n",
                                  "READ: 5 lines, last: - the last rule, `y`\n" * 2,
                                  "Asked for READ: 5 lines, last: - the last rule, `y`\n"])
def test_no_receipt_or_two_is_a_mismatch(repo: Path, body: str | None) -> None:
    """An agent that gave no line, an empty heredoc, one that gave two, and a line that only
    mentions the form partway through: none is a receipt."""
    p = receipt(repo, "sysop/runtime/2b-conventions.md", body)
    assert p.returncode == 1 and "READ: line" in p.stdout, p.stdout


@pytest.mark.parametrize("line", [
    "READ: 5 lines, last: `- the last rule, `y``",       # set in code by the reviewer
    'READ: 5 lines, last: "- the last rule, `y`"',       # quoted
    "**READ:** 5 lines, last: -  the last   rule, `y`",  # bold label, whitespace runs
    "- READ: 4 lines, last: - the last rule, `y`",       # newline count of a file without one
    "READ: 5 lines; last line: - the last rule, `y`",  # a semicolon, and "last line:"
    "READ: 6 lines, last: - the last rule, `y`",       # `Read`'s blank line after the final newline
    "`READ: 5 lines, last: - the last rule, `y``",     # the whole line set in code
    "**READ:** 5 lines, **last:** - the last rule, `y`",
    "> READ: 5 lines, last: - the last rule, `y`",     # quoted
])
def test_the_forms_a_careful_reviewer_writes_pass(repo: Path, line: str) -> None:
    conv = repo / "sysop/runtime/2b-conventions.md"
    if "4 lines" in line:
        conv.write_text(COPY.rstrip("\n"))
    p = receipt(repo, "sysop/runtime/2b-conventions.md", f"ROUTING:\n{line}\n")
    assert p.returncode == 0, p.stdout


def test_a_copy_ending_in_blank_lines_takes_its_last_non_blank_line_number(repo: Path) -> None:
    (repo / "sysop/runtime/2b-conventions.md").write_text(COPY + "\n\n")
    for n in (5, 7):
        p = receipt(repo, "sysop/runtime/2b-conventions.md", f"READ: {n} lines, last: - the last rule, `y`\n")
        assert p.returncode == 0, (n, p.stdout)


def test_a_thousands_comma_in_the_count_passes(repo: Path) -> None:
    conv = repo / "sysop/runtime/2b-conventions.md"
    conv.write_text("".join(f"- rule {i}\n" for i in range(1, 1202)))
    p = receipt(repo, str(conv), "READ: 1,201 lines, last: - rule 1201\n")
    assert p.returncode == 0, p.stdout
    assert receipt(repo, str(conv), "READ: 1,200 lines, last: - rule 1201\n").returncode == 1


def test_lines_end_at_newline_only_as_read_and_wc_count_them(repo: Path) -> None:
    """`str.splitlines()` also splits at U+2028, a form feed and a lone CR; `Read` does not
    (lens A measured each), so an honest receipt of such a copy was voided."""
    conv = repo / "sysop/runtime/2b-conventions.md"
    conv.write_text("## A\n- one\u2028two\f three\r four\n- LA\x85ST\n", encoding="utf-8")
    p = receipt(repo, str(conv), "READ: 3 lines, last: - LA\x85ST\n")
    assert p.returncode == 0, p.stdout
    conv.write_bytes(b"## A\r\n- crlf last\r\n")
    assert receipt(repo, str(conv), "READ: 2 lines, last: - crlf last\n").returncode == 0


def test_a_non_utf8_locale_reads_and_prints_utf8(repo: Path) -> None:
    conv = repo / "sysop/runtime/2b-conventions.md"
    conv.write_text("## A\n- caf\u00e9 \u2014 \U0001F600\n", encoding="utf-8")
    env = {**GIT_ENV, "LC_ALL": "en_US.ISO8859-1", "PYTHONUTF8": "0", "PYTHONIOENCODING": ""}
    run = lambda line: subprocess.run([sys.executable, str(SCRIPT), "receipt", str(conv)], cwd=repo, env=env,
                                      input=line.encode("utf-8"), capture_output=True, timeout=60)
    ok = run("READ: 2 lines, last: - caf\u00e9 \u2014 \U0001F600\n")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = run("READ: 1 lines, last: ## A\n")
    assert bad.returncode == 1 and "MISMATCH" in bad.stdout.decode("utf-8"), bad.stdout + bad.stderr


def test_the_security_copy_takes_a_receipt(repo: Path) -> None:
    sec = repo / "sysop/runtime/2b-security-0123abcd.md"
    sec.write_text("## `api/**` — Access\n- check auth\n")
    p = receipt(repo, str(sec), "READ: 2 lines, last: - check auth\n")
    assert p.returncode == 0, p.stdout


@pytest.mark.parametrize("rel", ["CLAUDE.md", "sysop/runtime/other.md", "sysop/runtime/sub/2b-conventions.md",
                                 "<the copy's absolute path>", ""])
def test_only_a_copy_step_2b_wrote_takes_a_receipt(repo: Path, rel: str) -> None:
    """A receipt checked against the project's `CLAUDE.md` says nothing about the copy the
    reviewer was handed."""
    target = repo / rel
    if rel and "<" not in rel:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(COPY)
    p = receipt(repo, rel, "READ: 5 lines, last: - the last rule, `y`\n")
    assert p.returncode == 2 and p.stdout.startswith("STOP:"), p.stdout
    if not rel or "<" in rel:
        assert "not substituted" in p.stdout, p.stdout


def test_an_empty_or_missing_copy_stops(repo: Path) -> None:
    conv = repo / "sysop/runtime/2b-conventions.md"
    conv.write_text("\n\n")
    assert receipt(repo, str(conv), "READ: 2 lines, last: \n").returncode == 2
    conv.unlink()
    assert receipt(repo, str(conv), "READ: 5 lines, last: x\n").returncode == 2


# --- the runner text ------------------------------------------------------------------------

def _flat(text: str) -> str:
    return " ".join(text.split())


def _core() -> str:
    return text_of(SKILL_DIR / "SKILL.md")


def _step(name: str) -> str:
    return (SKILL_DIR / "steps" / f"{name}.md").read_text()


def test_the_file_arm_pages_and_asks_for_the_receipt_the_script_reads() -> None:
    core = _core()
    a = core.index("sysop/runtime/2b-conventions.md> IN FULL before reviewing")
    b = core.index("## Instructions", a)
    arm = core[a:b]
    flat = _flat(arm)
    assert "read it in pages" in flat and "at most 100 lines a page" in flat, flat
    template = re.search(r"^\s*(READ: <N> lines, last: <[^>]*>)\s*$", arm, re.M)
    assert template, "the file arm lost its READ: line"
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import review_pins
    finally:
        sys.path.pop(0)
    filled = template.group(1).replace("<N>", "12").replace(
        "<the file's last non-blank line, copied exactly>", "- a rule")
    m = review_pins.RECEIPT_LINE.match(filled)
    assert m and (m.group(1), m.group(2)) == ("12", "- a rule"), (
        "the prompt asks for a line the checker does not read")
    assert "directly above `ROUTING:`" in flat and "is void" in flat
    # The runner fills the arm's own placeholders; these two are the reviewer's (lens A, F7).
    assert "You fill both values; they are left unfilled here on purpose" in flat
    fmt = core[core.index("Return your findings in exactly this format:"):]
    assert fmt.split("\n")[2].strip().startswith("READ: <N> lines, last: <line>"), (
        "the format block must list the READ: line, or a literal reviewer drops it (lens B, F4)")


def test_step_4_checks_each_receipt_before_it_records_a_verdict() -> None:
    """An `APPROVED` with `NOTES: none` is recorded for reuse: a partial read recorded there
    would be inherited by every later close with the same key."""
    flat = _flat(_core())
    check = flat.index('python3 sysop/scripts/review_pins.py receipt "<the copy\'s absolute path>" <<\'SYSOP_RECEIPT_EOF\'')
    record = flat.index("python3 sysop/scripts/gate_verdict.py record convention")
    assert check < record
    rule = flat[check - 600:record]
    assert "the verdict is void" in rule and "record nothing for it" in rule
    assert "`VOID: <target> — <the printed line>`" in rule
    assert "stop as a `VERDICT: BLOCKED` stops" in rule
    assert "unless it was reused or void" in rule
    assert "first check receipts and record the approvals as the two paragraphs below say" in flat, (
        "the BLOCKED path must route through the receipt check too (lens A, F9)")
    assert "that returned a `VERDICT:` line and was handed a copy by path" in rule
    assert "(step 1's conventions file, or the twin's `ARM: file` `COPY:`)" in rule
    assert "**Exit 1 (`MISMATCH:`): the verdict is void.**" in rule
    assert "**Exit 2: stop and show its output, recording nothing**" in rule
    assert "followed by any violations it listed" in rule
    assert "under the same `--prepare` rule" in rule
    assert "BLOCKED" not in rule[rule.index("Exit 1"):rule.index("and stop as")], "a void verdict is reported VOID"


def test_the_twin_fix_recheck_and_prepare_carry_the_receipt() -> None:
    twin = _flat(_step("2b-twin-spawn"))
    assert "for a path, the same paging rule and `READ:` line, verbatim" in twin
    fix = _flat(_step("4a-fix"))
    assert "whose `READ:` line you check with `review_pins.py receipt`" in fix
    assert "a void or unchecked receipt (its exit 1 or 2), or no verdict at all drops the whole commit" in fix
    prep = _flat(_step("prepare-resume"))
    assert "A void verdict (Step 2b step 4's receipt) is handled as a `VERDICT: BLOCKED` is" in prep
    assert "its `VOID:` line written before any violations it listed" in prep
    assert "BLOCKED, void, SKIP and gone branches" in prep


def test_the_spliced_runner_text_reaches_every_receipt_site() -> None:
    """The arms are read only when they fire; the spliced text is what a runner can reach. The
    last three needles are in step files only."""
    flat = _flat(text_of(SKILL_DIR / "SKILL.md"))
    for needle in ("review_pins.py receipt", "READ: <N> lines, last:", "same paging rule and `READ:` line",
                   "whose `READ:` line you check with `review_pins.py receipt`",
                   "A void verdict (Step 2b step 4's receipt)"):
        assert needle in flat, needle
