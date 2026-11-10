"""`/claim-task` Step 8's auto-mode chain reads the UI-verify catalogue by row (upstream #350).

`_shared/ui-verify.md` § Step 7 is a four-row catalogue, and its rows are not equivalent:
two return cleanly (no frontend files, dev server not running) and two leave the check to a
human (all paths auth-gated or deferred, Playwright unavailable). Step 8 used to skip the
chain to `/document-work` "when a UI-verify note flags pending manual checking", a
paraphrase that read the clean dev-server skip as a pending manual check and could be read
the other way past a real *"Manual verification required before merging"*.

The rows are derived from the partial, not retyped: a row whose emitted text asks for a
manual check is one that must skip the chain, and every other row must be named as one that
does not. A fifth row added to the catalogue goes red here until Step 8 places it.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"
UI_VERIFY = REPO_ROOT / "core/skills/_shared/ui-verify.md"

_AUTOCHAIN = ("**Auto-mode chaining.**", "**On `STATUS: BLOCKED`**")
_EXECUTOR = ("**START OF EXECUTOR PROMPT**", "**END OF EXECUTOR PROMPT**")


def _flat(s: str) -> str:
    """Emphasis, ticks and whitespace runs carry no meaning for these checks."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", s)).strip().lower()


def _between(text: str, start: str, end: str) -> str:
    """Fails closed: `""` when either marker is missing."""
    a = text.find(start)
    if a < 0:
        return ""
    b = text.find(end, a + len(start))
    return text[a:b] if b >= 0 else ""


def catalogue(partial: str) -> list[tuple[str, str]]:
    """`(condition, emitted text)` for each row of § Step 7's table."""
    sec = _between(partial, "## Step 7:", "\n---")
    rows = []
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0] in ("Condition", "") or set(cells[0]) <= set("-: "):
            continue
        rows.append((cells[0], cells[1]))
    return rows


def _rows_by_kind(partial: str) -> tuple[list[str], list[str]]:
    manual, clean = [], []
    for cond, emitted in catalogue(partial):
        (manual if re.search(r"manual", emitted, re.I) else clean).append(cond)
    return manual, clean


def chain_problems(skill: str, partial: str) -> list[str]:
    section = _between(skill, *_AUTOCHAIN)
    if not section:
        return ["Step 8's auto-mode chaining paragraph did not resolve"]
    manual, clean = _rows_by_kind(partial)
    if not manual or not clean:
        return [f"the § Step 7 catalogue did not resolve into both kinds of row: "
                f"manual={manual!r} clean={clean!r}"]
    sentences = re.split(r"(?<=[.!?])\s+", _flat(section))
    skip = next((s for s in sentences if s.startswith("skip the chain when")), "")
    keep = next((s for s in sentences if "do not skip the chain" in s), "")
    p: list[str] = []
    if not skip:
        p.append("Step 8 no longer has a 'Skip the chain when' sentence")
    if "ui-verify.md § step 7" not in skip:
        p.append("Step 8's skip sentence no longer points at the ui-verify catalogue")
    for cond in manual:
        if _flat(cond) not in skip:
            p.append(f"Step 8's skip sentence does not name the {cond!r} row, which leaves "
                     "the check to a human")
    for cond in clean:
        if _flat(cond) in skip:
            p.append(f"Step 8's skip sentence names the clean {cond!r} row")
        if _flat(cond) not in keep:
            p.append(f"Step 8 does not say the clean {cond!r} row leaves the chain running")
    if re.search(r"manual checking|flags pending", _flat(section)):
        p.append("Step 8 still carries the catalogue paraphrase")
    return p


def executor_problems(skill: str) -> list[str]:
    """The executor surfaces every catalogue row's note, not only the dev-server one, or
    Step 8 has nothing to read for the two rows that skip the chain."""
    prompt = _flat(_between(skill, *_EXECUTOR))
    if not prompt:
        return ["the executor prompt did not resolve"]
    if "surface any note from that partial's § step 7 catalogue verbatim" not in prompt:
        return ["executor item 6 no longer surfaces every § Step 7 catalogue note verbatim"]
    return []


def relay_problems(skill: str) -> list[str]:
    """Step 8 prints the note to the human and says why the chain stopped on it.

    `_shared/ui-verify.md` § Step 7 requires the note in the parent skill's handoff. The
    sealed report Step 8 prints is the reviewer's, so without a relay of its own the note
    reached no one, and an auto-mode stop on it printed "Run /document-work next" with no
    reason.
    """
    p: list[str] = []
    step8 = _between(skill, "## Step 8: Receive the executor envelope", "### Step 8b")
    if not step8:
        return ["Step 8 did not resolve"]
    report = step8.find("## Claim complete:")
    relay = _flat(step8[:report]) if report >= 0 else ""
    if "then print the ui-verify note the executor quoted (step 7e item 6), verbatim" not in relay:
        p.append("Step 8 does not print the executor's UI-verify note before its report")
    chain = _flat(_between(skill, *_AUTOCHAIN))
    if not re.search(r"when the chain stops on either row that leaves the check to a human, "
                     r"say so under the report and name the row", chain):
        p.append("an auto-mode stop on a UI-verify row does not say why it stopped")
    return p


def test_step_8_relays_the_note_and_the_stop():
    assert relay_problems(SKILL.read_text(encoding="utf-8")) == []


def test_the_catalogue_has_both_kinds_of_row():
    manual, clean = _rows_by_kind(UI_VERIFY.read_text(encoding="utf-8"))
    assert len(manual) + len(clean) == len(catalogue(UI_VERIFY.read_text(encoding="utf-8")))
    assert manual and clean, (manual, clean)


def test_step_8_names_the_catalogue_rows():
    skill = SKILL.read_text(encoding="utf-8")
    assert chain_problems(skill, UI_VERIFY.read_text(encoding="utf-8")) == []


def test_the_executor_surfaces_every_catalogue_note():
    assert executor_problems(SKILL.read_text(encoding="utf-8")) == []


def test_the_guard_reds_on_the_old_paraphrase_and_on_a_moved_row():
    skill = SKILL.read_text(encoding="utf-8")
    partial = UI_VERIFY.read_text(encoding="utf-8")
    manual, clean = _rows_by_kind(partial)
    old = re.sub(r"when the executor's UI-verify note is .*?§ Step 7 \(the two rows that leave "
                 r"the check to a human\)", "when a UI-verify note flags pending manual checking",
                 skill, count=1)
    assert old != skill
    assert chain_problems(old, partial), "the pre-fix paraphrase passed"
    # A clean row moved into the skip list must red, as must a manual row dropped from it.
    moved = skill.replace("*Playwright MCP unavailable* row", f"*{clean[0]}* row", 1)
    assert moved != skill
    got = chain_problems(moved, partial)
    assert any("does not name the 'Playwright MCP unavailable' row" in g for g in got), got
    assert any(f"names the clean {clean[0]!r} row" in g for g in got), got
    # A catalogue row Step 8 does not place must red.
    grown = partial.replace(
        "| Playwright MCP unavailable |",
        "| Browser crashed | `UI verify: browser crashed. Verify manually.` |\n"
        "| Playwright MCP unavailable |", 1)
    assert grown != partial
    assert chain_problems(skill, grown)
    no_relay = re.sub(r"\*\*Then print the UI-verify note the executor quoted.*?\n", "", skill, count=1)
    assert no_relay != skill and relay_problems(no_relay)
    old_item = skill.replace("surface any note from that partial's § Step 7 catalogue verbatim",
                             "surface that note verbatim", 1)
    assert old_item != skill and executor_problems(old_item)
