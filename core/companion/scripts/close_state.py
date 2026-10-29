#!/usr/bin/env python3
"""close_state.py — `/review-close` Step 1's three reads: worktree classes, `review_tasks.md`, archive rotation.

    python3 sysop/scripts/close_state.py worktrees        "<default branch>"
    python3 sysop/scripts/close_state.py review-tasks
    python3 sysop/scripts/close_state.py archive-rotation "<default branch>"
    python3 sysop/scripts/close_state.py strip-links      "<worktree path>"

Run from the main checkout's top level. Each was a loop in the step's own shell until Phase 421
(`Q-665`): `git -C <worktree>`, `| while read`, `case`, `VAR=$(…)` and `|| exit 0` are each
denied under `dontAsk`, and `git -C` at every path, so a claim worktree outside the project
could not be read at all. The skill text is the contract for every line printed.

`worktrees` (Step 1a) prints one line per worktree on a branch, the primary checkout skipped
unless a lock names it as its workspace: `DIRTY    <branch>  (<path>)  — <n> pending changes`,
`AHEAD    <branch>  (<path>)  — <n> commits ahead of main` or
`MERGED   <branch>  (<path>)  — tip matches main (claim-only or already merged)`. A worktree
whose `git status` fails is `DIRTY` with the error as its reason, and so is one git reads as
part of another checkout (its `.git` link gone) and a detached one in the middle of a rebase,
named by the branch it is rebasing; one whose commits cannot be counted is `AHEAD` with the
error. None of these may read as `MERGED`, the class Step 6 removes. Untracked files are listed
whatever `status.showUntrackedFiles` says.
An untracked symlink whose target the main checkout ignores (a `.venv` link) is not a pending
change (BeanRider ISSUE-0043). Commits a recorded PR head holds
(`refs/sysop/merged-pr-heads/*`) are not counted ahead.

`review-tasks` (Step 1b) prints `REVIEW_TASKS: clean`, `REVIEW_TASKS: save (+<a> -<d>)` or
`REVIEW_TASKS: rotation (+<a> -<d>, review_tasks_archive.md dirty)`: a rotation is the sibling
archive dirty or untracked and net deletions in `review_tasks.md` against `HEAD`.

`archive-rotation` (Step 1c) prints `--- Step 1c: archive-rotation pre-check`, then
`checked: <branch>` for every local branch but the default and `worktree-agent-*` ones, and the
three `WARN:` lines for each one cut before `review_tasks_archive.md` changed on the default
branch.

`strip-links` (Step 3b item b) deletes each untracked symlink in a linked worktree `git worktree
list` names whose target the main checkout ignores and lies outside the worktree (Step 1a's
downgrade rule above), and prints `REMOVED LINK: <path>` for each, then
`STRIP-LINKS: <n> removed`. Only the pointer is deleted,
never its target, and any real untracked file is left for the unforced `git worktree remove`
that follows to refuse. It was a `git -C … | while read` loop with a `case` and an `rm -f`, each
denied under `dontAsk` (`Q-665`). The primary checkout, or a path git does not list as a worktree,
is refused, and a link it cannot remove is reported and exits 2.

Exit 0, or 2 `STOP: …` for a usage error or a git command that failed outright.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

SUBCOMMANDS = ('worktrees', 'review-tasks', 'archive-rotation', 'strip-links')
_ENV = {k: v for k, v in os.environ.items()
        if k not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE')}
ARCHIVE_RE = re.compile(r'(^|/)review_tasks_archive\.md$')
SIBLING_RE = re.compile(r'(^\?\? |^ M | M )review_tasks_archive\.md( |$)')


def stop(line: str) -> NoReturn:
    print('STOP: ' + line)
    sys.exit(2)


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(['git', *args], capture_output=True, cwd=cwd, env=_ENV)
    except OSError as e:
        stop(f'git could not run: {e}')


def out(r: subprocess.CompletedProcess) -> str:
    return os.fsdecode(r.stdout)


def must(*args: str) -> str:
    r = git(*args)
    if r.returncode != 0:
        err = os.fsdecode(r.stderr).strip().splitlines()
        stop(f'git {" ".join(args[:2])} failed: {err[-1] if err else "exit " + str(r.returncode)}')
    return out(r)


def operand(value: str) -> str:
    if not value.strip() or '<' in value:
        stop(f'operand {value!r} is empty or not substituted; write it out')
    return value


def main_root() -> str:
    common = must('rev-parse', '--path-format=absolute', '--git-common-dir').strip()
    return os.path.realpath(os.path.join(common, '..'))


def worktree_branches() -> tuple[str, list[tuple[str, str]], list[str]]:
    """The primary checkout's path (git lists it first), (path, branch) for every worktree on a
    branch, and the paths of the detached ones, read from `-z` output so no path is split."""
    primary, rows, detached, path = '', [], [], None
    for field in must('worktree', 'list', '--porcelain', '-z').split('\0'):
        if field.startswith('worktree '):
            path = field[len('worktree '):]
            primary = primary or path
        elif field.startswith('branch refs/heads/') and path is not None:
            rows.append((path, field[len('branch refs/heads/'):]))
        elif field == 'detached' and path is not None and path != primary:
            detached.append(path)
    return primary, rows, detached


def rebasing(wt: str) -> str:
    """The branch a detached worktree is in the middle of rebasing, or ''. Its commits are not
    on the branch yet, and its tree may hold resolved work, so the branch must not be reviewed
    at its pre-rebase tip."""
    gd = git('rev-parse', '--absolute-git-dir', cwd=wt) if os.path.isdir(wt) else None
    if gd is None or gd.returncode != 0:
        return ''
    for d in ('rebase-merge', 'rebase-apply'):
        try:
            name = Path(out(gd).strip(), d, 'head-name').read_text(encoding='utf-8').strip()
        except OSError:
            continue
        except UnicodeDecodeError:
            return '(unreadable rebase head-name)'    # a rebase is in progress all the same
        if name.startswith('refs/heads/'):
            return name[len('refs/heads/'):]
    return ''


def ignored_link(wt: str, entry: str, root: str) -> bool:
    """An untracked symlink whose target the main checkout ignores — tooling, not work."""
    link = os.path.join(wt, entry)
    if not os.path.islink(link):
        return False
    target = os.readlink(link)
    if not os.path.isabs(target):
        here = os.path.join(wt, os.path.dirname(entry))
        there = os.path.normpath(os.path.join(here, os.path.dirname(target)))
        if not (os.path.isdir(here) and os.path.isdir(there)):
            return False          # a broken link is kept: classified dirty, never removed
        target = os.path.join(there, os.path.basename(target))
    return git('check-ignore', '-q', target, cwd=root).returncode == 0


def cmd_worktrees(default: str) -> None:
    # The primary checkout is matched two ways, as the step's loop did until Phase 421. The main
    # root comes from `--git-common-dir`, never `--show-toplevel`, which answers "which worktree
    # am I standing in" (Phase 234, `Q-020`/`Q-307`(b)); `samefile` compares device and inode, so
    # a symlinked or differently cased spelling still matches. `git worktree list` names the main
    # worktree first, the one handle that survives a `--separate-git-dir` checkout, where the
    # common dir's parent is not the checkout at all. Matching by branch name instead (Phase 249,
    # `Q-370`) classified the runner's own vantage `dirty` whenever a feature branch was checked
    # out in the primary. A lock naming the primary as its workspace is `claim_task.sh
    # --branch`'s mode: there the primary IS the paused work this step protects, so it is not
    # skipped (BeanRider ISSUE-0016).
    root = main_root()
    primary, rows, detached = worktree_branches()
    for wt in detached:
        branch = rebasing(wt)
        if branch:
            print(f'DIRTY    {branch}  ({wt})  — a rebase is in progress in this detached worktree')
    claimed = False
    for lock in sorted(Path(root, 'sysop', 'runtime', 'locks').glob('*.lock')):
        try:
            claimed |= f'workspace: {root}' in lock.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeDecodeError):
            claimed = True    # an unreadable lock may name the primary: classify it, never skip it
    for wt, branch in rows:
        if not claimed and (wt == primary or (os.path.exists(wt) and os.path.samefile(wt, root))):
            continue
        # `--untracked-files=normal`: a `status.showUntrackedFiles=no` in any config would hide
        # untracked work, and `git worktree remove` honours the same setting, so nothing after
        # this step would see it either (Phase 421's round, lens A).
        st = git('status', '--porcelain', '--untracked-files=normal', '--ignore-submodules=none',
                 cwd=wt) if os.path.isdir(wt) else None
        if st is None or st.returncode != 0:
            err = os.fsdecode(st.stderr).strip().splitlines()[-1:] if st else ['the directory is missing']
            print(f'DIRTY    {branch}  ({wt})  — git status failed: {err[0] if err else "no output"}')
            continue
        # A worktree whose `.git` link is gone makes git walk up to an enclosing repository and
        # report that one's status instead.
        if not os.path.lexists(os.path.join(wt, '.git')):
            print(f'DIRTY    {branch}  ({wt})  — no .git link, so git reads it as part of another checkout')
            continue
        significant = [line for line in out(st).splitlines() if line
                       and not (line.startswith('?? ') and ignored_link(wt, line[3:], root))]
        log = git('log', '--oneline', f'refs/heads/{default}..refs/heads/{branch}', '--not',
                  '--glob=refs/sysop/merged-pr-heads/*')
        if significant:
            print(f'DIRTY    {branch}  ({wt})  — {len(significant)} pending changes')
        elif log.returncode != 0:
            err = os.fsdecode(log.stderr).strip().splitlines()[-1:]
            print(f'AHEAD    {branch}  ({wt})  — commits could not be counted: {err[0] if err else "git log failed"}')
        elif out(log).strip():
            print(f'AHEAD    {branch}  ({wt})  — {len(out(log).splitlines())} commits ahead of main')
        else:
            print(f'MERGED   {branch}  ({wt})  — tip matches main (claim-only or already merged)')


def numstat(root: str) -> tuple[int, int]:
    r = git('diff', '--numstat', 'HEAD', '--', 'review_tasks.md', cwd=root)
    if r.returncode != 0:
        stop('git diff --numstat failed')
    fields = out(r).split('\t')
    def num(i: int) -> int:
        v = fields[i].strip() if len(fields) > i else ''
        return int(v) if v.isdigit() else 0     # a binary row prints `-`
    return num(0), num(1)


def cmd_review_tasks() -> None:
    # Read at the main checkout's root: the pathspec is relative to the working directory, so
    # from a subdirectory a dirty file read as clean (Phase 421's round, lens A).
    root = main_root()
    st = git('status', '--porcelain', '--untracked-files=normal', '--', 'review_tasks.md', cwd=root)
    whole = git('status', '--porcelain', '--untracked-files=normal', cwd=root)
    if st.returncode != 0 or whole.returncode != 0:
        stop('git status failed at the main checkout')
    if not out(st).strip():
        print('REVIEW_TASKS: clean')
        return
    added, deleted = numstat(root)
    sibling = any(SIBLING_RE.search(line) for line in out(whole).splitlines())
    if sibling and deleted > added:
        print(f'REVIEW_TASKS: rotation (+{added} -{deleted}, review_tasks_archive.md dirty)')
    else:
        print(f'REVIEW_TASKS: save (+{added} -{deleted})')


def cmd_archive_rotation(default: str) -> None:
    print('--- Step 1c: archive-rotation pre-check')
    for branch in must('for-each-ref', '--format=%(refname:lstrip=2)', 'refs/heads/').splitlines():
        if branch == default or branch.startswith('worktree-agent-'):
            continue
        print(f'checked: {branch}')
        mb = git('merge-base', f'refs/heads/{default}', f'refs/heads/{branch}')
        names = git('diff', '--name-only', f'{out(mb).strip()}..refs/heads/{default}', '--')
        if mb.returncode != 0 or names.returncode != 0:
            continue                  # no merge-base: nothing on the default branch to rebase over
        if any(ARCHIVE_RE.search(n) for n in out(names).splitlines()):
            print(f'WARN: {branch} was cut before an archive rotation on main;')
            print("      Step 4a's rebase will likely conflict on review_tasks.md.")
            print('      Resolve per Step 4a guidance, or skip this branch this cycle.')


def cmd_strip_links(wt: str) -> None:
    primary, rows, detached = worktree_branches()
    real = wt = os.path.realpath(wt)    # a relative operand would reach check-ignore as `../…`
    if os.path.realpath(primary) == real:
        stop(f'{wt} is the primary checkout, not a linked worktree')
    if real not in {os.path.realpath(p) for p in [path for path, _ in rows] + detached}:
        stop(f'{wt} is not a worktree git worktree list names')
    r = git('status', '--porcelain', '-z', '--untracked-files=normal', cwd=wt)
    if r.returncode != 0:
        err = os.fsdecode(r.stderr).strip().splitlines()
        stop(f'git status failed in {wt}: {err[-1] if err else "exit " + str(r.returncode)}')
    root, removed, failed = main_root(), 0, []
    for field in out(r).split('\0'):
        if not field.startswith('?? '):
            continue
        entry = field[3:]
        link = os.path.join(wt, entry)
        # A link into the worktree itself is the work, not tooling, even when the primary ignores
        # the directory the worktree sits in (`.claude/worktrees/<x>`).
        target = os.path.realpath(link)
        if os.path.commonpath([target, real]) == real:
            continue
        if ignored_link(wt, entry, root):
            try:
                os.unlink(link)
            except OSError as e:
                failed.append(f'{entry} ({e.__class__.__name__}: {e})')
                continue
            print(f'REMOVED LINK: {entry}')
            removed += 1
    print(f'STRIP-LINKS: {removed} removed')
    if failed:
        stop('could not remove: ' + '; '.join(failed))


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in SUBCOMMANDS:
        stop('usage: close_state.py {' + '|'.join(SUBCOMMANDS) + '} [<default branch> | <worktree path>]')
    sub, ops = argv[1], argv[2:]
    want = 0 if sub == 'review-tasks' else 1
    if len(ops) != want:
        stop(f'{sub} takes {want} operand(s), got {len(ops)}')
    if sub == 'worktrees':
        cmd_worktrees(operand(ops[0]))
    elif sub == 'review-tasks':
        cmd_review_tasks()
    elif sub == 'strip-links':
        cmd_strip_links(operand(ops[0]))
    else:
        cmd_archive_rotation(operand(ops[0]))


if __name__ == '__main__':
    main(sys.argv)
