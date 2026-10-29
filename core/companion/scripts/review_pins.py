#!/usr/bin/env python3
"""review_pins.py — `/review-close` Step 2b's baselines, pinned checkouts and post-spawn check.

    python3 sysop/scripts/review_pins.py clear-conventions
    python3 sysop/scripts/review_pins.py baseline
    python3 sysop/scripts/review_pins.py add "<revision>"
    python3 sysop/scripts/review_pins.py clean
    python3 sysop/scripts/review_pins.py check
    python3 sysop/scripts/review_pins.py restore-hooks-path

Run from the main checkout's top level. Under `dontAsk` the step's own shell was denied line by
line: `rm -f`, a `>` redirect (even with an `Edit` rule on its target), `mktemp -d` in the system
temp directory, `PIN=$(…)`, `case`, `| while read` and `diff <(…)` (Phase 421's probes). These
are those commands, as one each.

`clear-conventions` removes `sysop/runtime/2b-conventions.md` before a close writes its own copy,
so a close that skips the write cannot hand every agent the previous close's conventions; it
prints `CLEARED:` or `ABSENT:`. `baseline` writes `sysop/runtime/2b-baseline.txt` (`git status --porcelain -uall`) and
`sysop/runtime/2b-config-baseline.txt` (`git config --local --list`, sorted), replacing any
earlier copy: both are removed first, then both read, then both written, so a capture that
fails leaves no file to diff against. The tree baseline leaves out the two files and
`2b-conventions.md`, which the step writes after it. `add` resolves `<revision>` to a commit
(`refs/heads/<branch>` for a branch target, `HEAD` for the unpushed-main group), makes a detached
checkout of it at `sysop/runtime/pins/<id>` and an empty directory at
`sysop/runtime/scratch/<id>`, and prints `PIN=<sha> PINNED=<path> SCRATCH=<path>`, both paths
absolute. It refuses unless git ignores both paths: an unignored pin is an untracked directory in
the tree the baseline is compared against. `clean` removes every checkout under
`sysop/runtime/pins/` and its scratch directory, never with `--force`: a checkout that refuses
because it is dirty is reported `DIRTY: <path>` and kept, since a reviewer wrote to the tree its
siblings read, and one whose HEAD is no longer the commit it was pinned at is reported
`MOVED: <path> (…)` and kept, since a commit made there would go with it. The tree baseline
records the primary's HEAD and branch tips beside its status, so a commit or checkout there
shows in `check`'s diff. `check` is the five post-spawn assertions, each printing its clean line alone
(`no agent worktrees`, `no agent branches`, `primary tree unchanged by 2b`,
`local config unchanged by 2b`, `no pinned checkouts`) or what it found. `restore-hooks-path`
puts back a `core.hooksPath` the harness rewrote: spawning with `isolation: "worktree"` turns a
relative value absolute in the shared `--local` config and never restores it. It sets the value
the config baseline recorded and prints `RESTORED: core.hooksPath <value> (was <value>)`, or
`UNCHANGED: …` when there is nothing to put back; a value the baseline did not record is reported
and left alone, since the harness only rewrites one that exists.

Exit: 0 done (`check`: all five clean); 1 `clean` kept a dirty or moved checkout, `check` found
something, or `restore-hooks-path` found a value the baseline does not have; 2 `STOP: …` usage,
a refused path, a missing baseline, or a git command that failed.
"""
from __future__ import annotations

import difflib
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

SUBCOMMANDS = ('clear-conventions', 'baseline', 'add', 'clean', 'check', 'restore-hooks-path')
RUNTIME = Path('sysop/runtime')
PINS = RUNTIME / 'pins'
SCRATCH = RUNTIME / 'scratch'
TREE_BASELINE = RUNTIME / '2b-baseline.txt'
CONFIG_BASELINE = RUNTIME / '2b-config-baseline.txt'
CONVENTIONS = RUNTIME / '2b-conventions.md'
_ENV = {k: v for k, v in os.environ.items()
        if k not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE')}


def stop(line: str) -> NoReturn:
    print('STOP: ' + line)
    sys.exit(2)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(['git', *args], capture_output=True, env=_ENV)
    except OSError as e:
        stop(f'git could not run: {e}')
    if check and r.returncode != 0:
        err = os.fsdecode(r.stderr).strip().splitlines()
        stop(f'git {" ".join(args[:2])} failed: {err[-1] if err else "exit " + str(r.returncode)}')
    return r


def text(r: subprocess.CompletedProcess) -> str:
    return os.fsdecode(r.stdout)


def tree_now() -> str:
    """The primary's status, and where its HEAD and branches point: a reviewer's commit,
    checkout or reset on a clean tree changes no status line (Phase 421's round, lens A; the
    Phase 153 class). Agent branches are left to their own assertion."""
    head = git('symbolic-ref', '-q', 'HEAD', check=False)
    refs = [line for line in text(git('for-each-ref', '--format=%(refname) %(objectname)',
                                      'refs/heads/')).splitlines()
            if not line.startswith('refs/heads/worktree-agent-')]
    # This script's own files and the step's conventions copy are written after the baseline is
    # read, so they would show as an agent's whenever `sysop/runtime/` is not ignored as a whole.
    own = {str(TREE_BASELINE), str(CONFIG_BASELINE), str(CONVENTIONS)}
    status = ''.join(line for line in text(git('status', '--porcelain', '-uall')).splitlines(keepends=True)
                     if line[3:].rstrip('\n') not in own)
    return (status
            + f'# HEAD {text(head).strip() or "(detached)"} {text(git("rev-parse", "HEAD")).strip()}\n'
            + ''.join(f'# {line}\n' for line in refs))


def config_now() -> str:
    # `git config --local --list` exits 1 on a repository with no local config at all.
    r = git('config', '--local', '--list', check=False)
    if r.returncode not in (0, 1):
        stop('git config --local --list failed')
    return ''.join(sorted(text(r).splitlines(keepends=True)))


def worktree_paths() -> list[str]:
    out = text(git('worktree', 'list', '--porcelain', '-z'))
    return [f[len('worktree '):] for f in out.split('\0') if f.startswith('worktree ')]


def under(path: str, root: Path) -> bool:
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
        return True
    except ValueError:
        return False


def ignored(path: Path) -> bool:
    r = git('check-ignore', '-q', '--', str(path), check=False)
    if r.returncode not in (0, 1):
        stop(f'git check-ignore failed on {path}')
    return r.returncode == 0


def cmd_clear_conventions() -> None:
    try:
        CONVENTIONS.unlink()
        print(f'CLEARED: {CONVENTIONS}')
    except FileNotFoundError:
        print(f'ABSENT: {CONVENTIONS}')
    except OSError as e:
        stop(f'cannot remove {CONVENTIONS}: {e}')


def cmd_baseline() -> None:
    for old in (TREE_BASELINE, CONFIG_BASELINE):
        try:
            old.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            stop(f'cannot remove {old}: {e}')
    tree, config = tree_now(), config_now()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    TREE_BASELINE.write_text(tree, encoding='utf-8')
    CONFIG_BASELINE.write_text(config, encoding='utf-8')
    status = [line for line in tree.splitlines() if not line.startswith('# ')]
    print(f'BASELINE: {len(status)} status line(s), {len(config.splitlines())} config line(s)')


def cmd_add(rev: str) -> None:
    if not rev.strip() or '<' in rev:
        stop(f'revision {rev!r} is empty or not substituted; write it out')
    r = git('rev-parse', '--verify', '-q', rev + '^{commit}', check=False)
    sha = text(r).strip()
    if r.returncode != 0 or not sha:
        stop(f'{rev} did not resolve to a commit; nothing to place a reviewer at')
    pid = f'2b-{sha[:12]}-{secrets.token_hex(3)}'
    pin, scratch = PINS / pid, SCRATCH / pid
    for p in (pin, scratch):
        if not ignored(p):
            stop(f'{p} is not ignored by git; a pin there would show in the tree the baseline '
                 'is compared against. Add sysop/runtime/ to .gitignore')
    PINS.mkdir(parents=True, exist_ok=True)
    git('worktree', 'add', '-q', '--detach', str(pin), sha)
    scratch.mkdir(parents=True)
    print(f'PIN={sha} PINNED={pin.resolve()} SCRATCH={scratch.resolve()}')


def cmd_clean() -> None:
    kept, removed = [], 0
    for path in worktree_paths():
        if not under(path, PINS):
            continue
        # A reviewer that moved its pin's HEAD (a checkout, a commit) leaves a clean tree, which
        # `worktree remove` takes, and the commit with it. The pin's name carries its commit.
        want = Path(path).name.split('-')[1] if Path(path).name.startswith('2b-') else ''
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, env=_ENV, cwd=path)
        head = text(r).strip()
        if r.returncode != 0 or not want or not head.startswith(want):
            kept.append(path)
            print(f'MOVED: {path} (HEAD {head or "unreadable"}, pinned {want or "unknown"})')
            continue
        r = git('worktree', 'remove', path, check=False)
        if r.returncode != 0:
            kept.append(path)
            print(f'DIRTY: {path}')
            continue
        removed += 1
        shutil.rmtree(SCRATCH / Path(path).name, ignore_errors=True)
    print(f'REMOVED: {removed} pinned checkout(s)')
    sys.exit(1 if kept else 0)


def cmd_check() -> None:
    found = False
    paths = worktree_paths()

    agents = [p for p in paths if '/.claude/worktrees/' in p.replace(os.sep, '/')]
    print('\n'.join(agents) if agents else 'no agent worktrees')
    branches = [b for b in text(git('for-each-ref', '--format=%(refname:lstrip=2)', 'refs/heads/')).splitlines()
                if b.startswith('worktree-agent-')]
    print('\n'.join(branches) if branches else 'no agent branches')
    found |= bool(agents or branches)

    for label, base, now in (('primary tree unchanged by 2b', TREE_BASELINE, tree_now()),
                             ('local config unchanged by 2b', CONFIG_BASELINE, config_now())):
        if not base.is_file():
            print(f'MISSING BASELINE: {base} (run baseline before the first spawn)')
            found = True
            continue
        try:
            then = base.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            print(f'UNREADABLE BASELINE: {base}: {e}')
            found = True
            continue
        diff = list(difflib.unified_diff(then.splitlines(), now.splitlines(), str(base), 'now',
                                         lineterm=''))
        print('\n'.join(diff) if diff else label)
        found |= bool(diff)

    pins = [p for p in paths if under(p, PINS)]
    print('\n'.join(pins) if pins else 'no pinned checkouts')
    found |= bool(pins)
    sys.exit(1 if found else 0)


def hooks_path(config: str) -> str | None:
    for line in config.splitlines():
        if line.startswith('core.hookspath='):      # `--list` lower-cases the key
            return line[len('core.hookspath='):]
    return None


def cmd_restore_hooks_path() -> None:
    try:
        then = hooks_path(CONFIG_BASELINE.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError) as e:
        stop(f'cannot read {CONFIG_BASELINE}: {e}')
    now = hooks_path(config_now())
    if now == then:
        print(f'UNCHANGED: core.hooksPath {then if then is not None else "(unset)"}')
        return
    if then is None:
        print(f'UNCHANGED: core.hooksPath is {now}, which the baseline did not record; left alone')
        sys.exit(1)
    git('config', '--local', 'core.hooksPath', then)
    print(f'RESTORED: core.hooksPath {then} (was {now if now is not None else "(unset)"})')


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in SUBCOMMANDS:
        stop('usage: review_pins.py {' + '|'.join(SUBCOMMANDS) + '} [<revision>]')
    sub, ops = argv[1], argv[2:]
    if len(ops) != (1 if sub == 'add' else 0):
        stop(f'{sub} takes {"one operand" if sub == "add" else "no operand"}')
    # The main checkout, not a linked worktree's top level (lens A): there the baseline would
    # read the wrong tree. Its git dir is the common dir, as `git_check.py primary-checkout` says.
    top = text(git('rev-parse', '--show-toplevel')).strip()
    gd = text(git('rev-parse', '--absolute-git-dir')).strip()
    cd = text(git('rev-parse', '--path-format=absolute', '--git-common-dir')).strip()
    if (not top or os.path.realpath(top) != os.path.realpath('.')
            or os.path.realpath(gd) != os.path.realpath(cd)):
        stop('run this from the main checkout\'s top level')
    {'clear-conventions': cmd_clear_conventions, 'baseline': cmd_baseline, 'clean': cmd_clean,
     'check': cmd_check,
     'restore-hooks-path': cmd_restore_hooks_path}.get(sub, lambda: cmd_add(ops[0]))()


if __name__ == '__main__':
    main(sys.argv)
