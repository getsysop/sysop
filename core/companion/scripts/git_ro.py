#!/usr/bin/env python3
"""git_ro.py — read-only git in another worktree of this repository, as one command a rule admits.

    python3 sysop/scripts/git_ro.py "<worktree>" <git subcommand> [<argument> ...]

Under `dontAsk`, `git -C <path>` is denied at every path, `git -C .` included, and so are
`cd <path> && git …` and `git --git-dir=…` (Phase 421's probes). A Step 2b reviewer reads its
pinned checkout, and Step 1a reads each claim worktree, through this instead; the seeded
`Bash(python3 sysop/scripts/git_ro.py:*)` admits it.

`<worktree>` must be a worktree `git worktree list` names for the repository this runs in, the
primary checkout included. The subcommand must be one of `READ_ONLY` below, and comes first,
so nothing after it is read as one of git's global options (there `-C` and `-c` are copy
detection and a combined diff, and are allowed). Refused anywhere in the arguments, because
each makes a read-only subcommand write a file, run a program or read a file outside the
repository, or names a global option out of place: `REFUSED` for every subcommand
(`--output`, `--ext-diff`, `--textconv`, `--filters`, `--no-index`, `--pathspec-from-file`, …) and
`REFUSED_BY` for one (`grep`'s pager `-O` and pattern file `-f`, `blame`'s `--contents` and `-S`,
`ls-files`' `--exclude-from`, `describe`'s `--dirty`, which refreshes the index). A long option is
refused in any abbreviation too, since git's option parser takes a unique prefix (`grep
--open-files-in-pag=<program>` ran the program): git is told to refuse abbreviations as well, and
this refuses them itself where git ignores that. A short option is refused wherever it sits in a
cluster (`-nO<program>` is `-n -O<program>`). Runs `git --no-pager` in the worktree with
optional locks off and the pager, editor and external diff unset, so `status` writes nothing.
`diff` refreshes the index's stat cache whatever the lock setting (measured: the index changes
after a bare `git diff` of a touched file, with `GIT_OPTIONAL_LOCKS=0`), so it reads a private
copy of the index instead, and the worktree's own index is not written either. The copy keeps
the index's mtime: a fresh one hides a same-size edit made in the second the index was written.

Config can name a program for a read to run, and needs no argument to do it (`Q-726`, measured
on git 2.50.1): `core.fsmonitor` under `status`, `diff`, `diff-tree`, `blame`, `grep` and
`ls-files`; a filter's `clean` wherever the worktree is compared; `diff.external` and a diff
driver's `command` under `diff`; a driver's `textconv` under `diff`, `log -p`, `show`, `blame`
and `status -v`, whose `cachetextconv` writes a `refs/notes/textconv/` ref; `gpg.program` under
`log` when `log.showSignature` is set. So `NO_HELPERS` puts `--no-ext-diff`/`--no-textconv` ahead of the
caller's arguments, `status -v` is refused (status takes neither flag), and `GIT_CONFIG_COUNT`
sets the rest off at command scope: the monitor, each filter driver config names, and every
signature program. A submodule's own config is not read, so `status` and `diff` get
`--ignore-submodules=dirty` (git then runs no `status` inside one), `diff.submodule` is `short`,
and `--submodule` and `--ignore-submodules` are refused. `GIT_NO_LAZY_FETCH` keeps a partial
clone from fetching a missing object, which would run the transport's programs and write; such a
read fails instead. An empty value is not off for a diff driver or `diff.external` (git runs
`""` and dies), which is why those take the flags; an empty gpg program runs nothing and prints
`error: cannot run`. With clean filters off, a worktree file under one (LFS) is compared
unfiltered, so one whose stat is stale can read as modified; a diff of two commits is unaffected.
A submodule's own uncommitted changes are not reported either.

Exit: git's own exit code; 2 `STOP: …` for a refused worktree, subcommand or argument, or when
the worktree's config cannot be read for its filter drivers.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import NoReturn

READ_ONLY = frozenset((
    'blame', 'cat-file', 'describe', 'diff', 'diff-tree', 'for-each-ref', 'grep', 'log',
    'ls-files', 'ls-tree', 'merge-base', 'name-rev', 'rev-list', 'rev-parse', 'show',
    'show-ref', 'status',
))
#: Exact arguments, and the prefixes of `--opt=value` forms, refused anywhere after the subcommand.
REFUSED = ('--output', '-O', '--open-files-in-pager', '--ext-diff', '--textconv', '--filters', '--exec',
           '--upload-pack', '--receive-pack', '--git-dir', '--work-tree', '--namespace',
           '--exec-path', '--config-env', '--no-index', '--pathspec-from-file', '--submodule',
           '--ignore-submodules')
#: Refused only after the subcommand named: the same letter is harmless elsewhere (`log -S` is
#: the pickaxe, `blame -S` reads a revisions file).
REFUSED_BY = {
    'grep': ('-f', '--file'),
    'blame': ('-S', '--contents', '--ignore-revs-file'),
    'ls-files': ('-X', '--exclude-from', '--exclude-per-directory'),
    'describe': ('--dirty', '--broken'),
    'status': ('-v', '--verbose'),
}
#: Put ahead of the caller's arguments, so no diff helper or textconv filter config names runs.
#: `--ext-diff` and `--textconv` are refused, so nothing after these turns them back on.
NO_HELPERS = {
    'diff': ('--no-ext-diff', '--no-textconv', '--ignore-submodules=dirty'),
    'diff-tree': ('--no-ext-diff', '--no-textconv'),
    'log': ('--no-ext-diff', '--no-textconv'), 'show': ('--no-ext-diff', '--no-textconv'),
    'blame': ('--no-textconv',), 'grep': ('--no-textconv',),
    # A submodule's own config is not read here: `dirty` keeps git from running `status` inside it.
    'status': ('--ignore-submodules=dirty',),
}
#: Set at command scope for every subcommand, with each filter driver's programs (`config_off`).
CONFIG_OFF = (('core.fsmonitor', 'false'), ('diff.submodule', 'short'),
              ('log.showSignature', 'false'), ('gpg.program', ''),
              ('gpg.openpgp.program', ''), ('gpg.ssh.program', ''), ('gpg.x509.program', ''))
#: Whole options that are also a prefix of a refused one, so not abbreviations of it.
NOT_ABBREVIATIONS = frozenset(('--text', '--filter'))
_STRIP = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE', 'GIT_EXTERNAL_DIFF', 'GIT_CONFIG',
          'GIT_PAGER', 'PAGER', 'GIT_EDITOR', 'EDITOR', 'VISUAL', 'GIT_SSH', 'GIT_SSH_COMMAND',
          'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT')


def stop(line: str) -> NoReturn:
    print('STOP: ' + line)
    sys.exit(2)


def refused(arg: str, sub: str = '') -> bool:
    for r in (*REFUSED, *REFUSED_BY.get(sub, ())):
        if arg == r or arg.startswith(r + '='):
            return True
        # A short option anywhere in a cluster: glued to its value (`-Ofoo`) or after other
        # flags (`-nOfoo` is `-n -Ofoo`). It over-refuses a pattern glued to `-e`; nothing needs one.
        if len(r) == 2 and arg.startswith('-') and not arg.startswith('--') and r[1] in arg[1:]:
            return True
        # An abbreviation (`--open-files-in-pag=x`, `--filt`).
        name = arg.split('=', 1)[0]
        if (r.startswith('--') and arg.startswith('--') and len(name) > 2 and r.startswith(name)
                and name not in NOT_ABBREVIATIONS):
            return True
    return False


def worktrees(env: dict) -> list[str]:
    try:
        r = subprocess.run(['git', 'worktree', 'list', '--porcelain', '-z'], capture_output=True,
                           env=env)
    except OSError as e:
        stop(f'git could not run: {e}')
    if r.returncode != 0:
        stop('git worktree list failed; run this from inside the repository')
    out = []
    for field in os.fsdecode(r.stdout).split('\0'):
        if field.startswith('worktree '):
            out.append(os.path.realpath(field[len('worktree '):]))
    return out


def private_index(tree: str, env: dict, tmp: str) -> str:
    """A copy of `tree`'s index in `tmp`, for `diff` to refresh in place of the real one."""
    try:
        r = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-path', 'index'],
                           cwd=tree, env=env, capture_output=True)
    except OSError as e:
        stop(f'git could not run: {e}')
    index = os.fsdecode(r.stdout).strip()
    if r.returncode != 0 or not index:
        stop('git rev-parse --git-path index failed')
    copy = os.path.join(tmp, 'index')
    if os.path.isfile(index):
        # copy2, not copyfile: git rehashes an entry whose mtime is not older than the index's,
        # and a copy dated now made a same-second, same-size edit read as unchanged.
        shutil.copy2(index, copy)
    return copy


def config_off(tree: str, env: dict) -> dict:
    """`CONFIG_OFF` and every configured filter driver's programs, as `GIT_CONFIG_*` variables:
    key and value travel apart, so a driver name holding `=` or `.` needs no escaping."""
    try:
        r = subprocess.run(['git', 'config', '-z', '--name-only', '--get-regexp', r'^filter\.'],
                           cwd=tree, env=env, capture_output=True)
    except OSError as e:
        stop(f'git could not run: {e}')
    if r.returncode not in (0, 1):  # 1: no filter configured
        stop('git config --get-regexp failed; the filter drivers could not be read')
    pairs = list(CONFIG_OFF)
    drivers = set()
    for key in os.fsdecode(r.stdout).split('\0'):
        driver = key.partition('.')[2].rpartition('.')[0]  # filter.<driver>.<variable>
        if driver and driver not in drivers:
            drivers.add(driver)
            pairs += [(f'filter.{driver}.{v}', '') for v in ('clean', 'smudge', 'process')]
            pairs.append((f'filter.{driver}.required', 'false'))
    out = {'GIT_CONFIG_COUNT': str(len(pairs))}
    for i, (k, v) in enumerate(pairs):
        out[f'GIT_CONFIG_KEY_{i}'], out[f'GIT_CONFIG_VALUE_{i}'] = k, v
    return out


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        stop('usage: git_ro.py "<worktree>" <git subcommand> [<argument> ...]')
    tree, sub, args = argv[1], argv[2], argv[3:]
    if not tree.strip() or '<' in tree:
        stop(f'worktree {tree!r} is empty or not substituted; write it out')
    if sub not in READ_ONLY:
        stop(f'{sub!r} is not one of the read-only subcommands: {" ".join(sorted(READ_ONLY))}')
    bad = [a for a in args if refused(a, sub)]
    if bad:
        stop(f'refused argument(s): {" ".join(bad)}')
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_PAGER='cat', PAGER='cat', GIT_TERMINAL_PROMPT='0',
               GIT_TEST_DISALLOW_ABBREVIATED_OPTIONS='true', GIT_NO_LAZY_FETCH='1')
    real = os.path.realpath(tree)
    if real not in worktrees(env):
        stop(f'{tree} is not a worktree of this repository (git worktree list)')
    env.update(config_off(real, env))
    with tempfile.TemporaryDirectory(prefix='git-ro-') as tmp:
        if sub == 'diff':
            env['GIT_INDEX_FILE'] = private_index(real, env, tmp)
        try:
            r = subprocess.run(['git', '--no-pager', sub, *NO_HELPERS.get(sub, ()), *args],
                               cwd=real, env=env)
        except OSError as e:
            stop(f'git could not run: {e}')
    sys.exit(r.returncode)


if __name__ == '__main__':
    main(sys.argv)
