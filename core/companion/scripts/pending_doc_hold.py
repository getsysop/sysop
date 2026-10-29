#!/usr/bin/env python3
"""pending_doc_hold.py — the hold on a pending doc: test it, stamp it, clear it.

`/review-close` Step 4c 1c refuses to route a pending doc whose deliverable is
not finished, so the task it names is not flipped to `done`. Two things hold a
doc, and either is enough:

* **`hold: "<reason>"` in the doc's own frontmatter** (`Q-625`, Phase 353).
  `/document-work` writes it when the merge does not finish the task: a step
  outside the branch must still happen before the task may close. `clear` below
  is the command that removes it; no step of the close path does.
* **A truthy `user_action` on a task the doc names** (`Q-327`, Phase 241).

`user_action` alone was the hold until Phase 353, and it carries a second
meaning: `/roadmap`, `/next-task` and `/auto-build` read it as *a human must act
before an agent can take this task*. A flag cleared for that reason silently
disarmed the close-path hold on an unfinished deliverable, three times in one
consumer. `hold:` is the field that means only *do not close this yet*.

Subcommands:

    check [--stamp]
        One line per pending doc in the main checkout's
        `sysop/runtime/pending-docs/`: `HELD:` with its reasons, `ROUTE:`, or
        `UNREADABLE:`. A hold is per task: a doc naming an id a held doc names
        is held too. With `--stamp`, each held doc whose branch is merged into
        `HEAD` (or into a recorded PR head) and that carries no `held_since:`
        gets `held_since: '<today>'` as its first frontmatter line; `guard`
        reads it to keep the doc from being replaced. Exits 1, stamping nothing, when
        `tasks/index.yml` exists and cannot be read, because then no doc's hold
        can be decided.

    guard <PATH>
        `/document-work`'s step before it writes the pending doc PATH names.
        Prints `WRITE: <path>`, the file to write. That is PATH unless a close is
        holding it (it carries `held_since:`); then it is the existing unstamped
        `<stem>--<n>.md` beside it, or a new one, so the held doc, the only
        carrier of its tasks into a later close, is never replaced. An unstamped
        doc is rewritten: that is the ordinary re-stamp of a doc no close has
        held yet. Also prints one
        `CARRY HOLD: <reason>` line when the main checkout's same-named copy of
        this doc carries `hold:` and PATH is in another linked checkout: Step 3b's
        collect would replace that copy, so the new doc must carry the hold. A
        `--clone` workspace is its own repository and gets no such line; the
        collect's refusal names the hold instead. Exits 1 when a candidate file
        exists and cannot be read. Its protection rests on the stamp: a held doc
        that `--stamp` could not stamp is not protected.

    clear <TARGET> [--dry-run]
        Remove `hold:` from every pending doc TARGET names: a task id in its
        `roadmap_ids` (or legacy `task_ids`), its `branch:`, or its file name.
        Never touches `tasks/index.yml`, and never commits: pending docs are
        untracked. A doc that is also held on `user_action` stays held, and the
        output says so.

The edit rewrites only the one key and re-parses the result to prove every
other key is unchanged, the way `/review-close` Step 3c's answer recorder does.
It refuses rather than guess.
"""

from __future__ import annotations

import argparse
import datetime
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
    # ISSUE-0049; internal tracker #321). Same probe as clear_user_action.py:
    # script-anchored roots, then the main checkout via git-common-dir, then
    # the CWD; commit a candidate only once `import yaml` succeeds from it.
    # tests/test_venv_pyyaml_bootstrap.py pins the copies identical.
    _roots = []
    # `list(...)` before the slice: slicing `PurePath.parents` is 3.10+.
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
            "ERROR: pending_doc_hold.py requires PyYAML. fix: python3 -m venv .venv && "
            ".venv/bin/pip install pyyaml   (PEP-668-safe), or activate the venv.",
            file=sys.stderr,
        )
        sys.exit(2)


FM_RE = re.compile(r"^\ufeff?---\n(.*?)\n---", re.DOTALL)
PENDING = Path("sysop") / "runtime" / "pending-docs"
#: A fixed-name file the review skills own; not a branch pending doc.
NOT_A_BRANCH_DOC = {"convention-candidates.md"}


def main_repo_root() -> Path:
    """The MAIN checkout, resolved through git-common-dir.

    Pending docs that a close holds live in the main checkout, and a human may
    run `clear` from a linked worktree.
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


def doc_hold(fm: dict) -> str:
    """The doc's own `hold:` reason, or "".

    Truthy, the way 1c reads `user_action`: a malformed value such as the
    string "false" HOLDS, because holding a doc that should have closed costs
    one `clear`, and closing one that should have held writes a false `done`.
    """
    v = fm.get("hold")
    if not v:
        return ""
    return str(v).strip() or "(no reason given)"


def doc_ids(fm: dict) -> list[str]:
    """`roadmap_ids`, falling back to `task_ids` (the Phase 23a compat shim).

    A scalar is one id: iterating `roadmap_ids: T-1` would walk its characters.
    """
    v = fm.get("roadmap_ids") or fm.get("task_ids")
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None and str(x).strip()]
    return [str(v)]


class Doc:
    def __init__(self, path: Path):
        self.path = path
        self.error = ""
        self.raw = ""
        self.fm: dict = {}
        self.has_fm = False
        self.utf8 = True
        try:
            data = path.read_bytes()
        except OSError as exc:
            self.error = f"{exc.__class__.__name__}: {exc}"
            return
        # Decoded as Step 3c and Step 4c decode it (`errors="replace"`): they parse a doc
        # with a stray byte and route it, so a hold test that refused it would let its
        # `hold:` be routed past. Only a REWRITE refuses non-UTF-8 bytes (`_rewrite`).
        try:
            self.raw = data.decode("utf-8")
        except UnicodeDecodeError:
            self.raw = data.decode("utf-8", errors="replace")
            self.utf8 = False
        # Universal newlines, as `read_text` gives Step 3c: a CR-only doc parses there.
        m = FM_RE.match(self.raw.replace("\r\n", "\n").replace("\r", "\n"))
        if not m:
            return  # legacy body-only doc: no ids, no hold
        try:
            fm = yaml.safe_load(m.group(1))
        except Exception as exc:  # noqa: BLE001 — PyYAML raises more than YAMLError (`Q-621`)
            self.error = f"frontmatter does not parse ({exc.__class__.__name__}: {exc})"
            return
        if not isinstance(fm, dict):
            self.error = f"frontmatter is a {type(fm).__name__}, not a mapping"
            return
        self.fm = fm
        self.has_fm = True


def pending_docs(root: Path) -> list[Path]:
    pd = root / PENDING
    if not pd.is_dir():
        return []
    return [p for p in sorted(pd.glob("*.md")) if p.name not in NOT_A_BRANCH_DOC]


def load_tasks(root: Path) -> dict[str, dict] | None:
    """Task entries by id; {} when there is no index; None when it cannot be read."""
    path = root / "tasks" / "index.yml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_bytes().decode("utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not load {path}: {exc.__class__.__name__}: {exc}. "
              "No doc's hold can be decided; nothing was stamped.", file=sys.stderr)
        return None
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(tasks or [], list):
        print(f"ERROR: {path} is not a task index (a mapping with a `tasks:` list). "
              "No doc's hold can be decided; nothing was stamped.", file=sys.stderr)
        return None
    return {str(t["id"]): t for t in (tasks or []) if isinstance(t, dict) and t.get("id")}


def reasons(doc: Doc, tasks: dict[str, dict]) -> list[str]:
    """Why 1c holds this doc: its outstanding `user_action` ids, then its `hold:`."""
    out = []
    ua = [t for t in doc_ids(doc.fm) if tasks.get(t, {}).get("user_action")]
    if ua:
        out.append(f"user_action outstanding: {', '.join(ua)}")
    h = doc_hold(doc.fm)
    if h:
        out.append(f"hold: {h}")
    return out


def _rewrite(doc: Doc, drop: str | None = None, add: tuple[str, str] | None = None) -> str:
    """Remove top-level key `drop`, or append `add`, in the doc's frontmatter.

    Returns "" on success, or why the edit was refused. Every other line stays
    byte-for-byte, and the result must re-parse to the old mapping with exactly
    that one key changed.
    """
    if not doc.utf8:
        return "it is not valid UTF-8"
    raw = doc.raw
    nl = "\r\n" if "\r\n" in raw else "\n"
    if raw.count("\r") != raw.count("\r\n") or (
            nl == "\r\n" and raw.count("\n") != raw.count("\r\n")):
        return "it mixes line endings"
    text = raw.replace("\r\n", "\n")
    m = FM_RE.match(text)
    if not m or not doc.has_fm:
        return "it has no frontmatter mapping"
    lines = m.group(1).split("\n")
    expect = dict(doc.fm)
    if drop is not None:
        kept, skipping = [], False
        for i, line in enumerate(lines):
            if re.match(rf"{re.escape(drop)}\s*:", line):
                skipping = True
                continue
            if skipping and line[:1] in (" ", "\t", "-"):
                continue
            if skipping and not line.strip():
                # A blank line belongs to the dropped value only when the value goes on
                # after it; otherwise it is the author's, and stays.
                rest = next((x for x in lines[i + 1:] if x.strip()), "")
                if rest[:1] in (" ", "\t", "-"):
                    continue
            skipping = False
            kept.append(line)
        lines = kept
        expect.pop(drop, None)
    if add is not None:
        key, value = add
        # FIRST, as Step 3c's answer recorder writes `smoke_answers`: appended after a
        # trailing block scalar, the line would become part of that scalar's value.
        lines.insert(0, f"{key}: '{value}'")
        expect[key] = value
    new_fm = "\n".join(lines)
    try:
        check = yaml.safe_load(new_fm) if new_fm.strip() else {}
    except Exception:  # noqa: BLE001
        check = None
    if not isinstance(check, dict) or check != expect:
        return "rewriting it would change another frontmatter key"
    out = text[:m.start(1)] + new_fm + text[m.end(1):]
    fd, tmp = tempfile.mkstemp(dir=str(doc.path.parent), prefix=".hold-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=nl) as f:
            f.write(out)
        os.chmod(tmp, doc.path.stat().st_mode & 0o7777)  # mkstemp creates 0600
        os.replace(tmp, doc.path)
    except OSError as exc:
        return f"the write failed ({exc.__class__.__name__}: {exc})"
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                          errors="replace", env=env)


def branch_merged(root: Path, branch: str) -> bool:
    """Whether `branch` is in `HEAD`, or in a PR head a `pr` close recorded (`Q-623`).

    1c stamps only a doc whose work merged: a held doc whose branch 4a SKIPped, or
    one in main's pending-docs for a branch not in this close, did not land.
    """
    # `refs/heads/`, never the bare name: a tag of the same name on an ancestor resolves
    # first and reads as merged (`Q-686`).
    if not has_local_branch(root, branch):
        return False
    ref = f"refs/heads/{branch}"
    r = _git(root, "rev-list", "--count", "--end-of-options", ref, "^HEAD")
    if r.returncode == 0 and r.stdout.strip() == "0":
        return True
    r = _git(root, "for-each-ref", "--contains", ref, "--format=%(refname)",
             "refs/sysop/merged-pr-heads/")
    return r.returncode == 0 and bool(r.stdout.strip())


def has_local_branch(root: Path, branch: str) -> bool:
    return bool(branch) and _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options",
                                 f"refs/heads/{branch}^{{commit}}").returncode == 0


def check(root: Path, stamp: bool = False, today: str | None = None) -> int:
    tasks = load_tasks(root)
    if tasks is None:
        return 1
    today = today or datetime.date.today().isoformat()
    held = routed = 0
    docs = [Doc(p) for p in pending_docs(root)]
    why = {d.path: reasons(d, tasks) for d in docs if not d.error}
    # A hold is per TASK, as `user_action` and the round-trip's arm already are: a doc naming
    # an id that a held doc names waits with it, or it would write that task's `Complete`
    # while the task is held (Phase 353's round 2). Closed transitively.
    changed = True
    while changed:
        changed = False
        held_ids = {i for d in docs if why.get(d.path) for i in doc_ids(d.fm)}
        for d in docs:
            if d.error or why[d.path]:
                continue
            shared = sorted(set(doc_ids(d.fm)) & held_ids)
            if shared:
                why[d.path] = [f"shares {', '.join(shared)} with a held doc"]
                changed = True
    for doc in docs:
        path, name = doc.path, doc.path.name
        if doc.error:
            # Step 4c item 3 quarantines a doc whose frontmatter will not parse.
            print(f"UNREADABLE: {name} — {doc.error}")
            continue
        if not why[path]:
            routed += 1
            print(f"ROUTE: {name}")
            continue
        held += 1
        since = doc.fm.get("held_since")
        note = ""
        branch = str(doc.fm.get("branch") or "").strip()
        if not since and stamp and not has_local_branch(root, branch):
            note = f"; NOT STAMPED: no local branch {branch or '(none)'}"
        elif not since and stamp and not branch_merged(root, branch):
            note = f"; NOT STAMPED: branch {branch} is not merged into HEAD"
        elif not since and stamp:
            # An empty `held_since:` key is replaced, not duplicated: PyYAML keeps
            # the last of two equal keys, so a second line would pass the re-parse.
            refused = _rewrite(doc, drop="held_since" if "held_since" in doc.fm else None,
                               add=("held_since", today))
            if refused:
                note = f"; NOT STAMPED: {refused}"
            else:
                since, note = today, " (stamped now)"
        tail = f"; held since {since}" if since else ""
        print(f"HELD: {name} — branch {doc.fm.get('branch') or '(none)'}; "
              f"{'; '.join(why[path])}{tail}{note}")
    print(f"HOLD CHECK: {held} held, {routed} to route")
    return 0


def _siblings(d: Path, stem: str) -> list[tuple[int, Path]]:
    """`<stem>--<n>.md` beside the base doc, by n."""
    out = []
    for c in d.glob(f"{glob.escape(stem)}--*.md"):
        n = c.name[len(stem) + 2:-3]
        if n.isdigit():
            out.append((int(n), c))
    return sorted(out)


def guard(path: Path) -> int:
    d, name = path.parent, path.name
    stem = name[:-3] if name.endswith(".md") else name
    sibs = _siblings(d, stem)
    cands = ([path] if path.exists() else []) + [c for _, c in sibs]
    docs = []
    for c in cands:
        doc = Doc(c)
        if doc.error:
            print(f"ERROR: {c} exists and cannot be read ({doc.error}); not choosing a "
                  "path past it.", file=sys.stderr)
            return 1
        docs.append(doc)
    # A `<stem>--<n>.md` is a sibling only when it is the base's branch: `feat/x` and a branch
    # actually named `feat-x--2` sanitise to colliding names.
    if docs and docs[0].path == path:
        base_branch = docs[0].fm.get("branch")
        docs = [docs[0]] + [x for x in docs[1:] if x.fm.get("branch") == base_branch]
    unstamped = [doc for doc in docs if not doc.fm.get("held_since")]
    if unstamped:
        target = unstamped[-1].path
    elif not path.exists():
        target = path
    else:
        target = d / f"{stem}--{max([1] + [n for n, _ in sibs]) + 1}.md"
    for doc in docs:
        if doc.fm.get("held_since") and doc.path != target:
            print(f"NOTE: {doc.path.name} is held by a close (held since "
                  f"{doc.fm['held_since']}); it is left alone and this doc goes beside it.")
    print(f"WRITE: {target}")
    main = main_repo_root() / PENDING
    try:
        same = main.resolve() == d.resolve()
    except OSError:
        same = False
    # Only the same-named copy: it is the one Step 3b's collect would replace. A sibling is
    # never replaced, so its hold stands on its own.
    if not same and (main / name).exists():
        h = doc_hold(Doc(main / name).fm)
        if h:
            print(f"CARRY HOLD: {h} (from the main checkout's {name})")
    return 0


def _names(doc: Doc, target: str) -> bool:
    stem = doc.path.name[:-3] if doc.path.name.endswith(".md") else doc.path.name
    branch = str(doc.fm.get("branch") or "")
    return (target in doc_ids(doc.fm) or target == branch
            or target in (doc.path.name, stem))


def clear(root: Path, target: str, dry_run: bool = False) -> int:
    docs = [Doc(p) for p in pending_docs(root)]
    hits = [d for d in docs if not d.error and d.has_fm and _names(d, target)]
    if not hits:
        print(f"ERROR: no pending doc in {root / PENDING} names {target} "
              "(by a task id, its branch, or its file name).", file=sys.stderr)
        for d in docs:
            if d.error:
                print(f"   {d.path.name} could not be read ({d.error}), so it was not "
                      "searched.", file=sys.stderr)
        return 2
    tasks = load_tasks(root) or {}
    rc = 0
    for doc in hits:
        name = doc.path.name
        was = repr(doc.fm.get("hold"))
        removed = False
        if "hold" not in doc.fm:
            print(f"ℹ️  {name} carries no `hold:` — nothing to clear.")
        elif dry_run:
            print(f"DRY RUN: would remove `hold: {was}` from {name}. Nothing written.")
        else:
            refused = _rewrite(doc, drop="hold")
            if refused:
                print(f"REFUSING: {name} — {refused}; remove `hold:` by hand.",
                      file=sys.stderr)
                rc = 1
                continue
            removed = True
            print(f"✅ {name}: `hold:` removed (was: {was}).")
        ua = [t for t in doc_ids(doc.fm) if tasks.get(t, {}).get("user_action")]
        for t in ua:
            print(f"   Still held: {t} has user_action set. Once its step is done: "
                  f"python3 sysop/scripts/clear_user_action.py {t}")
        if removed and not ua:
            print("   The next /review-close consolidates this doc and closes its tasks.")
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pending_doc_hold.py",
        description="Test, stamp and clear the hold on /review-close pending docs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="print HELD / ROUTE for every pending doc")
    c.add_argument("--stamp", action="store_true",
                   help="write held_since: '<today>' into each held doc lacking it")
    g = sub.add_parser("guard", help="print the pending doc to write, and any hold to carry")
    g.add_argument("path", help="the pending doc /document-work would write")
    k = sub.add_parser("clear", help="remove `hold:` from the docs a target names")
    k.add_argument("target", help="a task id, a branch name, or a pending-doc file name")
    k.add_argument("--dry-run", action="store_true",
                   help="report what would change and write nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "guard":
        return guard(Path(args.path))
    root = main_repo_root()
    if args.cmd == "check":
        return check(root, stamp=args.stamp)
    return clear(root, args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
