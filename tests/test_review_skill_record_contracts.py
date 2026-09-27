"""The two review skills' round-record prose, tied to the code and the step it reports on.

Four places where `/codebase-review` and `/security-audit` told a literal executor to write
or react to something the code or a sibling step does not produce:

1. **Step 5b's `Reconciliation:` line** carried `/security-audit`'s three field names in
   `/codebase-review` (which has no categories), and three fields for `/security-audit`'s
   four Step 3-0b counts. The guard derives both sides from the skill itself: the rows of
   Step 3-0b's report template, and the fields of Step 5b's line with the sentence mapping
   one to the other.
2. **Step 2b's accounting paragraph** knew three of the pre-scan's five terminal states and
   one of its two warning markers. The guard renders a real `RunReport` with every state
   and reads the vocabulary off its output, so a new state or marker that
   `run_checks/accounting.py`'s renderer prints reddens this until both skills name it.
   (A status constant the renderer never prints changes no output, and passes.)
3. **Step 9b step 5** said to "fold into" Step 9's commit, which already exists, so the fold
   is an amend, and no seeded allow-rule matches an amend.
4. **`/security-audit` Step 3c** keyed its loud arm on `!= "verified"`, which also fires on
   the parser's `"none"`, which is every round with no report. The guard runs the parser
   over fixtures and reads the value set from its source.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

import ingest_security_report as ing
from run_checks.accounting import (
    DEGRADED,
    EXECUTED,
    FAILED,
    SKIPPED,
    UNROUTABLE,
    RunReport,
)

from _prose_guard_helpers import _fence_state

REPO = Path(__file__).resolve().parent.parent
SKILLS = {
    name: REPO / "core" / "skills" / name / "SKILL.md"
    for name in ("codebase-review", "security-audit")
}
SETTINGS = REPO / "core" / "companion" / ".claude" / "settings.json"
INSTALL = REPO / "install.sh"
INGEST = REPO / "core" / "companion" / "scripts" / "ingest_security_report.py"


def _text(skill: str) -> str:
    return SKILLS[skill].read_text(encoding="utf-8")


def _heading(text: str, prefix: str) -> str:
    """The one heading line starting with `prefix`, so a retitle does not break the slice."""
    hits = [ln for ln in text.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, f"expected one heading starting {prefix!r}, found {hits}"
    return hits[0]


def _slice(skill: str, prefix: str) -> str:
    """The body under the one heading starting with `prefix`, up to the next heading of
    the same or higher level outside a fence.

    Not `section()`: these guards slice two skills by heading PREFIX, and
    `tests/_section_call_sites.py` can only measure a call with a literal heading in one
    file. The fence rule still has one home: `_fence_state()`.
    """
    return _slice_text(_text(skill), prefix)


def _slice_text(text: str, prefix: str) -> str:
    head = _heading(text, prefix)
    level = len(head) - len(head.lstrip("#"))
    lines = text.splitlines()
    fenced = dict(_fence_state(lines))
    start = lines.index(head)
    assert not fenced[start], f"{prefix!r} is inside a fence"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        hashes = len(ln) - len(ln.lstrip("#"))
        if not fenced[i] and 1 <= hashes <= level and ln[hashes:hashes + 1] == " ":
            end = i
            break
    # An unterminated fence marks every later line fenced, so the slice would run to EOF:
    # fail-open, the same refusal `section()` makes.
    assert not (end == len(lines) and fenced[len(lines) - 1]), f"unterminated fence under {prefix!r}"
    return "\n".join(lines[start + 1:end])


@pytest.mark.parametrize("text,want", [
    ("## A\nx\n## B\ny\n", "x"),
    ("## A\nx\n### sub\nz\n## B\ny\n", "x\n### sub\nz"),
    ("## A\nx\n```bash\n# a comment, not a heading\n```\nw\n## B\n", "x\n```bash\n# a comment, not a heading\n```\nw"),
    ("## A\nx\n~~~\n## fenced\n~~~\nw\n# Top\n", "x\n~~~\n## fenced\n~~~\nw"),
])
def test_the_slicer_ends_at_the_next_unfenced_heading(text: str, want: str) -> None:
    assert _slice_text(text, "## A") == want


def test_the_slicer_refuses_an_unterminated_fence() -> None:
    with pytest.raises(AssertionError, match="unterminated fence"):
        _slice_text("## A\nx\n```\n## B\n", "## A")


def _paragraph(body: str, start: str) -> str:
    """From `start` to the next blank line: one markdown paragraph, not the whole section."""
    i = body.index(start)
    j = body.find("\n\n", i)
    return body[i: j if j != -1 else len(body)]


def _line(body: str, start: str) -> str:
    """The one line starting with `start`: a list item, not the list it sits in."""
    hits = [ln for ln in body.splitlines() if ln.startswith(start)]
    assert len(hits) == 1, f"expected one line starting {start!r}, found {len(hits)}"
    return hits[0]


# ── 1. Step 5b `Reconciliation:` ↔ Step 3-0b's report rows ─────────────────────────────

def _reconciliation_rows(skill: str) -> list[str]:
    body = _slice(skill, "### 3-0b.")
    fences = re.findall(r"```[^\n]*\n(.*?)```", body, re.S)
    tmpl = [f for f in fences if f.startswith("Assignment reconciliation:")]
    assert len(tmpl) == 1, f"{skill}: expected one 3-0b report template, found {len(tmpl)}"
    rows = [ln.split(":")[0].strip() for ln in tmpl[0].splitlines()[1:] if "<N>" in ln]
    assert rows, f"{skill}: the 3-0b template has no count rows"
    return rows


def _reconciliation_fields(skill: str) -> list[str]:
    body = _slice(skill, "### 5b.")
    lines = [ln for ln in body.splitlines() if ln.startswith("> **Reconciliation:**")]
    assert len(lines) == 1, f"{skill}: expected one Reconciliation template line, found {len(lines)}"
    return re.findall(r"([a-z][a-z-]*) <N>", lines[0])


def _field_map(skill: str) -> list[tuple[str, str]]:
    body = _slice(skill, "### 5b.")
    para = _paragraph(body, "Fill each ")
    return re.findall(r"`([a-z][a-z-]*)` = \*([^*]+)\*", para)


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_every_reconciliation_field_maps_to_a_3_0b_row_in_order(skill):
    rows = _reconciliation_rows(skill)
    fields = _reconciliation_fields(skill)
    mapping = _field_map(skill)
    assert [f for f, _ in mapping] == fields, (
        f"{skill}: Step 5b's Reconciliation fields {fields} are not the fields its mapping "
        f"sentence defines {[f for f, _ in mapping]}"
    )
    assert [r for _, r in mapping] == rows, (
        f"{skill}: Step 5b maps its fields to {[r for _, r in mapping]}, but Step 3-0b "
        f"reports {rows}. A count with no slot is dropped, and a slot with no count is "
        f"filled with a number that does not mean what its label says."
    )


def test_codebase_review_reconciliation_carries_no_category_field():
    fields = _reconciliation_fields("codebase-review")
    assert not [f for f in fields if "categor" in f], (
        f"/codebase-review has no OWASP categories, but its Reconciliation line asks for {fields}"
    )


# ── 2. Step 2b's accounting paragraph ↔ what `RunReport.render` prints ─────────────────

def _terminal_states() -> list[str]:
    """Every module-level status constant in `accounting.py`, read from its source, so a
    sixth state is rendered here the day it is added rather than when this list is edited."""
    src = (REPO / "core" / "companion" / "scripts" / "run_checks" / "accounting.py").read_text()
    out = [n.value.value for n in ast.parse(src).body
           if isinstance(n, ast.Assign) and len(n.targets) == 1
           and isinstance(n.targets[0], ast.Name) and n.targets[0].id.isupper()
           and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
    assert {EXECUTED, SKIPPED, FAILED, DEGRADED, UNROUTABLE} <= set(out), out
    return out


def _render_every_state() -> tuple[str, str]:
    """(full render with every state, header of an all-executed render). The last check
    is left unrecorded, which is how `unaccounted` is produced."""
    states = _terminal_states()
    ids = [f"c-{s}" for s in states] + ["c-none"]
    checks = [{"id": i, "blocking": True, "paths": ["src/"]} for i in ids]
    rep = RunReport(checks)
    for cid, st in zip(ids, states):
        rep.record([cid], st, "grep", reason="r", detail="d")
    full = rep.render([], mode="both")

    clean = RunReport(checks[:1])
    clean.record([checks[0]["id"]], EXECUTED, "grep")
    return full, clean.render([], mode="both").splitlines()[0]


def _count_words(header: str) -> list[str]:
    counts = header.split("checks:", 1)[1].split(" selected", 1)[0]
    return re.findall(r"\d+ ([a-z]+)", counts)


def _accounting_paragraph(skill: str) -> str:
    body = _slice(skill, "## Step 2b:")
    return _paragraph(body, "**Read the pre-scan accounting block")


def test_the_render_fixture_reaches_every_state():
    full, _ = _render_every_state()
    words = _count_words(full.splitlines()[0])
    assert set(words) >= {"executed", "skipped", "failed", "degraded", "unroutable",
                          "unaccounted"}, words
    assert "⚠ BLOCKING CHECK RAN INCOMPLETE" in full and "⚠ BLOCKING CHECK DID NOT RUN" in full


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_the_accounting_paragraph_names_every_marker_the_runner_prints(skill):
    full, _ = _render_every_state()
    para = _accounting_paragraph(skill)
    for marker in sorted(set(re.findall(r"⚠ [A-Z][A-Z ]+[A-Z]", full))):
        assert f"`{marker}`" in para, f"{skill}: Step 2b never names `{marker}`"


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_the_accounting_paragraph_carries_every_non_skip_detail_line(skill):
    full, _ = _render_every_state()
    para = _accounting_paragraph(skill)
    prefixes = {m for m in re.findall(r"^    ([a-z]+):", full, re.M)}
    assert prefixes >= {"failed", "degraded", "unroutable", "unaccounted"}, prefixes
    # Skipped lines may be compressed across rounds; every other one is carried verbatim.
    for p in sorted(prefixes - {"skipped"}):
        assert f"`{p}:`" in para, f"{skill}: Step 2b does not carry `{p}:` lines"


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_every_conditional_count_is_named_where_the_count_is_read(skill):
    """A count the header prints only when non-zero is exactly the one an executor
    reading an E/S/F template drops. Both Step 2b and Step 6 must name each one."""
    full, clean_header = _render_every_state()
    conditional = [w for w in _count_words(full.splitlines()[0])
                   if w not in _count_words(clean_header)]
    # The clean render must carry none of them, or the difference above undercounts
    # (round 2: a stale fixture id left the clean check unrecorded, so `unaccounted`
    # sat in both headers and dropped out of this guard).
    assert _count_words(clean_header) == ["executed", "skipped", "failed"], clean_header
    assert {"degraded", "unroutable", "unaccounted"} <= set(conditional), conditional
    para = _accounting_paragraph(skill)
    summary = _slice(skill, "## Step 6:")
    prescan = [ln for ln in summary.splitlines() if ln.startswith("Pre-scan")]
    assert len(prescan) == 1, f"{skill}: expected one Pre-scan line in Step 6, found {prescan}"
    for w in conditional:
        assert re.search(rf"` / [A-Z] {w}`", para), (
            f"{skill}: Step 2b does not say the header gains ` / <n> {w}`"
        )
        assert re.search(rf"\b{w}\b", prescan[0]), (
            f"{skill}: Step 6's Pre-scan line has no slot for the `{w}` count"
        )


# ── 3. Step 9b's commit ↔ the seeded allow-rules ───────────────────────────────────────

def _loop_allow() -> set[str]:
    src = INSTALL.read_text(encoding="utf-8")
    m = re.search(r"^LOOP_ALLOW = \{.*?^\}", src, re.S | re.M)
    assert m, "install.sh no longer defines LOOP_ALLOW as a set literal"
    tree = ast.parse(m.group(0))
    try:
        return set(ast.literal_eval(tree.body[0].value))
    except ValueError as exc:
        raise AssertionError(
            f"install.sh's LOOP_ALLOW is no longer a plain literal set ({exc}); this reader "
            "evaluates it as Python, the way the installer's own heredoc uses it") from None


def _full_allow() -> set[str]:
    return set(json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"])


def _commit_rules(rules: set[str]) -> list[str]:
    return [r for r in rules if r.startswith("Bash(git commit")]


@pytest.mark.parametrize("mode", ["full", "loop"])
def test_no_seeded_rule_matches_an_amend(mode):
    rules = _full_allow() if mode == "full" else _loop_allow()
    commit = _commit_rules(rules)
    assert commit, f"{mode}: no git commit rule is seeded at all"
    assert not [r for r in commit if "amend" in r], (
        f"{mode} now seeds an amend rule {commit}; Step 9b's reason for a separate commit "
        f"(no seeded rule matches `git commit --amend`) is false, so revisit it"
    )


def _commit_prefix(rule: str) -> str:
    return rule[len("Bash("):].rsplit(":*)", 1)[0]


@pytest.mark.parametrize("skill", sorted(SKILLS))
@pytest.mark.parametrize("mode", ["full", "loop"])
def test_step_9b_commits_with_a_command_a_seeded_rule_names(skill, mode):
    body = _slice(skill, "## Step 9b:")
    fences = re.findall(r"```bash\n(.*?)```", body, re.S)
    commits = [ln.strip() for f in fences for ln in f.splitlines()
               if ln.strip().startswith("git commit")]
    assert len(commits) == 1, f"{skill}: expected one git commit in Step 9b, found {commits}"
    assert "--amend" not in commits[0]
    rules = _full_allow() if mode == "full" else _loop_allow()
    # Whether the permission matcher compares a command with its shell quotes is not
    # documented (open queue entry Q-079). The prescribed command opens its message with
    # `"docs:`, exactly as Step 9's does, so compare with the quote removed: this asserts
    # both commits bind the same rule or neither does, not that either one binds.
    unquoted = commits[0].replace('"', "")
    assert any(unquoted.startswith(_commit_prefix(r)) for r in _commit_rules(rules)), (
        f"{skill}/{mode}: Step 9b commits with {commits[0]!r}, which no seeded rule names"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_step_9b_does_not_fold_into_step_9s_commit(skill):
    text = _text(skill)
    assert text.index(_heading(text, "## Step 9:")) < text.index(_heading(text, "## Step 9b:")), (
        f"{skill}: Step 9 no longer runs before Step 9b, so revisit the commit wording"
    )
    body = _slice(skill, "## Step 9b:")
    step5 = _paragraph(body, "5. **Commit**")
    assert not re.search(r"\bfold", step5, re.I), (
        f"{skill}: Step 9b step 5 folds into Step 9's commit again: that commit already "
        f"exists, so folding is an amend"
    )
    assert "**their own commit**" in step5


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_a_keep_only_round_still_commits_its_ledger_edit(skill):
    """Step 3 deletes a `keep` rule's ledger rows from review_tasks.md, so a skip rule
    keyed only to retire/demote/tighten leaves that edit uncommitted."""
    body = _slice(skill, "## Step 9b:")
    step4 = _paragraph(body, "4. **Emit demotion summary**")
    skip = [s for s in re.split(r"(?<=[.;])\s+", step4) if "skip the commit" in s]
    assert len(skip) == 1, skip
    assert "only when Step 9b changed no file" in skip[0], skip[0]


# ── 4. `/security-audit` Step 3c ↔ the values `trust.status` can take ─────────────────

def _status_values_in_source() -> set[str]:
    """Every string literal assigned to the aggregate `trust.status`."""
    tree = ast.parse(INGEST.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "overall_status" for t in node.targets
        ):
            values |= {c.value for c in ast.walk(node.value)
                       if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if "trust" in keys:
                inner = node.values[keys.index("trust")]
                if isinstance(inner, ast.Dict):
                    for k, v in zip(inner.keys, inner.values):
                        if (isinstance(k, ast.Constant) and k.value == "status"
                                and isinstance(v, ast.Constant)):
                            values.add(v.value)
    return values


def _report(root: Path, name: str, *, jsonl: bool = True, status: str | None = None) -> None:
    d = root / name
    d.mkdir()
    if jsonl:
        (d / ing.RESULTS_JSONL).write_text("", encoding="utf-8")
    if status is not None:
        (d / "CLAUDE-SECURITY-REVISION-1.json").write_text(
            json.dumps({"verification": {"status": status}, "revision": {}}), encoding="utf-8")


def _observed_statuses(tmp_path: Path) -> dict[str, str]:
    cases = {}
    empty = tmp_path / "empty"
    empty.mkdir()
    cases["no report"] = ing.ingest(empty, None, False)["trust"]["status"]
    for label, kw in (("verified stamp", {"status": "verified"}),
                      ("non-verified stamp", {"status": "partial"}),
                      ("no stamp", {}),
                      ("skipped report", {"jsonl": False})):
        root = tmp_path / label.replace(" ", "-")
        root.mkdir()
        _report(root, "CLAUDE-SECURITY-20260101-000000", **kw)
        cases[label] = ing.ingest(root, None, False)["trust"]["status"]
    return cases


def test_the_parser_produces_exactly_the_values_its_source_names(tmp_path):
    observed = _observed_statuses(tmp_path)
    assert observed == {"no report": "none", "verified stamp": "verified",
                        "non-verified stamp": "unverified", "no stamp": "unverified",
                        "skipped report": "none"}, observed
    assert set(observed.values()) == _status_values_in_source()


def test_step_3c_gives_every_trust_status_its_own_arm():
    values = _status_values_in_source()
    assert values == {"verified", "unverified", "none"}, values
    body = _slice("security-audit", "## Step 3c:")
    for v in sorted(values):
        assert re.search(rf"\*\*`\"{v}\"` → ", body), f"Step 3c has no arm for `{v}`"
    assert not re.search(r"trust\.status\s*!=", body), (
        "Step 3c keys an arm on `!=`, which also catches `none`, the status of a round "
        "with no report"
    )
    def arm(value: str) -> str:
        # Any list marker: `-`, `*` and `+` render the same bullet.
        hits = [ln for ln in body.splitlines()
                if re.match(rf'\s*[-*+] \*\*`"{value}"` → ', ln)]
        assert len(hits) == 1, f"expected one `{value}` arm, found {hits}"
        return hits[0]
    assert "trust.reasons" in arm("unverified") and "loudly" in arm("unverified")
    assert "no trust block" in arm("none")


def test_step_6_names_the_none_status_rather_than_a_state_of_the_disk():
    summary = _slice("security-audit", "## Step 6:")
    line = [ln for ln in summary.splitlines() if ln.startswith("Ingested (claude-security):")]
    assert len(line) == 1, line
    assert "`none`" in line[0] and "none on disk" not in line[0], line[0]


# ── 5. Integrator siblings: WORKFLOW.md's accounting states, Step 9's write steps ──────

WORKFLOW = REPO / "core" / "companion" / "docs" / "WORKFLOW.md"
_NUMBER_WORDS = {3: "three", 4: "four", 5: "five", 6: "six"}


def _workflow_accounting() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("**Execution accounting (the summary block).**")
    return text[start:text.index("\n```", start)]


def test_workflow_names_every_terminal_state_the_runner_records():
    """Every status `render()` can emit a detail line for, plus `executed`, is a bullet
    in WORKFLOW.md's accounting paragraph, and the stated count matches."""
    full, _ = _render_every_state()
    states = {"executed"} | {m for m in re.findall(r"^    ([a-z]+):", full, re.M)} - {"unaccounted"}
    assert states == {"executed", "skipped", "failed", "degraded", "unroutable"}, states
    para = _workflow_accounting()
    bullets = set(re.findall(r"^- \*\*`([a-z]+)", para, re.M))
    assert bullets == states, f"WORKFLOW.md's bullets {sorted(bullets)} != runner {sorted(states)}"
    assert f"exactly one of {_NUMBER_WORDS[len(states)]} states" in para


def test_workflow_says_the_conditional_counts_break_the_e_s_f_sum():
    para = _workflow_accounting()
    for w in ("degraded", "unroutable", "unaccounted"):
        assert f"`{w}`" in para.split("The stderr summary reports", 1)[1], w


def _step9_option(skill: str, lead: str) -> str:
    """One Step 9 option bullet. `lead` carries no list marker: `-`, `*` and `+` render
    the same bullet, and a marker swap is not an edit this guard is about."""
    body = _slice(skill, "## Step 9:")
    i = body.index(lead)
    m = re.compile(r"\n\s*[-*+] \*\*\(").search(body, i + 1)
    return body[i: m.start() if m else len(body)]


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_step_9_semgrep_promotion_writes_the_registry_entry(skill):
    """The pre-scan drops every finding of a semgrep rule with no `semgrep-<id>` entry
    (`run_checks/semgrep.py`), so a promotion that writes only the rule is dead."""
    src = (REPO / "core" / "companion" / "scripts" / "run_checks" / "semgrep.py").read_text()
    assert 'check_id = f"semgrep-{rule_id}"' in src and "if check_id not in paths_by_id:" in src
    opt = _step9_option(skill, "**(ii) `.claude/semgrep/*.yaml` AST rule**")
    assert "`semgrep-<id>` entry to `.claude/checks.yml`" in opt, opt[-600:]
    assert "`.claude/checks.project.yml`" in opt and "Either way" in opt


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_every_hook_letter_write_says_to_re_arm(skill):
    """Git runs the armed copy (`install.sh` arms with `cp`), so a letter added, deleted
    or moved in `sysop/scripts/hooks/pre-commit` does nothing until re-armed. The skill
    tells the human; it never names the arm script (`test_hook_autoarm_drift.py`)."""
    assert re.search(r'cp "\$f" "\$hook_dst/\$base"', INSTALL.read_text())
    rearm = ("the human re-arms the hooks from the main checkout (WORKFLOW.md § 4.3; a loop install "
             "ships no WORKFLOW.md, so point at https://github.com/getsysop/sysop/blob/main/docs/loop-mode.md#where-enforcement-lives)")
    opt = _step9_option(skill, "**(iii) `sysop/scripts/hooks/pre-commit` regex**")
    assert rearm in _line(opt.replace("         3.", "3.", 1), "3. On approval:")
    ninb = _slice(skill, "## Step 9b:")
    assert rearm in _line(ninb, "      - `pre-commit`: delete")
    assert rearm in _line(ninb, "   - **demote-to-advisory**")
    assert "has no consumer-side suppression" not in ninb
