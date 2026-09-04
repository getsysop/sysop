"""`Q-294` — the per-commit public-history scan, EXECUTED.

Runbook step 5 walks a published repo's history. Until `Q-294` it read only
CONTENT (`git grep`) and NAMES (`git ls-tree`), so the commit HEADER was outside
every pass the project has — and 16 published commits carried a private author
address, clean at every cut for five weeks.

WHY THIS MODULE EXISTS RATHER THAN MORE PROSE GUARDS. The arm was first written
as a fence in the runbook, pinned by regexes over that markdown block. An
independent battery walked **13 of 18** mutations through those guards, because a
regex over prose cannot distinguish `git log -1 … "$sha"` from `git log … HEAD`,
a live line from a commented one, or `-vcx` from `-vcxF`. The same guards
false-killed three legal edits — a line continuation, retitling the step, and an
earlier step cross-referencing it — which is the direction that gets a correct
guard deleted instead of fixed. So the arm moved into
`tools/scan_public_history.sh`, where the question "does it work" is answered by
running it against a repository whose answer is known.

Running it is not incidental here. The extracted script's FIRST version had two
defects that no amount of reading would have found: `[ "$h" -gt 0 ] && fail=1`
exits under `set -e` when the test is false, and `grep -vxF` exits 1 on a CLEAN
commit, which `pipefail` promoted into killing the scan before it reached a
single leaking commit — a leak gate failing open, silently, on good input.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = REPO_ROOT / "tools" / "scan_public_history.sh"
RATIFIED = "wade@gdpquery.ai"
GITHUB = "noreply@github.com"


def _scan_available():
    # tools/ is stripped from the mirror; this module ships. Skip rather than
    # error there, the discipline every mirror-aware module here follows.
    if not SCAN.is_file():
        pytest.skip("tools/ is absent — sterilized mirror; the scan is maintainer-side")


def _repo(tmp_path, commits):
    """Build a repo whose commit identities are exactly `commits`."""
    r = tmp_path / "clone"
    r.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    }
    def git(*a, **kw):
        return subprocess.run(["git", "-C", str(r), *a], env={**env, **kw.pop("extra", {})},
                              check=True, capture_output=True, encoding="utf-8")
    git("init", "-q", "-b", "main")
    for i, (an, ae, cn, ce) in enumerate(commits):
        (r / f"f{i}.txt").write_text(f"body {i}\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--no-gpg-sign", "-m", f"commit {i}", extra={
            "GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae,
            "GIT_COMMITTER_NAME": cn, "GIT_COMMITTER_EMAIL": ce,
        })
    return r


def _run(clone):
    p = subprocess.run(["bash", str(SCAN), str(clone)],
                       capture_output=True, encoding="utf-8")
    rows = [l for l in p.stdout.splitlines() if l and l[0] in "0123456789abcdef"]
    # FIELD match, not a suffix match. Phase 233 appends an `ACCEPTED(...)` /
    # `** NEW ... **` marker AFTER `header:N`, so `endswith("header:0")` silently
    # reclassified every annotated-but-clean row as flagged. It survived only
    # because these fixtures never produce a content finding.
    flagged = [l for l in rows if not re.search(r"\bheader:0\b", l)]
    return p, rows, flagged


CLEAN = ("Wade Petty", RATIFIED, "GitHub", GITHUB)
LEAK = ("wade-cms", "wade@cedarmountainsystems.com", "GitHub", GITHUB)


def test_a_clean_history_passes_and_scans_every_commit(tmp_path):
    """The fail-open case, which the first version got wrong.

    `grep -vxF` exits 1 when a commit is clean. With `pipefail` and `set -e` that
    killed the scan on commit one — zero rows printed, zero commits examined. A
    gate that dies on good input reports clean forever, so this asserts the ROW
    COUNT, not just the exit status.
    """
    _scan_available()
    p, rows, flagged = _run(_repo(tmp_path, [CLEAN] * 5))
    assert p.returncode == 0, f"clean history rejected:\n{p.stdout}{p.stderr}"
    assert len(rows) == 5, (
        f"scanned {len(rows)} of 5 commits — it exited early on a clean commit, "
        f"which is the fail-open shape:\n{p.stdout}{p.stderr}"
    )
    assert not flagged


def test_a_leaking_commit_is_found_and_the_scan_exits_non_zero(tmp_path):
    _scan_available()
    p, rows, flagged = _run(_repo(tmp_path, [CLEAN, LEAK, CLEAN]))
    assert len(rows) == 3, f"did not scan all 3 commits:\n{p.stdout}"
    assert len(flagged) == 1, f"expected exactly 1 flagged commit:\n{p.stdout}"
    assert p.returncode == 1, "a leaking history must exit non-zero"


def test_the_leak_is_found_wherever_it_sits_in_the_walk(tmp_path):
    """Not just at the tip.

    `Q-294` was missed by checking the tip and generalising to the history. A
    scan keyed to `HEAD` rather than to each `$sha` reproduces that exactly, and
    passes a tip-clean repo with a leak two commits back.
    """
    _scan_available()
    for label, history in (
        ("leak at the tip", [CLEAN, CLEAN, LEAK]),
        ("leak in the middle", [CLEAN, LEAK, CLEAN]),
        ("leak at the root", [LEAK, CLEAN, CLEAN]),
    ):
        p, rows, flagged = _run(_repo(tmp_path / label.replace(" ", "_"), history))
        assert len(flagged) == 1 and p.returncode == 1, (
            f"{label}: not detected — the scan is not per-commit:\n{p.stdout}"
        )


def test_the_committer_half_is_scanned_not_only_the_author(tmp_path):
    """GitHub sets the committer on a squash-merge; both halves ship."""
    _scan_available()
    committer_only = ("Wade Petty", RATIFIED, "Wade Petty", "wade@cedarmountainsystems.com")
    p, rows, flagged = _run(_repo(tmp_path, [committer_only]))
    assert len(flagged) == 1 and p.returncode == 1, (
        f"a committer-only leak passed; the arm reads %ae but not %ce:\n{p.stdout}"
    )


def test_the_allow_list_is_whole_line_not_substring(tmp_path):
    """An address CONTAINING an allowed one must not pass.

    Without `-x` the allow-list matches substrings, so a lookalike domain is
    accepted. This is battery row `A3`, which survived the prose guards because
    one of them named `grep -vc` in its own disjunction.
    """
    _scan_available()
    lookalike = ("Wade Petty", f"{RATIFIED}.attacker.example", "GitHub", GITHUB)
    p, rows, flagged = _run(_repo(tmp_path, [lookalike]))
    assert len(flagged) == 1 and p.returncode == 1, (
        f"a superstring of the allowed address passed the allow-list:\n{p.stdout}"
    )


def test_github_squash_committer_is_allowed_so_the_scan_is_not_all_noise(tmp_path):
    """The over-strictness direction.

    Every squash-merged commit has `noreply@github.com` as committer. If that is
    not allowed the scan flags all of them, is read as noise, and gets deleted —
    which is how a correct guard dies.
    """
    _scan_available()
    p, rows, flagged = _run(_repo(tmp_path, [CLEAN] * 3))
    assert not flagged, (
        f"GitHub's squash committer is being flagged; the scan would report every "
        f"merged commit as a finding:\n{p.stdout}"
    )


def test_the_allow_list_is_derived_from_the_cut_script_not_hardcoded(tmp_path):
    """Move the ratified identity and the scan must move with it.

    Otherwise the two drift, the scan starts flagging every legitimate commit,
    and it gets deleted as noise. Verified by pointing the script at a modified
    source of truth rather than by reading it.
    """
    _scan_available()
    fake = tmp_path / "cut.sh"
    # The token list here is DELIBERATELY not the real one. This module ships, and
    # Pass 1a scans every shipped file for those literals — planting them here put
    # blocked identifiers into the public tree. It passed locally and reddened CI,
    # because `_shipped_files()` derives from `git ls-files` and this file was
    # still untracked: a NEW shipping file is invisible to the leak gate until it
    # is staged. The scan under test does not care what the tokens are.
    fake.write_text(
        "P1A='some-private-token|another-token'\n"
        'IDENTITY_EMAIL="someone@example.org"\n',
        encoding="utf-8",
    )
    clone = _repo(tmp_path, [("X", "someone@example.org", "GitHub", GITHUB)])
    p = subprocess.run(["bash", str(SCAN), str(clone), str(fake)],
                       capture_output=True, encoding="utf-8")
    assert p.returncode == 0, (
        "the scan did not honour the identity declared in the source of truth it "
        f"was pointed at — it is hardcoded:\n{p.stdout}{p.stderr}"
    )


def test_the_scan_refuses_rather_than_passing_when_it_cannot_derive(tmp_path):
    """Fail CLOSED. An underivable allow-list must stop the scan, not empty it."""
    _scan_available()
    empty = tmp_path / "cut.sh"
    empty.write_text("# no declarations here\n", encoding="utf-8")
    clone = _repo(tmp_path, [LEAK])
    p = subprocess.run(["bash", str(SCAN), str(clone), str(empty)],
                       capture_output=True, encoding="utf-8")
    assert p.returncode == 2, (
        f"expected a refusal (2), got {p.returncode} — an underivable allow-list "
        f"must not degrade into a passing scan:\n{p.stdout}{p.stderr}"
    )
    assert "refusing" in (p.stdout + p.stderr)


# ── Q-300: the gate stops firing on the accepted baseline (Phase 233) ────────
#
# It used to `exit 1` on ANY header finding. 16 published commits carry a private
# address (`Q-294`, accepted) and are immutable, so it exited 1 forever and the
# exit code carried no information -- the operator separated a new leak from the
# baseline by hand-counting rows against a number held in prose, which is exactly
# what extracting this script existed to stop.
#
# These tests exist to prove the fix did not simply turn the gate OFF. Each one
# drives the real script.

ACCEPT_LIST = REPO_ROOT / "tools" / "public_history_accepted.txt"


def _run_accept(clone, accept_text, tmp_path):
    acc = tmp_path / "accepted.txt"
    acc.write_text(accept_text, encoding="utf-8")
    return subprocess.run(
        ["bash", str(SCAN), str(clone)], capture_output=True, encoding="utf-8",
        env={**os.environ, "ACCEPT_FILE": str(acc)},
    )


def _shas(clone):
    return subprocess.run(["git", "-C", str(clone), "rev-list", "HEAD"],
                          capture_output=True, encoding="utf-8").stdout.split()


def test_an_accepted_header_finding_no_longer_gates(tmp_path):
    """The defect itself: a dirty-but-adjudicated commit must not fail the cut."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK])
    sha = _shas(clone)[0]

    p = _run_accept(clone, f"# test\nheader {sha}   # accepted\n", tmp_path)

    assert p.returncode == 0, f"an accepted finding still gated\n{p.stdout}\n{p.stderr}"
    assert re.search(r"ACCEPTED\s*\(header\)", p.stdout), p.stdout
    assert re.search(r"NEW:content=0,(names=0,)?header=0", p.stdout), p.stdout


def test_an_unlisted_header_finding_still_gates(tmp_path):
    """**The non-vacuity twin, and the whole point of the phase.** Without this,
    the test above is satisfied by a script that accepts everything."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK])

    p = _run_accept(clone, "# nothing adjudicated\n", tmp_path)

    assert p.returncode == 1, f"a NEW leak did not gate\n{p.stdout}"
    assert "** NEW header finding **" in p.stdout, p.stdout
    assert re.search(r"NEW:content=0,(names=0,)?header=1", p.stdout), p.stdout


def test_accepting_one_commit_does_not_accept_another(tmp_path):
    """A per-SHA list, not a switch. The commit adjudicated is the commit
    exempted; the next leak is still a leak."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK, CLEAN, LEAK])
    dirty = [sha for sha in _shas(clone)
             if subprocess.run(
                 ["git", "-C", str(clone), "log", "-1", "--format=%ae", sha],
                 capture_output=True, encoding="utf-8").stdout.strip() != RATIFIED]
    assert len(dirty) == 2, f"fixture does not have two dirty commits: {dirty}"

    p = _run_accept(clone, f"header {dirty[0]}\n", tmp_path)

    assert p.returncode == 1, f"the unlisted sibling leak was not caught\n{p.stdout}"
    assert re.search(r"ACCEPTED\s*\(header\)", p.stdout), p.stdout
    assert "** NEW header finding **" in p.stdout, p.stdout
    assert re.search(r"NEW:content=0,(names=0,)?header=1", p.stdout), p.stdout


def test_a_content_acceptance_does_not_exempt_a_header_leak(tmp_path):
    """**The two arms are two lists.** They were adjudicated separately, on
    different dates, for different reasons -- 15 content commits accepted
    2026-07-31, 16 header commits accepted via `Q-294`. A SHA accepted for a
    `PHASE_LOG.md` line must not thereby exempt a private address in the same
    commit's header."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK])
    sha = _shas(clone)[0]

    p = _run_accept(clone, f"content {sha}\n", tmp_path)   # wrong arm, deliberately

    assert p.returncode == 1, f"a content acceptance exempted a HEADER finding\n{p.stdout}"
    assert "** NEW header finding **" in p.stdout, p.stdout


def test_a_missing_accept_list_refuses_rather_than_passing(tmp_path):
    """Fail closed. An absent list means the gate cannot know what is
    adjudicated, and a leak gate that passes when it cannot tell is worse than no
    gate -- a shape this script's own history has already paid for once."""
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    p = subprocess.run(
        ["bash", str(SCAN), str(clone)], capture_output=True, encoding="utf-8",
        env={**os.environ, "ACCEPT_FILE": str(tmp_path / "nope.txt")},
    )
    assert p.returncode == 2, p.stdout
    assert "no accepted-findings list" in p.stderr, p.stderr


def test_the_stale_report_is_silent_on_an_unrelated_history(tmp_path):
    """Run against any other clone -- a fixture, a fork, the tester mirror --
    every shipped entry is absent, and an unscoped report is 31 lines of noise.
    That is how an operator learns to skip the one line that matters."""
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    p = subprocess.run(
        ["bash", str(SCAN), str(clone)], capture_output=True, encoding="utf-8",
        env={**os.environ, "ACCEPT_FILE": str(ACCEPT_LIST)},
    )
    assert p.returncode == 0, p.stdout
    assert "stale entry" not in p.stderr, (
        f"the stale report fired against a history the list does not describe\n{p.stderr}"
    )


def test_the_shipped_accept_list_is_shas_only():
    """The list must never grow a token or a path. It exempts NAMED COMMITS; a
    pattern would exempt content wherever it appears, which is the failure this
    gate exists to catch. Also pins the two arm names the script greps for."""
    if not ACCEPT_LIST.is_file():
        pytest.skip("tools/ is absent — sterilized mirror; the list is maintainer-side")
    seen = {"content": 0, "names": 0, "header": 0}
    for ln in ACCEPT_LIST.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        arm, _, rest = ln.partition(" ")
        assert arm in seen, f"unknown arm in accept list: {ln!r}"
        sha = rest.split("#")[0].strip()
        assert re.fullmatch(r"[0-9a-f]{40}", sha), (
            f"accept-list entry is not a full SHA: {ln!r}"
        )
        seen[arm] += 1
    assert seen == {"content": 16, "names": 0, "header": 16}, (
        f"the adjudicated set changed: {seen}. Entries are appended ONLY on an "
        "explicit adjudication -- adding one to make a red run green is the "
        "single edit that defeats this gate. The 16th content entry is the "
        "tag-only commit Phase 233's round surfaced by widening the walk to "
        "`--all --tags`; `names` starts empty because the real history has no "
        "filename findings, and that arm exists so a future one cannot pass."
    )


def test_an_unlisted_CONTENT_finding_gates_too(tmp_path):
    """**Battery survivor `C2-content-arm-stops-gating`, closed.**

    The content arm was REPORT-ONLY before this phase, which is why the 15
    accepted commits could live in it. That also meant a brand-new content leak
    printed `content:1` in a column already carrying fifteen non-zero rows --
    visible in principle, invisible in practice. Phase 233 made it gate on
    UNLISTED findings, and reverting that left every guard green because nothing
    here had ever produced a content finding at all.
    """
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    # A Pass-1a token in file CONTENT — derived from the cut script, not restated,
    # for the same reason the scan derives its own token list.
    p1a = re.search(r"^P1A='(.*)'$", (REPO_ROOT / "tools" / "cut_public_release.sh")
                    .read_text(encoding="utf-8"), re.M)
    assert p1a, "no Pass 1a token list in the cut script"
    token = p1a.group(1).split("|")[0]
    (clone / "leak.md").write_text(f"a reference to {token} in content\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(clone), "commit", "-q", "--no-gpg-sign", "-m", "content leak"],
        check=True, capture_output=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
             "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
             "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_AUTHOR_NAME": "Wade Petty", "GIT_AUTHOR_EMAIL": RATIFIED,
             "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": GITHUB},
    )

    p = _run_accept(clone, "# nothing adjudicated\n", tmp_path)

    assert p.returncode == 1, f"a NEW content leak did not gate\n{p.stdout}"
    assert "** NEW content finding **" in p.stdout, p.stdout
    assert re.search(r"NEW:content=1,(names=0,)?header=0", p.stdout), p.stdout


def test_an_accepted_CONTENT_finding_does_not_gate(tmp_path):
    """The twin. Without it the test above is satisfied by a script that gates on
    every content finding, which is the permanently-red state `Q-300` fixed."""
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    p1a = re.search(r"^P1A='(.*)'$", (REPO_ROOT / "tools" / "cut_public_release.sh")
                    .read_text(encoding="utf-8"), re.M)
    token = p1a.group(1).split("|")[0]
    (clone / "leak.md").write_text(f"a reference to {token} in content\n", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Wade Petty", "GIT_AUTHOR_EMAIL": RATIFIED,
           "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": GITHUB}
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-q", "--no-gpg-sign",
                    "-m", "content leak"], check=True, capture_output=True, env=env)
    sha = _shas(clone)[0]

    p = _run_accept(clone, f"content {sha}\n", tmp_path)

    assert p.returncode == 0, f"an adjudicated content finding still gated\n{p.stdout}"
    assert re.search(r"ACCEPTED\s*\(content\)", p.stdout), p.stdout
    assert re.search(r"NEW:content=0,(names=0,)?header=0", p.stdout), p.stdout


def test_a_commit_reachable_only_from_a_tag_is_scanned(tmp_path):
    """**Round finding (MEDIUM, execute lens), closed.**

    The walk was `rev-list HEAD`, so anything reachable only from a tag was never
    scanned and the gate exited 0 over it. Sysop publishes release tags on purpose
    -- `install.sh --ref <tag>` (Phase 111) is the documented pinning mechanism --
    so a tag is a published ref, not scratch.

    This was not hypothetical: widening the walk on the REAL published history
    surfaced a 31st commit, reachable only from `v0.1.0`, that no cut had ever
    scanned.
    """
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "private@example.com",
           "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": "private@example.com"}
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "--detach"],
                   check=True, capture_output=True)
    (clone / "orphan.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-q", "--no-gpg-sign",
                    "-m", "tag-only leak"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(clone), "tag", "v9.9"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "main"],
                   check=True, capture_output=True)

    # The precondition: the leak must be invisible to the OLD walk, or this
    # fixture proves nothing about the widening.
    head_only = subprocess.run(["git", "-C", str(clone), "rev-list", "--count", "HEAD"],
                               capture_output=True, encoding="utf-8").stdout.strip()
    all_refs = subprocess.run(
        ["git", "-C", str(clone), "rev-list", "--count", "--all", "--tags"],
        capture_output=True, encoding="utf-8").stdout.strip()
    assert int(all_refs) > int(head_only), (
        f"fixture is wrong: the tagged commit is reachable from HEAD ({head_only} vs {all_refs})"
    )

    p = _run_accept(clone, "# nothing adjudicated\n", tmp_path)

    assert p.returncode == 1, (
        f"a private address on a tag-only commit passed the gate.\n{p.stdout}"
    )
    assert "** NEW header finding **" in p.stdout, p.stdout


def test_an_unlisted_FILENAME_finding_gates_too(tmp_path):
    """**Round finding (MEDIUM, execute lens), closed.**

    The `names:` column counted matches and gated nothing, so a file literally
    named after a private token passed the cut at exit 0. That is verbatim the
    argument this phase used to promote the content arm -- *visible in principle,
    invisible in practice* -- not applied to the column beside it.
    """
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    p1a = re.search(r"^P1A='(.*)'$", (REPO_ROOT / "tools" / "cut_public_release.sh")
                    .read_text(encoding="utf-8"), re.M)
    # A token with NO SPACE: the first draft took `split("|")[0]` and hyphenated it,
    # which does not match the alternation it came from — the fixture then produced
    # `names:0` and would have passed against a gate that never fires.
    token = next(t for t in p1a.group(1).split("|") if " " not in t)
    (clone / f"{token}-internal.md").write_text("nothing secret inside\n", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Wade Petty", "GIT_AUTHOR_EMAIL": RATIFIED,
           "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": GITHUB}
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-q", "--no-gpg-sign",
                    "-m", "filename leak"], check=True, capture_output=True, env=env)

    p = _run_accept(clone, "# nothing adjudicated\n", tmp_path)

    assert p.returncode == 1, (
        f"a private token in a FILENAME passed the cut.\n{p.stdout}"
    )
    assert "** NEW filename finding **" in p.stdout, p.stdout


# ── Round findings (guards lens): behaviour-changing survivors, closed ────────
#
# The author battery reported 18/18. An independent lens wrote 75 mutations and
# 13 behaviour-changing ones walked the guards. These are the scan-side members.

def test_a_commit_with_BOTH_arms_dirty_reports_both(tmp_path):
    """Survivors E10/E11. No fixture had ever produced a header AND a content
    finding on ONE commit, so the marker assembly -- `mark="${mark}  ..."` -- was
    free to drop the header half when the content branch stopped appending."""
    _scan_available()
    clone = _repo(tmp_path, [CLEAN])
    p1a = re.search(r"^P1A='(.*)'$", (REPO_ROOT / "tools" / "cut_public_release.sh")
                    .read_text(encoding="utf-8"), re.M)
    token = next(t for t in p1a.group(1).split("|") if " " not in t)
    (clone / "leak.md").write_text(f"content mentions {token}\n", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "private@example.com",
           "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": "private@example.com"}
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-q", "--no-gpg-sign",
                    "-m", "both arms"], check=True, capture_output=True, env=env)

    p = _run_accept(clone, "# nothing adjudicated\n", tmp_path)

    assert p.returncode == 1, p.stdout
    assert "** NEW header finding **" in p.stdout, (
        f"the header half of a both-arms commit was dropped.\n{p.stdout}"
    )
    assert "** NEW content finding **" in p.stdout, p.stdout
    assert re.search(r"NEW:content=1,names=0,header=1", p.stdout), p.stdout


def test_the_accepted_counts_are_reported_not_just_the_new_ones(tmp_path):
    """Survivors E13/E15/E17. `NEW:` was asserted everywhere; `accepted:` nowhere,
    so those counters could be frozen at 0 or swapped between arms and stay green.
    They are not cosmetic: the stale-entry report is gated on `acc_* > 0`, so a
    frozen counter silences it too."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK, LEAK, CLEAN])
    dirty = [sha for sha in _shas(clone)
             if subprocess.run(
                 ["git", "-C", str(clone), "log", "-1", "--format=%ae", sha],
                 capture_output=True, encoding="utf-8").stdout.strip() != RATIFIED]
    assert len(dirty) == 2, dirty

    p = _run_accept(clone, "".join(f"header {s}\n" for s in dirty), tmp_path)

    assert p.returncode == 0, p.stdout
    assert re.search(r"accepted:content=0,names=0,header=2", p.stdout), (
        "the accepted-header count is wrong or frozen — and the stale-entry "
        f"report keys on it.\n{p.stdout}"
    )


def test_a_stale_accepted_entry_is_reported_when_the_list_does_apply(tmp_path):
    """Survivor E20 — the POSITIVE twin. `test_the_stale_report_is_silent_on_an
    _unrelated_history` asserts only silence, so deleting the report wholesale
    stayed green: a guard with one direction is half a guard."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK])
    sha = _shas(clone)[0]
    ghost = "0" * 40

    p = _run_accept(clone, f"header {sha}\nheader {ghost}\n", tmp_path)

    assert p.returncode == 0, p.stdout
    assert "stale entry" in p.stderr, (
        "an accepted SHA absent from this history was not reported, on a run "
        f"where the list demonstrably DOES apply.\n{p.stderr}"
    )
    assert ghost in p.stderr, p.stderr


def test_an_accept_entry_may_carry_a_trailing_comment(tmp_path):
    """Survivor E25. The shipped list uses `<arm> <sha>   # <why>` -- every entry
    carries its adjudication reason -- but no test drove that shape through the
    script's `sed`, so loosening the hex class stayed green."""
    _scan_available()
    clone = _repo(tmp_path, [LEAK])
    sha = _shas(clone)[0]

    p = _run_accept(clone, f"header {sha}   # 2026-08-26  adjudicated, see Q-294\n", tmp_path)

    assert p.returncode == 0, (
        f"an entry with a trailing comment was not parsed.\n{p.stdout}\n{p.stderr}"
    )
    assert re.search(r"ACCEPTED\s*\(header\)", p.stdout), p.stdout


# ── Q-392: the MESSAGE arm ──────────────────────────────────────────────────
#
# The header arm above reads `%ae%n%ce` — the two EMAIL fields. Every other pass
# in the cut reads a tree or a path. So nothing read `%s` or `%B`, and the
# filing reproduced the consequence: a commit whose MESSAGE carried a Pass-1a
# token, a maintainer-side path and an absolute home path scanned `content:0
# names:0 header:0`, `NEW:0,0,0`, exit 0.
#
# The arm delegates to `tools/scan_message.py` rather than restating six
# patterns here — the two-copies state `Q-256` is about. What stays in the shell
# script is the decision about WHICH commits get scanned (`--all --tags`, bought
# by a round that found a tag-only commit unscanned), so that decision keeps
# living in exactly one place.
#
# The detectors themselves are covered by `tests/test_message_scan_gate.py`.
# What is asserted HERE is the wiring: that the column is computed for every
# commit, that a finding gates, that the arm adjudicates separately from the
# other three, and that an unrunnable scanner refuses rather than reporting a
# clean column it never computed.

CUT_SRC = REPO_ROOT / "tools" / "cut_public_release.sh"


def _leaky_message():
    """A message carrying a real Pass 1a token — DERIVED, never typed.

    **This module SHIPS.** A literal blocked identifier here would be a Pass 1a
    finding in the public tree — the canary becoming the leak, which is the
    first of the two reasons `tests/test_mirror_leak_gate.py`,
    `tests/test_cut_release_gate.py` and `tests/test_message_scan_gate.py` are
    all stripped from the mirror. This module does not need that exclusion
    precisely because it plants nothing it has to type.

    Deriving it from the same `P1A=` assignment the scanner reads has a second
    virtue: the fixture cannot drift from the list it is meant to exercise. A
    token retired upstream retires here in the same edit.
    """
    m = re.search(r"(?m)^P1A='([^']*)'$", CUT_SRC.read_text(encoding="utf-8"))
    assert m, "the Pass 1a source of truth moved; this fixture is now blind"
    token = m.group(1).split("|")[0]
    assert token, "the Pass 1a token list is empty; the fixture would plant nothing"
    return f"snapshot (private def5678)\n\nPorted the {token} pipeline.\n"


def _repo_msgs(tmp_path, messages, ident=None):
    """A repo whose commit MESSAGES are exactly `messages`.

    `_repo` above fixes the message at `commit {i}` and varies the identity;
    this varies the message and fixes the identity to the ratified one, so a
    message finding cannot be confused with a header finding.
    """
    an, ae, cn, ce = ident or ("Wade Petty", RATIFIED, "GitHub", GITHUB)
    r = tmp_path / "clone"
    r.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    }

    def git(*a, **kw):
        return subprocess.run(["git", "-C", str(r), *a],
                              env={**env, **kw.pop("extra", {})},
                              check=True, capture_output=True, encoding="utf-8")

    git("init", "-q", "-b", "main")
    for i, msg in enumerate(messages):
        (r / f"f{i}.txt").write_text(f"body {i}\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--no-gpg-sign", "-m", msg, extra={
            "GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae,
            "GIT_COMMITTER_NAME": cn, "GIT_COMMITTER_EMAIL": ce,
        })
    return r


def _msg_counts(stdout):
    return [int(m) for m in re.findall(r"\bmessage:(\d+)\b", stdout)]


def test_a_clean_history_gets_a_message_column_on_every_commit(tmp_path):
    """Vacuity control, and it is the one that matters.

    An arm that never runs reports the same thing as an arm that runs and finds
    nothing. `grep -vxF` exiting 1 on a clean commit is how the HEADER arm
    failed open here once already — the scan died on commit one, printed no
    rows, and read as green. So this asserts a computed column PER COMMIT, not
    just a zero in the summary.
    """
    _scan_available()
    p, rows, _ = _run(_repo_msgs(tmp_path, ["clean snapshot"] * 4))
    assert p.returncode == 0, f"{p.stdout}{p.stderr}"
    assert len(rows) == 4, f"scanned {len(rows)} of 4 commits:\n{p.stdout}"
    assert _msg_counts(p.stdout) == [0, 0, 0, 0], (
        f"the message column was not computed for every commit:\n{p.stdout}"
    )
    assert "message=0" in p.stdout, f"the summary carries no message arm:\n{p.stdout}"


def test_a_leaking_commit_MESSAGE_is_found_and_the_scan_exits_non_zero(tmp_path):
    """`Q-392`'s own reproduction, inverted into an assertion."""
    _scan_available()
    p, rows, _ = _run(_repo_msgs(tmp_path, ["clean", _leaky_message(), "clean"]))
    assert len(rows) == 3, f"did not scan all 3 commits:\n{p.stdout}"
    assert p.returncode == 1, (
        "a message carrying a blocked identifier and a maintainer-side path did "
        f"not gate — this is the exit 0 the filing reproduced:\n{p.stdout}{p.stderr}"
    )
    assert sorted(_msg_counts(p.stdout))[-1] >= 1, (
        f"the leaking commit reported no findings at all:\n{p.stdout}"
    )
    assert "NEW:content=0,names=0,header=0,message=1" in p.stdout, (
        f"the summary did not attribute the finding to the message arm:\n{p.stdout}"
    )


def test_the_github_squash_trailer_does_not_flag_published_history(tmp_path):
    """The measured false-positive class, pinned so nobody re-mints it.

    The arm's first run against the real published repo returned 33 findings
    across 35 commits, every one of them GitHub's own `(#N)` squash trailer — a
    number that resolves perfectly in the repo being scanned. A gate wrong 33
    times out of 35 does not get tightened, it gets switched off.
    """
    _scan_available()
    p, rows, _ = _run(_repo_msgs(tmp_path, [
        "sysop public snapshot (private d769247) (#2)",
        "sysop public snapshot (private 3954031) (#1)",
    ]))
    assert p.returncode == 0, (
        "GitHub's squash trailer gated the scan. Every published commit carries "
        f"one:\n{p.stdout}{p.stderr}"
    )
    assert _msg_counts(p.stdout) == [0, 0], p.stdout


def test_a_message_finding_is_adjudicated_on_its_own_arm(tmp_path):
    """A SHA accepted for a message leak is not thereby accepted for a header
    one, and vice versa. That is the whole reason these are separate lists.
    """
    _scan_available()
    clone = _repo_msgs(tmp_path, [_leaky_message()], ident=LEAK)
    sha = _shas(clone)[0]

    # Accepted for the message only: the HEADER leak must still gate.
    p = _run_accept(clone, f"message {sha}\n", tmp_path)
    assert p.returncode == 1, (
        f"a message acceptance silently covered a header leak:\n{p.stdout}{p.stderr}"
    )
    # BOTH markers, on the SAME row. Asserting only the message marker cannot see
    # the accumulation bug: the arms build one `mark` string, the first ASSIGNS and
    # the rest APPEND, so an arm written to assign silently erases its neighbour's
    # marker while its own stays present. That is the defect this phase shipped and
    # removed, and the author battery walked it straight back through a test that
    # only looked for one of the two.
    row = next(l for l in p.stdout.splitlines() if l.startswith(sha[:8]))
    assert "ACCEPTED(message)" in row and "** NEW header finding **" in row, (
        "the per-commit row names only one of the two arms that fired. An arm that "
        f"assigns `mark` rather than appending erases its neighbour:\n{row}"
    )

    # Accepted for the header only: the MESSAGE leak must still gate.
    p = _run_accept(clone, f"header {sha}\n", tmp_path)
    assert p.returncode == 1, (
        f"a header acceptance silently covered a message leak:\n{p.stdout}{p.stderr}"
    )
    assert "** NEW message finding **" in p.stdout, p.stdout

    # Both adjudicated: green, and reported as accepted rather than absent.
    p = _run_accept(clone, f"header {sha}\nmessage {sha}\n", tmp_path)
    assert p.returncode == 0, f"{p.stdout}{p.stderr}"
    assert "message=1" in p.stdout, p.stdout


def test_every_arm_appends_its_marker_rather_than_assigning(tmp_path):
    """Marker accumulation, across THREE arms rather than one pair.

    The arms build a single `mark` string: the first assigns and every later one
    appends. The phase found and fixed that at the *message* arm, and a round
    then reverted it at the *content* arm and watched the guards stay green —
    the header marker vanished from the row while the summary counts stayed
    right. Pinning one pair cannot see a third arm doing it.
    """
    _scan_available()
    clone = _repo_msgs(tmp_path, [_leaky_message()], ident=LEAK)
    sha = _shas(clone)[0]
    p, rows, _ = _run(clone)
    row = next(l for l in rows if l.startswith(sha[:8]))
    # This commit trips the header arm (a private address) and the message arm
    # (a Pass 1a token in the message). Both markers must survive on one row.
    assert row.count("**") >= 4, (
        "fewer than two arms are named on a row that trips two — an arm is "
        f"assigning `mark` instead of appending to it:\n{row}"
    )
    assert "NEW header finding" in row and "NEW message finding" in row, (
        f"a marker was overwritten by a later arm:\n{row}"
    )


def test_the_scan_refuses_when_the_message_scanner_cannot_run(tmp_path):
    """Fail CLOSED, the same rule the allow-list derivation follows.

    A missing or unrunnable scanner must stop the scan, not silently leave the
    message column uncomputed — which would report exactly what a clean history
    reports.
    """
    _scan_available()
    clone = _repo_msgs(tmp_path, [_leaky_message()])
    # A copy of the script whose scanner path cannot resolve.
    stray = tmp_path / "scan_copy.sh"
    stray.write_text(
        SCAN.read_text(encoding="utf-8").replace(
            'SCAN_MSG="$SRC/tools/scan_message.py"',
            'SCAN_MSG="$SRC/tools/no_such_scanner.py"',
        ),
        encoding="utf-8",
    )
    # The copy sits outside the repo, so `$SRC` no longer resolves to it. Both
    # of the script's OTHER derivations are handed their real sources here on
    # purpose: without that the copy refuses over the Pass 1a list or the accept
    # file, exit 2 for a reason that has nothing to do with this test — a test
    # that passes for the wrong reason is not a test.
    p = subprocess.run(
        ["bash", str(stray), str(clone), str(REPO_ROOT / "tools" / "cut_public_release.sh")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "ACCEPT_FILE": str(ACCEPT_LIST)},
    )
    assert p.returncode == 2, (
        f"expected a refusal (2), got {p.returncode} — a missing message scanner "
        f"must not degrade into a passing scan:\n{p.stdout}{p.stderr}"
    )
    assert "no message scanner" in (p.stdout + p.stderr), (
        "the scan refused, but not over the missing scanner — this case is "
        f"passing for the wrong reason:\n{p.stdout}{p.stderr}"
    )


def _scan_with_stub(tmp_path, clone, stub_body):
    """Run the arm against a scanner that EXISTS but misbehaves at runtime.

    The missing-scanner case above is caught by a `[ -f … ]` preflight, so it
    never reaches the two runtime checks — which is why the author battery
    walked both of them through. A stub that exists and then refuses, or exits
    without a SUMMARY, is what exercises them.

    **The stub MUST drain stdin, and the first version did not.** The arm pipes
    one commit's `%B` into the scanner. A stub that exits without reading gives
    `git log` a SIGPIPE, `set -o pipefail` promotes that 141 into the pipeline
    status, and `msg_rc=141` takes the `>= 2` refusal branch — so the test
    reached the wrong branch, false-FAILED on correct code roughly half the time
    under load, and in those runs never exercised the check it is named for.
    Found by a review lens that traced `msg_rc`; reproduced here at 2 of 6.
    """
    stub = tmp_path / "stub_scanner.py"
    stub.write_text(stub_body, encoding="utf-8")
    copy = tmp_path / "scan_copy.sh"
    copy.write_text(
        SCAN.read_text(encoding="utf-8").replace(
            'SCAN_MSG="$SRC/tools/scan_message.py"',
            f'SCAN_MSG="{stub}"',
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(copy), str(clone),
         str(REPO_ROOT / "tools" / "cut_public_release.sh")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "ACCEPT_FILE": str(ACCEPT_LIST)},
    )


def test_a_scanner_that_refuses_at_runtime_halts_the_scan(tmp_path):
    """Exit 2 is a refusal and must stop the walk, not be read as a finding.

    A refusal means the arm could not run. Folding it into the finding count
    would report a leak that was never looked for; ignoring it would report a
    clean message column nobody computed. Both are the fail-open shape this
    file's header is about.
    """
    _scan_available()
    p = _scan_with_stub(tmp_path, _repo_msgs(tmp_path, ["clean"]),
                        "import sys; sys.stdin.read(); sys.exit(2)\n")
    assert p.returncode == 2, (
        f"a scanner refusal did not halt the scan (rc={p.returncode}):\n"
        f"{p.stdout}{p.stderr}"
    )
    assert "could not run" in (p.stdout + p.stderr), f"{p.stdout}{p.stderr}"
    # A SIGPIPE 141 also satisfies `>= 2` and also prints "could not run", so
    # without the stub's `sys.stdin.read()` above this assertion passes for a
    # reason that has nothing to do with a refusal. Pin the code the stub
    # actually returns, so the two are distinguishable.
    assert "scanner could not run" in (p.stdout + p.stderr), f"{p.stdout}{p.stderr}"
    assert "141" not in p.stderr.split("\n")[0], (
        "the halt came from a broken pipe, not the stub's exit 2 — the stub is "
        f"not draining stdin:\n{p.stderr}"
    )


def test_a_scanner_that_prints_no_summary_halts_rather_than_reading_zero(tmp_path):
    """The count is parsed out of the scanner's SUMMARY line.

    No SUMMARY means the parse yields an empty string, and empty read as `0` is
    indistinguishable from a clean commit — a miss and a real zero being the
    same output, which is the class this project keeps finding. It must refuse.
    """
    _scan_available()
    p = _scan_with_stub(tmp_path, _repo_msgs(tmp_path, ["clean"]),
                        "import sys; sys.stdin.read()\nprint('some output with no summary line')\n")
    assert p.returncode == 2, (
        f"a scanner emitting no SUMMARY was read as zero findings (rc={p.returncode}):\n"
        f"{p.stdout}{p.stderr}"
    )
    assert "no SUMMARY" in (p.stdout + p.stderr), f"{p.stdout}{p.stderr}"
