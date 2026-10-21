#!/usr/bin/env python3
"""close_gate.py — the signed gate for the unattended land (`Q-411`, spec § 10.3).

The unattended land's trust comes from GitHub, not from the agent's machine: a
required check, posted by a dedicated GitHub App whose key only the default
branch's workflows can read, decides whether a pull request into the default
branch may merge with no human. This script computes that check. The workflow
template `sysop/scripts/ci/sysop-close-gate.yml.example` runs it on
`pull_request_target`, `issue_comment`, a push to the default branch, and the
relay's `workflow_run`, always from the default branch's copy, and never runs
anything the pull request carries: the head is fetched and read as data.

What it decides (spec § 10.5's split):

  Against a compromised agent — read from the merge result GitHub's squash would
  produce (`close_run.merge_tree`: an empty scratch `GIT_DIR`, pinned
  `merge.directoryRenames=false`, `--attr-source=<the empty tree>`), and from the base:
    * every changed path admitted by `## Unattended close class`, the governing
      set refused (compared folded), and no symlink or gitlink on either side;
    * no symlink or gitlink anywhere at the base but the installer's Codex links
      (`.agents/skills/<name>` -> `../../.claude/skills/<name>`);
    * no agent instruction file at the base that imports, directly or through any
      chain of files, a path the class admits (every `@` token in the raw text
      counts, and one Claude Code resolves outside the checkout by every trailing run of
      its segments);
    * `tasks/index.yml`: read strictly (no duplicate key, anchor, alias or merge
      key), no gating field changed on any task, no entry added, removed or
      renamed, and every entry the PR does not close parsing identically, value
      and type, as do the other top-level keys;
    * `CODEOWNERS` at the base: its first rule is `* @<code_owner>`, every
      governing and excluded path it is probed with is owned by the code owner,
      and GitHub's `codeowners/errors` reports no skipped line.

  For an honest agent only:
    * the tasks the PR closes (a status moving to `done`), with their
      `manual_smoke`, `solo`, `user_action` and `blast_radius` read at the base;
    * the second reader's verdict on the head (`## Second reader`, read at the
      base), with any comment of the reviewer's edited by someone else refused
      (GraphQL `userContentEdits`).

  The escape hatch: an approval by the code owner whose `commit_id` is the head
  and which postdates the PR's last base change passes every predicate.

Subcommands:

    evaluate <tip> <head>
        Offline: every predicate that needs no GitHub API, against two local
        commits. Prints `PROBLEM:` lines and `VERDICT: pass | fail`. Exit 0 on
        pass, 4 on fail.

    run --repo <owner/name> --event <name> [--pr <n>] [--head-sha <sha>] [--post]
        In the workflow. Asserts the checkout is the default branch's live tip
        (a re-run of an old run posts nothing), selects the pull requests the
        event concerns, fetches each head as `refs/sysop-gate/pr-<n>`, posts an
        `in_progress` check run, evaluates, and posts the verdict only if neither
        the tip nor the head moved meanwhile. `--pr` is a number; `--head-sha`
        only filters the open pull requests a relay re-evaluates. Without
        `--post` nothing is posted. Exit 1 when GitHub or git fails.

The check run is named `sysop/close-gate`. A `pending` verdict (the second reader
has not answered) is posted as `in_progress`, never `neutral`, which a required
check would accept.

Run it with an interpreter whose own environment holds PyYAML (the workflow's
venv, outside the checkout): the script refuses a `yaml` found anywhere else,
and imports nothing from a checkout but its own directory.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

_NO_YAML = ("ERROR: PyYAML must be installed in this interpreter's own environment "
            f"({sys.prefix}); close_gate.py imports nothing from a checkout but its own directory")
try:
    import yaml
except ImportError:
    print(_NO_YAML, file=sys.stderr)
    sys.exit(1)
if not os.path.abspath(yaml.__file__).startswith(os.path.abspath(sys.prefix) + os.sep):
    print(_NO_YAML, file=sys.stderr)
    sys.exit(1)

import argparse  # noqa: E402
import base64  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import posixpath  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

# The script's own directory is APPENDED, after the standard library, and only once the standard
# library modules above are loaded: inserted first, a `difflib.py` placed beside the gate shadowed
# the real one and ran with the gate's token (Phase 374's round). `-I` keeps the checkout itself
# off the path; this keeps the gate's directory from overriding anything but its own modules.
sys.path.append(_HERE)

import close_run as cr  # noqa: E402

CHECK_NAME = "sysop/close-gate"
INDEX = "tasks/index.yml"
GATING_FIELDS = ("manual_smoke", "solo", "user_action", "blast_radius")
INSTRUCTION_NAMES = frozenset(map(cr.fold, ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md")))
CODEOWNERS_PLACES = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")  # GitHub's search order


# --- tasks/index.yml, read strictly -------------------------------------------------------------

class Unreadable(Exception):
    """The index cannot be read strictly; the message says why."""


def strict_index(text: str) -> tuple[dict, dict]:
    """(entries by id, the other top-level keys) for a `tasks/index.yml`, refusing what a lenient
    reader resolves silently: an anchor or alias, a merge key, a duplicate key (PyYAML keeps the
    last), a duplicate id."""
    # `parse` and `compose` build events and nodes, never Python objects, so their default loader
    # constructs nothing; only `safe_load` constructs, and only after both have passed.
    try:
        for ev in yaml.parse(text):
            if isinstance(ev, yaml.AliasEvent) or getattr(ev, "anchor", None):
                raise Unreadable("it uses an anchor or alias")
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except Unreadable:
        raise
    except Exception as e:  # noqa: BLE001 — PyYAML also raises ValueError, RecursionError (`Q-621`)
        first = (str(e).splitlines() or [type(e).__name__])[0]
        raise Unreadable(f"it does not parse: {first}") from None

    def walk(n) -> None:
        if isinstance(n, yaml.MappingNode):
            keys = []
            for k, v in n.value:
                if k.tag == "tag:yaml.org,2002:merge" or k.value == "<<":
                    raise Unreadable(f"it uses a merge key at line {k.start_mark.line + 1}")
                if k.value in keys:
                    raise Unreadable(f"key {k.value!r} is given twice at line {k.start_mark.line + 1}")
                keys.append(k.value)
                walk(v)
        elif isinstance(n, yaml.SequenceNode):
            for v in n.value:
                walk(v)

    walk(node)
    if not isinstance(data, dict):
        raise Unreadable("its top level is not a mapping")
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        raise Unreadable("`tasks:` is not a list")
    entries: dict = {}
    for i, entry in enumerate(tasks):
        if not isinstance(entry, dict) or not entry.get("id"):
            raise Unreadable(f"entry {i + 1} has no id")
        tid = str(entry["id"])
        if tid in entries:
            raise Unreadable(f"id {tid} is given twice")
        entries[tid] = entry
    return entries, {k: v for k, v in data.items() if k != "tasks"}


def _typed(value):
    """A value with every scalar's type attached: `True == 1` in Python, and `/review-close`
    reads `manual_smoke` with `is True`, so `true` -> `1` must read as a change."""
    if isinstance(value, dict):
        return ("dict", tuple(sorted((str(k), _typed(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ("list", tuple(_typed(v) for v in value))
    return (type(value).__name__, value)


def _gating_value(entry: dict, field: str) -> tuple:
    """A gating field as (present, type, value): `True == 1` in Python, but `/review-close` reads
    `manual_smoke` with `is True`, so `true` -> `1` is a change (Phase 374's round)."""
    value = entry.get(field)
    return field in entry, type(value).__name__, value


def _gating(entry: dict) -> tuple:
    return tuple(_gating_value(entry, f) for f in GATING_FIELDS)


def index_problems(tip_text: str | None, result_text: str | None) -> tuple[list[str], list[str]]:
    """(problems, ids the merge closes) for `tasks/index.yml` from the tip to the merge result. A
    merged PR must not clear a gating flag for a later one (Wade's ruling (ab)): no gating field
    changes on any task, and **every entry the merge does not close parses identically, value and
    type**, as do the file's other top-level keys. Comparing only the gating fields missed two PRs
    that each moved one quote (Phase 367, round 2, HIGH-1), and a text-span rule both let a
    neighbour's lines be moved into the closed entry (Phase 374's round, H1) and refused an
    honest close, whose writer re-serialises the whole file. Comments and formatting may change;
    every reader of the index parses it with PyYAML."""
    if tip_text == result_text:
        return [], []
    if tip_text is None or result_text is None:
        return [f"{INDEX} is {'added' if tip_text is None else 'deleted'} by the merge"], []
    out: list[str] = []
    try:
        old, old_top = strict_index(tip_text)
    except Unreadable as e:
        return [f"{INDEX} at the base cannot be read strictly: {e}"], []
    try:
        new, new_top = strict_index(result_text)
    except Unreadable as e:
        return [f"{INDEX} after the merge cannot be read strictly: {e}"], []
    for tid in sorted(set(old) ^ set(new)):
        out.append(f"{INDEX}: entry {tid} is {'removed or renamed' if tid in old else 'added'}")
    common = [t for t in old if t in new]
    for tid in common:
        if _gating(old[tid]) != _gating(new[tid]):
            changed = [f for f in GATING_FIELDS if _gating_value(old[tid], f) != _gating_value(new[tid], f)]
            out.append(f"{INDEX}: {tid} changes a gating field ({', '.join(changed)})")
    closed = [t for t in common if old[t].get("status") != "done" and new[t].get("status") == "done"]
    others = [t for t in common if t not in closed and _typed(old[t]) != _typed(new[t])]
    if others:
        out.append(f"{INDEX}: a change to an entry this merge does not close ({', '.join(others[:5])})")
    if _typed(old_top) != _typed(new_top):
        out.append(f"{INDEX}: a change to its top-level keys")
    return out, closed


# --- the base: symlinks, imports ----------------------------------------------------------------

def base_tree(root: Path, tip: str) -> list[tuple[str, str]]:
    """[(mode, path), ...] for every entry at <tip>."""
    _, out = cr.git(root, "ls-tree", "-r", "-z", "--full-tree", tip)
    rows = []
    for rec in out.split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            rows.append((meta.split()[0], path))
    return rows


def _links(root: Path, tip: str, rows: list[tuple[str, str]]) -> dict[str, str]:
    """Every symlink at <tip>, path -> target."""
    out = {}
    for mode, path in rows:
        if mode == "120000":
            _, target = cr.git(root, "cat-file", "-p", f"{tip}:{path}")
            out[path] = target
    return out


CODEX_LINK = re.compile(r"\.agents/skills/([^/]+)")


def link_problems(root: Path, tip: str, rows: list[tuple[str, str]]) -> list[str]:
    """Every symlink and gitlink at the base but the installer's Codex links, each exactly
    `.agents/skills/<name>` -> `../../.claude/skills/<name>`. A link anywhere else could route an
    in-class edit into what an agent reads, and three rounds broke three ways of following links
    (lexical, then case-sensitive, then an import scan that never went through one). So nothing is
    followed and every other link is refused (Wade's ruling at Phase 374's round 3); GDP's and
    BeanRider's only links were the two Codex links. The gate stays red until a human removes it."""
    links = _links(root, tip, rows)
    out = []
    for mode, path in rows:
        if mode not in cr.LINK_MODES:
            continue
        if mode == "120000":
            m = CODEX_LINK.fullmatch(path)
            if m and links[path] == f"../../.claude/skills/{m.group(1)}":
                continue
            what = f"a symlink to {links[path]}"
        else:
            what = "a gitlink"
        out.append(f"{path} at the base is {what}; the class admits no link but the installer's "
                   "`.agents/skills/<name>` Codex links, so a human must replace it")
    return out


# Claude Code's import syntax as its extractor reads it: `@` then a run of non-space characters,
# where `\ ` escapes a space (read from the 2.1.296 binary by Phase 374's round 2). Matched in the
# RAW text, with no Markdown awareness at all: the extractor's lexer reads imports inside HTML
# blocks, comments, list-item fences and links that a Markdown-aware reader skips, and two rounds
# broke two attempts to imitate it. Reading too much refuses an honest merge; reading too little
# lets one through, so this errs wide (Wade's ruling at Phase 374's round 2).
RAW_IMPORT = re.compile(r"@((?:[^\s\\]|\\ )+)")
AGENT_DIRS = frozenset(map(cr.fold, cr.GOVERNING_DIRS))
_CUT = re.compile(r"[\]\[()<>\"'`,;!?|*{}]")


def import_tokens(text: str) -> list[str]:
    """Every candidate path an `@` in <text> could import: the token, with `\\ ` unescaped and any
    `#fragment` dropped, plus each prefix of it cut at a character that ends a path in prose or
    Markdown (`]`, `)`, a quote, a backtick, trailing punctuation). Over-reading is the point."""
    out: list[str] = []
    for m in RAW_IMPORT.finditer(text):
        tok = m.group(1).replace("\\ ", " ").split("#", 1)[0]
        cands = {tok, tok.rstrip(".,:;!?")}
        for cut in _CUT.finditer(tok):
            cands.add(tok[:cut.start()].rstrip(".,:;!?"))
        for c in sorted(cands, key=len, reverse=True):
            if c and c not in out:
                out.append(c)
    return out


def _instruction_file(path: str) -> bool:
    """A file an agent loads as instructions without being told to: one of the four names
    anywhere, or any file under a governing agent directory (`.claude/`, `.agents/`, `.codex/`)."""
    parts = [cr.fold(p) for p in path.split("/")]
    return parts[-1] in INSTRUCTION_NAMES or any(p in AGENT_DIRS for p in parts[:-1])


def _folded_paths(root: Path, rev: str) -> dict[str, list[str]]:
    """Every path at <rev> and every directory above one, keyed folded."""
    _, out = cr.git(root, "ls-tree", "-r", "-z", "--name-only", "--full-tree", rev)
    found: dict[str, list[str]] = {}
    for path in filter(None, out.split("\0")):
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            p = "/".join(parts[:i])
            found.setdefault(cr.fold(p), [])
            if p not in found[cr.fold(p)]:
                found[cr.fold(p)].append(p)
    return found


MACHINE_PATH = re.compile(r"[~/]|[A-Za-z]:[/\\]|file:", re.I)


def import_targets(path: str, tok: str, depth: int = 0) -> list[str]:
    """The repository paths <tok>, imported from <path>, could name. A relative token that stays
    in the repository names one, resolved against the importing file's directory. Anything else
    is resolved by Claude Code against the machine's filesystem, which the gate cannot see: an
    absolute, `~`, drive-letter or `file:` token (round 3: `@/opt/proj/src/a.py`; round 4:
    `@C:/proj/src/a.py`), or a relative one that climbs out and back in through the checkout's
    own directory name (round 4: `@../repo/src/a.py`). Each of those counts by every trailing run
    of its segments, at most <depth> of them when given, since no path the gate knows is deeper
    (round 4 measured the uncapped expansion growing cubically with the token's length)."""
    if MACHINE_PATH.match(tok):
        rest = tok.replace("\\", "/")
        if rest.startswith("~"):
            rest = rest.partition("/")[2]
    else:
        rest = posixpath.normpath(posixpath.join(posixpath.dirname(path), tok))
        if rest == ".":
            return []
        if rest != ".." and not rest.startswith("../"):
            return [rest]
    segs = [s for s in posixpath.normpath("/" + rest).split("/") if s]
    start = max(0, len(segs) - depth) if depth else 0
    return ["/".join(segs[i:]) for i in range(start, len(segs))]


def import_problems(root: Path, tip: str, cls: dict, rows: list[tuple[str, str]], tree: str = "") -> list[str]:
    """An agent instruction file at the base that imports, directly or through any chain of files
    it imports, a path the class admits (Phase 367, round 2, MEDIUM-5): an unattended merge could
    then change what the agent reads as instructions. The chain is followed through files of any
    kind, governing ones included, because Claude Code loads imports recursively (round 2's
    chain ran `CLAUDE.md` -> a Markdown file under `.github/` -> `docs/guide.md`). A target counts when it exists at
    the base or after the merge (so a merge cannot add the file a dangling import waits for),
    compared folded. A token that names nothing, like `@codex review`, does not count."""
    known = _folded_paths(root, tip)
    if tree:
        for k, v in _folded_paths(root, tree).items():
            known.setdefault(k, []).extend(p for p in v if p not in known.get(k, []))
    regular = {path for mode, path in rows if mode in ("100644", "100755")}
    depth = max((k.count("/") + 1 for k in known), default=0)
    queue = sorted(p for p in regular if _instruction_file(p))
    seen = set(queue)
    out = []
    while queue:
        path = queue.pop(0)
        _, text = cr.git(root, "cat-file", "-p", f"{tip}:{path}")
        for tok in import_tokens(text):
            for target in import_targets(path, tok, depth):
                for actual in known.get(cr.fold(target), []):
                    if not cr.path_problem(cls, actual):
                        out.append(f"{path} imports {tok}, which names {actual}, a path the class "
                                   "admits; an unattended merge could change what the agent reads "
                                   "as instructions")
                    elif actual in regular and actual not in seen:
                        seen.add(actual)
                        queue.append(actual)
    return out


# --- CODEOWNERS ---------------------------------------------------------------------------------

def codeowners_regex(pat: str) -> re.Pattern:
    """GitHub's reading of a CODEOWNERS pattern (*About code owners*): gitignore rules, case
    sensitive, no `!`, `[ ]` or `\\#`. A leading or middle `/` anchors at the root, otherwise the
    pattern matches at any depth; a trailing `/` matches a directory's contents; a last segment
    with no wildcard also covers everything under it (`apps` owns `apps/x`), and one with a
    wildcard does not (`docs/*` does not own `docs/a/b.md`)."""
    dir_only = pat.endswith("/")
    body = pat.strip("/")
    anchored = pat.startswith("/") or "/" in body
    if body in ("*", "**"):
        return re.compile(r".+\Z", re.S)
    segs = body.split("/")
    out = ""
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if seg == "**":
            out += ".*" if last else "(?:[^/]+/)*"
            continue
        out += "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in seg)
        if not last:
            out += "/"
    tail = segs[-1]
    if tail == "**":
        suffix = ""
    elif dir_only:
        suffix = "/.+"
    elif any(c in tail for c in "*?"):
        suffix = ""
    else:
        suffix = "(?:/.+)?"
    return re.compile(("" if anchored else "(?:.+/)?") + out + suffix + r"\Z", re.S)


def parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    rules = []
    for line in text.lstrip(cr.BOM).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        toks = s.split()
        owners = []
        for t in toks[1:]:
            if t.startswith("#"):
                break
            owners.append(t)
        rules.append((toks[0], owners))
    return rules


def owners_of(rules: list[tuple[str, list[str]]], path: str) -> list[str] | None:
    """The owners of <path> by the last matching rule, [] for a rule naming no owner, None when no
    rule matches."""
    found = None
    for pat, owners in rules:
        if codeowners_regex(pat).match(path):
            found = owners
    return found


def _sample(glob: str) -> str:
    return "/".join("x" if seg == "**" else re.sub(r"[*?]", "x", seg) for seg in glob.rstrip("/").split("/"))


def _prefix(glob: str) -> str:
    segs = []
    for seg in glob.rstrip("/").split("/"):
        if any(c in seg for c in "*?"):
            break
        segs.append(seg)
    return "/".join(segs)


GOVERNING_PROBES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md", ".claude/x",
                    ".agents/x", ".codex/x", ".mcp.json", ".gitmodules", ".gitattributes")


def codeowners_probes(cls: dict, changed: list[str], is_file=lambda p: False) -> list[str]:
    """Paths CODEOWNERS must give to the code owner: every changed path the class refuses, every
    governing name at the root and inside each allowed directory (the case a broad allow line
    after the governing lines would un-own), and a sample under each exclusion (the sample
    itself only when it is a file: CODEOWNERS owns files, and a directory rule `/x/` does not
    match the path `x`)."""
    probes = list(changed)
    probes += ["sysop/x", ".github/x", ".github/workflows/x.yml", "CODEOWNERS", "docs/CODEOWNERS"]
    for pat, _ in cls["allow"]:
        pre = _prefix(pat)
        for g in GOVERNING_PROBES:
            probes += [f"{pre}/{g}" if pre else g, f"{pre}/x/{g}" if pre else f"x/{g}"]
    for pat, _ in cls["exclude"]:
        probes += ([_sample(pat)] if is_file(_sample(pat)) else []) + [_sample(pat) + "/x"]
    seen, out = set(), []
    for p in probes:
        if p not in seen and cr.path_problem(cls, p):
            seen.add(p)
            out.append(p)
    return out


def codeowners_problems(root: Path, tip: str, cls: dict, changed: list[str]) -> list[str]:
    owner = cls["code_owner"]
    if not owner:
        return ["`## Unattended close class` names no code_owner"]
    place = next((p for p in CODEOWNERS_PLACES
                  if cr.git(root, "cat-file", "-e", f"{tip}:{p}", ok=(0, 1, 128))[0] == 0), "")
    if not place:
        return ["no CODEOWNERS at the base (.github/, the root or docs/): nothing owns the paths "
                "outside the class"]
    _, size = cr.git(root, "cat-file", "-s", f"{tip}:{place}")
    if int(size.strip() or 0) >= 3 * 1024 * 1024:
        return [f"{place} is 3 MB or larger, so GitHub does not load it (*About code owners*)"]
    _, text = cr.git(root, "cat-file", "-p", f"{tip}:{place}")
    rules = parse_codeowners(text)
    out = []
    if not rules or rules[0][0] != "*" or [o.lower() for o in rules[0][1]] != [f"@{owner}".lower()]:
        out.append(f"{place}: its first rule must be `* @{owner}` (default-deny), not "
                   f"{' '.join([rules[0][0]] + rules[0][1]) if rules else '(none)'!r}")
    for pat, _ in cls["allow"] + cls["exclude"]:
        if "#" in pat:
            out.append(f"the class glob {pat!r} uses `#`, which CODEOWNERS cannot express")
    def is_file(p: str) -> bool:
        return cr.git(root, "cat-file", "-t", f"{tip}:{p}", ok=(0, 128))[1].strip() == "blob"

    unowned = [p for p in codeowners_probes(cls, changed, is_file)
               if f"@{owner}".lower() not in [o.lower() for o in (owners_of(rules, p) or [])]]
    if unowned:
        out.append(f"{place} does not give the code owner {', '.join(unowned[:5])}"
                   + (f" and {len(unowned) - 5} more" if len(unowned) > 5 else "")
                   + "; re-own every governing and excluded path last, after the allow lines")
    return out


# --- evaluation ---------------------------------------------------------------------------------

def blob(root: Path, rev: str, path: str) -> str | None:
    code, out = cr.git(root, "cat-file", "-p", f"{rev}:{path}", ok=(0, 128))
    return None if code else out


def offline_problems(root: Path, tip: str, head: str) -> tuple[list[str], list[str], dict, list[str]]:
    """(compromised-agent problems, honest-agent problems, the class, the changed paths) for
    everything that needs no GitHub API."""
    try:
        cls = cr.read_class(root, rev=tip)
    except cr.Refuse as e:
        return [f"the class at the base cannot be read: {e}"], [], {}, []
    hard: list[str] = []
    if not cls["code_owner"]:
        hard.append("`## Unattended close class` names no code_owner")
    if not cls["gate_app"]:
        hard.append("`## Unattended close class` names no gate_app")
    why, tree = cr.merge_tree(root, tip, head)
    if why:
        return hard + [why], [], cls, []
    entries = cr.tree_entries(root, tip, tree)
    changed = [p for _, _, p in entries]
    hard += cr.merge_problems(cls, entries)
    rows = base_tree(root, tip)
    hard += link_problems(root, tip, rows)
    hard += import_problems(root, tip, cls, rows, tree)
    idx, closed = index_problems(blob(root, tip, INDEX), blob(root, tree, INDEX))
    hard += idx
    if cls["code_owner"]:
        hard += codeowners_problems(root, tip, cls, changed)
    soft: list[str] = []
    if not closed and not idx:
        soft.append(f"the merge closes no task in {INDEX}")
    if closed:
        base = cr.tasks_at(root, tip) or {}
        for tid in closed:
            soft += [f"at the base: {p}" for p in cr.task_problems(cls, tid, base.get(tid))]
    return hard, soft, cls, changed


def _login(s) -> str:
    return str(s or "").lower().removesuffix("[bot]")


def edit_problems(reviewer: str, graph: dict) -> list[str]:
    """Any comment or review of the reviewer's edited by someone other than its author (Phase 372,
    § 10.7 (7): a `write` collaborator can edit an app's comments, and only GraphQL's edit history
    names who did; `editor` keeps only the last editor)."""
    out = []
    pr = (((graph or {}).get("data") or {}).get("repository") or {}).get("pullRequest")
    if not isinstance(pr, dict):
        return ["GitHub returned no edit history for the pull request"]
    items = []
    conns = [pr.get("comments"), pr.get("reviews")]
    for c in (pr.get("comments") or {}).get("nodes") or []:
        items.append(("comment", c))
    for r in (pr.get("reviews") or {}).get("nodes") or []:
        items.append(("review", r))
        conns.append(r.get("comments"))
        for c in (r.get("comments") or {}).get("nodes") or []:
            items.append(("review comment", c))
    if any(isinstance(c, dict) and (c.get("pageInfo") or {}).get("hasNextPage") for c in conns):
        out.append("too many comments or reviews to read the edit history of every one")
    for kind, item in items:
        author = _login((item.get("author") or {}).get("login"))
        if author != _login(reviewer):
            continue
        edits = item.get("userContentEdits") or {}
        if (edits.get("pageInfo") or {}).get("hasNextPage"):
            out.append(f"a {kind} by {reviewer} has too many edits to read")
        for e in edits.get("nodes") or []:
            editor = _login(((e or {}).get("editor") or {}).get("login"))
            if editor != author:
                out.append(f"a {kind} by {reviewer} was edited by {editor or 'a deleted account'}")
                break
    return out


# GitHub refuses a query whose connections could return more than 500,000 nodes in all, counting
# each nested connection as the product of the `first:` values above it (measured live, Phase 374:
# 100 x 100 x 100 was refused). These sizes allow 135,151; a page that does not fit refuses the gate.
EDITS_QUERY = """query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){
pullRequest(number:$n){
 timelineItems(itemTypes:[BASE_REF_CHANGED_EVENT],last:1){nodes{...on BaseRefChangedEvent{createdAt}}}
 comments(first:100){pageInfo{hasNextPage} nodes{author{login} userContentEdits(first:50){pageInfo{hasNextPage} nodes{editor{login}}}}}
 reviews(first:50){pageInfo{hasNextPage} nodes{author{login} userContentEdits(first:50){pageInfo{hasNextPage} nodes{editor{login}}}
  comments(first:50){pageInfo{hasNextPage} nodes{author{login} userContentEdits(first:50){pageInfo{hasNextPage} nodes{editor{login}}}}}}}
}}}"""


def base_changed_at(graph: dict) -> datetime.datetime | None:
    pr = (((graph or {}).get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    nodes = (pr.get("timelineItems") or {}).get("nodes") or []
    return cr.parse_time(nodes[-1].get("createdAt")) if nodes and isinstance(nodes[-1], dict) else None


def owner_approved(owner: str, head: str, reviews: list, since: datetime.datetime | None) -> bool:
    """The escape hatch ((y)): the code owner's latest decisive review of <head> is an approval
    submitted after the PR's last base change."""
    # The login exactly (case aside): `_login` drops `[bot]`, which would let an app named like
    # the owner count as the owner.
    mine = [r for r in reviews if isinstance(r, dict) and str((r.get("user") or {}).get("login") or "").lower() == owner.lower()
            and r.get("commit_id") == head and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")]
    if not mine:
        return False
    last = max(mine, key=lambda r: str(r.get("submitted_at") or ""))
    at = cr.parse_time(last.get("submitted_at"))
    return last.get("state") == "APPROVED" and at is not None and (since is None or at > since)


def reader_state(cfg: dict, head: str, reviews: list, review_comments: list, comments: list,
                 reactions: list, now: datetime.datetime) -> tuple[str, list[str]]:
    """The second reader's verdict on <head>, through `close_run.reader_verdict`, with the request
    time taken from the newest PR comment carrying the configured request."""
    asks = [c for c in comments if isinstance(c, dict)
            and str(c.get("body") or "").strip() == cfg["request"].strip()]
    if not asks:
        return "wait", [f"no comment on the PR requests the second reading ({cfg['request']!r})"]
    asked = max(asks, key=lambda c: str(c.get("created_at") or ""))
    rec = {"reviewer": cfg["reviewer"], "head": head, "requested_at": asked.get("created_at"),
           "timeout": cfg["timeout"], "format": cfg["format"], "blocking": cfg.get("blocking", "")}
    return cr.reader_verdict(rec, reviews, review_comments, comments, reactions, now)


def verdict(hard: list[str], soft: list[str], reader: tuple[str, list[str]], hatch: bool) -> tuple[str, list[str]]:
    if hatch:
        return "success", ["the code owner approved this head after its last base change"] + \
            [f"(passed by the approval) {p}" for p in hard + soft]
    if hard or soft:
        return "failure", hard + soft
    state, lines = reader
    if state == "merge":
        return "success", lines
    return ("pending" if state == "wait" else "failure"), lines


# --- GitHub ---------------------------------------------------------------------------------------

class GitHub:
    """The calls the gate makes, through `gh` with GH_TOKEN (the gate app's installation token)."""

    def __init__(self, repo: str):
        self.repo = repo

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        p = subprocess.run(["gh", *args], capture_output=True, input=stdin.encode() if stdin else None)
        if p.returncode != 0:
            raise cr.Fail(f"gh {' '.join(args[:3])} failed: {os.fsdecode(p.stderr).strip()}")
        return os.fsdecode(p.stdout)

    def get(self, path: str):
        return json.loads(self._gh("api", f"repos/{self.repo}/{path}" if path else f"repos/{self.repo}"))

    def pages(self, path: str) -> list:
        out, items, dec, i = self._gh("api", "--paginate", f"repos/{self.repo}/{path}"), [], json.JSONDecoder(), 0
        while True:
            while i < len(out) and out[i].isspace():
                i += 1
            if i >= len(out):
                return items
            page, i = dec.raw_decode(out, i)
            items.extend(page if isinstance(page, list) else [page])

    def graph(self, n: int) -> dict:
        owner, name = self.repo.split("/", 1)
        return json.loads(self._gh("api", "graphql", "-f", f"query={EDITS_QUERY}", "-f", f"owner={owner}",
                                   "-f", f"name={name}", "-F", f"n={n}"))

    @staticmethod
    def _body(status: str, conclusion: str, title: str, lines: list[str]) -> dict:
        body = {"status": status,
                "output": {"title": title[:200], "summary": "\n".join(f"- {x}" for x in lines)[:60000] or "-"}}
        if status == "completed":
            body["conclusion"] = conclusion
        return body

    def post(self, head: str, status: str, conclusion: str, title: str, lines: list[str]) -> tuple[int, int]:
        """Create a check run; returns (its id, the posting app's id)."""
        body = {"name": CHECK_NAME, "head_sha": head, **self._body(status, conclusion, title, lines)}
        made = json.loads(self._gh("api", "-X", "POST", f"repos/{self.repo}/check-runs", "--input", "-",
                                   stdin=json.dumps(body)))
        return int(made["id"]), int((made.get("app") or {}).get("id") or 0)

    def update(self, run_id: int, status: str, conclusion: str, title: str, lines: list[str]) -> None:
        self._gh("api", "-X", "PATCH", f"repos/{self.repo}/check-runs/{run_id}", "--input", "-",
                 stdin=json.dumps(self._body(status, conclusion, title, lines)))

    def runs(self, head: str) -> list[tuple[int, int]]:
        """(id, app id) of every `sysop/close-gate` check run on <head>."""
        got = self.get(f"commits/{head}/check-runs?check_name={CHECK_NAME}&filter=all&per_page=100")
        return [(int(r["id"]), int((r.get("app") or {}).get("id") or 0))
                for r in (got.get("check_runs") or [] if isinstance(got, dict) else [])]


def fetch_head(root: Path, n: int) -> str:
    """Fetch the PR's head as data (never checked out) and return what it resolved to."""
    env = cr.pinned_git_env()
    token = os.environ.get("GH_TOKEN", "")
    if token:
        try:
            cred = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            raise cr.Fail(f"GH_TOKEN cannot be encoded for git: {e}") from e
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {cred}")
    ref = f"refs/sysop-gate/pr-{n}"
    p = subprocess.run(["git", "-C", str(root), "fetch", "--no-tags", "--no-write-fetch-head", "--quiet",
                        "origin", f"+refs/pull/{n}/head:{ref}"], capture_output=True, env=env)
    if p.returncode != 0:
        raise cr.Fail(f"cannot fetch pull request {n}'s head: {os.fsdecode(p.stderr).strip()}")
    return cr.ref_sha(root, ref)


def evaluate_pr(root: Path, gh: GitHub, tip: str, n: int, head: str, now: datetime.datetime) -> tuple[str, list[str]]:
    hard, soft, cls, changed = offline_problems(root, tip, head)
    # The comments and reviews are read before their edit history, so an edit made between the
    # reads is in the history the gate checks (Phase 374's round, H3).
    reviews = gh.pages(f"pulls/{n}/reviews")
    review_comments = gh.pages(f"pulls/{n}/comments")
    comments = gh.pages(f"issues/{n}/comments")
    graph = gh.graph(n)
    if cls and cls.get("code_owner") and owner_approved(cls["code_owner"], head, reviews, base_changed_at(graph)):
        return verdict(hard, soft, ("merge", []), True)
    if cls:
        try:
            errs = gh.get(f"codeowners/errors?ref={tip}")
            errs = errs.get("errors") if isinstance(errs, dict) else None
            if errs is None:
                hard.append("GitHub's codeowners/errors returned no error list")
            for e in errs or []:
                hard.append(f"GitHub skipped a CODEOWNERS line: {e.get('path')}:{e.get('line')} {e.get('kind')}")
        except cr.Fail as e:
            hard.append(f"cannot read GitHub's codeowners/errors: {e}")
    try:
        cfg = cr.read_second_reader(root, rev=tip)
    except cr.Refuse as e:
        return verdict(hard, soft + [f"no usable `## Second reader` at the base: {e}"], ("wait", []), False)
    soft += edit_problems(cfg["reviewer"], graph)
    # Reactions are not read: a `+1` names no commit, so `reader_verdict` only ever answers "wait"
    # from one, and an empty list gives the same verdict. Reading them would need the app to hold
    # Issues: read, which it otherwise does not (measured live, Phase 374: 403).
    reader = reader_state(cfg, head, reviews, review_comments, comments, [], now)
    return verdict(hard, soft, reader, False)


def cmd_run(root: Path, args) -> int:
    gh = GitHub(args.repo)
    default = gh.get("")["default_branch"]
    live = str(gh.get(f"git/ref/heads/{default}").get("object", {}).get("sha") or "")
    here = cr.ref_sha(root, "HEAD")
    if not cr.SHA.fullmatch(live) or here != live:
        print(f"STALE: the checkout is {here[:10] or '?'} and {default}'s live tip is {live[:10] or '?'}; "
              "nothing posted (a later run evaluates the current tip)")
        return 0
    if args.pr:
        prs = [gh.get(f"pulls/{args.pr}")]
    else:
        prs = [p for p in gh.pages(f"pulls?state=open&base={default}&per_page=100")
               if not args.head_sha or (p.get("head") or {}).get("sha") == args.head_sha]
    for pr in prs:
        n = int(pr["number"])
        if pr.get("state") != "open" or (pr.get("base") or {}).get("ref") != default:
            print(f"SKIP #{n}: not an open pull request into {default}")
            continue
        head = str((pr.get("head") or {}).get("sha") or "")
        # Posted before anything that can fail, so a failure leaves this head blocked rather than
        # carrying an earlier verdict about a state that run never read (Phase 374's round 2).
        mine = (0, 0)
        if args.post:
            mine = gh.post(head, "in_progress", "", "evaluating", [f"evaluating {head[:10]} against {live[:10]}"])
        if fetch_head(root, n) != head:
            print(f"SKIP #{n}: its head moved while it was fetched; the push re-runs the gate")
            continue
        state, lines = evaluate_pr(root, gh, live, n, head, cr.utcnow())
        for line in lines:
            print(f"GATE #{n}: {line}")
        now_live = str(gh.get(f"git/ref/heads/{default}").get("object", {}).get("sha") or "")
        now_head = str((gh.get(f"pulls/{n}").get("head") or {}).get("sha") or "")
        if now_live != live or now_head != head:
            print(f"MOVED #{n}: the tip or the head moved during the evaluation; nothing more posted")
            continue
        # Two runs on one tip and head can read different reviews and finish in either order. The
        # newest check run decides (measured live, L3), so a run that is no longer the newest of
        # the gate app's runs on this head posts nothing more: the newer one owns the verdict.
        if args.post and any(rid > mine[0] and app == mine[1] for rid, app in gh.runs(head)):
            print(f"SUPERSEDED #{n}: a newer gate run on {head[:10]} owns the verdict; nothing more posted")
            continue
        print(f"VERDICT #{n}: {state}")
        if args.post:
            title = {"success": "may merge unattended", "failure": "may not merge unattended",
                     "pending": "waiting on the second reader"}[state]
            gh.update(mine[0], "in_progress" if state == "pending" else "completed", state, title, lines)
    return 0


def cmd_evaluate(root: Path, tip: str, head: str) -> int:
    t, h = cr.ref_sha(root, tip), cr.ref_sha(root, head)
    if not t or not h:
        raise cr.Refuse(f"{tip if not t else head} does not resolve")
    hard, soft, _, _ = offline_problems(root, t, h)
    for p in hard + soft:
        print(f"PROBLEM: {p}")
    print("NOT READ: the second reader, comment edits, GitHub's codeowners/errors and the escape hatch "
          "(they need the GitHub API; `run` reads them)")
    print(f"VERDICT: {'fail' if hard or soft else 'pass'}")
    return 4 if hard or soft else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="close_gate.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("tip")
    ev.add_argument("head")
    rn = sub.add_parser("run")
    rn.add_argument("--repo", required=True)
    rn.add_argument("--event", required=True)
    rn.add_argument("--pr", type=int)
    rn.add_argument("--head-sha", default="")
    rn.add_argument("--post", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 3 if e.code else 0
    # A `refs/replace/*` ref would change what the base reads return but not the merge, which
    # runs in an empty `GIT_DIR` (Phase 374's round 3); every git this process runs ignores them.
    os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
    try:
        root = cr.main_root()
        if args.cmd == "evaluate":
            return cmd_evaluate(root, args.tip, args.head)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
            raise cr.Refuse(f"not a repository: {args.repo!r}")
        if args.head_sha and not cr.SHA.fullmatch(args.head_sha):
            raise cr.Refuse(f"not a commit sha: {args.head_sha!r}")
        return cmd_run(root, args)
    except cr.Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    except cr.Fail as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
