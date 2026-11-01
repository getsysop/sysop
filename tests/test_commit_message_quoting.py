"""`Q-732` (Phase 455, upstream #923): a commit message a skill fills with prose goes in a quoted
heredoc, never in `-m "…"`.

`/auto-fix` and `/auto-judge` substituted `<batch title, lowercase>` — a `review_tasks.md` header a
review agent wrote — into `git commit -m "fix: …"`, and `/auto-fix`'s verify step did the same with
`<what you caught>` and `<short reason>`. Inside double quotes a backtick or `$(…)` is command
substitution, so a title naming a command ran it and a title quoting an identifier lost it. Each
site now passes its message as `git commit -F - <<'MSG'`, where nothing expands.

Measured under `--permission-mode dontAsk` (Claude Code 2.1.312, `--allowedTools
"Bash(git commit:*)"`, PHASE_LOG.md § Phase 455): the heredoc commit is admitted, alone and at
the end of the `add && diff || commit` chain, and its message lands with the backtick and `$(…)`
as text. `_bash_rule_match.binds` still refuses any heredoc; it is a model for guards, and this
module does not ask it.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "core" / "skills"
AUTO_FIX = SKILLS / "auto-fix" / "SKILL.md"
AUTO_JUDGE = SKILLS / "auto-judge" / "SKILL.md"
DELIM = "SYSOP_COMMIT_MSG_EOF"
HEREDOC = f"git commit -F - <<'{DELIM}'"
HOSTILE = "scripts: `touch PWNED` and $(touch PWNED2) in `_sanitize_log`"

# Placeholders a `-m "…"` may carry: counts, ids and names the workflow mints, never prose.
ID_PLACEHOLDERS = {"<N>", "<N1>", "<N2>", "<N3>", "<F>", "<M>", "<K>", "<A>", "<B>", "<count>",
                   "<CLAIM_ID>", "<TASK_ID>"}

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
_ENV.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def _heredoc_blocks(text: str) -> list[str]:
    return [b for b in re.findall(r"```bash\n(.*?)\n```", text, re.S) if HEREDOC in b]


def _commit_block(tmp_path: Path, block: str, message_line: str) -> subprocess.CompletedProcess:
    repo = tmp_path / "wt"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=_ENV)
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    script = block.replace("<WORKTREE_PATH>", str(repo))
    script = re.sub(r"^(?:fix: <batch title, lowercase>|<the message>)$", lambda _m: message_line,
                    script, flags=re.M)
    assert "<" not in script.replace(f"<<'{DELIM}'", ""), script
    return subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
                          env=_ENV, timeout=30)


@pytest.mark.parametrize("skill,count", [(AUTO_FIX, 2), (AUTO_JUDGE, 1)],
                         ids=["auto-fix", "auto-judge"])
def test_each_prose_commit_runs_as_a_quoted_heredoc_and_keeps_the_text(tmp_path, skill, count):
    blocks = _heredoc_blocks(text_of(skill))
    assert len(blocks) == count, blocks
    for i, block in enumerate(blocks):
        d = tmp_path / str(i)
        d.mkdir()
        r = _commit_block(d, block, f"fix: {HOSTILE}")
        assert r.returncode == 0, r.stderr
        subject = subprocess.run(["git", "-C", str(d / "wt"), "log", "-1", "--format=%s"],
                                 capture_output=True, text=True, env=_ENV).stdout.strip()
        assert subject == f"fix: {HOSTILE}", subject
        assert not list(d.rglob("PWNED*")), "a substitution in the message ran"


def test_the_retired_double_quoted_form_runs_the_title(tmp_path):
    """The premise, measured: the retired line ran both substitutions and lost them from the
    subject. If this ever passes without creating the files, the test above proves nothing."""
    old = ('cd <WORKTREE_PATH> && git add -A && git diff --cached --quiet && echo "Nothing to '
           'commit" || git commit -m "fix: <batch title, lowercase>"')
    r = _commit_block(tmp_path, old.replace("<batch title, lowercase>", HOSTILE), "")
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in tmp_path.rglob("PWNED*")) == ["PWNED", "PWNED2"]
    subject = subprocess.run(["git", "-C", str(tmp_path / "wt"), "log", "-1", "--format=%s"],
                             capture_output=True, text=True, env=_ENV).stdout.strip()
    assert "touch" not in subject, subject


_COMMIT_LINE = re.compile(r"\bgit\b(?:\s+-C\s+\S+)?(?:\s+-c\s+\S+)*\s+commit\b")
_MESSAGE_ARG = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*m|--message)(?:=|\s+)([\"'])(.*?)\1")


def _prose_in_messages(text: str) -> list[str]:
    bad = []
    for line in text.splitlines():
        if not _COMMIT_LINE.search(line):
            continue
        for _q, msg in _MESSAGE_ARG.findall(line):
            bad += [f"{ph} in {msg!r}" for ph in re.findall(r"<[^<>]+>", msg)
                    if ph not in ID_PLACEHOLDERS]
    return bad


def test_no_commit_puts_prose_in_a_quoted_message():
    """Every `-m`/`--message` left in the shipped skill tree, `_shared/` and step files included,
    carries only ids and counts (Phase 455's round: `runner_texts` skipped `_shared/`, and the
    first pattern missed `git -C`, `-am`, `--message=`, single quotes and a second `-m`)."""
    bad = [f"{p.relative_to(SKILLS)}: {b}" for p in sorted(SKILLS.rglob("*.md"))
           for b in _prose_in_messages(p.read_text(encoding="utf-8"))]
    assert not bad, bad


@pytest.mark.parametrize("line", [
    'git commit -m "fix: <what you caught>"',
    'git -C <WORKTREE_PATH> commit -m "fix: <batch title, lowercase>"',
    'git commit -am "fix: <batch title, lowercase>"',
    'git commit --message="fix: <short reason>"',
    "git commit -m 'fix: <batch title, lowercase>'",
    'git commit -m "fix: x" -m "<what you caught>"',
    'git commit -q -m "fix: <short reason>"',
])
def test_the_guard_sees_each_message_shape(line):
    assert _prose_in_messages(line), line


def test_the_guard_passes_ids_and_counts():
    assert not _prose_in_messages('git commit -m "docs: close Batch <N1>, <N2>, <N3>"')
    assert not _prose_in_messages('git commit -m "chore: release <CLAIM_ID>"')


def test_a_line_reading_the_old_delimiter_no_longer_ends_the_message(tmp_path):
    """Phase 455's round (F1): with `MSG` as the delimiter, a message line reading `MSG` ended
    the heredoc and the lines after it ran as shell. The delimiter is uppercase, so a batch
    title, which the runner lowercases, cannot contain it."""
    (block,) = [b for b in _heredoc_blocks(text_of(AUTO_FIX)) if "<the message>" in b]
    r = _commit_block(tmp_path, block, "fix: first line\nMSG\ntouch PWNED3")
    assert r.returncode == 0, r.stderr
    assert not list(tmp_path.rglob("PWNED*"))
    body = subprocess.run(["git", "-C", str(tmp_path / "wt"), "log", "-1", "--format=%B"],
                          capture_output=True, text=True, env=_ENV).stdout
    assert "touch PWNED3" in body, body
    assert DELIM.lower() != DELIM


def test_the_verify_steps_messages_name_no_double_quoted_form():
    text = text_of(AUTO_FIX)
    for msg in ("fix(batch-<N>): <what you caught> (opus verify)",
                "revert(batch-<N>): drop TASK-NNN — <short reason> (opus verify)"):
        assert f"the message `{msg}`" in text, msg
        assert f'-m "{msg}"' not in text, msg
