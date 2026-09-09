#!/usr/bin/env python3
"""backfill_completed_dates.py — fill completed_date on already-done tasks.

When a project migrates from a single-file `[x]`-style checklist (e.g.,
`product_roadmap.md`) to the hybrid `tasks/index.yml` system, tasks already
flipped to done lose their completion timestamps — the migration knows the
task is done but not when it became done. This script reconstructs the
date by grepping git history for the commit that introduced the `[x]`
marker against the task ID.

This is a one-time migration helper. After the source file is deleted and
`tasks/index.yml` becomes the source of truth, `/review-close` writes
`completed_date` directly on every close — no backfill needed.

Usage:
    # Preview only — no writes:
    python3 sysop/scripts/backfill_completed_dates.py --dry-run

    # Write inferred dates back to tasks/index.yml:
    python3 sysop/scripts/backfill_completed_dates.py

    # Custom source file (default: product_roadmap.md):
    python3 sysop/scripts/backfill_completed_dates.py --source-file ROADMAP.md

    # Custom task-ID pattern (default: project's task-prefix family,
    # extracted from index.yml so the regex matches your IDs):
    python3 sysop/scripts/backfill_completed_dates.py --id-pattern '^(FEAT|TECH|FIX)-'

Strategy:
- For each task with status=done AND no completed_date, run `git log -S`
  scoped to --source-file, searching for a string containing the task ID
  plus the `[x]` marker. The earliest commit that added the line is taken
  as the completion date.
- Two patterns are tried in order: `[x] **<TASK-ID>` (bold-form), then
  `` `<TASK-ID>` `` (backtick-form, common in `<details>` blocks).
- If git history can't find a match (rebased, predates the file, or the
  task ID never appeared inline with `[x]`), `completed_date` is left
  null and the task ID is flagged in the report.

Caveat — `git log -S <needle> -- <file>` pickaxe matches the first commit
whose diff of *that file* alters the count of the search needle (it does
not search commit messages — that would be `--grep`). The backtick-form
needle `` `<TASK-ID>` `` also appears in the source file's own
cross-references (sibling-task references, `<details>`-block mentions,
follow-up notes) that can predate the `[x]` flip, so the `--reverse` +
first-match-wins posture below can attribute the earliest *mention* of
the task rather than the earliest commit that flipped its checkbox to
`[x]`. This is acceptable for a one-time migration — the operator reviews
the report and can hand-correct outliers. If the rate of false-positives
turns out to be high, switch to the bold-form-only pattern (drop the
backtick candidate) and rerun.

Exits 0 on success even if some tasks couldn't be resolved — surfacing
remaining nulls is the operator's call. Exits 1 only on hard failures
(unreadable index, git unavailable).

Path-in-message convention: error messages reference the index file by
basename (`Path(p).name`), not the absolute path. The path is operator-
controlled (no PII) but absolute paths clutter terminals and leak the
operator's home-directory layout into shared paste-backs.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
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
            "ERROR: backfill_completed_dates.py requires PyYAML. fix: python3 -m venv .venv && "
            ".venv/bin/pip install pyyaml   (PEP-668-safe), or activate the venv.",
            file=sys.stderr,
        )
        sys.exit(2)

# Single-sourced via sysop/scripts/_log.py (Phase 68) — `sysop/scripts/` is on
# sys.path[0] when this runs directly and on pythonpath under the test suite. The name is
# bound into this module's namespace, so `backfill_completed_dates._sanitize_log`
# (the test patch path) keeps resolving.
from _log import _sanitize_log  # noqa: E402


def _unlink_quietly(path: str) -> None:
    """Best-effort removal of a temp file that never made it to `os.replace`.

    Deliberately silent: it runs on an error path that is already reporting a
    cause, and a failure to clean up must not replace that cause with its own.
    """
    try:
        os.unlink(path)
    except OSError:
        pass


def _default_index() -> Path:
    return Path.cwd() / "tasks" / "index.yml"


def find_completion_date(task_id: str, source_path: str) -> str | None:
    """Use `git log -S` against *source_path* to find the earliest commit
    that introduced an `[x]` marker for *task_id*.

    Returns ISO YYYY-MM-DD or None if no match found.
    """
    search_strings = (
        f"[x] **{task_id}",   # bold-form: `- [x] **TASK-ID** ...`
        f"`{task_id}`",        # backtick-form: `[x] \`TASK-ID\` ...`
    )
    for needle in search_strings:
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--all",
                    "--reverse",
                    "--format=%H %ad",
                    "--date=short",
                    "-S",
                    needle,
                    "--",
                    source_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except (subprocess.SubprocessError, OSError) as e:
            print(
                f"WARN: git log failed for {task_id} ({needle!r}): "
                f"{_sanitize_log(e)}",
                file=sys.stderr,
            )
            continue
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if lines:
            return lines[0].split()[1]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill completed_date via git history for done tasks "
        "whose dates weren't preserved during migration from a "
        "checklist-style roadmap to tasks/index.yml."
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Path to tasks/index.yml (default: <cwd>/tasks/index.yml).",
    )
    parser.add_argument(
        "--source-file",
        default="product_roadmap.md",
        help="Path (relative to the git repo) to the legacy roadmap file "
        "that held the `[x]` markers in git history. May already be "
        "deleted on disk — we go through git log. Default: "
        "product_roadmap.md.",
    )
    parser.add_argument(
        "--id-pattern",
        default=None,
        help="Optional regex; only tasks whose id matches this pattern "
        "are considered. Useful when your project uses a different ID "
        "family than the validator's default `^[A-Z][A-Z0-9-]{2,80}$`. "
        "Example: --id-pattern '^(FEAT|TECH|FIX)-'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed changes without writing.",
    )
    args = parser.parse_args(argv)

    index_path = args.index if args.index else _default_index()
    if not index_path.is_file():
        print(f"ERROR: index not found: {index_path.name}", file=sys.stderr)
        return 1

    try:
        with open(index_path, encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        print(f"ERROR: cannot read {index_path.name}: {_sanitize_log(e)}", file=sys.stderr)
        return 1

    # Parameterized by the --id-pattern CLI arg — cannot hoist to module scope.
    id_pattern = re.compile(args.id_pattern) if args.id_pattern else None  # nosemgrep: recompile-inside-def
    tasks = data.get("tasks") or []

    needs_backfill: list[tuple[int, dict]] = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        if t.get("status") != "done":
            continue
        if t.get("completed_date"):
            continue
        tid = t.get("id")
        if not isinstance(tid, str):
            continue
        if id_pattern and not id_pattern.search(tid):
            continue
        needs_backfill.append((i, t))

    print(f"Found {len(needs_backfill)} done task(s) without completed_date.")
    if not needs_backfill:
        return 0

    updated = 0
    skipped = 0
    for i, task in needs_backfill:
        tid = task["id"]
        date = find_completion_date(tid, args.source_file)
        if date:
            print(f"  {tid}: {date}")
            data["tasks"][i]["completed_date"] = date
            updated += 1
        else:
            print(f"  {tid}: no match in git history for {args.source_file} (leaving null)")
            skipped += 1

    print(f"\nUpdated: {updated}. Skipped (no match): {skipped}.")

    if args.dry_run:
        print("--dry-run: not writing.")
        return 0

    # Atomic rewrite via `mkstemp` + `os.replace` so a crash mid-write cannot
    # leave truncated YAML — `tasks/index.yml` is load-bearing for
    # `/next-task`, `/claim-task`, `/review-close`. See CLAUDE.md
    # § Data integrity and the sibling `_atomic_write_text` in
    # archive_review_tasks.py.
    #
    # `mkstemp` rather than a fixed `<path>.tmp` (`Q-442`): this was the last
    # writer of `tasks/index.yml` deriving its temp name from its target, so two
    # concurrent writers could collide on one temp path. It is operator-invoked
    # rather than on a claim or close path, which lowered the exposure without
    # changing the class. The four elements below are the shape the converted
    # siblings already carry (`/claim-task` Step 4a, `/auto-build` Step 5.1,
    # `claim_task.sh`, `/review-close` Step 4c, `clear_user_action.py`). THREE of
    # them answer a defect the conversion would otherwise INTRODUCE; the first
    # fixes one that was already here:
    #   - `realpath` so a symlinked index is written THROUGH rather than having
    #     the link itself replaced (Phase 237's round). PRE-EXISTING — the
    #     fixed-name form had the same exposure, so this is a fix the conversion
    #     carries along rather than one it owes.
    #   - the mode carried across, because `mkstemp` creates 0600 and a plain
    #     conversion silently narrows a 0644 index — which git does not track,
    #     so nothing downstream would have surfaced it (Phase 237's round).
    #   - `dir=` the target's own directory, which is what keeps the replace
    #     SAME-FILESYSTEM; a tmp in the system temp dir makes `os.replace` raise
    #     `EXDEV`. That was the stated reason the fixed-name form was pinned in
    #     place, and `dir=` answers it directly.
    #   - a non-`OSError` cleanup arm. Under the fixed name a leaked tmp
    #     self-healed, because the next run wrote the same path; under `mkstemp`
    #     every failed run would leak a NEW uniquely-named file into `tasks/`.
    #     `except OSError` alone does not reach a `yaml` representer error.
    #
    # Belt-and-braces durability, kept from the pre-conversion form: `os.fsync`
    # on the file fd flushes the data; an `os.fsync` on the parent dir fd
    # flushes the rename itself so the post-crash directory entry points at the
    # new inode rather than the old one.
    real = os.path.realpath(index_path)
    try:
        mode = os.stat(real).st_mode & 0o7777
    except OSError:
        mode = 0o644
    # `mkstemp` INSIDE the try, and its own arm, because it is the most likely
    # place an OSError arises on this path — a read-only `tasks/`, a full disk, a
    # bad permission. The first cut left it outside, which made the sanitized
    # `ERROR: cannot write …` + `return 1` contract below UNREACHABLE for exactly
    # that case: measured against a 0555 `tasks/`, the pre-fix script printed the
    # sanitized line and this one printed a raw `PermissionError` traceback. A
    # separate arm because there is no `tmp_path` to clean up yet.
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(real), prefix=os.path.basename(real) + ".", suffix=".tmp"
        )
    except OSError as e:
        print(f"ERROR: cannot write {index_path.name}: {_sanitize_log(e)}", file=sys.stderr)
        return 1
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as f:
            yaml.safe_dump(
                data,
                f,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
                width=120,
            )
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, real)
        dir_fd = os.open(os.path.dirname(real), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as e:
        _unlink_quietly(tmp_path)
        print(f"ERROR: cannot write {index_path.name}: {_sanitize_log(e)}", file=sys.stderr)
        return 1
    except BaseException:
        # Not swallowed — re-raised after cleanup, so `KeyboardInterrupt` still
        # interrupts. Present only so a non-`OSError` failure does not leak a
        # uniquely-named tmp that no later run will overwrite.
        _unlink_quietly(tmp_path)
        raise
    print(f"Wrote {index_path.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
