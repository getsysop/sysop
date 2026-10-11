"""Phase 349: `reasoning` splits into `planner` / `plan-review` / `executor`, and every skill pins.

Upstream #763: `/claim-task` 7a, 7b and 7e and `/auto-build` 6a, 6b and 6e all rode one
`reasoning` pin, and 7b/7e said "same agent parameters as 7a", so a consumer could not move
execution to a cheaper model without moving the plan reviewer with it. Each new role names
`reasoning` and follows it — the `convention-gate` pattern (Phase 262) — so a default install
resolves exactly as before. Upstream #762: `/document-work`, `/sitrep`, `/triage` and
`/auto-fix`'s orchestrator carried no frontmatter pin and rode the session model.

The consequential tests are the resolver runs: they fail if a marker, a role, the resolver's
marker regex or the local-config layering stop lining up. Identity is pinned to each spawn's
own `description`, because Phase 262's round defeated a nearness check with a decoy bullet.
"""
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "core/skills"
CONFIG = REPO_ROOT / "core/companion/.claude/served_models.yml"
RESOLVER = REPO_ROOT / "core/companion/scripts/resolve_skill_models.py"
CLAIM = SKILLS / "claim-task/SKILL.md"
BUILD = SKILLS / "auto-build/SKILL.md"
SHARED = SKILLS / "_shared/adversarial-review.md"
NEW_ROLES = ("planner", "plan-review", "executor")

sys.path.insert(0, str(REPO_ROOT / "core/companion/scripts"))
import _model_roles as m  # noqa: E402  (path set above)

sys.path.insert(0, str(REPO_ROOT / "tests"))
from _prose_guard_helpers import _fence_state  # noqa: E402  the repo's one fence rule


def _sections(lines):
    """[(heading, first line, last line)] for every `#`–`###` heading outside a fence, by the
    repo's CommonMark fence rule — round 2's guards lens walked a naive toggle both ways (a
    fake heading inside a 4-backtick fence; an innocent `~~~` block desynchronising it)."""
    heads = [(i, lines[i]) for i, fenced in _fence_state(lines)
             if not fenced and re.match(r"#{1,3} ", lines[i])]
    out = []
    for k, (i, h) in enumerate(heads):
        end = heads[k + 1][0] - 1 if k + 1 < len(heads) else len(lines) - 1
        out.append((h, i, end))
    return out


def _role_pins():
    """Every per-pin role marker in the skills tree, read with the RESOLVER'S OWN regex, so a
    spelling the resolver honours (inner whitespace, say) is one this guard sees too.

    Yields `(role, file, line index, enclosing heading)`. The heading is the nearest `#`–`###`
    heading outside a fence: a spawn's identity is the step it belongs to, which a decoy bullet
    elsewhere in the file cannot copy (round 1, guards lens, M12)."""
    for path in sorted(SKILLS.rglob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        secs = _sections(lines)
        for i, line in enumerate(lines):
            mk = m._PIN_MARKER_RE.search(line)
            if mk:
                head = next((h for h, a, b in secs if a <= i <= b), "")
                yield mk.group(1), path, i, head


def _marked(role):
    """Every (file, line text) carrying a per-pin marker for `role`."""
    return sorted((p.relative_to(SKILLS).as_posix(), p.read_text(encoding="utf-8").splitlines()[i])
                  for r, p, i, _h in _role_pins() if r == role)


# ── the config ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", NEW_ROLES)
def test_each_new_role_names_reasoning_and_resolves_to_its_model(role):
    """Shipped as the role NAME, so it follows a consumer's `reasoning` choice. A literal
    `opus` here would silently re-raise the pin for a consumer who moved `reasoning`."""
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["roles"]
    assert raw[role] == "reasoning", raw
    roles, _ = m.load_roles_config(CONFIG, None)
    assert roles[role] == roles["reasoning"] == "opus"


def test_a_reasoning_override_still_reaches_every_split_pin(tmp_path):
    """The follow, exercised: `reasoning: sonnet` alone must move the nine split pins."""
    out, stdout = _resolve(tmp_path, "roles:\n  reasoning: sonnet\n")
    for role in NEW_ROLES:
        for rel, line in _marked(role):
            moved = [l for l in (out / rel).read_text().splitlines()
                     if (mk := m._PIN_MARKER_RE.search(l)) and mk.group(1) == role]
            assert moved and all('"sonnet"' in l and '"opus"' not in l for l in moved), (rel, moved)


# ── which spawn carries which role ────────────────────────────────────────────
EXPECTED = {
    # (file, the heading the spawn sits under, the text that identifies THIS spawn)
    "planner": [("claim-task/SKILL.md", "### Step 7a:", '"Plan <CLAIM_ID>"'),
                ("auto-build/SKILL.md", "### Phase 6a:", '"Plan <TASK_ID>"')],
    "plan-review": [("_shared/adversarial-review.md", "## Caller contract", '"Adversarial plan review"'),
                    ("auto-build/SKILL.md", "### Phase 6b:", '"Adversarial plan review <TASK_ID>"'),
                    ("auto-build/SKILL.md", "### Step 7b:", '"Adversarial plan review <TASK_ID>"'),
                    ("claim-task/SKILL.md", "### Step 7b:", '"Adversarial plan review <CLAIM_ID>"')],
    "executor": [("auto-build/SKILL.md", "### Phase 6e:", '"Execute <TASK_ID>"'),
                 ("claim-task/SKILL.md", "### Step 7e:", '"Execute <CLAIM_ID>"'),
                 ("claim-task/SKILL.md", "### Step 8c:", '"Answers <CLAIM_ID>"')],
}


def _spawn_block(lines, idx):
    """The spawn's parameter list around the pin: up to 6 lines above and 8 below, bounded by
    headings and fences, NOT by blank lines — a loose list and a `description` placed above
    the `model` bullet are the same spawn (round 1, guards lens, M10 and M11)."""
    lo = idx
    while lo > 0 and idx - lo < 6 and not re.match(r"(#{1,6} |\s*(```|~~~))", lines[lo - 1]):
        lo -= 1
    hi = idx
    while hi + 1 < len(lines) and hi - idx < 8 and not re.match(r"(#{1,6} |\s*(```|~~~))", lines[hi + 1]):
        hi += 1
    return "\n".join(lines[lo:hi + 1])


def _found(role):
    out = []
    for r, path, i, head in _role_pins():
        if r != role:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        out.append((path.relative_to(SKILLS).as_posix(), head, lines[i], _spawn_block(lines, i)))
    return out


@pytest.mark.parametrize("role", NEW_ROLES)
def test_each_marker_sits_on_the_spawn_it_names(role):
    """Count AND identity. A marker on the wrong spawn — the reviewer's pin marked executor —
    is the single most plausible error here, and it would move review with execution, the
    exact coupling this phase exists to remove."""
    found = _found(role)
    for rel, _head, line, _block in found:
        assert re.search(r'model[`:\s]*"opus"', line), f"{rel}: marker without a pin: {line}"
    problems = _identity_problems(found, EXPECTED[role]) + _section_problems(EXPECTED[role])
    assert not problems, (role, problems)


def _section_problems(want, root=SKILLS):
    """From the DESCRIPTION side (round 2, guards lens, A2b): a retry sentence carrying the
    pin, the marker and the needle under the same heading passed the pin-side check while the
    real spawn went unpinned. So each expected section must have exactly one heading with that
    prefix, exactly one occurrence of the needle, and exactly one inline pin — its own."""
    problems = []
    for rel, heading, needle in want:
        lines = (root / rel).read_text(encoding="utf-8").splitlines()
        secs = [s for s in _sections(lines) if s[0].startswith(heading)]
        if len(secs) != 1:
            problems.append(f"{rel}: {len(secs)} headings start {heading!r}")
            continue
        _h, a, b = secs[0]
        body = lines[a:b + 1]
        if sum(l.count(needle) for l in body) != 1:
            problems.append(f"{rel} {heading}: {needle} occurs {sum(l.count(needle) for l in body)} times")
        pins = [p for p in m.analyze_text("\n".join(body)) if p.kind == "inline"]
        if len(pins) != 1:
            problems.append(f"{rel} {heading}: {len(pins)} inline pins")
    return problems


def _identity_problems(found, want):
    """Each expected (file, heading, needle) must be matched by exactly one marked spawn, and
    every marked spawn must be expected."""
    if len(found) != len(want):
        return [f"{len(found)} marked, {len(want)} expected: {[(f, h) for f, h, _l, _b in found]}"]
    problems = []
    for rel, heading, needle in want:
        hits = [f for f in found if f[0] == rel and f[1].startswith(heading) and needle in f[3]]
        if len(hits) != 1:
            problems.append(f"{len(hits)} marked spawn(s) in {rel} under {heading} carry {needle}")
    return problems


def test_the_identity_check_refuses_a_decoy():
    """Control for the helper: an executor-marked 're-spawn' bullet that copies 6e's
    description but sits under another heading must not stand in for 6e itself."""
    real = [("auto-build/SKILL.md", "### Phase 6e: Execution Agents", "p", '`"Execute <TASK_ID>"`'),
            ("claim-task/SKILL.md", "### Step 7e: Spawn the executor", "p", '`"Execute <CLAIM_ID>"`'),
            ("claim-task/SKILL.md", "### Step 8c: Spawn the answers executor", "p", '`"Answers <CLAIM_ID>"`')]
    assert not _identity_problems(real, EXPECTED["executor"])
    decoy = [("auto-build/SKILL.md", "### Step 9: Re-spawn", "p", '`"Execute <TASK_ID>"`')] + real[1:]
    assert _identity_problems(decoy, EXPECTED["executor"])
    swapped = [real[0], ("claim-task/SKILL.md", "### Step 7a: Spawn the planner", "p", '`"Plan <CLAIM_ID>"`'), real[2]]
    assert _identity_problems(swapped, EXPECTED["executor"])


def test_the_section_check_refuses_a_same_section_decoy(tmp_path):
    """Round 2's A2b: the real 6e pin bullet deleted, and a retry sentence under the same
    heading carries the pin, the marker and the description. Also a duplicated heading."""
    want = [("auto-build/SKILL.md", "### Phase 6e:", '"Execute <TASK_ID>"')]
    (tmp_path / "auto-build").mkdir()
    f = tmp_path / "auto-build/SKILL.md"
    good = ('### Phase 6e: Execution Agents\n\n- `subagent_type`: `"general-purpose"`\n'
            '- `model`: `"opus"` <!-- sysop:role=executor -->\n- `description`: `"Execute <TASK_ID>"`\n')
    f.write_text(good)
    assert not _section_problems(want, tmp_path)
    f.write_text(good.replace('- `model`: `"opus"` <!-- sysop:role=executor -->\n', "")
                 + '- If one dies, re-spawn it: `model`: `"opus"` <!-- sysop:role=executor -->, '
                   '`description`: `"Execute <TASK_ID>"`\n')
    assert _section_problems(want, tmp_path)
    f.write_text(good + "\n### Phase 6e: Execution Agents — retry\n\ntext\n")
    assert _section_problems(want, tmp_path)
    f.write_text("````markdown\n```\n### Phase 6e: fake\n```\n````\n\n" + good)
    assert not _section_problems(want, tmp_path), "a heading inside a 4-backtick fence counted"


def test_the_marker_regex_is_the_resolvers():
    """A marker spelled `<!--  sysop:role=executor  -->` is honoured by the resolver, so the
    guard must read it too rather than fail an innocent reformat."""
    assert m._PIN_MARKER_RE.search('`model`: `"opus"` <!--  sysop:role=executor  -->').group(1) == "executor"


def test_no_split_spawn_inherits_7as_pin_without_its_own():
    """`Same agent parameters as 7a` is how 7b, 7e and 8c were written, and it is how they
    carried no pin the checker could see (#763). Each such line must now pin its own role."""
    seen = []
    for path in (CLAIM, BUILD):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"[Ss]ame agent param(eter)?s as (Step )?7a", line):
                seen.append(path.parent.name)
                assert "<!-- sysop:role=" in line and re.search(r'model[`:\s]*"', line), (
                    f"{path.name}:{n} inherits 7a's parameters with no pin of its own"
                )
    # Population: /claim-task 7b, 7e and 8c, and /auto-build's Step 7b prompt, which spells
    # it "the same agent params as Step 7a". A narrowed pattern loses that one silently.
    assert sorted(seen) == ["auto-build", "claim-task", "claim-task", "claim-task"], seen


def test_auto_build_step_6_names_no_model_for_all_three_phases():
    """Step 6's intro used to say every spawn MUST set `model: "opus"`. Under an executor
    override that sentence contradicts Phase 6e's pin, and — being a pin itself under the
    file's `inline=reasoning` default — it would have stayed on the reasoning model."""
    text = BUILD.read_text(encoding="utf-8")
    intro = [l for l in text.splitlines() if l.startswith("Spawned agents must NOT use `isolation")]
    assert len(intro) == 1, intro
    assert not re.search(r'model[`:\s]*"', intro[0]), intro[0]


# ── the knob, end to end ──────────────────────────────────────────────────────
def _resolve(tmp_path, local):
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    loc = tmp_path / "served_models.local.yml"
    loc.write_text(local)
    r = subprocess.run([sys.executable, str(RESOLVER), "--root", str(skills), "--config",
                        str(CONFIG), "--local", str(loc), "--apply"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return skills, r.stdout


@pytest.mark.parametrize("role,count", [("executor", 3), ("plan-review", 4), ("planner", 2)])
def test_a_one_key_override_moves_that_roles_pins_and_nothing_else(tmp_path, role, count):
    out, stdout = _resolve(tmp_path, f"roles:\n  {role}: sonnet\n")
    changed = []
    for path in sorted(SKILLS.rglob("*.md")):
        before = path.read_text(encoding="utf-8").splitlines()
        after = (out / path.relative_to(SKILLS)).read_text(encoding="utf-8").splitlines()
        assert len(before) == len(after)
        changed += [a for b, a in zip(before, after) if a != b]
    assert len(changed) == count, changed
    assert all(f"<!-- sysop:role={role} -->" in l and '"sonnet"' in l for l in changed), changed
    assert f"APPLIED: {count} pin(s)" in stdout, stdout


def test_the_default_config_is_a_no_op(tmp_path):
    """No override → zero bytes changed. Shipping the split must not change what any
    consumer's spawns run on."""
    out, _ = _resolve(tmp_path, "roles: {}\n")
    for path in SKILLS.rglob("*.md"):
        assert (out / path.relative_to(SKILLS)).read_bytes() == path.read_bytes(), path


# ── #762: every skill pins ────────────────────────────────────────────────────
PINNED_762 = {"document-work": ("reasoning", "opus"), "sitrep": ("quick", "haiku"),
              "triage": ("reasoning", "opus"), "auto-fix": ("mechanical", "sonnet")}


@pytest.mark.parametrize("skill", sorted(PINNED_762))
def test_the_four_formerly_unpinned_skills_carry_their_role(skill):
    role, model = PINNED_762[skill]
    pins = m.analyze_text((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))
    fm = [p for p in pins if p.kind == "frontmatter"]
    assert len(fm) == 1 and fm[0].role == role and fm[0].value == model, fm


def test_every_skill_carries_a_frontmatter_pin():
    """`served_models.yml` now says every skill carries a pin, and the monograph says none
    rides the session model. This is what makes both true."""
    bare = []
    for d in sorted(p for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("_")):
        pins = m.analyze_text((d / "SKILL.md").read_text(encoding="utf-8"))
        if not any(p.kind == "frontmatter" and p.role for p in pins):
            bare.append(d.name)
    assert not bare, f"skills riding the session model: {bare}"
    assert "Every skill carries a pin." in CONFIG.read_text(encoding="utf-8")


# ── #761: prose that names the model behind a role ────────────────────────────
_MODEL_WORD = re.compile(r"\b(opus|sonnet|haiku|fable)(e?s)?\b", re.I)
_CODE_SPAN = re.compile(r"`[^`]*`")

#: Lines in the skills tree that may name a model in prose, keyed by the SHA-256 (16 hex) of
#: the whole line, so editing one forces a re-read. `/auto-fix`'s dated evidence of what Sonnet
#: and Opus were each observed doing (lines 395, 434, 446, 456, 519 at Phase 349), and its
#: `(opus verify)` commit label, an identifier already in consumers' histories (462, 463).
PROSE_ALLOW = {
    "auto-fix/SKILL.md": {'1846f3caaf63296f', '9ee89a9e8a41e2be', 'ebbfcbebf287f758', 'db3897122fb6466d', 'e7a8ee68d5e06892', '4e1c651a94abe4e6', 'eb594184fef9a492'},
}


def _prose_model_mentions():
    """(file, line no, text) for every skills-tree line that names a model outside a pin or a
    code span. Round 1's guards lens walked five rewordings past a 16-phrase denylist
    ("Opus-backed convention gate", "convention gate (Opus)", lower-case), so this matches
    the model WORD, case-insensitively, and allows by line instead."""
    out, scanned = [], set()
    for path in sorted(SKILLS.rglob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        fm = m._frontmatter_close(lines)
        rel = path.relative_to(SKILLS).as_posix()
        scanned.add(rel)
        for n, line in enumerate(lines, 1):
            if fm and n < fm and re.match(r"\s*model:", line):
                continue  # the frontmatter pin itself; its `description:` is shipped prose
            bare = _CODE_SPAN.sub("", m._INLINE_PIN_RE.sub("", line))
            if _MODEL_WORD.search(bare):
                h = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
                if h not in PROSE_ALLOW.get(rel, set()):
                    out.append((rel, n, line.strip()[:110]))
    return out, scanned


def test_no_skill_prose_names_the_model_behind_a_role():
    """The reporter's reproduction, generalised: with `convention-gate: sonnet` a sentence
    saying "the Opus convention gate" was false. Name the role; a value belongs in a code span."""
    offenders, scanned = _prose_model_mentions()
    # Population: every skill body, the shared partials, and the files #761 was filed over.
    skills = {p.name for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("_")}
    assert {f"{s}/SKILL.md" for s in skills} <= scanned, "the scan no longer reads every skill"
    assert "_shared/adversarial-review.md" in scanned and len(skills) >= 20, (len(skills), len(scanned))
    assert not offenders, "\n  ".join(f"{r}:{n}  {s}" for r, n, s in offenders)


def test_the_prose_scan_catches_the_rewordings_that_walked_the_denylist():
    for text in ("the Opus-backed convention gate", "the convention gate (Opus)",
                 "Sonnet fix agents", "the opus convention gate", "All three phases run on Opus."):
        assert _MODEL_WORD.search(_CODE_SPAN.sub("", text)), text
    for text in ("defaults to `opus`", "one of `opus`/`sonnet`/`haiku`/`fable`", "`model: haiku`"):
        assert not _MODEL_WORD.search(_CODE_SPAN.sub("", text)), text


def test_every_prose_allowance_still_matches_a_line():
    """A stale allowance is dead weight that would silently re-admit a reworded line with the
    same hash nowhere; each one must still name a line in its file."""
    for rel, hashes in PROSE_ALLOW.items():
        have = {hashlib.sha256(l.encode("utf-8")).hexdigest()[:16]
                for l in (SKILLS / rel).read_text(encoding="utf-8").splitlines()}
        assert hashes <= have, (rel, hashes - have)


# Round 2 (guards lens, C1–C6) walked the phrase list with "the Opus executor",
# "Opus-based convention gate", "the convention gate runs on Opus" and "the Sonnet plan
# reviewer": it named none of this phase's own roles. So a model word within a few plain
# words of a role noun, in either order, is the finding; a backtick or a parenthesis
# between them ("`convention-gate` role (Opus by default)") breaks the match, and that is
# the one legitimate shape these docs use.
role_noun = (r"(?:convention[- ]gate|executors?|planners?|plan[- ]review(?:ers?)?|reviewers?|"
             r"judges?|judgment|fix agents?|verif\w*|orchestrat\w*|agents?|sub-?agents?|fan-out)")
model = r"(?:opus|sonnet|haiku)"
_DOC_BANNED = re.compile(
    r"inherits? the session model|model · inherits|model-tag\">inherits|"
    rf"\b{model}(?:[- ]backed|[- ]based)?(?:\s+[a-z-]+){{0,2}}\s+{role_noun}\b|"
    rf"\b{role_noun}(?:\s+[a-z-]+){{0,3}}\s+(?:runs?|running)\s+on\s+{model}\b|"
    rf"(?:gate|agents?)\s*\({model}\)|each sub-agent is opus|/opus agents|\(sonnet\)",
    re.I)


def test_the_doc_pattern_catches_round_2s_rewordings_and_spares_the_legitimate_shapes():
    for text in ("the Opus executor", "Opus-based convention gate", "the convention gate runs on Opus",
                 "the Opus convention-gate", "the Sonnet plan reviewer", "the opus convention gate",
                 "two Sonnet fix agents", "Un-pinned skills inherit the session model"):
        assert _DOC_BANNED.search(text), text
    for text in ("the `convention-gate` role (Opus by default)",
                 "Sonnet 5.5 against Opus 5.5 in the executor seat",
                 "the default mapping (fixes on Sonnet, verification on Opus)"):
        assert not _DOC_BANNED.search(text), text


def test_no_shipped_doc_names_the_model_behind_a_role():
    """Outside the skills tree the docs legitimately name models — "(Opus by default)", the
    effort note, GDP's A/B — so there the guard is a case-insensitive phrase list, widened
    after round 1 to the rewordings its guards lens used."""
    offenders, scanned = [], set()
    roots = [REPO_ROOT / "core/companion", REPO_ROOT / "docs"]
    for root in roots + [REPO_ROOT / "README.md", REPO_ROOT / "CONTRIBUTING.md"]:
        for path in (sorted(root.rglob("*")) if root.is_dir() else [root]):
            if not path.is_file() or path.suffix not in {".md", ".py", ".html", ".yml", ".example"}:
                continue
            if path.name == "migrate_skill_model.py":  # its docstring QUOTES the prose it flags
                continue
            scanned.add(path.relative_to(REPO_ROOT).as_posix())
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if _DOC_BANNED.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{n}  {_DOC_BANNED.search(line).group(0)}")
    for must in ("core/companion/docs/WORKFLOW.md", "docs/workflow.html", "docs/configuration.md",
                 "core/companion/scripts/sitrep_survey.py"):
        assert must in scanned, f"the doc prose guard no longer reads {must}"
    assert not offenders, "\n  ".join(offenders)


_ROLE = r"(?:<code>|`)?(?:reasoning|planner|plan-review|executor|convention-gate|mechanical|quick)(?:</code>|`)?"
_SEP = r"\s*(?:/|,|·|\||\band\b|\bor\b)\s*(?:\bor\b\s*)?"
#: A LIST of roles — three or more role names joined by separators — not a line that merely
#: mentions several (docs/configuration.md's spend sentence names three in running prose).
_ROLE_LIST = re.compile(rf"{_ROLE}(?:{_SEP}{_ROLE}){{2,}}")


def _paragraphs(text):
    """(first line no, joined text) per blank-line-separated paragraph, with a leading `#`
    comment marker dropped from each line — so a role list wrapped over two lines, as
    `served_models.yml`'s comments are, is one list (round 2, guards lens, D1)."""
    lines, start, buf = text.splitlines(), None, []
    for n, line in enumerate(lines + [""], 1):
        bare = re.sub(r"^\s*#+\s?", "", line).strip()
        if bare:
            start = start or n
            buf.append(bare)
        elif buf:
            yield start, " ".join(buf)
            start, buf = None, []


def test_the_role_list_predicate_is_not_vacuous():
    """Positive and negative controls, from shapes that shipped."""
    assert _ROLE_LIST.search("Skills pin a ROLE (`reasoning`/`convention-gate`/`mechanical`/`quick`) via")
    assert _ROLE_LIST.search("<code>reasoning</code>, <code>convention-gate</code>, <code>mechanical</code>, or")
    assert _ROLE_LIST.search("# (reasoning / planner / plan-review / executor / convention-gate / mechanical / quick)")
    assert not _ROLE_LIST.search("`mechanical` and `quick` already resolve to Sonnet and Haiku")
    assert _ROLE_LIST.search(" ".join(t for _n, t in _paragraphs("# roles: reasoning / convention-gate /\n# mechanical / quick")))
    assert _ROLE_LIST.search("--role reasoning|convention-gate|mechanical|quick")


def test_no_shipped_enumeration_of_the_roles_omits_the_split():
    """`test_convention_gate_role`'s class, for the three new roles: a list of the role set
    (any run of three or more role names that includes `mechanical`) must name the split and
    `convention-gate` too, or a consumer reading it cannot find the knob. `quick` may be left
    out: the inline-governing lists legitimately omit it."""
    offenders, lists = [], 0
    paths = [p for root in ("core", "docs", "packs") for p in sorted((REPO_ROOT / root).rglob("*"))]
    # Root docs that ship, not the history records (CLAUDE.md, PHASE_LOG.md, REVIEW_*.md),
    # which describe what was true at the time.
    paths += [REPO_ROOT / n for n in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "install.sh")]
    for path in paths:
            if not path.is_file() or path.suffix not in {".md", ".yml", ".html", ".example", ".py",
                                                         ".sh", ".json"}:
                continue
            for n, para in _paragraphs(path.read_text(encoding="utf-8", errors="replace")):
                for run in _ROLE_LIST.finditer(para):
                    lists += "mechanical" in run.group(0)
                    s = run.group(0)
                    if "mechanical" in s and not all(r in s for r in NEW_ROLES + ("convention-gate",)):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{n}  {s[:90]}")
    # Vacuity: the full role lists shipped today (configuration.md x2, WORKFLOW.md § 8.4, the
    # pre-commit example, served_models.yml, the monograph x2). Fewer means the scan narrowed.
    assert lists >= 7, f"only {lists} role lists seen; the guard's population collapsed"
    assert not offenders, offenders


def test_the_effort_guidance_ships_beside_the_executor_knob():
    """A role picks a model; moving `executor` to Sonnet without its effort runs it at the
    model default (`medium`), the cell GDP's A/B found a gap in. Both consumer surfaces say so."""
    doc = (REPO_ROOT / "docs/configuration.md").read_text(encoding="utf-8")
    cfg = re.sub(r"\s*\n#\s*", " ", CONFIG.read_text(encoding="utf-8"))  # unwrap comments
    for text in (doc, cfg):
        assert "the Agent tool has no effort parameter" in text
        assert re.search(r'"modelSettings"\s*:\s*\{\s*"claude-sonnet-5-5"\s*:\s*\{\s*"effortLevel"\s*:\s*"high"', text)
    assert "**Set that model's effort as well.**" in doc


# ── a skill invoked mid-turn must not pin below its caller ───────────────────
_TIER = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}
_SKILL_TOOL = re.compile(r"\bthe\s+`?Skill`?\s+tool\b|\b(?:the\s+)?`/?[a-z-]+`\s+skill\b", re.I)
_VERB = re.compile(r"\b(?:invok\w*|run|runs|running|call\w*|chain\w*|use|uses|using)\b", re.I)


def _invocations(text):
    """The `/skill` names a paragraph invokes through the Skill tool — any verb form, any
    order, across wrapped lines (round 2, guards lens, E2–E6: "run `/x` via the Skill tool",
    "invokes", "use the Skill tool to invoke", a line break between the two halves)."""
    for para in re.split(r"\n\s*\n", text):
        if _SKILL_TOOL.search(para) and _VERB.search(para):
            yield from re.findall(r"`/([a-z][a-z-]+)", para)


def _frontmatter_model(skill):
    pins = m.analyze_text((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))
    roles, _ = m.load_roles_config(CONFIG, None)
    fm = [p for p in pins if p.kind == "frontmatter"]
    return roles[fm[0].role] if fm and fm[0].role else None


def test_no_skill_invokes_a_cheaper_pinned_skill_mid_turn():
    """Round 1, execution lens: `/auto-judge` invokes `/triage` through the Skill tool, and a
    skill's frontmatter model holds for the rest of the turn (the skills docs), so a cheaper
    `/triage` would have run `/auto-judge`'s own orchestration on the cheaper model. Wade's
    answer put `/triage` on `reasoning`. Checked on the default mapping, orchestrator to skill;
    an Agent-spawned executor invoking `/document-work` is outside this check."""
    pairs, offenders = [], []
    for caller in sorted(p.name for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for callee in set(_invocations((SKILLS / caller / "SKILL.md").read_text(encoding="utf-8"))):
                if callee == caller or not (SKILLS / callee / "SKILL.md").is_file():
                    continue
                pairs.append((caller, callee))
                a, b = _frontmatter_model(caller), _frontmatter_model(callee)
                if _TIER[b] < _TIER[a]:
                    offenders.append(f"/{caller} ({a}) invokes /{callee} ({b})")
    # Population: the three mid-turn invocations shipped today (the executor's is in a prompt
    # the orchestrator hands to a spawned agent, and is matched too, harmlessly: same tier).
    assert {("auto-fix", "triage"), ("auto-judge", "triage"), ("claim-task", "document-work")} <= set(pairs), pairs
    assert not offenders, offenders


def test_the_invocation_scan_reads_every_phrasing_round_2_used():
    for text in ("Run `/sitrep` via the Skill tool.", "Invoke the `/sitrep` skill first.",
                 "It invokes `/sitrep` via the Skill tool.", "invoke `/sitrep`,\nthen via the Skill tool",
                 "Use the Skill tool to invoke `/sitrep`."):
        assert list(_invocations(text)) == ["sitrep"], text
    assert not list(_invocations("See `/sitrep` for the survey."))
