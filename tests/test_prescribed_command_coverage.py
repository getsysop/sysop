"""Leg B of Phase 184 — a shipped instruction must have a rule that covers it.

THE DEFECT. `WORKFLOW.md` § 8.2a's venv carve-out named five scripts and said
bare `python3 sysop/scripts/<script>.py` "is what the shipped
`.claude/settings.json` allow-rules" — a sentence that both ended mid-clause and
was false: `backfill_completed_dates.py` had no rule in any shape, so a consumer
following the documented recipe hit a permission prompt. Nothing checked it,
because the doc's claim and the JSON's contents had no mechanical relationship.

WHY THE FILED INVARIANT WAS NOT ENOUGH, which is the finding worth keeping. The
item as filed proposed exactly one check: the doc enumerates its own subjects,
so derive the list from the doc and look each up in the JSON. That is Invariant
1 below and it is genuinely decidable — but a sweep of the tree found it reaches
**one** of the four live cases. The other three are not doc-enumerated at all:

* `bash sysop/scripts/self_check.sh` — prescribed by the installer's own
  post-install footer in BOTH modes and by `docs/getting-started.md`, with zero
  rules of any shape anywhere. The first thing a fresh install tells a consumer
  to run was also the first prompt it hit.
* `bash sysop/scripts/cleanup_worktrees.sh --clean` — prescribed by `/sitrep`
  and `WORKFLOW.md` § 4, zero rules.
* `... | tee /tmp/close-batch.log` in `/review-close` — `|` is a documented
  separator, so the tail is its own invocation; `tee` is in no read-only set and
  binds no rule, and the prompt arrives *after* the close has run.

So Invariant 2 is the one that reaches the class: **every command a shipped file
prescribes inside a fenced code block must be covered by a shipped rule.** A fence
is the unambiguous half of "prescribes" — descriptive prose naming a script
("`cleanup_worktrees.sh --clean` removes merged worktrees") is deliberately out
of scope, because folding it in makes the guard argue about intent. That
boundary is a stated limit, not an oversight: see WHAT THIS CANNOT DO.

MATCHER SEMANTICS are the ones `tests/test_permission_surface_drift.py` records
from the 2026-07-26 `claude-code-guide` probe: rules match the literal text sent
before shell expansion, and a trailing `:*` is a wildcard with a word boundary,
so `Bash(bash x.sh:*)` covers `bash x.sh --flag` while `Bash(bash x.sh)` alone
matches only the bare form.

WHAT THIS CANNOT DO.

* **It reads fenced code blocks only** — any fence, with or without an info string
  (the round found a live bare-fence miss). An imperative sentence outside a fence
  ("run `sysop/scripts/foo.sh`") is invisible here. Four such sites exist in
  `WORKFLOW.md` § 4 written without the `bash ` command word; they are recorded
  in the review queue rather than guarded, because separating an imperative from
  a description mechanically is the judgement this guard declines to make.
* **It checks the command word and script path, not the whole line.** A pipe
  tail, an assignment prefix or a `for … done` wrapper each defeat an otherwise
  correct rule; `WORKFLOW.md` § 8.2a *Invocation shapes* carries that list, and
  Invariant 3 pins only the one shape this phase removed.
* **Loop mode is checked by script, not by skill.** If loop mode ships the
  script and any shipped file prescribes it, `LOOP_ALLOW` must cover it. That
  over-approximates: a loop-shipped script prescribed only by a lifecycle-only
  skill would fail here wrongly. No such case exists today; if one appears, the
  fix is to narrow this to the loop-shipped doc set, not to delete the check.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "core/companion/.claude/settings.json"
INSTALLER = REPO_ROOT / "install.sh"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"

# Shipped files a consumer reads and acts on. `core/skills` and the companion
# docs install directly; `docs/` is the public site, and its quickstart is where
# the self_check.sh defect was reachable from.
PRESCRIBING_GLOBS = (
    "core/skills/**/*.md",
    "core/companion/docs/**/*.md",
    "docs/**/*.md",
    # Round finding H3: the installer's own post-install footer prescribes
    # `self_check.sh` in BOTH modes and was outside this set — the module's
    # docstring said so while the code did not read the file. `self_check.sh`
    # was caught only because `docs/getting-started.md` happens to fence it.
    "install.sh",
    "README.md",
    "packs/**/*.md",
    "core/companion/tasks/*.md",
)

# ANY fence, with or without an info string. Round finding H1: the first
# version required exactly ```bash/sh/shell with nothing after it, and
# `auto-build/SKILL.md:851` prescribes `claim_task.sh --release` inside a BARE
# fence — live, shipped, and invisible. ```console and ```bash title="..." were
# invisible too. This is the same "where it looks" class as the indented-command
# miss the author-side pass had just closed, one variable over, which is the
# argument for the round rather than for a bigger battery.
#
# Widening to any fence risks matching a `sysop/scripts/...` path inside a
# ```json or ```text block. Measured on the shipped tree it adds 11 sites and 3
# command-word pairs, all of them real prescriptions; the INVOCATION pattern
# still requires a command position, so a bare path in prose does not match.
FENCE_ANY = re.compile(r"^\s*```")

# `<word> sysop/scripts/<name>`, at a command position: line start (INDENTATION
# ALLOWED), or after a separator the matcher itself treats as starting a new
# command.
#
# The leading `\s*` is not cosmetic. Without it the first draft anchored on a
# bare `^` and silently missed every indented command — five in the shipped
# tree, inside numbered-list fences, including the very `close_batch.sh` line
# whose `| tee` tail this phase removed. All five happen to have rules today, so
# nothing was live; the population was simply short by five and nothing said so.
# Found by the author-side battery, which is the "where it looks" mutation
# class: derive the population from the source of truth, not from the shape you
# assumed it had.
# LOW round findings: `if bash …; then`, `sudo bash …` and a quoted
# `bash "sysop/scripts/x.py"` all escaped. The keyword arm and the optional
# quote close those; `&&`/`||` were already covered by the separator class.
INVOCATION = re.compile(
    r"(?:^\s*|[;|&(]\s*|\b(?:if|then|else|do|sudo|time|exec|env)\s+)"
    r"((?:bash|sh|python3?|\.venv/bin/python3)\s+)?"
    r"[\"']?"
    r"(sysop/scripts/[A-Za-z0-9_./-]+)"
)


def _template_rules():
    return set(json.loads(TEMPLATE.read_text(encoding="utf-8"))["permissions"]["allow"])


def _loop_allow():
    """Parse `LOOP_ALLOW = { ... }` out of install.sh.

    Derived from the installer, not restated here — a second copy of the set is
    the drift this whole module exists to catch, one layer up.
    """
    text = INSTALLER.read_text(encoding="utf-8")
    m = re.search(r"^LOOP_ALLOW = \{(.*?)^\}", text, re.S | re.M)
    assert m, "LOOP_ALLOW is no longer a `LOOP_ALLOW = { ... }` block in install.sh"
    return set(re.findall(r'"(Bash\([^"]*\))"', m.group(1)))


def _loop_excluded_scripts():
    text = INSTALLER.read_text(encoding="utf-8")
    m = re.search(r'^LOOP_EXCLUDE_SCRIPTS="([^"]*)"', text, re.M)
    assert m, "LOOP_EXCLUDE_SCRIPTS is no longer a quoted string in install.sh"
    return set(m.group(1).split())


def _prescribing_files():
    seen, out = set(), []
    for glob in PRESCRIBING_GLOBS:
        for path in sorted(REPO_ROOT.glob(glob)):
            if path.is_file() and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _fenced_lines():
    """Yield (rel, lineno, line) for every line inside a fence, in every file.

    ONE fence walk, used by both Invariant 2 and Invariant 3. Round finding H2:
    they each had their own copy, so opening the matcher in one would have left
    the other blind — the six-readers-one-writer shape this repo has paid for
    before.
    """
    for path in _prescribing_files():
        in_fence = False
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if FENCE_ANY.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                yield str(rel), lineno, line


# A `"Bash(bash sysop/scripts/x.sh:*)",` line inside a fenced settings.json
# example is a RULE DECLARATION, not a command. Widening the fence matcher to
# any fence pulled ten of them in from WORKFLOW.md's permission example — they
# passed by luck (the path regex stops at the `:`), but they inflated the
# population and would have failed the moment the doc illustrated a rule for a
# script the template does not seed. Found by measuring the round's own fix.
RULE_DECLARATION = re.compile(r'"Bash\(')


def _fenced_invocations():
    """(command_word, script_path) -> ["rel:line", ...] for every fenced command."""
    found = {}
    for rel, lineno, line in _fenced_lines():
        if RULE_DECLARATION.search(line):
            continue
        for m in INVOCATION.finditer(line):
            found.setdefault(((m.group(1) or "").strip(), m.group(2)), []).append(
                f"{rel}:{lineno}"
            )
    return found


def _covering_rules(word, script):
    head = f"{word} {script}" if word else script
    return (f"Bash({head})", f"Bash({head}:*)")


def _is_covered(word, script, rules):
    return any(r in rules for r in _covering_rules(word, script))


def test_fenced_invocations_were_actually_found():
    """Vacuity control. An empty population makes every check below pass.

    Named scripts rather than a bare count: a fence-parser that silently stops
    at the first closing ``` still yields a plausible-looking number.
    """
    found = _fenced_invocations()
    assert len(found) >= 10, (
        f"only {len(found)} fenced sysop/scripts invocations found; the fence "
        "parser has collapsed and this module is now vacuous"
    )
    scripts = {script for _, script in found}
    for expected in (
        "sysop/scripts/run_checks.sh",
        "sysop/scripts/claim_task.sh",
        "sysop/scripts/self_check.sh",
        "sysop/scripts/validate_tasks.py",
    ):
        assert expected in scripts, (
            f"{expected} is prescribed in a fenced code block in the shipped tree "
            "but this module no longer sees it — the parser or the file globs "
            "have narrowed past what they declare"
        )


def test_indented_fenced_commands_are_seen():
    """The blind spot the author-side battery found, pinned.

    Numbered-list steps indent their fences. A `^`-anchored pattern misses every
    one of them and reports a plausible population, which is worse than an empty
    one — it looks like coverage.
    """
    for line in (
        "   bash sysop/scripts/close_batch.sh <N1>",
        "  python3 sysop/scripts/validate_tasks.py",
        "        bash sysop/scripts/claim_task.sh --release <TASK_ID>",
    ):
        assert INVOCATION.search(line), (
            f"an indented fenced command is invisible to the sweep: {line!r}. "
            "The scan set is short by every list-nested step in the tree."
        )
    # Assert on SHAPE, not on a line number. The first version pinned
    # `review-close/SKILL.md:930` and reddened — with a false message — when an
    # unrelated edit shifted the file. A stale line pin, inside the phase whose
    # Leg C exists because line pins go stale.
    indented = [
        (rel, lineno)
        for rel, lineno, line in _fenced_lines()
        if line[:1] in " \t"
        and not RULE_DECLARATION.search(line)
        and INVOCATION.search(line)
    ]
    assert indented, (
        "no indented fenced command is in the swept population; the shipped "
        "tree has several, so the sweep has narrowed back to line-start only"
    )


def test_a_wordless_rule_form_does_not_count_as_coverage():
    """LOW round finding: adding a bare `Bash(<script>:*)` form survived.

    Per the recorded matcher semantics a rule matches the literal text sent, so
    `Bash(sysop/scripts/x.py:*)` binds nothing a skill actually writes — but it
    would satisfy a widened `_covering_rules` and mark the command compliant.
    """
    forms = _covering_rules("python3", "sysop/scripts/validate_tasks.py")
    assert all("python3 " in f for f in forms), (
        f"_covering_rules now accepts a form with no command word: {forms}. "
        "That rule shape matches no invocation any shipped file prescribes."
    )


def test_each_prescribing_glob_contributes_files():
    """LOW round finding: dropping a glob left the sweep plausible but short."""
    from collections import Counter
    files = [str(p.relative_to(REPO_ROOT)) for p in _prescribing_files()]
    for needle in (
        "core/skills/review-close/SKILL.md",
        "core/companion/docs/WORKFLOW.md",
        "docs/getting-started.md",
        "docs/analysis/REPORT.md",
        "core/companion/tasks/README.md",
        "install.sh",
        "README.md",
    ):
        assert needle in files, (
            f"{needle} is no longer in the prescribing set; a PRESCRIBING_GLOBS "
            "entry has been dropped and the sweep is short without saying so"
        )


def test_every_fence_language_is_swept():
    """Round finding H1, pinned: bare and info-string fences must be read.

    `auto-build/SKILL.md:851` prescribes a command inside a BARE fence and was
    invisible; ```console and ```bash title="..." were too.
    """
    for opener in ("```", "```console", '```bash title="recovery"', "   ```bash"):
        assert FENCE_ANY.match(opener), (
            f"the fence matcher no longer opens on {opener!r}; a shipped "
            "prescription inside that fence is invisible to the whole module"
        )
    seen = {rel for sites in _fenced_invocations().values() for rel in sites}
    assert any(s.startswith("core/skills/auto-build/SKILL.md") for s in seen), (
        "auto-build/SKILL.md's bare-fence prescription is no longer swept — "
        "the fence matcher has narrowed back to ```bash-only"
    )


def test_a_command_word_without_a_rule_is_not_covered():
    """Kills the 'any rule mentioning the script counts' weakening.

    Rules bind the literal text sent, so `python` and `python3` are different
    matches even for the same script. A substring check over the rule set marks
    an unrunnable command compliant — worse than a gap, because it is confident.
    """
    rules = _template_rules()
    assert _is_covered("python3", "sysop/scripts/validate_tasks.py", rules), (
        "the control's own premise is broken: validate_tasks.py has no bare "
        "python3 rule, so the negative half below proves nothing"
    )
    assert not _is_covered("perl", "sysop/scripts/validate_tasks.py", rules), (
        "`perl sysop/scripts/validate_tasks.py` is reported as covered. The "
        "coverage check has been weakened to a substring match over the rule "
        "set, which marks every command word compliant once any rule names the "
        "script."
    )
    assert not _is_covered("bash", "sysop/scripts/review_index.py", rules), (
        "a script with no rule at all is reported as covered"
    )


def test_every_fenced_invocation_has_a_covering_rule():
    """Invariant 2 — the one that reaches the class."""
    rules = _template_rules()
    missing = [
        (word, script, sites)
        for (word, script), sites in sorted(_fenced_invocations().items())
        if not _is_covered(word, script, rules)
    ]
    assert not missing, (
        "shipped files prescribe these commands in a fenced code block and the "
        "shipped .claude/settings.json covers none of them, so a consumer "
        "following the instruction hits a permission prompt:\n"
        + "\n".join(
            f"  `{w} {s}`  needs one of {_covering_rules(w, s)}\n"
            f"      prescribed at: {', '.join(sites[:4])}"
            for w, s, sites in missing
        )
    )


def test_loop_mode_covers_the_scripts_it_ships():
    """A loop-mode install seeds only LOOP_ALLOW — 21 rules, not the full 71.

    `self_check.sh` ships in loop mode and the installer's footer prescribes it
    there; until Phase 184 LOOP_ALLOW did not carry it.
    """
    loop_rules = _loop_allow()
    excluded = _loop_excluded_scripts()
    missing = []
    for (word, script), sites in sorted(_fenced_invocations().items()):
        if Path(script).name in excluded:
            continue
        if not _is_covered(word, script, loop_rules):
            missing.append((word, script, sites))
    assert not missing, (
        "loop mode ships these scripts and shipped files prescribe them, but "
        "install.sh's LOOP_ALLOW does not cover them — a loop-mode consumer "
        "gets a prompt where a full-mode one does not:\n"
        + "\n".join(
            f"  `{w} {s}`  needs one of {_covering_rules(w, s)}\n"
            f"      prescribed at: {', '.join(sites[:4])}"
            for w, s, sites in missing
        )
    )


# --------------------------------------------------------------------------
# Invariant 1 — the doc enumerates its own subjects, so check it against the JSON.
# --------------------------------------------------------------------------

CARVE_OUT_ANCHOR = "Never give a `sysop/scripts/*.py` invocation a `.venv/bin/` command word."
# The subject list ends here; everything after is the sentence's own exception
# clause (`check_skill_models.py`, `resolve_skill_models.py`, `_model_roles.py`),
# which is NOT bootstrapped and must not be required to carry a rule. Splitting
# on the sentence's grammar beats a hardcoded skip-list: the first draft used
# one, and `_model_roles.py` — named only inside that clause — failed the check
# on the first run.
CARVE_OUT_SUBJECT_END = "all resolve venv PyYAML themselves"


def _carve_out_scripts():
    """Derive the named list from WORKFLOW.md § 8.2a, not from a copy here.

    The author-side rule this repo learned the hard way: derive the population
    from the source of truth, never from an index or summary of it. A hardcoded
    list here would still pass after the doc gained a sixth script.
    """
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if CARVE_OUT_ANCHOR in line:
            assert CARVE_OUT_SUBJECT_END in line, (
                "the carve-out sentence no longer contains "
                f"{CARVE_OUT_SUBJECT_END!r}, so its subject list cannot be "
                "separated from its exception clause. Re-anchor rather than "
                "widening the match — a widened one silently requires rules "
                "for the exceptions, which is the opposite of what it means."
            )
            return re.findall(r"`([a-z0-9_]+\.py)`", line.split(CARVE_OUT_SUBJECT_END)[0])
    raise AssertionError(
        "WORKFLOW.md § 8.2a's venv carve-out sentence is gone or reworded past "
        f"its anchor {CARVE_OUT_ANCHOR!r}. Invariant 1 derives its subjects "
        "from that sentence; re-anchor it rather than hardcoding the list."
    )


def test_the_carve_out_names_a_non_empty_list():
    """Vacuity control for Invariant 1: a reworded sentence must not read clean."""
    scripts = _carve_out_scripts()
    assert len(scripts) >= 4, (
        f"the carve-out sentence yielded {scripts!r}; a list this short means "
        "the extraction has broken and the check below is vacuous"
    )
    assert "backfill_completed_dates.py" in scripts, (
        "backfill_completed_dates.py is the script whose missing allow-rule "
        "this invariant exists to catch; it is no longer extracted from the "
        "sentence, so the regression it guards would now pass unseen"
    )


def test_every_carve_out_script_has_a_bare_python3_rule():
    """Invariant 1 — exactly as filed, and it catches exactly one of the four."""
    rules = _template_rules()
    missing = [
        s
        for s in _carve_out_scripts()
        if not _is_covered("python3", f"sysop/scripts/{s}", rules)
    ]
    assert not missing, (
        "WORKFLOW.md § 8.2a tells consumers that bare `python3 "
        "sysop/scripts/<script>.py` is the form the shipped allow-rules cover, "
        f"and names these scripts for which no such rule exists: {missing}. "
        "Either seed the rule or stop naming the script."
    )


def test_the_carve_out_sentence_is_not_truncated():
    """It shipped ending mid-clause at 'allow-rules' — a claim with no verb.

    Cheap, and it pins the exact defect: the sentence asserted a relationship to
    settings.json and then stopped before saying what the relationship was.
    """
    line = next(
        l for l in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if CARVE_OUT_ANCHOR in l
    )
    assert "allow-rules." not in line, (
        "WORKFLOW.md § 8.2a's carve-out sentence has reverted to ending "
        "mid-clause at '…the shipped `.claude/settings.json` allow-rules.' — "
        "state what the rules DO with that form."
    )


# --------------------------------------------------------------------------
# Invariant 3 — the one invocation shape this phase removed.
# --------------------------------------------------------------------------


def _piped_sysop_commands(fenced):
    """Extracted so a control can exercise the REAL predicate (round finding H2).

    A single `|`, not `||`. The first draft matched both and flagged
    `validate_tasks.py || { echo …; exit 1; }` — an in-repo idiom, and a
    logical-OR rather than a pipe. Over-strictness in the direction that hides:
    a guard that cries wolf gets exempted, not fixed.
    """
    out = []
    for rel, lineno, line in fenced:
        if "sysop/scripts/" not in line:
            continue
        if re.search(r"(?<!\|)\|(?!\|)", line.split("sysop/scripts/")[1]):
            out.append(f"{rel}:{lineno}  {line.strip()[:110]}")
    return out


def test_the_pipe_check_fires_on_a_planted_pipe():
    """Positive control Invariant 3 shipped without (round finding H2).

    With none, `if False:` and `for path in []:` both left it green — so the
    exact `close_batch.sh … | tee /tmp/x.log` defect this phase removed could
    be re-planted with the suite passing.
    """
    planted = [
        ("core/skills/fake/SKILL.md", 9,
         "   bash sysop/scripts/close_batch.sh <N> 2>&1 | tee /tmp/x.log"),
    ]
    assert _piped_sysop_commands(planted), (
        "POSITIVE CONTROL FAILED: a piped sysop command was not reported. "
        "Invariant 3 is inert and the defect it removed can return."
    )
    benign = [
        ("core/skills/fake/SKILL.md", 9,
         "   python3 sysop/scripts/validate_tasks.py || { echo no; exit 1; }"),
    ]
    assert not _piped_sysop_commands(benign), (
        "NEGATIVE CONTROL FAILED: `||` was reported as a pipe. That is an "
        "ordinary in-repo idiom and flagging it gets the check exempted."
    )


def test_no_shipped_fence_pipes_a_sysop_script_into_another_command():
    """`|` starts a new invocation the rules must also cover.

    `/review-close`'s recovery step piped `close_batch.sh` into
    `tee /tmp/close-batch.log`: the left side was covered, `tee` bound nothing,
    and the prompt landed after the close had already run. Two defects in one
    line — an uncovered tail and a hardcoded `/tmp` path.
    """
    offenders = _piped_sysop_commands(_fenced_lines())
    assert not offenders, (
        "a shipped fence pipes a sysop script into another command; the tail "
        "is a separate invocation that needs its own rule, and the prompt "
        "arrives after the script has already run:\n  " + "\n  ".join(offenders)
    )
