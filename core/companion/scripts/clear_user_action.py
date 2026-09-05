#!/usr/bin/env python3
"""clear_user_action.py — mark a task's human-only step as done.

`user_action: true` declares that some step of a task is human-only — a console,
a credential, a domain, private knowledge (`tasks/schema.md` § User ops). It
gates **dispatch**: all three automated frontier filters exclude the task, so it
is never picked up by an agent.

**Until Phase 237 nothing ever cleared it.** No shipped writer touched the
field, so once the human had supplied the credential the task was fully
agent-executable and yet stayed out of `/auto-build`'s frontier, out of
`next_task.py`'s agent pool, and 🔒 in `/roadmap` — permanently. Meanwhile
`roadmap/SKILL.md`'s unblock-the-human-first ordering promised that "clearing it
early converts a serial stall into parallel progress", and nothing implemented a
clearing. The only escape was hand-editing the field, which the tree never
instructed. This script is that clearing, given a name.

**Why one field and not two.** A `user_action_done:` companion would encode one
fact in two booleans that must be kept in sync forever, and `user_action` is a
*step* property rather than a task property (`tasks/schema.md` § User ops): the
rubric's own list includes steps that are not prerequisites at all — a go/no-go
at a rollout boundary, a done-except-for-sign-off pairing — for which "done" is
not even well defined. Clearing the one field says exactly what happened: this
task no longer needs a human before an agent can take it.

**Why not at `/review-close`.** Close runs *after* the work, and the promise this
repairs is about clearing *early* so the rest of the queue parallelises. For the
ordinary prerequisite case, waiting for close would be circular.

**The `## User ops` record stays.** Clearing the flag does not delete the section
describing what the human did — `tasks/schema.md` was amended in the same phase
so the section is no longer scoped "present only when `user_action: true`". The
record of a performed step is worth more after it is performed, not less.

**It round-trips the index through PyYAML**, which reformats the whole file
(list indentation in particular). That is not new: `claim_task.sh --release`
already does exactly this to the same file, with the same dump kwargs. This is
the **sixth** whole-file writer of `tasks/index.yml` (the others: `/claim-task`
Step 4a, `/auto-build` Step 5.1, `/review-close` Step 4c, `claim_task.sh
--release`, `backfill_completed_dates.py`), and `tests/test_index_writer_class.py`
has pinned the canonical kwargs across all of them since Phase 201. On a queue
that has never had a claim released, expect the first run to produce a large
diff.

Never commits. Like `claim_task.sh`, it mutates and hands you the commit.

Usage:
    python3 sysop/scripts/clear_user_action.py <TASK_ID>
    python3 sysop/scripts/clear_user_action.py --dry-run <TASK_ID>
"""

from __future__ import annotations

import argparse
import glob
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    # PyYAML lives only in the project venv on PEP-668 hosts (BeanRider
    # ISSUE-0049; internal tracker #321), so resolve it onto sys.path before giving up
    # — that keeps a bare `python3 sysop/scripts/…` working, which is what the
    # skills prescribe and settings.json allow-rules are written against.
    # It PROBES rather than assuming: a candidate is committed to sys.path only
    # once `import yaml` actually succeeds from it, and is rolled back
    # otherwise. The first draft stopped at the first venv-SHAPED directory, so
    # one empty `.venv` disabled the whole search — including the main-checkout
    # arm below, which is the entire point of it — and a `.venv` shadowed a
    # sibling `venv` that did have PyYAML. That was the shell helper's design
    # (`claim_task.sh:resolve_yaml_python`) stated in this phase's own log and
    # not honoured here; the round caught it by running it.
    #
    # Order is script-anchored FIRST — this file's ancestors, then the MAIN
    # checkout via git-common-dir (a linked worktree carries the scripts but
    # never a `.venv`, and worktrees are where /claim-task builds) — and only
    # then the CWD. CWD-first let an unrelated project's venv win whenever a
    # script was invoked by path from elsewhere. Both `.venv/` and `venv/`
    # layouts, at every root.
    #
    # The git probe strips git's discovery vars for the reason
    # `tests/test_git_env_hermeticity.py` exists (BeanRider ISSUE-0048): git
    # exports `GIT_DIR` into every hook, and these scripts run from pre-commit. Inline by necessity rather than by accident: it must run before
    # any import can be trusted, and validate_tasks.py + next_task.py are
    # deliberately standalone for pre-commit (see _log.py's header).
    # tests/test_venv_pyyaml_bootstrap.py pins the five copies identical.
    _roots = []
    # `list(...)` before the slice: slicing `PurePath.parents` is 3.10+
    # (bpo-35498), and on 3.9 it raises TypeError from inside this very
    # `except ImportError` — the interpreter the block exists to rescue.
    for _cand in list(Path(__file__).resolve().parents)[:3]:
        if _cand not in _roots:
            _roots.append(_cand)
    try:
        _r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=5,
            env={_k: _v for _k, _v in os.environ.items()
                 if _k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                               "GIT_INDEX_FILE")},
        )
        if _r.returncode == 0 and _r.stdout.strip():
            _main = (Path(__file__).resolve().parent / _r.stdout.strip()).resolve().parent
            if _main not in _roots:
                _roots.append(_main)
    except (OSError, subprocess.SubprocessError):
        pass
    if Path.cwd() not in _roots:
        _roots.append(Path.cwd())
    _hit = False
    for _root in _roots:
        for _layout in (".venv", "venv"):
            for _site in glob.glob(str(_root / _layout / "lib/python*/site-packages")):
                sys.path.insert(0, _site)
                try:
                    import yaml
                except ImportError:
                    sys.path.remove(_site)
                    continue
                _hit = True
                break
            if _hit:
                break
        if _hit:
            break
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: clear_user_action.py requires PyYAML. fix: python3 -m venv .venv && "
            ".venv/bin/pip install pyyaml   (PEP-668-safe), or activate the venv.",
            file=sys.stderr,
        )
        sys.exit(2)




def main_repo_root() -> Path:
    """The MAIN checkout, resolved through git-common-dir.

    `tasks/index.yml` is tracked, so a worktree has its own copy — but the flip
    is committed on `main`, and every other writer of this file (`claim_task.sh`)
    resolves the same way. Two writers disagreeing about which copy is canonical
    is how a flip lands on a feature branch and is lost at merge.
    """
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        print("ERROR: not inside a git repository.", file=sys.stderr)
        sys.exit(1)
    p = Path(out.stdout.strip())
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return p.parent


def _write_atomically(path: Path, data: dict) -> None:
    """Rewrite via tempfile + os.replace.

    Dump kwargs are IDENTICAL to `claim_task.sh --release`'s flip block on
    purpose: two writers of one file with different kwargs reformat it
    differently, and every such reformat shows up as a spurious diff on someone
    else's branch.
    """
    # **Resolve symlinks and preserve the mode.** `os.replace` onto a SYMLINK
    # replaces the link itself, leaving the canonical file untouched while this
    # script reports success — and `mkstemp` creates 0600, so a plain rewrite
    # silently narrowed a 0644 `tasks/index.yml` to 0600, which git does not
    # track and nothing would have surfaced. Both were found by Phase 237's round,
    # which ran two writers side by side: `claim_task.sh --release` wrote through
    # `open(path, "w")` at the time and so had neither problem. Phase 261 converted
    # it to this same mkstemp shape, so it now carries both fixes too — the older
    # sentence claiming it still writes in place outlived the conversion by two
    # phases with nothing pinning it (`Q-404`).
    path = path.resolve()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        os.chmod(tmp, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
                width=120,
            )
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(task_id: str, dry_run: bool = False, root: Path | None = None) -> int:
    root = root or main_repo_root()
    index_path = root / "tasks" / "index.yml"
    if not index_path.is_file():
        print(f"ERROR: no task index at {index_path}", file=sys.stderr)
        return 1

    with open(index_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        print(f"ERROR: {index_path} does not parse as a mapping "
              f"(got {type(data).__name__}) — not a task index.", file=sys.stderr)
        return 1
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        print(f"ERROR: {index_path} has a `tasks:` key that is not a list "
              f"(got {type(tasks).__name__}).", file=sys.stderr)
        return 1
    hits = [t for t in tasks if isinstance(t, dict) and t.get("id") == task_id]
    if len(hits) > 1:
        # Flipping the first and leaving the rest would report success while
        # half the queue still reads `user_action: true`. The index is invalid;
        # say so rather than picking one.
        print(f"ERROR: {task_id} appears {len(hits)} times in {index_path} — "
              f"duplicate ids. Fix the index; nothing was changed.",
              file=sys.stderr)
        return 3
    match = hits[0] if hits else None

    if match is None:
        print(f"ERROR: {task_id} is not in {index_path}", file=sys.stderr)
        return 2

    current = match.get("user_action")
    if current is not True:
        # Not an error. Re-running after a successful clear is the ordinary way
        # a human checks, and a script that fails on its own settled state
        # teaches people to ignore its exit code.
        shown = "absent" if "user_action" not in match else repr(current)
        print(
            f"ℹ️  {task_id} does not carry `user_action: true` ({shown}) — "
            f"nothing to clear."
        )
        return 0

    status = match.get("status", "?")
    if dry_run:
        print(
            f"DRY RUN: would set {task_id} user_action: true → false "
            f"(status: {status}). Nothing written."
        )
        return 0

    match["user_action"] = False
    try:
        _write_atomically(index_path, data)
    except OSError as exc:
        print(f"ERROR: could not rewrite {index_path}: "
              f"{exc.__class__.__name__}: {exc}. Nothing was changed.",
              file=sys.stderr)
        return 1

    print(f"✅ {task_id}: user_action true → false (status: {status}).")
    print(
        "   The `## User ops` section in the task body is deliberately left in "
        "place — it is the record of the step you performed."
    )
    if status == "open":
        print(
            "   The task is now on the agent-executable frontier: /auto-build, "
            "/next-task and /roadmap will all offer it."
        )
    else:
        print(
            f"   Note: status is `{status}`, so the automated frontier "
            f"(which selects `open` tasks) still will not pick it up."
        )

    validator = root / "sysop" / "scripts" / "validate_tasks.py"
    if validator.is_file():
        # Flush first: through a pipe our buffered prints would otherwise land
        # AFTER the subprocess's unbuffered output, so the validator appears to
        # report on a flip that had not been announced yet.
        sys.stdout.flush()
        rc = subprocess.run(
            [sys.executable, str(validator)], cwd=str(root)
        ).returncode
        print("✅ Queue validates." if rc == 0 else
              "⚠️  validate_tasks.py reported issues (see above).")

    print("")
    print("📝 Next step — commit it (this script never commits for you):")
    print(f"   cd {root}")
    print(f"   git add tasks/index.yml && git commit -m \"chore: {task_id} user ops done\"")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clear_user_action.py",
        description="Clear a task's `user_action` flag once the human step is done.",
    )
    p.add_argument("task_id", help="the task ID, e.g. TECH-0004")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args.task_id, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
