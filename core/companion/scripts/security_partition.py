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

Design stance — **advisory and honest, never a gate.** It reports; it does not block, and
every degraded path (no map, no ``CLAUDE.md``, empty repo, not a git tree) exits 0 with a
stated reason rather than failing the round. Only an unexpected crash exits 2. Same stance
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
    python3 sysop/scripts/security_partition.py                 # human report
    python3 sysop/scripts/security_partition.py --json          # structured, for the skill
    python3 sysop/scripts/security_partition.py --budget 6 --per-agent 30

Exit codes:
    0   report produced (including every "could not assess" degrade path)
    2   unexpected error
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
            # predicate would wrongly condemn those, and the shipped maps have two.
            "placeholder": bool(globs) and all("<" in g for g in globs),
        })
    return out


def _strip_fences(text: str) -> str:
    """Blank out fenced code blocks, keeping line numbering intact.

    Markdown examples are content, not instructions. `WORKFLOW.md` ships fenced *templates*
    for consumers to copy — including whole `## <globs> — <Name>` section skeletons — and a
    parse that reads them treats a copied template as a live declaration. Reproduced by the
    round: a fenced authoring note containing `## `**`` — Everything In My Repo` made every
    file in the repo read as mapped, residual 0, verdict `Full`.

    An unterminated fence blanks to end-of-text, which is the safe direction: content inside
    an unclosed fence is ignored rather than half-read.
    """
    out, fenced = [], False
    for ln in text.split("\n"):
        if re.match(r"^\s*(```|~~~)", ln):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else ln)
    return "\n".join(out)


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

def _git(root: str, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
    ).stdout


def _is_git_tree(root: str) -> bool:
    """A non-repo used to degrade with the EMPTY-REPO reason, which is a different fact."""
    return subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
        capture_output=True, text=True,
    ).returncode == 0


def resolve_glob(root: str, glob: str) -> set[str]:
    """Tracked files a map glob matches.

    Uses git's ``:(glob)`` pathspec magic, which gives ``**`` its true meaning. The plain
    pathspec does not: ``git ls-files -- 'api/**/*.py'`` silently drops the direct child
    ``api/server.py``, and ``'api/routes/**/*.py'`` returns nothing at all because ``**``
    will not match an empty path segment. Both were reproduced before this was written.
    """
    if "<" in glob:          # unlocalized placeholder — matches nothing, by construction
        return set()
    out = _git(root, "ls-files", "-z", "--", f":(glob){glob}")
    return {p for p in out.split("\0") if p}


def manifest(root: str) -> list[str]:
    return sorted(p for p in _git(root, "ls-files", "-z").split("\0") if p)


def read_vendor_paths(root: str) -> set[str]:
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
    try:
        with open(lock, encoding="utf-8") as fh:
            data = json.load(fh)
        # `isinstance(data, dict)` BEFORE `.get`. A lock that is valid JSON but not an object
        # (`null`, `[1,2,3]`, `"x"`, `123`, `true`) crashed the whole report with exit 2 — while
        # a lock that was not JSON at all exited 0. `install.sh`'s `lock_field()` was hardened
        # against this identical pair in Phase 148, and its comment names it verbatim:
        # "json.load raising, or .get on a non-object".
        if not isinstance(data, dict):
            return set()
        paths = data.get("managed_paths")
        return set(p for p in paths if isinstance(p, str)) if isinstance(paths, list) else set()
    except (ValueError, OSError, UnicodeDecodeError):
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


def build(root: str, budget: int, per_agent: int, group_cap: int | None = None) -> dict:
    """The whole derivation. Returns the report structure; raises nothing on a normal degrade."""
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
            f"{root} is not a git work tree — the manifest comes from `git ls-files`"]}
    files = manifest(root)
    if not files:
        return {"status": "empty", "notes": notes + ["no tracked files"], "assignments": []}

    # mapped: matched by at least one non-placeholder section that carries a category
    mapped: set[str] = set()
    bound_by_uncategorised: set[str] = set()
    for s in sections:
        if s["placeholder"]:
            continue
        hit: set[str] = set()
        for g in s["globs"]:
            hit |= resolve_glob(root, g)
        if s["cats"]:
            mapped |= hit
        else:
            # Matched, but the section carries no category token, so a category-keyed
            # dispatch cannot route it. Step 3-0b class (c). Residual, and named.
            bound_by_uncategorised |= hit

    excluded: set[str] = set()
    for g in exclusions:
        excluded |= resolve_glob(root, g)

    vendor = read_vendor_paths(root)
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
    residual = sorted(set(files) - mapped)
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
        report = build(args.root, args.budget, args.per_agent, args.group_cap)
    except Exception as exc:                                    # noqa: BLE001 — advisory tool
        # The last-resort net. After the degrade hardening above, no input found by a review
        # lens or by the author reaches this branch: a missing map, a map that is a directory,
        # invalid UTF-8 in either parsed file, every non-object lock shape, a non-git tree, an
        # empty repo and a nonexistent --root all exit 0 with a stated reason. So a mutation
        # of this `2` is currently a no-op, and no test pins it — declared rather than closed,
        # because a test for an unreachable branch would be a test of the mocking, not the code.
        print(f"security_partition: unexpected error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
