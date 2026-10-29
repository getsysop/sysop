#!/usr/bin/env python3
"""ignored_refs.py — gitignored files the work references (`Q-633`).

A gate that reads the working tree (a test runner, a build) sees an untracked,
gitignored file the branch's code imports, so it passes; the merge does not
carry the file, so the merged tree breaks. And an unforced `git worktree remove`
deletes ignored files without asking, so a close that removes the worktree
destroys the only copy. Two modes, one for each half:

    ignored_refs.py <WORKSPACE> <BASE> [--branch <NAME>]     # the check
    ignored_refs.py <WORKSPACE> --preserve <DEST>            # the copy

**The check** reads every line the work adds since its merge-base with BASE and
reports each ignored file a line references. It is best-effort. It reads the
consumer's resolver configuration where Wade ruled it should (2026-10-04): a
quoted token through the `compilerOptions.paths` (and `baseUrl`) of the nearest
`tsconfig.json` or `jsconfig.json` above the referencing file that declares
usable `paths` (a nearer one without them, unparsable, or with a `baseUrl`
outside the workspace defers to an outer one, roughly as an `extends` would), and a
root-absolute URL (`/logo.png`) through the `public/` directory beside the
nearest `next.config.*`. It cannot see `extends`, a bundler alias map, or a name
built at run time (a template literal, `importlib`, `import.meta.glob`), nor a
config under another name (`tsconfig.app.json`, reached by `references`), and it
reads no file inside a directory ignored as a whole. The configuration is read
from the same tree as the lines: the working tree, or BRANCH's tip.

**The copy** is matcher-free: it copies every ignored file the caller's main
checkout has no byte-identical copy of, referenced or not, to DEST (which must be
gitignored in the main checkout). A file already preserved, at DEST or in an
earlier timestamped run under it, is not copied again; a differing one, or one
whose path is blocked, goes under a fresh UTC timestamp, so nothing preserved is
overwritten. A main-checkout file that is a link, or that resolves into the
workspace, is not a copy. `/review-close` Step 3b step 0b runs it
before removing a worktree, so the remove destroys nothing the check missed
(Wade, 2026-10-02).

**Which ignored files**, in both modes: the ones `git ls-files --others --ignored
--exclude-standard --directory` lists one by one, the files a file pattern
ignores (`*.json`, `.env`). A directory a pattern ignores as a whole
(`node_modules/`, `.venv/`, `__pycache__/`) is one entry and is not read: those
are installs, caches and build output, and on one consumer's four live claim
worktrees they produced every false hit (Wade, 2026-10-01). Symlinks are skipped
(removing one removes the link), and so is `sysop/runtime/`, Sysop's own state:
the close collects its pending docs, and the rest is scratch.

**Which lines.** The working tree against `git merge-base BASE HEAD` (committed
and uncommitted changes, read with `--text` so a `-diff` attribute hides
nothing), plus every line of each untracked, unignored, non-binary file, so an
executor can run it before it commits. With `--branch NAME`, when the workspace
has another branch checked out (a `--branch` claim at close time), NAME's commits
since the merge-base instead. Not read: `*ignore` files and prose (`.md`,
`.markdown`, `.rst`, `.adoc`, any case).

**Which references.** A path-like token resolves against the referencing file's
directory or the workspace root, with a leading `@/`, `~/`, `#/`, `/` or `$VAR/`
read as root-relative only. A path-like token with no extension also matches a
file with one of the extensions a resolver tries (Node's and the bundlers', or
Python's), or its `/index.*` or `/__init__.*`. A directory named in a string
literal reports every ignored file under it, beside the referencing file or, for
two or more components, from the root; a glob reports the files its pattern
matches, `*` within one component and `**` across them, beside the file or from
the root (a bare `*` or `**` names nothing). A token of two or more components
also matches as a trailing suffix. A bare file name with an extension (`a.json`,
`.env`) matches an ignored file of that name anywhere. A Python `import`/`from`
line, including a parenthesised one over several lines, is read as module paths,
with `.py`, `.pyi`, `.so`, `.pyd` or a package `__init__`, and as a suffix for a
`src/` layout.

Output of the check, one line per referenced file, then one summary line:

    IGNORED-REF: <path> <- <file>:<line> (only copy | the main checkout has an identical copy
                                          | not compared: the workspace is its own main checkout)
    IGNORED-REFS: <n found | none> (<k> ignored files; <d> ignored directories not read; <a> added lines in <f> files;
                  <r> resolver configs read[, <u> not parsed]; names built at run time not read)

`<r>` counts each `tsconfig.json`/`jsconfig.json` parsed and each directory holding a Next
config; `<u>` each `tsconfig.json`/`jsconfig.json` that could not be parsed, which is skipped.

The main checkout compared against is the CALLER's (the repository the command
runs from), so a `--clone` workspace checked from the repo root is compared with
the real main checkout; from the main working tree it is that tree's top level,
which holds under `--separate-git-dir` and in a submodule. With `--branch`, a
`--clone` workspace whose tip is not this repository's branch is refused (exit 3):
Step 4a merges this repository's branch, not the clone's, and `/review-close` Step
1-pre is what brings the two together. The copy prints one `PRESERVED: <path> -> <target>` line
per file it copies and a `PRESERVE:` summary.

Exit 0 when the check reports nothing or the copy finished, 1 when the check
reports something, 2 on a usage error (argparse), 3 when either could not run (a
placeholder operand, a workspace that is not the top of a git work tree, a BASE
git cannot resolve, a DEST outside the main checkout or not ignored there, a git
command or a copy that failed, any unexpected error). Neither 2 nor 3 is a pass.
"""

from __future__ import annotations

import argparse
import datetime
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_DISCOVERY = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
_MAX_UNTRACKED_BYTES = 1 << 20
_TOKEN = re.compile(r"[\w@~#+\-./${}]+")
_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+(\.*[\w.]*)\s+import\s+(\(?)([\w., ]*)|import\s+([\w., ]+))")
_PY_OPEN_FROM = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\s+\([^)]*$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_PROSE = (".md", ".markdown", ".rst", ".adoc")
# What a resolver tries when an import names a path without an extension: Node and the
# bundlers for a path token, Python's import system for a module. Completing to ANY
# extension reported `app.db` for `from app import x` and `api.log` for `./api`.
_PATH_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".json", ".node",
             ".vue", ".svelte", ".py", ".pyi")
_PY_EXT = (".py", ".pyi", ".so", ".pyd")
_RUNTIME = "sysop/runtime"


class CheckError(Exception):
    """The check could not run; the caller exits 3."""


def _git(ws: Path, *args: str) -> bytes:
    env = {k: v for k, v in os.environ.items() if k not in _DISCOVERY}
    r = subprocess.run(["git", "-C", str(ws), *args], capture_output=True, env=env)
    if r.returncode != 0:
        raise CheckError("git {} failed ({}): {}".format(
            " ".join(args), r.returncode, os.fsdecode(r.stderr).strip()))
    return r.stdout


def _in_runtime(path: str) -> bool:
    return path == _RUNTIME or path.startswith(_RUNTIME + "/")


def ignored_files(ws: Path) -> tuple[set[str], int]:
    """(files, directory count): the ignored, untracked files git lists one by one, and
    the directories it lists with nothing listed under them, whose contents go unread.

    git lists an untracked directory BESIDE the ignored files it holds; those files are
    read, so such a directory is not counted as unread.
    """
    out = _git(ws, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
               "--directory")
    entries = [os.fsdecode(raw) for raw in out.split(b"\0") if raw]
    listed = [e for e in entries if not e.endswith("/")]
    # A symlink is never the only copy of anything: removing it removes the link.
    files = {e for e in listed if not _in_runtime(e) and not os.path.islink(ws / e)}
    dirs = sum(1 for e in entries if e.endswith("/")
               and not any(f.startswith(e) for f in listed))
    return files, dirs


def _unquote(target: str) -> str:
    """A path git C-quoted in a diff header (`"b/a\\"b.ts"`), as written on disk.

    `core.quotePath=false` stops the quoting of non-ASCII bytes but not of a `"`, a
    backslash or a control character; read raw, such a header names no `b/` path and
    every line under it would go unread.
    """
    if not (len(target) >= 2 and target[0] == target[-1] == '"'):
        return target
    body, out, i = target[1:-1], bytearray(), 0
    simple = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if body[i + 1:i + 4].isdigit() and len(body[i + 1:i + 4]) == 3:
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
        out += ch.encode("utf-8", "surrogateescape")
        i += 1
    return os.fsdecode(bytes(out))


def _not_read(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return ("." in name and name.rsplit(".", 1)[-1].endswith("ignore")) \
        or name.lower().endswith(_PROSE)


def _head_branch(ws: Path) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _DISCOVERY}
    # The full ref, stripped by hand: `--short` prints `heads/<name>` when a tag shares the name.
    r = subprocess.run(["git", "-C", str(ws), "symbolic-ref", "-q", "HEAD"],
                       capture_output=True, env=env)
    out = os.fsdecode(r.stdout).strip() if r.returncode == 0 else ""
    return out[len("refs/heads/"):] if out.startswith("refs/heads/") else ""


def _tip(ws: Path, branch: str | None) -> str:
    """`HEAD` when the workspace's working tree is the work, else BRANCH (see added_lines)."""
    return "HEAD" if branch is None or _head_branch(ws) == branch else f"refs/heads/{branch}"


def added_lines(ws: Path, base: str, branch: str | None = None) -> list[tuple[str, int, str]]:
    """(file, line number, text) for every line the work adds since the merge-base.

    Without BRANCH, or when the workspace has BRANCH checked out: the working tree against
    the merge-base of BASE and HEAD, plus untracked files. With a BRANCH the workspace does
    not have checked out (a `--branch` claim whose checkout has moved back to the default
    branch): only BRANCH's commits, because the working tree is not that branch's.
    """
    tip = _tip(ws, branch)
    mb = os.fsdecode(_git(ws, "merge-base", base, tip)).strip()
    if not mb:
        raise CheckError("git merge-base {} {} printed nothing".format(base, tip))
    revs = [mb] if tip == "HEAD" else [mb, tip]
    diff = _git(ws, "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--text",
                "--no-ext-diff", "--no-textconv", "--no-renames",
                "--src-prefix=a/", "--dst-prefix=b/", *revs, "--")
    lines: list[tuple[str, int, str]] = []
    cur, lineno, in_hunk = None, 0, False
    for raw in diff.split(b"\n"):
        text = os.fsdecode(raw)
        if text.startswith("diff --git "):
            cur, in_hunk = None, False
            continue
        if not in_hunk:
            # File headers. `+++ b/<path>` names the file; `+++ /dev/null` is a
            # deletion, which adds nothing. Only a hunk header ends the headers, so a
            # body line that happens to begin `+++` is never read as one.
            if text.startswith("+++ "):
                # git ends the header with a TAB when the path holds a space.
                target = _unquote(text[4:][:-1] if text.endswith("\t") else text[4:])
                cur = target[2:] if target.startswith("b/") else None
            m = _HUNK.match(text)
            if m:
                in_hunk, lineno = True, int(m.group(1))
            continue
        m = _HUNK.match(text)
        if m:
            lineno = int(m.group(1))
        elif text.startswith("+"):
            if cur is not None and "\0" not in text:
                lines.append((cur, lineno, text[1:]))
            lineno += 1
        elif text.startswith(" "):
            lineno += 1
    untracked = b"" if tip != "HEAD" else _git(ws, "ls-files", "-z", "--others",
                                               "--exclude-standard")
    for raw in untracked.split(b"\0"):
        if not raw:
            continue
        rel = os.fsdecode(raw)
        p = ws / rel
        if p.is_symlink() or not p.is_file():
            continue
        with open(p, "rb") as fh:
            data = fh.read(_MAX_UNTRACKED_BYTES)
        if b"\0" in data:
            continue
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            lines.append((rel, n, line))
    return [t for t in lines if not _not_read(t[0])]


def _norm(path: str) -> str | None:
    """A repo-relative path, or None when it is empty or leaves the workspace."""
    p = os.path.normpath(path).replace(os.sep, "/")
    if p in (".", "", "..") or p.startswith("../") or p.startswith("/"):
        return None
    return p


def _stem(path: str) -> str:
    head, _, name = path.rpartition("/")
    s = os.path.splitext(name)[0]
    return head + "/" + s if head else s


def _module_candidates(rel_dir: str, line: str) -> list[str]:
    """The paths a Python `import`/`from` line names, without their extension."""
    m = _PY_IMPORT.match(line)
    if not m:
        return []

    def names(group: str) -> list[str]:
        return [n for n in (part.strip().split(" ")[0].replace(".", "/")
                            for part in group.split(",")) if n]

    def roots(name: str) -> list[str]:
        """Root-relative, and relative to the referencing file's package."""
        return [x for x in (_norm(name), _norm(os.path.join(rel_dir, name)) if rel_dir
                            else None) if x]

    if m.group(4) is not None:
        return [c for n in names(m.group(4)) for c in roots(n)]
    mod = m.group(1)
    dots = len(mod) - len(mod.lstrip("."))
    name = mod[dots:].replace(".", "/")
    if dots:
        up = os.path.join(rel_dir or ".", *([".."] * (dots - 1)))
        base = os.path.normpath(os.path.join(up, name or ".")).replace(os.sep, "/")
        if base.startswith(".."):
            return []
        bases = ["" if base == "." else base]
    else:
        bases = roots(name) if name else []
    out = [b for b in bases if b]
    for b in bases:
        for n in names(m.group(3) or ""):
            c = _norm(os.path.join(b, n)) if b else _norm(n)
            if c:
                out.append(c)
    return out


def _glob_re(glob: str) -> re.Pattern:
    """A `/`-aware glob: `*` and `?` stay inside one path component, `**` crosses them."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


_TS_CONFIGS = ("tsconfig.json", "jsconfig.json")   # tsconfig wins in one directory
_NEXT_CONFIGS = tuple("next.config." + e for e in ("js", "mjs", "cjs", "ts", "mts"))


def _jsonc(text: str) -> object:
    """`tsconfig.json` is JSON with comments and trailing commas; strip both outside strings."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            in_str = ch != '"'
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch)
            i += 1
    bare, kept, in_str, k = "".join(out), [], False, 0
    while k < len(bare):
        ch = bare[k]
        if in_str:
            kept.append(ch)
            if ch == "\\" and k + 1 < len(bare):
                kept.append(bare[k + 1])
                k += 2
                continue
            in_str = ch != '"'
        elif ch == '"':
            in_str = True
            kept.append(ch)
        elif ch == ",":
            j = k + 1
            while j < len(bare) and bare[j] in " \t\r\n":
                j += 1
            if j >= len(bare) or bare[j] not in "}]":
                kept.append(ch)
        else:
            kept.append(ch)
        k += 1
    return json.loads("".join(kept))


class Resolver:
    """What the consumer's resolver configuration maps a token to (Wade, 2026-10-04).

    Read: `compilerOptions.paths` (with `baseUrl`) of the nearest `tsconfig.json` or
    `jsconfig.json` above the referencing file that declares `paths`, and the `public/` directory beside the
    nearest Next config (`next.config.*`), where a root-absolute URL (`/logo.png`) is
    served from. Not read: `extends`, `references` (`tsconfig.app.json`), bundler alias maps, and every name only run time
    builds (a template literal, `importlib`, `import.meta.glob`).
    """

    def __init__(self, ws: Path, tip: str):
        self.aliases: dict[str, tuple[str, dict[str, list[str]]]] = {}
        self.public: set[str] = set()
        self.read = self.unparsed = 0
        if tip == "HEAD":
            names = _git(ws, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        else:
            names = _git(ws, "ls-tree", "-r", "-z", "--name-only", tip)
        found: dict[str, set[str]] = {}
        for raw in names.split(b"\0"):
            rel = os.fsdecode(raw)
            name = rel.rsplit("/", 1)[-1]
            if name in _TS_CONFIGS or name in _NEXT_CONFIGS:
                found.setdefault(rel.rsplit("/", 1)[0] if "/" in rel else "", set()).add(name)
        for d, here in found.items():
            nexts = [n for n in here if n in _NEXT_CONFIGS]
            if tip == "HEAD":   # a link, or tracked and deleted here: not a config
                nexts = [n for n in nexts if not os.path.islink(ws / d / n)
                         and (ws / d / n).is_file()]
            if nexts:
                self.public.add(d)
                self.read += 1
            cfg = next((c for c in _TS_CONFIGS if c in here), None)
            if cfg is None:
                continue
            rel = d + "/" + cfg if d else cfg
            try:
                if tip == "HEAD":
                    if not os.path.lexists(ws / rel):
                        continue   # tracked and deleted here: not a config
                    if os.path.islink(ws / rel):
                        raise ValueError("a link")   # unread, as on a branch tip
                    data = (ws / rel).read_bytes()
                else:
                    data = _git(ws, "cat-file", "blob", "{}:{}".format(tip, rel))
                opts = _jsonc(data.decode("utf-8-sig")).get("compilerOptions") or {}
                paths = opts.get("paths") or {}
                base = opts.get("baseUrl") or "."
                if not (isinstance(paths, dict) and isinstance(base, str)):
                    raise ValueError("paths is not an object")
            except (OSError, CheckError, ValueError, AttributeError, UnicodeDecodeError):
                self.unparsed += 1
                continue
            self.read += 1
            root = os.path.normpath(os.path.join(d, base)).replace(os.sep, "/")
            root = "" if root == "." else _norm(root)
            targets = {k: [v for v in vs if isinstance(v, str)] for k, vs in paths.items()
                       if isinstance(k, str) and isinstance(vs, list) and k.count("*") <= 1}
            # A `baseUrl` outside the workspace names nothing here to resolve against.
            if targets and root is not None:
                self.aliases[d] = (root, targets)

    @staticmethod
    def _nearest(rel_dir: str, dirs) -> str | None:
        d = rel_dir
        while True:
            if d in dirs:
                return d
            if not d:
                return None
            d = d.rsplit("/", 1)[0] if "/" in d else ""

    def candidates(self, rel_dir: str, token: str, quoted: bool) -> list[tuple[str, bool]]:
        """(workspace path, complete it as a resolver would) for each path TOKEN names
        through the configuration that governs REL_DIR. An alias applies only to a quoted,
        non-relative token: TypeScript maps import specifiers and never a `./` or `../`
        one, and a catch-all `"*"` pattern still maps every quoted word. A `public/` URL is
        served by its exact name, so it is not completed."""
        out: list[tuple[str, bool]] = []
        relative = token.startswith(("./", "../"))
        d = self._nearest(rel_dir, self.aliases) if quoted and not relative else None
        if d is not None:
            base, targets = self.aliases[d]
            star, best = None, None
            if token in targets:
                best = token
            else:
                # TypeScript takes the matching pattern with the longest prefix.
                for key in targets:
                    if "*" not in key:
                        continue
                    pre, post = key.split("*")
                    if (token.startswith(pre) and token.endswith(post)
                            and len(token) >= len(pre) + len(post)
                            and (best is None or len(pre) > len(best.split("*")[0]))):
                        best, star = key, token[len(pre):len(token) - len(post)]
            for sub in targets.get(best, []) if best is not None else []:
                c = _norm(os.path.join(base, sub.replace("*", star) if star is not None
                                       else sub))
                if c:
                    out.append((c, True))
        if token.startswith("/") and not token.startswith("//"):
            d = self._nearest(rel_dir, self.public)
            if d is not None:
                c = _norm(os.path.join(d, "public", token.lstrip("/")))
                if c:
                    out.append((c, False))
        return out


class Matcher:
    def __init__(self, files: set[str]):
        self.files = files
        self.by_stem: dict[str, set[str]] = {}
        self.by_name: dict[str, set[str]] = {}
        self.by_dir: dict[str, set[str]] = {}
        for f in files:
            self.by_stem.setdefault(_stem(f), set()).add(f)
            self.by_name.setdefault(f.rsplit("/", 1)[-1], set()).add(f)
            parts = f.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                self.by_dir.setdefault("/".join(parts[:i]), set()).add(f)

    def _exact(self, cand: str, exts: tuple[str, ...]) -> set[str]:
        """`cand` itself, or with one of EXTS, or its `index`/`__init__` with one."""
        hits = {cand} & self.files
        for stem in (cand, cand + "/index", cand + "/__init__"):
            hits |= {f for f in self.by_stem.get(stem, ()) if f.endswith(exts)}
        return hits

    def token(self, rel_dir: str, token: str, quoted: bool, glob: str = "") -> set[str]:
        t, aliased = token, False
        if t.startswith("$"):
            # `$ROOT/config/x.sh`, `${DIR}/x`: the variable is a root nobody can resolve.
            if "/" not in t:
                return set()
            t, aliased = t.split("/", 1)[1], True
        for prefix in ("@/", "~/", "#/"):
            if t.startswith(prefix):
                t, aliased = t[len(prefix):], True
                break
        if t.startswith("/"):
            t, aliased = t.lstrip("/"), True
        comps = [x for x in t.split("/") if x not in ("", ".", "..")]
        if not comps:
            return set()
        path_like = "/" in token
        exts = _PATH_EXT if path_like and "." not in comps[-1] else ()
        cands = [] if aliased else [_norm(os.path.join(rel_dir, t))]
        cands.append(_norm(t))
        hits: set[str] = set()
        for c in {c for c in cands if c}:
            hits |= self._exact(c, exts)
        # A directory read whole, in a string literal: one beside the referencing file
        # (`Path(__file__).parent / "fixtures"`), or a path of two or more components from
        # the root, where test runners stand (`Path("tests/fixtures")`). A glob names only
        # the files its pattern matches, beside the file or from the root. Every other
        # mention of a directory (`frontend/`, an unquoted path, a bare `**`) is not a read
        # of its files: measured on one consumer, resolving those reported every ignored file
        # under `frontend/` and `data/` from task text, comments and CI config.
        if glob:
            if glob.strip("*/") and not aliased:
                pat = _glob_re(glob)
                for d in {_norm(os.path.join(rel_dir, t)), _norm(t)}:
                    if d:
                        hits |= {f for f in self.by_dir.get(d, ())
                                 if pat.match(f[len(d) + 1:])}
        elif quoted and not aliased:
            dirs = {_norm(os.path.join(rel_dir, t))}
            if len(comps) >= 2:
                dirs.add(_norm(t))
            for d in dirs:
                if d:
                    hits |= self.by_dir.get(d, set())
        if len(comps) >= 2:
            tail = "/".join(comps)
            for f in self.files:
                if f == tail or f.endswith("/" + tail):
                    hits.add(f)
                elif exts and f.endswith(exts) and (
                        _stem(f) == tail or _stem(f).endswith("/" + tail)):
                    hits.add(f)
        elif "/" not in token and "." in comps[0]:
            # A bare name: `a.json` or `.env`, not `env`, `index` or `./a.json`.
            hits |= self.by_name.get(comps[0], set())
        return hits

    def resolved(self, cand: str) -> set[str]:
        """A path the resolver configuration named, completed as a resolver completes it."""
        exts = _PATH_EXT if "." not in cand.rsplit("/", 1)[-1] else ()
        return self._exact(cand, exts)

    def module(self, cand: str) -> set[str]:
        hits = self._exact(cand, _PY_EXT)
        if "/" in cand:
            # A `src/` layout: `mypkg/local` is `src/mypkg/local.py`.
            for f in self.files:
                if f.endswith(_PY_EXT) and (_stem(f).endswith("/" + cand)
                                            or _stem(f).endswith("/" + cand + "/__init__")):
                    hits.add(f)
        return hits


def references(ws: Path, base: str, branch: str | None = None
               ) -> tuple[dict[str, tuple[str, int]], int, int, int, int, Resolver]:
    """({ignored file: first referencing (file, line)}, files, dirs, lines, line files,
    the resolver configuration read)."""
    files, dirs = ignored_files(ws)
    lines = added_lines(ws, base, branch)
    matcher = Matcher(files)
    resolver = Resolver(ws, _tip(ws, branch))
    first: dict[str, tuple[str, int]] = {}
    open_from: tuple[str, str] | None = None   # (file, module) of a `from x import (`
    for rel, n, text in lines:
        rel_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        hits: set[str] = set()
        for m in _TOKEN.finditer(text):
            token = m.group(0)
            if any(ch.isalnum() for ch in token):
                quoted = m.start() > 0 and text[m.start() - 1] in "\"'`"
                glob = ""
                if text[m.end():m.end() + 1] == "*" and token.endswith("/"):
                    glob = re.match(r"[^\s\"'`),;]*", text[m.end():]).group(0)
                hits |= matcher.token(rel_dir, token, quoted, glob)
                for cand, complete in resolver.candidates(rel_dir, token, quoted):
                    hits |= matcher.resolved(cand) if complete else {cand} & matcher.files
        if rel.endswith((".py", ".pyi")):
            line = text
            if open_from and open_from[0] == rel:
                # A parenthesised import continues until `)`: its names are modules too.
                line = "from {} import {}".format(open_from[1], text.split(")")[0])
                if ")" in text:
                    open_from = None
            else:
                om = _PY_OPEN_FROM.match(text)
                open_from = (rel, om.group(1)) if om else None
            for cand in _module_candidates(rel_dir, line):
                hits |= matcher.module(cand)
        for h in sorted(hits):
            first.setdefault(h, (rel, n))
    return first, len(files), dirs, len(lines), len({r for r, _, _ in lines}), resolver


def _rev_parse(where: Path, *args: str) -> Path:
    out = Path(os.fsdecode(_git(where, "rev-parse", *args)).strip())
    return (out if out.is_absolute() else where / out).resolve()


def _main_root(where: Path) -> Path | None:
    """The main checkout of the repository WHERE belongs to, or None when it cannot be told.

    From the main working tree itself (its git dir IS the common dir) that is its own
    top level: right under `--separate-git-dir` and inside a submodule, where the common
    dir's parent is some other directory. From a linked worktree it is the common dir's
    parent, and only when that is a working tree whose `.git` leads back to the common dir;
    otherwise (a separate git dir seen from a linked worktree) nothing names it.
    """
    git_dir = _rev_parse(where, "--absolute-git-dir")
    common = _rev_parse(where, "--git-common-dir")
    if git_dir == common:
        return _rev_parse(where, "--show-toplevel")
    parent = common.parent
    try:
        if parent.is_dir() and _rev_parse(parent, "--absolute-git-dir") == common:
            return _rev_parse(parent, "--show-toplevel")
    except CheckError:
        pass
    return None


def _callers_main(ws: Path) -> Path | None:
    """The main checkout of the repository the CALLER stands in, not the workspace's own:
    a `--clone` workspace is its own repository, whose common dir is its own `.git`."""
    try:
        return _main_root(Path.cwd())
    except CheckError:
        return _main_root(ws)


def _has_copy(root: Path, ws: Path, rel: str) -> bool:
    """A byte-identical regular file at the same path in the main checkout, which is not
    the workspace's own file reached through a link."""
    other = root / rel
    if other.is_symlink() or not other.is_file():
        return False
    real, base = os.path.realpath(other), os.path.realpath(ws)
    if real == base or real.startswith(base + os.sep):
        return False
    return filecmp.cmp(ws / rel, other, shallow=False)


def _same_repo(a: Path, b: Path) -> bool:
    return _rev_parse(a, "--git-common-dir") == _rev_parse(b, "--git-common-dir")


def _clone_tip_matches(ws: Path, branch: str) -> None:
    """A `--clone` workspace is its own repository, and Step 4a merges THIS repository's
    BRANCH. A clone whose tip differs from it would be checked on commits that do not
    merge, and a file committed only in the clone would read as clean. Raises when they
    differ; does nothing when the caller stands in no repository or in the same one."""
    try:
        here = Path.cwd()
        if _same_repo(here, ws):
            return
    except CheckError:
        return
    theirs = os.fsdecode(_git(ws, "rev-parse", "--verify", "--quiet",
                              "refs/heads/{}^{{commit}}".format(branch))).strip()
    env = {k: v for k, v in os.environ.items() if k not in _DISCOVERY}
    r = subprocess.run(["git", "-C", str(here), "rev-parse", "--verify", "--quiet",
                        "refs/heads/{}^{{commit}}".format(branch)], capture_output=True, env=env)
    ours = os.fsdecode(r.stdout).strip()
    if ours != theirs:
        raise CheckError("{} is at {} in the clone and {} here; bring this repository's branch "
                         "to the clone's tip first: re-run /review-close, whose Step 1-pre "
                         "does".format(branch, theirs[:12], ours[:12] or "absent"))


def run(ws: Path, base: str, branch: str | None) -> int:
    if branch is not None:
        _clone_tip_matches(ws, branch)
    first, n_files, n_dirs, n_lines, n_line_files, resolver = references(ws, base, branch)
    root = _callers_main(ws)
    reported = 0
    for path in sorted(first):
        if root == ws:
            # The main checkout itself (`--branch`), which no step removes, or a clone
            # checked from inside, which no step removes either.
            label = "not compared: the workspace is its own main checkout"
        elif root is None:
            label = "not compared: the main checkout cannot be found from here"
        else:
            label = ("the main checkout has an identical copy" if _has_copy(root, ws, path)
                     else "only copy")
        rel, n = first[path]
        print("IGNORED-REF: {} <- {}:{} ({})".format(path, rel, n, label))
        reported += 1
    print("IGNORED-REFS: {} ({} ignored files; {} ignored directories not read; "
          "{} added lines in {} files; {} resolver configs read{}; "
          "names built at run time not read)".format(
              "{} found".format(reported) if reported else "none",
              n_files, n_dirs, n_lines, n_line_files, resolver.read,
              ", {} not parsed".format(resolver.unparsed) if resolver.unparsed else ""))
    return 1 if reported else 0


_STAMP = re.compile(r"\d{8}T\d{6}Z(-\d+)?\Z")


def _free(path: Path, dest: Path) -> bool:
    """Nothing occupies PATH, and every ancestor up to DEST is a directory or absent."""
    if os.path.lexists(path):
        return False
    for anc in path.relative_to(dest).parents:
        a = dest / anc
        if os.path.lexists(a) and (os.path.islink(a) or not a.is_dir()):
            return False
    return True


def preserve(ws: Path, dest_arg: str) -> int:
    """Copy every ignored file the main checkout has no identical copy of to DEST.

    Referenced or not: this is Step 3b step 0b's data-loss guard, and a reference matcher
    is never complete (Wade, 2026-10-02). DEST must be gitignored in the main checkout, so
    a preserved file never shows up as untracked work there. A file already preserved,
    in DEST or in an earlier timestamped run under it, is not copied again; a differing
    one goes under a fresh timestamp, so nothing preserved is overwritten.
    """
    root = _callers_main(ws)
    if root is None:
        raise CheckError("the main checkout cannot be found from here; run from it")
    if root == ws:
        raise CheckError("the workspace is the main checkout; nothing is removed, nothing to preserve")
    dest = (Path.cwd() / dest_arg).resolve()
    try:
        rel_dest = dest.relative_to(root)
    except ValueError:
        raise CheckError("{} is not inside the main checkout {}".format(dest, root)) from None
    if rel_dest.as_posix() in ("", "."):
        raise CheckError("the destination is the main checkout itself")
    probe = rel_dest.as_posix() + "/.preserve-probe"
    env = {k: v for k, v in os.environ.items() if k not in _DISCOVERY}
    if subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--no-index", probe],
                      env=env).returncode != 0:
        raise CheckError("{} is not gitignored in the main checkout; a preserved file "
                         "would show up there as untracked work".format(rel_dest))
    files, _ = ignored_files(ws)
    runs = sorted(d for d in dest.iterdir() if d.is_dir() and _STAMP.match(d.name)) \
        if dest.is_dir() else []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    n = 1
    while os.path.lexists(dest / stamp):
        n += 1
        stamp = "{}-{}".format(stamp.split("-")[0], n)
    done = already = copied_bytes = with_copy = gone = 0
    for rel in sorted(files):
        src = ws / rel
        if not src.is_file():
            gone += 1
            continue
        if _has_copy(root, ws, rel):
            with_copy += 1
            continue
        if any(c.is_file() and not c.is_symlink() and filecmp.cmp(src, c, shallow=False)
               for c in [dest / rel] + [r / rel for r in runs]):
            already += 1
            continue
        target = dest / rel
        if not _free(target, dest):
            target = dest / stamp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied_bytes += src.stat().st_size
        done += 1
        print("PRESERVED: {} -> {}".format(rel, target))
    print("PRESERVE: {} preserved ({} bytes), {} already preserved, {} with a copy in the "
          "main checkout, {} gone before it was read -> {}".format(
              done, copied_bytes, already, with_copy, gone, rel_dest))
    return 0


# The literal placeholders the skills print; a `<` in a real branch or file name is legal.
_PLACEHOLDERS = ("<workspace>", "<worktree-path>", "<default branch>", "<branch>",
                 "<sanitized branch>", "<path>", "<WORKSPACE>", "<BASE>", "<DEST>", "<NAME>")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Gitignored files the work references (Q-633).")
    p.add_argument("workspace")
    p.add_argument("base", nargs="?")
    p.add_argument("--branch", metavar="NAME")
    p.add_argument("--preserve", metavar="DEST")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        # A file name the stdout codec cannot encode must not crash a report about it.
        sys.stdout.reconfigure(errors="backslashreplace")
    if (a.preserve is None) == (a.base is None) or (a.preserve is not None and a.branch):
        p.error("give BASE (the check) or --preserve DEST (the copy), not both")
    operands = tuple(x for x in (a.workspace, a.base, a.branch, a.preserve) if x is not None)
    if any(not x.strip() or any(ph in x for ph in _PLACEHOLDERS) for x in operands):
        print("ERROR: placeholder not substituted: {!r}".format(list(operands)),
              file=sys.stderr)
        return 3
    try:
        ws = Path(a.workspace).resolve()
        if not ws.is_dir():
            raise CheckError("no such workspace directory: {}".format(ws))
        top = Path(os.fsdecode(_git(ws, "rev-parse", "--show-toplevel")).strip()).resolve()
        if top != ws:
            raise CheckError("{} is not the top of its git work tree ({} is)".format(ws, top))
        if a.preserve is not None:
            return preserve(ws, a.preserve)
        return run(ws, a.base, a.branch)
    except (CheckError, OSError) as exc:
        print("ERROR: the ignored-file check did not run: {}".format(exc), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — exit 1 means "found"; a crash must not read so
        print("ERROR: the ignored-file check did not run: {}: {}".format(
            exc.__class__.__name__, exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
