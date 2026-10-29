#!/usr/bin/env python3
"""git_check.py — the checks a skill runs before it writes, as one command a seeded rule admits.

    python3 sysop/scripts/git_check.py head-is         "<branch>"
    python3 sysop/scripts/git_check.py head-is-not     "<branch>"
    python3 sysop/scripts/git_check.py head-matches    "<pattern>"
    python3 sysop/scripts/git_check.py primary-checkout
    python3 sysop/scripts/git_check.py ancestor        "<commit>" "<ref>"
    python3 sysop/scripts/git_check.py nothing-staged  "<path>"
    python3 sysop/scripts/git_check.py file            "<path>"
    python3 sysop/scripts/git_check.py lock            "<task id>"
    python3 sysop/scripts/git_check.py fork-has        "<default branch>" "<path>"
    python3 sysop/scripts/git_check.py published       "<branch>"

`_shared/main-push-guard.md` Rule A and the skills' fail-stops used to be
`test "$(git …)" = "<branch>" || { echo …; exit 1; }`. Under `dontAsk` none of that binds a
rule: `test` binds none, and an `exit` or a `{ …; }` group is denied wherever it sits
(`Q-710`, measured). This script is the whole check, so a step chains its write after it with
`&&` and the check and the write stay one call.

Each prints one line. Exit 0 `OK: …` (the check holds), 1 `STOP: …` (it does not: do not
write), 2 `STOP: …` (it could not be measured, or a usage error: do not write), 3 `STOP: …`
(an operand is empty or still holds a `<placeholder>`, or `ancestor` was given a short name).
A branch is compared as `refs/heads/<branch>`, never by its short name (`Q-703`): a tag or
remote ref of the same name cannot pass for it. `ancestor`'s operands are `HEAD`, a full commit
id or a `refs/` name, for the same reason. `lock` (`/review-close` Step 2d) looks for
`sysop/runtime/locks/<task id>.lock` in the main checkout, found through `--git-common-dir` from
anywhere in the repository, and prints that step's own lines instead: `OWED — claimed through
/claim-task` (exit 0) or `CANNOT TELL — no lock on disk` (exit 1). `head-matches` matches the short name of a `refs/heads/` ref with
`fnmatch` (the `merge/review-close-*` pattern); a detached HEAD fails every HEAD check.
`fork-has` (`/review-close` Step 2b, `Q-712`) asks whether `<path>` is committed on the commit an
`isolation: "worktree"` agent's checkout is forked from: `refs/remotes/origin/<default branch>`
(measured, Phase 421), or `refs/heads/<default branch>` where there is no such ref (unmeasured).
A reviewer runs `sysop/scripts/git_ro.py` from that checkout, so until a Sysop update reaches it,
every reviewer's first call fails.
`published` (`/review-close` Step 4a item 1) asks whether `refs/remotes/origin/<branch>` exists:
exit 0 prints its commit id (published), exit 1 `(local-only)`. It replaced a `case` guard and
`git rev-parse --verify --quiet … || echo`, both denied under `dontAsk` (`Q-665`), and like them
it exits 3 on an unsubstituted name, which would otherwise read as local-only.
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
from typing import NoReturn

SUBCOMMANDS = ('head-is', 'head-is-not', 'head-matches', 'primary-checkout', 'ancestor',
                'nothing-staged', 'file', 'lock', 'fork-has', 'published')
_ARITY = {'head-is': 1, 'head-is-not': 1, 'head-matches': 1, 'primary-checkout': 0,
          'ancestor': 2, 'nothing-staged': 1, 'file': 1, 'lock': 1, 'fork-has': 2,
          'published': 1}


def say(code: int, line: str) -> NoReturn:
    print(line)
    sys.exit(code)


def git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(['git', *args], capture_output=True)
    except OSError as e:
        say(2, f'STOP: git could not run: {e}')
    return r.returncode, os.fsdecode(r.stdout).strip()


def head_ref() -> str:
    """HEAD's full ref name, or "" when HEAD is detached."""
    rc, out = git('symbolic-ref', '-q', 'HEAD')
    if rc == 1:
        return ''
    if rc != 0:
        say(2, 'STOP: git symbolic-ref HEAD failed; the branch could not be read')
    return out


def qualified(branch: str) -> str:
    return branch if branch.startswith('refs/heads/') else 'refs/heads/' + branch


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in SUBCOMMANDS:
        say(2, 'STOP: usage: git_check.py {' + '|'.join(SUBCOMMANDS) + '} <operands>')
    sub, ops = argv[1], argv[2:]
    if len(ops) != _ARITY[sub]:
        say(2, f'STOP: {sub} takes {_ARITY[sub]} operand(s), got {len(ops)}')
    for op in ops:
        if not op.strip() or '<' in op:
            say(3, f'STOP: operand {op!r} is empty or not substituted; write it out')

    if sub in ('head-is', 'head-is-not', 'head-matches'):
        ref = head_ref()
        shown = ref or 'detached'
        if sub == 'head-is':
            want = qualified(ops[0])
            if ref == want:
                say(0, f'OK: HEAD is {want}')
            say(1, f'STOP: HEAD is {shown}, not {want} (a concurrent actor may have moved it)')
        if sub == 'head-is-not':
            avoid = qualified(ops[0])
            if ref and ref != avoid:
                say(0, f'OK: HEAD is {ref}, not {avoid}')
            if not ref:
                say(1, f'STOP: HEAD is detached; this step needs a branch other than {avoid}')
            say(1, f'STOP: HEAD is {ref}; this step must not run on {avoid}')
        short = ref[len('refs/heads/'):] if ref.startswith('refs/heads/') else ''
        if short and fnmatch.fnmatchcase(short, ops[0]):
            say(0, f'OK: HEAD is {ref}, which matches {ops[0]}')
        say(1, f'STOP: HEAD is {shown}, which does not match {ops[0]}')

    if sub == 'primary-checkout':
        rc1, gd = git('rev-parse', '--absolute-git-dir')
        rc2, cd = git('rev-parse', '--path-format=absolute', '--git-common-dir')
        if rc1 or rc2 or not gd or not cd:
            say(2, 'STOP: git rev-parse failed; not in a git checkout?')
        if os.path.realpath(gd) == os.path.realpath(cd):
            say(0, 'OK: this is the primary checkout')
        say(1, 'STOP: this is a linked worktree, not the primary checkout')

    if sub == 'ancestor':
        commit, ref = ops
        # Qualified operands only: a short name resolves to whatever shadows it, and a local
        # branch named `origin/main` let an unpushed HEAD pass for pushed (Phase 421's round,
        # lens A; `Q-703`'s other position).
        for name in (commit, ref):
            if not (name == 'HEAD' or name.startswith('refs/')
                    or re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', name)):
                say(3, f'STOP: operand {name!r} is a short name; write HEAD, a full commit id, '
                       'or a refs/ name (refs/heads/…, refs/remotes/origin/…, refs/tags/…)')
        for name in (commit, ref):
            if git('rev-parse', '--verify', '-q', name + '^{commit}')[0] != 0:
                say(2, f'STOP: {name} does not name a commit')
        rc, _ = git('merge-base', '--is-ancestor', commit, ref)
        if rc == 0:
            say(0, f'OK: {commit} is an ancestor of {ref}')
        if rc == 1:
            say(1, f'STOP: {commit} is not an ancestor of {ref}')
        say(2, f'STOP: git merge-base --is-ancestor {commit} {ref} failed (exit {rc})')

    if sub == 'nothing-staged':
        rc, _ = git('diff', '--cached', '--quiet', '--', ops[0])
        if rc == 0:
            say(0, f'OK: nothing is staged at {ops[0]}')
        if rc == 1:
            say(1, f'STOP: {ops[0]} has staged changes')
        say(2, f'STOP: git diff --cached failed (exit {rc})')

    if sub == 'lock':
        rc, common = git('rev-parse', '--path-format=absolute', '--git-common-dir')
        if rc or not common:
            say(2, 'STOP: git rev-parse --git-common-dir failed; not in a git checkout?')
        lock = os.path.join(os.path.dirname(common), 'sysop', 'runtime', 'locks', ops[0] + '.lock')
        if os.path.isfile(lock):
            say(0, 'OWED — claimed through /claim-task')
        say(1, 'CANNOT TELL — no lock on disk')

    if sub == 'fork-has':
        default, path = ops
        remote = 'refs/remotes/origin/' + default
        base = remote if git('rev-parse', '--verify', '-q', remote + '^{commit}')[0] == 0 else qualified(default)
        if git('rev-parse', '--verify', '-q', base + '^{commit}')[0] != 0:
            say(2, f'STOP: {base} does not name a commit')
        rc, _ = git('cat-file', '-e', f'{base}:{path}')
        if rc == 0:
            say(0, f'OK: {path} is on {base}, where an isolated agent\'s checkout is forked')
        say(1, f'STOP: {path} is not on {base}, where an isolated agent\'s checkout is forked; '
               'land the Sysop update there (push it, or merge its PR), then run this step again')

    if sub == 'published':
        remote = 'refs/remotes/origin/' + ops[0]
        rc, out = git('rev-parse', '--verify', '-q', remote + '^{commit}')
        if rc == 0 and out:
            say(0, out)
        if rc == 1:
            say(1, '(local-only)')
        say(2, f'STOP: git rev-parse --verify {remote} failed (exit {rc})')

    if os.path.isfile(ops[0]):
        say(0, f'OK: {ops[0]} is a file')
    say(1, f'STOP: no such file: {ops[0]}')


if __name__ == '__main__':
    main(sys.argv)
