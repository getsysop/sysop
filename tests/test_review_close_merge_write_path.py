"""R2 — `/review-close`'s merge and write path (Steps 4-pre → 4c, 8).

Guards for `Q-233` (shipped prose that executes differently than it reads) and `Q-269`
(one piece of work recorded in `changelog.md` twice).

**Written against the failure mode the previous phase's guard lens demonstrated**, not
just against the defect: every prompt guard in Phase 218 stayed green when the rule was
kept and a countermanding clause was appended beside it. A rule plus its contradiction is
worse than neither, because the agent picks. So the checks here bound a *window* — the
rule and its neighbourhood — rather than asserting a sentence is present somewhere in a
2,000-line file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def flat(skill: str) -> str:
    """Whitespace-collapsed. A line-oriented search cannot see a wrapped sentence, which
    is how a Phase 218 sweep missed five sites it was written to find."""
    return " ".join(skill.split())


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


# ── Q-233 (1) — the continue that opens an editor ───────────────────────────

def test_the_rebase_continue_is_never_prescribed_bare(skill: str):
    """Measured on git 2.50.1: a conflict-resolved `git rebase --continue` invokes the
    editor, an unchanged message does NOT skip it, and with none configured git falls
    back to `vi` — which hangs this harness to its tool timeout. Asserted as *gone*."""
    # Two lookbehinds, because the file legitimately CITES the bare form in order to
    # forbid it — the permission note explains why `Bash(git rebase:*)` cannot cover the
    # safe spelling, and it has to name the unsafe one to do that. A guard that cannot
    # tell a citation from a prescription is the over-strictness that gets guards
    # weakened; `a bare …` is the discriminator, and no instruction reads that way.
    bare = re.findall(
        r"(?<!core\.editor=true )(?<!a bare `)git rebase --continue", skill
    )
    assert not bare, f"{len(bare)} bare `git rebase --continue` site(s) are back"
    assert skill.count("git -c core.editor=true rebase --continue") >= 3


def test_the_exact_allow_rule_exists_because_a_prefix_rule_cannot_cover_it():
    """`-c` is not one of the wrappers the Bash matcher strips, so `Bash(git rebase:*)`
    does not match `git -c … rebase`. The rule has to be exact, and it has to match the
    prescribed string CHARACTER FOR CHARACTER — an exact-match rule is not a prefix."""
    import json
    settings = json.loads(
        (REPO_ROOT / "core" / "companion" / ".claude" / "settings.json").read_text()
    )
    rule = "Bash(git -c core.editor=true rebase --continue)"
    assert rule in settings["permissions"]["allow"], (
        "the seeded allow-list does not authorize the non-interactive continue; the "
        "prescribed command would route to the classifier on every conflict"
    )
    # The rule and the invocation must not drift apart — Phase 152 found rules seeded
    # against invocations that bind none, which is this failure with the halves swapped.
    invocation = rule[len("Bash("):-1]
    assert invocation in SKILL.read_text(encoding="utf-8"), (
        f"the seeded rule authorizes {invocation!r}, which the skill never runs"
    )


# ── Q-233 (2) — a check that could not be measured ──────────────────────────

def test_4a_post_has_a_could_not_measure_arm(skill: str):
    block = _section(skill, "### 4a-post.", "### 4b.")
    flat_block = " ".join(block.split())
    assert "could not be measured is neither a pass nor a failure" in flat_block
    assert "TIMEOUT:" in flat_block, (
        "the arm must name the token the report carries — and it is deliberately the "
        "same token /auto-fix and /auto-judge already emit for this event"
    )


@pytest.mark.parametrize("contradiction", [
    "In practice, a timeout can be reported as a failure and the close continued.",
    "If the command times out, treat it as a pass — the tree merged cleanly.",
    "Simply re-run with a longer timeout and report the second result.",
])
def test_the_could_not_measure_arm_forbids_its_own_contradictions(skill: str, contradiction: str):
    """The window, not the sentence. Each of these is a plausible line a later author
    could append *beside* the rule, leaving every presence-assert green while the arm
    stops meaning anything. The shipped text must already forbid each in terms."""
    block = " ".join(_section(skill, "### 4a-post.", "### 4b.").split())
    forbidden = [
        "Do not silently re-run with a longer timeout and report the second result as the first",
        "Do not classify it as a failure either",
    ]
    for f in forbidden:
        assert f in block, (
            f"the arm no longer forbids {f!r}, so appending {contradiction!r} would be "
            "consistent with what ships"
        )
    # …and it must not itself say the thing it forbids.
    assert "treat it as a pass" not in block.lower()


# ── Q-233 (3) — the loop that iterated once under zsh ───────────────────────

def test_step1c_does_not_word_split_an_unquoted_variable(skill: str):
    """bash word-splits an unquoted expansion; zsh does not (SH_WORD_SPLIT off). Measured
    on the same two-branch repo: the old form emitted 2 warnings under bash and **0**
    under zsh, because the newline-joined string went to `git merge-base` as one ref."""
    block = _section(skill, "### 1c.", "## Step 2")
    assert "for branch in $BRANCHES_TO_MERGE" not in block, (
        "the unquoted `for … in $VAR` loop is back in Step 1c"
    )
    assert "while IFS= read -r branch; do" in block
    # The class, not the instance: no `for X in $Y` anywhere in the skill.
    assert not re.findall(r"^\s*for\s+[A-Za-z_]\w*\s+in\s+\$", skill, re.M)


def test_step1c_makes_an_empty_enumeration_visible(skill: str):
    """A run that enumerated nothing and a run that checked everything and found nothing
    were indistinguishable — silence read as a clean result. That is the half of this
    defect that survives the shell fix, so it is guarded separately."""
    block = _section(skill, "### 1c.", "## Step 2")
    assert 'echo "checked: $branch"' in block
    flat_block = " ".join(block.split())
    # Semantics, not the sentence: zero `checked:` lines must read as "nothing was
    # enumerated", not "everything passed". Control C6 caught the exact-string form
    # reddening on a legal reword.
    assert re.search(r"(No|Zero) `checked:` line", flat_block), (
        "Step 1c no longer tells the reader how to read an absent `checked:` line"
    )
    assert "enumeration was empty" in flat_block


# ── Q-233 (4) — the classifier that knew one signature of four ──────────────

@pytest.mark.parametrize("signature,why", [
    ("does not exist in", "rev resolved, path did not"),
    ("ambiguous argument", "the operand itself was mangled"),
    ("invalid object name", "path resolved, rev did not"),
])
def test_every_measured_git_show_failure_signature_is_routed(skill: str, signature, why):
    """Scoped to the classifier bullet, and deliberately WITHOUT a whole-file fallback.

    The first version fell back to searching the entire skill when its end-anchor was
    missing, and the author battery walked straight through: dropping `ambiguous argument`
    from the classifier left the phrase present at three other sites — including the
    sentence that scopes the prefix advice away from it — so the assertion passed while
    the outcome routed nowhere. A guard whose subject can silently widen to the whole file
    is not a guard.
    """
    bullet = _section(skill, "- **`unreadable`**", "\n\n  **None of the four is `missing`:**")
    flat_bullet = " ".join(bullet.split())
    assert len(flat_bullet) < 4000, (
        "the `unreadable` bullet slice ran away — re-anchor it rather than letting it "
        "grow to swallow the rest of the file"
    )
    assert signature in flat_bullet, (
        f"the `unreadable` classifier does not route {signature!r} ({why}). Note the "
        "phrase may still appear elsewhere in the skill; this asserts it is routed HERE."
    )


def test_the_exit_zero_fail_open_is_named_and_given_a_test(skill: str, flat: str):
    """The worst outcome is not a fatal at all. `git show <path>` — an operand that lost
    its `<rev>:` — exits **0** and prints the newest commit touching that path, whose `+`
    lines can contain `## Test decision`. Verified by execution: rc=0, a `commit <sha>`
    header, and `+## Test decision` in the body. A reader scanning for the record finds
    one, from `main`, not from the branch."""
    assert "Exit `0` with a commit diff instead of a file" in flat
    # A named hazard with no test is advice. The operator needs both halves.
    assert "confirm the operand you sent contained a literal `:`" in flat
    assert "means you read a commit" in flat


def test_the_prefix_advice_is_scoped_to_the_signature_it_fits(flat: str):
    """`ambiguous argument` and `invalid object name` cannot be produced by a prefix
    mistake, so 'check the recorded `body:` value' sends the reader to the one place the
    fault is not. Scoping it is the fix; deleting it would lose advice that is correct
    for the signature it was written for."""
    assert "cannot** be produced by a prefix mistake" in flat


# ── Q-269 — one piece of work, two changelog entries ────────────────────────

def test_the_wide_close_and_the_bugfix_row_are_mutually_exclusive(flat: str):
    """Path B, which the filing does not name: on a close of more than 4 pending-docs the
    Consolidation clause routes EVERY entry's detail to `changelog.md`, and the bugfix row
    then writes the same entry again — two bullets, one entry, one date heading, one
    close. This is the `/auto-fix` and `/auto-judge` shape, so it is the automated path."""
    assert "only when the Consolidation clause did not fire" in flat
    assert "One clause fires or the other does; never both for the same entry." in flat


def test_the_rotation_deduplicates_against_what_is_already_there(flat: str):
    """Path A: a `bugfix` is written to §6 and to `changelog.md` on the close that creates
    it; a later close rotates the §6 line into the same date heading the bullet is already
    under. The rotation is a MOVE, and it must not re-write an entry already recorded."""
    assert "Rotation is a MOVE, and it must not re-write an entry that is already there" in flat
    assert "drop the §6 line instead of copying it" in flat
    # The two formats differ, so a whole-line match would never fire — a dedupe that
    # cannot match is inert while looking present, which is the Phase 200 shape.
    assert "match on the **summary**, not on the whole line" in flat
    assert "would leave this rule inert while looking present" in flat


def test_the_staging_note_still_names_all_three_changelog_writers(flat: str):
    """The dedupe must not be read as reducing the writer count. There are three, and the
    note that says so is what keeps the changelog staged on a run with no bugfix.
    (Phase 222 / Q-279 renamed the target `changelog.md` → `CHANGELOG.md` — one file,
    one case, shared with `/release`; the three-writer rule itself is unchanged.)"""
    assert "Do not stage `CHANGELOG.md` from the routing table alone" in flat
    assert "the **Rotation check** writes it whenever §6 exceeds 8 entries" in flat
    assert "the **Consolidation clause** writes every entry's detail there" in flat


# ── Q-265 — the published branch ────────────────────────────────────────────

def test_the_publication_probe_refuses_an_unsubstituted_placeholder(skill: str):
    """Found by running the command this phase itself wrote.

    `git rev-parse --verify --quiet` exits non-zero and prints nothing both for a ref
    that does not exist and for a name the operator forgot to substitute — so the probe
    reported `(local-only)` for the placeholder, and `(local-only)` selects the in-place
    rebase, which is the arm that damages a published branch. The `case` guard exits 3
    instead. Executed across `/bin/bash` 3.2.57, zsh 5.9 and bash 5.3.9: exit 3 in all
    three unsubstituted, and the SHA with a real branch name written in.
    """
    block = _section(skill, "### 4a. Merge Approved Feature Branches", "### 4a-post.")
    probe = block.index('git rev-parse --verify --quiet "refs/remotes/origin/<branch>"')
    guard = block.index('case "<branch>" in')
    assert guard < probe, (
        "the placeholder guard must precede the probe it protects — after it, the probe "
        "has already answered `(local-only)` and the operator has already rebased"
    )
    assert "exit 3" in block[guard:probe], "the guard does not stop the step"


def test_the_status_derived_body_path_gloss_stays_swept(skill: str):
    """H4, and `Q-021`'s real guard — the sweep had none at all.

    `tasks/<status>/<TASK-ID>.md` is false for every status a claimed task is in: a claim
    never moves the body, there is no `tasks/in_progress/` in any shipped layout, and
    `tasks/schema.md` blesses a FLAT `tasks/` layout, which is why the fix uses the
    `body:` form rather than a hard `tasks/open/` path — one of the entry's own two
    proposed shapes was false for that reason."""
    offenders = []
    for rel in ("core/skills", "core/companion/docs"):
        for f in sorted((REPO_ROOT / rel).rglob("*.md")):
            body = f.read_text(encoding="utf-8")
            for i, line in enumerate(body.splitlines(), 1):
                if "tasks/<status>" in line:
                    offenders.append(f"{f.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, (
        "the `tasks/<status>/` path gloss is back at: " + ", ".join(offenders) +
        ". Resolve the body path from the index entry's `body:` field instead — `status` "
        "predicts the directory for none of the statuses these skills run against."
    )


# ── Q-265, after the round replaced the mechanism ───────────────────────────

def _bullet(block: str, label: str) -> int:
    """Offset of a list item, whatever marker it uses.

    Pinning `- ` made a `-`->`*` reformat go red — over-strict, and over-strict guards
    are the ones maintainers learn to switch off. Caught by this phase's own legal-edit
    control C4.
    """
    m = re.search(r"^\s*[-*]\s+" + re.escape(label), block, re.M)
    assert m, f"no list item labelled {label!r} in this section"
    return m.start()


def _step4a(skill: str) -> str:
    return _section(skill, "### 4a. Merge Approved Feature Branches", "### 4a-post.")


def test_step4a_probes_publication_before_the_merge_it_governs(skill: str):
    """ORDERING, not presence. Phase 218's headline finding was a shape gate stated 81
    lines after the command it gated: an operator in written order did the damage first
    and met the rule afterwards."""
    block = _step4a(skill)
    assert block.index('git rev-parse --verify --quiet "refs/remotes/origin/<branch>"') \
        < block.index("git merge --no-ff -m"), (
        "the publication probe is stated after the merge whose form it selects"
    )


def test_the_published_arm_does_not_rebase_and_the_local_one_does(skill: str):
    """Asserted by PAIRING. Both command strings survive a swap of which label sits above
    which, and the swap IS the defect.

    The published arm must not rebase at all — not even through a throwaway ref. That
    variant was tried and withdrawn by this phase's own round: it keeps the branch ref
    intact but leaves the branch's commits off the merge target, so Step 4c's filter reads
    `rev-list --count <branch> ^HEAD` = 2 and calls a merged branch NOT-MERGED, and Step
    6's `git branch -d` refuses. Measured side by side; `--no-ff` scores 0 and deletes.
    """
    block = _step4a(skill)
    pub = _bullet(block, "**Published**")
    loc = _bullet(block, "**Local-only**")
    assert loc < pub
    loc_body, pub_body = block[loc:pub], block[pub:]
    assert "git rebase" in loc_body and "git merge --ff-only <branch>" in loc_body
    assert "git merge --no-ff -m" in pub_body
    assert "do not rebase it at all" in pub_body
    assert "git rebase" not in pub_body.split("**Why not rebase through a throwaway ref")[0], (
        "the published arm rebases again — that rewrites a ref the remote already has"
    )
    assert "git checkout -B sysop/rebase-tmp" not in block, "the withdrawn mechanism is back"


def test_the_no_ff_merge_carries_its_own_message(skill: str):
    """`git merge` decides on an editor from whether stdin is a terminal, so the same
    command is silent in one context and blocks in another. `-m` removes the question —
    the `--continue` lesson applied to a second verb before it can bite."""
    block = _step4a(skill)
    assert re.search(r"git merge --no-ff(?! -m)", block) is None
    assert "`-m` is not optional" in block


def test_the_withdrawn_mechanism_stays_withdrawn_with_its_reason(skill: str):
    """A rejected design that leaves no trace gets re-proposed. Its reason is two measured
    consequences, and both must survive — without them the note reads as taste."""
    flat_block = " ".join(_step4a(skill).split())
    assert "Why not rebase through a throwaway ref" in flat_block
    assert "withdrawn by this phase's own review round" in flat_block
    assert "= **2**" in flat_block and "NOT-MERGED" in flat_block
    assert "refuses" in flat_block


def test_the_superseded_pr_end_state_is_stated_accurately(flat: str):
    """The first version said the PR stays open and a human closes it. The round found
    Step 6, three steps later, running `git push origin --delete <branch>` on every branch
    this step merged — and deleting a PR's head branch closes it **as unmerged**. The
    honest end state is a closed-not-merged PR for work that shipped, which is worse than
    an open one and is why the comment has to go on before Step 6 runs."""
    assert "closes that PR as unmerged" in flat
    assert "comment on that PR" in flat
    # Scoped to Step 8. A whole-file search passes on the Step 4a prose that merely
    # MENTIONS the row, which is how battery D11 walked through: renaming it to
    # `Superseded PRs (optional):` left the mention intact. Same shape as D16.
    step8 = " ".join(_section(SKILL.read_text(encoding="utf-8"),
                              "## Step 8: Report", "Pending-doc collisions:").split())
    assert "Superseded PRs: <branch #PR" in step8, (
        "Step 8 has no `Superseded PRs:` row — a mention elsewhere is not the row"
    )


# ── the git shape, EXECUTED ─────────────────────────────────────────────────
#
# Lens 1's M7: every other test in this module matches strings in a markdown file, and
# both HIGH findings of the round were invisible to all of them. The two consequences
# that killed the temp-ref mechanism are downstream *git* facts — what Step 4c's filter
# reads, and whether Step 6's `git branch -d` succeeds — so they need a git repo, not a
# regex. This is the test that would have caught it.

def _git(repo, *args, **kw):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                          env=_ISOLATED, **kw)


import os
import subprocess

_ISOLATED = {
    **{k: v for k, v in os.environ.items()
       if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")},
    "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent-home-for-tests",
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


@pytest.fixture
def published_branch(tmp_path):
    """A branch that exists on a real `origin`, with the merge target moved on since."""
    origin, work = tmp_path / "origin", tmp_path / "w"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=_ISOLATED)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True,
                   capture_output=True, env=_ISOLATED)
    (work / "f").write_text("base\n")
    _git(work, "add", "f"); _git(work, "commit", "-qm", "base")
    _git(work, "push", "-q", "origin", "HEAD:main")
    _git(work, "branch", "feat/pub")
    _git(work, "checkout", "-q", "feat/pub")
    (work / "g").write_text("w\n"); _git(work, "add", "g"); _git(work, "commit", "-qm", "w")
    _git(work, "push", "-q", "origin", "feat/pub")
    _git(work, "checkout", "-q", "main")
    (work / "i").write_text("m\n"); _git(work, "add", "i"); _git(work, "commit", "-qm", "moved")
    return work


def test_the_published_arm_leaves_the_branch_mergeable_downstream(published_branch):
    """Run Step 4a's published arm, then the two downstream consumers that the withdrawn
    mechanism broke.

    Step 4c's merged-branch filter is `git rev-list --count "<branch>" "^HEAD"` and treats
    `0` as merged. Step 6 then runs `git branch -d`. Under the temp-ref variant the branch
    scored **2** and `-d` **refused**; under `--no-ff` it scores 0 and deletes. Both are
    asserted here because both are how a real close loses a task's pending-doc and leaves
    a branch behind.
    """
    w = published_branch
    before = _git(w, "rev-parse", "feat/pub").stdout.strip()

    r = _git(w, "merge", "--no-ff", "-m", "merge feat/pub (published — not rebased)", "feat/pub")
    assert r.returncode == 0, r.stderr

    # 1. the branch — and therefore its remote and any PR tracking it — is untouched
    assert _git(w, "rev-parse", "feat/pub").stdout.strip() == before
    assert _git(w, "rev-list", "--count", "--left-right",
                "origin/feat/pub...feat/pub").stdout.split() == ["0", "0"]

    # 2. Step 4c's filter reads it as merged
    assert _git(w, "rev-list", "--count", "feat/pub", "^HEAD").stdout.strip() == "0", (
        "Step 4c's merged-branch filter would classify this branch NOT-MERGED — its "
        "pending-doc is held back, its task never flips to done, its lock never drops"
    )

    # 3. Step 6's safe delete succeeds, so the branch is not left for the next close
    assert _git(w, "branch", "-d", "feat/pub").returncode == 0, (
        "Step 6's `git branch -d` refuses, and the same step forbids `-D`"
    )


def test_the_withdrawn_temp_ref_mechanism_really_did_break_those_two(published_branch):
    """The negative control for the test above — it is only meaningful if the rejected
    mechanism actually fails these assertions. Without this, a `--no-ff` that happened to
    be equivalent would look like a fix."""
    w = published_branch
    _git(w, "checkout", "-q", "-B", "sysop/rebase-tmp", "feat/pub")
    assert _git(w, "rebase", "main").returncode == 0
    _git(w, "checkout", "-q", "main")
    assert _git(w, "merge", "--ff-only", "sysop/rebase-tmp").returncode == 0
    _git(w, "branch", "-D", "sysop/rebase-tmp")

    assert _git(w, "rev-list", "--count", "feat/pub", "^HEAD").stdout.strip() != "0", (
        "the temp-ref mechanism no longer reproduces the NOT-MERGED misread — if that is "
        "genuinely fixed upstream, this control and the withdrawal note both need revisiting"
    )
    assert _git(w, "branch", "-d", "feat/pub").returncode != 0


# ── the sibling sweep (`Q-233`(2)), reinstated by the round ─────────────────
#
# The phase originally DECLINED this sweep, on the claim that /auto-fix and /auto-judge
# "keep TIMEOUT as a distinct token and conflate only at disposition, fail-closed". That
# was measured wrong: it read the envelope-schema lines and not the two the filing cited.
# Both producing agents were told to "treat it as a verify failure", and the very next
# section in each is `Handle verify failure`, whose body makes ONE code edit. So a killed
# command routed a sub-agent into changing working code on evidence that does not exist —
# the exact disposition `/review-close`'s new 4a-post arm forbids in terms.

@pytest.mark.parametrize("skill_name,section", [
    ("auto-fix", "### 4. Handle verify failure"),
    ("auto-judge", "### 5. Handle verify failure"),
])
def test_a_timeout_does_not_route_a_sibling_into_a_code_edit(skill_name, section):
    path = REPO_ROOT / "core" / "skills" / skill_name / "SKILL.md"
    body = path.read_text(encoding="utf-8")
    flat = " ".join(body.split())

    assert "do not treat it as a failure" in flat or "do not treat it as a verify failure" in flat, (
        f"/{skill_name} tells the agent to treat a timeout as a failure again"
    )
    assert "unverified" in flat, (
        f"/{skill_name} no longer names the state a killed command actually leaves"
    )
    # The load-bearing half: it must say to SKIP the fix section, by name. Saying
    # "it's unverified" while leaving the agent pointed at a one-shot code edit is a
    # rule and its contradiction shipping together.
    num = section.split(".")[0].removeprefix("### ")
    assert f"skip § {num} entirely" in flat, (
        f"/{skill_name} names the state but does not route past § {num}, which is the "
        f"section that edits code"
    )
    # …and that section must still exist and still be the code-editing one, or the
    # cross-reference is pointing at nothing.
    assert section in body
    after = body[body.index(section):]
    assert "fix attempt" in after[:1200] or "Make **ONE** fix" in after[:1200], (
        f"{section} in /{skill_name} is no longer the one-shot fix section this rule "
        "routes around — re-derive the reference rather than deleting the assertion"
    )


def test_all_three_surfaces_name_the_unmeasured_state_the_same_way():
    """`/review-close` 4a-post, `/auto-fix` and `/auto-judge` must agree. The phase's
    original claim was that they already did; they agreed on the *token* and disagreed on
    the *disposition*, which is the half that changes what an agent does."""
    rc = " ".join((REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md")
                  .read_text(encoding="utf-8").split())
    assert "TIMEOUT:" in rc
    for name in ("auto-fix", "auto-judge"):
        flat = " ".join((REPO_ROOT / "core" / "skills" / name / "SKILL.md")
                        .read_text(encoding="utf-8").split())
        assert "VERIFY: TIMEOUT" in flat, f"/{name} lost the shared token"
        assert "treat as failure and report" not in flat, (
            f"/{name} still prescribes the conflation in its producing instructions"
        )


def test_the_published_arm_forbids_its_own_simplification(skill: str):
    """D08 from the author battery: appending *"in practice, rebasing the branch in place
    is fine and simpler"* beside the rule left every other guard green.

    A rule and its contradiction shipping together is worse than neither, because the
    agent picks — and here the contradiction is the *shorter, more familiar* instruction,
    so it wins. The shipped text has to refuse the simplification by name."""
    flat_block = " ".join(_step4a(skill).split())
    assert 'Do not "simplify" this arm back to a rebase, in place or through a throwaway ref' in flat_block, (
        "the published arm no longer refuses its own simplification, so a one-sentence "
        "addition can restore the defect with the suite green"
    )


# ── the author battery's third-run survivors ────────────────────────────────

def test_the_published_arm_does_not_also_bless_a_rebase(skill: str):
    """Battery D08, second attempt — and the first attempt is the lesson.

    That fix asserted the *refusal sentence* was present. The mutation appended a
    contradiction beside it, so the refusal stayed intact and the guard stayed green. A
    rule and its contradiction shipping together is worse than neither, because the agent
    picks — and here the contradiction is the shorter, more familiar instruction.

    So this checks the window for approving phrasings. **The list is not exhaustive and
    cannot be:** a prose rule can always be contradicted by a paraphrase no blocklist
    anticipates. It catches the class the battery demonstrated; the limit is recorded here
    rather than implied away.
    """
    window = " ".join(_step4a(skill).split())
    pub = window[window.index("**Published**"):]
    pub = pub[:pub.index("3. **A published branch's own PR")]
    for approving in (
        "rebasing the branch in place is fine",
        "the temp ref is optional",
        "rebase it like any other branch",
        "in place is simpler",
        "either approach works",
    ):
        assert approving.lower() not in pub.lower(), (
            f"the published arm now also blesses a rebase ({approving!r})"
        )


def test_the_ci_workflow_actually_installs_a_sub_floor_interpreter():
    """Battery D03. `test_ci_supplies_the_floor_interpreter` asks whether a sub-3.10
    interpreter was *discovered*, which is true on this machine whatever the workflow
    says — so deleting the CI step is invisible locally and only bites in CI, where the
    result is a silent skip nobody reads. This asserts the workflow file, which is the
    half that can be checked from here."""
    wf = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    m = re.search(r"id: floor-python\s*\n\s*with:\s*\n\s*python-version: '([^']+)'", wf)
    assert m, "the floor-python step is gone or no longer declares a python-version"
    major, minor = (int(x) for x in m.group(1).split(".")[:2])
    assert (major, minor) < (3, 10), (
        f"CI installs Python {m.group(1)} as the floor interpreter, which is not below "
        "3.10 — the guard would then run against modern interpreters only, and pass"
    )
    assert "SYSOP_FLOOR_PYTHONS=${{ steps.floor-python.outputs.python-path }}" in wf, (
        "the workflow no longer hands the floor interpreter to the test module"
    )


def test_the_step4c_heredoc_reports_its_own_exit_status(skill: str):
    """Battery D31. The heredoc rewrites and stages `tasks/index.yml` before it cleans
    locks and markers, so a crash in the tail — a lock path that is a directory raises
    PermissionError, measured — leaves a half-done close whose five report rows silently
    vanish. The validator that runs next passes on the valid index and says nothing."""
    assert "Step 4c heredoc exit (MUST be 0" in " ".join(skill.split()), (
        "nothing checks the consolidation heredoc's exit status, so a crash after the "
        "index rewrite is indistinguishable from a clean run"
    )


def test_a_dangling_lock_symlink_is_reported_as_removed_not_absent(tmp_path):
    """Battery D19b, asserted by EXECUTION rather than by reading the source.

    `Path.exists()` follows symlinks, so a dangling lock symlink reports "already absent"
    while `unlink(missing_ok=True)` really does delete it — a row that claims to report
    what the code did, reporting the opposite. Nothing asserted this until the battery
    walked through the source-level fix.
    """
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    dangling = lock_dir / "TASK-0001.lock"
    dangling.symlink_to(tmp_path / "nowhere")

    # The shipped predicate, lifted verbatim from the heredoc.
    shipped = "(locks_removed if (lock.exists() or lock.is_symlink()) else locks_absent)"
    assert shipped in SKILL.read_text(encoding="utf-8"), (
        "the heredoc's lock-existence test no longer covers symlinks"
    )
    assert not dangling.exists(), "fixture is wrong — the symlink should dangle"
    assert dangling.is_symlink()
    # exists() alone would classify it absent; the shipped form classifies it removed,
    # which is what actually happens one line later.
    assert (dangling.exists() or dangling.is_symlink()) is True
    dangling.unlink(missing_ok=True)
    assert not dangling.is_symlink(), "the unlink really does remove it"


def test_the_timeout_token_has_a_slot_in_the_row_it_is_told_to_write_to(skill: str):
    """Round lens 3, finding 2 — and it is this phase's own defect class, shipped by the
    phase that fixed six instances of it.

    4a-post's new arm says *"Report it on Step 8's `Verification:` line as
    `TIMEOUT: <command>`"*. Step 8's template enumerated exactly three forms —
    `ran on <target>: N commands | ran nothing: why | not reached: why` — and `TIMEOUT`
    occurred **once** in the whole skill, in the arm. A producer with no consumer is the
    same shape as `Q-237`'s consumers with no producer, and nothing looked at both ends.
    """
    step8 = _section(skill, "## Step 8: Report", "Unverified surfaces:")
    assert "TIMEOUT:" in step8, (
        "Step 8's `Verification:` row has no TIMEOUT slot, so the arm that instructs the "
        "agent to write one there is instructing it to write into nothing"
    )
    arm = _section(skill, "### 4a-post.", "### 4b.")
    assert "TIMEOUT:" in arm, "the producing arm no longer names the token"
    # Both ends, in one assertion, so neither can be removed alone.
    assert "UNVERIFIED" in step8.upper(), (
        "the slot exists but no longer says what the state means — a reader folding it "
        "into `ran N commands` is the failure the arm exists to prevent"
    )


# ── round lens 3: guards that were present, ordered, and inert ──────────────

def test_the_placeholder_guard_pattern_actually_matches_a_placeholder(skill: str):
    """Lens 3 F3. The existing guard asserts the `case` exists and that `exit 3` sits
    between it and the probe — never that the pattern matches anything. Changing
    `*"<"*)` to `*"<<<"*)` leaves it present, ordered, and completely inert, and
    `(local-only)` then selects the in-place rebase on an unsubstituted placeholder.

    So run it: extract the shipped `case` and execute it against a placeholder.
    """
    block = _step4a(skill)
    i = block.index('case "<branch>" in')
    j = block.index("esac", i) + len("esac")
    case_src = "\n".join(ln.strip() for ln in block[i:j].split("\n"))
    script = case_src + '\necho "FELL-THROUGH"\n'
    r = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 3, (
        f"the shipped placeholder guard does not refuse an unsubstituted `<branch>` "
        f"(exit {r.returncode}, output {r.stdout.strip()!r}). Present and ordered is not "
        "the same as matching."
    )
    assert "FELL-THROUGH" not in r.stdout

    # …and it must NOT fire once a real branch name is substituted, or every close stops.
    real = subprocess.run(
        ["/bin/bash", "-c", case_src.replace("<branch>", "feat/x") + '\necho "OK"\n'],
        capture_output=True, text=True, timeout=30)
    assert real.returncode == 0 and "OK" in real.stdout, (
        f"the guard fires on a legitimate branch name: {real.stdout!r} {real.stderr!r}"
    )


def test_the_status_gloss_sweep_catches_respellings_and_the_whole_shipped_tree():
    """Lens 3 J1/J2. The first sweep matched the literal `tasks/<status>` under
    `core/skills` and `core/companion/docs` only. Two mutations walked through it: the
    same false gloss written `tasks/{status}/`, and the same gloss placed in
    `core/companion/tasks/README.md` — a file that ships to every consumer and that the
    sweep did not scan."""
    bad = re.compile(r"tasks/[<{\[]status[>}\]]")
    offenders = []
    for root in ("core", "packs", "docs"):
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.md")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if bad.search(line):
                    offenders.append(f"{f.relative_to(REPO_ROOT)}:{i}")
    for f in (REPO_ROOT / "README.md", REPO_ROOT / "install.sh"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line):
                offenders.append(f"{f.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, (
        "a status-derived body-path gloss is back at: " + ", ".join(offenders) +
        ". Resolve the body from the index entry's `body:` field — `status` predicts the "
        "directory for none of the statuses these skills run against, and a flat `tasks/` "
        "layout is valid."
    )


@pytest.mark.parametrize("doc", [
    "core/companion/docs/WORKFLOW.md",
    "core/companion/docs/WORKFLOW_GUIDE.md",
])
def test_the_spec_mirrors_do_not_revert_behind_the_skill(doc):
    """Lens 3 L2/L3. Two guards scanned only `review-close/SKILL.md`, so the human-facing
    guide could go back to a bare `git rebase --continue` — the command the skill calls a
    hang — and `WORKFLOW.md` could narrow the reuse condition back, each with the suite
    green. A spec that contradicts the skill ships two readings."""
    body = (REPO_ROOT / doc).read_text(encoding="utf-8")
    bare = re.findall(r"(?<!core\.editor=true )(?<!a bare `)git rebase --continue", body)
    assert not bare, (
        f"{doc} prescribes a bare `git rebase --continue` ({len(bare)} site(s)) — the "
        "skill prescribes the non-interactive form, and the two must not disagree"
    )
    if "narrower shape" in body:
        flat = " ".join(body.split())
        assert "that the branch does not\nalready contain" in body or \
               "that the branch does not already contain" in flat, (
            f"{doc} has reverted to the pre-widening reuse condition 3"
        )


# ── round lens 3: inversions, which a guard CAN close ───────────────────────
#
# Most of lens 3's 39 survivors are "append a contradiction", which no prose guard fully
# closes and which is filed rather than chased. These are different: each keeps every
# asserted string and reverses a direction, so the assertion is available if you write it.

def test_the_rotation_dedupe_is_not_inverted(flat: str):
    """Lens 3 E1. Flipping the predicate to *"if **no** bullet already carries it → drop
    the §6 line"* keeps every pinned sentence and makes the rule do the opposite: new
    entries dropped, already-recorded ones duplicated. Assert the direction."""
    i = flat.index("Rotation is a MOVE")
    window = flat[i:i + 1400]
    assert "If a bullet already carries it" in window, (
        "the rotation dedupe's condition is no longer 'already present → drop'"
    )
    assert "drop the §6 line instead of copying it" in window
    assert "no bullet already carries it" not in window.lower(), (
        "the dedupe predicate is inverted — it would drop the entries that are NOT yet "
        "recorded and copy in the ones that are"
    )


def test_the_timeout_arm_still_stops(flat: str):
    """Lens 3 B2. `and then stop per item 4` → `and then continue past item 4` removes the
    arm's only consequence while leaving both "Do not …" sentences intact."""
    i = flat.index("could not be measured is neither a pass nor a failure")
    window = flat[i:i + 1600]
    assert "then stop per item 4" in window, (
        "the could-not-measure arm no longer stops the close — with the stop removed it "
        "is a logging instruction, and an unmeasured gate merges"
    )
    assert "continue past item 4" not in window


def test_the_four_git_show_outcomes_keep_their_own_causes(skill: str):
    """Lens 3 D1. The four outcomes can keep their labels and exchange their bodies: the
    `ambiguous argument` bullet gets the rev-does-not-exist cause and vice versa. Every
    membership assertion passes; the classifier now misdiagnoses both."""
    bullet = _section(skill, "- **`unreadable`**", "\n\n  **None of the four is `missing`:**")
    def _cause(sig: str) -> str:
        i = bullet.index(sig)
        return " ".join(bullet[i:bullet.index("\n", i)].split())
    assert "the **operand itself** was mangled" in _cause("ambiguous argument"), (
        "the `ambiguous argument` outcome no longer carries its own cause"
    )
    assert "the **path** resolved but the rev did not exist" in _cause("invalid object name")
    assert "the rev resolved, the path did not" in _cause("does not exist in")


def test_the_allow_rule_is_matched_as_an_exact_rule_not_a_substring(skill: str):
    """Lens 3 A4, the sharpest of its survivors.

    `test_the_exact_allow_rule_exists_because_a_prefix_rule_cannot_cover_it` asserts the
    rule's inner text is a *substring* of the skill — but the rule is an EXACT-match rule,
    so growing the prescribed command (`… --continue --no-edit`) leaves the substring
    present while the rule stops binding. The test's own docstring says it prevents
    exactly that drift.
    """
    import json
    rules = json.loads(
        (REPO_ROOT / "core" / "companion" / ".claude" / "settings.json").read_text()
    )["permissions"]["allow"]
    rule = "Bash(git -c core.editor=true rebase --continue)"
    assert rule in rules
    invocation = rule[len("Bash("):-1]
    # Every prescribed occurrence must END there — an exact rule does not cover a longer
    # command. Backtick-delimited in prose, so the closing backtick is the terminator.
    # A SPACE is not an acceptable terminator — that is precisely the case where the
    # command continues (`… --continue --no-edit`) and the exact rule stops binding. The
    # first version of this assertion allowed one, and the mutation walked through it.
    for m in re.finditer(re.escape(invocation), skill):
        tail = skill[m.end():m.end() + 2]
        ok = tail.startswith("`") or tail.startswith(")`") or tail == "" or tail.startswith("\n")
        assert ok, (
            f"a prescribed invocation continues past the exact-match rule "
            f"({skill[m.start():m.end() + 24]!r}) — an exact rule does not cover a longer "
            "command, so this would route to the classifier on every conflict"
        )


def test_the_orchestrator_disposition_matches_the_agent_instruction():
    """Phase 222 (Q-283): Phase 219 fixed the AGENT instruction (`auto-fix` § 3,
    `auto-judge` § 4) and left the ORCHESTRATOR's batch disposition (§ 4c) reading
    `FAIL or TIMEOUT → failed`, three sections down in the same file. The layer that
    records the outcome must make the same distinction the layer that measures it does:
    TIMEOUT is `unverified`, not failed — and the Opus pass (4d) must gate on a verify
    that actually returned PASS, since an unverified diff is not a verified one."""
    body = (REPO_ROOT / "core" / "skills" / "auto-fix" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(body.split())

    # The conflation must not come back in any spelling of the old line.
    assert "FAIL or TIMEOUT, note the batch as failed" not in flat, (
        "/auto-fix's orchestrator re-acquired the FAIL/TIMEOUT conflation Q-283 filed"
    )
    # The disposition SENTENCE, pinned whole and whitespace-normalized (Phase 168
    # precedent) — the round's VF-1 kept "unverified, not failed" and appended a
    # countermand on the same line, so a token check accepted its own negation.
    assert (
        "If it reports `VERIFY: TIMEOUT`, the batch is **unverified, not failed** "
        "(Phase 222, Q-283): the verify command was killed and returned no verdict"
    ) in flat, (
        "/auto-fix's 4c disposition sentence was altered — if the reword was "
        "deliberate, update this pin in the same commit"
    )
    for countermand in ("note it as failed anyway", "has proved not to matter",
                       "note it as **failed** and continue anyway"):
        assert countermand not in flat, (
            f"4c countermands its own disposition ({countermand!r})"
        )
    # 4d must be gated on both halves — on the OPERATIVE spawn sentence, not only the
    # heading (the round's VF-2 de-gated the spawn sentence while the heading kept
    # the needle) — and Step 5 must carry the Unverified table so the state survives
    # into the run report instead of vanishing at the summary.
    assert "`STATUS: PASS` *and* `VERIFY: PASS`" in body, (
        "/auto-fix 4d lost its VERIFY: PASS gate — an unverified batch would get an "
        "Opus certification pass over a diff no verify ever measured"
    )
    assert (
        "For each batch that reported `STATUS: PASS` **and** `VERIFY: PASS`"
    ) in flat, (
        "/auto-fix 4d's operative spawn sentence is no longer gated on VERIFY: PASS "
        "— the heading alone satisfied the old check (round survivor VF-2)"
    )
    assert "including `VERIFY: TIMEOUT`" not in flat, (
        "4d's spawn sentence explicitly re-admits unverified batches"
    )
    assert "### Unverified (verify timed out" in body, (
        "/auto-fix Step 5 lost the Unverified table — the disposition exists at 4c "
        "but vanishes from the summary a human reads"
    )
