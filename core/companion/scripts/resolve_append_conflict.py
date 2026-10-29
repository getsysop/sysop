#!/usr/bin/env python3
"""resolve_append_conflict.py — `/review-close` Step 4a: resolve a shared append file's conflict
from the merge stages, as one command a seeded rule admits.

    python3 sysop/scripts/resolve_append_conflict.py index
    python3 sysop/scripts/resolve_append_conflict.py index --since "<ref>" "<branch>"
    python3 sysop/scripts/resolve_append_conflict.py notes

Run from the top level of the checkout where the merge or rebase stopped, while the file is
conflicted. Stage 1 is the merge base (the replayed commit's parent during a rebase), stage 2
the merge target, stage 3 the branch being replayed. Each subcommand writes the resolved file
through `mkstemp` and `os.replace` and never stages it: the step stages it and, for
`tasks/index.yml`, runs `validate_tasks.py` before it continues.

`index` starts from stage 2's text and changes only the entries the branch changed, comparing
entries by parsed value and splicing each one as text, so the target's file keeps its order,
comments and style (`yaml.safe_dump` would restyle it). Per id: an entry the branch added is
appended verbatim from stage 3; an entry the branch edited replaces the target's copy when the
target left it as stage 1 had it; an entry the branch removed is removed when the target left
it as stage 1 had it; an entry the target removed stays out. A reformat that parses to the same
value is not a change, and is not carried; neither is an order change, and a comment above an
entry the branch removed stays. An empty `tasks: []`, which the installer seeds, is a list with no
entries. Before it writes, it checks that the spliced file parses to exactly the expected entries. `--since "<ref>" "<branch>"` (Step 4a item 2's
published arm, when a recorded PR head contains the branch's claim commits) reads what the
branch changed since its merge base with `<ref>` instead of from stage 1, and prints a
`TARGET SIDE:` line for each status it resolved to the target's side, for Step 8.

`notes` resolves `tasks/notes.md`, a flat list of one-line notes, as a three-way line merge:
stage 2's lines, less the lines the branch deleted, plus the lines it added that the target
did not add too. Lines are compared whole, so a note one side edited and the other deleted comes
back edited: line identity cannot tell an edit from a new note.

Exit 0 `RESOLVED: …` (written). Exit 1 `REFUSED: …`: the resolution needs a person, nothing was
written; abort and 4a-SKIP the branch. `index` refuses an id both sides added differently, an
entry both sides edited, an edit to an entry the target removed or a removal of one it edited,
a branch change outside `tasks:`, and any conflicted body file under `tasks/`; `notes` refuses a file that is not flat.
A stage that lacks the file (one side deleted it) is refused too. Exit 4 `STOP: …` (`index`): two
actors moved one task's status; it prints both values and writes nothing. Exit 2 `STOP: …`: it
could not be measured (the file is not conflicted here, PyYAML or git failed, the entries could not
be mapped to the text, or `--since`'s ref already holds the whole branch); nothing was written. Exit 3 `STOP: …`: an operand is empty or still a `<placeholder>`.

It replaced `steps/4a-append.md`'s two stage-extraction blocks (`mktemp -d`, `>` redirects and
`comm … <(sort …)`), each denied under `dontAsk` (`Q-665`), and the by-hand resolver a close
otherwise wrote mid-merge (`Q-629`).
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import NoReturn

try:
    import yaml
except ImportError:
    # PyYAML lives only in the project venv on PEP-668 hosts (BeanRider ISSUE-0049); the same
    # probe as `validate_tasks.py`, pinned identical by `tests/test_venv_pyyaml_bootstrap.py`.
    _roots = []
    # `list(...)` before the slice: slicing `PurePath.parents` is 3.10+ (bpo-35498).
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
        print("STOP: resolve_append_conflict.py requires PyYAML. fix: python3 -m venv .venv && "
              ".venv/bin/pip install pyyaml; nothing was written", file=sys.stderr)
        sys.exit(2)

SUBCOMMANDS = ("index", "notes")
INDEX = "tasks/index.yml"
NOTES = "tasks/notes.md"
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
PLACEHOLDER = re.compile(r"<[^<>]*>")


class Refused(Exception):
    """A resolution that needs a person (exit 1)."""


def say(code: int, line: str) -> NoReturn:
    print(line)
    sys.exit(code)


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], capture_output=True, text=True, env=GIT_ENV)
    return p.returncode, p.stdout


def stage_text(n: int | str, path: str) -> str | None:
    """The file at stage `n` (1-3), or at commit `n`; None when that side has no such file.

    Read as bytes: `text=True` reads with universal newlines, which turned a CRLF file into LF and
    rewrote every line of it on a one-entry append (Phase 425's round, lens A)."""
    spec = f":{n}:{path}" if isinstance(n, int) else f"{n}:{path}"
    p = subprocess.run(["git", "show", spec], capture_output=True, env=GIT_ENV)
    if p.returncode != 0:
        return None
    try:
        return p.stdout.decode("utf-8")
    except UnicodeDecodeError:
        say(2, f"STOP: {spec} is not UTF-8; nothing was written")


def lines_of(text: str) -> list[str]:
    """Lines split at `\n` only, each keeping its end. `str.splitlines` also splits at U+2028,
    U+0085 and a form feed, which rewrote such a line as two (Phase 425's round, lens A)."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def unmerged() -> list[str]:
    p = subprocess.run(["git", "diff", "--name-only", "--no-relative", "--diff-filter=U", "-z"],
                       capture_output=True, env=GIT_ENV)
    if p.returncode != 0:
        say(2, "STOP: git could not list the unmerged paths; nothing was written")
    return [x for x in p.stdout.decode("utf-8", "surrogateescape").split("\0") if x]


def write_atomic(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def preflight(path: str) -> None:
    code, prefix = git("rev-parse", "--show-prefix")
    if code != 0:
        say(2, "STOP: not inside a git repository; nothing was written")
    if prefix.strip():
        say(2, f"STOP: run from the checkout's top level, not {prefix.strip()}; nothing was written")
    if path not in unmerged():
        say(2, f"STOP: {path} is not conflicted here; nothing was written")


# --- tasks/index.yml ---------------------------------------------------------------------------

ITEM = re.compile(r"^( *)-( |\r?\n|$)")
TASKS_KEY = re.compile(r"^tasks:[ \t]*(#.*)?\r?\n?$")
TASKS_EMPTY = re.compile(r"^tasks:[ \t]*\[[ \t]*\][ \t]*(#.*)?\r?\n?$")


def _trivia(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _outside(line: str, indent: int) -> bool:
    """A blank line, or a comment no deeper than the list's items: not part of an entry. A deeper
    line starting with `#` can be a block scalar's content (Phase 425's round, lens A)."""
    return not line.strip() or (line.lstrip(" ").startswith("#")
                                and len(line) - len(line.lstrip(" ")) <= indent)


class Index:
    """One stage's `tasks/index.yml`: its parsed value, and each entry's block of text."""

    def __init__(self, text: str, label: str):
        self.label = label
        self.lines = lines_of(text)
        self.flow_empty = None
        try:
            self.doc = yaml.safe_load(text)
        except Exception as e:  # safe_load raises more than YAMLError (`Q-621`)
            raise Refused(f"{label} does not parse: {(str(e).splitlines() or [type(e).__name__])[0]}")
        if not isinstance(self.doc, dict):
            raise Refused(f"{label} is not a mapping")
        tasks = self.doc.get("tasks")
        if tasks is None:
            tasks = []
        if not isinstance(tasks, list) or not all(isinstance(t, dict) and "id" in t for t in tasks):
            raise Refused(f"{label}'s tasks: is not a list of entries with an id")
        self.tasks = tasks
        self.ids = [str(t["id"]) for t in tasks]
        dup = sorted({i for i in self.ids if self.ids.count(i) > 1})
        if dup:
            raise Refused(f"{label} carries {', '.join(dup)} twice")
        self.by_id = dict(zip(self.ids, tasks))
        self._map()

    def _map(self) -> None:
        keys = [n for n, ln in enumerate(self.lines) if TASKS_KEY.match(ln)]
        empty = [n for n, ln in enumerate(self.lines) if TASKS_EMPTY.match(ln)]
        if not keys and len(empty) == 1 and not self.tasks:
            # The installer's seed, and `safe_dump`'s form of an empty list (Phase 425's round,
            # lens A): no entries, and the line becomes `tasks:` if an entry is appended.
            self.flow_empty = empty[0]
            self.has_key = True
            self.start = self.end = empty[0] + 1
            self.indent, self.blocks, self.lead = 2, [], []
            self.tail = (self.start, self.start)
            return
        if len(keys) != 1:
            if not self.tasks and "tasks" not in self.doc:
                self.start = self.end = len(self.lines)
                self.indent, self.blocks, self.lead = 2, [], []
                self.has_key = False
                return
            raise Refused(f"{self.label}'s tasks: is not one block-style key")
        self.has_key = True
        start = keys[0] + 1
        indent = None
        for ln in self.lines[start:]:
            if _trivia(ln):
                continue
            m = ITEM.match(ln)
            if m:
                indent = len(m.group(1))
            break
        end = start
        for n in range(start, len(self.lines)):
            ln = self.lines[n]
            if _outside(ln, 0 if indent is None else indent):
                continue
            lead = len(ln) - len(ln.lstrip(" "))
            if indent is None or lead < indent or (lead == indent and not ITEM.match(ln)):
                break
            end = n + 1
        if indent is None:
            if self.tasks:
                raise Refused(f"{self.label}'s tasks: is not a block-style list")
            indent = 2
        starts = []
        for n in range(start, end):
            m = ITEM.match(self.lines[n])
            if m and len(m.group(1)) == indent:
                starts.append(n)
        self.start, self.end, self.indent = start, end, indent
        self.blocks, self.lead = [], []
        prev = start
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else end
            while e > s + 1 and _outside(self.lines[e - 1], indent):
                e -= 1
            self.lead.append((prev, s))
            self.blocks.append((s, e))
            prev = e
        self.tail = (prev, end)
        values = []
        for s, e in self.blocks:
            try:
                v = yaml.safe_load(self.dedent(self.lines[s:e]))
            except Exception:  # `Q-621`: an unparseable block maps to nothing
                v = None
            values.append(v[0] if isinstance(v, list) and len(v) == 1 else None)
        if values != self.tasks:
            raise Unmappable(f"could not map {self.label}'s entries to its text")

    def dedent(self, lines: list[str]) -> str:
        pad = " " * self.indent
        return "".join(ln[self.indent:] if ln.startswith(pad) else ln.lstrip(" ") for ln in lines)

    def block(self, tid: str) -> list[str]:
        s, e = self.blocks[self.ids.index(tid)]
        return self.lines[s:e]

    def leading(self, tid: str) -> list[str]:
        s, e = self.lead[self.ids.index(tid)]
        return self.lines[s:e]


class Unmappable(Exception):
    """The text and the parsed entries disagree (exit 2)."""


def reindent(lines: list[str], src: Index, dst: Index) -> list[str]:
    pad = " " * dst.indent
    out = []
    for ln in lines_of(src.dedent(lines)):
        out.append(pad + ln if ln.strip() else ln)
    return out


def classify(base: Index, ours: Index, theirs: Index):
    """Per id, what the branch did and what to do with it."""
    ops, refused, status, target_side = [], [], [], []
    for key in sorted(set(base.doc) | set(theirs.doc), key=str):
        if key != "tasks" and base.doc.get(key) != theirs.doc.get(key):
            refused.append(f"the branch changed {key}: outside tasks:")
    for tid in theirs.ids:
        t = theirs.by_id[tid]
        if tid not in base.by_id:
            if tid not in ours.by_id:
                ops.append(("append", tid))
            elif ours.by_id[tid] != t:
                refused.append(f"both sides added {tid}, differently")
            continue
        b = base.by_id[tid]
        if t == b:
            o = ours.by_id.get(tid)
            if o is not None and o.get("status") != t.get("status"):
                target_side.append((tid, o.get("status"), t.get("status")))
            continue
        if tid not in ours.by_id:
            refused.append(f"the target removed {tid} and the branch edited it")
            continue
        o = ours.by_id[tid]
        if o == b:
            ops.append(("replace", tid))
        elif o != t:
            keys = set(b) | set(t) | set(o)
            both = sorted(k for k in keys
                          if b.get(k) != t.get(k) and b.get(k) != o.get(k) and t.get(k) != o.get(k))
            if "status" in both:
                status.append((tid, o.get("status"), t.get("status")))
            if both != ["status"]:
                mine = sorted(k for k in keys if b.get(k) != t.get(k))
                yours = sorted(k for k in keys if b.get(k) != o.get(k))
                refused.append(f"both sides edited {tid}: the target changed {', '.join(yours)}, "
                               f"the branch {', '.join(mine)}")
    for tid in base.ids:
        if tid in theirs.by_id or tid not in ours.by_id:
            continue
        if ours.by_id[tid] == base.by_id[tid]:
            ops.append(("remove", tid))
        else:
            refused.append(f"the branch removed {tid} and the target edited it")
    return ops, refused, status, target_side


def splice(ours: Index, theirs: Index, ops) -> str:
    lines = list(ours.lines)
    if not ours.has_key:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append("tasks:\n")
        ours.start = ours.end = len(lines)
        ours.tail = (ours.end, ours.end)
    edits = []  # (start, end, replacement), applied from the bottom up
    for kind, tid in ops:
        if kind == "replace":
            s, e = ours.blocks[ours.ids.index(tid)]
            edits.append((s, e, reindent(theirs.block(tid), theirs, ours)))
        elif kind == "remove":
            i = ours.ids.index(tid)
            s, e = ours.blocks[i]
            ls, le = ours.lead[i]
            if i > 0 and all(not ln.strip() for ln in lines[ls:le]):
                s = ls
            edits.append((s, e, []))
    added = []
    for kind, tid in ops:
        if kind == "append":
            lead = theirs.leading(tid)
            if theirs.ids.index(tid) == 0 and any(ln.strip() for ln in lead):
                lead = [ln for ln in lead if not ln.strip()]
            added += lead + reindent(theirs.block(tid), theirs, ours)
    at = ours.blocks[-1][1] if ours.blocks else ours.start
    if added and ours.flow_empty is not None:
        line = lines[ours.flow_empty]
        lines[ours.flow_empty] = "tasks:" + line[len(line.rstrip("\r\n")):]
    if added:
        if at > 0 and not lines[at - 1].endswith("\n"):
            lines[at - 1] += "\n"
        if added[-1] and not added[-1].endswith("\n"):
            added[-1] += "\n"
        edits.append((at, at, added))
    for s, e, rep in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        lines[s:e] = rep
    return "".join(lines)


def expected(ours: Index, theirs: Index, ops) -> dict:
    tasks = []
    gone = {tid for kind, tid in ops if kind == "remove"}
    swap = {tid for kind, tid in ops if kind == "replace"}
    for tid in ours.ids:
        if tid in gone:
            continue
        tasks.append(theirs.by_id[tid] if tid in swap else ours.by_id[tid])
    tasks += [theirs.by_id[tid] for kind, tid in ops if kind == "append"]
    doc = dict(ours.doc)
    if tasks or "tasks" in doc:
        doc["tasks"] = tasks
    return doc


def normal(doc: dict) -> dict:
    """`tasks:` with nothing under it parses to None; the comparison reads it as no entries."""
    return {**doc, "tasks": doc.get("tasks") or []} if "tasks" in doc else doc


def cmd_index(args: list[str]) -> None:
    since = None
    if args:
        if len(args) != 3 or args[0] != "--since":
            say(2, 'STOP: usage: index [--since "<ref>" "<branch>"]')
        ref, branch = args[1], args[2]
        for op in (ref, branch):
            if not op.strip() or PLACEHOLDER.search(op):
                say(3, f"STOP: write the operand out, not {op!r}; nothing was written")
        code, ref_sha = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        if code != 0:
            say(2, f"STOP: {ref} names no commit; nothing was written")
        code, br_sha = git("rev-parse", "--verify", "--end-of-options",
                           f"refs/heads/{branch}^{{commit}}")
        if code != 0:
            say(2, f"STOP: refs/heads/{branch} does not exist; nothing was written")
        code, mb = git("merge-base", ref_sha.strip(), br_sha.strip())
        if code != 0:
            say(2, f"STOP: {ref} and {branch} have no merge base; nothing was written")
        if mb.strip() == br_sha.strip():
            # Step 4a item 1's `REPLAY 0`: the ref holds the whole branch, so there is nothing
            # to read past it, and reading from it would drop the branch's edits (lens A).
            say(2, f"STOP: {ref} already contains refs/heads/{branch}; it should not be merged "
                   "(Step 4a item 1's REPLAY 0); nothing was written")
        since = (ref, mb.strip())
    preflight(INDEX)
    texts = {"stage 2 (the merge target)": stage_text(2, INDEX),
             "stage 3 (the branch)": stage_text(3, INDEX)}
    if since:
        texts["the merge base with " + since[0]] = stage_text(since[1], INDEX)
    else:
        texts["stage 1 (the merge base)"] = stage_text(1, INDEX)
    missing = [k for k, v in texts.items() if v is None]
    if missing:
        say(1, f"REFUSED: {INDEX} is absent from {' and '.join(missing)}; nothing was written; "
               "abort and 4a-SKIP the branch")
    try:
        ours = Index(texts["stage 2 (the merge target)"] or "", "stage 2 (the merge target)")
        theirs = Index(texts["stage 3 (the branch)"] or "", "stage 3 (the branch)")
        blabel = next(k for k in texts if k.startswith(("stage 1", "the merge base")))
        base = Index(texts[blabel] or "", blabel)
    except Unmappable as e:
        say(2, f"STOP: {e}; nothing was written")
    except Refused as e:
        say(1, f"REFUSED: {e}; nothing was written; abort and 4a-SKIP the branch")
    ops, refused, status, target_side = classify(base, ours, theirs)
    bodies = [p for p in unmerged() if p.startswith("tasks/") and p.endswith(".md") and p != NOTES]
    for p in bodies:
        refused.append(f"{p} is conflicted too: a body file both sides changed needs a person")
    if status:
        for tid, o, t in status:
            print(f"STATUS: {tid} target {o}, branch {t}")
        for r in refused:
            print(f"REFUSED: {r}")
        say(4, "STOP: two actors moved a task's status; nothing was written")
    if refused:
        for r in refused:
            print(f"REFUSED: {r}")
        say(1, "REFUSED: nothing was written; abort and 4a-SKIP the branch")
    text = splice(ours, theirs, ops)
    try:
        got = Index(text, "the resolved file")
    except (Refused, Unmappable) as e:
        say(2, f"STOP: the spliced file failed its own check ({e}); nothing was written")
    if normal(got.doc) != normal(expected(ours, theirs, ops)):
        say(2, "STOP: the spliced file does not parse to the expected entries; nothing was written")
    write_atomic(Path(INDEX), text)
    words = {"append": "APPENDED: {} (the branch filed it)",
             "replace": "APPLIED: {} (the branch's edit)",
             "remove": "REMOVED: {} (the branch removed it)"}
    for kind, tid in ops:
        print(words[kind].format(tid))
    for tid in base.ids:
        if tid in theirs.by_id and tid not in ours.by_id:
            print(f"KEPT OUT: {tid} (the target removed it)")
    if since:
        for tid, o, t in target_side:
            print(f"TARGET SIDE: {tid} status {o} (the branch's {t} predates {since[0]})")
    say(0, f"RESOLVED: {INDEX} written from stage 2 with {len(ops)} change(s); "
           "stage it and run validate_tasks.py")


# --- tasks/notes.md ----------------------------------------------------------------------------

def _flat(text: str) -> str | None:
    """Why `text` is not a flat list of one-line notes, or None when it is."""
    seen_content = False
    for n, ln in enumerate((x.rstrip("\r") for x in text.split("\n")), 1):
        if not ln.strip():
            continue
        if ln[0] in " \t":
            return f"line {n} is indented (a sub-bullet or a continued line)"
        if ln.startswith("#") and seen_content:
            return f"line {n} is a heading below the first line (a section)"
        seen_content = True
    return None


def cmd_notes(args: list[str]) -> None:
    if args:
        say(2, "STOP: usage: notes")
    preflight(NOTES)
    base, ours, theirs = (stage_text(n, NOTES) for n in (1, 2, 3))
    if ours is None or theirs is None:
        say(1, f"REFUSED: one side deleted {NOTES}; nothing was written; abort and 4a-SKIP the branch")
    base = base or ""
    for label, text in (("stage 1", base), ("stage 2", ours), ("stage 3", theirs)):
        why = _flat(text)
        if why:
            say(1, f"REFUSED: {NOTES} at {label} is not flat: {why}; keeping both sides is not safe; "
                   "nothing was written; abort and 4a-SKIP the branch")
    def counted(text: str) -> Counter:
        return Counter(ln.rstrip("\r") for ln in text.split("\n") if ln.strip())
    b, o, t = counted(base), counted(ours), counted(theirs)
    dropped, added, both = b - t, t - b, o - b
    out, n_drop = [], 0
    for ln in lines_of(ours):
        key = ln.rstrip("\r\n")
        if key.strip() and dropped[key] > 0:
            dropped[key] -= 1
            n_drop += 1
            continue
        out.append(ln)
    nl = "\r\n" if "\r\n" in ours else "\n"
    if out and not out[-1].endswith("\n"):
        out[-1] += nl
    n_add = 0
    for ln in (x.rstrip("\r") for x in theirs.split("\n")):
        if not ln.strip() or added[ln] <= 0:
            continue
        added[ln] -= 1
        if both[ln] > 0:
            both[ln] -= 1
            continue
        out.append(ln + nl)
        n_add += 1
    write_atomic(Path(NOTES), "".join(out))
    say(0, f"RESOLVED: {NOTES} written from stage 2: {n_add} line(s) the branch added, "
           f"{n_drop} line(s) it deleted taken out; re-read it, then stage it")


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in SUBCOMMANDS:
        say(2, "STOP: usage: resolve_append_conflict.py {" + "|".join(SUBCOMMANDS) + "} [args]")
    {"index": cmd_index, "notes": cmd_notes}[argv[0]](argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
