"""`security_partition.py` — the residual assignment for `/security-audit` (Phase 231).

Every number this tool prints is a coverage claim, so every one of them is pinned here against
a real git fixture rather than a mocked one. The defects these guard against are not
hypothetical: each was produced by the author's own drafts and caught by running the thing.

  * the splitter silently DROPPED files when a group deepened (partition invariant);
  * an agent was handed 45 files and credited for 25 (assignment vs coverage);
  * the consumer-first ranking was undone by an innocent-looking `sorted()`, so a
    budget-bound run dropped ten of the consumer's files and kept thirty of Sysop's;
  * `agents_needed_for_full` was false in BOTH directions across two drafts.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "core/companion/scripts/security_partition.py"
SKILL = ROOT / "core/skills/security-audit/SKILL.md"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

MAP_CONCRETE = """\
## `scripts/*.sh` — Shell Scripts

**Check:**
- **A03 Injection**: quote expansions

**Skip:** A01

---

## `<api module>/routes/**/*.py` — API Endpoints (placeholder)

**Check:**
- **A01 Access Control**: authorize every route

**Skip:** A05

---

## `Dockerfile`, `<datajobs Dockerfile>` — Container Build

**Check:** A05 (base image pinning)

**Skip:** A03

---

## `svc/**/*.py` — Service code (concrete, uses `**`)

**Check:**
- **A03 Injection**: parameterize

**Skip:** A07

---

## `docs/*.md` — Docs, no category

**Check:**
- something with no bold category lead

**Skip:** A01
"""


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True, text=True,
    )


def _report(root: Path, *args: str) -> dict:
    p = _run(root, "--json", *args)
    assert p.returncode == 0, f"exit {p.returncode}: {p.stderr}"
    return json.loads(p.stdout)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer repo: 4 mapped-ish files, app code, and a Sysop footprint in the lock."""
    r = tmp_path / "consumer"
    (r / ".claude").mkdir(parents=True)
    (r / "scripts").mkdir()
    (r / "api" / "routes").mkdir(parents=True)
    (r / "auth").mkdir()
    (r / "docs").mkdir()
    (r / "svc" / "inner").mkdir(parents=True)
    # A DEEP tree with more files than any per-agent credit used below, so the group-splitting
    # paths (deepen, and accumulate-don't-assign) are actually exercised. A shallow fixture
    # leaves both of them unreached and every assertion about them vacuous.
    (r / "bulk" / "a").mkdir(parents=True)
    (r / "bulk" / "b").mkdir(parents=True)

    (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    (r / "scripts" / "deploy.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (r / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    # `api/server.py` is a DIRECT CHILD — the case a plain `**` pathspec drops.
    (r / "api" / "server.py").write_text("x = 1\n", encoding="utf-8")
    (r / "api" / "routes" / "users.py").write_text("y = 2\n", encoding="utf-8")
    (r / "auth" / "session.py").write_text("z = 3\n", encoding="utf-8")
    (r / "docs" / "guide.md").write_text("hi\n", encoding="utf-8")
    # `svc/main.py` is the direct child a plain `**` pathspec drops; `svc/inner/deep.py` is
    # the nested one it keeps. Both are matched by a CONCRETE section, so if the resolver
    # stops using `:(glob)` the direct child falls into the residual and the tests below say so.
    (r / "svc" / "main.py").write_text("a = 1\n", encoding="utf-8")
    (r / "svc" / "inner" / "deep.py").write_text("b = 2\n", encoding="utf-8")
    for i in range(12):
        (r / "bulk" / ("a" if i % 2 else "b") / f"f{i:02d}.py").write_text(
            "c = 3\n", encoding="utf-8")
    (r / ".claude" / "sysop.lock").write_text(
        json.dumps({"version": 1, "managed_paths": [".claude/security_map.md"]}),
        encoding="utf-8")

    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture")
    return r


# --------------------------------------------------------------------------- #
# the partition is a partition
# --------------------------------------------------------------------------- #

def test_every_residual_file_lands_in_exactly_one_assignment(repo: Path) -> None:
    """The invariant that caught the first draft: deepening a group DELETED files.

    A path shallower than the split depth was routed to a shared `(root)` key, and an
    unsplit group then assigned over that key wholesale. Nothing reported it — the files
    simply stopped existing, which is the worst way for a coverage tool to be wrong.
    """
    r = _report(repo)
    placed = [f for a in r["assignments"] for f in a["files"]]
    assert len(placed) == len(set(placed)), "a file was assigned to two agents"
    assert len(placed) == r["reviewed"], "assignment count disagrees with the credited count"
    assert r["reviewed"] + r["unreached"] == r["residual"], (
        "reviewed + unreached must equal residual — an unaccounted file is an unaudited "
        "file that nothing reports"
    )


def test_deepening_a_group_never_loses_a_file(repo: Path) -> None:
    """`bulk/` holds 12 files across two subdirectories, so a small `--per-agent` forces the
    splitter to deepen. Every one of them must still be reachable.

    This is the fixture half of the first draft's worst defect: with a shallow tree the
    deepening path never ran, and the assertion that it preserves files proved nothing.
    """
    big = _report(repo, "--budget", "60", "--per-agent", "2")
    placed = {f for a in big["assignments"] for f in a["files"]}
    bulk = {f for f in placed if f.startswith("bulk/")}
    assert len(bulk) == 12, (
        f"deepening dropped bulk files: {len(bulk)} of 12 survived. A split that silently "
        f"deletes is a coverage tool reporting files it never assigned."
    )
    assert big["verdict"] == "Full"


def test_no_agent_is_handed_more_than_it_is_credited(repo: Path) -> None:
    """Assignment is not coverage. Hand an agent exactly the number you count."""
    for per_agent in (1, 2, 3, 25):
        r = _report(repo, "--per-agent", str(per_agent), "--budget", "1")
        for a in r["assignments"]:
            assert len(a["files"]) <= per_agent, (
                f"agent {a['agent']} handed {len(a['files'])} files at --per-agent "
                f"{per_agent}: the dispatch instruction and the arithmetic disagree"
            )


def test_the_mapped_set_is_never_in_the_residual(repo: Path) -> None:
    """The residual is a set difference, so it adds no double-count to `opened <M>`."""
    r = _report(repo)
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "scripts/deploy.sh" not in placed, "a mapped file reached a residual agent"
    assert "Dockerfile" not in placed, "an inline-marker mapped file reached a residual agent"


# --------------------------------------------------------------------------- #
# what counts as mapped
# --------------------------------------------------------------------------- #

def test_a_placeholder_section_binds_nothing_so_its_files_are_residual(repo: Path) -> None:
    """`## <api module>/routes/**/*.py` matches nothing until localized.

    This is the whole of Q-212: 30 of 36 shipped sections are in exactly this shape, so the
    consumer's routes are unowned on a fresh install. If this test ever goes green by the
    routes file being *mapped*, the placeholder predicate has broken open.
    """
    r = _report(repo)
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "api/routes/users.py" in placed, (
        "the placeholder section was treated as binding its glob — a placeholder binds "
        "nothing, and treating it as coverage is the defect this tool exists to end"
    )
    assert r["placeholder_sections"] >= 1


def test_a_mixed_glob_section_binds_its_concrete_globs(repo: Path) -> None:
    """`## `Dockerfile`, `<datajobs Dockerfile>`` binds `Dockerfile` and nothing else.

    A "header contains a `<…>` token" predicate would condemn the whole section. Two shipped
    sections are in this shape, and one of them is `core §Container Build`.
    """
    r = _report(repo)
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "Dockerfile" not in placed, "a mixed-glob section failed to bind its concrete glob"


def test_a_section_with_no_category_token_leaves_its_files_residual(repo: Path) -> None:
    """3-0b class (c): matched, but a category-keyed dispatch cannot route it."""
    r = _report(repo)
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "docs/guide.md" in placed
    assert r["residual_uncategorised"] >= 1, (
        "a section carrying no category token binds files that NO agent can be handed — "
        "counting them as mapped is how a file reads as covered while nobody audits it"
    )


def test_a_concrete_double_star_section_binds_its_direct_child(repo: Path) -> None:
    """The `:(glob)` pathspec, pinned through the shipped resolver rather than beside it.

    `## `svc/**/*.py`` is concrete, so both `svc/main.py` (direct child) and
    `svc/inner/deep.py` must be MAPPED. With a plain pathspec git silently drops the direct
    child, which would put a file a section explicitly covers into the residual — a coverage
    claim wrong in the direction that hides work.
    """
    r = _report(repo)
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "svc/main.py" not in placed, (
        "svc/main.py fell into the residual: the resolver is no longer giving `**` its true "
        "meaning, so a concrete section is failing to bind the files it names"
    )
    assert "svc/inner/deep.py" not in placed


def test_glob_resolution_reaches_a_direct_child(repo: Path) -> None:
    """`git ls-files -- 'api/**/*.py'` drops `api/server.py`; `:(glob)` does not.

    Reproduced before this was written: the plain pathspec returns only the nested file, and
    `'api/routes/**/*.py'` returns nothing at all because `**` will not match an empty
    segment. The shipped resolver uses `:(glob)` for exactly this reason.
    """
    plain = subprocess.run(["git", "ls-files", "--", "api/**/*.py"],
                           cwd=repo, capture_output=True, text=True).stdout.split()
    magic = subprocess.run(["git", "ls-files", "--", ":(glob)api/**/*.py"],
                           cwd=repo, capture_output=True, text=True).stdout.split()
    assert "api/server.py" not in plain, (
        "the plain-pathspec failure this resolver works around has been fixed upstream — "
        "re-derive whether `:(glob)` is still needed before simplifying"
    )
    assert "api/server.py" in magic and "api/routes/users.py" in magic


# --------------------------------------------------------------------------- #
# exclusions
# --------------------------------------------------------------------------- #

def test_the_seeded_example_comment_is_not_read_as_a_real_exclusion(repo: Path) -> None:
    """The installer seeds `## Map coverage exclusions` with a COMMENTED example block.

    Reading `**/migrations/**` out of that comment would silently carve real directories out
    of every fresh install's residual — a coverage hole seeded by the installer itself.
    """
    (repo / "CLAUDE.md").write_text(
        "## Map coverage exclusions\n\n"
        "<!-- Seeded by Sysop — example:\n"
        "       - `api/**` — not real, this is a comment\n"
        "       - `auth/**` — also a comment -->\n",
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "claude")
    r = _report(repo)
    assert r["declared_expected_unmapped"] == 0, (
        f"{r['declared_expected_unmapped']} files read out of a commented-out example block"
    )
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "auth/session.py" in placed


def test_a_declared_exclusion_is_counted_but_still_dispatched(repo: Path) -> None:
    """`## Map coverage exclusions` scopes the Step 2a coverage AUDIT, never dispatch.

    `WORKFLOW.md` § 6.1: *"it does not change the review/scan manifest and is not a
    review-exclusion knob"*; `security-audit/SKILL.md`: *"not a scan-exclusion mechanism"*.
    Phase 139 settled that reading. A first cut of Step 3-0c subtracted the list from the
    residual anyway — which is dispatch — so a listed path got no agent, and the phase's own
    record had cited that very contract as the reason it rejected a *different* use of the
    list. The round caught the contradiction.

    So: counted, reported, and still handed to an agent.
    """
    (repo / "CLAUDE.md").write_text(
        "## Map coverage exclusions\n\n- `auth/**` — reviewed at the gateway\n",
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "claude")
    r = _report(repo)
    assert r["declared_expected_unmapped"] >= 1, "the declared exclusion was not counted"
    placed = {f for a in r["assignments"] for f in a["files"]}
    assert "auth/session.py" in placed, (
        "a coverage-exclusion entry removed a file from DISPATCH. That list scopes the Step 2a "
        "map-coverage audit only — subtracting it here silently leaves a consumer-declared "
        "path with no auditor, which is the reading Phase 139 settled against"
    )


def test_prose_that_disclaims_an_exclusion_does_not_declare_one(repo: Path) -> None:
    """The round's sharpest input: a bullet saying a path is NOT excluded excluded it.

    Reproduced on the first cut: a bullet reading "Note: we deliberately do NOT exclude
    api/** or auth/** - they are security-critical" removed the API server, a SQL route and
    the auth module from dispatch, and the report said `Full`. Two independent defects stacked: the
    parse harvested every backticked token from every list item, and the residual subtracted
    the result. Both are fixed; this pins the parse half.
    """
    (repo / "CLAUDE.md").write_text(
        "## Map coverage exclusions\n\n"
        "- `vendor/**` — third-party, reviewed upstream\n"
        "- Note: we deliberately do NOT exclude `api/**` or `auth/**` — security-critical\n"
        "\n### A subsection, which must also terminate the list\n\n"
        "- `everything/**` — from an unrelated subsection\n",
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "claude")
    r = _report(repo)
    assert r["declared_expected_unmapped"] == 0, (
        "a prose bullet's incidental backticks, or a `###` subsection's globs, were read as "
        "declarations — only a list item LEADING with a backticked glob declares one"
    )
    placed = {f for a in r["assignments"] for f in a["files"]}
    for f in ("api/server.py", "api/routes/users.py", "auth/session.py"):
        assert f in placed, f"{f} was dropped from dispatch by prose that disclaims excluding it"


def test_a_fenced_example_is_never_read_as_a_declaration(repo: Path) -> None:
    """Fenced blocks are examples, not instructions — in both files this tool parses.

    `WORKFLOW.md` ships fenced *templates* for consumers to copy, including whole
    `## <globs> — <Name>` section skeletons. The round showed an authoring note containing a
    fenced section skeleton for `**` made every file in the repo read as mapped:
    residual 0, verdict `Full`.
    """
    (repo / "CLAUDE.md").write_text(
        "## Map coverage exclusions\n\n"
        "```\n- `**` — WRONG, this is an example of what not to write\n```\n",
        encoding="utf-8")
    mp = repo / ".claude" / "security_map.md"
    mp.write_text(mp.read_text(encoding="utf-8")
                  + "\n\n## Authoring note\n\nCopy this skeleton:\n\n"
                    "```\n## `**` — Everything In My Repo\n\n**Check:**\n"
                    "- **A03 Injection**: x\n\n**Skip:** A01\n```\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fenced")
    r = _report(repo)
    assert r["declared_expected_unmapped"] == 0, "a fenced example was read as an exclusion"
    assert r["residual"] > 0, (
        "a fenced section skeleton was parsed as a live map section, so everything read as "
        "mapped and the residual emptied — a coverage tool reporting Full over an audit "
        "nobody performed"
    )


# --------------------------------------------------------------------------- #
# ranking and the budget
# --------------------------------------------------------------------------- #

def test_the_consumer_s_files_are_never_dropped_before_sysop_s(tmp_path: Path) -> None:
    """The ranking is the point, and a stray `sorted()` silently undid it once.

    Build a repo where Sysop's own footprint dominates the residual — which is the real
    shape: 78 of 90 residual files on a fresh four-pack install — then squeeze the budget to
    one agent. Every consumer file must still be reached.
    """
    r = tmp_path / "c"
    (r / ".claude" / "semgrep").mkdir(parents=True)
    (r / "app").mkdir()
    (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    vendor = []
    for i in range(40):
        p = f".claude/semgrep/rule{i:02d}.yaml"
        (r / p).write_text("rules: []\n", encoding="utf-8")
        vendor.append(p)
    consumer = []
    for i in range(3):
        p = f"app/mod{i}.py"
        (r / p).write_text("x = 1\n", encoding="utf-8")
        consumer.append(p)
    (r / ".claude" / "sysop.lock").write_text(
        json.dumps({"version": 1, "managed_paths": vendor + [".claude/security_map.md"]}),
        encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "f")

    rep = _report(r, "--budget", "1", "--per-agent", "5")
    assert rep["verdict"] == "Sampled", "the fixture must actually bind the budget"
    placed = {f for a in rep["assignments"] for f in a["files"]}
    missing = [c for c in consumer if c not in placed]
    assert not missing, (
        f"consumer files dropped while Sysop's own were kept: {missing}. The consumer-first "
        f"ranking is the only thing standing between a binding budget and an audit that "
        f"spends itself entirely on the installer's output."
    )
    assert rep["unreached_consumer"] == 0
    assert rep["unreached_vendor"] > 0

    # The budget number must be derived from the SAME ranked packing the real call uses. A
    # draft simulated an UNRANKED pack — a different question — and the mutation that drops
    # the ranking survived a whole battery, because the small fixture's vendor set was too
    # thin for ranked and unranked packing to diverge. Here the vendor set is 40 of 43
    # residual files, which is the real proportion on a fresh install, and they diverge.
    needed = rep["agents_needed_for_full"]
    assert needed, "Full reported unreachable on a fixture with no oversized group"
    at = _report(r, "--budget", str(needed), "--per-agent", "5")
    assert at["verdict"] == "Full", (
        f"named {needed} agents; running at that budget reported {at['verdict']} "
        f"({at['reviewed']}/{at['residual']}) — the simulation is not packing the way the "
        f"real call packs"
    )
    below = _report(r, "--budget", str(needed - 1), "--per-agent", "5")
    assert below["verdict"] == "Sampled", (
        f"{needed} is an overcount — {needed - 1} already reaches Full"
    )

    # END TO END, through the CLI. An earlier version pinned only `_budget_for_full`'s
    # internal `pack(..., vendor)` call; dropping `vendor` at `build()`'s CALL SITE moved the
    # same defect one line and became invisible to every test. The number a reader acts on is
    # the one the CLI prints, so that is the one under test.
    for pa in (3, 5, 9):
        rep2 = _report(r, "--budget", "1", "--per-agent", str(pa))
        n2 = rep2["agents_needed_for_full"]
        if not n2:
            continue
        got = _report(r, "--budget", str(n2), "--per-agent", str(pa))
        assert got["verdict"] == "Full", (
            f"--per-agent {pa}: CLI named {n2} agents and running at {n2} reported "
            f"{got['verdict']} ({got['reviewed']}/{got['residual']})"
        )


def test_sysop_s_own_files_are_counted_not_excluded(repo: Path) -> None:
    """Auto-excluding the shipped tool's own code from the audit it ships is a smell."""
    r = _report(repo)
    assert r["residual_vendor"] + r["residual_consumer"] == r["residual"]
    assert r["declared_expected_unmapped"] == 0, "no exclusions are declared in this fixture"


# --------------------------------------------------------------------------- #
# the verdict is arithmetic, and it is checkable
# --------------------------------------------------------------------------- #

def test_agents_needed_for_full_is_both_sufficient_and_tight(repo: Path) -> None:
    """Run at the budget the report names; Full must be reached. Run one below; it must not.

    **Four consecutive versions of this number were false**, and the sufficiency half alone
    caught only two of them:
      1. an UNDERCOUNT, from decoupling the group cap from `--per-agent`;
      2. a wild OVERCOUNT (360 agents for 486 files) while correcting (1) — and an overcount
         is invisible to "run at N and check Full", which is why the tightness half exists;
      3. `ceil(residual / per_agent)`, which is only a LOWER BOUND — bin-packing indivisible
         groups can need more bins than the ceiling, and a real 486-file residual reported
         `Sampled` when run at the 20 it named;
      4. the simulation packing WITHOUT the vendor ranking the real call uses, so it answered
         a different question.
    The number is now derived by running the real packer, and pinned in both directions.
    """
    for per_agent in (1, 2, 3, 5):
        r = _report(repo, "--budget", "1", "--per-agent", str(per_agent))
        needed = r["agents_needed_for_full"]
        assert needed, (
            f"Full reported unreachable at --per-agent {per_agent} on a fixture whose largest "
            f"group is small — the splitter has stopped splitting"
        )
        at = _report(repo, "--budget", str(needed), "--per-agent", str(per_agent))
        assert at["verdict"] == "Full", (
            f"report named {needed} agents at {per_agent} files each; running at that budget "
            f"reported {at['verdict']} ({at['reviewed']}/{at['residual']}). A number a reader "
            f"acts on has to survive being acted on."
        )
        if needed > 1:
            below = _report(repo, "--budget", str(needed - 1), "--per-agent", str(per_agent))
            assert below["verdict"] == "Sampled", (
                f"budget {needed - 1} already reaches Full, so the reported {needed} is an "
                f"OVERCOUNT — the direction a sufficiency-only check cannot see"
            )


def test_full_reported_unreachable_names_the_groups_that_block_it(tmp_path: Path) -> None:
    """When no budget reaches Full, print that — never the upper bound as if it worked.

    The splitter stops at a bounded depth, so a directory nested deeper than that can hold
    more files than one agent's credit and no budget covers it. A draft returned 457 here and
    running at 457 still reported `Sampled`.
    """
    r = tmp_path / "deep"
    deep = r / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    (r / ".claude").mkdir()
    (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    for i in range(9):
        (deep / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "deep")

    rep = _report(r, "--budget", "2", "--per-agent", "2")
    assert rep["verdict"] == "Sampled"
    assert rep["agents_needed_for_full"] == 0, (
        "a budget was named for a residual no budget can cover"
    )
    assert rep["oversized_groups"], "the blocking groups must be named, not just the failure"
    text = _run(r, "--budget", "2", "--per-agent", "2").stdout
    assert "UNREACHABLE" in text and "Raise --per-agent" in text


def test_an_angle_bracket_exclusion_glob_binds_nothing(tmp_path: Path) -> None:
    """The `"<" in glob` guard in the resolver, exercised where it actually bites.

    A first version of this test pointed a placeholder SECTION at a literal `<gen>` directory
    and passed with the guard removed — `build()` skips placeholder sections before the
    resolver is ever reached, so the section path masks the guard completely. The battery
    caught it: a mutation written to be killed by this test survived it.

    The live path is `CLAUDE.md`'s exclusion globs, which reach the same resolver with no
    placeholder skip in front of them. A consumer who writes `<vendor dir>/**` there means "I
    have not filled this in"; without the guard git matches a literal `<vendor dir>` and
    silently carves real files out of the residual.
    """
    r = tmp_path / "angle"
    (r / ".claude").mkdir(parents=True)
    (r / "<vendor dir>").mkdir()
    (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    (r / "<vendor dir>" / "out.py").write_text("x = 1\n", encoding="utf-8")
    (r / "CLAUDE.md").write_text(
        "## Map coverage exclusions\n\n- `<vendor dir>/**` — not filled in yet\n",
        encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "angle")

    # The fixture must be adversarial: git really does match the literal directory.
    matched = subprocess.run(["git", "ls-files", "--", ":(glob)<vendor dir>/**"],
                             cwd=r, capture_output=True, text=True).stdout
    assert "out.py" in matched, "fixture is not adversarial — git matched nothing"

    rep = _report(r)
    assert rep["declared_expected_unmapped"] == 0, (
        "an unlocalized `<…>` exclusion glob matched real files: the resolver stopped "
        "treating angle-bracket globs as placeholders, so a consumer's un-filled-in "
        "placeholder is counted as a real declaration"
    )
    placed = {f for a in rep["assignments"] for f in a["files"]}
    assert "<vendor dir>/out.py" in placed


def test_no_group_can_exceed_one_agent_s_credit(repo: Path) -> None:
    """The cap coupling is what makes the simple arithmetic honest — pin it."""
    for per_agent in (1, 2, 3, 5):
        r = _report(repo, "--budget", "60", "--per-agent", str(per_agent))
        assert r["verdict"] == "Full", (
            f"with a large budget every group must be reachable at --per-agent {per_agent}; "
            "an indivisible group larger than one agent's credit makes Full unreachable "
            "however many agents are added"
        )


def test_the_verdict_comes_from_the_PACKING_not_from_raw_capacity(repo: Path) -> None:
    """`Full` iff the assignments actually cover the residual — never `budget × per_agent`.

    **An earlier version of this test had the defect as its oracle.** It computed
    `expected = "Full" if budget * per_agent >= residual`, which is exactly the mutation an
    independent lens used to break the module: on a real four-pack install `4 × 25 = 100 >= 94`
    prints `Full` while the packing reached 93 of 94, because indivisible groups waste capacity.
    The one test named for this property would have certified the defect it exists to prevent —
    and the property in question is the module's entire reason for existing.

    The oracle is now the assignments themselves, which cannot restate the formula under test.
    """
    for budget, per_agent in ((1, 1), (1, 100), (2, 2), (3, 4), (50, 1), (7, 25)):
        r = _report(repo, "--budget", str(budget), "--per-agent", str(per_agent))
        covered = sum(len(a["files"]) for a in r["assignments"])
        expected = "Full" if covered >= r["residual"] else "Sampled"
        assert r["verdict"] == expected, (
            f"budget {budget} x per-agent {per_agent}: assignments cover {covered} of "
            f"{r['residual']} residual files, so the verdict must be {expected}, got "
            f"{r['verdict']}"
        )
        assert r["reviewed"] == covered, (
            f"`reviewed` ({r['reviewed']}) must be what the agents were actually handed "
            f"({covered}), not a capacity figure"
        )
        # And capacity alone must never be sufficient: if the two disagree, the packing wins.
        capacity = budget * per_agent
        if capacity >= r["residual"] and covered < r["residual"]:
            assert r["verdict"] == "Sampled", (
                "capacity covered the residual but the packing did not, and the verdict "
                "followed capacity — that is the laundering this module exists to prevent"
            )


# --------------------------------------------------------------------------- #
# degrade paths never break the round
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("case", ["no-map", "no-git", "empty-repo"])
def test_every_degrade_path_exits_zero(tmp_path: Path, case: str) -> None:
    """A partial audit beats a refused one — the advisory must never fail the round."""
    r = tmp_path / case
    r.mkdir()
    if case != "no-git":
        _git(r, "init", "-q")
    if case == "empty-repo":
        (r / ".claude").mkdir()
        (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    p = _run(r)
    assert p.returncode == 0, f"{case} exited {p.returncode}: {p.stderr}"
    assert "not assessed" in p.stdout or "residual" in p.stdout


def test_a_damaged_lock_does_not_crash_the_report(repo: Path) -> None:
    (repo / ".claude" / "sysop.lock").write_text("{not json", encoding="utf-8")
    r = _report(repo)
    assert r["status"] == "ok"
    assert r["residual_vendor"] == 0, "an unreadable lock must degrade to 'no vendor known'"


def test_nonsense_flag_values_are_refused(repo: Path) -> None:
    for args in (("--budget", "0"), ("--per-agent", "0"), ("--group-cap", "0")):
        p = _run(repo, *args)
        assert p.returncode == 2, f"{args} was accepted"


# --------------------------------------------------------------------------- #
# the skill actually calls it
# --------------------------------------------------------------------------- #

def test_the_skill_wires_step_3_0c_to_this_script() -> None:
    """A tool nothing invokes is not shipped — Phase 156's five readers, one writer."""
    text = SKILL.read_text(encoding="utf-8")
    assert "### 3-0c." in text, "Step 3-0c is gone — the residual sweep has no invoker"
    assert "sysop/scripts/security_partition.py" in text, (
        "the skill no longer names the script; the step would be prose describing a "
        "mechanism nobody runs"
    )
    assert "**Residual:**" in text, "the Step 5b round header lost its Residual line"


def test_the_step_states_assignment_is_not_coverage() -> None:
    """The reversion guard. This sentence is the whole difference between this mechanism
    and the laundering it replaces, and a draft of it shipped without the distinction."""
    text = SKILL.read_text(encoding="utf-8")
    assert "assignment is not coverage" in text.lower(), (
        "the 'assignment is not coverage' rule was softened out of Step 3-0c — without it "
        "a total partition reads as a completed audit, which is the defect the step exists "
        "to prevent"
    )


# --------------------------------------------------------------------------- #
# the budget simulation must simulate the packing that actually runs
# --------------------------------------------------------------------------- #

def _module():
    """Import the shipped script directly — `_budget_for_full` is a pure function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("security_partition", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_budget_simulation_uses_the_consumer_first_ranking() -> None:
    """`_budget_for_full` must pack the way the real call packs, ranking included.

    A draft simulated an UNRANKED pack, which answers a different question, and the mutation
    that drops the ranking survived **two** batteries: every git-fixture test in this module
    was too small for ranked and unranked packing to diverge, so the assertion was there and
    proved nothing. On the real 486-file corpus they differ by twelve bins (32 vs 20).

    The counterexample below is the minimal one, found by search rather than by construction:
    five groups, twelve files, a credit of three, and two of the groups belonging to Sysop.
    Consumer-first ranking costs a bin here — 5 rather than 4 — and that is the *point*. The
    number has to describe the packing that runs, not a cheaper one nobody performs.
    """
    m = _module()
    groups = {
        "g0": ["g0/f1.py"],
        "g1": ["g1/f2.py", "g1/f3.py", "g1/f4.py"],
        "g2": ["g2/f5.py", "g2/f6.py"],
        "g3": ["g3/f7.py", "g3/f8.py", "g3/f9.py"],
        "g4": ["g4/f10.py", "g4/f11.py", "g4/f12.py"],
    }
    vendor = set(groups["g1"]) | set(groups["g3"])
    total = sum(len(v) for v in groups.values())

    ranked = m._budget_for_full(groups, 3, total, vendor)
    unranked = m._budget_for_full(groups, 3, total, None)
    assert ranked != unranked, (
        "the fixture no longer distinguishes ranked from unranked packing — find a new "
        "counterexample rather than deleting the test, or this guard goes quiet again"
    )
    assert ranked == 5 and unranked == 4

    # And the ranked number is the one that works, for the packing that actually runs.
    packed = m.pack(groups, ranked, vendor)
    assert sum(min(len(a["files"]), 3) for a in packed) >= total, (
        "the simulated budget does not cover the residual under the real packer"
    )
    short = m.pack(groups, ranked - 1, vendor)
    assert sum(min(len(a["files"]), 3) for a in short) < total, (
        f"{ranked} is an overcount — {ranked - 1} bins already cover it"
    )


# --------------------------------------------------------------------------- #
# the human report is a coverage claim too
# --------------------------------------------------------------------------- #

def _human_numbers(text: str) -> dict:
    """Every number the human report states, keyed the way the JSON keys it."""
    out: dict[str, object] = {}
    m = re.search(r"manifest (\d+) · mapped (\d+) · residual (\d+)", text)
    if m:
        out["manifest"], out["mapped"], out["residual"] = (int(g) for g in m.groups())
    m = re.search(r"map sections (\d+) \((\d+) all-placeholder", text)
    if m:
        out["sections"], out["placeholder_sections"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"of the residual, (\d+) are your code and (\d+) are Sysop's", text)
    if m:
        out["residual_consumer"], out["residual_vendor"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"\((\d+)/(\d+) reviewed", text)
    if m:
        out["reviewed"] = int(m.group(1))
    m = re.search(r"unreached: (\d+) of your files, (\d+) of Sysop's", text)
    if m:
        out["unreached_consumer"], out["unreached_vendor"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"--budget (\d+) reaches Full at (\d+) files each", text)
    if m:
        out["agents_needed_for_full"], out["per_agent"] = int(m.group(1)), int(m.group(2))
    out["verdict"] = "Full" if "residual coverage: Full" in text else "Sampled"
    out["_agents"] = len(re.findall(r"^    residual-\d+: (\d+) files", text, re.M))
    out["_agent_sizes"] = [int(x) for x in re.findall(r"^    residual-\d+: (\d+) files",
                                                      text, re.M)]
    return out


def test_the_human_report_states_the_same_numbers_as_the_json(repo: Path) -> None:
    """`render()` was pinned by nothing at all.

    An independent lens replaced the whole function body with a constant string and every
    test passed. Twelve realistic mutations of it survived, each one printing a *different*
    number than `--json` for the same run: `manifest`/`mapped` swapped, `reviewed` inverted to
    `94/93`, the vendor and consumer counts printed the other way round on the very line that
    says whose code went unaudited, the budget and per-agent figures transposed, and three
    lines suppressed entirely.

    The human report is what an operator reads. It is a coverage claim, and it is now held to
    the same standard as the JSON — because nothing else compares the two.
    """
    for budget, per_agent in ((1, 2), (2, 3), (4, 25), (60, 1)):
        args = ("--budget", str(budget), "--per-agent", str(per_agent))
        j = _report(repo, *args)
        h = _human_numbers(_run(repo, *args).stdout)
        for key in ("manifest", "mapped", "residual", "sections", "placeholder_sections",
                    "residual_consumer", "residual_vendor", "verdict", "per_agent",
                    "reviewed", "unreached_consumer", "unreached_vendor",
                    "agents_needed_for_full"):
            if key in h:
                assert h[key] == j[key], (
                    f"budget {budget}/per-agent {per_agent}: the human report says "
                    f"{key}={h[key]} and --json says {j[key]}"
                )
        assert h["_agents"] == len(j["assignments"]), "agent count differs between renderings"
        assert h["_agent_sizes"] == [len(a["files"]) for a in j["assignments"]], (
            "the per-agent file counts differ between renderings — the human line prints a "
            "number the assignment does not carry"
        )


def test_the_human_report_names_every_agent_and_its_groups(repo: Path) -> None:
    """Three render lines could be suppressed wholesale with the suite still green."""
    j = _report(repo, "--budget", "4", "--per-agent", "3")
    h = _run(repo, "--budget", "4", "--per-agent", "3").stdout
    assert "of the residual," in h and "are Sysop's own installed files" in h, (
        "the vendor/consumer breakdown line vanished — it is the line that says whose code "
        "a binding budget will drop"
    )
    for a in j["assignments"]:
        assert f"{a['agent']}: {len(a['files'])} files" in h, f"{a['agent']} unrendered"
        assert a["groups"], "an assignment carries no group provenance"
        assert a["groups"][0] in h, f"{a['agent']}'s groups are unrendered"


def test_every_reported_group_actually_holds_a_file_in_that_assignment(repo: Path) -> None:
    """After truncation the group list must narrow with the file list.

    A survivor left the pre-truncation groups on a truncated assignment, so the report named
    directories the agent was never handed — provenance for work nobody does.
    """
    r = _report(repo, "--budget", "1", "--per-agent", "3")
    for a in r["assignments"]:
        for g in a["groups"]:
            assert any(f == g or f.startswith(g + "/") for f in a["files"]), (
                f"{a['agent']} reports group {g!r} but holds no file from it"
            )


# --------------------------------------------------------------------------- #
# the counters are the argument for the tool's existence
# --------------------------------------------------------------------------- #

def test_the_map_counters_are_exact(repo: Path) -> None:
    """`sections`, `placeholder_sections`, `mapped` and `manifest` were never asserted.

    Four survivors shipped `map sections 6 (25 all-placeholder)`, `31 (6 all-placeholder)`,
    a wrong `mapped`, and a wrong `manifest` — all green. On a fresh install those numbers
    ARE the argument for this tool: "30 of 36 sections bind nothing" is the finding.
    """
    r = _report(repo)
    assert r["sections"] == 5, f"the fixture map has 5 sections, reported {r['sections']}"
    assert r["placeholder_sections"] == 1, (
        f"exactly one fixture section is all-placeholder, reported {r['placeholder_sections']}"
    )
    manifest = subprocess.run(["git", "ls-files"], cwd=repo,
                              capture_output=True, text=True).stdout.split()
    assert r["manifest"] == len(manifest), (
        f"manifest {r['manifest']} != `git ls-files` {len(manifest)}"
    )
    assert r["mapped"] + r["residual"] == r["manifest"], (
        "mapped + residual must partition the manifest exactly"
    )
    assert r["mapped"] == 4, (
        f"4 fixture files are matched by a categorised concrete section "
        f"(scripts/deploy.sh, Dockerfile, svc/main.py, svc/inner/deep.py), reported {r['mapped']}"
    )
    assert r["manifest"] == 22, f"the fixture tracks 22 files, reported {r['manifest']}"
    assert r["residual_uncategorised"] == 1, (
        f"one fixture file is matched only by a section with no category token, reported "
        f"{r['residual_uncategorised']}"
    )


# --------------------------------------------------------------------------- #
# survivors an independent lens found (69 of its 117 mutations walked through)
# --------------------------------------------------------------------------- #

def test_a_mixed_ownership_group_is_not_treated_as_vendor(tmp_path: Path) -> None:
    """The vendor tier is `all(f in vendor)`, and `any(...)` survived a whole battery.

    It survived because the fixture that pins the ranking uses **homogeneous** groups — 40
    pure-vendor, 3 pure-consumer — on which `all` and `any` cannot diverge. A real install has
    mixed directories, and there `any` reclassifies a group holding one Sysop file as entirely
    Sysop's, sending the consumer's own code to the back of the queue.
    """
    r = tmp_path / "mixed"
    (r / ".claude").mkdir(parents=True)
    (r / "app").mkdir()
    (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    # `app/` holds four consumer files and ONE Sysop-installed file.
    consumer = [f"app/m{i}.py" for i in range(4)]
    for f in consumer:
        (r / f).write_text("x = 1\n", encoding="utf-8")
    (r / "app" / "vendored.py").write_text("y = 2\n", encoding="utf-8")
    filler = [f"z{i:02d}.py" for i in range(8)]
    for f in filler:
        (r / f).write_text("z = 3\n", encoding="utf-8")
    (r / ".claude" / "sysop.lock").write_text(
        json.dumps({"version": 1,
                    "managed_paths": ["app/vendored.py", ".claude/security_map.md",
                                      ".claude/sysop.lock"] + filler}),
        encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "mixed")

    rep = _report(r, "--budget", "1", "--per-agent", "4")
    placed = {f for a in rep["assignments"] for f in a["files"]}
    missing = [c for c in consumer if c not in placed]
    assert not missing, (
        f"a group holding four consumer files and one Sysop file was ranked as vendor, so "
        f"{missing} lost their agent. The tier must be `all`, not `any` — a mixed directory "
        f"is the consumer's."
    )


def test_the_colon_inside_bold_check_marker_is_read(tmp_path: Path) -> None:
    """`**Check: A01** — …` ships in `packs/postgres` with NUMBERED sub-items.

    The code lives only inside the bold, so dropping the marker-line fold-back makes that
    whole section uncategorised — its files fall into the residual as if no rule covered them.
    The fixture had no section in this shape, so the mutation survived.
    """
    r = tmp_path / "pgshape"
    (r / ".claude").mkdir(parents=True)
    (r / "migrations").mkdir()
    (r / ".claude" / "security_map.md").write_text(
        "## `migrations/*.sql` — Database Migrations\n\n"
        "**Check: A01** — every migration must be reversible\n\n"
        "1. no destructive DDL without a down step\n"
        "2. no data backfill in a schema migration\n\n"
        "**Skip:** A03\n", encoding="utf-8")
    (r / "migrations" / "001.sql").write_text("SELECT 1;\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "pg")

    rep = _report(r)
    placed = {f for a in rep["assignments"] for f in a["files"]}
    assert "migrations/001.sql" not in placed, (
        "a `**Check: A01**` section (the shipped postgres shape) parsed as carrying no "
        "category, so its file fell into the residual — it is mapped and routable"
    )
    assert rep["residual_uncategorised"] == 0


def test_the_skip_region_is_not_read_as_check_content(tmp_path: Path) -> None:
    """`Skip:` lists categories too. Reading past the boundary makes a skip look like a check.

    Two survivors flipped an uncategorised section to categorised by widening the region —
    a file then reads as owned that no agent can actually be routed to.
    """
    r = tmp_path / "skipbleed"
    (r / ".claude").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / ".claude" / "security_map.md").write_text(
        "## `docs/*.md` — Docs\n\n"
        "**Check:**\n- a rule with no category token at all\n\n"
        "**Skip:** A01, A03, A05 (documentation carries no executable surface)\n",
        encoding="utf-8")
    (r / "docs" / "a.md").write_text("hi\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "s")

    rep = _report(r)
    assert rep["residual_uncategorised"] == 1, (
        "the `Skip:` list's category tokens were read as `Check:` content, so a section with "
        "no routable rule reported one — the file reads as owned and no agent is routed to it"
    )


@pytest.mark.parametrize("case,expect", [
    ("no-map", "no .claude/security_map.md"),
    ("no-git", "not a git work tree"),
    ("empty-repo", "no tracked files"),
])
def test_each_degrade_path_states_its_own_reason(tmp_path: Path, case: str,
                                                 expect: str) -> None:
    """Each degrade names the fact that is actually true of it.

    The earlier version asserted `"not assessed" in stdout OR "residual" in stdout`, which is
    satisfied by almost any output — deleting the empty-repo degrade path entirely left it
    green. And `no-git` never created a map, so it exited at the no-map gate and never
    reached the path it is named for; a non-repo used to report the *empty repo* reason.
    """
    r = tmp_path / case
    r.mkdir()
    if case != "no-git":
        _git(r, "init", "-q")
    if case != "no-map":
        (r / ".claude").mkdir()
        (r / ".claude" / "security_map.md").write_text(MAP_CONCRETE, encoding="utf-8")
    p = _run(r)
    assert p.returncode == 0, f"{case} exited {p.returncode}: {p.stderr}"
    assert "not assessed" in p.stdout, f"{case} did not degrade: {p.stdout[:200]}"
    assert expect in p.stdout, (
        f"{case} degraded with the wrong reason — expected {expect!r}, got: {p.stdout[:250]}"
    )


@pytest.mark.parametrize("lock", ["null", "[1,2,3]", '"a string"', "123", "true",
                                  "{not json", '{"managed_paths": "not-a-list"}',
                                  '{"managed_paths": [1, 2, null]}'])
def test_no_lock_shape_crashes_the_report(repo: Path, lock: str) -> None:
    """The docstring promises every degrade exits 0. Five valid-JSON shapes exited 2.

    `data.get(...)` sat outside the `try`, so a lock that was valid JSON but not an object
    crashed — while a lock that was not JSON at all exited 0. `install.sh`'s `lock_field()`
    was hardened against this exact pair in Phase 148, and its comment names it verbatim.
    """
    (repo / ".claude" / "sysop.lock").write_text(lock, encoding="utf-8")
    p = _run(repo)
    assert p.returncode == 0, f"lock {lock!r} exited {p.returncode}: {p.stderr[:200]}"
    assert "residual" in p.stdout


@pytest.mark.parametrize("target", ["security_map.md", "CLAUDE.md"])
def test_an_unreadable_input_degrades_rather_than_crashing(repo: Path, target: str) -> None:
    """Invalid UTF-8 in either parsed file exited 2 with a traceback."""
    path = repo / ".claude" / target if target == "security_map.md" else repo / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")
    p = _run(repo)
    assert p.returncode == 0, f"{target} with invalid UTF-8 exited {p.returncode}"


def test_group_cap_is_honoured_when_given(repo: Path) -> None:
    """`--group-cap` could be made inert with the whole suite green."""
    loose = _report(repo, "--budget", "4", "--per-agent", "25", "--group-cap", "25")
    tight = _report(repo, "--budget", "4", "--per-agent", "25", "--group-cap", "2")
    assert tight["residual_groups"] > loose["residual_groups"], (
        f"--group-cap 2 produced {tight['residual_groups']} groups and --group-cap 25 "
        f"produced {loose['residual_groups']} — the flag is inert"
    )


def test_the_shipped_defaults_agree_with_every_document_that_cites_them() -> None:
    """Pin the AGREEMENT, never the literal values.

    A lens found the defaults could be changed with nothing going red. The obvious fix — assert
    `(4, 25)` — was tried and is wrong: it turns every legitimate retune into a red suite, and
    the battery's own over-strictness control caught it as a **false kill** on the next run.
    What is actually defective is a default that disagrees with the documents quoting it, and
    three do. So the guard derives both sides and compares them; retune freely, update the docs
    with it.
    """
    m = _module()
    shipped = {"budget": m.DEFAULT_BUDGET, "per_agent": m.DEFAULT_PER_AGENT}
    assert all(isinstance(v, int) and v >= 1 for v in shipped.values())

    helptext = _run(ROOT, "--help").stdout
    for flag, key in (("--budget", "budget"), ("--per-agent", "per_agent")):
        assert f"default {shipped[key]}" in helptext, (
            f"{flag}'s --help text no longer states the shipped default {shipped[key]}"
        )

    workflow = (ROOT / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")
    row = next(ln for ln in workflow.split("\n") if ln.startswith("| `security_partition.py`"))
    assert "--budget" in row and "--per-agent" in row, (
        "the § 8.4 row no longer names the two flags whose defaults this pins"
    )


def test_git_pathspec_glob_semantics_hold_on_this_machine(repo: Path) -> None:
    """An ENVIRONMENT PROBE, not a guard on this module — it invokes git, never the script.

    Kept deliberately and labelled, because `resolve_glob`'s use of `:(glob)` is justified by
    git's default-pathspec behaviour, and if git ever changed that the justification would be
    stale. A lens correctly noted this test would pass with `security_partition.py` deleted;
    `test_a_concrete_double_star_section_binds_its_direct_child` is the one that guards the
    module.
    """
    plain = subprocess.run(["git", "ls-files", "--", "svc/**/*.py"],
                           cwd=repo, capture_output=True, text=True).stdout.split()
    magic = subprocess.run(["git", "ls-files", "--", ":(glob)svc/**/*.py"],
                           cwd=repo, capture_output=True, text=True).stdout.split()
    assert "svc/main.py" not in plain, (
        "git's default pathspec now matches direct children — re-derive whether `:(glob)` is "
        "still needed, and update `Q-302`, which is filed on this behaviour"
    )
    assert {"svc/main.py", "svc/inner/deep.py"} <= set(magic)


def _mkrepo(root: Path, files: dict, lock_managed: list | None = None,
            mapdoc: str | None = None) -> Path:
    """A git repo with exactly these files, a map, and a lock."""
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "security_map.md").write_text(mapdoc or MAP_CONCRETE, encoding="utf-8")
    (root / ".claude" / "sysop.lock").write_text(
        json.dumps({"version": 1, "managed_paths": lock_managed or []}), encoding="utf-8")
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "f")
    return root


def test_wasted_capacity_does_not_become_a_full_verdict(tmp_path: Path) -> None:
    """Three indivisible 3-file groups, two agents crediting 5 each: capacity 10 ≥ 9, and the
    packing still reaches only 8.

    This is the configuration the earlier verdict test lacked. Without it, "capacity covers the
    residual" and "the packing covers the residual" never disagree on the fixture, so the
    mutation that reads the verdict off raw capacity survives — and that mutation is the exact
    laundering this module exists to prevent.
    """
    # `.claude/*` is mapped here on purpose, so the residual is exactly the nine app files
    # and the capacity arithmetic below is not muddied by the fixture's own config files.
    r = _mkrepo(tmp_path / "waste", {
        f"{g}/f{i}.py": "x = 1\n" for g in ("ga", "gb", "gc") for i in range(3)
    }, mapdoc=("## `.claude/*` — Sysop config\n\n**Check:**\n"
               "- **A05 Misconfiguration**: config hygiene\n\n**Skip:** A01\n"))
    rep = _report(r, "--budget", "2", "--per-agent", "5")
    covered = sum(len(a["files"]) for a in rep["assignments"])
    assert rep["residual"] == 9 and 2 * 5 >= rep["residual"], "fixture no longer discriminates"
    assert covered < rep["residual"], (
        f"fixture no longer wastes capacity (covered {covered} of {rep['residual']})"
    )
    assert rep["verdict"] == "Sampled", (
        f"capacity was {2 * 5} against a residual of {rep['residual']}, but the packing "
        f"reached {covered}. Reporting `Full` here is the laundering the module docstring "
        f"says this file exists to prevent."
    )


def test_the_cli_budget_number_accounts_for_the_ranking(tmp_path: Path) -> None:
    """End-to-end on the minimal case where ranked and unranked packing need different bins.

    Five groups, twelve files, a credit of three, two groups Sysop's: ranked needs 5 bins,
    unranked 4. The unit test pins `_budget_for_full`'s internal call; this pins the number the
    **CLI prints**, which is the one a reader acts on — dropping the ranking at `build()`'s call
    site moved the same defect one line and became invisible.
    """
    vendor = [f"g1/f{i}.py" for i in range(3)] + [f"g3/f{i}.py" for i in range(3)]
    files = {"g0/f0.py": "x\n"}
    for g, n in (("g1", 3), ("g2", 2), ("g3", 3), ("g4", 3)):
        for i in range(n):
            files[f"{g}/f{i}.py"] = "x\n"
    r = _mkrepo(tmp_path / "rank", files, lock_managed=vendor + [".claude/sysop.lock"])
    rep = _report(r, "--budget", "1", "--per-agent", "3")
    needed = rep["agents_needed_for_full"]
    assert needed, "Full unreachable on a fixture with no oversized group"
    at = _report(r, "--budget", str(needed), "--per-agent", "3")
    assert at["verdict"] == "Full", (
        f"CLI named {needed} agents; running at {needed} reported {at['verdict']} "
        f"({at['reviewed']}/{at['residual']}) — the budget simulation is not packing the way "
        f"the real call packs"
    )
    below = _report(r, "--budget", str(needed - 1), "--per-agent", "3")
    assert below["verdict"] == "Sampled", f"{needed} is an overcount"


def test_a_mixed_group_outranks_a_pure_vendor_one(tmp_path: Path) -> None:
    """`all` vs `any` on the vendor tier, on a fixture where they actually diverge.

    `app/` holds four consumer files and one Sysop file; `other/` is pure consumer. Under `all`
    both are consumer-tier and `app/` (equal size, earlier name) is packed first, so its four
    consumer files survive a one-agent budget. Under `any`, `app/` is reclassified as Sysop's
    and goes last — its four consumer files are dropped for `other/`'s.
    """
    files = {f"app/m{i}.py": "x\n" for i in range(4)}
    files["app/vendored.py"] = "y\n"
    files.update({f"other/n{i}.py": "z\n" for i in range(5)})
    r = _mkrepo(tmp_path / "tier", files,
                lock_managed=["app/vendored.py", ".claude/sysop.lock", ".claude/security_map.md"])
    rep = _report(r, "--budget", "1", "--per-agent", "5")
    placed = {f for a in rep["assignments"] for f in a["files"]}
    missing = [f"app/m{i}.py" for i in range(4) if f"app/m{i}.py" not in placed]
    assert not missing, (
        f"{missing} lost their agent: a directory holding four consumer files and one Sysop "
        f"file was ranked as Sysop's. The tier must be `all`, not `any` — a mixed directory "
        f"belongs to the consumer."
    )


def test_skip_bullets_are_not_read_as_check_bullets(tmp_path: Path) -> None:
    """A `Skip:` region with BULLETED categories — the shape that makes the boundary matter.

    An earlier fixture put the skip list on the marker line, where `_token_of` never looks, so
    widening the region changed nothing and the mutation survived.
    """
    r = _mkrepo(tmp_path / "skipb", {"docs/a.md": "hi\n"}, mapdoc=(
        "## `docs/*.md` — Docs\n\n"
        "**Check:**\n- a rule with no category token at all\n\n"
        "**Skip:**\n- **A01 Access Control**: docs carry no executable surface\n"
        "- **A03 Injection**: not applicable\n"))
    rep = _report(r)
    assert rep["residual_uncategorised"] == 1, (
        "the `Skip:` bullets' categories were read as `Check:` content, so a section with no "
        "routable rule reported one — its file reads as owned and no agent is routed to it"
    )


def test_a_subsection_heading_ends_the_exclusions_list(tmp_path: Path) -> None:
    """`### ` must terminate the section — and the fixture's subsection glob must MATCH files.

    An earlier version used a glob (`everything/**`) that matched nothing, so harvesting it
    changed no count and the narrowed-terminator mutation survived.
    """
    r = _mkrepo(tmp_path / "sub", {
        "keep/a.py": "x\n", "keep/b.py": "y\n", "vendor/c.py": "z\n"})
    (r / "CLAUDE.md").write_text(
        "## Map coverage exclusions\n\n- `vendor/**` — third-party\n\n"
        "### Notes for maintainers\n\n- `keep/**` — this is NOT an exclusion\n",
        encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c")
    rep = _report(r)
    assert rep["declared_expected_unmapped"] == 1, (
        f"expected only `vendor/**` (1 file) to be declared, got "
        f"{rep['declared_expected_unmapped']} — a `###` subsection's globs were harvested"
    )


def test_the_binary_search_agrees_with_an_exhaustive_reference() -> None:
    """The fast path must return exactly what a linear walk would.

    `_budget_for_full` was a linear walk calling `pack` at every step — cubic, and a review
    lens timed it at ~4 minutes on an ordinary 20k-file repo and ~27 minutes at 42k, all to
    produce one advisory number. It is now a binary search, which is only correct if coverage
    is monotone in the budget. That was measured (4,000 random group sets, zero violations)
    rather than assumed, and this pins the consequence: the answer never changes.
    """
    m = _module()
    rng = __import__("random").Random(20260826)
    for _ in range(150):
        groups, vendor, fid = {}, set(), 0
        for gi in range(rng.randint(2, 8)):
            name, fs = f"g{gi}", []
            for _ in range(rng.randint(1, 6)):
                fid += 1
                fs.append(f"{name}/f{fid}.py")
            groups[name] = fs
            if rng.random() < 0.4:
                vendor.update(fs)
        total = sum(len(v) for v in groups.values())
        per_agent = rng.randint(1, 5)

        fast = m._budget_for_full(groups, per_agent, total, vendor)
        # Exhaustive reference: the smallest budget whose packing actually covers.
        ref = 0
        for b in range(1, len(groups) + 1):
            packed = m.pack(groups, b, vendor)
            if sum(min(len(a["files"]), per_agent) for a in packed) >= total:
                ref = b
                break
        assert fast == ref, (
            f"binary search returned {fast}, exhaustive reference {ref}, for "
            f"{ {k: len(v) for k, v in groups.items()} } at per_agent={per_agent}"
        )


def test_an_uncoverable_residual_returns_zero_not_a_budget() -> None:
    """A group larger than one agent's credit makes `Full` unreachable at any budget."""
    m = _module()
    groups = {"big": [f"big/f{i}.py" for i in range(10)], "small": ["small/a.py"]}
    assert m._budget_for_full(groups, 3, 11, set()) == 0, (
        "a residual no budget can cover must report 0 (rendered UNREACHABLE), never the "
        "group count dressed up as an achievable budget"
    )
