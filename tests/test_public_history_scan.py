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
    flagged = [l for l in rows if not l.endswith("header:0")]
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
