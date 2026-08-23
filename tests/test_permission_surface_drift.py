"""Drift guard for the permission surface (Phase 152, upstream #205 + #210).

The defect this exists to prevent: the shipped `.claude/settings.json` template
and the skills' Step 0 "required rules" blocks drifted apart with nothing
verifying them against each other. `/review-close` hard-required six rules the
installer never seeded (five `pr`-policy verbs plus a `git worktree list` shape
mismatch), and `/sitrep` hard-required six git rules that never shipped — five
plainly read-only verbs the harness auto-approves in every mode, plus a
`git worktree list:*` for a call it makes inside `sitrep_survey.py` rather than
at the Bash layer. Neither surfaced because the consumers exercising those paths
knowingly overrode the documented gate.

Five assertions, in both directions:

1. Every rule a skill declares as *required* (bullet form, inside its pre-flight
   block) is satisfied by the shipped template — otherwise a fresh install
   hard-stops at Step 0.
2. Every rule the template seeds is either named by a skill or carries an
   explicit justification here, so headroom is a decision rather than accretion.
3. No skill declares a read-only `git` verb as required. Claude Code
   auto-approves read-only forms of `git` in every mode, so listing one costs a
   fresh-install hard-stop and buys nothing (the `/sitrep` regression).
4. The guard reads `permissions.defaultMode` and skips rather than halting under
   `bypassPermissions`, and every skill whose pre-flight can hard-stop points at
   that escape.
5. No skill cites a pre-Phase-152 guard step number (the Algorithm renumbered;
   `/report-issues` kept citing step 4, which now names a different step).

WHAT THIS FILE CANNOT DO. Assertions 4 and 5 are drift guards over *prose*. The
first draft's versions were substring-presence checks over the whole file, and
an adversarial reviewer defeated all four with semantic inversions that kept the
tokens — an HTML-commented step, "the allow-list is **not** inert", "**Ignore**
`permissions.defaultMode`", a skill *naming* the mode check while negating it,
and "Do not stop." kept as a historical note beside a halting instruction. They
now parse the numbered Algorithm step in isolation, strip HTML comments and
blockquoted lines first, and pin whole clauses rather than fragments, which
kills all six. That is a higher bar, not a proof: prose asserting the opposite
of what it says elsewhere can still be written. These guards catch drift, not an
adversary.

WHAT A RULE STRING DOES NOT PROVE. A rule being present does not mean the
command is authorized — the matcher compares against the literal text sent, and
an assignment capture, a `for … done` loop, a `|| true` tail, or a variable
command word each defeat an otherwise-correct rule. Nothing here checks
invocation shapes; see `WORKFLOW.md` § 8.2a *Invocation shapes* for the ones
Sysop knows are uncovered.

Matcher semantics used below were established by a `claude-code-guide` probe of
the official permissions docs on 2026-07-26: rules match the literal text the
model sends (before shell expansion), and a trailing `:*` is a wildcard with a
word boundary, so `Bash(git:*)` covers `git worktree list --porcelain` while
`Bash(git worktree list)` — no wildcard — matches only the bare invocation.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "core/companion/.claude/settings.json"
SKILLS_DIR = REPO_ROOT / "core/skills"
GUARD = SKILLS_DIR / "_shared/permission-guard.md"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"

# Read-only forms of `git`, auto-approved in every permission mode. A skill that
# lists one of these as a required rule hard-stops consumers for nothing. Keyed
# on the bare verb: `git branch:*` is banned, `git branch -d:*` is not (that one
# writes).
READ_ONLY_GIT_VERBS = (
    "git log", "git status", "git branch", "git diff", "git rev-parse",
    "git rev-list", "git show", "git describe", "git blame", "git ls-files",
    "git shortlog", "git for-each-ref", "git cat-file", "git merge-base",
    "git check-ignore", "git name-rev",
)
# Verbs above that also have a *write* form, so only their bare spelling is
# banned: `git branch -d`/-D really does delete, and /review-close requires
# both. Everything else in the list writes nothing whatever its flags, so a
# flagged spelling (`git log --oneline`) is banned too and cannot smuggle the
# verb past the check.
WRITE_CAPABLE_SPELLINGS = ("git branch",)
# NOTE ON THE EVIDENCE THIS BAN RESTS ON. The docs verify the *category*
# ("read-only forms of `git`" run without a prompt in every mode) but never
# enumerate its members, and describe the surrounding built-in set as
# non-exhaustive. So membership is an inference, and this test promotes that
# inference to a gate. That is deliberate and bounded: the cost of a wrong ban
# is that a genuinely-needed rule cannot be *declared* (it can still ship, and
# `git worktree list:*` does), while the cost of no ban is the /sitrep
# regression — a fresh-install hard-stop on rules the installer never seeds.
# Revisit if Claude Code ever publishes the enumeration.

# Seeded rules no skill names in backticks. Each needs a reason, so that "is this
# dead weight or intentional headroom?" is answered once per rule instead of
# re-litigated. Removing a rule from the template does NOT remove it from an
# installed consumer (install_permissions set-unions), so pruning buys nothing
# for existing installs — the bar for keeping one is only that it is reachable.
SEEDED_WITHOUT_SKILL_MENTION = {
    # ---- Phase 220: the near-miss reporter. Prescribed by WORKFLOW.md in a
    # fence, by `close_batch.sh`'s grep-fallback warning and by
    # `archive_review_tasks.py`'s refusal — all three name
    # `--check-headers` as the way to list the offending headers. No skill
    # step invokes it: it is what an operator runs after a tool tells them a
    # header is unreadable.
    "Bash(python3 sysop/scripts/review_index.py:*)":
        "Prescribed by WORKFLOW.md \u00a7 4.2's canon block, by close_batch.sh's "
        "fallback warning and by the archiver's near-miss refusal; no skill "
        "step runs it (Phase 220).",
    # ---- Phase 184: prescribed by docs and by the installer, not by a skill
    # step. `test_prescribed_command_coverage.py` is the guard that now
    # requires them; each is reachable from shipped instructions.
    "Bash(bash sysop/scripts/self_check.sh)":
        "install.sh's post-install footer prints this in BOTH modes and "
        "docs/getting-started.md puts it in a fence; WORKFLOW.md § 8.4 lists "
        "it as the one-command health check. No skill step invokes it.",
    "Bash(bash sysop/scripts/self_check.sh:*)":
        "Same self_check.sh script, with flags (Phase 184). The installer "
        "prints the absolute-path spelling too, which no relative rule can "
        "match — a stated limit.",
    "Bash(bash sysop/scripts/cleanup_worktrees.sh)":
        "WORKFLOW.md § 4 prescribes it as an operator step and /sitrep names "
        "it as a recommended actuator; /claim-task and /auto-build discuss "
        "its --force semantics but neither runs it.",
    "Bash(bash sysop/scripts/cleanup_worktrees.sh:*)":
        "Same cleanup_worktrees.sh script with --clean / --force (Phase "
        "184), which is the form WORKFLOW.md § 4 actually shows.",
    "Bash(python3 sysop/scripts/backfill_completed_dates.py)":
        "No skill prescribes it; core/companion/tasks/README.md carries the "
        "one recipe that runs it, and WORKFLOW.md § 8.2a used to claim an "
        "allow-rule existed for it when none did (Phase 184).",
    "Bash(python3 sysop/scripts/backfill_completed_dates.py:*)":
        "Same backfill_completed_dates.py script with --path (Phase 184), "
        "the form the roadmap-migration recipe in tasks/README.md uses.",
    "Bash(bash sysop/scripts/install_hooks.sh)":
        "Human-invoked only since Phase 150 removed the worktree auto-arm; "
        "WORKFLOW.md § 8.2a records it as direct-user-invocation-only; § 8.4 "
        "lists it as the post-reconcile re-arm step.",
    "Bash(bash sysop/scripts/sysop-update.sh)":
        "Human/agent-invoked update shim (sysop-update.sh), not a skill step "
        "— shipped for agent-driven updates in Phase 99.",
    "Bash(bash sysop/scripts/sysop-update.sh:*)":
        "Same shim with flags — `--yes` clears install.sh's interactive gate "
        "for agent-driven updates (Phase 99).",
    "Bash(python3 -c:*)":
        "Headroom. Since Phase 126 every skill heredoc uses the `python3 - <<` "
        "form instead; the only live `python3 -c` in shipped consumer content "
        "is inside claim_task.sh (install.sh uses it too, maintainer-side), "
        "which runs as a subprocess of an already-permitted bash call and binds "
        "no rule of its own. Kept because the `-c` form is the natural sibling "
        "of a rule we do grant and pruning it cannot help installed consumers.",
    "Bash(.venv/bin/python3 sysop/scripts/validate_tasks.py)":
        "Phase 45b venv twin; /intake, /add-task, /onboard, /claim-task and "
        "/auto-build all invoke the venv form with no arguments.",
    "Bash(.venv/bin/python3 sysop/scripts/validate_tasks.py:*)":
        "Phase 45b venv twin, invoked with `--quiet` / `--path`.",
    "Bash(python3 sysop/scripts/sitrep_survey.py)":
        "No-arg twin of the sitrep_survey.py rule /sitrep declares — the "
        "script takes only optional flags, so the bare form is a live spelling.",
    "Bash(python3 sysop/scripts/next_task.py)":
        "Non-venv twin of the next_task.py call /next-task ships, whose "
        "$ARGUMENTS may be empty (Phase 45b dual-spelling convention).",
    "Bash(python3 sysop/scripts/next_task.py:*)":
        "Non-venv twin of the next_task.py call /next-task ships with "
        "--review / --avoid-inflight (Phase 45b dual-spelling convention).",
    "Bash(.venv/bin/python3 sysop/scripts/next_task.py)":
        "The next_task.py spelling /next-task actually ships (Phase 45b "
        "venv-preferred), with empty $ARGUMENTS.",
    "Bash(.venv/bin/python3 sysop/scripts/next_task.py:*)":
        "The next_task.py spelling /next-task actually ships (Phase 45b "
        "venv-preferred), with arguments.",
    "Bash(python3 sysop/scripts/scope_overlap.py)":
        "No-arg twin of the rule /claim-task Step 2 declares. Every documented "
        "invocation of scope_overlap.py passes a TASK_ID, so this bare form is "
        "headroom rather than a live path.",
    "Bash(.venv/bin/python3 sysop/scripts/scope_overlap.py)":
        "No-arg twin in the Phase 45b venv spelling; headroom, same as above.",
    "Bash(.venv/bin/python3 sysop/scripts/scope_overlap.py:*)":
        "The scope_overlap.py spelling /claim-task Step 2 ships (Phase 45b "
        "venv-preferred).",
    "Bash(.venv/bin/python3 sysop/scripts/ingest_security_report.py:*)":
        "Phase 45b venv twin of /security-audit Step 3c's ingest call.",
    "Bash(.venv/bin/python3 sysop/scripts/pr_dependabot.py:*)":
        "Phase 45b venv twin of /pr-dependabot's classifier call.",
}


def _seeded():
    return json.loads(TEMPLATE.read_text())["permissions"]["allow"]


def _inner(rule):
    """`Bash(git add:*)` -> `git add:*`."""
    m = re.fullmatch(r"Bash\((.*)\)", rule)
    return m.group(1) if m else None


def _wildcard_prefix(inner):
    """The command prefix a trailing-wildcard rule authorizes, else None."""
    for suffix in (":*", " *"):
        if inner.endswith(suffix):
            return inner[: -len(suffix)]
    return None


def satisfied(required, allow_rules):
    """Does `allow_rules` satisfy `required`?

    Exact match, or a broader rule whose wildcard prefix covers it. This mirrors
    `_shared/permission-guard.md` § Algorithm step 4 — checking exact strings
    alone reports a false miss against a consumer running `Bash(git:*)`.
    """
    if required in allow_rules:
        return True
    r = _inner(required)
    if r is None:
        return False
    for rule in allow_rules:
        a = _inner(rule)
        if a is None:
            continue
        prefix = _wildcard_prefix(a)
        if prefix is None:
            continue
        if r == prefix or r.startswith(prefix + " ") or r.startswith(prefix + ":"):
            return True
    return False


def _preflight_body(text):
    """The skill's pre-flight / Step 0 section, up to the next `## ` heading."""
    m = re.search(r"^## (Pre-flight|Step 0)[^\n]*\n(.*?)(?=^## )", text, re.S | re.M)
    return m.group(2) if m else None


def declared_required():
    """skill name -> [rules declared required], bullet form only.

    Bullet form is the contract: a `Bash(...)` named in a *paragraph* of the
    pre-flight is documentation (an explicit non-entry, or a note about what the
    template ships), not a hard requirement. `/review-close` relies on this to
    say out loud which verbs it deliberately does NOT require.
    """
    out = {}
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        body = _preflight_body(path.read_text())
        if body is None:
            continue
        rules = []
        for line in body.splitlines():
            if re.match(r"^\s*[-*] ", line):
                rules += re.findall(r"`(Bash\([^`]+\))`", line)
        if rules:
            out[path.parent.name] = rules
    return out


def mentioned_anywhere():
    rules = set()
    for path in SKILLS_DIR.rglob("*.md"):
        rules |= set(re.findall(r"`(Bash\([^`]+\))`", path.read_text()))
    return rules


# ── sanity floors: every assertion below is vacuous if the parser finds nothing ──

# Every skill whose pre-flight declares required rules. Asserted as a SET, not a
# count: a count floor let four skills be renamed out of the scan while the
# suite stayed green (Phase 152 adversarial review). Adding or removing a skill
# here is a deliberate decision, exactly like EXPECTED_LOOP_ALLOW.
SKILLS_WITH_DECLARED_RULES = {
    "auto-build", "auto-fix", "auto-judge", "claim-task", "codebase-review",
    "contribute-convention", "document-work", "pr-dependabot", "release",
    "report-issues", "review-close", "roadmap", "security-audit", "share-wins",
    "sitrep", "triage",
}


def test_parsers_find_the_surface():
    seeded = _seeded()
    assert len(seeded) > 50, f"template shrank unexpectedly: {len(seeded)} rules"
    declared = declared_required()
    assert set(declared) == SKILLS_WITH_DECLARED_RULES, (
        "the set of skills whose pre-flight parses changed — a renamed heading "
        "silently drops a skill from every check below. "
        f"missing={SKILLS_WITH_DECLARED_RULES - set(declared)} "
        f"unexpected={set(declared) - SKILLS_WITH_DECLARED_RULES}"
    )
    assert len(declared["review-close"]) >= 24, "review-close pre-flight under-parsed"
    mentioned = mentioned_anywhere()
    assert len(mentioned) > 40, "backtick-mention scan under-parsed"
    # `Bash(git:*)` is named only in _shared/permission-guard.md, so this fails
    # if the scan stops recursing into _shared/ (where the shared partials live).
    assert "Bash(git:*)" in mentioned, "_shared/ dropped out of the mention scan"


# ── direction 1: declared -> seeded ──

def test_every_declared_required_rule_ships_in_the_template():
    """Upstream #210: six of /review-close's 23 were absent, so a `pr`-policy
    consumer hard-stopped at Step 0 on a fresh install."""
    seeded = _seeded()
    missing = {
        skill: [r for r in rules if not satisfied(r, seeded)]
        for skill, rules in declared_required().items()
    }
    missing = {k: v for k, v in missing.items() if v}
    assert not missing, (
        "skills hard-require rules the installer never seeds — a fresh install "
        f"hard-stops at Step 0: {missing}"
    )


# ── direction 2: seeded -> declared or justified ──

def test_every_seeded_rule_is_named_by_a_skill_or_justified():
    mentioned = mentioned_anywhere()
    orphans = [
        r for r in _seeded()
        if r not in mentioned and r not in SEEDED_WITHOUT_SKILL_MENTION
    ]
    assert not orphans, (
        "seeded rules that no skill names and that carry no justification in "
        f"SEEDED_WITHOUT_SKILL_MENTION: {orphans}"
    )


def test_justification_list_has_no_stale_entries():
    """A justified-orphan entry that a skill now names, or that the template no
    longer ships, is stale bookkeeping — the inventory must stay live."""
    seeded, mentioned = set(_seeded()), mentioned_anywhere()
    stale = [
        r for r in SEEDED_WITHOUT_SKILL_MENTION
        if r not in seeded or r in mentioned
    ]
    assert not stale, f"stale SEEDED_WITHOUT_SKILL_MENTION entries: {stale}"


def test_every_justification_names_something_concrete():
    """A length floor alone passes on 42 characters of filler. Require a real
    referent — a script path, a skill, or a phase."""
    for rule, reason in SEEDED_WITHOUT_SKILL_MENTION.items():
        assert len(reason.strip()) > 40, f"{rule} carries no real justification"
        assert any(
            tok in reason for tok in (".py", ".sh", "/", "Phase")
        ), f"{rule}'s justification names no script, skill, or phase: {reason!r}"


# ── direction 3: read-only git must not be required ──

def test_no_skill_requires_a_read_only_git_verb():
    """The `/sitrep` regression: it required `git log`, `git status`,
    `git branch`, `git rev-parse` and `git rev-list`, none of which ship, and
    ended its block with "Do not proceed"."""
    offenders = {}
    for skill, rules in declared_required().items():
        for rule in rules:
            inner = _inner(rule)
            if inner is None:
                continue
            exact = inner[:-2] if inner.endswith((":*", " *")) else inner
            # Normalise to the first two tokens so a flag cannot smuggle a
            # banned verb past the check (`Bash(git log --oneline:*)`) — except
            # for the verbs that have a real write form, where only the bare
            # spelling is banned.
            verb = " ".join(exact.split()[:2])
            banned = exact in READ_ONLY_GIT_VERBS if verb in WRITE_CAPABLE_SPELLINGS \
                else verb in READ_ONLY_GIT_VERBS
            if banned:
                offenders.setdefault(skill, []).append(rule)
    assert not offenders, (
        "read-only git verbs declared as required rules — the harness "
        f"auto-approves these in every mode: {offenders}"
    )


# ── direction 4: the mode check exists and is reachable from the skills ──

def _guard_live_text():
    """The guard's prose with HTML comments and blockquoted lines removed.

    Both are ways to disable an instruction while leaving its words in the file
    — the class that let a commented-out guard satisfy a Phase-151 test.
    """
    text = re.sub(r"<!--.*?-->", "", GUARD.read_text(), flags=re.S)
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith(">")
    )


def _algorithm_step(n):
    """The live text of numbered Algorithm step `n`, up to the next step."""
    body = _guard_live_text()
    body = body[body.index("## Algorithm"):]
    m = re.search(rf"^{n}\. (.*?)(?=^{n + 1}\. |^## )", body, re.S | re.M)
    return " ".join(m.group(1).split()) if m else None


def test_guard_step_3_reads_default_mode_and_proceeds_under_bypass():
    """Upstream #205: the guard stated its precondition and never tested it.

    Asserted on step 3's own text rather than the whole file, so a sentence
    kept elsewhere as a historical note cannot stand in for a live instruction.
    """
    step = _algorithm_step(3)
    assert step, "Algorithm step 3 is missing, commented out, or blockquoted"
    assert re.search(r"\*\*Read `permissions\.defaultMode`\*\*", step), (
        "step 3 no longer *reads* permissions.defaultMode (an 'Ignore …' or "
        "'Re-read permissions.allow' rewrite lands here)"
    )
    assert "bypassPermissions" in step
    assert "is **inert**" in step and "not inert" not in step, (
        "step 3 no longer states the allow-list is inert under bypassPermissions"
    )
    assert "Do not stop." in step, "step 3's verdict is no longer proceed-not-halt"
    for halting in ("stop with a clean error", "hard-stop", "halt the run"):
        assert halting not in step, f"step 3 now halts ({halting!r})"


def test_guard_step_4_accepts_a_broader_allow_rule():
    """A consumer running `Bash(git:*)` must not be told every git rule is
    missing. Pinned on step 4's text so an inverted rewrite ("satisfied ONLY by
    an exact string match, and never by a broader allow-rule…") fails."""
    step = _algorithm_step(4)
    assert step, "Algorithm step 4 is missing, commented out, or blockquoted"
    assert "satisfied by an **exact string match**, or by a **broader allow-rule that already covers it**" in step, (
        "step 4 no longer tolerates a broader-but-equivalent consumer rule"
    )
    assert "`Bash(git:*)`" in step and "satisfy a requirement" in step


# The sanctioned escape wording. Pinned as one phrase so a skill cannot satisfy
# the check by *naming* the mode check while negating it ("the guard's step 3
# mode check does NOT apply to this skill").
MODE_CHECK_ESCAPE = "unless the guard's step 3 mode check applies"


def test_hard_stopping_skills_point_at_the_mode_check():
    """A skill that can hard-stop must name the escape, or #205 recurs one skill
    at a time. Whitespace is collapsed before both checks: `/report-issues`
    hard-wraps `Do not\nproceed.` and escaped this test entirely until Phase
    152's review caught it."""
    offenders = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        body = _preflight_body(path.read_text())
        if body is None:
            continue
        flat = " ".join(body.split())
        if "Do not proceed" not in flat:
            continue
        if MODE_CHECK_ESCAPE not in flat:
            offenders.append(path.parent.name)
    assert not offenders, (
        "skills whose pre-flight hard-stops without pointing at the guard's "
        f"bypassPermissions mode check: {offenders}"
    )


def test_no_skill_cites_a_stale_guard_step_number():
    """The Algorithm renumbered in Phase 152 (the error message moved 4 -> 5).
    `/report-issues` kept citing step 4, which after the renumber names the
    satisfaction check rather than the error."""
    stale = []
    for path in sorted(SKILLS_DIR.rglob("*.md")):
        if path == GUARD:
            continue
        flat = " ".join(path.read_text().split())
        if re.search(r"§ Algorithm step [1-4]\b", flat):
            stale.append(path.parent.name)
    assert not stale, f"skills citing a pre-Phase-152 guard step number: {stale}"


def test_workflow_illustrative_allowlist_is_a_subset_of_the_template():
    """§ 8.2a calls its JSON block an illustrative subset. It is allowed to be
    incomplete; it is not allowed to name a rule the template does not ship —
    that is how the stale `Bash(git worktree list)` survived there."""
    text = WORKFLOW.read_text()
    m = re.search(r"### 8\.2a.*?```json\n(.*?)\n```", text, re.S)
    assert m, "§ 8.2a illustrative settings.json block not found"
    illustrative = set(re.findall(r'"(Bash\([^"]*\))"', m.group(1)))
    assert len(illustrative) > 15, "§ 8.2a block under-parsed"
    seeded = set(_seeded())
    assert illustrative <= seeded, (
        "§ 8.2a names rules the template does not ship: "
        f"{sorted(illustrative - seeded)}"
    )


def test_workflow_no_longer_claims_git_add_is_a_conscious_omission():
    """The omission's stated reason ("the auto-mode classifier passes these")
    is false under `dontAsk`, and the rule now ships."""
    text = WORKFLOW.read_text()
    m = re.search(r"\*\*Conscious omissions\*\*.*?(?=\n\n\*\*|\n\n### )", text, re.S)
    assert m, "§ 8.2a Conscious omissions block not found"
    block = m.group(0)
    for rule in ("`Bash(git add:*)`", "`Bash(git branch -D:*)`"):
        bullets = [
            ln for ln in block.splitlines()
            if ln.lstrip().startswith("- ") and rule in ln
        ]
        assert not bullets, (
            f"{rule} is named in a conscious-omission bullet but ships in the "
            f"template: {bullets}"
        )
