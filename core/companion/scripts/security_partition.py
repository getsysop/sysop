#!/usr/bin/env python3
"""Residual assignment for ``/security-audit`` — the files no map section reaches (Phase 231).

``/security-audit`` dispatches **per OWASP category**: each agent is handed "all files where
my category is listed under ``Check:`` in ``.claude/security_map.md``". That mechanism works,
and this tool does not touch it. What it cannot do — and Step 3-0 says so in its own words —
is establish that the union of the agents' assigned files spans the Step 1 manifest. A file
that **no section matches** is assigned to nobody, and nothing counts it.

That is not a rare corner. **30 of the 36 shipped ``security_map`` sections are
all-placeholder** (``## <api module>/routes/**/*.py — API Endpoints``), binding nothing until
a consumer localizes them, and markdown is never token-substituted at install time. On a
fresh install the six sections that bind are all infrastructure — shell scripts,
``Dockerfile``, ``.gitignore``, CI workflows, skill markdown, ``pyrightconfig.json`` — so the
audit reaches those and **not the application code**. Measured on a realistic four-pack
install: 6 of the consumer's 14 files owned, 8 unowned, and all 8 of the unowned were the API
server, its routes, auth, the pipeline, a utility module, a frontend component, a SQL migration
and the tests. (An earlier version of this list named seven of the eight and still said
"all 8" — the omitted one was the utility module.)

**The inversion this tool makes.** Ownership cannot be keyed on map *sections*: 30 of 36 bind
nothing, so section-keyed ownership assigns a real consumer's routes and auth to nobody. So
this does not partition the map. It partitions the **manifest** — always real, always
complete — and demotes the map to what it can actually be when most of its globs are
placeholders: a *rule* source, not a *coverage* source. Mapped files keep the category
dispatch untouched. The residual is a set difference, disjoint from the mapped set by
construction, and it is **largest exactly when the map is least localized**, which is the
case that was silently empty before.

**The manifest is the skill's, passed as a file** (``--manifest-file``, required): the Step 1
list ``/security-audit`` built — its scope, its exclusions, its always-include files — one
repo-relative path per line. This script defines no manifest of its own; listing ``git
ls-files`` here sized the residual over files Step 1 had excluded. The file is read as UTF-8
(a BOM is dropped). Blank lines are skipped, a leading ``./`` is dropped, CRLF reads as LF,
and a line git C-quoted (Step 1's recipes run with ``core.quotePath`` on) counts as the
tracked name it decodes to: none of them names a different file. A path listed twice, or one ``git ls-files`` does not list (deleted,
untracked, a directory, outside the repo), is refused — status ``bad-manifest``, nothing
assessed — because counting it would change ``manifest`` or the residual. A file that cannot
be read is ``unreadable-manifest``; one listing no path is ``empty``.

Design stance — **advisory and honest, never a gate.** It reports; it does not block, and
every degraded path (no map, no ``CLAUDE.md``, empty repo, not a git tree, a non-UTF-8
tracked name, a manifest file it cannot read or will not count) exits 0 with a
stated reason rather than failing the round. Only an unexpected crash, or a usage error such as
a missing ``--manifest-file``, exits 2. Same stance
as ``scope_overlap.py``, and for the same reason: a partial audit beats a refused one.

**Assignment is not coverage, and this tool refuses to conflate them.** Packing a 486-file
residual into four agents and calling it ``Full`` because every file landed in a bucket is the
laundering the ``Full``/``Sampled`` arithmetic exists to prevent — 121 files is not a review.
(An earlier draft of this paragraph said "436 … 109 files each". That pair reproduces on no
fixture this phase built; the measured residual on the 533-file corpus is 486.)
Each agent is credited with at most ``--per-agent`` files; everything past that is reported
as the shortfall, with the agent count ``Full`` would have required. That check is the
reason this file exists in the shape it does: the first cut reported ``Full`` over a
533-file repo it had reviewed a quarter of.

Usage:
    python3 sysop/scripts/security_partition.py --manifest-file <path>          # human report
    python3 sysop/scripts/security_partition.py --json --manifest-file <path>   # for the skill
    python3 sysop/scripts/security_partition.py --manifest-file <path> --budget 6 --per-agent 30

Exit codes:
    0   report produced (including every "could not assess" degrade path)
    2   usage error (a missing --manifest-file, a flag value below 1) or an unexpected error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Parse semantics are lifted from tests/test_dispatch_assignment_reconciliation.py, which is
# this repo's source of truth for reading these maps. Kept identical on purpose — two readers
# of one format drift. (An earlier version of this note cited `_sanitize_log` as the precedent;
# the log records that helper as duplicated deliberately, not as having drifted, so the
# citation was withdrawn rather than repaired.)
SECTION_RE = re.compile(r"^## (?P<globs>.+?) — (?P<name>.+?)\s*$", re.M)
CHECK_MARKER = re.compile(r"\*\*Check\b[^*\n]*\*\*:?|\*\*Check\*\*:?", re.I)
SKIP_MARKER = re.compile(r"\*\*Skip\b", re.I)
BOLD_LEAD = re.compile(r"^\s*-\s+\*\*(?P<label>[^*]+?)\*\*")
OWASP_CODES = tuple(f"A{n:02d}" for n in range(1, 11))

EXCLUSIONS_HEADING = "## Map coverage exclusions"

# A section glob's brace list is expanded before git sees it (git has none), with the same
# expansion and the same ceiling as `security_map_filter.py`'s `tokens()`, so the two readers of
# one map agree on what a `*.{ts,tsx}` glob names. Past the ceiling a glob binds nothing here and
# is named in the notes: binding it would mark files mapped that no category agent is sent.
BRACE_EXPAND_LIMIT = 256

DEFAULT_BUDGET = 4
DEFAULT_PER_AGENT = 25
# The group cap DEFAULTS TO `per_agent` and is not an independent knob by accident. A group is
# indivisible — it is what keeps one agent's assignment coherent — so a group larger than one
# agent's credit can never be covered, however many agents you add. With the two decoupled the
# report published a false number: 90 residual files, "4 agents would reach Full at 25 each"
# (4 x 25 = 100 >= 90), while the actual packing reviewed 67, because one 39-file group could
# only ever be credited 25. Tying them makes the arithmetic true.
DEFAULT_GROUP_CAP = None


# --------------------------------------------------------------------------- #
# map parsing
# --------------------------------------------------------------------------- #

def _token_of(bullet: str) -> str | None:
    """The category token a ``Check:`` bullet opens with, or None."""
    m = BOLD_LEAD.match(bullet if bullet.lstrip().startswith("-") else f"- {bullet}")
    if not m:
        return None
    label = m.group("label").split(":")[0].split("(")[0].strip()
    return label.split()[0] if label.split() else None


def parse_sections(text: str) -> list[dict]:
    """``## <globs> — <Name>`` sections with their globs and category tokens.

    Reads the whole ``Check:`` region rather than its bullets: the shipped maps use four
    marker shapes and a bullets-only parse silently drops three of them, which makes a
    section that reads as needing no auditor indistinguishable from one that has none.
    """
    out: list[dict] = []
    text = _strip_fences(text)
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end]
        globs = re.findall(r"`([^`]+)`", m.group("globs"))

        marker = CHECK_MARKER.search(body)
        if marker:
            region = body[marker.end():]
            skip = SKIP_MARKER.search(region)
            region = region[: skip.start()] if skip else region
            # Fold the marker text back in: `**Check: A01** — …` puts the code inside the bold.
            region = marker.group(0) + region
        else:
            region = ""

        bullets = [b.strip() for b in re.findall(r"^\s*-\s+(.*)$", region, flags=re.M) if b.strip()]
        cats = {t for t in (_token_of(b) for b in bullets) if t}
        marker_line = region.split("\n", 1)[0]
        for code in OWASP_CODES:
            if re.search(rf"\b{code}\b", marker_line):
                cats.add(code)

        out.append({
            "name": m.group("name"),
            "globs": globs,
            "cats": sorted(cats),
            # A section whose globs are ALL `<placeholder>` tokens binds no file until the
            # consumer localizes it. A section that MIXES concrete and placeholder globs
            # binds exactly what its concrete globs match — a "header contains `<…>`"
            # predicate would wrongly condemn those, and the shipped maps have two. The test is
            # per expanded alternative: `{<api module>,lib}/*.py` binds `lib/*.py`.
            "placeholder": bool(globs) and all(_all_placeholder(g) for g in globs),
        })
    return out


def _all_placeholder(glob: str) -> bool:
    """Whether every alternative ``glob`` names is still in ``<…>`` form. A glob past the brace
    ceiling is not expanded, and reads as placeholder only if it carries a ``<`` at all."""
    if brace_count(glob.strip()) > BRACE_EXPAND_LIMIT:
        return "<" in glob
    alts = glob_alternatives(glob)
    return bool(alts) and all("<" in a for a in alts)


def _strip_fences(text: str) -> str:
    """Blank out fenced code blocks, keeping line numbering intact.

    Markdown examples are content, not instructions. `WORKFLOW.md` ships fenced *templates*
    for consumers to copy — including whole `## <globs> — <Name>` section skeletons — and a
    parse that reads them treats a copied template as a live declaration. Reproduced by the
    round: a fenced authoring note containing `## `**`` — Everything In My Repo` made every
    file in the repo read as mapped, residual 0, verdict `Full`.

    An unterminated fence blanks to end-of-text, which is the safe direction: content inside
    an unclosed fence is ignored rather than half-read.

    A fence closes only on its own character, at least as long, with no info string: the
    toggle this replaced flipped on any marker, so a ```` ```python ```` line inside a block
    ended it and a backtick run with a backtick after it (an inline span) opened one. A closer
    indented more than three columns past its opener is content: a list item's ``` inside a
    column-0 example block is not its end.
    """
    out, fence, at = [], None, 0
    for ln in text.split("\n"):
        if fence:
            if fence_closes(ln, fence, at):
                fence = None
            out.append("")
        elif fence_mark(ln):
            fence, at = fence_mark(ln), indent_of(ln)
            out.append("")
        else:
            out.append(ln)
    return "\n".join(out)


# `security_map_filter.py`'s `fence_mark` / `fence_closes`, copied rather than imported (that
# module imports this one), less one leg: a marker indented four or more spaces still counts
# here. `parse_exclusions` matches its list items and headings at any indent, and a fence
# inside a list item sits four spaces in, where CommonMark reads it as a fence.
# `tests/test_fence_opener_shared_readers.py` holds the two to the same verdicts up to three
# spaces.
def fence_mark(line: str):
    """`(char, length)` if the line is a fence marker, else None. A backtick run followed by
    another backtick is an inline span, not a fence (CommonMark); a tilde run may be."""
    s = line.lstrip()
    for ch in ("`", "~"):
        if s.startswith(ch * 3):
            n = len(s) - len(s.lstrip(ch))
            if ch == "`" and "`" in s[n:]:
                return None
            return ch, n
    return None


def indent_of(line: str) -> int:
    """Columns of leading whitespace, a tab to the next multiple of four."""
    col = 0
    for ch in line:
        if ch == "\t":
            col += 4 - col % 4
        elif ch.isspace():
            col += 1
        else:
            break
    return col


def fence_closes(line: str, open_mark, open_indent: int = 0) -> bool:
    """Same character, at least as long, no info string (an opener may carry one, a closer may
    not), and indented at most three columns past the opener: a list item's four-space ```
    inside a column-0 block is content, not its closer."""
    mark = fence_mark(line)
    return (bool(mark) and mark[0] == open_mark[0] and mark[1] >= open_mark[1]
            and not line.strip().strip(mark[0]) and indent_of(line) <= open_indent + 3)


def parse_exclusions(text: str) -> list[str]:
    """Globs under ``## Map coverage exclusions`` in the consumer's ``CLAUDE.md``.

    Three narrowings, each from a defect the round reproduced:

    * **HTML comments are stripped.** The installer seeds this section with a commented-out
      *example* block; reading those examples as declarations would carve `**/migrations/**`
      out of every fresh install.
    * **Any `#`-prefixed heading ends the section**, not just `## `. A `### ` subsection did
      not terminate it, so globs from an unrelated subsection were harvested as exclusions.
    * **Only the FIRST backticked glob on a list item counts**, and only when the item has the
      documented ``- `glob` — reason`` shape. Harvesting every backtick made an ordinary
      sentence — *"we deliberately do NOT exclude `api/**` or `auth/**`"* — declare exactly
      what it disclaims. Prose bullets carry backticks; declarations lead with one.

    These globs no longer remove anything from dispatch (see ``build``), so a mis-parse is now
    a wrong *count* rather than an unaudited file. The narrowings stay because a wrong count in
    a coverage report is still a coverage claim.
    """
    lines = _strip_fences(re.sub(r"<!--.*?-->", "", text, flags=re.S)).split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == EXCLUSIONS_HEADING)
    except StopIteration:
        return []
    globs: list[str] = []
    for ln in lines[start + 1:]:
        if ln.lstrip().startswith("#"):
            break
        # The documented shape: a list item whose FIRST token is a backticked glob.
        m = re.match(r"^\s*[-*]\s+`([^`]+)`", ln)
        if m:
            globs.append(m.group(1))
    return globs


# --------------------------------------------------------------------------- #
# file resolution
# --------------------------------------------------------------------------- #

class UndecodablePath(ValueError):
    """A tracked path whose name is not UTF-8; carries the name as a bash operand."""


def _bash_operand(name: bytes) -> str:
    """``name`` as a bash ANSI-C quoted word (``$'…'``) that names exactly these bytes.

    Printable ASCII other than ``\\`` and ``'`` is kept; every other byte becomes a
    two-digit ``\\xHH`` (always two digits, so a following hex character cannot be
    read into the escape). The note tells the reader to ``git mv`` the file, and a
    ``backslashreplace`` rendering (``caf\\xe9.py``) pasted into a shell names a
    file with a literal backslash — which does not exist.
    """
    keep = {c for c in range(0x20, 0x7F)} - {ord("\\"), ord("'")}
    return "$'" + "".join(chr(b) if b in keep else f"\\x{b:02x}" for b in name) + "'"


def _git_run(root: str, *args: str) -> tuple[int, str, str]:
    """``(returncode, stdout, first stderr line)``; a non-UTF-8 name in stdout raises."""
    p = subprocess.run(["git", *args], cwd=root, capture_output=True)
    err = p.stderr.decode("utf-8", "replace").strip().split("\n")[0]
    try:
        return p.returncode, p.stdout.decode("utf-8"), err
    except UnicodeDecodeError:
        bad = next(c for c in p.stdout.split(b"\0") if not _utf8(c))
        raise UndecodablePath(_bash_operand(bad)) from None


def _git(root: str, *args: str) -> str:
    return _git_run(root, *args)[1]


def _utf8(chunk: bytes) -> bool:
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _is_git_tree(root: str) -> bool:
    """A non-repo used to degrade with the EMPTY-REPO reason, which is a different fact."""
    return subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
        capture_output=True, text=True,
    ).returncode == 0


def expand_braces(g: str) -> list[str]:
    """``g`` with every ``{a,b}`` list expanded, innermost first: ``security_map_filter.py``'s
    ``tokens()`` expansion, which imports it, so both readers expand a glob alike."""
    m = re.search(r"\{([^{}]*)\}", g)
    return [g] if not m else [x for alt in m.group(1).split(",")
                              for x in expand_braces(g[:m.start()] + alt + g[m.end():])]


def brace_count(g: str) -> int:
    """How many globs ``expand_braces(g)`` would return, without building them."""
    m = re.search(r"\{([^{}]*)\}", g)
    return 1 if not m else (m.group(1).count(",") + 1) * brace_count(g[:m.start()] + "x" + g[m.end():])


def glob_alternatives(glob: str) -> list[str]:
    """The globs a map glob names: braces expanded, then each alternative's leading ``./``
    (repeatedly) and ``/`` dropped, an empty one discarded — ``security_map_filter.py``'s
    ``tokens()`` reading of one backticked glob. The caller checks ``brace_count`` first."""
    out = []
    for g in expand_braces(glob.strip()):
        while g.startswith("./"):
            g = g[2:]
        g = g.lstrip("/")
        if g:
            out.append(g)
    return out


def resolve_glob(root: str, glob: str, notes: list | None = None) -> set[str]:
    """Tracked files a map glob matches.

    Uses git's ``:(glob)`` pathspec magic, which gives ``**`` its true meaning. The plain
    pathspec does not: ``git ls-files -- 'api/**/*.py'`` silently drops the direct child
    ``api/server.py``, and ``'api/routes/**/*.py'`` returns nothing at all because ``**``
    will not match an empty path segment. Both were reproduced before this was written.

    A brace list is expanded first, since git has none: unexpanded, ``*.{ts,tsx}`` matched only
    a file literally named with the braces, so its section bound nothing and its files fell to
    the residual. Each alternative is read as ``security_map_filter.py`` reads it (a leading
    ``./`` or ``/`` dropped: git refuses ``/x`` as outside the repository), and one still in
    ``<…>`` form is dropped on its own.

    A glob git refuses binds nothing, and is NAMED in ``notes`` rather than read as an empty
    match. When the one batched call fails, each alternative is run alone, so a bad alternative
    cannot void the siblings that resolve.
    """
    def _note(text: str) -> None:
        if notes is not None and text not in notes:
            notes.append(text)

    if brace_count(glob.strip()) > BRACE_EXPAND_LIMIT:
        _note(f"map glob `{glob}` expands to more than {BRACE_EXPAND_LIMIT} globs, so it "
              "binds nothing here and its files count as residual")
        return set()
    # An unlocalized placeholder matches nothing, by construction.
    globs = [g for g in glob_alternatives(glob) if "<" not in g]
    if not globs:
        return set()
    rc, out, _ = _git_run(root, "ls-files", "-z", "--", *(f":(glob){g}" for g in globs))
    if rc == 0:
        return {p for p in out.split("\0") if p}
    hit: set[str] = set()
    for g in globs:
        rc, out, err = _git_run(root, "ls-files", "-z", "--", f":(glob){g}")
        if rc == 0:
            hit |= {p for p in out.split("\0") if p}
        else:
            _note(f"map glob `{g}`" + (f" (from `{glob}`)" if g != glob else "")
                  + f" could not be resolved by git ({err or f'exit {rc}'}), so it binds "
                  "nothing here and its files count as residual")
    return hit


def tracked(root: str) -> set[str]:
    """Every path ``git ls-files`` lists: what a manifest line may name."""
    return {p for p in _git(root, "ls-files", "-z").split("\0") if p}


def _unquote(target: str) -> str:
    """A path git C-quoted (``"caf\\303\\251.py"``, ``"tab\\tname.py"``), as written on disk.

    ``ignored_refs.py``'s ``_unquote``, copied as it is: that script does not ship in a loop
    install, and this one does. ``git ls-files`` and ``git log --name-only`` quote a name with a
    non-ASCII byte, a control character, a ``"`` or a backslash unless ``core.quotePath`` is off,
    and Step 1's recipes run with git's default.
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


def _drop_dot_slash(p: str) -> str:
    while p.startswith("./"):
        p = p[2:]
    return p


def read_manifest(path: str, known: set[str]) -> tuple[list[str], str, str]:
    """The manifest file's paths, sorted, or a status and reason that refuse it.

    Returns ``(paths, "", "")`` when every line is countable, else ``([], status, reason)``.
    Read through, because they name no different file: a leading UTF-8 BOM, blank lines, a
    leading ``./``, the ``\\r`` of a CRLF ending (universal newlines), and a line git C-quoted
    whose decoded name is tracked (a line that is itself tracked is taken as written first).
    Refused, because counting them would change a number this script reports: a path listed
    twice after decoding (``manifest`` would count one file twice) and a path ``git ls-files``
    does not list (it can never be mapped, so it would be residual whatever the map says, and
    a deleted one is a file no agent can open).
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [], "unreadable-manifest", f"could not read the manifest file {path}: {exc}"

    seen: dict[str, int] = {}
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        p = _drop_dot_slash(raw)
        if p not in known:
            decoded = _drop_dot_slash(_unquote(raw))
            if decoded in known:
                p = decoded
        seen[p] = seen.get(p, 0) + 1

    def _some(names: list[str]) -> str:
        shown = ", ".join(repr(n) for n in names[:5])
        return shown + (f", +{len(names) - 5} more" if len(names) > 5 else "")

    problems = []
    twice = sorted(p for p, n in seen.items() if n > 1)
    if twice:
        problems.append(f"{len(twice)} path(s) listed more than once: {_some(twice)}")
    untracked = sorted(p for p in seen if p not in known)
    if untracked:
        spaced = [p for p in untracked if p != p.strip() and _drop_dot_slash(p.strip()) in known]
        problems.append(f"{len(untracked)} path(s) `git ls-files` does not list — deleted, "
                        f"untracked, a directory or outside the repo: {_some(untracked)}"
                        + (f" ({len(spaced)} of them differ from a tracked path only by "
                           f"surrounding whitespace: {_some(spaced)})" if spaced else ""))
    if problems:
        return [], "bad-manifest", (
            f"the manifest file {path} was not counted: " + "; ".join(problems)
            + ". List each tracked file once, correct Step 1's count with it, and re-run")
    if not seen:
        return [], "empty", f"the manifest file {path} lists no paths"
    return sorted(seen), "", ""


def read_vendor_paths(root: str, notes: list | None = None) -> set[str]:
    """The files Sysop itself installed, from the lock's own ``managed_paths``.

    DERIVED, never guessed. A hardcoded prefix list (``.claude/``, ``sysop/``, ``.agents/``)
    would drift the moment the vendor layout moves — which it already did once, when Phase 128
    relocated the consumer footprint into ``sysop/``. The lock is the installer's own record of
    what it wrote, so it is exact for this install and cannot go stale.

    These are NOT excluded. Sysop auto-excluding its own shipped code from the security audit
    it ships would be a self-serving default, and a supply-chain smell besides: this code runs
    in the consumer's repo. They are counted and reported separately, and ranked BEHIND the
    consumer's own code when the agent budget binds — on a fresh four-pack install 78 of the
    90 residual files are Sysop's, so without the ranking the sweep spends its whole budget on
    the installer's output and never reaches the application.
    """
    lock = os.path.join(root, ".claude", "sysop.lock")
    # No lock is an uninstalled tree and says nothing. A lock that EXISTS but cannot be read
    # is named in `notes`: reading it as empty counts Sysop's own files as the consumer's.
    unread = (f"could not read {os.path.join('.claude', 'sysop.lock')} ({{}}) — Sysop's "
              "installed files are counted as the consumer's own")
    try:
        with open(lock, encoding="utf-8") as fh:
            data = json.load(fh)
        # `isinstance(data, dict)` BEFORE `.get`. A lock that is valid JSON but not an object
        # (`null`, `[1,2,3]`, `"x"`, `123`, `true`) crashed the whole report with exit 2 — while
        # a lock that was not JSON at all exited 0. `install.sh`'s `lock_field()` was hardened
        # against this identical pair in Phase 148, and its comment names it verbatim:
        # "json.load raising, or .get on a non-object".
        if not isinstance(data, dict):
            if notes is not None:
                notes.append(unread.format(f"not a JSON object: {type(data).__name__}"))
            return set()
        paths = data.get("managed_paths")
        return set(p for p in paths if isinstance(p, str)) if isinstance(paths, list) else set()
    except FileNotFoundError:
        return set()
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        if notes is not None:
            notes.append(unread.format(f"{type(exc).__name__}: {exc}"))
        return set()


# --------------------------------------------------------------------------- #
# the partition
# --------------------------------------------------------------------------- #

def group_residual(files: list[str], cap: int = DEFAULT_PER_AGENT) -> dict[str, list[str]]:
    """Directory groups, deepened only where a group exceeds ``cap``.

    Grouping by directory is what keeps a reviewer's assignment coherent — a whole directory
    reads as a subject, a size-balanced pile does not.
    """
    groups: dict[str, list[str]] = {}
    for f in files:
        parts = f.split("/")
        groups.setdefault(parts[0] if len(parts) > 1 else f, []).append(f)

    depth = 1
    while depth < 5:
        depth += 1
        over = {k for k, v in groups.items() if len(v) > cap}
        if not over:
            break
        out: dict[str, list[str]] = {}
        for k, v in groups.items():
            if k in over:
                for f in v:
                    p = f.split("/")
                    # A path SHALLOWER than the current depth is its own group, never a
                    # shared sink: routing them all to one "(root)" key and then letting an
                    # unsplit bucket assign over it silently DELETED every such file. The
                    # partition invariant caught that on the first run.
                    out.setdefault("/".join(p[:depth]) if len(p) > depth else f, []).append(f)
            else:
                # Accumulate rather than assign. **This is defence in depth, not the fix** —
                # and the distinction is measured, not assumed. The original defect was the
                # PAIR: a shallow path routed to a shared `(root)` sink above, plus `out[k] =
                # v` here dropping whatever the sink had accumulated. With the sink gone, a
                # differential fuzz over 120,000 random trees found **zero** inputs where the
                # two forms differ, so reverting this line alone is currently a no-op. It
                # stays because it costs nothing and the coupling is not obvious to the next
                # reader — but no test can pin it, and claiming one does would be false.
                out.setdefault(k, []).extend(v)
        if out == groups:
            break
        groups = out
    return dict(sorted(groups.items()))


def pack(groups: dict[str, list[str]], budget: int, vendor: set[str] | None = None) -> list[dict]:
    """Pack directory groups into at most ``budget`` bins, largest group first.

    Packing rather than splitting, because the agent budget is the binding constraint:
    keyed on directory alone, a 141-file repo produced 55 buckets, most of them one file.
    And packing rather than *taking* the first ``budget`` groups, because taking was
    alphabetical — it dispatched ``.agents``/``.claude``/``CLAUDE.md`` and dropped the
    consumer's own ``api`` and ``auth``, the exact files the sweep exists for.
    """
    if not groups:
        return []
    vendor = vendor or set()

    def _rank(kv: tuple[str, list[str]]) -> tuple[int, int, str]:
        name, fs = kv
        # Consumer code first (0), Sysop's own installed footprint last (1). Within a tier,
        # largest group first so first-fit-decreasing packs tightly.
        tier = 1 if fs and all(f in vendor for f in fs) else 0
        return (tier, -len(fs), name)

    bins: list[list[tuple[str, list[str]]]] = [[] for _ in range(max(1, min(budget, len(groups))))]
    for name, fs in sorted(groups.items(), key=_rank):
        target = min(range(len(bins)), key=lambda i: (sum(len(x[1]) for x in bins[i]), i))
        bins[target].append((name, fs))
    # Files stay in the bin's RANKED group order, not alphabetical. Sorting here looked
    # harmless and silently undid the ranking: truncating a bin to its credit then dropped
    # whichever files sorted late, so a budget-bound run reported "10 of your files unreached"
    # while keeping thirty of Sysop's — the exact inversion the ranking exists to prevent.
    return [
        {"agent": f"residual-{i + 1}",
         "groups": [n for n, _ in b],
         "files": [f for _, fs in b for f in sorted(fs)]}
        for i, b in enumerate(bins) if b
    ]


def _budget_for_full(groups: dict[str, list[str]], per_agent: int, total: int,
                     vendor: set[str] | None = None) -> int:
    """The smallest budget at which THIS packer actually reaches every residual file.

    Computed by running the real packer, not by arithmetic, and that is the whole point. This
    number has been wrong three times:

      1. `ceil(total / per_agent)` with the group cap DECOUPLED from `per_agent` — an
         undercount, because one indivisible 39-file group could only ever be credited 25, so
         "4 agents" was published over a residual that packed to 67 of 90.
      2. A per-group sum — a wild overcount (360 agents for 486 files), having forgotten that
         groups share a bin.
      3. a simulation that packed WITHOUT the consumer-first ranking the real call uses, so it
         answered a different question and named a budget that reports `Sampled`.
      4. `ceil(total / per_agent)` WITH the cap coupled, which looked airtight and is still
         only a **lower bound**: bin-packing indivisible items can need more bins than the
         ceiling. Measured on a 486-file residual at `--per-agent 25`, it claimed 20 and
         running at 20 reported `Sampled`.

    A number a reader acts on has to survive being acted on, so it is now derived by acting on
    it. Bounded above by one bin per group, which always suffices since no group exceeds the cap.
    """
    if per_agent < 1 or not groups:
        return 0
    total_cap = sum(min(len(v), per_agent) for v in groups.values())
    if total_cap < total:                       # no budget can cover it — say so, don't guess
        return 0

    def covers(budget: int) -> bool:
        packed = pack(groups, budget, vendor)
        return sum(min(len(a["files"]), per_agent) for a in packed) >= total

    # BINARY search, not a linear walk. Coverage is monotone in the budget — more bins means
    # smaller bins means less truncation — verified over 4,000 random group sets with zero
    # violations. The linear form was cubic and a review lens timed it: 32s on a 10k-file
    # repo, ~4 minutes at 20k, ~27 minutes at 42k, all of it to produce one advisory number
    # on a tool whose whole design stance is "never block the round".
    lo, hi = max(1, -(-total // per_agent)), len(groups)
    if not covers(hi):
        return 0
    while lo < hi:
        mid = (lo + hi) // 2
        if covers(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def build(root: str, manifest_file: str, budget: int, per_agent: int,
          group_cap: int | None = None) -> dict:
    """The whole derivation over the manifest ``manifest_file`` lists. Returns the report
    structure; raises nothing on a normal degrade."""
    notes: list[str] = []

    map_path = os.path.join(root, ".claude", "security_map.md")
    if not os.path.exists(map_path):
        return {"status": "no-map", "notes": [
            f"no {os.path.relpath(map_path, root)} — nothing to reconcile against. "
            "Run the installer, or pass --root at the consumer repo root."], "assignments": []}

    try:
        with open(map_path, encoding="utf-8") as fh:
            sections = parse_sections(fh.read())
    except (OSError, UnicodeDecodeError) as exc:
        # Unreadable, invalid UTF-8, or a directory where a file belongs. The docstring
        # promises every degraded path exits 0 with a stated reason; three of them did not.
        return {"status": "unreadable-map", "notes": [
            f"could not read {os.path.relpath(map_path, root)}: {exc}"], "assignments": []}
    if not sections:
        notes.append("the security map parsed to zero sections — the `## <globs> — <Name>` "
                     "header shape has drifted; every file below will read as residual")

    claude_md = os.path.join(root, "CLAUDE.md")
    exclusions: list[str] = []
    try:
        with open(claude_md, encoding="utf-8") as fh:
            exclusions = parse_exclusions(fh.read())
    except FileNotFoundError:
        notes.append("no CLAUDE.md — no coverage exclusions read")
    except (OSError, UnicodeDecodeError) as exc:
        notes.append(f"could not read CLAUDE.md ({exc}) — no coverage exclusions read")

    if not _is_git_tree(root):
        return {"status": "not-a-git-tree", "assignments": [], "notes": notes + [
            f"{root} is not a git work tree — the manifest's paths are checked against "
            "`git ls-files`"]}
    try:
        known = tracked(root)
    except UndecodablePath as exc:
        # A partial partition would silently drop the file, and the partition promises
        # every tracked file an owner — so it names the file and assesses nothing.
        return {"status": "undecodable-path", "assignments": [], "notes": notes + [
            f"tracked path {exc} is not valid UTF-8, so the manifest cannot be "
            f"partitioned; rename it from {root} with `git mv -- {exc} <new UTF-8 name>` "
            "and re-run"]}
    if not known:
        return {"status": "empty", "notes": notes + ["no tracked files"], "assignments": []}
    files, refused, reason = read_manifest(manifest_file, known)
    if refused:
        return {"status": refused, "notes": notes + [reason], "assignments": []}
    in_manifest = set(files)

    # mapped: matched by at least one non-placeholder section that carries a category. A
    # section glob resolves over every tracked file, so each hit is cut to the manifest:
    # `mapped + residual` partitions the manifest, never the repository.
    mapped: set[str] = set()
    bound_by_uncategorised: set[str] = set()
    for s in sections:
        if s["placeholder"]:
            continue
        hit: set[str] = set()
        for g in s["globs"]:
            hit |= resolve_glob(root, g, notes)
        hit &= in_manifest
        if s["cats"]:
            mapped |= hit
        else:
            # Matched, but the section carries no category token, so a category-keyed
            # dispatch cannot route it. Step 3-0b class (c). Residual, and named.
            bound_by_uncategorised |= hit

    excluded: set[str] = set()
    for g in exclusions:
        excluded |= resolve_glob(root, g, notes)

    vendor = read_vendor_paths(root, notes)
    # NOT `- excluded`. `CLAUDE.md § Map coverage exclusions` scopes the Step 2a map-coverage
    # AUDIT and nothing else: `WORKFLOW.md` § 6.1 states it "does not change the review/scan
    # manifest and is not a review-exclusion knob", and `security-audit/SKILL.md` repeats it
    # ("not a scan-exclusion mechanism"). Step 3-0c is dispatch, so subtracting the list here
    # would silently give a listed path NO agent — the exact reading Phase 139 settled against.
    #
    # A first cut did subtract it, and the round showed what that costs. `parse_exclusions`
    # harvests backticked globs from list items, so an ordinary sentence — "we deliberately do
    # NOT exclude `api/**` or `auth/**`, they are security-critical" — removed the API server,
    # a SQL route and the auth module from dispatch and reported `Full`. A coverage tool whose
    # worst failure is silently dropping the files a consumer called security-critical, while
    # certifying completeness, is worse than no tool. The list is now COUNTED, never subtracted.
    residual = sorted(in_manifest - mapped)
    groups = group_residual(residual, group_cap if group_cap is not None else per_agent)
    assignments = pack(groups, budget, vendor)

    # Hand each agent exactly what it is credited for. Packing under a binding budget put 45
    # files in a bin whose credit was 25 -- so the dispatch instruction said 45 and the
    # arithmetic said 25, and the 20-file difference was a claim neither of them owned.
    # Truncate to the credit and let the remainder be reported as unreached, which is what it
    # is. The consumer-first ranking means the files that fall off are Sysop's own last.
    unreached_files: list[str] = []
    for a in assignments:
        if len(a["files"]) > per_agent:
            unreached_files.extend(a["files"][per_agent:])
            a["files"] = a["files"][:per_agent]
            a["groups"] = sorted({g for g in a["groups"]
                                  if any(f == g or f.startswith(g + "/") for f in a["files"])})
    reviewed = sum(len(a["files"]) for a in assignments)
    needed = _budget_for_full(groups, per_agent, len(residual), vendor)
    verdict = "Full" if reviewed >= len(residual) else "Sampled"

    return {
        "status": "ok",
        "notes": notes,
        "manifest": len(files),
        "sections": len(sections),
        "placeholder_sections": sum(1 for s in sections if s["placeholder"]),
        "mapped": len(mapped),
        # Reported, never subtracted — see the note in build(). This is "how much of the
        # residual you have already declared expected-unmapped", not "what was removed".
        "declared_expected_unmapped": len(excluded & set(residual)),
        "residual": len(residual),
        "residual_vendor": sum(1 for f in residual if f in vendor),
        "residual_consumer": sum(1 for f in residual if f not in vendor),
        "residual_uncategorised": len(bound_by_uncategorised - mapped - excluded),
        "residual_groups": len(groups),
        "budget": budget,
        "per_agent": per_agent,
        "reviewed": reviewed,
        "unreached": max(0, len(residual) - reviewed),
        "unreached_vendor": sum(1 for f in unreached_files if f in vendor),
        "unreached_consumer": sum(1 for f in unreached_files if f not in vendor),
        "agents_needed_for_full": needed,
        "oversized_groups": sorted(
            (k for k, v in groups.items() if len(v) > per_agent), key=lambda k: -len(groups[k])
        )[:5],
        "verdict": verdict,
        "assignments": assignments,
    }


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def render(r: dict) -> str:
    if r["status"] != "ok":
        return "Residual assignment: not assessed — " + "; ".join(r["notes"])

    out = ["Residual assignment (manifest ↔ dispatch):"]
    out.append(f"  manifest {r['manifest']} · mapped {r['mapped']} · residual {r['residual']}")
    if r["declared_expected_unmapped"]:
        out.append(f"  {r['declared_expected_unmapped']} of the residual are on your "
                   "`## Map coverage exclusions` list — still dispatched (that list scopes the "
                   "Step 2a coverage audit only, never review)")
    out.append(f"  map sections {r['sections']} ({r['placeholder_sections']} all-placeholder, "
               f"binding nothing on this install)")
    if r["residual_vendor"]:
        out.append(f"  of the residual, {r['residual_consumer']} are your code and "
                   f"{r['residual_vendor']} are Sysop's own installed files "
                   "(counted, not excluded; ranked last when the budget binds)")
    if r["residual_uncategorised"]:
        out.append(f"  of the residual, {r['residual_uncategorised']} are matched by a section "
                   "carrying no category token (3-0b class (c) — matched, unroutable)")
    if r["verdict"] == "Full":
        out.append("  residual coverage: Full")
    elif r["agents_needed_for_full"]:
        out.append(f"  residual coverage: Sampled ({r['reviewed']}/{r['residual']} reviewed, "
                   f"{r['unreached']} unreached; --budget {r['agents_needed_for_full']} reaches "
                   f"Full at {r['per_agent']} files each)")
    else:
        out.append(f"  residual coverage: Sampled ({r['reviewed']}/{r['residual']} reviewed, "
                   f"{r['unreached']} unreached; Full is UNREACHABLE at --per-agent "
                   f"{r['per_agent']} — these groups exceed it and cannot be split further: "
                   f"{', '.join(r['oversized_groups']) or 'unknown'}. Raise --per-agent.)")
    if r["unreached"]:
        out.append(f"  unreached: {r['unreached_consumer']} of your files, "
                   f"{r['unreached_vendor']} of Sysop's — raise --budget to reach them")
    for a in r["assignments"]:
        out.append(f"    {a['agent']}: {len(a['files'])} files")
        out.append(f"      {', '.join(a['groups'][:8])}"
                   + (f", +{len(a['groups']) - 8} more" if len(a["groups"]) > 8 else ""))
    for n in r["notes"]:
        out.append(f"  note: {n}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Residual assignment for /security-audit — the files no map section reaches.")
    ap.add_argument("--root", default=".", help="consumer repo root (default: cwd)")
    ap.add_argument("--manifest-file", required=True, metavar="PATH",
                    help="the round's manifest: one repo-relative path per line (required; "
                         "a relative PATH is read from the current directory)")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                    help=f"max residual agents (default {DEFAULT_BUDGET})")
    ap.add_argument("--per-agent", type=int, default=DEFAULT_PER_AGENT,
                    help=f"files one residual agent is credited with (default {DEFAULT_PER_AGENT})")
    ap.add_argument("--group-cap", type=int, default=None,
                    help="deepen a directory group past this size (default: --per-agent)")
    ap.add_argument("--json", action="store_true", help="emit the structured report")
    args = ap.parse_args(argv)

    if args.budget < 1 or args.per_agent < 1 or (args.group_cap is not None and args.group_cap < 1):
        print("--budget, --per-agent and --group-cap must all be >= 1", file=sys.stderr)
        return 2

    try:
        report = build(args.root, args.manifest_file, args.budget, args.per_agent,
                       args.group_cap)
    except Exception as exc:                                    # noqa: BLE001 — advisory tool
        # The last-resort net. A missing map, a map that is a directory, invalid UTF-8 in
        # either parsed file, every non-object lock shape, a non-git tree, an empty repo, a
        # nonexistent --root, a tracked file whose NAME is not UTF-8 (`git ls-files -z`
        # prints it raw) and a manifest file that cannot be read or is refused all exit 0
        # with a stated reason. Nothing known reaches this net.
        print(f"security_partition: unexpected error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
