"""Drift guards — Phase 165: nothing prescribes a wholesale worktree wipe as a
single-target rollback, and the canonical table says what the script really does.

The defect these guard against was a *class* with a root cause upstream of every
member. `cleanup_worktrees.sh` reads only `$1`, so it has no path operand and no
single-target mode; `--force` removes every non-main worktree. Three skill sites
nonetheless prescribed it as the rollback "on the orphan" (`claim-task` Step 4's
rollback, `/auto-build` Step 5 abort handling, `/auto-build` Step 8's FAILED-task
advice), so one failed claim would have destroyed every concurrent claim's
uncommitted work — and Step 8 additionally claimed it "clears the lock", which the
script has no code for.

The root cause: WORKFLOW.md § 8.4 — the canonical description of `sysop/scripts/`
— listed it as `cleanup_worktrees.sh [--clean]` / "List or remove merged
worktrees". `--force` was absent from the table entirely and "merged" is the exact
wrong premise the three sites acted on. A fix confined to the skills would leave
the row that licenses the belief, so `test_workflow_8_4_row_states_the_real_scope`
guards the row's *content*. (For anyone inheriting the filed version of this item:
`tests/test_workflow_scripts_table.py` was reported as pinning that row, but its
regex captures the filename only and discards the whole description cell — the
misleading text was unguarded, not test-anchored. Verified by restoring the
pre-fix row and running that guard: it passes. That is why this module exists
rather than an amendment to that one.)

## What these guards can and cannot do — read before trusting them

**The real safety net is not here.** It is in the script: `--force <path>` now
exits 1 instead of silently meaning "remove them all", so the wrong belief is
non-executable no matter what any document says. These guards are
defence-in-depth on the *prose*, and their limits are load-bearing enough to
state rather than discover:

- **They cannot tell a prescription from a description.** That is a coherence
  judgement, not a pattern. `test_every_force_mention_states_its_scope` uses the
  best available proxy — a `--force` mention must state on-the-spot that the mode
  is wholesale — which catches the historical defect (all three wrong sites made
  no such statement) but **passes a prescription that admits its own scope**
  ("run `--force` on the orphan — yes, all non-main worktrees go"). Phase 165's
  own round demonstrated exactly that bypass. Nothing short of reading the
  sentence catches it.
- **`test_workflow_8_4_row_states_the_real_scope` is a reversion guard, not a
  semantics guard.** It asserts five facts are *present* in the row. A rewrite can
  contain all five as disconnected substrings and still assert the opposite; the
  round demonstrated that too. What it does reliably catch is the realistic
  drift — someone shortening the row back toward "List or remove merged
  worktrees" — because that deletes the facts.
- **A flag held in a shell variable escapes the proximity window** if the
  assignment is far from the invocation.

These are documented holes, not accepted-and-forgotten ones. **Adding a new
honest phrasing to `SCOPE_MARKERS` is expected maintenance; deleting a scope
statement to get green is the drift.**

## Why the matching works the way it does

Phase 165's first version of these guards matched **per physical line**, and its
own round defeated that with four ordinary authoring habits: a backslash
line-continuation, naming the flag before the script (*"pass `--force` so
`cleanup_worktrees.sh` drops the orphan"*), a shell variable, and a list step with
the command fenced and the flag explained in following prose. None is adversarial;
they are how people write shell instructions. So matching now runs over
**whitespace-collapsed file text with a proximity window**, which closes all four
except the distant-variable case.

The population was also wrong: it covered only `core/skills` and
`core/companion/docs`, while **`install.sh` already prescribes this script**
(twice, correctly, with `--clean`) and `README.md`, `docs/` and `packs/` all ship
to readers. A guard that excludes a file in the exact population it exists for is
not a guard. Both fixes came from the round, not from the author.

`core/companion/scripts/` stays excluded on purpose — a script documenting its own
flags is not a prescription — and so does `tests/`, which necessarily writes the
forbidden forms as fixtures.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"

SCRIPT_NAME = "cleanup_worktrees.sh"

# Markdown trees that ship to a reader, plus the two non-markdown files that
# already name this script. Excludes core/companion/scripts/ and tests/.
MD_ROOTS = ("core/skills", "core/companion/docs", "docs", "packs")
EXTRA_FILES = ("README.md", "install.sh")

# How far from the script name a `--force` token still counts as being about it.
# Wide enough to span a fenced command plus the sentence that introduces or
# follows it; narrow enough that two unrelated paragraphs do not bleed together.
WINDOW = 250

# The runnable form, on collapsed text so a line-continuation cannot split it.
# `bash` is OPTIONAL and the path prefix is arbitrary: WORKFLOW.md's own
# prescriptive house style omits `bash` (`sysop/scripts/cleanup_worktrees.sh
# --clean` at § 4 and § 5), so requiring it — as the first version of this guard
# did — left the repo's most idiomatic prescription shape unmatched. What marks a
# line as runnable rather than referential is the PATH: a `/` before the script
# name. The three correct descriptive sites all name the script bare, so this
# discriminates without touching them.
PRESCRIPTION = re.compile(
    r"(?:bash[\s\\]+)?[^\s`]*/cleanup_worktrees\.sh[\s\\]+--force"
)

# Ordinary ways to state that the mode is wholesale. Deliberately excludes the
# bare stem "surviv": it was in this set, and the round showed an incidental
# "survives if pushed upstream" on the same line as a wrongly-scoped prescription
# satisfied the guard and laundered the line as compliant. The two correct sites
# that leaned on it now state the scope outright instead.
SCOPE_MARKERS = (
    "no path operand",
    "wholesale",
    "every non-main",
    "all non-main",
)


def _targets():
    seen = []
    for root in MD_ROOTS:
        d = REPO_ROOT / root
        if d.is_dir():
            seen.extend(sorted(d.rglob("*.md")))
    for name in EXTRA_FILES:
        f = REPO_ROOT / name
        if f.is_file():
            seen.append(f)
    return seen


def _collapse(text):
    """Whitespace-collapsed text plus a collapsed-index -> original-index map."""
    out, offsets, prev_space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                offsets.append(i)
            prev_space = True
        else:
            out.append(ch)
            offsets.append(i)
            prev_space = False
    return "".join(out), offsets


def _force_windows():
    """(relpath, lineno, window) for every mention of the script whose window
    contains `--force`. The window is what a reader takes in around the mention:
    the proximity span **union the mention's whole physical line**. The union
    matters in both directions — the span alone is too narrow for a long
    WORKFLOW.md table row (a single logical unit that can run past it), and the
    line alone is what the first version of this module used, which four ordinary
    authoring habits walked straight through."""
    for path in _targets():
        text = path.read_text(encoding="utf-8")
        collapsed, offsets = _collapse(text)
        for m in re.finditer(re.escape(SCRIPT_NAME), collapsed):
            lo = max(0, m.start() - WINDOW)
            hi = min(len(collapsed), m.end() + WINDOW)
            orig = offsets[m.start()]
            line_start = text.rfind("\n", 0, orig) + 1
            line_end = text.find("\n", orig)
            line = text[line_start:] if line_end == -1 else text[line_start:line_end]
            window = collapsed[lo:hi] + "\n" + line
            if "--force" not in window:
                continue
            yield path.relative_to(REPO_ROOT), text.count("\n", 0, orig) + 1, window


def test_no_prescription_of_a_wholesale_wipe():
    """A document telling a reader to RUN `--force` is telling them to destroy work.

    Every legitimate single-worktree removal has an owner already:
    `git worktree remove <path>` (refuses on uncommitted or untracked changes), or
    `claim_task.sh --release <TASK_ID>` / `batch_work.sh --release <N>` when a lock
    and a status also need releasing. This script is neither.
    """
    hits = sorted(
        f"{p}:{n}" for p, n, w in _force_windows() if PRESCRIPTION.search(w)
    )
    assert not hits, (
        f"These sites give a runnable `cleanup_worktrees.sh --force` command: {hits}. "
        f"It takes no path operand, so it removes EVERY non-main worktree — one "
        f"failed claim destroys every concurrent claim's uncommitted work. For a "
        f"single worktree use `git worktree remove <path>`, or "
        f"`claim_task.sh --release <TASK_ID>` when a lock also needs releasing. "
        f"See WORKFLOW.md § 8.4."
    )


def test_every_force_mention_states_its_scope():
    """Mentioning `--force` without saying it is wholesale is how the belief spread.

    A proxy for "is this a prescription", not a test of it — see the module
    docstring on what this cannot catch.
    """
    bare = sorted(
        f"{p}:{n}"
        for p, n, w in _force_windows()
        if not any(m in w.lower() for m in SCOPE_MARKERS)
    )
    assert not bare, (
        f"These mentions of `cleanup_worktrees.sh --force` never say it acts on "
        f"ALL worktrees: {bare}. State it nearby — 'no path operand', "
        f"'wholesale', 'every non-main', or 'ALL non-main'. If you have a better "
        f"honest phrasing, add it to SCOPE_MARKERS; do not delete the scope "
        f"statement to get green."
    )


def test_the_matching_is_still_matching_something():
    """Both guards above pass vacuously if no `--force` mention remains anywhere.

    Without this, deleting the honest descriptions of the blast radius would look
    identical to fixing the problem — the same "silence reads as clean" failure
    the § 8.4 row itself embodied.
    """
    found = sorted({f"{p}:{n}" for p, n, _ in _force_windows()})
    assert found, (
        "No `cleanup_worktrees.sh --force` mention is reachable in any searched "
        "file. Either the flag was removed — in which case retire these guards "
        "deliberately — or the honest descriptions of its blast radius were "
        "deleted, which is the drift and not the fix."
    )


def test_the_searched_population_covers_the_known_prescription_sites():
    """`install.sh` prescribes this script twice; the first version of this module
    did not search it. Pin the population so a root file cannot drop out of it."""
    searched = {str(p.relative_to(REPO_ROOT)) for p in _targets()}
    for required in ("install.sh", "README.md"):
        assert required in searched, (
            f"{required} is no longer in the searched population, but it ships to "
            f"readers and install.sh already names cleanup_worktrees.sh. A guard "
            f"that excludes a file in the population it exists for is not a guard."
        )
    assert any(p.startswith("core/skills/") for p in searched)
    assert any(p.startswith("core/companion/docs/") for p in searched)


def _section_8_4():
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^### 8\.4 .*?$(.*?)^### 8\.5 ", text, re.M | re.S)
    assert match, (
        "WORKFLOW.md § 8.4 (the scripts table) could not be located — if the "
        "section was renumbered, update this guard rather than deleting it"
    )
    return match.group(1)


def _cleanup_row():
    for line in _section_8_4().splitlines():
        if line.startswith("| `cleanup_worktrees.sh"):
            return line
    raise AssertionError(
        "No `cleanup_worktrees.sh` row in WORKFLOW.md § 8.4 — "
        "tests/test_workflow_scripts_table.py should have caught this first"
    )


def test_workflow_8_4_row_states_the_real_scope():
    """The root cause. The row read `[--clean]` / "List or remove merged
    worktrees": `--force` absent, and "merged" the wrong premise three skill sites
    acted on. Each fact below is one the row did not carry.

    A reversion guard, not a semantics guard — see the module docstring.
    """
    row = _cleanup_row().lower()
    for claim, why in (
        ("--force", "the destructive mode was absent from the canonical table"),
        ("all non-main", "the row never stated the blast radius"),
        ("no path operand", "the row never said it cannot target one worktree"),
        ("git worktree remove", "the row never named the single-target alternative"),
        ("claim_task.sh --release", "the row never named the lock-aware inverse"),
        ("prune", "every mode mutates the worktree admin DB, including the listing one"),
        ("branch -d", "both removing modes also delete the removed worktree's branch"),
        ("fallthrough", "ACTIVE means 'may hold uncommitted work', not 'does' — "
                        "the row's first version taught the wrong inference"),
    ):
        assert claim in row, (
            f"WORKFLOW.md § 8.4's cleanup_worktrees.sh row no longer states "
            f"'{claim}' — {why}. This row is the canonical description of the "
            f"script; three skill sites prescribed a wholesale wipe as a "
            f"single-orphan rollback while it said only 'remove merged worktrees'."
        )
