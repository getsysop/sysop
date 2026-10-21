#!/usr/bin/env python3
"""claim_record.py — `/claim-task` Step 7f item 1: write `## Test decision` and `## Plan` into the body file.

    python3 sysop/scripts/claim_record.py "<CLAIM_ID>" "<RUN_ID>" "<BODY_PATH>" '<TEST_DECISION>'

Run in the main checkout. Option C: writes the planner's test decision and plan into the task's
body file and reports whether the sealed plan-review report is present.

The skill text is the contract: `/claim-task`'s step says what each line and each exit
code means. This file was that step's heredoc until Phase 386 (`Q-409` P3, with `Q-665`'s
command-length limit), moved verbatim.
"""
import os, sys, json, subprocess, tempfile
from pathlib import Path

claim_id, run_id, body_rel, test_decision = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
if "<" in claim_id or "<" in run_id or "<" in body_rel:
    print("ERROR: placeholder not substituted: {!r} {!r} {!r}".format(
        claim_id, run_id, body_rel), file=sys.stderr)
    sys.exit(2)
if not test_decision.strip() or "<" in test_decision:
    print("ERROR: <TEST_DECISION> not substituted -- the plan's Test decision is required "
          "here, because option C has no executor to write it later", file=sys.stderr)
    sys.exit(2)

common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
run_dir = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id
if not run_dir.is_dir():
    print("ERROR: no such run directory {}".format(run_dir), file=sys.stderr)
    sys.exit(3)

plan_md = run_dir / "plan.md"
if not plan_md.is_file():
    print("ERROR: no plan.md in {} -- refusing to write an empty plan back".format(run_dir),
          file=sys.stderr)
    sys.exit(4)
try:
    plan_text = plan_md.read_text(encoding="utf-8").strip()
except (OSError, UnicodeDecodeError) as e:
    print("ERROR: {} could not be read ({}: {})".format(plan_md, type(e).__name__, e),
          file=sys.stderr)
    sys.exit(4)
if not plan_text:
    print("ERROR: plan.md is empty", file=sys.stderr)
    sys.exit(4)

# Both body forms, exactly as /review-close Step 2d resolves them. The canonical value
# every writer emits is `open/<ID>.md` RELATIVE TO `tasks/`; assuming the other form is
# the documented way to make this block fail on a real queue while passing on a fixture.
body = main_root / "tasks" / body_rel
if not body.is_file():
    body = main_root / body_rel
if not body.is_file():
    print("ERROR: body not found for {!r} (tried tasks/-relative and repo-relative)".format(
        body_rel), file=sys.stderr)
    sys.exit(5)
# Write THROUGH a symlink, not over it: `tmp.replace(body)` on a symlinked body would
# swap the link for a regular file and leave the real target stale.
body = body.resolve()

# The sealed report is the reviewer's ONE unforgeable channel and it lives only in the
# envelope. An absent one is RECORDED, never silently dropped -- a missing record and a
# lost one must not look the same (Step 7c's transport check writes the same distinction
# to review-transport.md).
env_path = main_root / "sysop" / "runtime" / "subagent-envelopes" / (claim_id + ".review.json")
sealed = None
if env_path.is_file():
    try:
        sealed = json.loads(env_path.read_text(encoding="utf-8")).get("review_report_raw")
    except ValueError:
        sealed = None

def fence_mark(line):
    """`(char, length)` if this line is a fence marker, else None.

    Reports only that the line IS a marker. Whether it *closes* an open fence is
    `fence_closes`' question -- an opener may carry an info string (this writer
    emits `fence + "markdown"` below), a closer may not."""
    s = line.lstrip()
    for ch in ("`", "~"):
        if s.startswith(ch * 3):
            n = 0
            while n < len(s) and s[n] == ch:
                n += 1
            return ch, n
    return None

def fence_closes(line, open_mark):
    """True only if `line` CLOSES the fence `open_mark` opened.

    Three properties, not two. Same character, at least as long -- and **no info
    string**, which is the one an opener is allowed to carry and a closer is not.
    A ```json line nested inside a plain ``` fence satisfies the first two, so a
    reader without the third believes it has LEFT the fence while still inside it,
    and then reads the fence's own lines as content. That is the fabricating
    direction, not the dropping one (`Q-468`).

    The closer decision lives here, in one place, precisely because it was split
    across two loops before and only one of them remembered it."""
    mark = fence_mark(line)
    return (bool(mark) and mark[0] == open_mark[0] and mark[1] >= open_mark[1]
            and not line.strip().strip(mark[0]))

def strip_sections(lines, headings, preserve=()):
    """Drop each `## <heading>` through the line before the next `## `.

    Returns `(kept, insert_at, unbalanced, saved)`. `insert_at` is where the
    EARLIEST removed section began, so the rewrite lands back in the position it
    held rather than at the end of the file; `None` means none of them were
    present and the caller appends. `unbalanced` reports an unterminated fence,
    on which the caller REFUSES -- see the note at the return.

    `preserve` names headings to remove from the body but hand BACK to the
    caller in `saved` (keyed by the lowercased canonical heading, the original
    heading line included), so the caller can re-emit them at a mandated
    position instead of leaving them where they fell. It exists for one
    concrete defect (`Q-461`): the caller strips `## Test decision` and
    `## Plan` and reinserts them as one contiguous block at `insert_at`, so a
    body in the schema's own order -- `Test decision / Also fixed / Plan` --
    came out `Test decision / Plan / Also fixed`, inverting the order
    `tasks/schema.md` calls load-bearing. Two insertion points would need a
    second fence-aware walk over `out`; preserving through THIS walk keeps the
    fence arithmetic single-sourced, which matters in a helper that has
    produced silent section loss twice.

    `preserve` matches at `## ` by SEARCH rather than equality: a match is
    `## <name>` or a heading beginning `## <name> `. That was forced by grepping
    the live consumer corpus -- `## Also fixed (PR 1)` and `## Also fixed (PR 0)`
    are real headings in one task body, and an equality test would leave each
    where it was, i.e. still sitting after `## Plan`, while reporting nothing,
    because this arm is silent by design. The re-emitted heading is the caller's
    original line, so the suffix survives.

    **Matching at `## ` only is a decision, not an oversight, and it was made by
    reverting the alternative.** A first cut matched any heading level. The
    corpus does not support it -- of 12 `Also fixed` headings, the only
    non-`## ` one is `tasks/schema.md`'s own section header, and no task body
    carries the shape -- and it cost three defects: hoisting a deeper heading
    RE-PARENTS it (an edit to the consumer's content, not a move), the hoisted
    section then landed after `## Plan` so the NEXT run consumed it as part of
    the plan section and dropped it, and a `# Also fixed` at h1 swallowed every
    following `## ` section into the sink. Handling a deeper heading correctly
    means deciding whether re-parenting is acceptable, which is a design
    question; it is filed, not fixed here.

    `headings` keeps equality at `## ` for the same reason plus one more: the
    corpus carries `### Test decision` headings that this helper therefore does
    not strip, so the caller inserts a SECOND section and a first-match reader
    can meet the stale one. That is pre-existing and separately filed, and must
    not be "tidied" into this line without the double-section case being handled.

    FENCE-AWARE on purpose, and it tracks fence LENGTH rather than just the
    marker. A task body can carry ``` or ~~~ blocks whose content starts with
    `## `, and a fence-blind slice either stops early (leaving half a section)
    or runs to EOF (eating every section after it). Length matters because the
    block below writes the plan inside a fence made LONGER than any backtick
    run in it -- so a plain ``` inside that plan must NOT be read as closing
    it. A closer must use the same character and be at least as long, and
    carry no info string.
    """
    want = {"## " + h.lower() for h in headings}
    keep = ["## " + h.lower() for h in preserve]
    out, fence, skipping, insert_at = [], None, False, None
    saved, sink = {}, None
    for ln in lines:
        mark = fence_mark(ln)
        if fence is None:
            if mark:
                fence = mark
            else:
                low = ln.strip().lower()
                # Equality for `headings`; search at `## ` for `preserve`.
                key = None
                for k in keep:
                    if low == k or low.startswith(k + " "):
                        key = k
                        break
                if low in want or key is not None:
                    if insert_at is None:
                        insert_at = len(out)
                    skipping = True
                    # `sink` is None for a stripped-and-discarded section and a list
                    # for a preserved one, so the two share one walk without either
                    # branch having to know about the other.
                    sink = saved.setdefault(key, []) if key is not None else None
                    if sink is not None:
                        sink.append(ln)
                    continue
                elif skipping and ln.startswith("## "):
                    skipping = False
                    sink = None
        elif fence_closes(ln, fence):
            fence = None
        if skipping:
            if sink is not None:
                sink.append(ln)
        else:
            out.append(ln)
    # An UNTERMINATED fence means the body's own fencing is unbalanced, and the
    # scan above cannot then tell a heading from fenced text -- so `skipping`
    # never resets and every remaining section is dropped. That is silent data
    # loss in a tracked file, so the caller refuses instead of writing.
    # This is a BACKSTOP, not the fix: the fence arithmetic below is what stops
    # this block producing an unbalanced body in the first place. It exists
    # because an independent reviewer reached it with ordinary reviewer output.
    return out, insert_at, fence is not None, saved

# newline="" disables universal-newline translation, so a CRLF body is not silently
# rewritten LF throughout -- which showed as a whole-file diff rather than the ~20 added
# lines. Normalise for processing, restore on write.
#
# `open(...)` rather than `Path.read_text(..., newline="")`: `read_text` did not
# accept `newline` until Python 3.13, and this tree's floor is 3.9
# (`tests/test_python_floor_portability.py`). Measured on four interpreters --
# 3.9.6, 3.11.12 and 3.12.13 all raise `read_text() got an unexpected keyword
# argument 'newline'`; only 3.13 accepts it. So this read FATALED on the floor
# AND on every currently-supported Python below 3.13, taking the whole option-C
# body rewrite with it. It went unseen because the suite's venv is 3.14.
# `open` has accepted `newline` since 3.0.
try:
    with open(body, encoding="utf-8", newline="") as _f:
        raw = _f.read()
except (OSError, UnicodeDecodeError) as e:
    print("ERROR: {} could not be read ({}: {}) -- nothing was written".format(
        body, type(e).__name__, e), file=sys.stderr)
    sys.exit(5)
crlf = "\r\n" in raw
text = raw.replace("\r\n", "\n")
# Replace IN PLACE, both sections, at the position the earlier of them held.
# Appending instead would leave two `## Plan` sections on a second option-C run --
# and Step 7a's presence test reads whichever comes first, i.e. the stale one --
# and on the FIRST run it would push both sections below `## Surfaced by`, which
# is not the order `tasks/schema.md` documents.
lines, insert_at, unbalanced, saved = strip_sections(
    text.split("\n"), ("Test decision", "Plan"), preserve=("Also fixed",))
if unbalanced:
    print("ERROR: {} has an unterminated code fence -- refusing to rewrite it, because a "
          "section scan cannot tell a heading from fenced text in that state and would drop "
          "every section after it. Fix the body's fencing and re-run.".format(body),
          file=sys.stderr)
    sys.exit(6)
if insert_at is None:
    insert_at = len(lines)
# Normalise blank lines on BOTH sides of the insertion point, so the block below
# supplies exactly one separator each way. Without this the rewrite is not
# idempotent: running option C twice on the same task accretes one blank line per
# run, which a diff shows and a reader does not. Found by running it twice.
while insert_at > 0 and not lines[insert_at - 1].strip():
    lines.pop(insert_at - 1)
    insert_at -= 1
while insert_at < len(lines) and not lines[insert_at].strip():
    lines.pop(insert_at)

# A fence longer than any run of backticks in EITHER embedded document, so an ordinary
# ```bash block inside them cannot terminate it. Demoting their own headings instead
# would need a fence-aware rewriter over sub-agent prose; this needs arithmetic.
#
# BOTH, not just the plan. An earlier cut computed this over `plan_text` alone and wrapped
# the sealed report in a bare ```yaml -- and a reviewer quoting a fenced snippet in a
# finding's `evidence:` field is ordinary output, not an adversarial payload. That broke
# the wrapper, and the NEXT option-C run's strip then desynced and deleted every section
# after it. Found by an independent reviewer running two consecutive runs on realistic
# input; the author's own fence test covered only the plan.
longest = 0
for doc in (plan_text, sealed or ""):
    run = 0
    for ch in doc:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
fence = "`" * max(3, longest + 1)

block = [
    "",
    "## Test decision",
    "",
    test_decision.strip(),
    "",
]
# `## Also fixed` is re-emitted HERE, between the two sections, because
# `tasks/schema.md` orders it between them and this writer is the only thing that
# can place it (`Q-461`). It was not stripped before, so it survived into `out`
# AFTER `insert_at` was captured, and the reinserted block landed in front of it --
# turning the schema's order into `Test decision / Plan / Also fixed`. Reached
# independently by two reviewers and confirmed by executing the helper.
#
# Content is the consumer's; it is carried through unjudged. Trailing blanks are
# dropped so the single "" below is the only separator, matching the blank-line
# hygiene the insertion-point normalisation above establishes -- without it a
# second option-C run accretes one blank line per run.
# Keyed by the canonical `"## <name>"`, matching `keep` in `strip_sections`.
# Getting this key wrong is silent data loss, not a no-op: the section is stripped
# either way, and a lookup that misses simply fails to re-emit it. It has now been
# wrong twice in this phase -- once in each direction, as the matching rule moved --
# and both times the CONTENT test caught it while a heading test would not have.
also = saved.get("## also fixed") or []
while also and not also[-1].strip():
    also.pop()
if also:
    block += also + [""]
block += [
    "## Plan",
    "",
    "_Written by `/claim-task --plan-only` (option C), run `{}`. The plan below was "
    "adversarially reviewed before it was written here; the sealed report follows it. "
    "A later `/claim-task {}` reads this section as a PRESENCE test, skips the planner, "
    "and re-reviews the plan against today's `main`._".format(run_id, claim_id),
    "",
    fence + "markdown",
    plan_text,
    fence,
    "",
    "### Sealed review report",
    "",
]
if sealed:
    block += [fence + "yaml", sealed.strip(), fence, ""]
else:
    block += [
        "_No sealed `REVIEW_REPORT:` block reached the orchestrator for this run "
        "(`review-transport.md` in the run directory records which of `NO_ENVELOPE` or "
        "`EMPTY_TRANSPORT` applied). The reviewer's full findings were written to "
        "`review.md` in that directory. This absence is recorded rather than omitted: "
        "a review whose verdict did not arrive must not read like one that had none._",
        "",
    ]

out = "\n".join(lines[:insert_at] + block + lines[insert_at:]).rstrip() + "\n"
if crlf:
    out = out.replace("\n", "\r\n")
# `mkstemp` rather than a fixed `<path>.tmp` (`Q-444`): the same collision class
# `Q-382` closed for the claim paths and `Q-414` for the close path, on the task
# BODY rather than on `tasks/index.yml`. Exposure is lower here -- a body is
# written by the one session that claimed that task -- but the shape is the
# tree's. THREE of the four elements answer a defect the conversion would
# otherwise INTRODUCE: the mode carried across (`mkstemp` creates 0600 and would
# silently narrow a 0644 tracked body), `dir=` the target's own directory (same
# filesystem, so `os.replace` cannot raise `EXDEV`), and the cleanup arm (a
# fixed-name leak self-heals on the next run, because the next run writes the
# same path; a `mkstemp` leak does not). The fourth, `realpath`, is REDUNDANT
# here and kept only for shape: `body = body.resolve()` already ran above, so
# this block was never writing over a symlink. Measured: the pre-fix form left
# the link intact and grew the real file, same as this one.
#
# `os.fdopen(..., newline="")` rather than `Path.write_text(..., newline="")`:
# `write_text` did not accept `newline` until Python 3.10, and this tree's floor
# is 3.9 (`tests/test_python_floor_portability.py`). Measured on stock macOS
# /usr/bin/python3 3.9.6: `write_text() got an unexpected keyword argument
# 'newline'` -- so this write FATALED on the floor interpreter, taking the whole
# option-C plan write with it. `open`/`fdopen` have accepted `newline` since 3.0.
real = os.path.realpath(body)
try:
    mode = os.stat(real).st_mode & 0o7777
except OSError:
    mode = 0o644
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real),
                           prefix=os.path.basename(real) + ".", suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    os.chmod(tmp, mode)
    os.replace(tmp, real)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise
print("wrote {} ({} bytes)".format(body, len(out)))
print("sealed_report: " + ("present" if sealed else "ABSENT"))
