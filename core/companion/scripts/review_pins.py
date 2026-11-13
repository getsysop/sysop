#!/usr/bin/env python3
"""review_pins.py — `/review-close` Step 2b's baselines, pinned checkouts and post-spawn check.

    python3 sysop/scripts/review_pins.py clear-conventions
    python3 sysop/scripts/review_pins.py receipt "<copy path>"   # the READ: line on stdin
    python3 sysop/scripts/review_pins.py baseline
    python3 sysop/scripts/review_pins.py add "<revision>"
    python3 sysop/scripts/review_pins.py own "<worktree path>"
    python3 sysop/scripts/review_pins.py clean
    python3 sysop/scripts/review_pins.py check
    python3 sysop/scripts/review_pins.py reap "<default branch>"
    python3 sysop/scripts/review_pins.py restore-hooks-path

Run from the main checkout's top level. Under `dontAsk` the step's own shell was denied line by
line: `rm -f`, a `>` redirect (even with an `Edit` rule on its target), `mktemp -d` in the system
temp directory, `PIN=$(…)`, `case`, `| while read` and `diff <(…)` (Phase 421's probes). These
are those commands, as one each.

`clear-conventions` removes `sysop/runtime/2b-conventions.md` before a close writes its own copy,
so a close that skips the write cannot hand every agent the previous close's conventions; it
prints `CLEARED:` or `ABSENT:`. `receipt` checks the line a reviewer handed a copy by path gave
before its verdict, `READ: <N> lines, last: <the copy's last non-blank line>`, read from stdin,
against the copy: `sysop/runtime/2b-conventions.md` or a `2b-security*.md` (`Q-735`). A reviewer
that read 30 lines of a copy, or only a `Read` that failed for size, has not seen its end, which the
receipt asks for. `N` may be
the copy's line count, its newline count, the number of its last non-blank line, or one past a
final newline (Claude Code's `Read` shows a blank line there); the line compares with whitespace runs as one space,
and may sit in one pair of backticks or double quotes; a count may carry thousands commas, and
the whole line may sit in backticks. It prints `RECEIPT OK: <path> (<n> lines)`
or `MISMATCH: <path> — <why>` (exit 1), for no `READ:` line, more than one, or either value
wrong; `/review-close` voids that verdict. Its `STOP:` (exit 2: a path that is not a Step 2b copy,
an empty or missing copy, stdin a terminal) is a check that could not run, and stops the close. `baseline` writes `sysop/runtime/2b-baseline.txt` (`git status --porcelain -uall`) and
`sysop/runtime/2b-config-baseline.txt` (`git config --local --list`, sorted) and
`sysop/runtime/2b-agents-baseline.txt` (every linked worktree with its branch, and every
`worktree-agent-*` tip), replacing any earlier copy and `own`'s list: all are removed first, then
read, then written, so a capture that fails leaves no file to diff against. The tree baseline
leaves out these files and `2b-conventions.md`, which the step writes after it. `own` records a
worktree path a spawn's result named, in `sysop/runtime/2b-own.txt`, and refuses a path that is not
a linked `agent-*` worktree under `.claude/worktrees/`, or one the agents baseline already had. `add` resolves `<revision>` to a commit
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
shows in `check`'s diff. `check` is the five post-spawn assertions, each printing its clean line
(`no agent worktrees`, `no agent branches`, `primary tree unchanged by 2b`,
`local config unchanged by 2b`, `no pinned checkouts`) or what it found. It removes nothing, and it
sorts what it finds by whose it is. Ours is a `worktree-agent-*` branch, or a worktree whose path
`own` recorded: `LEAK: …`. Anything else new under `.claude/worktrees/` or inside this checkout
(its pins aside), and a branch tip or
`branch.<name>.*` line of a branch another worktree has checked out, is another session's:
`FOREIGN: …`. Both exit 1. After the five come lines that are not findings: `LOCKED: …`, an
agent worktree whose process still holds it, and `PREDATES: …`, one the agents baseline already
had. `reap` removes ours, and only ours: a worktree with no commits ahead of `<default branch>`
and either a clean tree or a path `own` recorded, whose uncommitted files it lists as
`DISCARDING:` first, and then its branch if that is a `worktree-agent-*` branch the agents
baseline did not have (any other branch it holds is kept: an agent can check out a claim's, the
default branch or a peer's); an agent branch with no worktree and no commits ahead.
It never touches a locked worktree (git refuses one without `-f -f`) and keeps anything else as
`KEPT: …`, ending `REAPED: <n> removed, <n> kept`. `restore-hooks-path`
puts back a `core.hooksPath` the harness rewrote: spawning with `isolation: "worktree"` turns a
relative value absolute in the shared `--local` config and never restores it. It sets the value
the config baseline recorded and prints `RESTORED: core.hooksPath <value> (was <value>)`, or
`UNCHANGED: …` when there is nothing to put back; a value the baseline did not record is reported
and left alone, since the harness only rewrites one that exists.

Exit: 0 done (`check`: all five clean); 1 `receipt` printed `MISMATCH:`, `clean` kept a dirty or moved checkout, `check` found
something, `reap` kept something, or `restore-hooks-path` found a value the baseline does not have; 2 `STOP: …` usage,
a refused path, a missing baseline, or a git command that failed.
"""
from __future__ import annotations

import difflib
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

SUBCOMMANDS = ('clear-conventions', 'receipt', 'baseline', 'own', 'add', 'clean', 'check', 'reap',
               'restore-hooks-path')
RUNTIME = Path('sysop/runtime')
PINS = RUNTIME / 'pins'
SCRATCH = RUNTIME / 'scratch'
TREE_BASELINE = RUNTIME / '2b-baseline.txt'
CONFIG_BASELINE = RUNTIME / '2b-config-baseline.txt'
AGENTS_BASELINE = RUNTIME / '2b-agents-baseline.txt'
OWN = RUNTIME / '2b-own.txt'
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
    own = {str(TREE_BASELINE), str(CONFIG_BASELINE), str(AGENTS_BASELINE), str(OWN),
           str(CONVENTIONS)}
    # Unquoted, so a non-ASCII worktree name matches the path `worktree list` gives (round, lens A).
    read = git('-c', 'core.quotePath=false', 'status', '--porcelain', '-uall')
    status = ''.join(line for line in text(read).splitlines(keepends=True)
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
    return [w['path'] for w in worktrees()]


def worktrees() -> list[dict]:
    """Every worktree git lists, primary first: its path, its branch (`None` when detached) and
    its lock (`None`, or the reason, `''` when it gave none)."""
    rows: list[dict] = []
    for field in text(git('worktree', 'list', '--porcelain', '-z')).split('\0'):
        if field.startswith('worktree '):
            rows.append({'path': field[len('worktree '):], 'branch': None, 'locked': None})
        elif rows and field.startswith('branch refs/heads/'):
            rows[-1]['branch'] = field[len('branch refs/heads/'):]
        elif rows and (field == 'locked' or field.startswith('locked ')):
            rows[-1]['locked'] = field[len('locked '):]
    return rows


def agent_dir(path: str) -> bool:
    return '/.claude/worktrees/' in path.replace(os.sep, '/')


def agents_now() -> str:
    """Checks 1 and 2's own baseline: every linked worktree with its branch, and every
    `worktree-agent-*` tip, so one present before the spawn is not this close's leak."""
    rows = [f'worktree {os.path.realpath(w["path"])}\t{w["branch"] or "(detached)"}\n'
            for w in worktrees()[1:]]
    rows += [f'agent-branch {line}\n' for line in text(git(
        'for-each-ref', '--format=%(refname:lstrip=2) %(objectname)', 'refs/heads/')).splitlines()
        if line.startswith('worktree-agent-')]
    return ''.join(rows)


def recorded() -> set[str]:
    """The worktree paths `own` recorded from this close's spawn results."""
    try:
        return {os.path.realpath(p) for p in
                OWN.read_text(encoding='utf-8', errors='surrogateescape').splitlines() if p}
    except FileNotFoundError:
        return set()
    except (OSError, UnicodeDecodeError) as e:
        stop(f'cannot read {OWN}: {e}')


def classify() -> dict:
    """Sort what checks 1 to 4 can see by whose it is. Ours is a `worktree-agent-*` branch or a
    worktree whose path `own` recorded; anything else new is FOREIGN, another session's, and is
    never removed. A worktree or agent branch in the agents baseline predates this close."""
    try:
        base = AGENTS_BASELINE.read_text(encoding='utf-8', errors='surrogateescape').splitlines()
    except FileNotFoundError:
        return {'missing': f'MISSING BASELINE: {AGENTS_BASELINE} (run baseline before the first spawn)'}
    except (OSError, UnicodeDecodeError) as e:
        return {'missing': f'UNREADABLE BASELINE: {AGENTS_BASELINE}: {e}'}
    then_wt = {}
    for line in base:
        if line.startswith('worktree '):
            path, _, branch = line[len('worktree '):].partition('\t')
            then_wt[path] = branch
    # By name: an agent branch the baseline had is not this close's, wherever it points now.
    then_br = {line[len('agent-branch '):].split(' ', 1)[0] for line in base
               if line.startswith('agent-branch ')}
    own = recorded()
    trees = worktrees()
    out = {'missing': None, 'leak': [], 'foreign': [], 'locked': [], 'predates': [],
           'foreign_branches': set(), 'paths': {}, 'held': {}, 'then_wt': then_wt,
           'then_branches': then_br}
    for w in trees[1:]:
        if under(w['path'], PINS):
            continue                    # this close's pins: `clean` and the fifth check's (round 2)
        real, branch = os.path.realpath(w['path']), w['branch']
        ours = real in own or (branch or '').startswith('worktree-agent-')
        if real in then_wt:
            kind = 'predates'
        elif w['locked'] is not None and ours:
            kind = 'locked'
        elif ours:
            kind = 'leak'
        else:
            kind = 'foreign'
        if not ours and branch:
            out['foreign_branches'].add(branch)
        # A worktree inside this checkout shows in its status; one outside it shows only by its
        # branch, below.
        if agent_dir(w['path']) or kind in ('leak', 'locked') or under(w['path'], Path('.')):
            out[kind].append(w)
            out['paths'][real] = kind
            if branch:
                out['held'][branch] = kind
    # A branch another session has checked out moved in that session's worktree, not here; one
    # that was checked out there at the baseline and is gone now was released there.
    out['foreign_branches'] |= {b for p, b in then_wt.items()
                                if p not in own and b != '(detached)'
                                and not b.startswith('worktree-agent-')}
    tips = text(git('for-each-ref', '--format=%(refname:lstrip=2) %(objectname)',
                    'refs/heads/')).splitlines()
    held = {w['branch'] for w in trees[1:] if os.path.realpath(w['path']) in out['paths']}
    names = [t.split(' ', 1)[0] for t in tips]
    out['branches'] = [b for b in names
                       if b.startswith('worktree-agent-') and b not in then_br and b not in held]
    out['predated_branches'] = [b for b in names if b in then_br]
    return out


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


RECEIPT_LINE = re.compile(r'^\s*(?:>\s*)?(?:[-*]\s+)?(?:\*\*)?READ:(?:\*\*)?\s*(\d{1,3}(?:,\d{3})+|\d+)\s+lines?\s*[,;]\s*'
                          r'(?:\*\*)?last(?: line)?:(?:\*\*)?[ \t]?(.*)$')


def _receipt_lines(text: str) -> list[re.Match]:
    """Each line of the reviewer's text that is a receipt. A line set whole in backticks is read
    inside them; a receipt anywhere but a line's start is not one."""
    found = []
    for line in text.split('\n'):
        s = line.strip()
        if len(s) >= 2 and s[0] == s[-1] == '`' and s[1:].lstrip('*').startswith('READ:'):
            s = s[1:-1]
        m = RECEIPT_LINE.match(s)
        if m:
            found.append(m)
    return found


def _same_line(given: str, last: str) -> bool:
    """`given` is the copy's last non-blank line. Whitespace runs compare as one space, and one
    pair of backticks or double quotes around the whole value is allowed: a reviewer that set
    the line in code still copied it."""
    want = ' '.join(last.split())
    got = ' '.join(given.split())
    if got == want:
        return True
    return len(got) >= 2 and got[0] == got[-1] and got[0] in '`"' and ' '.join(got[1:-1].split()) == want


def cmd_receipt(path: str) -> None:
    # The copy and the receipt are UTF-8 whatever the locale, and so is what this prints.
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not path.strip() or '<' in path:
        stop(f'path {path!r} is empty or not substituted; write it out')
    real = Path(os.path.realpath(os.path.expanduser(path)))
    name = real.name
    if (real.parent != Path(os.path.realpath(RUNTIME))
            or not (name == CONVENTIONS.name or (name.startswith('2b-security') and name.endswith('.md')))):
        stop(f'{path} is not a copy Step 2b wrote: only sysop/runtime/2b-conventions.md and '
             'sysop/runtime/2b-security*.md take a receipt')
    if sys.stdin is None or sys.stdin.isatty():
        stop("the reviewer's READ: line goes on stdin, through a quoted heredoc")
    try:
        # Bytes, not `read_text()`: its universal newlines turn a lone `\r` into a line end.
        body = real.read_bytes().decode('utf-8', 'replace')
        given = _receipt_lines(sys.stdin.buffer.read().decode('utf-8', 'replace'))
    except OSError as e:
        stop(f'cannot read {real} or stdin: {e}')
    # Lines end at `\n` only, as `Read` and `wc -l` count them: `str.splitlines()` also splits at
    # U+2028, a form feed or a lone `\r`, which neither tool does.
    shown = [line[:-1] if line.endswith('\r') else line for line in body.split('\n')]
    lines = shown[:-1] if body.endswith('\n') else shown
    filled = [line for line in lines if line.strip()]
    if not filled:
        stop(f'{real} is empty; the prompt told its reviewer to stop on that')
    # `wc -l` counts newlines, a file tool numbers lines; they differ by one only when the copy
    # does not end in a newline. Claude Code's `Read` shows one more, blank, line after a final
    # newline (measured on a 190-line copy: line 191). A copy that ends in blank lines may be
    # counted to its last non-blank one, the line the receipt quotes. Each reached the end.
    tail = max(i for i, line in enumerate(lines) if line.strip()) + 1
    counts = {len(lines), body.count('\n'), tail, len(shown)}
    if len(given) != 1:
        print(f'MISMATCH: {real} — {len(given) or "no"} READ: line{"s" if len(given) > 1 else ""}; '
              'a receipt is exactly one `READ: <N> lines, last: <line>`')
        sys.exit(1)
    n, last = int(given[0].group(1).replace(',', '')), given[0].group(2)
    wrong = []
    if n not in counts:
        wrong.append(f'it says {n} lines and the copy has {len(lines)}')
    if not _same_line(last, filled[-1]):
        wrong.append(f'its last line is not the copy\'s, which reads: {filled[-1].strip()[:200]}')
    if wrong:
        print(f'MISMATCH: {real} — ' + '; '.join(wrong))
        sys.exit(1)
    print(f'RECEIPT OK: {real} ({len(lines)} lines)')


def cmd_baseline() -> None:
    for old in (TREE_BASELINE, CONFIG_BASELINE, AGENTS_BASELINE, OWN):
        try:
            old.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            stop(f'cannot remove {old}: {e}')
    tree, config, agents = tree_now(), config_now(), agents_now()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    # `surrogateescape` round-trips a name that is not UTF-8, which `os.fsdecode` hands over.
    TREE_BASELINE.write_text(tree, encoding='utf-8', errors='surrogateescape')
    CONFIG_BASELINE.write_text(config, encoding='utf-8', errors='surrogateescape')
    AGENTS_BASELINE.write_text(agents, encoding='utf-8', errors='surrogateescape')
    status = [line for line in tree.splitlines() if not line.startswith('# ')]
    print(f'BASELINE: {len(status)} status line(s), {len(config.splitlines())} config line(s), '
          f'{len(agents.splitlines())} worktree or agent-branch line(s)')


def cmd_own(path: str) -> None:
    if not path.strip() or '<' in path:
        stop(f'path {path!r} is empty or not substituted; write it out')
    real = os.path.realpath(os.path.expanduser(path))
    # Only a worktree the harness made for an agent: a recorded path is one whose uncommitted
    # files `reap` may discard, so a mistyped or borrowed path must not become one (lens B).
    if (real not in {os.path.realpath(w['path']) for w in worktrees()[1:]}
            or not agent_dir(real) or not os.path.basename(real).startswith('agent-')):
        stop(f'{path} is not a linked agent-* worktree under .claude/worktrees/; record only '
             "the worktreePath an agent's completion notice names")
    c = classify()
    if c['missing']:
        stop(c['missing'])
    if real in c['then_wt']:
        stop(f'{path} was there before this close\'s baseline, so no agent of this close made it')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        with OWN.open('a', encoding='utf-8', errors='surrogateescape') as f:
            f.write(real + '\n')
    except OSError as e:
        stop(f'cannot write {OWN}: {e}')
    print(f'OWN: {real}')


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
        try:
            r = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, env=_ENV, cwd=path)
            head = text(r).strip() if r.returncode == 0 else ''
        except OSError:                 # its directory is gone; git still lists it (round, lens A)
            head = ''
        if not want or not head.startswith(want):
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


def describe(w: dict) -> str:
    return f'{w["path"]} (branch {w["branch"] or "(detached)"})'


def owner_of(line: str, c: dict) -> str | None:
    """The class of the worktree a primary-tree status line falls in, if any."""
    path = line[3:].strip().strip('"').rstrip('/')
    top = os.path.realpath('.')
    for real, kind in c.get('paths', {}).items():
        rel = os.path.relpath(real, top).replace(os.sep, '/')
        if path == rel or path.startswith(rel + '/'):
            return kind
    return None


def foreign_config(line: str, c: dict) -> bool:
    # By prefix, not by parsing: a branch name may hold a `.` or an `=` (round 1, lens A). What
    # follows is a bare variable name, so `branch.feat.x.merge` is `feat.x`'s, not `feat`'s.
    for b in c.get('foreign_branches', ()):
        head = f'branch.{b}.'
        if line.startswith(head) and '.' not in line[len(head):].split('=', 1)[0]:
            return True
    return False


def foreign_line(line: str, c: dict) -> bool:
    """A primary-tree baseline line that another session's worktree moved: its branch tip. A
    status line inside a peer's worktree is the first check's `FOREIGN:` line, not this one's."""
    return (line.startswith('# refs/heads/')
            and line[len('# refs/heads/'):].rsplit(' ', 1)[0] in c.get('foreign_branches', ()))


def named(line: str, c: dict) -> bool:
    if line.startswith('# refs/heads/'):
        return line[len('# refs/heads/'):].rsplit(' ', 1)[0] in c.get('held', {})
    return not line.startswith('# ') and owner_of(line, c) is not None


def cmd_check() -> None:
    found = False
    paths = worktree_paths()
    c = classify()
    notes: list[str] = []

    if c['missing']:
        print(c['missing'])
        found = True
        c = {}
    else:
        lines = ([f'LEAK: {describe(w)}' for w in c['leak']]
                 + [f'FOREIGN: {describe(w)}, another session\'s; not removed' for w in c['foreign']])
        print('\n'.join(lines) if lines else 'no agent worktrees')
        found |= bool(lines)
        notes += [f'LOCKED: {describe(w)}, lock {w["locked"] or "(no reason)"}; left, and its '
                  'process removes it when it exits' for w in c['locked']]
        notes += [f'PREDATES: {describe(w)}, there before this close; not removed'
                  for w in c['predates']]
        print('\n'.join(f'LEAK: branch {b}' for b in c['branches'])
              if c['branches'] else 'no agent branches')
        found |= bool(c['branches'])
        notes += [f'PREDATES: branch {b}, there before this close; not removed'
                  for b in c['predated_branches']]

    for label, base, now, is_foreign in (
            ('primary tree unchanged by 2b', TREE_BASELINE, tree_now(),
             lambda l: foreign_line(l, c)),
            ('local config unchanged by 2b', CONFIG_BASELINE, config_now(),
             lambda l: foreign_config(l, c))):
        if not base.is_file():
            print(f'MISSING BASELINE: {base} (run baseline before the first spawn)')
            found = True
            continue
        try:
            then = base.read_text(encoding='utf-8', errors='surrogateescape')
        except OSError as e:
            print(f'UNREADABLE BASELINE: {base}: {e}')
            found = True
            continue
        diff = list(difflib.unified_diff(then.splitlines(), now.splitlines(), str(base), 'now',
                                         lineterm=''))
        changed = [d for d in diff if d[:1] in '+-' and not d.startswith(('+++', '---'))]
        foreign = [d for d in changed if is_foreign(d[1:])]
        # A line the first check already named (a worktree's untracked directory, the branch it
        # has checked out) is that check's line, not a second, unattributed mutation.
        quiet = [d for d in changed if d not in foreign and named(d[1:], c)]
        rest = [d for d in diff if d not in foreign and d not in quiet]
        if any(d[:1] in '+-' and not d.startswith(('+++', '---')) for d in rest):
            print('\n'.join(rest))
            found = True
        else:
            print(label)
        if foreign:
            print('\n'.join(f'FOREIGN: {d}' for d in foreign))
            found = True

    pins = [p for p in paths if under(p, PINS)]
    print('\n'.join(pins) if pins else 'no pinned checkouts')
    found |= bool(pins)
    for n in notes:
        print(n)
    sys.exit(1 if found else 0)


def cmd_reap(default: str) -> None:
    if not default.strip() or '<' in default:
        stop(f'default branch {default!r} is empty or not substituted; write it out')
    if git('rev-parse', '--verify', '-q', f'refs/heads/{default}', check=False).returncode != 0:
        stop(f'{default} is not a local branch')
    c = classify()
    if c['missing']:
        stop(c['missing'])
    own, kept, removed = recorded(), 0, 0

    def ahead(rev: str) -> int:
        r = git('rev-list', '--count', f'refs/heads/{default}..{rev}', check=False)
        return int(text(r).strip()) if r.returncode == 0 and text(r).strip().isdigit() else -1

    def run_in(path: str, *args: str) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(['git', *args], capture_output=True, env=_ENV, cwd=path)
        except OSError:
            return None

    for w in c['leak']:
        path, branch, real = w['path'], w['branch'], os.path.realpath(w['path'])
        if os.path.isdir(path):
            r = run_in(path, 'rev-parse', 'HEAD')
            n = ahead(text(r).strip()) if r and r.returncode == 0 and text(r).strip() else -1
        else:
            # Its directory is gone and git still lists it (prunable): read its branch instead.
            n = ahead(f'refs/heads/{branch}') if branch else -1
        if n != 0:
            print(f'KEPT: {describe(w)}, '
                  + (f'{n} commit(s) ahead of {default}' if n > 0 else 'its commits unreadable'))
            kept += 1
            continue
        dirty: list[str] = []
        if os.path.isdir(path):
            r = run_in(path, 'status', '--porcelain', '-uall')
            if r is None or r.returncode != 0:
                print(f'KEPT: {describe(w)}, its status unreadable')
                kept += 1
                continue
            dirty = text(r).splitlines()
        if dirty and real not in own:
            print(f'KEPT: {describe(w)}, {len(dirty)} uncommitted file(s) and not recorded by '
                  'this close: another session\'s agent may have left it')
            kept += 1
            continue
        for d in dirty:
            print(f'DISCARDING: {path}: {d}')
        r = git('worktree', 'remove', *(['--force'] if dirty else []), path, check=False)
        if r.returncode != 0:
            err = os.fsdecode(r.stderr).strip().splitlines()
            print(f'KEPT: {describe(w)}, {err[-1] if err else "git worktree remove failed"}')
            kept += 1
            continue
        removed += 1
        print(f'REMOVED: {path}')
        if not branch:
            continue
        # Only an agent branch this close's spawns made. A recorded worktree can hold any branch
        # an agent checked out there: a claim's, the default branch, or one a peer made during
        # the window, so no other name is ours (rounds 1 and 2).
        if branch.startswith('worktree-agent-') and branch not in c['then_branches']:
            if git('branch', '-D', branch, check=False).returncode == 0:
                removed += 1
                print(f'REMOVED: branch {branch}')
            else:
                print(f'KEPT: branch {branch}, git branch -D failed')
                kept += 1
        else:
            print(f'KEPT: branch {branch}, not an agent branch this close made; not deleted')
            kept += 1
    for b in c['branches']:
        n = ahead(f'refs/heads/{b}')
        if n != 0:
            print(f'KEPT: branch {b}, '
                  + (f'{n} commit(s) ahead of {default}' if n > 0 else 'its commits unreadable'))
            kept += 1
            continue
        if git('branch', '-D', b, check=False).returncode != 0:
            print(f'KEPT: branch {b}, git branch -D failed')
            kept += 1
            continue
        removed += 1
        print(f'REMOVED: branch {b}')
    for w in c['foreign']:
        print(f'FOREIGN: {describe(w)}, another session\'s; not removed')
    print(f'REAPED: {removed} removed, {kept} kept')
    sys.exit(1 if kept else 0)


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
        stop('usage: review_pins.py {' + '|'.join(SUBCOMMANDS) + '} [<revision> | <path> | <default branch>]')
    sub, ops = argv[1], argv[2:]
    takes = 1 if sub in ('add', 'own', 'reap', 'receipt') else 0
    if len(ops) != takes:
        stop(f'{sub} takes {"one operand" if takes else "no operand"}')
    # The main checkout, not a linked worktree's top level (lens A): there the baseline would
    # read the wrong tree. Its git dir is the common dir, as `git_check.py primary-checkout` says.
    top = text(git('rev-parse', '--show-toplevel')).strip()
    gd = text(git('rev-parse', '--absolute-git-dir')).strip()
    cd = text(git('rev-parse', '--path-format=absolute', '--git-common-dir')).strip()
    if (not top or os.path.realpath(top) != os.path.realpath('.')
            or os.path.realpath(gd) != os.path.realpath(cd)):
        stop('run this from the main checkout\'s top level')
    {'clear-conventions': cmd_clear_conventions, 'baseline': cmd_baseline, 'clean': cmd_clean,
     'check': cmd_check, 'restore-hooks-path': cmd_restore_hooks_path,
     'own': lambda: cmd_own(ops[0]), 'reap': lambda: cmd_reap(ops[0]),
     'receipt': lambda: cmd_receipt(ops[0]),
     }.get(sub, lambda: cmd_add(ops[0]))()


if __name__ == '__main__':
    main(sys.argv)
