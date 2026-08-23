"""
Shadow JSON index for review_tasks.md.

Parses the Markdown into structured JSON for reliable machine consumption.
The Markdown remains the human-readable source of truth; scripts read from
the JSON index for reliable parsing and write mutations back to the Markdown,
then rebuild the index.

Usage:
    python sysop/scripts/review_index.py                 # Rebuild index (or verify fresh)
    python sysop/scripts/review_index.py --rebuild       # Force rebuild
    python sysop/scripts/review_index.py --check         # Exit 0 if fresh, 1 if stale
    python sysop/scripts/review_index.py --list          # Tab-separated batch list
    python sysop/scripts/review_index.py --batch 293     # Single batch details
    python sysop/scripts/review_index.py --range 293     # Line range for sed operations
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone


# ── Paths ────────────────────────────────────────────────────────

def _repo_root():
    """Walk up from this script to find the git working-tree root.

    Inside a git worktree, ``.git`` is a *file* containing
    ``gitdir: <path>`` rather than a directory — so ``os.path.isdir`` would
    walk past the worktree root and fall through to the script's own
    directory, breaking ``TASKS_FILE`` resolution. ``os.path.exists``
    accepts both shapes.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))


REPO_ROOT = _repo_root()
TASKS_FILE = os.path.join(REPO_ROOT, "review_tasks.md")
INDEX_FILE = os.path.join(REPO_ROOT, ".claude", "review_index.json")


# ── Regex patterns ───────────────────────────────────────────────
# Mirrors the patterns used by batch_work.sh, close_batch.sh, and
# archive_review_tasks.py, but consolidated in one place.

_ROUND_HEADER_RE = re.compile(r"^## (Round \d+.*)$")
# Status charset is `[^`]+`, not `[A-Za-z ]+`. A status carrying a hyphen or a
# digit is a thing a consumer can write, and a reader that cannot see it does
# not prevent it \u2014 it only makes the batch invisible, which is how
# `batch_work.sh --release <N>` came to answer "not found" for a batch plainly
# in the file. Deciding what an undeclared value MEANS belongs to the readers'
# status ladders, not to the pattern that finds the batch.
_BATCH_HEADER_RE = re.compile(
    r"^### Batch (\d+) \u2014 (.+?) `([^`]+)`$"
)
# Permissive twin, used ONLY to notice a `### Batch <N>` line the strict pattern
# rejected so the open batch can be closed. See the closer in
# `parse_review_tasks` for what it prevents.
#
# `\s+`, not literal spaces. The first version of this twin used single literal
# spaces and so was NOT permissive where it mattered: a header with a TAB or a
# double space (`###\tBatch 8`, `###  Batch 8`, `### Batch  8`) fails the strict
# pattern AND fails this one, which is precisely the fall-through the twin
# exists to stop. Phase 191's own adversarial round reproduced the full
# carry-over \u2014 batch 7 returned with `review/batch-8` \u2014 on the fixed tree.
# The twin must be strictly more permissive than the strict pattern in EVERY
# dimension the strict pattern constrains, not just the status charset.
#
# Kept equal to the twins in sitrep_survey.py, next_task.py and
# archive_review_tasks.py \u2014 but note those files' strict patterns differ from
# each other (next_task.py tolerates an ASCII hyphen), so "edit one, edit all"
# applies to THIS pattern, not to the strict ones. tests/test_batch_status_gate.py
# drives every shape against every parser rather than pinning the text.
#
# Phase 209 removed one of those parsers: this comment used to name
# `batch_work.sh`'s bash fallback and its `[[:space:]]` spelling in the present
# tense, and that fallback no longer exists.
#
# NOT the predicate for "is this a batch". `duplicate_batch_numbers` used this
# twin and that was a regression — see its docstring.
_BATCH_HEADER_ANY_RE = re.compile(r"^###\s+Batch\s+\d+\b")
_META_BRANCH_RE = re.compile(r"^> \*\*Branch:\*\* `([^`]+)`")
_META_SCOPE_RE = re.compile(r"^> \*\*Scope:\*\* (.+)")
_META_VERIFY_RE = re.compile(r"^> \*\*Verify:\*\* (.+)")
_META_OVERLAP_RE = re.compile(r"^> \*\*Overlap:\*\* (.+)")
# `Flag:` and `Triaged:` are the two halves of the triage record, and the
# patterns below are duplicated verbatim in sitrep_survey.py. They are pinned
# equal by tests/test_flag_contract.py rather than shared through an import.
#
# The reason is the house pattern, not availability: this module's own header
# says its regexes "mirror the patterns used by batch_work.sh, close_batch.sh
# and archive_review_tasks.py", i.e. this file already duplicates-and-pins
# rather than exports. sitrep_survey.py also imports nothing from a sibling
# today, and giving it its first one would add a new failure surface (path
# bootstrap, this module's import-time REPO_ROOT resolution) to buy a
# cosmetic. If you edit either pattern, edit both — the test names the sites.
#
# `Flag:` = human-readable reason this batch needs judgment. Its presence is
# the pool predicate (/auto-judge takes it, /auto-fix skips it) and this phase
# did not change that. `Triaged:` is the machine-readable verdict record:
# which run classified the batch, what it decided, and — on a flag verdict —
# exactly which tasks need judgment. A `Flag:` line with no `Triaged:` sibling
# has unknown provenance and is treated as *untriaged* by /triage.
_META_FLAG_RE = re.compile(r"^> \*\*Flag:\*\*\s*(.*)$")
_META_TRIAGED_RE = re.compile(
    r"^> \*\*Triaged:\*\* (\d{4}-\d{2}-\d{2}) (auto|flag)"
    r"(?:\s+\[([^\]]*)\])?"
    r"(?:\s+[—–-]\s*(.*?))?\s*$"
)
_TRIAGED_TASK_ID_RE = re.compile(r"TASK-\d+")
_META_OWASP_RE = re.compile(r"^> \*\*OWASP:\*\* (.+)")
# Severity emoji escapes: \U0001f534 = \ud83d\udd34 (high), \U0001f7e1 = \ud83d\udfe1 (medium),
# \U0001f7e2 = \ud83d\udfe2 (low). Matches _SEVERITY_MAP below; keep these in sync.
# Inline comments are not allowed inside a raw-string regex without re.VERBOSE,
# so the marker lives here so grep for "\ud83d\udd34"/"\ud83d\udfe1"/"\ud83d\udfe2" reaches both sites.
_TASK_RE = re.compile(
    r"^- \[( |/|x)\] \*\*(TASK-\d+)\*\*: (.+?)(?:\s+(\U0001f534|\U0001f7e1|\U0001f7e2))?$"
)
_DEFERRED_TASK_RE = re.compile(
    r"^- \[ \] \*\*(TASK-\d+)\*\*: (.+?)(?:\s+(\U0001f534|\U0001f7e1|\U0001f7e2))?"
    r"(?: \u2014 .+)?$"
)
_GRAND_TOTAL_RE = re.compile(
    r"\*\*Grand Total \(all rounds\):\*\* (\d+) tasks"
    r" \u2014 (\d+) done, (\d+) open, (\d+) deferred"
)

_SEVERITY_MAP = {
    "\U0001f534": "high",    # 🔴
    "\U0001f7e1": "medium",  # 🟡
    "\U0001f7e2": "low",     # 🟢
}

_CHECKBOX_MAP = {
    " ": "open",
    "/": "in_progress",
    "x": "done",
}


# ── Checksum ─────────────────────────────────────────────────────

def _file_sha256(path):
    """Compute SHA-256 hex digest of a file.

    Caller contract: the file must exist and be readable. Both callers
    (``parse_review_tasks`` and ``is_stale``) are invoked only after the
    upstream entry points (e.g. ``archive_review_tasks.main``,
    ``rebuild_index`` wrappers) have already opened ``review_tasks.md``
    inside a ``try/except FileNotFoundError``. Raising ``OSError`` from
    here is intentional — a file that disappeared mid-rebuild is a
    surprise the caller should see, not silently mask.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Parser ───────────────────────────────────────────────────────

def parse_review_tasks(path=None):
    """Parse review_tasks.md into a structured dict.

    Returns:
        dict with keys: generated_at, source_sha256, batches, deferred,
        rounds, grand_total, summary
    """
    path = path or TASKS_FILE
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    source_sha = _file_sha256(path)

    batches = {}
    deferred = []
    rounds = []
    grand_total = None

    current_round = None
    current_batch = None
    in_deferred_section = False
    # Fenced content is example text, not structure. A task's remediation
    # routinely quotes the tracker's own shapes — `## Deferred`,
    # `### Batch N — … \`Pending\``, `> **Flag:** <reason>` — and before this
    # was masked, a fenced `> **Flag:**` became the enclosing batch's real
    # verdict (internal tracker #337's failure mode arriving from inside the file) and a fenced
    # `## ` heading truncated the batch.
    fenced = _fenced_mask([ln.rstrip("\n") for ln in lines])

    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        line_num = i + 1  # 1-indexed for sed/grep compatibility

        if fenced[i]:
            continue

        # ── Any level-2 heading closes the open batch ──
        # A batch ends at the next `## ` section or `### Batch` header, never
        # at end-of-file-regardless.
        #
        # Before Phase 181 there were four closers — round header, next batch
        # header, `## Statistics`, and an EOF fallback. The `## Statistics`
        # closer is skipped whenever a `## Deferred` section is still open at
        # that point, because the deferred branch below early-`continue`s; but
        # a `## Round` header clears the flag, so on a tracker whose Deferred
        # section sits *before* the Rounds (GDP's does) the closer fired and
        # the last batch bounded correctly. **What was never bounded is any
        # other trailing section** — above all the `## Convention fire ledger`
        # that `/codebase-review` § 5e parks at end-of-file on purpose, which
        # is neither a Round nor Deferred nor Statistics. That is the live
        # shape, and it appears the first time a round records a stale verdict.
        #
        # The range is not cosmetic: close_batch.sh feeds it to CLOSE_AWK as
        # `-v s -v e`, and `mode=flip` rewrites every `- [ ] **TASK-…**` inside
        # it to `[x]`. Closing here, before the section branches, makes the
        # rule hold regardless of section order — and matches close_batch.sh's
        # own grep fallback (`grep -n '^##'`), so the two range paths agree
        # whether or not python3 is present.
        if line.startswith("## ") and current_batch is not None:
            current_batch["line_end"] = line_num - 1
            _finalize_batch(current_batch)
            batches[str(current_batch["number"])] = current_batch
            current_batch = None

        # ── Round header ──
        m = _ROUND_HEADER_RE.match(line)
        if m:
            current_round = m.group(1)
            rounds.append(current_round)
            in_deferred_section = False
            continue

        # ── Deferred section ──
        # `startswith`, not `strip() ==`: an *indented* `## Deferred` in a
        # task's detail lines is prose, and treating it as a section opener
        # diverted every following task line into `deferred` while the batch
        # stayed open — a divergence from the `startswith("## ")` closer above
        # and from every other reader. Found by the second review round.
        if line.startswith("## Deferred"):
            in_deferred_section = True
            continue

        if in_deferred_section:
            dm = _DEFERRED_TASK_RE.match(line)
            if dm:
                deferred.append({
                    "id": dm.group(1),
                    "description": dm.group(2).strip(),
                    "severity": _SEVERITY_MAP.get(dm.group(3), "unknown"),
                    "line": line_num,
                })
            # Other section headers end the deferred block
            if line.startswith("## ") and line.strip() != "## Deferred":
                in_deferred_section = False
            continue

        # ── Batch header ──
        bm = _BATCH_HEADER_RE.match(line)
        if bm:
            # Close previous batch
            if current_batch is not None:
                current_batch["line_end"] = line_num - 1
                _finalize_batch(current_batch)
                batches[str(current_batch["number"])] = current_batch

            current_batch = {
                "number": int(bm.group(1)),
                "title": bm.group(2).strip(),
                "status": bm.group(3).strip(),
                "branch": "",
                "scope": "",
                "verify": "",
                "overlap": "",
                "flag": "",
                "triaged_date": "",
                "triaged_verdict": "",
                "triaged_tasks": [],
                "triaged_note": "",
                "owasp": "",
                "round": current_round or "",
                "line_start": line_num,
                "line_end": None,
                "tasks": [],
            }
            continue

        # ── A `### Batch <N>` line the strict pattern rejected ──
        # It still closes the open batch. Without this it fell through as
        # ordinary content and the orphan's own `> **Branch:**`/`Scope:`/
        # `Verify:` lines were read as the PREVIOUS batch's — so `batch_work.sh
        # 7` built a worktree named `…-batch-7` on branch `review/batch-8`,
        # carrying batch 8's scope and batch 8's verify command. Measured in
        # this parser and in batch_work.sh's bash fallback alike.
        #
        # This is the same rule as the `## ` closer above, applied to the one
        # heading level that was missing it: a heading ends the batch whether or
        # not the parser could make sense of the heading.
        #
        # Widening the status charset shrinks this class but cannot close it —
        # a header with no status token, or a hyphen where the em-dash belongs,
        # still fails to parse. Those are authoring slips rather than statuses,
        # so the batch stays invisible, which is honest; what it must not do is
        # corrupt a batch that IS visible.
        if _BATCH_HEADER_ANY_RE.match(line):
            if current_batch is not None:
                current_batch["line_end"] = line_num - 1
                _finalize_batch(current_batch)
                batches[str(current_batch["number"])] = current_batch
                current_batch = None
            continue

        # ── Batch metadata (blockquote lines) ──
        if current_batch is not None:
            mm = _META_BRANCH_RE.match(line)
            if mm:
                current_batch["branch"] = mm.group(1)
                continue
            mm = _META_SCOPE_RE.match(line)
            if mm:
                current_batch["scope"] = mm.group(1)
                continue
            mm = _META_VERIFY_RE.match(line)
            if mm:
                current_batch["verify"] = mm.group(1)
                continue
            mm = _META_OVERLAP_RE.match(line)
            if mm:
                current_batch["overlap"] = mm.group(1)
                continue
            mm = _META_FLAG_RE.match(line)
            if mm:
                current_batch["flag"] = mm.group(1)
                continue
            mm = _META_TRIAGED_RE.match(line)
            if mm:
                current_batch["triaged_date"] = mm.group(1)
                current_batch["triaged_verdict"] = mm.group(2)
                current_batch["triaged_tasks"] = _TRIAGED_TASK_ID_RE.findall(
                    mm.group(3) or ""
                )
                current_batch["triaged_note"] = (mm.group(4) or "").strip()
                continue
            mm = _META_OWASP_RE.match(line)
            if mm:
                current_batch["owasp"] = mm.group(1)
                continue

            # ── Task line ──
            tm = _TASK_RE.match(line)
            if tm:
                current_batch["tasks"].append({
                    "id": tm.group(2),
                    "description": tm.group(3).strip(),
                    "severity": _SEVERITY_MAP.get(tm.group(4), "unknown"),
                    "checkbox": _CHECKBOX_MAP.get(tm.group(1), "open"),
                    "line": line_num,
                })
                continue

        # ── Statistics section — detect end of batches ──
        if line.startswith("## Statistics"):
            if current_batch is not None:
                current_batch["line_end"] = line_num - 1
                _finalize_batch(current_batch)
                batches[str(current_batch["number"])] = current_batch
                current_batch = None

        # ── Grand Total ──
        gm = _GRAND_TOTAL_RE.search(line)
        if gm:
            grand_total = {
                "total": int(gm.group(1)),
                "done": int(gm.group(2)),
                "open": int(gm.group(3)),
                "deferred": int(gm.group(4)),
            }

    # Close trailing batch (if file ends without ## Statistics)
    if current_batch is not None:
        current_batch["line_end"] = len(lines)
        _finalize_batch(current_batch)
        batches[str(current_batch["number"])] = current_batch

    # ── Build summary ──
    summary = _build_summary(batches)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_sha,
        "batches": batches,
        "deferred": deferred,
        "rounds": rounds,
        "grand_total": grand_total,
        "summary": summary,
    }


# Fence detection. The blockquote prefix is deliberate: tracker metadata lines
# are `> **Key:**`, so an example of the metadata shape is quoted *inside a
# blockquote*, and a fence rule that cannot see `> ```` misses the one form
# that matters. The close pattern requires nothing but whitespace after the
# run (CommonMark), so a nested ```` ```python ```` opener does not close the
# block it is inside.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})[ \t]*$")


def _fenced_mask(lines):
    """True for every line inside a **balanced** fenced block, delimiters included.

    An **unterminated** fence is deliberately ignored — its lines stay
    structural. Honouring it is strictly worse than having no fence rule at
    all: one stray ``` disables structural parsing to end-of-file, so the
    enclosing batch's ``line_end`` runs to EOF and ``close_batch.sh`` flips
    every checkbox in that range, including a trailing ``## Deferred``
    section's. Phase 181's first fence implementation did exactly that, and
    its second review round caught it by writing a tracker with an unbalanced
    marker — a shape neither the author's fixtures nor the first round had.

    Two passes rather than one state machine for exactly that reason: you
    cannot know a fence is balanced until you have seen the whole file.

    Duplicated verbatim in ``sitrep_survey.py`` and ``next_task.py`` and
    pinned equal by ``tests/test_flag_contract.py`` — the same
    duplicate-and-pin idiom this module's regex header already uses.
    """
    mask = [False] * len(lines)
    start = None
    marker = None
    for i, line in enumerate(lines):
        if start is None:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                start, marker = i, m.group(1)
        else:
            m = _FENCE_CLOSE_RE.match(line)
            if m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker):
                for j in range(start, i + 1):
                    mask[j] = True
                start = marker = None
    return mask


def _unterminated_fence(lines):
    """The opener of a fence that is never closed, or ``None``.

    Returns ``(start_index, marker)`` — ``start_index`` 0-indexed.

    Extracted by Phase 211 so ``unterminated_structural_span`` and
    ``unterminated_batch_span`` share ONE scan. Before the extraction the
    close-predicate — marker character AND marker length, both load-bearing —
    lived here as well as in ``_fenced_mask``. ``Q-228`` rows (3)+(4) were filed
    against it, and Phase 209's guard closed only the ``_fenced_mask`` copy,
    because that is the copy it asserted against. Adding a third copy for the
    new detector would have re-opened the same gap a third time.

    Both halves of the close rule are data-reachable and are guarded in
    ``tests/test_fence_close_predicate.py``: a 4-backtick opener is NOT closed
    by 3 backticks (length), and a ``~~~`` opener is NOT closed by ``` (char).
    """
    start = -1
    marker = ""
    for i, line in enumerate(lines):
        if start < 0:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                start, marker = i, m.group(1)
        else:
            m = _FENCE_CLOSE_RE.match(line)
            if m and marker and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker):
                start, marker = -1, ""

    if start < 0:
        return None
    return (start, marker)


def unterminated_structural_span(lines):
    """Locate an unterminated fence whose body contains STRUCTURAL lines (Q-012).

    Returns ``(fence_line, marker, structural_line, structural_text)`` — all line
    numbers 1-indexed — or ``None``.

    **Why this is not "detect an unbalanced fence".** ``_fenced_mask`` ignores an
    unterminated fence on purpose (see its docstring), so everything from the
    stray opener to EOF stays structural. That is harmless for the overwhelming
    majority of unterminated spans: a task's remediation quoting ``> **Flag:**``
    or a code sample is parsed as prose either way. It becomes a **gate bypass**
    only when the unmasked span contains a line the parser acts on — a
    ``### Batch <N>`` header or a ``## `` section — because ``parse_review_tasks``
    keys batches by number in a dict, so a fenced EXAMPLE batch silently
    *overwrites* the real one and the claim path then reads the example's status.

    Measured before this was written: over ~32,000 lines of real trackers
    (BeanRider, GDP, two archives, the loop-mode dogfood) **zero** carried an
    imbalance at all. Refusing on imbalance alone would therefore have cost
    nothing today and everything on the first legitimate in-flight edit — the
    operator needs ``close_batch.sh`` to work precisely when they are mid-edit.
    Refusing on *consequence* keeps the failure mode and drops the false
    positives.

    The predicates are taken from the parser above rather than restated:
    ``_BATCH_HEADER_ANY_RE`` is the counter at the ``### Batch`` branch and
    ``"## "`` is the level-2 closer. If the parser's notion of structure moves,
    this moves with it.

    Deliberately a SEPARATE function rather than an extra return value from
    ``_fenced_mask``: that helper is pinned byte-identical across four modules by
    ``tests/test_flag_contract.py::test_fenced_mask_bodies_are_identical_in_all_parsers``,
    and changing its shape here would red that pin or force four edits for a
    check only this module needs.

    The signal is the one `/report-issues` and `/share-wins` already ship for
    ``SYSOP_ISSUES.md`` — *"an unterminated fence is reported, never assumed
    shut"* — applied to the tracker.
    """
    # `-1`/`""` rather than the `None` sentinels `_fenced_mask` uses: that helper
    # is byte-pinned and cannot change, but its `marker[0]` reads as an Optional
    # subscript to a type checker. Not repeating the shape here keeps the ratchet
    # clean without touching the pinned copy.
    hit = _unterminated_fence(lines)
    if hit is None:
        return None
    start, marker = hit

    # The span runs to EOF by construction, so "a structural line appears after
    # the stray opener" is true of almost every real tracker and is NOT the
    # defect. The first cut of this function refused on exactly that and
    # false-positived on the ordinary multi-round shape: a fence left open in a
    # Round 1 task, with `## Round 2` below, parses IDENTICALLY to its balanced
    # control — same batches, same statuses, same branches — and was refused
    # anyway, with the diagnostic pointing at `## Round 2`, a line that is not
    # the problem. There is no `--force` here, so that is an operator dead end,
    # and it lands on precisely the mid-edit operator this check is for.
    #
    # What is unambiguously wrong is a **collision**: a `### Batch <N>` inside
    # the span whose number ALSO appears outside it. `parse_review_tasks` keys
    # batches by number, so the fenced example overwrites the real batch and the
    # claim path reads the example's status. No legitimate tracker carries two
    # headers for the same batch number with one of them fenced.
    #
    # A `### Batch <N>` inside the span with a number that appears nowhere else
    # is deliberately NOT refused: it is indistinguishable from a real batch
    # written below a stray fence, which is the common case. A bare `## ` inside
    # the span is not refused either — that truncates the enclosing batch, which
    # is the conservative direction and is `Q-017`'s subject, not this one.
    mask = _fenced_mask(lines)
    outside = set()
    for i in range(start):
        if mask[i]:
            continue
        if _BATCH_HEADER_ANY_RE.match(lines[i]):
            num = re.search(r"\d+", lines[i])
            if num:
                # Normalized, for the reason `duplicate_batch_numbers` states:
                # the collision this reports is an overwrite in a dict keyed by
                # `str(int(...))`, so comparing raw digit runs lets `07` vs `7`
                # slip past. Verified defeated before this normalization.
                outside.add(str(int(num.group())))

    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not _BATCH_HEADER_ANY_RE.match(line):
            continue
        num = re.search(r"\d+", line)
        if num and str(int(num.group())) in outside:
            return (start + 1, marker, j + 1, line.rstrip())
    return None



def unterminated_batch_span(lines):
    """An unterminated fence whose span contains ANY ``### Batch <N>`` (Q-229/Q-231).

    Returns ``(fence_line, marker, batch_line, batch_text)`` 1-indexed, or ``None``.

    **How this differs from ``unterminated_structural_span`` above.** That one
    additionally requires a COLLISION — the fenced number must also appear
    outside the fence. Phase 211 measured two ways past that requirement:

    * ``Q-229`` — run the shipped ``archive_review_tasks.py``, ordinary
      prescribed maintenance. It relocates the completed round, removes the real
      batch, and dissolves the collision; ``--check-fences`` then reports
      ``fences ok`` over a file that still contains the phantom.
    * ``Q-231(2)`` — give the fenced example a number no real batch uses and
      there is no collision to begin with. No archive step required.

    Both end in the same state, so they are one residual reached two ways.

    **Why it stops at a batch header rather than at any structural line.** The
    blanket form — refuse on any ``## `` too — was measured false-firing on
    98.2% and 96.8% of opener positions on two real trackers, because every tracker
    ends in ``## Statistics``; Phase 208 shipped it and reverted it. Requiring a
    ``### Batch`` in the span keeps ``HARMLESS`` (a fence quoting a metadata
    example, with no batch below it) passing, which is the common legal shape.

    **The cost, stated rather than discovered later.** This still cannot separate
    a fenced documentation example from a real batch written below a stray
    fence: an unterminated span runs to EOF, so the two are textually identical
    (see the note in ``unterminated_structural_span``). ``MULTI_ROUND_BENIGN``
    in ``tests/test_fence_refusal.py`` is that case and it refuses here.

    What makes that acceptable is the escape, not a narrowing: the shells accept
    ``--force`` past THIS check while still refusing past the collision above.
    Ambiguity is forceable; a proven impersonation is not. Closing the fence is
    always the correct fix — the file is malformed markdown either way — so the
    remedy is one character, which is what Phase 208's revert note said the
    first cut lacked ("there is no --force, so that was an operator dead end").
    """
    hit = _unterminated_fence(lines)
    if hit is None:
        return None
    start, marker = hit
    for j in range(start + 1, len(lines)):
        if _BATCH_HEADER_ANY_RE.match(lines[j]):
            return (start + 1, marker, j + 1, lines[j].rstrip())
    return None

def duplicate_batch_numbers(lines):
    """Map every repeated batch number to the 1-based lines that declare it.

    ``{"1": [18, 194], "5": [122, 225]}``. A number appearing once is absent,
    so an empty dict means the tracker is unambiguous.

    Reads the SOURCE and reuses this module's own ``_fenced_mask`` and
    ``_BATCH_HEADER_RE``, so "what counts as a batch" cannot drift away from
    ``parse_review_tasks``.

    **It must be the STRICT pattern, not the permissive twin.** The first cut
    used ``_BATCH_HEADER_ANY_RE`` and that was a regression, caught by this
    phase's own review round: ``ANY`` is a superset that exists only to notice a
    header the strict pattern REJECTED, so the open batch can be closed (see its
    definition). Counting those as declarations means a malformed line the
    parser never turns into a batch — ``### Batch 1 draft (superseded)``, a tab
    instead of a space, an ASCII hyphen for the em-dash — is scored as a
    duplicate. Measured: a tracker with one real Batch 1 plus one such near-miss
    produced exactly ONE batch from ``parse_review_tasks`` and was still refused
    at the claim path, with a diagnostic ("would silently pick one and discard
    the other") that was false, and a remedy ("renumber one of them") that did
    not apply. It claimed fine before this phase.

    The harm this detects is ``batches[str(n)] = …`` overwriting an earlier
    entry, and only a STRICT match ever reaches that line. So the strict pattern
    is not merely safer here, it is the correct one.

    **This reports; it does not judge.** Per-round renumbering — a Round 2 that
    restarts at Batch 1 — is a real shape on a real tracker (measured
    2026-08-16: eleven headers, five numbers doubled, no fence anywhere) and
    nothing in the shipped tree forbids it. ``WORKFLOW.md``'s template nests
    ``### Batch <N>`` under ``## Round N`` and states no numbering scope. A
    whole-file refusal would therefore reject a legal tracker — the shape of
    defect Phase 208 shipped and had to reshape mid-round.

    An earlier version of this paragraph added *"and no shipped skill derives
    the next number from existing headers"*. **That is false**, and Phase 211
    corrected it in ``batch_work.sh`` while missing THIS copy: its sweep
    grepped the sentence as one line, and here it wraps across two, so a
    line-oriented search could not see it. Its own round caught that.
    ``codebase-review/SKILL.md:166`` and ``security-audit/SKILL.md:181`` — the
    only two operational writers of ``### Batch`` headers — both derive
    ``next_batch_number`` = highest Batch N + 1, file-globally. It does not
    change this function's scoping decision, which rests on the template's
    silence and on nothing ENFORCING the writers' rule; but the argument is
    narrower than the struck sentence claimed.

    So the ratified contract (2026-08-16) splits by what the caller is about to
    do: a caller that MUTATES asks about the single number it is acting on and
    refuses only if THAT number is ambiguous; a caller that READS surfaces every
    collision as a warning and continues. Both halves live here so the two
    cannot drift apart.
    """
    mask = _fenced_mask(lines)
    seen = {}
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        m = _BATCH_HEADER_RE.match(line)
        if m:
            # `str(int(...))`, matching `parse_review_tasks`'s own key
            # (`"number": int(...)` at :272, stored as `batches[str(number)]`).
            # Keying on the RAW digit run instead lets one leading zero defeat
            # this entire check: `### Batch 07` and `### Batch 7` collapse to a
            # single parser entry — the later silently discarding the earlier,
            # which IS the harm — while raw keys "07" and "7" look distinct and
            # no duplicate is reported. Found by this phase's review round,
            # reproduced end to end: the claim proceeded and created a branch
            # for a batch the file records twice.
            seen.setdefault(str(int(m.group(1))), []).append(i + 1)
    return {n: ls for n, ls in seen.items() if len(ls) > 1}


# Extracts the number from a line the permissive twin matched. Deliberately its
# OWN pattern rather than a group on `_BATCH_HEADER_ANY_RE`, so the twin's text
# is left exactly as its three siblings carry it.
#
# **The first version of this comment claimed the twin is "pinned byte-identical
# across four modules" by `test_fenced_mask_bodies_are_identical_in_all_parsers`.
# That test pins `_fenced_mask`, not the twin, and nothing in the tree compares
# the twin across modules at all** — the round checked. The four are not even
# byte-identical: `archive_review_tasks.ANY_BATCH_HEADER_RE` already carries a
# capture group. Keeping this pattern separate is still right (four hand-kept
# copies should not diverge on a whim), but it is a convention, not an enforced
# invariant, and saying otherwise invents a guard a reader would rely on.
_NEAR_MISS_NUMBER_RE = re.compile(r"^###\s+Batch\s+(\d+)\b")


def near_miss_batch_headers(lines):
    """Lines that LOOK like a batch header but that the strict readers reject.

    Not "that no reader can act on" — an earlier version said that and it is
    false in two directions this phase established itself: `next_task.py`
    deliberately keeps an ASCII-hyphen tolerance (so it offers such a batch as
    claimable, which `batch_work.sh` then refuses), and `close_batch.sh` closes
    one through its grep fallback. The disagreement IS the defect; "nobody sees
    it" would be a tidier problem than the one that exists.

    Returns ``[(lineno_1based, number_or_None, text), ...]`` for every UNFENCED
    line the permissive twin matches and the strict pattern rejects.

    **This is the canon's enforcement surface, and it exists because narrowing
    a reader is the wrong lever.** `WORKFLOW.md`'s two batch-metadata templates
    and both operational writers (`codebase-review/SKILL.md`,
    `security-audit/SKILL.md`) already emit the strict shape — em-dash,
    backticked status — so the contract was never in doubt. What was missing is
    that a header MISSING that shape disappears silently: this module's parser
    and `sitrep_survey.py` drop it without a word, and `next_task.py`'s docstring
    still claims a stderr warning its code never emits (its only stderr write for
    a header is a non-integer-number branch that its own digits-only capture
    group makes unreachable). **Phase 220 did not fix that** — `next_task.py` is untouched by
    it — and an earlier version of this sentence said "until Phase 220", which
    asserted a correction that was never made.

    **Why detection rather than tolerance.** Widening the strict patterns to
    accept an ASCII hyphen would make every currently-invisible header appear at
    once across `/sitrep`, `/next-task`, `/roadmap`, `/triage`, `/auto-fix` and
    `/auto-judge` — on consumer trackers nobody can migrate. No shipped tool
    MIGRATES header spellings: the three that rewrite `review_tasks.md`
    (`close_batch.sh`, `batch_work.sh`, the archiver) only ever flip a status
    token or relocate a round, and `install.sh`'s never-sweep guard names the
    file explicitly. Making things APPEAR silently is the same defect class as
    making them disappear silently, pointed the other way.

    **Why this is not `duplicate_batch_numbers`' predicate.** That function must
    use the STRICT pattern and its docstring records why: counting near-misses
    as declarations produced a false "would silently pick one and discard the
    other" plus a remedy ("renumber one of them") that did not apply. A
    near-miss is not a duplicate. It is a line no reader acts on, which is a
    different fact and gets a different message.

    Fenced lines are excluded via the shared `_fenced_mask`, so a documentation
    example inside a BALANCED fence is not reported — same rule the parser uses.
    An unterminated fence is deliberately ignored by `_fenced_mask` (honouring
    one would disable parsing to end-of-file), so its contents ARE reported;
    `--check-fences` is the surface for that condition.

    **Trailing whitespace is NOT a near miss, and that is a correction from this
    function's own review round.** The strict pattern is `$`-anchored, so
    ``### Batch 1 - Alpha `Merged` `` with one trailing space fails it — but the
    archiver's own ``BATCH_HEADER_RE`` is *not* end-anchored and has always
    archived that header. Refusing over it was a regression: a tracker that
    archived cleanly before Phase 220 refused whole-run after it, and the
    operator was shown an ``rstrip``ped line that looked perfectly canonical
    beside a diagnosis about a missing em-dash they were staring at. Trailing
    whitespace is invisible in rendered markdown and is not what the canon is
    about, so it is normalised away before the test. (``--range`` still cannot
    match such a header — that inconsistency predates this phase and is filed,
    not widened into here.)
    """
    mask = _fenced_mask(lines)
    out = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        stripped = line.rstrip()
        if _BATCH_HEADER_RE.match(stripped):
            continue
        if not _BATCH_HEADER_ANY_RE.match(stripped):
            continue
        m = _NEAR_MISS_NUMBER_RE.match(stripped)
        out.append((i + 1, str(int(m.group(1))) if m else None, stripped))
    return out


def describe_near_misses(near_misses, filename):
    """The one wording for a near-miss report, so surfaces cannot drift apart.

    Returns a list of lines. Callers decide the stream and the exit code; what
    they must not do is invent a second phrasing for the same fact.
    """
    lines = [
        f"WARNING: {filename} has {len(near_misses)} batch header(s) that do "
        f"not match the canonical shape:"
    ]
    for lineno, _num, text in near_misses:
        lines.append(f"         :{lineno} — {text}")
    lines.append(
        "         The canonical shape is: ### Batch <N> — <Title> `<Status>` "
        "(em-dash, backticked status)."
    )
    lines.append(
        "         The readers disagree about these lines, which is the point: "
        "/sitrep and the"
    )
    lines.append(
        "         archiver do not see them at all; /next-task DOES (it tolerates "
        "an ASCII hyphen)"
    )
    lines.append(
        "         and will offer one as a claimable batch that batch_work.sh "
        "then refuses;"
    )
    lines.append(
        "         close_batch.sh closes them via its grep fallback. Nothing "
        "counts them consistently."
    )
    return lines


def _read_source_lines(path=None):
    """Source lines for the detectors above, newline-stripped.

    Deliberately reads the file rather than the index. Routing a detector
    through ``ensure_fresh()`` makes it depend on a cached artifact whose
    staleness is keyed on the source hash alone, so a consumer upgrading Sysop
    holds an index that is still "fresh" while missing any new key — and the
    shells, which discard stderr, would swallow the resulting error and fall
    through. That failure mode was designed, built and measured in Phase 208's
    pre-build pass before being thrown away.
    """
    with open(path or TASKS_FILE, "r", encoding="utf-8", errors="replace") as fh:
        return [ln.rstrip("\n") for ln in fh]


def _warn_on_duplicate_numbers():
    """Surface every duplicated batch number on stderr, and continue.

    The reading half of the contract. It never changes an exit code: a reader
    that refuses takes a routing surface offline over a heading, and
    ``/sitrep``, ``/next-task``, ``/triage``, ``/auto-fix``, ``/auto-judge`` and
    ``/roadmap`` all sit downstream of this data.
    """
    dupes = duplicate_batch_numbers(_read_source_lines())
    if not dupes:
        return
    name = os.path.basename(TASKS_FILE)
    for num in sorted(dupes, key=lambda n: int(n)):
        locs = ", ".join(f":{ln}" for ln in dupes[num])
        print(
            f"WARNING: {name} declares Batch {num} {len(dupes[num])} times ({locs}).\n"
            f"         Batches are keyed by number, so only the last is reported "
            f"here and the earlier one(s) are invisible to this command.",
            file=sys.stderr,
        )


def _finalize_batch(batch):
    """Compute counts for a parsed batch."""
    tasks = batch["tasks"]
    batch["counts"] = {
        "total": len(tasks),
        "open": sum(1 for t in tasks if t["checkbox"] == "open"),
        "in_progress": sum(1 for t in tasks if t["checkbox"] == "in_progress"),
        "done": sum(1 for t in tasks if t["checkbox"] == "done"),
        "high": sum(1 for t in tasks if t["severity"] == "high"),
        "medium": sum(1 for t in tasks if t["severity"] == "medium"),
        "low": sum(1 for t in tasks if t["severity"] == "low"),
    }


def _build_summary(batches):
    """Aggregate batch data into a summary."""
    by_status = {}
    total_tasks = 0
    open_tasks = 0
    done_tasks = 0
    in_progress_tasks = 0

    for b in batches.values():
        status = b["status"]
        by_status[status] = by_status.get(status, 0) + 1
        c = b["counts"]
        total_tasks += c["total"]
        open_tasks += c["open"]
        done_tasks += c["done"]
        in_progress_tasks += c["in_progress"]

    return {
        "total_batches": len(batches),
        "by_status": by_status,
        "total_tasks": total_tasks,
        "open_tasks": open_tasks,
        "in_progress_tasks": in_progress_tasks,
        "done_tasks": done_tasks,
    }


# ── Index I/O ────────────────────────────────────────────────────

def write_index(data, path=None):
    """Write the parsed data to the JSON index file.

    Atomic rewrite via `<path>.tmp` + `os.replace` so a crash mid-write
    cannot leave truncated JSON that `read_index` would then raise on.
    See CLAUDE.md § Data integrity.
    """
    path = path or INDEX_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    # ``errors=`` applies to decoding, not encoding; dropping the param
    # rather than switching to ``"strict"`` mirrors the standard-library
    # default for write-mode handles.
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def read_index(path=None):
    """Read the JSON index file. Returns None if it doesn't exist."""
    path = path or INDEX_FILE
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def is_stale(tasks_path=None, index_path=None):
    """Check if the index is stale (source has changed since last build).

    Returns True if stale or index doesn't exist.
    """
    tasks_path = tasks_path or TASKS_FILE
    index_path = index_path or INDEX_FILE

    index = read_index(index_path)
    if index is None:
        return True

    current_sha = _file_sha256(tasks_path)
    return index.get("source_sha256") != current_sha


def ensure_fresh(tasks_path=None, index_path=None):
    """Rebuild the index if stale, then return the index data."""
    tasks_path = tasks_path or TASKS_FILE
    index_path = index_path or INDEX_FILE

    if is_stale(tasks_path, index_path):
        data = parse_review_tasks(tasks_path)
        write_index(data, index_path)
        return data

    return read_index(index_path)


def rebuild_index(tasks_path=None, index_path=None):
    """Force rebuild the index regardless of staleness."""
    tasks_path = tasks_path or TASKS_FILE
    index_path = index_path or INDEX_FILE

    data = parse_review_tasks(tasks_path)
    write_index(data, index_path)
    return data


# ── Query helpers (for CLI and bash script consumption) ──────────

def list_batches(data):
    """Return tab-separated batch lines matching batch_work.sh format.

    Format: NUMBER<tab>TITLE<tab>STATUS<tab>BRANCH<tab>SCOPE<tab>VERIFY
    """
    lines = []
    for num in sorted(data["batches"].keys(), key=int):
        b = data["batches"][num]
        lines.append(
            f"{b['number']}\t{b['title']}\t{b['status']}\t"
            f"{b['branch']}\t{b['scope']}\t{b['verify']}"
        )
    return lines


def get_batch(data, batch_num):
    """Return a single batch dict, or None."""
    return data["batches"].get(str(batch_num))


def get_batch_range(data, batch_num):
    """Return (line_start, line_end, status, branch) for a batch.

    line_start and line_end are 1-indexed, matching grep -n / sed output.
    Returns None if batch not found.
    """
    b = get_batch(data, batch_num)
    if b is None:
        return None
    return (b["line_start"], b["line_end"], b["status"], b["branch"])


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Shadow JSON index for review_tasks.md"
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Force rebuild the index"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check if index is fresh (exit 0) or stale (exit 1)"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all batches (tab-separated, batch_work.sh format)"
    )
    parser.add_argument(
        "--batch", type=int, metavar="N",
        help="Show details for batch N"
    )
    parser.add_argument(
        "--range", type=int, metavar="N",
        help="Show line range for batch N (for sed operations)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output in JSON format (for --batch)"
    )
    parser.add_argument(
        "--check-fences", action="store_true",
        help="Exit 3 if an unterminated fence contains a DUPLICATE batch header "
        "(Q-012); exit 5 if it contains any batch header (Q-229/Q-231)"
    )
    parser.add_argument(
        "--fenced-lines", action="store_true",
        help="Print the 1-based line numbers inside balanced fences, comma-"
             "separated, for close_batch.sh's rewriter (Q-017)"
    )
    parser.add_argument(
        "--check-duplicates", type=int, metavar="N",
        help="Exit 4 if batch N is declared more than once (Q-037). Scoped to N "
             "on purpose: per-round renumbering is legal, so a whole-file "
             "refusal would reject a valid tracker."
    )
    parser.add_argument(
        "--check-headers", action="store_true",
        help="Exit 6 if any unfenced line looks like a batch header but does "
             "not match the canonical shape (Q-017/Q-037/Q-242/Q-274)."
    )

    args = parser.parse_args()

    if not os.path.isfile(TASKS_FILE):
        print(f"ERROR: {TASKS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    # ── Fence refusal (Q-012) ────────────────────────────────────
    #
    # Read the SOURCE, never the index. Routing this through ensure_fresh()
    # would make the check depend on a cached artifact whose staleness is keyed
    # on the source hash alone — a consumer upgrading Sysop holds an index that
    # is still "fresh", so any new key read from it raises on the first run and
    # the shells, which discard stderr and swallow the status, fall through to
    # the grep fallback for EVERY batch. That failure mode was designed, built
    # and measured in this phase's pre-build pass before being thrown away; it
    # is recorded here because the cheap-looking version of this check
    # reintroduces it.
    #
    # Exit 3 is unused: argparse takes 2, every other error path takes 1.
    def _refuse_on_structural_fence():
        with open(TASKS_FILE, "r", encoding="utf-8", errors="replace") as fh:
            src = [ln.rstrip("\n") for ln in fh]
        hit = unterminated_structural_span(src)
        if hit is None:
            return
        fence_line, marker, struct_line, struct_text = hit
        print(
            f"ERROR: unterminated `{marker}` fence opened at "
            f"{os.path.basename(TASKS_FILE)}:{fence_line}\n"
            f"       contains a duplicate batch header at :{struct_line} — {struct_text}\n"
            f"       That number already appears outside the fence, and batches are "
            f"keyed by number, so the fenced copy overwrites the real batch.\n"
            f"       Close the fence in {os.path.basename(TASKS_FILE)} and re-run.",
            file=sys.stderr,
        )
        sys.exit(3)

    def _refuse_on_open_fence():
        """Exit 5 when an unterminated fence's span contains a ``### Batch``
        header. Forceable (``--allow-open-fence``); exit 3 is not.

        NOT "any unterminated fence" — an earlier version of this line said so
        and was wrong about the function directly below it. A span containing no
        batch header is deliberately not refused, which is the narrowing that
        keeps a fence quoting a metadata example legal.
        """
        with open(TASKS_FILE, "r", encoding="utf-8", errors="replace") as fh:
            src = [ln.rstrip("\n") for ln in fh]
        hit = unterminated_batch_span(src)
        if hit is None:
            return
        fence_line, marker, batch_line, batch_text = hit
        print(
            f"ERROR: unterminated `{marker}` fence opened at "
            f"{os.path.basename(TASKS_FILE)}:{fence_line}\n"
            f"       contains a batch header at :{batch_line} — {batch_text}\n"
            f"       Nothing can tell that header apart from a real batch: an "
            f"unterminated span runs to EOF, so a documentation example and a "
            f"real batch below a stray fence look identical.\n"
            f"       Close the fence at {os.path.basename(TASKS_FILE)}:{fence_line} "
            f"and re-run. If the tracker is correct as written, the shells take "
            f"--allow-open-fence.",
            file=sys.stderr,
        )
        sys.exit(5)

    if args.check_fences:
        _refuse_on_structural_fence()
        _refuse_on_open_fence()
        print("fences ok")
        sys.exit(0)

    # ── Fenced-line export for close_batch.sh's rewriter (Q-017) ──
    #
    # `review_index.py --range` returns a fence-AWARE span and CLOSE_AWK then
    # rewrote it fence-BLIND: measured 2026-08-16, the index path reported
    # "4 tasks closed" on a three-task batch and marked a task that exists only
    # inside a fenced documentation example as completed work. Fence-awareness in
    # the parser bought nothing for the rewriter.
    #
    # This exports the mask rather than teaching awk to find fences, and the
    # distinction is the whole point of this phase: a fence parser written in awk
    # would be a SIXTH implementation of a rule that already exists four times in
    # Python and had two divergent copies in bash. `_fenced_mask` stays the one
    # definition; awk just consumes its answer.
    #
    # Line numbers are 1-based to match awk's NR. close_batch.sh's flip pipeline
    # feeds awk from a `sed` whose own comment records that it changes no line
    # count, so NR and the file's line numbers agree.
    if args.fenced_lines:
        mask = _fenced_mask(_read_source_lines())
        print(",".join(str(i + 1) for i, m in enumerate(mask) if m))
        sys.exit(0)

    # ── Duplicate-number refusal, scoped to the acted-on number (Q-037) ──
    #
    # Reads the SOURCE for the reason `_read_source_lines` states. Exit 4:
    # argparse takes 2, the fence refusal takes 3, every other path takes 1.
    #
    # Why this is scoped to N rather than the file: measured 2026-08-16, a real
    # tracker restarts batch numbering per round (Round 1: 1-6, Round 2: 1-5).
    # Nothing in the shipped tree forbids that, so refusing the file would
    # reject a legal shape. Refusing only the number being acted on stops the
    # operator exactly when acting would be a coin flip, and leaves every
    # unambiguous batch on that file usable.
    # ── Near-miss headers (Q-017/Q-037/Q-242/Q-274) ──────────────
    #
    # Exit 6. Codes in use: 1 error, 2 argparse, 3 structural fence, 4 duplicate
    # batch, 5 open fence. Unlike `--check-duplicates` this is NOT probed by any
    # caller, so it is free to refuse.
    #
    # Whole-file, unlike `--check-duplicates`'s deliberate per-number scoping —
    # and the asymmetry is the point. That scoping exists because per-round
    # renumbering is a LEGAL tracker shape, so a whole-file duplicate refusal
    # would reject valid work. There is no legal shape in which a header misses
    # the canonical form on purpose: `WORKFLOW.md`'s two batch-metadata
    # templates document one spelling and both operational writers emit it. So
    # nothing valid is rejected by reporting all of them.
    if args.check_headers:
        near = near_miss_batch_headers(_read_source_lines())
        if not near:
            print("no near-miss batch headers")
            sys.exit(0)
        for line in describe_near_misses(near, os.path.basename(TASKS_FILE)):
            print(line, file=sys.stderr)
        sys.exit(6)

    if args.check_duplicates is not None:
        n = str(args.check_duplicates)
        dupes = duplicate_batch_numbers(_read_source_lines())
        if n in dupes:
            locs = ", ".join(f":{ln}" for ln in dupes[n])
            print(
                f"ERROR: {os.path.basename(TASKS_FILE)} declares Batch {n} "
                f"{len(dupes[n])} times ({locs}).\n"
                f"       Batches are keyed by number, so acting on Batch {n} "
                f"would silently pick one and discard the other.\n"
                f"       Renumber one of them, or act on an unambiguous batch.",
                file=sys.stderr,
            )
            sys.exit(4)
        # A near-miss for THIS number is not a duplicate and must not be
        # reported as one (see `duplicate_batch_numbers`' docstring: the false
        # "renumber one of them" remedy is exactly what a widened predicate
        # produced). But `next_task.py`'s duplicate warning names this check as
        # "the authority", so answering a bare "unambiguous" over a line no
        # reader can act on is the check lying about its own subject — `Q-242`.
        #
        # The EXIT CODE deliberately stays 0. Two callers depend on it:
        # `close_batch.sh`'s per-batch ambiguity check and `batch_work.sh`'s
        # `refuse_on_duplicate_number` both branch on rc 4 alone, and
        # `batch_work.sh`'s `require_index_parser` probe runs
        # `--check-duplicates 0` and clears its result on ANY non-zero
        # (`|| probe=""`), so a new refusal code here would make a near-miss
        # numbered 0 refuse every batch_work.sh invocation in the repo.
        # Refusal belongs to `--check-headers`, which no caller probes with.
        near = [nm for nm in near_miss_batch_headers(_read_source_lines())
                if nm[1] == n]
        if near:
            # **STDERR for the report, STDOUT for the answer, and the split is
            # the whole of whether this fix reaches anyone.** The first cut put
            # the report on stdout — and both automated callers capture stderr
            # while DISCARDING stdout (`2>&1 >/dev/null`, `close_batch.sh` and
            # `batch_work.sh`'s `refuse_on_duplicate_number`), so the fix for
            # "the check lies about its own subject" was visible only on a
            # hand-run. That is the same "addressed to an empty room" defect
            # this phase fixes in `close_batch.sh`'s other half, committed in
            # the same change. Found by the round.
            #
            # stdout still carries a one-line answer because
            # `require_index_parser`'s probe fails an EMPTY stdout.
            for line in describe_near_misses(near, os.path.basename(TASKS_FILE)):
                print(line, file=sys.stderr)
            print(
                f"batch {n} has no duplicate STRICT header, but the line(s) "
                f"reported on stderr declare it in a shape no reader parses."
            )
            sys.exit(0)
        print(f"batch {n} unambiguous")
        sys.exit(0)

    # --check: just report staleness
    if args.check:
        if is_stale():
            print("stale")
            sys.exit(1)
        else:
            print("fresh")
            sys.exit(0)

    # --rebuild: force rebuild
    if args.rebuild:
        data = rebuild_index()
        n = len(data["batches"])
        print(f"Rebuilt index: {n} batches, {data['summary']['total_tasks']} tasks")
        sys.exit(0)

    # All query modes auto-ensure freshness
    data = ensure_fresh()

    # --list
    if args.list:
        # The reading half of the Q-037 contract. `list_batches` renders the
        # dict, so a duplicated number is already collapsed by the time we get
        # here and no row can show the loss — the warning is the only place the
        # operator learns a batch is missing. stdout stays byte-identical so
        # every existing consumer of this format is unaffected.
        _warn_on_duplicate_numbers()
        for line in list_batches(data):
            print(line)
        sys.exit(0)

    # --batch N
    if args.batch is not None:
        b = get_batch(data, args.batch)
        if b is None:
            print(f"Batch {args.batch} not found", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(b, indent=2, ensure_ascii=False))
        else:
            print(
                f"{b['number']}\t{b['title']}\t{b['status']}\t"
                f"{b['branch']}\t{b['scope']}\t{b['verify']}\t"
                f"{b['line_start']}\t{b['line_end']}"
            )
        sys.exit(0)

    # --range N
    if args.range is not None:
        # Defence in depth. The shells run the preflight before this, under a
        # byte-identical availability guard, so this can only fire in the window
        # between the two — a `git pull` on the claim path, or close_batch's own
        # per-batch loop. What happens when it fires now differs by caller, and
        # Phase 211 changed one of the two:
        #
        #   batch_work.sh — REFUSES. Its `|| true` still swallows the status,
        #     but the grep fallback that used to absorb the empty result is gone
        #     (Q-017), so an unset range is a loud refusal on both the claim and
        #     the --release paths. This is the safe direction: --release's range
        #     bounds the completed-work check, so a fence-blind range there was a
        #     safety-guard bypass, not a miscount.
        #
        #   close_batch.sh — still degrades to its grep fallback, which was
        #     measured CORRECT on this shape: it emits both batch rows and the
        #     consumer takes the first (the real one), where the index keys by
        #     number and lets the fenced example overwrite it. That is why no
        #     exit-code plumbing is threaded through find_batch_range, whose only
        #     caller (`if ! find_batch_range`) cannot observe a return code.
        #
        # An earlier version of this comment stated the degrades-to-the-fallback
        # outcome universally. It was written when both scripts had a fallback;
        # asserting it of batch_work.sh is now false.
        _refuse_on_structural_fence()
        # Q-037: `--list` has warned since Phase 209; this path did not, and it
        # is the one the shells take. The mutating callers refuse an ambiguous
        # number before they get here, so this is defence in depth rather than
        # the primary surface — kept because the refusal is scoped to ONE
        # number and this warning names every duplicate in the file.
        _warn_on_duplicate_numbers()
        r = get_batch_range(data, args.range)
        if r is None:
            print(f"Batch {args.range} not found", file=sys.stderr)
            sys.exit(1)
        start, end, status, branch = r
        print(f"{start}\t{end}\t{status}\t{branch}")
        sys.exit(0)

    # Default: ensure index is fresh, report status
    data = rebuild_index()
    n = len(data["batches"])
    pending = data["summary"]["by_status"].get("Pending", 0)
    in_prog = data["summary"]["by_status"].get("In Progress", 0)
    print(
        f"Index fresh: {n} batches "
        f"({pending} pending, {in_prog} in progress, "
        f"{data['summary']['total_tasks']} tasks)"
    )


if __name__ == "__main__":
    main()
