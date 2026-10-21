#!/usr/bin/env python3
"""close_index.py — `/review-close` Step 4c item 4: close the merged tasks in `tasks/index.yml`.

    python3 sysop/scripts/close_index.py [--keep-locks] [<roadmap id> ...]

Run from the main checkout's top level. Sets `status: done` and `completed_date` on each
id given (step 1c's ROUTE: docs' `roadmap_ids`), moves each body under `archive/`, stages the index,
then removes the closed claims' locks, park markers and claim artifacts
(`--keep-locks`, under `--request-review`, leaves the locks). Prints one report row per
outcome (`CLOSED_IDS:`, `HELD_USER_ACTION:`, ...).

The skill text is the contract: `/review-close` Step 4c item 4 says what each row and a
non-zero exit mean. This file was that step's heredoc until Phase 386 (`Q-409` P3),
moved verbatim except one change: the runner used to edit a literal id list in the
program, and the ids are now arguments.
"""
import datetime, os, re, shutil, subprocess, sys, tempfile
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
from pathlib import Path
today = datetime.date.today().isoformat()
# The roadmap_ids of step 1c's ROUTE: docs only, never a HELD: one (with the Phase 23a
# compat shim applied at parse time — see step 3 above), one argument each, after an
# optional `--keep-locks`. review_task_ids are NOT processed here — they're documentary
# only. Until Phase 386 the runner edited a literal list in this program; a shipped
# script takes them as arguments, and refuses one that is not an id before any write.
_args = sys.argv[1:]
KEEP_LOCKS = _args[:1] == ['--keep-locks']
ids = _args[1:] if KEEP_LOCKS else _args
_bad = [i for i in ids if not i.strip() or i.startswith('-') or '<' in i or '>' in i]
if _bad:
    sys.exit(f"ERROR: not a task id: {_bad!r}. Pass step 1c's ROUTE: docs' roadmap_ids, "
             "one argument each, after an optional --keep-locks; nothing was changed")
p = Path('tasks/index.yml')
try:
    d = yaml.safe_load(p.read_text(encoding='utf-8'))
except Exception as e:
    sys.exit(f"ERROR: tasks/index.yml could not be read ({type(e).__name__}: {e}); nothing was changed")
closed = []
held = []
# DEFENCE IN DEPTH for a doc's own `hold:` (`Q-625`), as the `user_action` arm below is
# for that flag: an id named by a pending doc that still carries `hold:` is not closed,
# whatever the argument list says. Truthy, as step 1c reads it.
held_doc, doc_held = [], set()
for _pd in sorted(Path('sysop/runtime/pending-docs').glob('*.md')):
    if _pd.name == 'convention-candidates.md':
        continue
    try:
        _m = re.match(r'\ufeff?---\n(.*?)\n---',
                      _pd.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n'),
                      re.DOTALL)
        _fm = yaml.safe_load(_m.group(1)) if _m else None
    except Exception:
        continue
    if isinstance(_fm, dict) and _fm.get('hold'):
        _v = _fm.get('roadmap_ids') or _fm.get('task_ids') or []
        doc_held.update([_v] if isinstance(_v, str) else
                        [str(x) for x in _v] if isinstance(_v, (list, tuple)) else [str(_v)])
for t in d.get('tasks', []):
    if t['id'] not in ids:
        continue
    if t['id'] in doc_held:
        held_doc.append(t['id'])
        continue
    # HOLD a task whose human step is still outstanding (`Q-327`). `user_action` is
    # Sysop's OWN schema field — validate_tasks.py requires it as a bool on every
    # open/in_progress task — and until Phase 241 this round-trip never read it, so a
    # merged diff alone flipped the task to `done`. Nothing upstream is a backstop:
    # Step 3c's smoke gate deliberately excludes `## User ops` from its phrase set,
    # and its waive outcome does not halt, so a waived smoke and a passed smoke are
    # indistinguishable here. `tasks/schema.md` § User ops already conceded this in
    # prose ("Nothing verifies the steps were performed"); this is the one step that
    # writes the durable state, so it is where the concession gets closed.
    # THIS IS DEFENCE IN DEPTH, not the primary gate. Step 1c above holds the
    # whole pending-doc back before any routing happens, so on the ordinary path
    # a held task's ids never reach this loop at all. This arm exists because
    # `ids` are arguments the runner writes out by HAND: 1c can be skipped or
    # mis-read, and the list can be pasted from a previous run.
    # If a held id does arrive here, the flip must still not happen.
    # What is withheld: the status flip, the body archive move, and the
    # lock/parked-marker/claim-artifact cleanup below — all keyed on `closed`,
    # so keeping a held id OUT of that list is what withholds them.
    # NOTE the ordering consequence, because it is not obvious: reaching this arm
    # means the doc WAS routed, so its PROJECT_STATUS/CHANGELOG entries have
    # landed for a task that did not close, and the doc is about to be deleted by
    # step 6 — the stranding Step 1c exists to prevent. Report it loudly at
    # Step 8 and fix the id list; a hold HERE is an anomaly, not the normal case.
    # NOT a contradiction of clear_user_action.py (Phase 237): that clears the flag
    # EARLY so a task rejoins the frontier, and its docstring explicitly declines the
    # close path. Clearing is the human saying "done"; this is the close path
    # declining to say it on their behalf.
    # Truthiness, deliberately, NOT `is True`. `validate_tasks.py` requires a
    # bool, but that validator runs at the END of this step, so a malformed
    # index reaches here first. Measured across eight values: a bare `true`
    # holds; `false`, a missing key and an explicit `null` all close (which is
    # what a task predating the field needs); and a non-bool truthy value such
    # as the STRING `"false"` also holds. That last one is wrong-looking and is
    # the SAFE direction — holding a task that should have closed costs one
    # `clear_user_action.py`; closing one that should have held is the defect
    # this hold exists to remove. Do not tighten this to `is True`: a string
    # `"true"` would then CLOSE a task whose human step is outstanding, which
    # inverts the bias on exactly the malformed input the strictness was for.
    if t.get('user_action'):
        held.append(t['id'])
        continue
    t['status'] = 'done'
    t['completed_date'] = today
    closed.append(t['id'])
    body = t.get('body', '')
    if not body:
        continue  # no body to move (archive_summary case)
    parts = body.split('/')
    # Locate the path segment matching the task's pre-transition status
    # directory. Generalizes over open/ and deferred/ — a task may complete
    # from either. Skips bodies that live at the root of tasks/ (no swap
    # target). The segment-based match is prefix-agnostic: it works whether
    # body is stored as "open/X.md" or "tasks/open/X.md".
    swap_idx = next((i for i, seg in enumerate(parts) if seg in ('open', 'deferred')), None)
    if swap_idx is None:
        continue
    new_parts = list(parts)
    new_parts[swap_idx] = 'archive'
    new_body = '/'.join(new_parts)
    src = body if body.startswith('tasks/') else f'tasks/{body}'
    dst = new_body if new_body.startswith('tasks/') else f'tasks/{new_body}'
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'mv', src, dst], check=True)
    # Re-stage the moved body. `git mv` stages the rename of the COMMITTED content;
    # a modification made to the body earlier in this close is left unstaged, so the
    # commit would archive the pre-edit text. Staging `dst` (never `src` — the stale
    # pre-rename pathspec aborts the whole invocation) is the only thing that picks it
    # up. Step 7's post-commit gate catches the miss, so the cost of omitting this is
    # an amend rather than a loss — but the state should not be created.
    subprocess.run(['git', 'add', dst], check=True)
    t['body'] = new_body
# Only write when something actually closed. With `closed` empty, `d` is unchanged, and
# writing it anyway would reserialize the whole index (stripping comments and formatting)
# and stage that diff under the consolidation subject — on a run whose pending-docs
# carried no roadmap_ids, where Step 7 correctly expects tasks/index.yml to be ABSENT
# from the commit.
if closed:
    # Atomic rewrite (Phase 201). `p.write_text` truncates in place, so an interrupted
    # write leaves a half-written index — the one file carrying every task's status.
    # `backfill_completed_dates.py` has used tempfile + os.replace since Phase 108 and is
    # the shape copied here. Phase 261 converted claim-task Step 4a and
    # claim_task.sh --release (and gave --commit-claim the same shape when it added
    # it); Phase 263 converted auto-build Step 5.1, which was the last one, so NO
    # writer of tasks/index.yml truncates in place via open(..., "w") any more.
    # What `Q-404` still has open is the MUTEX, not atomicity: this site,
    # backfill_completed_dates.py and clear_user_action.py all write without it; this
    # site was done first because it is the one that has already `git mv`d the bodies, so
    # a torn write there strands staged renames against an index that never recorded them.
    # Same directory, so the replace is atomic and no reader sees a partial file.
    # Scope, stated because the sibling is copied only in part: this takes the
    # tempfile + os.replace half, NOT its fsync pair — process-level interruption is
    # covered, machine-level (power loss) is not. The failure arm IS copied: a
    # surviving .tmp would sit untracked beside a tracked path for the rest of the
    # close, which is the residue hazard Step 2b names. Two properties `write_text`
    # had for free and `os.replace` does not are restored explicitly: it writes
    # THROUGH a symlink rather than replacing it, and it keeps the old file's mode.
    #
    # `mkstemp` rather than a fixed `<path>.tmp` (`Q-414`, Phase 269, finishing
    # `Q-382`'s job). It is the last of the four SKILL/claim-path writers to convert:
    # /claim-task Step 4a, /auto-build Step 5.1, and claim_task.sh's --release and
    # --commit-claim all use mkstemp precisely so two concurrent writers cannot
    # collide on the temp NAME — a collision that survives os.replace's atomicity,
    # because the losing writer's replace still runs.
    #
    # NOT the last writer of this file, and an earlier draft of this comment said it
    # was — corrected by a review lens in the same phase. `backfill_completed_dates.py`
    # still derives `<path>.tmp` from the target (`Q-442`), and the roster three lines
    # above names it. The falsehood sat six lines from its own counter-evidence, which
    # is the same shape Phase 263 fixed here when the roster called Step 5.1 last.
    # Exposure here is lower than the claim paths' (once per close, not once per
    # claim, so it needs two closes overlapping), which is why this one was last,
    # not why it was exempt.
    #
    # `dir=os.path.dirname(real)` is what keeps the replace SAME-FILESYSTEM. That
    # was the stated reason the old fixed-name form was pinned in place — a tmp in
    # the system temp dir makes os.replace raise EXDEV — and `dir=` answers it
    # directly, so the property is preserved rather than traded away.
    real = os.path.realpath(p)
    mode = os.stat(real).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real),
                               prefix=os.path.basename(real) + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            yaml.safe_dump(d, f, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120)
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    # Stage the rewrite here, in the same code that performed it. `git mv` above staged
    # each body rename (and the loop re-adds the moved path, because `git mv` stages only
    # the COMMITTED content — see there), but `Path.write_text` does not stage
    # anything — so without this line the index is left HALF staged, and Step 7's
    # `git commit` would record the renames while silently dropping the `status: done`
    # + `completed_date` flip under a subject claiming the consolidation happened
    # (internal tracker #203). Staging beside the write is the only form that cannot drift out
    # of sync with what was written.
    subprocess.run(['git', 'add', str(p)], check=True)
# Working-tree cleanup, deferred until every git mv landed and the index wrote:
# an abort mid-loop must not have already destroyed an earlier task's records
# (the parked marker below is unrecreatable — plan + verdict, never committed).
# Keyed on the task id, not the body shape, so archive_summary and flat-layout
# closes — which `continue` past the move above — are still cleaned up.
locks_removed, locks_absent, markers_removed = [], [], []
locks_kept = []
artifacts_removed, artifacts_failed = [], []
for tid in closed:
    # Drop the per-task lock file (BeanRider ISSUE-0035). The lock's lifecycle
    # is open → in_progress (claim_task --lock creates it) → done (here). Leaving
    # it behind clutters sysop/runtime/locks/ and confuses the "is anyone working on this?"
    # signal. `sysop/runtime/locks/` is .gitignored, so this is a working-tree-only operation
    # — no stage, no commit. `missing_ok=True` tolerates pre-Phase-32 tasks
    # whose locks already got cleaned up by hand.
    lock = Path(f'sysop/runtime/locks/{tid}.lock')
    # Record existence BEFORE the unlink. `missing_ok=True` is deliberate (see the
    # pre-Phase-32 note above) but it DISCARDS the one fact Step 8's `Locks cleaned:`
    # row asks for, so a list assembled afterwards would name tasks whose lock was
    # already gone. Removed and already-absent are reported as separate sets.
    # `exists()` alone follows symlinks, so a DANGLING lock symlink reports
    # 'already absent' while the unlink below really does remove it — a row
    # that claims to report what this code did, reporting the opposite.
    if KEEP_LOCKS:
        (locks_kept if (lock.exists() or lock.is_symlink()) else locks_absent).append(tid)
    else:
        (locks_removed if (lock.exists() or lock.is_symlink()) else locks_absent).append(tid)
        lock.unlink(missing_ok=True)
    # Also drop any parked marker(s) for the task. /auto-build Phase 6d mirrors a
    # parked task's plan + verdict to the durable project-root archive
    # sysop/runtime/parked/<TASK_ID>__<TS>.md; the close path historically
    # never removed them, so markers for done tasks accumulated — the parked/ dir a
    # human lists when hunting resumable work over-reports a done task as still
    # parked. Same timing + working-tree-only semantics as the lock above (see the
    # `pr`-policy invariant note in Step 6 for why pre-merge death is accepted).
    # A task that never parked has no markers, and Path.glob on a missing parked/
    # dir yields nothing — both no-op cleanly.
    for marker in Path('sysop/runtime/parked').glob(f'{tid}__*.md'):
        markers_removed.append(marker.name)
        marker.unlink(missing_ok=True)
    # And the orchestrated-claim artifact set. Since Phase 171 /claim-task writes
    # sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/ (plan.md, review.md, classification.md,
    # ...) into the MAIN checkout so it outlives `git worktree remove` — and until
    # Phase 236 NOTHING removed it, for either claim kind, so it grew one directory
    # per run of every claim ever made. This is the roadmap half; the batch half is
    # `close_batch.sh`'s remove_claim_artifacts(), because `closed` is built from
    # `roadmap_ids` only and no batch id can reach this loop.
    #
    # `tid` comes from the id list this step parsed, so it is not free text — but
    # this is the one `rm -rf`-shaped operation in the close path, so it is guarded
    # rather than trusted: a `tid` that ever contained a separator or `..` would walk
    # the delete out of sysop/runtime/claim/ entirely. Resolve and re-check
    # containment before removing anything.
    claim_root = Path('sysop/runtime/claim')
    claim_dir = claim_root / tid
    try:
        inside = claim_dir.resolve().parent == claim_root.resolve()
    except OSError:
        inside = False
    if not inside:
        pass
    elif claim_dir.is_symlink():
        # Remove the LINK, never what it points at — the target may be anything.
        try:
            claim_dir.unlink(missing_ok=True)
            artifacts_removed.append(tid)
        except OSError as e:
            artifacts_failed.append(f'{tid} ({e.__class__.__name__})')
    elif claim_dir.is_dir():
        # NEVER let this raise. This loop's own contract, stated at its head, is that
        # an abort mid-loop must not have already destroyed an earlier task's records —
        # and every other operation here is non-raising by construction
        # (`unlink(missing_ok=True)`, `glob`). `shutil.rmtree` over a user tree is the
        # first that realistically raises. Record the failure and keep going; a
        # leftover directory under a gitignored path is a tidy-up, a half-done close
        # is not.
        # See REFERENCE.md, section Step 4c — provenance.
        try:
            shutil.rmtree(claim_dir)
            artifacts_removed.append(tid)
        except OSError as e:
            artifacts_failed.append(f'{tid} ({e.__class__.__name__})')
    elif claim_dir.exists():
        # A regular file where a directory belongs. Neither arm above owns it, and
        # silently printing "never ran the pipeline" would state a specific, false
        # cause. Say what was actually found.
        artifacts_failed.append(f'{tid} (not a directory)')
# Report what this code DID. Two of these values are not derivable after the fact at
# all: `missing_ok=True` erases the lock distinction, and the markers are gone once
# unlinked.
#
# `NOT_IN_INDEX` exists because `closed` is a strict SUBSET of `ids`: the loop above
# skips any id with no matching `tasks/index.yml` entry, silently. Reporting `ids`
# would over-claim; reporting `closed` alone would hide the drop. Both, or neither.
# See REFERENCE.md, section Step 4c — provenance.
print('CLOSED_IDS: ' + (' '.join(closed) or '(none)'))
# `held` is subtracted here as well as `closed`. A held task IS in the index — that is
# how its `user_action` was read — so scoring it `NOT_IN_INDEX` would report a task
# that exists as one that does not, and send the operator looking for a missing entry
# instead of an outstanding human step. `closed`, `held` and NOT_IN_INDEX partition
# `ids`; no id may appear in two rows or in none.
print('HELD_USER_ACTION: ' + (' '.join(held) or '(none)'))
print('HELD_BY_HOLD: ' + (' '.join(held_doc) or '(none)'))
print('NOT_IN_INDEX: ' + (' '.join(t for t in ids if t not in closed and t not in held
                                    and t not in held_doc) or '(none)'))
print('LOCKS_REMOVED: ' + (' '.join(locks_removed) or '(none)'))
if KEEP_LOCKS:
    print('LOCKS_KEPT: ' + (' '.join(locks_kept) or '(none)'))
print('LOCKS_ALREADY_ABSENT: ' + (' '.join(locks_absent) or '(none)'))
print('PARKED_MARKERS_REMOVED: ' + (' '.join(sorted(markers_removed)) or '(none)'))
print('CLAIM_ARTIFACTS_REMOVED: ' + (' '.join(sorted(artifacts_removed)) or '(none)'))
print('CLAIM_ARTIFACTS_FAILED: ' + (' '.join(sorted(artifacts_failed)) or '(none)'))
