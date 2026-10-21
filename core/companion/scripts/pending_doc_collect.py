#!/usr/bin/env python3
"""pending_doc_collect.py — `/review-close` Step 3b: collect a branch's pending docs, or roll them back.

    python3 sysop/scripts/pending_doc_collect.py collect  "<workspace path>" "<branch>"
    python3 sysop/scripts/pending_doc_collect.py rollback "<workspace path>" "<branch>"

Run from the main checkout's top level. `collect` copies the workspace's
`sysop/runtime/pending-docs/*.md` into main's, provenance-checked by each doc's
`branch:`. `rollback` undoes this branch's collect when the workspace could not be
removed. A missing or unknown subcommand exits 2.

The skill text is the contract: `/review-close` Step 3b, items (a) and the rollback
under (b), says what each line and each exit code means. Both subcommands were that
step's two heredocs until Phase 386 (`Q-409` P3), moved verbatim.
"""
import sys

_SUBCOMMANDS = ('collect', 'rollback')
if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS:
    sys.stderr.write('usage: ' + sys.argv[0] + ' {' + '|'.join(_SUBCOMMANDS) + '} <args>\n')
    sys.exit(2)
_SUBCOMMAND = sys.argv.pop(1)

if _SUBCOMMAND == 'collect':
    import os, re, shutil, stat, sys, tempfile
    from pathlib import Path
    try:
        import yaml
    except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
        import glob, os, subprocess
        _sites = []
        try:
            _r = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                capture_output=True, text=True, timeout=5,
                env=dict((_k, _v) for _k, _v in os.environ.items()
                     if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                                   "GIT_COMMON_DIR", "GIT_INDEX_FILE")),
            )
            _g = _r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            _g = ""
        for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
            for _layout in (".venv", "venv"):
                _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
        sys.path[:0] = _sites
        import yaml

    wt      = Path(sys.argv[1])
    branch  = sys.argv[2]          # the branch this iteration is processing
    live    = Path('sysop/runtime/pending-docs')
    src_dir = wt / 'sysop' / 'runtime' / 'pending-docs'

    # `convention-candidates.md` is NOT a branch pending-doc. It is a fixed-name file
    # /codebase-review and /security-audit write, append to, and delete themselves; it
    # carries no `branch:` frontmatter and belongs to no branch. Collecting it moves a
    # live review round's candidates onto main, where Step 4c consolidates and deletes
    # them. Never collect it.
    NOT_A_BRANCH_DOC = set(['convention-candidates.md'])
    fm_re = re.compile(r'^\ufeff?---\n(.*?)\n---', re.DOTALL)

    # A wrong or unsubstituted <worktree-path> must be LOUD. The retired `cp` form
    # exited 1 on a bad path; a bare glob over a missing dir yields nothing and would
    # exit 0 with a success-shaped report, after which (b) removes the worktree and the
    # untracked docs are gone. Step 3c hard-errors on its unsubstituted placeholder for
    # the same reason.
    #
    # `src_dir` USED to sit in this same disjunction.
    # See REFERENCE.md, section Step 3b — provenance.
    if ('<worktree' in str(wt) or '<branch' in branch
            or not branch.strip() or not wt.is_dir()):
        print(f'PENDING-DOC COLLECT ABORTED: unusable worktree path or branch name '
              f'({wt}, {branch!r})')
        sys.exit(4)

    # THE MAIN CHECKOUT AS `<worktree-path>` (`Q-478`). Exit 4 refuses this operand: it is
    # an assertion about the INVOCATION, and main is untouched, which is what that row
    # promises. Compare RESOLVED paths — `workspace:` is written unresolved so it can
    # contain `/../`, and on macOS the repo root reaches through `/private` — and compare
    # the two DIRECTORIES rather than `wt` against the repo root, which tests the actual
    # hazard: source and destination are the same place. Bounded honestly: `live` is
    # CWD-relative, so run this from the repo root, as step 1 says — run from a SUBDIRECTORY
    # of main with `wt` naming the primary checkout and the two differ, the guard does not
    # fire, and the step builds a spurious `sysop/runtime/pending-docs/` under the CWD.
    # See REFERENCE.md, section Step 3b — provenance.
    try:
        _same_dir = src_dir.resolve() == live.resolve()
    except (OSError, RuntimeError) as e:
        # Measured on CPython 3.14: non-strict `resolve()` returns a path even for a
        # symlink loop, so this arm did not fire in testing. It is kept because the
        # alternative on an unanswerable comparison is to fall through into a step whose
        # documented remedy deletes, and because an uncaught exception here would exit 1 —
        # a code this step's own table does not carry.
        print(f'PENDING-DOC COLLECT ABORTED: {src_dir} cannot be resolved ({e}), so '
              f'whether it is main\'s own pending-docs directory is unanswerable — '
              f'refusing rather than proceeding toward a step that deletes by provenance')
        sys.exit(4)
    if _same_dir:
        print(f'PENDING-DOC COLLECT ABORTED: {wt} resolves to the checkout this close is '
              f'running in, so its pending-docs ARE main\'s — already where Step 4c '
              f'looks. Copying them onto themselves raises SameFileError and halts '
              f'this step, and before `Q-478` that halt\'s prescribed remedy deleted '
              f'them. Step 0 reports this workspace with the main-checkout shape and '
              f'an empty path, and step 1 skips this step for it; there is nothing to '
              f'collect here and nothing to remove.')
        sys.exit(4)

    WHY = {}
    def branch_of(p):
        """This doc's `branch:`, read with the SAME parser Steps 3c and 4c use.

    Deliberately `yaml.safe_load` and not a hand-rolled line scan. A scan diverges
    from PyYAML on ordinary YAML — a folded scalar (`branch: >`) yields the literal
    `>`, duplicate keys pick the wrong one, a trailing `# comment` is kept as part
    of the value — and two different branches collapsing to one token is precisely
    the silent overwrite this step exists to prevent. A third divergent reader in a
    file that already had two is what this phase is fixing; adding one would be the
    same defect wearing the fix's name.

    None is a real answer, not an error: a doc whose provenance will not parse can
    never be shown to be the SAME branch as another, and the caller treats
    unknown-vs-anything as a collision.
    """
        # ONLY A REGULAR FILE IS READ. A `*.md` glob matches by NAME, so a FIFO or a
        # directory carrying that name reaches here — and `read_text` on a FIFO BLOCKS
        # FOREVER, which no caller recovers from and no timeout here covers. Measured:
        # the rollback hung indefinitely on a neighbour FIFO in main's pending-docs.
        # `is_file()` follows symlinks, so a valid link to a real doc still reads and a
        # dangling one returns the sentinel.
        if not p.is_file():
            WHY[p] = ' — it is not a regular file'
            return None
        try:
            m = fm_re.match(p.read_text(encoding='utf-8', errors='replace'))
        except OSError as e:
            WHY[p] = f' — it could not be read ({type(e).__name__})'
            return None
        if not m:
            WHY[p] = ' — it has no frontmatter block at the top'
            return None
        try:
            fm = yaml.safe_load(m.group(1))
        except Exception as e:
            WHY[p] = f' — its frontmatter does not parse ({type(e).__name__}: {str(e).split(chr(10))[0]})'
            return None
        if not isinstance(fm, dict):
            WHY[p] = f' — its frontmatter is a {type(fm).__name__}, not a mapping'
            return None
        b = fm.get('branch')
        if isinstance(b, str) and b.strip():
            return b.strip()
        WHY[p] = (f' — `branch:` is a YAML {type(b).__name__}: quote it, or re-run /document-work'
                  if b is not None and not isinstance(b, str) else ' — it has no `branch:` value')
        return None

    def hold_of(p):
        """The doc's `hold:` (`Q-625`), read truthy as Step 4c 1c reads it; "" when it has none."""
        try:
            m = fm_re.match(p.read_text(encoding='utf-8', errors='replace'))
            fm = yaml.safe_load(m.group(1)) if m else None
        except Exception:
            return ''
        v = fm.get('hold') if isinstance(fm, dict) else None
        return (str(v).strip() or '(no reason given)') if v else ''

    def _git(*args, where=None):
        """Read-only git in `where` (default: the WORKSPACE), hermetic, and it FAILS OPEN
    — it never raises and never halts.

    **`where` exists because the two populations do not live in the same repository.**
    A doc collected FROM the workspace was stamped there, and the paragraph below is
    the argument for measuring it there. A doc already on MAIN was authored on the main
    checkout — that is what `Q-470`'s first reading means — and measuring *it* from a
    `--clone` workspace asks a repository that need not hold the commits: measured, a
    main-side drift of 1 read as **0** from the clone, and `rev-list` SUCCEEDED, so the
    run reported measured-and-clean over a record it had never measured. That is worse
    than the fail-open UNKNOWN arm because it is silent. Found by Phase 286's round.

    `-C wt`, not the CWD, and that is the whole coverage argument. A `--clone`
    workspace is a **separate repository** (`claim_task.sh --clone` publishes the
    branch and clones `origin`), so its commits live in its own object store; measured
    from the main checkout, a clone-shape doc's `branch_tip` did not resolve, and every
    clone-shape close took the unknown arm — armed-looking and dead for that
    whole population. Run from the workspace, the objects are always there: a linked
    worktree shares the primary's store, and a clone has its own. The branch this asks
    about is the branch the DOC describes, which is the one the workspace holds.

    The env strip is Phase 124's rule: an inherited `GIT_DIR`/`GIT_WORK_TREE` from the
    caller's shell overrides `-C` and resolves the wrong repository. Returning None on
    any failure is deliberate and is stated in the exit table: a missing git, a
    workspace that is not a repository, or a pruned object must not turn a
    doc-integrity step into a refusal to close. Every doc written before `branch_tip:`
    existed reaches the staleness test below with nothing to compare, and that case has
    to be indistinguishable from a git that would not answer.
    """
        import os, subprocess
        try:
            r = subprocess.run(
                ['git', '-C', str(where if where is not None else wt), *args],
                capture_output=True, text=True, timeout=10,
                env=dict((_k, _v) for _k, _v in os.environ.items()
                     if _k not in ('GIT_DIR', 'GIT_WORK_TREE',
                                   'GIT_COMMON_DIR', 'GIT_INDEX_FILE')),
            )
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            return None
        return r.stdout if r.returncode == 0 else None

    UNUSABLE_TIP = object()   # the key is there and its value cannot be an object name

    def tip_of(p):
        """This doc's `branch_tip:` — the branch tip /document-work Step 3 authored it
    against. None is the ordinary answer for every doc predating the key; the
    `UNUSABLE_TIP` sentinel says the key IS present and its value is not a string."""
        # DEFENCE IN DEPTH, AND UNREACHABLE TODAY — said plainly because the phase that
        # added it claimed otherwise. Every call site into `staleness()` pre-filters on
        # `branch_of(...) == branch`, and `branch_of` already returns None for anything
        # that is not a regular file, so a FIFO or a directory can never arrive here.
        # Proven rather than argued: replacing this guard's body with a fatal probe leaves
        # all 137 tests green, i.e. no test can reach it. Found by Phase 286's round, whose
        # guard lens also showed the phase's own battery had scored a kill against it by
        # mutating all three copies of this guard at once.
        #
        # It stays because the property it protects is real — `read_text` on a FIFO BLOCKS
        # FOREVER, which no caller recovers from and no timeout here covers — and a future
        # call site that skips the filter would need it. What it must not do is be counted
        # as covered. The reachable copies are the two in `branch_of`, and those are.
        if not p.is_file():
            return None
        try:
            m = fm_re.match(p.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            return None
        if not m:
            return None
        try:
            fm = yaml.safe_load(m.group(1))
        except Exception:
            return None
        if not isinstance(fm, dict):
            return None
        if 'branch_tip' not in fm:
            return None
        t = fm.get('branch_tip')
        # PRESENT-BUT-UNUSABLE is not ABSENT, and reporting it as absent states something
        # false about the doc. `branch_tip: 1234567` is a YAML *int*, `true` a bool,
        # `null` a None — all legal YAML, none of them an object name, and each one
        # reaches here from a hand-edited or machine-mangled frontmatter. Returning the
        # sentinel lets the caller say which it saw.
        return t.strip() if isinstance(t, str) and t.strip() else UNUSABLE_TIP

    SHA_RE = re.compile(r'[0-9a-fA-F]{7,64}\Z')

    def staleness(paths, where=None):
        """`Q-471`'s comparison, over ANY population of docs claiming this branch.

    **This lived inside the `src_dir`-present loop and nowhere else, which is the
    defect it is being hoisted out of.** Phase 282 shipped `Q-470` and `Q-471`
    together: `Q-470` made an absent `src_dir` a legitimate exit-0 state, and that
    arm returns BEFORE the loop — so a doc authored into the MAIN checkout, the path
    `/document-work` explicitly supports and the one `Q-470` exists to let through,
    was never compared against the branch tip at all. Measured: one commit of drift,
    `PENDING-DOC COLLECT SKIPPED`, exit 0, no `PENDING-DOC STALE`, and Step 4c then
    routes the outdated `summary:` into the shared docs in the same commit that flips
    the task `done`.

    Single-sourced rather than copied into the second site. Two readers of one rule
    twenty lines apart is exactly what this step already paid for once, when the
    rollback hand-rolled a frontmatter scan while the collect used yaml and the two
    halves disagreed on 18 of 33 shapes.

    The caller passes only docs that CLAIM this branch. A foreign doc is a
    collision, settled before anything is said about currency — "whose record is
    this" outranks "is this record current", which is the ordering the populated
    path's own comment states.
    """
        unknown, stale = [], []
        for src in paths:
            tip = tip_of(src)
            if tip is None:
                unknown.append(f'{src.name} (no `branch_tip:` — written before the key '
                                   f'existed, or by a writer that does not emit it)')
            elif tip is UNUSABLE_TIP:
                unknown.append(f'{src.name} (`branch_tip:` is present but is not a '
                                   f'string — a bare hex-looking value is a YAML int, and '
                                   f'`true`/`null`/`[]` are not object names either)')
            elif '<' in tip:
                # The writer emitted its own template verbatim. `is not an object name` is
                # true of it but names the wrong cause, and this heredoc already treats an
                # unsubstituted `<worktree-path>` as its own loud case. Still fail open: the
                # defect is in a writer, and halting every close until someone fixes one is
                # the disposition `Q-470` is on this page for.
                unknown.append(f'{src.name} (`branch_tip:` is an UNSUBSTITUTED PLACEHOLDER '
                                   f'— {tip!r}. The writer did not fill it in; fix the writer, '
                                   f'not this close)')
            elif not SHA_RE.match(tip):
                unknown.append(f'{src.name} (`branch_tip: {tip!r}` is not an object name)')
            else:
                counted = _git('rev-list', '--count', f'{tip}..{branch}',
                           where=where)
                try:
                    drift = int((counted or '').strip())
                except ValueError:
                    counted = None
                    drift = 0
                if counted is None:
                    unknown.append(f'{src.name} (`branch_tip` {tip[:12]} does not resolve '
                                       f'here — not evidence either way)')
                elif drift:
                    log = (_git('log', '--oneline', '--no-decorate',
                                f'{tip}..{branch}', where=where)
                           or '').strip()
                    stale.append((src.name, tip[:12], drift, log))
        return unknown, stale

    def claimed_ids():
        """`Q-594`. Task ids whose lock names this branch; a review batch's `BATCH-<N>.lock`
    is excluded. See REFERENCE.md, section Step 3b — provenance."""
        locks, claimed = Path('sysop/runtime/locks'), []   # CWD-relative, like `live`
        if not locks.is_dir():
            return claimed
        try:
            entries = sorted(locks.iterdir())
        except OSError as e:
            print(f'PENDING-DOC CLAIMS UNREADABLE: {locks} could not be listed ({e}); '
                  f'whether a task lock names {branch!r} was not checked')
            return claimed
        for lk in entries:
            if not lk.name.endswith('.lock') or re.fullmatch(r'BATCH-\d+\.lock', lk.name):
                continue
            # Stat explicitly, not via `is_file()`: see REFERENCE.md, section Step 3b — provenance.
            try:
                if not stat.S_ISREG(lk.stat().st_mode):
                    continue            # a FIFO blocks `read_text` forever
                lines = lk.read_text(encoding='utf-8', errors='replace').splitlines()
            except FileNotFoundError:
                continue                # vanished, or a dangling link: names nothing
            except OSError as e:
                print(f'PENDING-DOC CLAIMS UNREADABLE: {lk} ({e}); whether it names '
                      f'{branch!r} was not checked')
                continue
            fields = {}
            for line in lines:
                if not line or line[0].isspace() or line.startswith(('-', '#')):
                    continue
                k, sep, v = line.partition(':')
                if sep and k.strip() not in fields:
                    fields[k.strip()] = v.strip()
            if fields.get('branch') == branch:
                claimed.append(fields.get('task_id') or lk.stem)
        return claimed

    def refuse_if_claimed_but_undocumented():
        """`Q-594`. Called only when NO doc claims this branch, in the workspace or on main."""
        claimed = claimed_ids()
        if not claimed:
            return
        print(f'PENDING-DOC MISSING: {branch!r} is claimed by {", ".join(claimed)} (a '
              f'lock in sysop/runtime/locks/ names it) and no doc claims the branch — '
              f'refusing. Step 4c closes only the ids a doc names, so merging it would '
              f'leave the claim open. Nothing collected, main untouched, worktree left in '
              f'place. Run /document-work on this branch, then re-run the close; if the '
              f'branch delivers only part of the claim, leave that id out of `roadmap_ids`.'
              + ''.join(f' Unreadable: {d.name}{w}.' for d, w in WHY.items()))
        sys.exit(8)

    def report_open_claims(doc_paths):
        """`Q-604`'s report half: report, never refuse, each claimed id that no doc for
    this branch names. See REFERENCE.md, section Step 3b — provenance."""
        named = set()
        for d in doc_paths:
            try:
                m = fm_re.match(d.read_text(encoding='utf-8', errors='replace'))
                fm = yaml.safe_load(m.group(1)) if m else None
            except Exception:
                fm = None
            if isinstance(fm, dict):
                ids = fm.get('roadmap_ids') or fm.get('task_ids') or []   # Phase 23a shim
                named |= {str(i).strip() for i in (ids if isinstance(ids, list) else [ids])}
        for tid in claimed_ids():
            if tid not in named:
                print(f'PENDING-DOC OPEN CLAIM: {tid} — its lock names {branch!r} and no doc '
                      f'for the branch names the id, so if the branch merges this close '
                      f'leaves it in_progress with its lock held')

    # `src_dir` ABSENT is not an error — see the guard above. An existing but EMPTY
    # `src_dir` reaches stage 1 with `docs == []`, collects nothing and exits 0 — or 8, when
    # a task lock names the branch (`Q-594`). The two states must not be dispositioned
    # differently.
    # See REFERENCE.md, section Step 3b — provenance.
    if not src_dir.is_dir():
        # The wrong-but-existing directory, refused by the one test that tells it apart
        # from the legitimate state. A HEALTHY workspace is always a checkout — a linked
        # worktree (`.git` file) or a clone (`.git` directory) — and `main-checkout` never
        # runs this heredoc at all. Arm (ii) `recorded` accepts the lock's `workspace:` on
        # `cand.is_dir()` alone, so a stale or hand-edited lock naming a plain directory
        # resolves as `recorded` and arrives here. Exit 4 is the right answer for it —
        # there is no checkout to collect from — which is why the message below names the
        # actual reason instead of reusing the generic one.
        # See REFERENCE.md, section Step 3b — provenance.
        if not (wt / '.git').exists():
            print(f'PENDING-DOC COLLECT ABORTED: {wt} is not a checkout (no .git) and '
                  f'holds no sysop/runtime/pending-docs — nothing here belongs to '
                  f'{branch!r}. Check the workspace this branch\'s lock records.')
            sys.exit(4)
        on_main = sorted(
            q.name for q in live.glob('*.md')
            if q.name not in NOT_A_BRANCH_DOC and branch_of(q) == branch
        ) if live.is_dir() else []
        if on_main:
            print(f'PENDING-DOC COLLECT SKIPPED: no {src_dir} — this branch\'s doc is '
                  f'already on main ({", ".join(on_main)}); nothing to collect')
        else:
            print(f'PENDING-DOC COLLECT SKIPPED: no {src_dir}, and main holds no doc '
                  f'claiming {branch!r} — this branch has no pending-doc anywhere')
            refuse_if_claimed_but_undocumented()

        # `Q-471` RUNS HERE TOO, and until this arm existed it did not. "Nothing to
        # collect" is a statement about the COPY, never about whether the record on main
        # is current — and on this route main's doc is the one Step 4c will consolidate,
        # so it is precisely the doc whose freshness decides a task's state. The exit
        # code matches the populated path's because the operator's remedy is identical:
        # re-run /document-work on this branch to re-stamp `branch_tip:`.
        if on_main:
            # Same rule as the populated path below, with an empty incoming set:
            # every doc main holds for this branch survives into Step 4c. Measured
            # in the MAIN checkout, which is where these docs were authored.
            unknown_here, stale_here = staleness([live / n for n in on_main],
                                                 where=Path.cwd())
            for u in unknown_here:
                print(f'PENDING-DOC STALENESS UNKNOWN: {u}')
            if stale_here:
                for name, tip12, drift, log in stale_here:
                    print(f'PENDING-DOC STALE: {name} — {drift} commit(s) landed on '
                          f'{branch!r} after the doc was authored (branch_tip {tip12})')
                    for line in log.split('\n'):
                        if line:
                            print(f'    after the doc: {line}')
                # The state claim differs from the populated path's on purpose: nothing
                # was collected *because there was nothing to collect*, and main is NOT
                # untouched in the sense that matters — it is holding the stale doc.
                print(f'PENDING-DOC STALE: {len(stale_here)} — refusing. Nothing was '
                      f'collected (there was nothing to collect), but main is holding a '
                      f'doc for {branch!r} that the branch has outgrown, and Step 4c '
                      f'would route its summary while flipping the task done. Re-run '
                      f'/document-work on this branch to refresh it (that re-stamps '
                      f'`branch_tip:`), then re-run the close.')
                sys.exit(6)
            report_open_claims([live / n for n in on_main])
        print('PENDING-DOC COLLISIONS: 0')
        sys.exit(0)

    docs = [p for p in sorted(src_dir.glob('*.md')) if p.name not in NOT_A_BRANCH_DOC]

    # STAGE 1 — DECIDE. Nothing is written until every doc has been checked, so there is
    # no partial state to undo. Deciding first makes that class impossible rather than
    # handled.
    # See REFERENCE.md, section Step 3b — provenance.
    collisions = []
    # THE POPULATION IS "EVERY DOC THIS RUN LEAVES FOR STEP 4c TO CONSOLIDATE", and
    # that is the rule on BOTH routes.
    #
    # Two terms, because they are two different claims measured in two different repos:
    #   - the worktree's own docs claiming this branch, which this run is about to copy;
    #   - main's docs claiming this branch that this run will NOT overwrite, which
    #     therefore survive into Step 4c exactly as they are.
    # A main doc whose name IS in the incoming set is excluded: it is replaced by the
    # fresh copy, so its staleness is about to stop existing.
    #
    # Only docs that CLAIM this branch. The loop below skips a foreign doc with a
    # `continue` before it ever reached the staleness read: measuring a foreign doc's
    # drift asks the wrong question about the wrong record, and its answer would
    # refuse a close over a doc this branch has no claim on.
    # See REFERENCE.md, section Step 3b — provenance.
    mine = [d for d in docs if branch_of(d) == branch]
    incoming = {d.name for d in mine}
    surviving_on_main = [
        q for q in sorted(live.glob('*.md'))
        if q.name not in NOT_A_BRANCH_DOC and q.name not in incoming
        and branch_of(q) == branch
    ] if live.is_dir() else []
    unknown_tip, stale = staleness(mine, where=wt)
    _u2, _s2 = staleness(surviving_on_main, where=Path.cwd())
    unknown_tip += _u2
    stale += _s2
    for src in docs:
        # Ground truth is the branch being PROCESSED, not what two docs say about each
        # other. A doc that does not claim this branch is not this branch's to collect.
        src_b = branch_of(src)
        if src_b != branch:
            collisions.append(f'{src.name} (worktree doc claims {src_b!r}, '
                              f'processing {branch!r}){WHY.get(src, "")}')
            continue

        # STALENESS (`Q-471`). `branch_tip` is free-form frontmatter, and an unvalidated value
        # beginning with `-` reaches `git rev-list` as an option rather than a revision, so
        # `SHA_RE` is not decoration. A value that is not an object name is not a measurement,
        # so it takes the same arm as a git that would not answer.
        # See REFERENCE.md, section Step 3b — provenance.
        dst = live / src.name
        if dst.exists():
            dst_b = branch_of(dst)
            # Overwrite ONLY main's own stale twin of this same branch. Any other
            # branch's record is untouchable, however this branch's doc is labelled.
            if dst_b != branch:
                collisions.append(f'{src.name} (main copy belongs to {dst_b!r}, '
                                  f'processing {branch!r}){WHY.get(dst, "")}')
            # `Q-625`: never replace main's held copy with a doc that drops its `hold:`.
            elif hold_of(dst) and not hold_of(src):
                collisions.append(f'{src.name} (main copy carries `hold: {hold_of(dst)}` and '
                                  f'the incoming doc does not; add that `hold:` line to the '
                                  f'incoming doc, or, if its step is done, clear main\'s copy '
                                  f'with `python3 sysop/scripts/pending_doc_hold.py clear '
                                  f'{src.name}`, then re-run)')
    for u in unknown_tip:
        print(f'PENDING-DOC STALENESS UNKNOWN: {u}')

    if collisions:
        for c in collisions:
            print(f'PENDING-DOC COLLISION: {c}')
        print(f'PENDING-DOC COLLISIONS: {len(collisions)} — refusing; '
              f'nothing collected, main untouched, worktree left in place')
        sys.exit(3)

    # An existing-but-EMPTY `src_dir` with nothing on main is the absent arm's `Q-594`
    # shape, and takes the same refusal.
    if not mine and not surviving_on_main:
        refuse_if_claimed_but_undocumented()

    # Collisions outrank staleness: a collision is about WHOSE record this is, which has
    # to be settled before anything is said about whether a record is current.
    if stale:
        for name, tip12, drift, log in stale:
            print(f'PENDING-DOC STALE: {name} — {drift} commit(s) landed on {branch!r} '
                  f'after the doc was authored (branch_tip {tip12})')
            for line in log.split('\n'):
                if line:
                    print(f'    after the doc: {line}')
        print(f'PENDING-DOC STALE: {len(stale)} — refusing; nothing collected, main '
              f'untouched, worktree left in place. Re-run /document-work on this branch '
              f'to refresh its doc (that re-stamps `branch_tip:`), then re-run the close.')
        sys.exit(6)

    if mine or surviving_on_main:
        report_open_claims(mine + surviving_on_main)

    # STAGE 2 — COPY. Every doc has already been cleared.
    # `live.mkdir` is the one write here that can fail BEFORE any doc is touched, and
    # uncaught it exits **1** with a traceback — a code this step's table does not carry,
    # on the very cause this failure's row names (an unwritable `sysop/runtime/pending-docs/`).
    # Reproduced: an unwritable PARENT with the directory absent.
    try:
        live.mkdir(parents=True, exist_ok=True)   # load-bearing, see below
    except OSError as e:
        print(f'PENDING-DOC COLLECT FAILED: {live} could not be created: {e}')
        print('PENDING-DOC UNDO: nothing to undo — stage 2 never started.')
        sys.exit(7)

    # STAGE 2 — COPY, AND UNDO ITSELF IF IT CANNOT FINISH. Stage 2 cannot decide first — a
    # write either works or it does not — so it gets the same property the other way: it
    # restores what it displaced and removes what it created, and main ends as it began.
    #
    # THE UNDO RESTORES; IT DOES NOT UNLINK. The dominant collision here is the same branch
    # collected twice, where the copy deliberately OVERWRITES main's stale twin, so a
    # delete-based undo would destroy the very record the overwrite displaced. Each doc's
    # prior copy is preserved first, and only docs this run CREATED are removed.
    # See REFERENCE.md, section Step 3b — provenance.
    staged, undo_root = [], None
    for src in docs:
        dst = live / src.name
        bak = None
        try:
            # `os.path.lexists`, NOT `dst.exists()`. `exists()` FOLLOWS SYMLINKS, so a
            # DANGLING symlink at the destination reads as absent: no backup is taken,
            # `copy2` then writes THROUGH the link — creating a file wherever it points,
            # outside this directory — and the undo, seeing `bak is None`, concludes this
            # run created the entry and unlinks it. Measured before the fix: main lost the
            # symlink, gained a stray file under a sibling directory, and the step reported
            # *"main is as it was"*. Found by Phase 284's round 2.
            if os.path.lexists(dst):
                if undo_root is None:
                    # A random name, per the fixed-name temp class this project converted
                    # (Phases 271-272): a predictable path is another process's to collide with.
                    undo_root = Path(tempfile.mkdtemp(prefix='sysop-collect-undo-'))
                bak = undo_root / src.name
                # `follow_symlinks=False` preserves the LINK rather than its target, so a
                # symlink can be put back as a symlink.
                shutil.copy2(dst, bak, follow_symlinks=False)
                if dst.is_symlink():
                    dst.unlink()            # never write THROUGH it
            staged.append((src.name, bak))
            shutil.copy2(src, dst)
        except OSError as e:
            print(f'PENDING-DOC COLLECT FAILED: {src.name}: {e}')
            restored, removed, stuck = [], [], []
            for name, saved in reversed(staged):
                d = live / name
                try:
                    if saved is not None:
                        # Unlink ONLY where it is required: writing through a symlink
                        # would put the bytes outside this directory, and restoring a
                        # symlink needs the destination gone first. Doing it
                        # unconditionally breaks the ordinary restore — `live` is usually
                        # read-only when this arm fires, and removing an entry needs
                        # DIRECTORY write permission while overwriting a file in place
                        # does not. Measured: it turned three passing restores into
                        # PermissionError.
                        if (os.path.islink(d) or os.path.islink(saved)) and os.path.lexists(d):
                            d.unlink()
                        shutil.copy2(saved, d, follow_symlinks=False)
                        restored.append(name)
                    elif os.path.lexists(d):
                        d.unlink()                      # this run created it
                        removed.append(name)
                except OSError as ue:
                    stuck.append(f'{name}: {ue}')
            print(f'PENDING-DOC UNDO: {len(restored)} restored'
                  f'{" (" + ", ".join(restored) + ")" if restored else ""}, '
                  f'{len(removed)} removed'
                  f'{" (" + ", ".join(removed) + ")" if removed else ""}')
            if stuck:
                # The undo itself failed. THIS is the only way main is left partial, and
                # the backups are deliberately not cleaned up — they are the remedy.
                for s in stuck:
                    print(f'PENDING-DOC UNDO FAILED: {s}')
                # `undo_root` is None when nothing had been displaced yet, and an earlier
                # cut of this line printed the literal string "preserved in None" at an
                # operator being told to restore by hand from it.
                where = (f'Main\'s prior copies are preserved in {undo_root}; restore '
                         f'them by hand.' if undo_root is not None else
                         'No copies were preserved — nothing had been displaced yet, so '
                         'the entries named above are ones this run created and could not '
                         'remove.')
                print(f'PENDING-DOC UNDO FAILED: {len(stuck)} — main MAY BE PARTIAL. '
                      f'{where} Do NOT run the rollback: it deletes by provenance, which '
                      f'is what `Q-481` is about, and it would remove records this run '
                      f'never wrote.')
                sys.exit(5)
            if undo_root is not None:
                shutil.rmtree(undo_root, ignore_errors=True)
            print('PENDING-DOC UNDO: main is as it was. Do NOT run the rollback — there '
                  'is nothing to undo, and it deletes by provenance rather than by what '
                  'this run copied.')
            sys.exit(7)
        print(f'PENDING-DOC COLLECTED: {src.name}')
    if undo_root is not None:
        shutil.rmtree(undo_root, ignore_errors=True)
    for p in sorted(src_dir.glob('*.md')):
        if p.name in NOT_A_BRANCH_DOC:
            print(f'PENDING-DOC SKIPPED (not a branch doc): {p.name}')
    print('PENDING-DOC COLLISIONS: 0')

elif _SUBCOMMAND == 'rollback':
    import os, re, sys
    from pathlib import Path

    try:
        import yaml
    except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
        import glob, os, subprocess
        _sites = []
        try:
            _r = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                capture_output=True, text=True, timeout=5,
                env=dict((_k, _v) for _k, _v in os.environ.items()
                     if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                                   "GIT_COMMON_DIR", "GIT_INDEX_FILE")),
            )
            _g = _r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            _g = ""
        for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
            for _layout in (".venv", "venv"):
                _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
        sys.path[:0] = _sites
        import yaml

    wt     = Path(sys.argv[1])
    branch = sys.argv[2]
    live   = Path('sysop/runtime/pending-docs')
    NOT_A_BRANCH_DOC = set(['convention-candidates.md'])   # never collected, so never rolled back
    fm_re = re.compile(r'^\ufeff?---\n(.*?)\n---', re.DOTALL)

    src_dir = wt / 'sysop' / 'runtime' / 'pending-docs'

    # `wt.is_dir()` is here for the reason the COLLECT's own guard states about itself:
    # a bad path must be LOUD. Without it this heredoc globs a directory that is not
    # there, finds nothing, prints `ROLLED BACK: none` and exits **0** — a
    # success-shaped report over a rollback that did not happen, which is exactly the
    # failure mode the collect's comment forbids. Measured on a typo'd operand: rollback
    # exit 0 while the collect refused the same path at 4. Found by Phase 284's round.
    if ('<worktree' in str(wt) or '<branch' in branch
            or not branch.strip() or not wt.is_dir()):
        print(f'PENDING-DOC ROLLBACK ABORTED: unusable worktree path or branch name '
              f'({wt}, {branch!r})')
        sys.exit(4)

    # The same operand refusal the collect carries (`Q-478`), sited here as well because
    # THIS is the half that deletes. The collect merely fails on a main-checkout
    # `<worktree-path>`; the rollback walks the worktree's docs and unlinks main's copy of
    # each, so when the two directories are the same it unlinks the ORIGINALS.
    #
    # Stated precisely, because the easy version of this sentence overclaims: with the
    # collect's refusal in place the CHAINED route is already closed — step (b) is reached
    # only after the collect exits 0, and on this operand it now exits 4. What this guard
    # covers is the rollback invoked on its own, which the page now prescribes from ONE
    # place — step (b), when `git worktree remove` still refuses — and which takes the same
    # hand-substituted operand. (An earlier cut of this comment said "two places, exit 5's
    # disposition and step (b)". That was true before `Q-481` removed the exit-5
    # prescription, and it then contradicted a paragraph 110 lines away in this same file
    # for one commit. Round 2 caught it.) Defence in depth on the half that deletes, not a
    # second live route.
    try:
        _same_dir = src_dir.resolve() == live.resolve()
    except (OSError, RuntimeError) as e:
        print(f'PENDING-DOC ROLLBACK ABORTED: {src_dir} cannot be resolved ({e}), so '
              f'whether it is main\'s own pending-docs directory is unanswerable — '
              f'refusing rather than deleting')
        sys.exit(4)
    if _same_dir:
        print(f'PENDING-DOC ROLLBACK ABORTED: {wt} resolves to the checkout this close is '
              f'running in. Rolling back here would unlink main\'s own pending-docs — the '
              f'originals, not copies of them. Nothing was ever collected FROM main, so '
              f'there is nothing to undo.')
        sys.exit(4)

    WHY = {}
    def branch_of(p):
        """Identical to the collect's reader — same regex, same `yaml.safe_load`.

    An earlier draft hand-rolled a line scan here while the collect used yaml, so
    the two halves of one step disagreed on 18 of 33 frontmatter shapes: the
    rollback could not undo its own collect, and reported a byte-identical doc as
    'not this branch's'. Two divergent readers twenty lines apart, in the phase
    whose subject is two divergent readers."""
        # ONLY A REGULAR FILE IS READ. A `*.md` glob matches by NAME, so a FIFO or a
        # directory carrying that name reaches here — and `read_text` on a FIFO BLOCKS
        # FOREVER, which no caller recovers from and no timeout here covers. Measured:
        # the rollback hung indefinitely on a neighbour FIFO in main's pending-docs.
        # `is_file()` follows symlinks, so a valid link to a real doc still reads and a
        # dangling one returns the sentinel.
        if not p.is_file():
            WHY[p] = ' — it is not a regular file'
            return None
        try:
            m = fm_re.match(p.read_text(encoding='utf-8', errors='replace'))
        except OSError as e:
            WHY[p] = f' — it could not be read ({type(e).__name__})'
            return None
        if not m:
            WHY[p] = ' — it has no frontmatter block at the top'
            return None
        try:
            fm = yaml.safe_load(m.group(1))
        except Exception as e:
            WHY[p] = f' — its frontmatter does not parse ({type(e).__name__}: {str(e).split(chr(10))[0]})'
            return None
        if not isinstance(fm, dict):
            WHY[p] = f' — its frontmatter is a {type(fm).__name__}, not a mapping'
            return None
        b = fm.get('branch')
        if isinstance(b, str) and b.strip():
            return b.strip()
        WHY[p] = (f' — `branch:` is a YAML {type(b).__name__}: quote it, or re-run /document-work'
                  if b is not None and not isinstance(b, str) else ' — it has no `branch:` value')
        return None

    # POPULATION — `Q-482`. The worktree's docs were only ever a NAME source: every
    # unlink below is gated on MAIN's own copy claiming this branch, so `src_dir`
    # decided which names to look at and nothing else. On `Q-470`'s absent-`src_dir`
    # route there are no names, so this loop ran zero times over a main that was holding
    # this branch's doc and printed `ROLLED BACK: none` at exit 0 — the success-shaped
    # report the collect's own comment forbids, one heredoc away, with step (b) as the
    # only caller. So the population is the UNION of the worktree's names and main's own
    # docs claiming this branch.
    #
    # The union, NOT a replacement. Dropping the worktree half would retire the
    # `LEFT ALONE` diagnostic — Phase 210's foreign-branch finding, and the only line
    # that says a doc was deliberately spared rather than never looked at.
    def _md_names(d):
        return (set(p.name for p in d.glob('*.md') if p.name not in NOT_A_BRANCH_DOC)
                if d.is_dir() else set())

    # An entry in main that cannot be READ carries no branch claim, so this step cannot
    # attribute it to this branch and does not reach for it here. It is still reported
    # when the worktree names it, which is the case measured below.
    names = _md_names(src_dir) | {
        n for n in _md_names(live) if branch_of(live / n) == branch
    }

    # RESTORE, DO NOT DELETE, WHERE MAIN HOLDS THE ONLY COPY — this phase's correction
    # of its own filing. `Q-482` proposed taking main's copies as the population and
    # unlinking them. Measured on both routes: ordinary, 2 copies -> 1, and the worktree
    # can re-collect; the `Q-470` route, 1 copy -> **0**, because the worktree has none.
    # That is `Q-478`'s class a fourth time — a documented recovery destroying the record
    # it exists to protect. The unlink's own comment states the property that makes it
    # safe (*re-collected on a later run*), and that property is FALSE wherever the
    # worktree holds no copy. So the discriminator is exactly that property: unlink only
    # when another copy survives, and otherwise LEAVE main's copy exactly where it is
    # and report it (`held`). NOTHING IS MOVED. `Q-482` briefly added a restore half
    # that moved the doc back to the worktree; its own round removed it again, because
    # `git worktree remove` — the command step (b) is running — deletes that directory's
    # gitignored content silently at exit 0, so the "safe" destination is where the only
    # copy goes to die. This comment said "MOVE ... back to the worktree" until Phase 290
    # (`Q-492`): it is the section's own header comment, so it is the first sentence an
    # editor meets, and acting on it would rebuild the exact route that round killed.
    removed, held, left, failed = [], [], [], []
    for name in sorted(names):
        dst = live / name
        # `os.path.lexists`, NOT `dst.exists()`. `exists()` FOLLOWS SYMLINKS, so a
        # DANGLING symlink in main's pending-docs reads as absent and is skipped — the
        # entry stays and this step reports `ROLLED BACK: none` at exit 0 over it.
        # Measured. Phase 284 found the identical substitution in stage 2's undo; this
        # is the same class in the half that deletes.
        if not os.path.lexists(dst):
            continue
        # Ground truth is the branch being processed. Act on main's copy ONLY when THAT
        # copy claims this branch — the copy step (a) just made. Comparing the two docs
        # to each other is what let a worktree carrying a foreign-branch doc delete
        # another branch's only surviving record.
        if (dst_b := branch_of(dst)) != branch:
            left.append(f'{name} (main copy claims {dst_b!r}, processing {branch!r}){WHY.get(dst, "")}')
            continue
        # THE UNLINK IS CONDITIONAL ON ANOTHER COPY SURVIVING, and that condition is the
        # unlink's OWN stated property (`re-collected on a later run`) rather than a new
        # rule. It is FALSE wherever the worktree holds no readable copy, so unlinking there
        # destroys the only record.
        #
        # `is_file()`, not `lexists`, and the two sides of this loop want OPPOSITE symlink
        # rules for opposite reasons. Main's entry above is tested with `lexists` because an
        # entry that is THERE must never read as absent. Here the question is whether the
        # RECORD survives, so a dangling symlink in the worktree is not a copy.
        # A COPY SURVIVES ONLY IF UNLINKING `dst` LEAVES ONE — which an ALIAS does not.
        #
        # `realpath` rather than `samefile`, because the two alias shapes must NOT be
        # treated alike: a HARDLINK is a genuine surviving copy, and `samefile` would hold
        # it too. Comparing resolved PATHS separates them: a symlink resolves onto `dst`, a
        # hardlink does not.
        # See REFERENCE.md, section Step 3b — provenance.
        _t = src_dir / name
        if not (_t.is_file() and os.path.realpath(_t) != os.path.realpath(dst)):
            # NOTHING IS MOVED, AND THAT IS THE ROUND'S FINDING, NOT AN OMISSION. An
            # earlier cut of this phase moved main's copy INTO the worktree here. That is
            # worse than the bug it replaced: `git worktree remove` — the very command
            # step (b) is trying to run — deletes a worktree's gitignored
            # `sysop/runtime/` content SILENTLY and exits 0 (§ 8.4 of `WORKFLOW.md` says
            # so; re-measured for this phase), and `claim_task.sh --release` runs it with
            # no pending-doc awareness anywhere in the script. So the move relocated the
            # only copy of a record into the one directory scheduled for deletion, and
            # `Q-482` — a REPORTING defect over a record that survived — would have
            # become a durability one. There is no safe destination, so the doc stays
            # where it is and the step says so instead of reporting success.
            held.append(name)
            continue
        try:
            dst.unlink()                              # re-collected on a later run
            removed.append(name)
        except OSError as e:
            # Previously a raw traceback at exit 1 — a code this page does not carry —
            # on the half that deletes, with NOTHING on stdout. Measured against a
            # read-only `sysop/runtime/pending-docs/`.
            failed.append(f'{name} ({e.__class__.__name__}: {e})')
    print('ROLLED BACK: ' + (', '.join(removed) or 'none'))
    print("MAIN'S ONLY COPY, LEFT IN PLACE: " + (', '.join(held) or 'none'))
    print('LEFT ALONE (not this branch\'s): ' + (', '.join(left) or 'none'))
    if held or failed:
        if failed:
            print('PENDING-DOC ROLLBACK FAILED: ' + '; '.join(failed))
        if held:
            print(f'Main holds the ONLY copy of {", ".join(held)} — the worktree has '
                  f'none, so removing it would destroy the record rather than roll back '
                  f'a copy. Left in place deliberately. Do NOT delete it by hand.')
        print(f'Main still holds a doc claiming {branch!r}, so this branch must not be '
              f'consolidated. Step 4c item 1b holds a doc whose branch content is not in '
              f'the merge target, which covers the ordinary case — but it is then the '
              f'only thing standing between that doc and BeanRider ISSUE-0050, so check '
              f'Step 8 names this branch under `Held-back docs:` before the close ends.')
        sys.exit(8)
