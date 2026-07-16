#!/usr/bin/env python3
"""
PermissionDenied hook (Claude Code 2.1.89+).

Reads the denied tool call from stdin, matches against known
"classifier-overrides-allow-rule" patterns that Sysop's /review-close
hits during a normal cycle, and emits `additionalContext` guidance telling
the model the exact `!`-escape command the human user should type at the
next prompt.

Background. The auto-mode classifier hard-codes destructive-flag protection
(`--delete`, `--force`) and protected-branch policy (push/commit on `main`)
and overrides user-supplied allow-rules in `.claude/settings.json` for those
operations. `AskUserQuestion` does not satisfy the classifier (see
WORKFLOW.md § 8.2a). The only unblocks are (a) a pre-laid allow-rule the
classifier honors, or (b) the human user typing `! <command>` at the prompt
— the `!`-prefix shell-escapes the classifier entirely.

This hook can NOT bypass the classifier itself (returning `retry: true`
just re-hits the same deny). What it CAN do is inject `additionalContext`
into the model's view of the denial, so the model knows immediately what
to relay to the user rather than having to remember Phase 30's skill prose.

Unmatched denials produce no output — the denial stands silently, exactly
as before Phase 36. The hook only fires on patterns we are confident the
user has authorized via `permissions.allow` AND we know the classifier
overrides anyway.

See WORKFLOW.md § 8.2a (Phase 36) for the design rationale.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


PROTECTED_BRANCHES = ("main", "master")
VENV_PREFIX = "PATH=.venv/bin:$PATH "


def _main_repo_root(cwd: str) -> str:
    """Resolve the main repo root (handles worktrees via git-common-dir)."""
    try:
        cp = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return cwd
    if cp.returncode != 0:
        return cwd
    gcd = cp.stdout.strip()
    if not gcd:
        return cwd
    if not os.path.isabs(gcd):
        gcd = os.path.realpath(os.path.join(cwd, gcd))
    if os.path.basename(gcd) == ".git":
        return os.path.dirname(gcd)
    return gcd


def _has_venv(cwd: str) -> bool:
    root = _main_repo_root(cwd)
    return os.path.isdir(os.path.join(root, ".venv"))


def _current_branch(cwd: str) -> str:
    try:
        cp = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return cp.stdout.strip() if cp.returncode == 0 else ""


def _emit(context: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionDenied",
            "additionalContext": context,
        }
    }
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _strip_cd_prefix(command: str) -> str:
    """Drop leading `cd <path> && ` or `cd <path>; ` skill-generated prefixes.

    Quoted-path caveat — the regex uses ``\\S+`` for the path so a path
    containing spaces (``cd "path with spaces" && ...``) won't match and
    the unstripped command falls through to the matchers downstream.
    Skill-generated prefixes today always pass an absolute path under
    a worktree directory (no spaces in any current BeanRider worktree
    path), so this is forward-looking. macOS user paths CAN contain
    spaces; if a skill ever generates one, swap this regex for a
    ``shlex.split`` first-token check.
    """
    return re.sub(r'^\s*cd\s+\S+\s*(?:&&|;)\s*', '', command).strip()


def _match_protected_push(stripped: str, cwd: str) -> str | None:
    m = re.match(r'^git\s+push\s+(?:-u\s+)?origin\s+(main|master)\b(.*)$', stripped)
    if not m:
        return None
    branch = m.group(1)
    tail = m.group(2).strip()
    suffix = f" {tail}" if tail else ""
    venv_hint = ""
    if _has_venv(cwd):
        venv_hint = (
            f"\n\nIf the project's pre-push hook depends on `.venv/bin` tools "
            f"(`bean-check`, project linters, `pytest` in a hook), prepend the venv path:\n\n"
            f"  ! {VENV_PREFIX}git push origin {branch}{suffix}"
        )
    return (
        f"`git push origin {branch}` was denied by the auto-mode classifier's "
        f"protected-branch policy. The classifier overrides the "
        f"`Bash(git push origin:*)` allow-rule on pushes to `main`/`master`; "
        f"the model cannot bypass this directly — only the human user can.\n\n"
        f"Ask the user to type the following at the next prompt (the `!`-prefix "
        f"shell-escapes the classifier):\n\n"
        f"  ! git push origin {branch}{suffix}\n\n"
        f"Do NOT use `AskUserQuestion` — empirically the classifier does not honor "
        f"its answer for protected-branch pushes (see WORKFLOW.md § 8.2a)."
        f"{venv_hint}"
    )


def _match_destructive_push(stripped: str, cwd: str) -> str | None:
    m = re.match(r'^git\s+push\s+origin\s+--delete\s+(\S+)(.*)$', stripped)
    if not m:
        return None
    branch = m.group(1)
    tail = m.group(2).strip()
    suffix = f" {tail}" if tail else ""
    venv_hint = ""
    if _has_venv(cwd):
        venv_hint = (
            f"\n\nIf the project's pre-push hook depends on `.venv/bin` tools, "
            f"prepend the venv path:\n\n"
            f"  ! {VENV_PREFIX}git push origin --delete {branch}{suffix}"
        )
    return (
        f"`git push origin --delete {branch}` was denied by the auto-mode classifier's "
        f"destructive-flag protection. The classifier overrides the "
        f"`Bash(git push origin:*)` allow-rule on `--delete` and `--force` regardless "
        f"of glob; the model cannot bypass this directly — only the human user can.\n\n"
        f"Ask the user to type the following at the next prompt:\n\n"
        f"  ! git push origin --delete {branch}{suffix}\n\n"
        f"The subsequent `git branch -d {branch}` runs in-band without classifier "
        f"interference (local-only operation, no remote contact). Do NOT use "
        f"`AskUserQuestion`."
        f"{venv_hint}"
    )


def _match_protected_commit(stripped: str, cwd: str) -> str | None:
    if not re.match(r'^git\s+commit\b', stripped):
        return None
    branch = _current_branch(cwd)
    if branch not in PROTECTED_BRANCHES:
        return None
    return (
        f"`git commit` on `{branch}` was denied by the auto-mode classifier — "
        f"empirically the classifier extends protected-branch policy upstream from "
        f"the push to its enabling commit when context implies an imminent push "
        f"(e.g., `/review-close` Step 4c's consolidation commit). The model cannot "
        f"bypass this directly — only the human user can.\n\n"
        f"Ask the user to retype the commit at the next prompt with `!`-prefix. "
        f"Use multiple `-m` flags rather than a heredoc — `$(cat <<'EOF' … EOF)` "
        f"breaks zsh quote-tracking when typed as a one-line `!`-escape:\n\n"
        f"  ! {stripped}\n\n"
        f"If the original command used a heredoc, rewrite it as sequential "
        f"`-m \"<paragraph>\"` flags — each `-m` becomes its own paragraph in the "
        f"commit message. Do NOT use `AskUserQuestion`."
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not command:
        return 0

    cwd = data.get("cwd") or os.getcwd()
    stripped = _strip_cd_prefix(command)

    for matcher in (_match_protected_push, _match_destructive_push, _match_protected_commit):
        context = matcher(stripped, cwd)
        if context is not None:
            _emit(context)
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
