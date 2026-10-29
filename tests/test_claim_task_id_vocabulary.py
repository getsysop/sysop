"""`/claim-task` takes any schema-valid task id, whatever its prefix (Phase 332).

Before this phase, Step 1 classified a roadmap task by five hard-coded prefixes
(`FEAT`/`TECH`/`DATA`/`UX`/`FIX`) and printed usage for anything else, and Step 3 turned
the same five into a five-row branch table. `tasks/schema.md` leaves prefixes to the
project, so a consumer's `OPS-FOO` passed its own `validate_tasks.py` and could not be
claimed. `/release` Step 4's category map named the same five and nothing else.

These guards read the rule the skill states and EXECUTE it, rather than matching its
wording:

* Step 1's arms are turned into a classifier (first matching arm wins, in document order)
  and run over ids of known and unknown prefixes. The roadmap arm's grammar must be the
  validator's own `_TASK_ID_RE`, read from the module, not retyped here.
* Step 3's rule is turned into a branch function from the regex it states, and every
  `ID` → `branch` example anywhere in the skill must be what that function produces. The
  branch it produces must round-trip through `sitrep_survey.py`'s reverse mapping.
* An unknown id must still be refused, by Step 2: the real `claim_task.sh --entry-state`
  answers `absent` for it.
* A population scan over shipped markdown refuses a paragraph that lists three or more of
  the old bare branch directories (`` `feat/` ``, `` `tech/` ``, …), whatever fallback it
  states, and one that maps three or more bare old id prefixes (`` `FEAT-` ``) with no
  stated fallback for any other. Every `ID` → `dir/leaf` example in shipped markdown must
  be what Step 3's rule gives.
* **What this module does not do, on Wade's call after Phase 332's round 2:** read the
  MEANING of Step 1's or Step 3's prose. A sentence rule, a carve-out regex and per-clause
  checks were built in round 1; round 2 walked 14 rewordings through them and turned 10
  legal edits red with them, so they were deleted. A reworded gate or carve-out that
  keeps the grammar and the examples right is `Q-560`'s open question about prose guards.
* Lists are read item by item with their continuation lines, under any bullet marker, so
  a re-wrap is not a defect. A mutation row whose anchor is gone fails as `AnchorMoved`,
  distinct from the guard passing a defect.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import sitrep_survey as ss
import validate_tasks as vt
from _prose_guard_helpers import section, states, swap  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "core/skills/claim-task/SKILL.md"
RELEASE = REPO / "core/skills/release/SKILL.md"
SCRIPT = REPO / "core/companion/scripts/claim_task.sh"

# The five prefixes the old gate hard-coded. Used only to recognise the old shape
# coming back; nothing here treats them as the vocabulary.
CANON = ("FEAT", "TECH", "DATA", "UX", "FIX")

STEP1 = "## Step 1: Parse Argument & Classify"
STEP3 = "## Step 3: Generate Branch Name"
RELEASE_STEP4 = "## Step 4 — Join `tasks/index.yml` for human-readable highlights"

_ARROW_PAIR = re.compile(r"`([A-Z][A-Z0-9-]*)`\s*→\s*`([a-z0-9][a-z0-9/-]*)`")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ─── Step 1 ──────────────────────────────────────────────────────────────────


_BULLET = re.compile(r"[-*+] ")


def _norm(s: str) -> str:
    return " ".join(s.split())


def _list_items(block: str) -> list[str]:
    """Each top-level list item WITH its continuation lines, as a verbatim substring.

    Any bullet marker (`-`, `*`, `+`). An item runs until a blank line or the next
    column-0 line that is not an indented continuation. Reading a bullet's first line
    only made the guards red on a legal re-wrap (Phase 332 integration and round 1).
    """
    items, cur = [], None
    for line in block.splitlines(keepends=True):
        if _BULLET.match(line):
            cur = [line]
            items.append(cur)
        elif cur is not None and line.strip() and line.startswith(" "):
            cur.append(line)
        else:
            cur = None
    return ["".join(i).rstrip("\n") for i in items]


def step1_arms(skill_text: str) -> list[str]:
    """The top-level classification bullets of Step 1 (bold-led), in document order."""
    body = section(skill_text, STEP1)
    arms: list[str] = []
    for item in _list_items(body):
        if item[2:].startswith("**"):
            arms.append(item)
        elif arms:
            break
    return arms


def build_classifier(text: str):
    """(classify, problems): a classifier built from Step 1's arms as written."""
    problems: list[str] = []
    arms = step1_arms(text)
    preds = []
    for arm in (_norm(a) for a in arms):
        label = arm.split("→", 1)[0]
        if "Bare integer" in label and "`BATCH-<N>`" in label and "review batch" in arm:
            preds.append(("batch", lambda a: re.fullmatch(r"\d+|BATCH-\d+", a) is not None))
        elif "→ roadmap task" in arm:
            globs = re.findall(r"`[A-Z]+-\*`", arm)
            if globs:
                problems.append(f"the roadmap arm enumerates prefix globs {globs}: a fixed list is a gate")
            named = [p for p in CANON if re.search(rf"`{p}-\*?`", arm)]
            if len(named) >= 3:
                problems.append(f"the roadmap arm names {named}: that is the retired five-prefix list")
            grammars = re.findall(r"`(\^[^`]*\$)`", arm)
            if grammars != [vt._TASK_ID_RE.pattern]:
                problems.append(
                    f"the roadmap arm's grammar is {grammars}, not the validator's own "
                    f"{vt._TASK_ID_RE.pattern!r}: Step 1 and the schema disagree on what an id is"
                )
                continue
            rx = re.compile(grammars[0])
            preds.append(("roadmap", lambda a, rx=rx: rx.fullmatch(a) is not None))
        elif "Empty or unrecognized" in label and "usage" in arm:
            preds.append(("usage", lambda a: True))
        else:
            problems.append(f"unrecognised Step 1 arm: {arm[:80]!r}")

    def classify(arg: str) -> str:
        for kind, pred in preds:
            if pred(arg):
                return kind
        return "none"

    return classify, problems


STEP1_CASES = [
    ("116", "batch"),
    ("BATCH-120", "batch"),
    ("FEAT-STUDIO-UI", "roadmap"),
    ("OPS-FOO", "roadmap"),          # the reported case: a prefix outside the old five
    ("QA-7", "roadmap"),
    ("ABC123", "roadmap"),           # schema-valid with no hyphen at all
    ("SEC-0001", "roadmap"),
    ("Z99", "roadmap"),              # three characters: the grammar's floor
    ("BATCH-X1", "roadmap"),         # id-shaped, not `BATCH-<N>`: Step 2 then answers `absent`
    ("feat-x", "usage"),             # lowercase is not a task id
    ("", "usage"),
    ("--plan-only", "usage"),
    ("OP", "usage"),                 # two characters: under the grammar's three-character floor
]


def step1_problems(skill_text: str) -> list[str]:
    classify, problems = build_classifier(skill_text)
    for arg, want in STEP1_CASES:
        got = classify(arg)
        if got != want:
            problems.append(f"Step 1 classifies {arg!r} as {got}, expected {want}")
    arms = [_norm(a) for a in step1_arms(skill_text)]
    roadmap = [a for a in arms if "→ roadmap task" in a]
    if roadmap and not ("--entry-state" in roadmap[0] and "`absent`" in roadmap[0]):
        problems.append("the roadmap arm no longer hands existence to Step 2's --entry-state `absent`")
    return problems


def test_step1_cases_agree_with_the_validator():
    """The table's own answers, checked against the validator rather than by hand:
    a `roadmap` row is an id `validate_tasks.py` accepts, a `usage` row is not."""
    for arg, want in STEP1_CASES:
        if want == "roadmap":
            assert vt._TASK_ID_RE.match(arg), arg
        elif want == "usage":
            assert not vt._TASK_ID_RE.match(arg), arg


def test_step1_takes_any_schema_valid_id():
    assert step1_problems(_read(SKILL)) == []


STEP2 = "## Step 2: Read Context & Validate"


def step2_problems(skill_text: str) -> list[str]:
    """Step 1 no longer checks existence, so Step 2's `absent` row must stop."""
    rows = [l for l in section(skill_text, STEP2).splitlines() if l.startswith("| `absent` |")]
    if len(rows) != 1:
        return [f"expected one `absent` row in Step 2's entry-state table, found {len(rows)}"]
    cells = [c.strip() for c in rows[0].strip("|").split("|")]
    if len(cells) != 3 or not cells[2].startswith("**Stop.**"):
        return [f"Step 2's `absent` row does not stop: {rows[0][:100]!r}"]
    return []


def test_step2_refuses_an_absent_id_with_a_stop():
    assert step2_problems(_read(SKILL)) == []


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})


def _entry_state(tmp_path, task_id):
    repo = tmp_path / "r"
    if not repo.exists():
        repo.mkdir()
        _git(repo, "-c", "init.defaultBranch=main", "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "tasks").mkdir()
        (repo / "tasks/index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: OPS-FOO\n    status: open\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "seed")
    pybin = tmp_path / "pybin"
    pybin.mkdir(exist_ok=True)
    shim = pybin / "python3"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "PATH": f"{pybin}:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(SCRIPT), "--entry-state", task_id], cwd=str(repo),
                          capture_output=True, text=True, env=env)


def test_entry_state_answers_for_an_unlisted_prefix(tmp_path):
    """The path an `OPS-` id now takes: claimable when listed, `absent` when not."""
    r = _entry_state(tmp_path, "OPS-FOO")
    assert (r.returncode, r.stdout.strip()) == (0, "claimable"), r.stderr
    r = _entry_state(tmp_path, "OPS-NOPE")
    assert (r.returncode, r.stdout.strip()) == (0, "absent"), r.stderr


# ─── Step 3 ──────────────────────────────────────────────────────────────────


def step3_roadmap_block(skill_text: str) -> str:
    body = section(skill_text, STEP3)
    m = re.search(r"\*\*Review\s+batches:\*\*", body)
    assert m, "Step 3 lost its **Review batches:** clause"
    return body[:m.start()]


def _otherwise_items(block: str) -> list[str]:
    """Each `Otherwise` bullet of Step 3 with its continuation lines, verbatim."""
    return [i for i in _list_items(block) if i[2:].startswith("Otherwise")]


def build_branch_rule(text: str):
    """(derive, problems): the branch function Step 3's rule states."""
    problems: list[str] = []
    block = step3_roadmap_block(text)
    bullets = _otherwise_items(block)
    if len(bullets) != 1:
        return None, [f"expected one '- Otherwise' derivation bullet in Step 3, found {len(bullets)}"]
    rule = _norm(bullets[0])
    nested = [l for l in block.splitlines() if re.match(r"^\s+[-*+] ", l)]
    if nested:
        problems.append(f"Step 3 carries a nested list, the per-prefix table shape: {nested[:2]}")
    segs = re.findall(r"`(\^\[A-Z\][^`]*)`", rule)
    if len(segs) != 1:
        return None, problems + [f"Step 3's rule states {len(segs)} leading-segment regexes, not one"]
    seg = re.compile(segs[0])
    def derive(task_id: str) -> str:
        m = seg.match(task_id)
        return f"{m.group(0).lower()}/{task_id.lower()}" if m else ""

    pairs = _ARROW_PAIR.findall(rule)
    if not any(p == "FEAT-X" for p, _ in pairs):
        problems.append("Step 3 lost its `FEAT-X` example, which the option-C release step cites")
    if not any(p.split("-")[0] not in CANON for p, _ in pairs):
        problems.append("Step 3's examples are all old-vocabulary prefixes: nothing shows the rule generalises")
    return derive, problems


def step3_problems(text: str) -> list[str]:
    derive, problems = build_branch_rule(text)
    if derive is None:
        return problems
    # Independent ids, not the document's own examples: the regex must stop at the
    # first hyphen, and a hyphenless id must be its own directory.
    for tid, want in (("OPS-FOO-BAR", "ops/ops-foo-bar"), ("FEAT-X", "feat/feat-x"),
                      ("ABC123", "abc123/abc123"), ("QA2-X", "qa2/qa2-x")):
        if derive(tid) != want:
            problems.append(f"Step 3's rule gives {derive(tid)!r} for {tid}, expected {want!r}")
    # Every `ID` → `branch` example anywhere in the skill must be what the rule produces.
    for tid, branch in _ARROW_PAIR.findall(text):
        if "/" in branch and derive(tid) != branch:
            problems.append(f"the skill maps {tid} → {branch}, but Step 3's rule gives {derive(tid)}")
    return problems


def test_step3_is_one_rule_for_every_prefix():
    assert step3_problems(_read(SKILL)) == []


def shipped_branch_examples(root: Path = REPO) -> list[tuple[str, str, str]]:
    """Every `ID` → `dir/leaf` example in shipped markdown, as (file, id, branch)."""
    out = []
    for base in ("core", "packs"):
        for p in sorted((root / base).rglob("*.md")):
            for tid, branch in _ARROW_PAIR.findall(_read(p)):
                if "/" in branch:
                    out.append((str(p.relative_to(root)), tid, branch))
    return out


def test_every_shipped_branch_example_follows_step3():
    """`/auto-build` and any other skill that names a generated branch must agree with
    Step 3's one rule (round lens 2, A08: `OPS-FOO` → `tech/ops-foo` in auto-build)."""
    examples = shipped_branch_examples()
    assert len({f for f, _, _ in examples}) >= 2, examples  # claim-task and auto-build at least
    assert branch_example_problems() == []


def branch_example_problems(root: Path = REPO) -> list[tuple[str, str, str]]:
    derive, problems = build_branch_rule(_read(SKILL))
    assert problems == []
    return [(f, tid, b) for f, tid, b in shipped_branch_examples(root) if derive(tid) != b]


def test_the_branch_example_check_sees_a_planted_disagreement(tmp_path):
    import shutil
    for base in ("core", "packs"):
        shutil.copytree(REPO / base, tmp_path / base,
                        ignore=lambda d, names: [n for n in names
                                                 if not (n.endswith(".md") or os.path.isdir(os.path.join(d, n)))])
    assert branch_example_problems(tmp_path) == []
    pack = tmp_path / "packs/python/companion/planted.md"
    pack.write_text("A claim of `OPS-FOO` → `tech/ops-foo` lands here.\n", encoding="utf-8")
    assert branch_example_problems(tmp_path) == [
        ("packs/python/companion/planted.md", "OPS-FOO", "tech/ops-foo")]


@pytest.mark.parametrize("tid", ["OPS-FOO", "FEAT-X", "DATA-SERIES-CROSSWALK", "ABC123"])
def test_step3_branch_round_trips_through_sitrep(tid):
    """`sitrep_survey` maps a branch with no `branch:` field back to its task by
    upper-casing everything after the first `/`. The generated name must survive it."""
    derive, problems = build_branch_rule(_read(SKILL))
    assert problems == []
    assert ss._derive_task_id_from_branch(derive(tid), {tid: {}}) == tid


# ─── /release Step 4 ─────────────────────────────────────────────────────────


def release_problems(release_text: str) -> list[str]:
    body = section(release_text, RELEASE_STEP4)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", _norm(body)) if "`id`-prefix category" in s]
    if len(sentences) != 1:
        return [f"expected one sentence naming the `id`-prefix category, found {len(sentences)}"]
    s = sentences[0]
    problems = []
    if not states(s, "any other prefix"):
        problems.append("release Step 4 maps named prefixes and states nothing for any other")
    if "literal prefix" not in s:
        problems.append("release Step 4's fallback no longer names the literal-prefix category")
    return problems


def test_release_names_a_fallback_category():
    assert release_problems(_read(RELEASE)) == []


# ─── population ──────────────────────────────────────────────────────────────

# A line that MAPS three or more of the old five prefixes, and states no fallback for
# any other, is the retired shape. Prose examples ("pick a vocabulary such as FEAT-,
# TECH-, …") carry no mapping marker and are not matched.
_MAPPING_MARKERS = ("→", "Known prefix", "based on the ID prefix")
_FALLBACK_MARKERS = ("any other prefix", "(other)")

def population_offenders(root: Path = REPO) -> set[str]:
    hits = set()
    for base in ("core", "packs"):
        for p in sorted((root / base).rglob("*.md")):
            # Per paragraph, whitespace-normalised: a re-wrap must not split a map from
            # its own fallback (round 2, lens 5).
            for line in (_norm(b) for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8"))):
                # A bare `feat/` directory: a branch map is one rule, so a list of
                # directories is the retired table whatever fallback it states. A full
                # example branch (`feat/feat-a`) is not a directory list.
                dirs = [c for c in CANON if re.search(rf"`{c.lower()}/`", line)]
                if len(dirs) >= 3:
                    hits.add(str(p.relative_to(root)))
                    continue
                # A bare `FEAT-` id prefix: a category map may list prefixes, with a
                # fallback. An example id (`FEAT-FOO`) is not a prefix list.
                named = [c for c in CANON if re.search(rf"`{c}-\*?`", line)]
                if len(named) < 3:
                    continue
                if not any(m in line for m in _MAPPING_MARKERS):
                    continue
                if any(f in line for f in _FALLBACK_MARKERS):
                    continue
                hits.add(str(p.relative_to(root)))
    return hits


def test_no_shipped_prefix_map_without_a_fallback():
    extra = population_offenders()
    assert not extra, f"a shipped file maps the old five prefixes with no fallback: {sorted(extra)}"


# ─── the guards' own discrimination ──────────────────────────────────────────
#
# Each row plants one defect in the shipped text and requires the guard that owns it to
# report a problem. The first three rows are the pre-phase text itself.

_OLD_STEP1_ARM = "- **Known prefix** (`FEAT-*`, `TECH-*`, `DATA-*`, `UX-*`, `FIX-*`) → roadmap task."
_OLD_STEP3 = """- Otherwise, auto-generate from the task ID by lowercasing and mapping the prefix:
  - `FEAT-X` → `feat/feat-x`
  - `TECH-X` → `tech/tech-x`
  - `DATA-X` → `data/data-x`
  - `UX-X` → `ux/ux-x`
  - `FIX-X` → `fix/fix-x`"""


def _roadmap_arm(text):
    arm = next((a for a in step1_arms(text) if "→ roadmap task" in _norm(a)), None)
    if arm is None:
        raise AnchorMoved("Step 1's roadmap arm")
    return arm


def _step3_rule(text):
    return _otherwise_items(step3_roadmap_block(text))[0]


def _swap_arm_order(text):
    arm = _roadmap_arm(text)
    batch = next((a for a in step1_arms(text) if "→ review batch" in _norm(a)), None)
    if batch is None:
        raise AnchorMoved("Step 1's review-batch arm")
    text = text.replace(arm + "\n", "", 1)
    return text.replace(batch, arm + "\n" + batch, 1)


class AnchorMoved(Exception):
    """A mutation row's anchor is gone: the shipped text changed, so re-anchor the row.
    Distinct from the guard passing a defect, which is what the row exists to catch."""


def _edit_in(getter, old, new):
    # Whitespace-tolerant, so a re-wrap of the anchored text does not move the anchor.
    rx = re.compile(r"\s+".join(re.escape(w) for w in old.split()))
    def f(text):
        span = getter(text)
        if not old.split():
            raise AnchorMoved(old)
        m = rx.search(span)
        if not m:
            raise AnchorMoved((old, span[:120]))
        return text.replace(span, span[:m.start()] + new + span[m.end():], 1)
    return f


MUTATIONS = {
    "pre-phase Step 1 gate": (step1_problems, SKILL,
        lambda t: t.replace(_roadmap_arm(t), _OLD_STEP1_ARM, 1)),
    "pre-phase Step 3 table": (step3_problems, SKILL,
        lambda t: t.replace(_step3_rule(t), _OLD_STEP3, 1)),
    "pre-phase release map": (release_problems, RELEASE,
        _edit_in(lambda release_text: section(release_text, RELEASE_STEP4),
                 "; **any other prefix → a category named by the literal prefix**, `OPS-` → `OPS`, "
                 "as `/roadmap` groups kinds — prefixes are project-chosen, so an unmapped one is "
                 "never dropped from the highlights", "")),
    "roadmap arm tested before the batch arm": (step1_problems, SKILL, _swap_arm_order),
    "grammar loosened": (step1_problems, SKILL, _edit_in(_roadmap_arm, "{2,80}", "{1,80}")),
    "prefix globs re-added": (step1_problems, SKILL,
        _edit_in(_roadmap_arm, "whatever its prefix", "whatever its prefix (`FEAT-*`, `OPS-*`)")),
    "existence handed to nobody": (step1_problems, SKILL,
        _edit_in(_roadmap_arm, "answers `absent` for one", "answers for one")),
    "Step 2 absent row continues": (step2_problems, SKILL,
        _edit_in(lambda skill_text: section(skill_text, STEP2),
                 "| `absent` | no such id in `tasks/index.yml` | **Stop.**",
                 "| `absent` | no such id in `tasks/index.yml` | Continue.")),
    "segment regex takes hyphens": (step3_problems, SKILL,
        _edit_in(_step3_rule, "`^[A-Z][A-Z0-9]*`", "`^[A-Z][A-Z0-9-]*`")),
    "non-canonical example wrong": (step3_problems, SKILL,
        _edit_in(_step3_rule, "`ops/ops-foo`", "`tech/ops-foo`")),
    "non-canonical examples dropped": (step3_problems, SKILL,
        lambda t: _edit_in(_step3_rule, "`QA2-X` → `qa2/qa2-x`, and a hyphenless id is its own "
                           "directory: `ABC123` → `abc123/abc123`.", "")(
            _edit_in(_step3_rule, ", `OPS-FOO` → `ops/ops-foo`", "")(t))),
    "FEAT-X example dropped": (step3_problems, SKILL,
        _edit_in(_step3_rule, "`FEAT-X` → `feat/feat-x`, ", "")),
    "table re-added under the rule": (step3_problems, SKILL,
        lambda t: t.replace(_step3_rule(t), _step3_rule(t) + "\n  - `OPS-X` → `ops/ops-x`", 1)),
    "a distant example disagrees": (step3_problems, SKILL,
        lambda t: swap(t, "(`FEAT-X` → `feat/feat-x`) — `claim_task.sh`",
                       "(`FEAT-X` → `feature/feat-x`) — `claim_task.sh`")),
    "five-prefix list re-added without globs": (step1_problems, SKILL,
        _edit_in(_roadmap_arm, "whatever its prefix", "for a `FEAT-`, `TECH-` or `FIX-` prefix")),
    "grammar upper bound drifts": (step1_problems, SKILL, _edit_in(_roadmap_arm, "{2,80}", "{2,90}")),
    "segment regex drops digits": (step3_problems, SKILL,
        _edit_in(_step3_rule, "`^[A-Z][A-Z0-9]*`", "`^[A-Z][A-Z]*`")),
    "non-canonical examples replaced": (step3_problems, SKILL,
        lambda t: _edit_in(_step3_rule, "`QA2-X` → `qa2/qa2-x`, and a hyphenless id is its own "
                           "directory: `ABC123` → `abc123/abc123`.", "`UX-Y` → `ux/ux-y`.")(
            _edit_in(_step3_rule, "`OPS-FOO` → `ops/ops-foo`", "`TECH-FOO` → `tech/tech-foo`")(t))),
    "FEAT-X example replaced": (step3_problems, SKILL,
        _edit_in(_step3_rule, "`FEAT-X` → `feat/feat-x`", "`DATA-X` → `data/data-x`")),
    "fallback names no category": (release_problems, RELEASE,
        _edit_in(lambda release_text: section(release_text, RELEASE_STEP4), "a category named by the literal prefix",
                 "its own category")),
    "release fallback negated": (release_problems, RELEASE,
        _edit_in(lambda release_text: section(release_text, RELEASE_STEP4), "**any other prefix →",
                 "it is not the case that **any other prefix →")),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_guard_refuses(name):
    guard, path, mutate = MUTATIONS[name]
    text = _read(path)
    assert guard(text) == [], f"{name}: the guard is red on the shipped text"
    try:
        mutated = mutate(text)
    except AnchorMoved as e:
        pytest.fail(f"{name}: the row's anchor moved, re-anchor it: {e}", pytrace=False)
    assert mutated != text, f"{name}: the mutation changed nothing"
    assert guard(mutated), f"{name}: the guard passed the defect"


def test_population_scan_sees_a_planted_map(tmp_path):
    """A copy of the shipped markdown tree with one mapping line added must be refused."""
    import shutil
    for base in ("core", "packs"):
        shutil.copytree(REPO / base, tmp_path / base,
                        ignore=lambda d, names: [n for n in names
                                                 if not (n.endswith(".md") or os.path.isdir(os.path.join(d, n)))])
    assert population_offenders(tmp_path) == set()
    planted = tmp_path / "core/skills/next-task/SKILL.md"
    planted.write_text(planted.read_text(encoding="utf-8")
                       + "\nBranch prefix: `FEAT-` → feat, `TECH-` → tech, `FIX-` → fix.\n",
                       encoding="utf-8")
    assert "core/skills/next-task/SKILL.md" in population_offenders(tmp_path)
    # The pre-phase auto-build sentence, and the same list with a fallback bolted on
    # (round lens 2, A06): a branch-directory list is refused whatever fallback it states.
    old_ab = ("Branch-name generation (matches `/claim-task` Step 3): lowercase task ID with prefix "
              "`feat/` / `tech/` / `data/` / `ux/` / `fix/` based on the ID prefix.")
    for i, line in enumerate((old_ab, old_ab[:-1] + ", and `tech/` for any other prefix.")):
        pack = tmp_path / f"packs/python/companion/planted{i}.md"
        pack.parent.mkdir(parents=True, exist_ok=True)
        pack.write_text(line + "\n", encoding="utf-8")
        assert f"packs/python/companion/planted{i}.md" in population_offenders(tmp_path), line
