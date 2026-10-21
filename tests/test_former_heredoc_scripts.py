"""The heredocs that became shipped scripts — Phases 386 and 387, `Q-409` P3 and `Q-665`'s length wall.

Phase 386 moved eight always-run heredoc bodies in four skills, verbatim, into six scripts
under `core/companion/scripts/`. Claude Code denies a Bash command over about 10,000
characters under `dontAsk` (`Q-665`, measured 9,990 admitted and 10,010 denied), and five of
those bodies were over it. Phase 387 moved review-close's eight remaining Python heredocs,
all under the limit, into seven more, for context. A script leaves one invocation line in
the skill.

This module pins what the move must keep true, and what it changed on purpose:

* each skill still runs its program, by the invocation the step prescribes;
* each script has the seeded allow-rule the invocation binds, and ships in the modes whose
  skills run it — `round_receipt.py` in loop mode too, the close and claim scripts in full
  mode only;
* the programs that share `pending_doc_collect.py` or `feature_branch.py` dispatch on a
  subcommand, and a missing or unknown one is refused before anything runs;
* Step 4c's and Step 2b's runners used to EDIT a literal list inside the heredoc;
  `close_index.py` and `convention_size.py` take the values as arguments and refuse one that
  is not a value before any write or read;
* no executable fence in a shipped skill reaches the length limit again.

The bodies' own behaviour is tested where it always was, by the modules that ran the
heredocs and now run the scripts.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _shipped_scripts import FORMER_HEREDOCS, script  # noqa: E402
from skill_runner_text import runner_texts, text_of  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "core" / "skills"
SETTINGS = REPO_ROOT / "core" / "companion" / ".claude" / "settings.json"
INSTALL = REPO_ROOT / "install.sh"

# (skill, the invocation line its step prescribes, verbatim)
INVOCATIONS = [
    ("review-close", 'python3 sysop/scripts/clone_sync.py "<default branch>" "<apply or dry-run>"'),
    ("review-close", 'python3 sysop/scripts/smoke_detect.py "$SMOKE_WORKTREE_DIRS" "$APPROVED_BRANCHES" '
                     '"<default branch>"'),
    ("review-close", 'python3 sysop/scripts/pending_doc_collect.py collect "<worktree-path>" "<branch name>"'),
    ("review-close", 'python3 sysop/scripts/pending_doc_collect.py rollback "<worktree-path>" "<branch name>"'),
    ("review-close", 'python3 sysop/scripts/close_index.py "<roadmap id>" "<roadmap id>"'),
    ("claim-task", 'python3 sysop/scripts/claim_record.py "<CLAIM_ID>" "<RUN_ID>" "<BODY_PATH>" '
                   "'<TEST_DECISION>'"),
    ("review-close", 'python3 sysop/scripts/feature_branch.py landed "<branch>" "<default branch>"'),
    ("review-close", 'python3 sysop/scripts/feature_branch.py keep-ignored "<workspace>" "<path>" '
                     '"<commit or copy>"'),
    ("review-close", 'python3 sysop/scripts/convention_size.py "Prevention Conventions" "Testing Patterns"'),
    ("review-close", 'python3 sysop/scripts/claim_artifacts.py "<branch 1>" "<branch 2>" '
                     '"<...one argument per branch under review...>"'),
    ("review-close", 'python3 sysop/scripts/workspace_locate.py "<branch name>" "$(git worktree list '
                     '--porcelain)" "${WORKTREE_PREFIX:-$(basename "$(git rev-parse --show-toplevel)")}"'),
    ("review-close", 'python3 sysop/scripts/smoke_record.py "<the doc the KEY line names>" '
                     '"<the KEY\'s 16 hex>" "<confirmed or unrunnable>"'),
    ("review-close", 'python3 sysop/scripts/pr_head_check.py "<branch>" "<merge target>"'),
    ("review-close", 'python3 sysop/scripts/close_check.py'),
    ("codebase-review", 'python3 sysop/scripts/round_receipt.py "<ROUND_MARKER path from Pre-flight>"'),
    ("security-audit", 'python3 sysop/scripts/round_receipt.py "<ROUND_MARKER path from Pre-flight>"'),
]
SCRIPTS = sorted({name for name, _ in FORMER_HEREDOCS})
LOOP_SHIPPED = {"round_receipt.py"}
# A script the skill runs with no arguments is seeded as the exact command, as
# `validate_tasks.py`'s bare form is.
NO_ARGS = {"close_check.py"}

# `Q-665`, Phase 380's round: 9,990 characters admitted, 10,010 denied.
DONTASK_LIMIT = 9_990


@pytest.mark.parametrize("skill,line", INVOCATIONS, ids=[f"{s}:{l.split()[1]}" for s, l in INVOCATIONS])
def test_each_skill_runs_its_program_by_the_prescribed_invocation(skill, line):
    """Exactly once, alone on its line, inside an executable fence: a line in prose, a
    comment, a `text` fence or an HTML comment is not a command (Phase 386's round, lens B)."""
    text = text_of(SKILLS / skill / "SKILL.md")
    live = [ln.strip() for _, body in _executable_fences(text) for ln in body.split("\n")]
    assert live.count(line) == 1, f"{skill}: {live.count(line)} live invocation lines for {line!r}"
    # Reached, too: a line after an `exit` or `return` in its own fence never runs
    # (Phase 387's round, lens B).
    body = next(b for _, b in _executable_fences(text) if line in [ln.strip() for ln in b.split("\n")])
    before = body.split("\n")[:[ln.strip() for ln in body.split("\n")].index(line)]
    assert not _unconditional_exits(before), (skill, line, _unconditional_exits(before))


def _unconditional_exits(lines):
    """`exit`/`return` lines outside any `if`, `case`, loop or brace group: one inside an arm
    runs only on that arm."""
    depth, hits = 0, []
    for ln in lines:
        s = ln.strip()
        if re.match(r"(fi|esac|done|\})\b", s):
            depth -= 1
        if depth == 0 and re.match(r"(exit|return)\b", s):
            hits.append(s)
        if re.match(r"(if|case|for|while|until)\b", s) and not re.search(r"\b(fi|esac|done)\s*$", s) \
                or s.endswith("{"):
            depth += 1
    return hits


def test_the_invocations_cover_every_former_heredoc():
    named = {line.split()[1].split("/")[-1] for _, line in INVOCATIONS}
    assert named == set(SCRIPTS), (named, SCRIPTS)


@pytest.mark.parametrize("name", SCRIPTS)
def test_each_script_has_its_seeded_rule(name):
    allow = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"]
    rule = f"Bash(python3 sysop/scripts/{name})" if name in NO_ARGS else f"Bash(python3 sysop/scripts/{name}:*)"
    assert rule in allow


def _install_list(var: str) -> set[str]:
    m = re.search(rf'^{var}="([^"]*)"', INSTALL.read_text(encoding="utf-8"), re.M)
    assert m, f"install.sh lost {var}"
    return set(m.group(1).split())


@pytest.mark.parametrize("name", SCRIPTS)
def test_each_script_ships_in_the_modes_whose_skills_run_it(name):
    excluded = _install_list("LOOP_EXCLUDE_SCRIPTS")
    if name in LOOP_SHIPPED:
        assert name not in excluded, f"{name}: loop-mode review skills run it, so loop mode ships it"
        assert f'"Bash(python3 sysop/scripts/{name}:*)",' in INSTALL.read_text(encoding="utf-8"), (
            f"{name}: its rule is not in LOOP_ALLOW, so a loop consumer is prompted or denied")
    else:
        assert name in excluded, f"{name}: a lifecycle script must stay out of a loop install"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_a_loop_install_ships_the_receipt_script_and_its_rule(tmp_path):
    """By execution: the lists above are what install.sh reads, not proof it read them."""
    target = tmp_path / "consumer"
    target.mkdir()
    _git(target, "init", "-q")
    _git(target, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "seed")
    r = subprocess.run(["bash", str(INSTALL), str(target), "--mode", "loop", "--packs", "python", "--yes"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    shipped = {p.name for p in (target / "sysop" / "scripts").glob("*.py")}
    assert "round_receipt.py" in shipped
    assert not shipped & (set(SCRIPTS) - LOOP_SHIPPED), shipped & (set(SCRIPTS) - LOOP_SHIPPED)
    allow = json.loads((target / ".claude" / "settings.json").read_text())["permissions"]["allow"]
    assert "Bash(python3 sysop/scripts/round_receipt.py:*)" in allow


# ── the shared script's dispatch ─────────────────────────────────────────────

@pytest.mark.parametrize("argv", [[], ["collect-all", "/x", "b"], ["--collect", "/x", "b"]],
                         ids=["none", "unknown", "option-shaped"])
def test_pending_doc_collect_refuses_a_missing_or_unknown_subcommand(tmp_path, argv):
    r = subprocess.run([sys.executable, str(script("pending_doc_collect.py")), *argv],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "usage:" in r.stderr and "collect|rollback" in r.stderr
    assert r.stdout == "" and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv", [[], ["land", "b", "main"], ["--landed", "b", "main"]],
                         ids=["none", "unknown", "option-shaped"])
def test_feature_branch_refuses_a_missing_or_unknown_subcommand(tmp_path, argv):
    r = subprocess.run([sys.executable, str(script("feature_branch.py")), *argv],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "usage:" in r.stderr and "landed|keep-ignored" in r.stderr
    assert r.stdout == "" and list(tmp_path.iterdir()) == []


def test_a_subcommand_body_keeps_a_comment_at_either_edge(tmp_path, monkeypatch):
    """The helper slices by branch, not by statement: a comment before a branch's first
    statement or after its last is part of the program a test reads."""
    import _shipped_scripts as ss
    (tmp_path / "two.py").write_text(
        "import sys\n_SUBCOMMANDS = ('a', 'b')\n_SUBCOMMAND = sys.argv.pop(1)\n\n"
        "if _SUBCOMMAND == 'a':\n    # FIRST\n    x = 1\n    # LAST\n\n"
        "elif _SUBCOMMAND == 'b':\n    # ONLY\n    y = 2\n    # END\n", encoding="utf-8")
    monkeypatch.setattr(ss, "SCRIPTS", tmp_path)
    assert ss.subcommand_body("two.py", "a") == "# FIRST\nx = 1\n# LAST\n"
    assert ss.subcommand_body("two.py", "b") == "# ONLY\ny = 2\n# END\n"


# ── Step 4c's ids, as arguments ──────────────────────────────────────────────

def _index_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "tasks" / "open").mkdir(parents=True)
    (repo / "tasks" / "open" / "T-1.md").write_text("# T-1\n", encoding="utf-8")
    (repo / "tasks" / "index.yml").write_text(
        "schema_version: 1\ntasks:\n- id: T-1\n  status: in_progress\n  body: open/T-1.md\n",
        encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    return repo


@pytest.mark.parametrize("ids", [
    ["<roadmap id>"], ["T-1", "<roadmap id>"], ["<ROADMAP_ID_1>"], ["-x"], [""], ["T-1", " "],
    ["--keep-locks", "<roadmap id>"], ["T-1", "--keep-locks"], ["<T-1"], ["T-1>"],
], ids=["placeholder", "placeholder-after-a-real-id", "old-literal", "option", "empty", "blank",
        "placeholder-after-the-flag", "flag-not-first", "open-bracket-only", "close-bracket-only"])
def test_close_index_refuses_an_argument_that_is_not_an_id_before_any_write(tmp_path, ids):
    """An unsubstituted `<roadmap id>` used to be looked up and reported NOT_IN_INDEX; now it
    is refused, and nothing is written — no flip, no move, no staging."""
    repo = _index_repo(tmp_path)
    before = (repo / "tasks" / "index.yml").read_bytes()
    r = subprocess.run([sys.executable, str(script("close_index.py")), *ids], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "not a task id" in r.stderr and "nothing was changed" in r.stderr
    assert (repo / "tasks" / "index.yml").read_bytes() == before
    assert (repo / "tasks" / "open" / "T-1.md").exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
    assert status.stdout == "", status.stdout


@pytest.mark.parametrize("argv", [["T-1"], ["--keep-locks", "T-1"]], ids=["plain", "keep-locks"])
def test_close_index_closes_the_ids_it_is_given(tmp_path, argv):
    repo = _index_repo(tmp_path)
    r = subprocess.run([sys.executable, str(script("close_index.py")), *argv], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "CLOSED_IDS: T-1" in r.stdout
    assert ("LOCKS_KEPT:" in r.stdout) is (argv[0] == "--keep-locks")
    assert (repo / "tasks" / "archive" / "T-1.md").exists()


def test_close_index_with_no_ids_closes_nothing_and_succeeds(tmp_path):
    """Step 1c's ROUTE: docs may name no roadmap id; the round-trip then flips nothing."""
    repo = _index_repo(tmp_path)
    before = (repo / "tasks" / "index.yml").read_bytes()
    r = subprocess.run([sys.executable, str(script("close_index.py"))], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "CLOSED_IDS: (none)" in r.stdout
    assert (repo / "tasks" / "index.yml").read_bytes() == before


# ── the length limit ─────────────────────────────────────────────────────────

# The info string may follow spaces (CommonMark), and `zsh` is a shell too (Phase 386's round).
_FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})[ \t]*(\S*)")
_SHELLS = ("bash", "sh", "shell", "zsh")


def _executable_fences(text: str):
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        ind, fence, lang = m.groups()
        j = i + 1
        while j < len(lines) and not re.match(
                r"^[ \t]*" + re.escape(fence[0]) + "{%d,}[ \t]*$" % len(fence), lines[j]):
            j += 1
        if lang.lower() in _SHELLS:
            body = "\n".join(l[len(ind):] if l.startswith(ind) else l for l in lines[i + 1:j])
            yield i + 1, body
        i = j + 1


def _skill_texts():
    """(label, runner text) for every shipped skill, core and packs, step files spliced."""
    dirs = [SKILLS, *sorted(REPO_ROOT.glob("packs/*/skills"))]
    return [(f"{d.relative_to(REPO_ROOT)}/{name}", text) for d in dirs
            for name, text in sorted(runner_texts(d).items())]


def test_no_executable_fence_reaches_the_dontask_length_limit():
    """A runner may send a whole fenced block as one command, so the fence is the unit."""
    over = [f"{label}:{ln} ({len(body):,} chars)"
            for label, text in _skill_texts() for ln, body in _executable_fences(text)
            if len(body) >= DONTASK_LIMIT]
    assert not over, (
        "an executable fence a runner sends as one Bash command reaches the length `dontAsk` "
        f"denies (`Q-665`): move its program into a shipped script — {over}")


def test_the_fence_measure_sees_the_largest_blocks():
    """Non-vacuity: the measure must find real fences, and a planted one over the limit."""
    sizes = [len(b) for _, text in _skill_texts() for _, b in _executable_fences(text)]
    assert len(sizes) > 100 and max(sizes) > 5_000, (len(sizes), max(sizes, default=0))
    planted = "x\n```bash\n" + "echo y\n" * 2_000 + "```\n"
    assert [len(b) for _, b in _executable_fences(planted)] == [len("echo y\n" * 2_000) - 1]
    for opener in ("``` bash", "```zsh", "~~~sh"):
        found = list(_executable_fences(f"x\n{opener}\necho y\n{opener[:3]}\n"))
        assert [b for _, b in found] == ["echo y"], opener
    assert list(_executable_fences("x\n```text\necho y\n```\n")) == []


def test_review_close_runs_no_python_heredoc_and_its_preflight_does_not_ask_for_the_rule():
    """Phase 387 moved review-close's last Python heredoc, so its pre-flight stopped requiring
    `Bash(python3 -:*)`. A heredoc added back would need the rule again, and a pre-flight that
    lists it would refuse a consumer who dropped the rule as WORKFLOW.md's breadth note allows."""
    text = text_of(SKILLS / "review-close" / "SKILL.md")
    heredocs = [b[:80] for _, b in _executable_fences(text) if re.search(r"python3?\s+-\s*<<", b)]
    assert heredocs == []
    assert not re.search(r"^\s*- `Bash\(python3 -:\*\)`", text, re.M)


# ── Step 2b's sections, as arguments ────────────────────────────────────────

@pytest.mark.parametrize("argv", [[], ["<section>"], ["Prevention Conventions", ""], [" "],
                                  ["## Testing Patterns"], ["Testing <section> Patterns"]],
                         ids=["none", "placeholder", "empty-after-a-real-one", "blank",
                              "with-its-hashes", "placeholder-inside"])
def test_convention_size_refuses_an_argument_that_is_not_a_section_name(tmp_path, argv):
    """The runner used to edit SECTIONS in the program; a measurement of no section, or of
    an unsubstituted one, would put the paste on the wrong arm, so it is refused before
    CLAUDE.md is read."""
    r = subprocess.run([sys.executable, str(script("convention_size.py")), *argv], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "pass each section's name as one argument" in r.stderr
    assert r.stdout == ""


def test_convention_size_measures_a_heading_that_holds_its_own_hash_or_arrow(tmp_path):
    """The refusal is for a placeholder and a kept `## `, not for the characters: the base
    program measured any heading the runner edited into SECTIONS, and a real CLAUDE.md
    heading can start with `#` or hold `->` (Phase 387's round)."""
    (tmp_path / "CLAUDE.md").write_text(
        "# P\n\n## #1 Rules\n\none\n\n## Frontend -> Backend contracts\n\ntwo\n",
        encoding="utf-8")
    r = subprocess.run([sys.executable, str(script("convention_size.py")), "#1 Rules",
                        "Frontend -> Backend contracts"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = r.stdout.splitlines()
    assert "(absent)" not in r.stdout, r.stdout
    assert rows[0].endswith("## #1 Rules") and rows[1].endswith("## Frontend -> Backend contracts")


def test_convention_size_matches_a_whole_heading_never_a_prefix(tmp_path):
    """A longer heading that starts with the name is another section (Phase 387's round:
    a prefix match passed the suite)."""
    (tmp_path / "CLAUDE.md").write_text("# P\n\n## Testing Patterns (legacy)\n\nold\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(script("convention_size.py")), "Testing Patterns"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[0].strip() == "0  ## Testing Patterns   (absent)"


def test_convention_size_measures_each_section_it_is_given(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# P\n\n## Prevention Conventions\n\nrule\n\n## Data integrity\n\nmore\n",
        encoding="utf-8")
    r = subprocess.run([sys.executable, str(script("convention_size.py")), "Prevention Conventions",
                        "Testing Patterns", "Data integrity"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = r.stdout.splitlines()
    assert rows[0].endswith("## Prevention Conventions") and int(rows[0].split()[0]) > 0
    assert rows[1].strip() == "0  ## Testing Patterns   (absent)"
    assert rows[2].endswith("## Data integrity") and int(rows[2].split()[0]) > 0
    assert int(rows[3].split()[0]) == int(rows[0].split()[0]) + int(rows[2].split()[0])
    assert rows[3].endswith("TOTAL")
