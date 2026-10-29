"""Step 2b's security gate and its per-target map copy — Phase 395, `Q-666`.

`core/companion/scripts/security_map_filter.py` decides whether the security twin spawns for a
target and cuts the copy of the security maps that agent is handed. Wade's answers
(2026-10-20): drop only a section whose globs are all concrete and match nothing in the diff,
keep every section with a placeholder glob, and hand the agent the omitted headings and the
full copy's path; one matcher for the gate and the copy; the inline arm measures the cut copy.

This module pins, by running the script in scratch repositories:

* which sections are kept and which dropped, including every shape a heading parse can miss;
* that a fenced `## ` is not a section, by the closer rule of `Q-468`, and an unclosed fence
  keeps its map whole;
* the gate: a skip says how many sections still carry placeholders, a mixed section's concrete
  glob spawns it, and the match is git's, against the diff;
* the two files, where they are written, and the arm;
* the security verdict key moving with the filter's source, and the shipped step's order.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_runner_text import text_of  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "companion" / "scripts"
SCRIPT = SCRIPTS / "security_map_filter.py"
CLOSE_DIR = REPO / "core" / "skills" / "review-close"

GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}

MAP = """# Security map

Read every section that routes your files.

## `scripts/*.sh` — Shell Scripts
- **Check:** A03 shell injection

## `.github/workflows/*.yml` — CI Configuration
- **Check:** A08 pinned actions

## `<api module>/routes/**/*.py` — API Endpoints
- **Check:** A01 authorization on every route

## `deploy/Dockerfile`, `<datajobs Dockerfile>` — Container Build
- **Check:** A05 no secrets in layers

## Config & Infrastructure
- **Check:** A05 secrets come from the environment
"""


def git(cwd, *args) -> str:
    p = subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       capture_output=True, text=True, env=GIT_ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def put(cwd, name, text="x\n"):
    (cwd / name).parent.mkdir(parents=True, exist_ok=True)
    (cwd / name).write_text(text, encoding="utf-8")


def commit(cwd, msg="c", **files):
    for name, text in files.items():
        put(cwd, name, text)
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", msg)


def run(cwd, target="feat", default="main", script=SCRIPT):
    return subprocess.run([sys.executable, str(script), target, default], cwd=cwd,
                          capture_output=True, text=True, env=GIT_ENV)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, env=GIT_ENV)
    put(r, ".claude/security_map.md", MAP)
    commit(r, "init", **{"README.md": "r\n"})
    return r


def branch(r, name="feat", rm=(), mv=(), **files):
    git(r, "switch", "-q", "-c", name, "main")
    for path in rm:
        git(r, "rm", "-q", path)
    for old, new in mv:
        (r / new).parent.mkdir(parents=True, exist_ok=True)
        git(r, "mv", old, new)
    for path, text in files.items():
        put(r, path, text)
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", name)
    git(r, "switch", "-q", "main")


def lines(p, label):
    return re.findall(rf"^{label}: (.*)$", p.stdout, re.M)


def copy_of(p) -> str:
    path = re.search(r"^COPY: (.*) \([\d,]+ characters\)$", p.stdout, re.M).group(1)
    return Path(path).read_text(encoding="utf-8")


# ── which sections are kept ─────────────────────────────────────────────────────────────

def test_only_a_concrete_section_the_diff_misses_is_dropped(repo):
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert p.stdout.startswith("SPAWN feat — 1 of 5 map sections matched\n")
    assert lines(p, "MATCHED") == ["## `scripts/*.sh` — Shell Scripts"]
    assert lines(p, "OMITTED") == ["## `.github/workflows/*.yml` — CI Configuration"]
    copy = copy_of(p)
    assert "CI Configuration" not in copy and "A08 pinned actions" not in copy
    # Kept: the matched section, the all-placeholder one, the mixed one (its concrete glob
    # missed, but a placeholder cannot rule a path out), the heading with no glob, the preamble.
    for kept in ("A03 shell injection", "API Endpoints", "Container Build",
                 "Config & Infrastructure", "secrets come from the environment",
                 "# Security map", "Read every section"):
        assert kept in copy, kept
    assert lines(p, "PLACEHOLDER") == ["## `<api module>/routes/**/*.py` — API Endpoints",
                                       "## `deploy/Dockerfile`, `<datajobs Dockerfile>` — Container Build"]


def test_the_kept_sections_are_verbatim_and_in_order(repo):
    branch(repo, **{"scripts/run.sh": "echo\n"})
    copy = copy_of(run(repo))
    whole = MAP.replace("## `.github/workflows/*.yml` — CI Configuration\n- **Check:** A08 pinned actions\n\n", "")
    assert copy == "<!-- .claude/security_map.md -->\n" + whole


@pytest.mark.parametrize("heading", [
    "## `ci/*.yml` - hyphen, not an em dash",
    "## ci/*.yml — globs not in backticks",
])
def test_a_heading_the_parse_cannot_read_is_kept(repo, heading):
    put(repo, ".claude/security_map.md", MAP + f"\n{heading}\n- **Check:** UNREAD rule\n")
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.returncode == 0 and "UNREAD rule" in copy_of(p), p.stdout


@pytest.mark.parametrize("heading", ["   ## `ci/*.yml` — Indented", "# A top-level heading"])
def test_an_indented_or_top_level_heading_ends_the_section_above_it(repo, heading):
    """Otherwise the text under it rides with the dropped section above and is lost: here the
    heading sits under the CI section, which this diff misses."""
    text = MAP.replace("- **Check:** A08 pinned actions\n",
                       f"- **Check:** A08 pinned actions\n\n{heading}\n- **Check:** AFTER rule\n")
    put(repo, ".claude/security_map.md", text)
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    copy = copy_of(p)
    if heading.startswith("#"):
        assert "AFTER rule" in copy, p.stdout
    else:  # an indented `## ` is a section of its own, concrete, and missed
        assert "## `ci/*.yml` — Indented" in lines(p, "OMITTED")
        assert "AFTER rule" not in copy and "secrets come from the environment" in copy


def test_a_tab_after_the_hashes_is_a_heading_that_parses(repo):
    put(repo, ".claude/security_map.md", MAP + "\n##\t`ci/*.yml` — Tabbed\n- **Check:** TAB rule\n")
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert "##\t`ci/*.yml` — Tabbed" in lines(p, "OMITTED") and "TAB rule" not in copy_of(p)
    branch(repo, "feat2", **{"ci/a.yml": "x\n"})
    assert lines(run(repo, target="feat2"), "MATCHED") == ["##\t`ci/*.yml` — Tabbed"]


@pytest.mark.parametrize("heading", ["## `deps/*.txt` - Deps, a hyphen", "##\t`deps/*.txt`, no name",
                                     "## `deps/*.txt` — Deps ##"])
def test_a_heading_the_strict_parse_misses_still_reaches_the_gate(repo, heading):
    """Lens A: a heading the cut cannot parse is kept, and its globs must spawn the twin, not
    read as a searched absence."""
    put(repo, ".claude/security_map.md", MAP + f"\n{heading}\n- **Check:** DEPS rule\n")
    commit(repo, "map")
    branch(repo, **{"deps/requirements.txt": "x\n"})
    p = run(repo)
    assert p.returncode == 0 and len(lines(p, "MATCHED")) == 1 and "DEPS rule" in copy_of(p), p.stdout


def test_a_deeper_heading_glob_reaches_the_gate(repo):
    """Lens A, HIGH: a consumer routes `migrations/*.sql` in a `###` under a `##` naming none.
    The first build read only `##` headings, so a migration-only branch skipped the twin."""
    put(repo, ".claude/security_map.md", MAP.replace(
        "## Config & Infrastructure\n", "## Config & Infrastructure\n\n### `migrations/*.sql`\n- **Check:** MIGRATION rule\n\n"))
    commit(repo, "map")
    branch(repo, **{"migrations/001.sql": "x\n"})
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == ["## Config & Infrastructure"], p.stdout
    assert "MIGRATION rule" in copy_of(p)


def test_a_deeper_heading_that_matches_keeps_its_section(repo):
    """The dropping half: a `###` that the diff reaches keeps the concrete `##` above it."""
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n\n### `deps/*.txt` — Deps\n- **Check:** DEPS rule\n"))
    commit(repo, "map")
    branch(repo, **{"deps/requirements.txt": "x\n"})
    p = run(repo)
    assert lines(p, "MATCHED") == ["## `.github/workflows/*.yml` — CI Configuration"], p.stdout
    assert "DEPS rule" in copy_of(p) and "A08 pinned actions" in copy_of(p)


def test_a_deeper_placeholder_keeps_its_section(repo):
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n\n### `<deploy dir>/*.yml`\n- **Check:** DEPLOY rule\n"))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert "DEPLOY rule" in copy_of(p) and "CI Configuration" not in "".join(lines(p, "OMITTED"))


def test_a_commented_out_heading_is_not_a_section(repo):
    """Lens A, HIGH: a `## ` inside `<!-- -->` cut the matched section above it short."""
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A03 shell injection\n",
        "<!--\n## `old/**` — Retired\nold rule\n-->\n- **Check:** A03 shell injection\n"))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert "A03 shell injection" in copy_of(p) and not any("Retired" in x for x in lines(p, "OMITTED")), p.stdout


def test_a_leading_bom_does_not_hide_the_first_heading(repo):
    (repo / ".claude" / "security_map.md").write_text("\ufeff" + MAP.split("\n", 4)[-1], encoding="utf-8")
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert lines(p, "MATCHED") == ["## `scripts/*.sh` — Shell Scripts"], p.stdout


def test_a_setext_heading_ends_the_section_above_and_reaches_the_gate(repo):
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n\n`deps/*.txt` — Deps\n-----------\n- **Check:** DEPS rule\n"))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    assert "DEPS rule" in copy_of(run(repo))
    branch(repo, "feat2", **{"deps/requirements.txt": "x\n"})
    assert lines(run(repo, target="feat2"), "MATCHED") == ["`deps/*.txt` — Deps"]


@pytest.mark.parametrize("glob,path", [("web/**/*.{ts,tsx}", "web/src/a.tsx"), ("/deps/*.txt", "deps/a.txt"),
                                       ("./deps/*.txt", "deps/a.txt")])
def test_braces_and_a_leading_slash_are_read(repo, glob, path):
    put(repo, ".claude/security_map.md", MAP + f"\n## `{glob}` — Extra\n- **Check:** EXTRA rule\n")
    commit(repo, "map")
    branch(repo, **{path: "x\n"})
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == [f"## `{glob}` — Extra"], (p.stdout, p.stderr)


def test_the_match_does_not_depend_on_the_current_directory(repo):
    """Lens A: `:(glob)` resolves against the current directory, so a run from a subdirectory
    skipped. `:(top,glob)` reads from the top level."""
    branch(repo, **{"scripts/run.sh": "echo\n"})
    (repo / "src").mkdir()
    p = run(repo / "src")
    assert p.returncode == 0 and lines(p, "MATCHED") == ["## `scripts/*.sh` — Shell Scripts"], p.stdout


def test_a_write_that_fails_is_exit_2(repo):
    branch(repo, **{"scripts/run.sh": "echo\n"})
    put(repo, "sysop", "a file where the directory goes\n")
    p = run(repo)
    assert p.returncode == 2 and "could not be written" in p.stderr, (p.stdout, p.stderr)


# ── fences ─────────────────────────────────────────────────────────────────────────────

def test_a_fenced_heading_is_not_a_section(repo):
    fenced = "```markdown\n## `scripts/*.sh` — Template only\n```\n"
    put(repo, ".claude/security_map.md",
        MAP.replace("- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n" + fenced))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.stdout.startswith("SPAWN feat — 1 of 5 "), p.stdout
    assert "Template only" not in copy_of(p)


def test_a_line_opening_with_an_inline_span_is_not_a_fence(repo):
    """CommonMark: a backtick fence's info string has no backtick, so "```x``` …" is text."""
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n```x``` is inline\n\n## `deps/*.txt` — Deps\n- **Check:** DEPS rule\n"))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert "## `deps/*.txt` — Deps" in lines(p, "OMITTED"), p.stdout
    branch(repo, "feat2", **{"deps/a.txt": "x\n"})
    assert "DEPS rule" in copy_of(run(repo, target="feat2"))


def test_an_info_string_line_inside_a_fence_does_not_close_it(repo):
    """`Q-468`: a toggle on any marker leaves the fence at "```json" and reads the next line
    as a heading, which here would keep a fake section and split the dropped one."""
    nested = "```\n```json\n## `scripts/*.sh` — Fake\n```\n"
    put(repo, ".claude/security_map.md",
        MAP.replace("- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n" + nested))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.stdout.startswith("SPAWN feat — 1 of 5 "), p.stdout
    assert "Fake" not in copy_of(p) and lines(p, "MATCHED") == ["## `scripts/*.sh` — Shell Scripts"]


def test_a_shorter_marker_inside_a_longer_fence_does_not_close_it(repo):
    nested = "````\n```\n## `scripts/*.sh` — Fake\n```\n````\n"
    put(repo, ".claude/security_map.md",
        MAP.replace("- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n" + nested))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.stdout.startswith("SPAWN feat — 1 of 5 "), p.stdout
    assert "Fake" not in copy_of(p)


@pytest.mark.parametrize("rule", ["- Reject `<!--` and `<script` in user-supplied names.",
                                  "Retired notes follow. <!-- legacy"])
def test_a_comment_marker_mid_line_opens_no_comment(repo, rule):
    """Round 2, lens A, HIGH: a `<!--` anywhere on a line opened a comment, so a rule naming
    the marker hid every heading after it until a `-->`. CommonMark opens one only where
    `<!--` starts its line."""
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A03 shell injection\n", f"- **Check:** A03 shell injection\n{rule}\n"
        ) + "\n## `src/auth/**` — Auth\n- **Check:** AUTH-1 verify the token\n- a --> b\n")
    commit(repo, "map")
    branch(repo, **{"src/auth/a.py": "x\n"})
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == ["## `src/auth/**` — Auth"], p.stdout
    assert "AUTH-1" in copy_of(p)


@pytest.mark.parametrize("opener", ["<!-->", "<!-- one line -->"])
def test_a_comment_closed_on_its_own_line_hides_nothing_after_it(repo, opener):
    put(repo, ".claude/security_map.md", MAP + f"\n{opener}\n\n## `src/auth/**` — Auth\n- AUTH-1\n")
    commit(repo, "map")
    branch(repo, **{"src/auth/a.py": "x\n"})
    assert lines(run(repo), "MATCHED") == ["## `src/auth/**` — Auth"]


@pytest.mark.parametrize("marker", ["    ```", "\t```"])
def test_an_indented_marker_is_code_not_a_fence(repo, marker):
    """Round 2, lens A: a marker indented four spaces or a tab opened a phantom fence, which the
    next real fence closed, hiding every heading between."""
    put(repo, ".claude/security_map.md", MAP + f"\n{marker}\n\n## `src/auth/**` — Auth\n- AUTH-1\n\n```bash\necho\n```\n")
    commit(repo, "map")
    branch(repo, **{"src/auth/a.py": "x\n"})
    assert lines(run(repo), "MATCHED") == ["## `src/auth/**` — Auth"]


@pytest.mark.parametrize("heading", ["> ## `src/auth/**` — Auth", "- ## `src/auth/**` — Auth"])
def test_a_heading_in_a_blockquote_or_list_reaches_the_gate(repo, heading):
    put(repo, ".claude/security_map.md", MAP.replace(
        "- **Check:** A08 pinned actions\n", f"- **Check:** A08 pinned actions\n{heading}\n- AUTH-1\n"))
    commit(repo, "map")
    branch(repo, **{"src/auth/a.py": "x\n"})
    p = run(repo)
    assert lines(p, "MATCHED") == ["## `.github/workflows/*.yml` — CI Configuration"] and "AUTH-1" in copy_of(p), p.stdout


def test_a_glob_too_wide_to_expand_counts_as_a_match(repo):
    wide = "src/" + "{a,b,c,d,e,f,g,h,i,j}" * 3 + "/**"
    put(repo, ".claude/security_map.md", MAP + f"\n## `{wide}` — Wide\n- WIDE rule\n")
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert lines(p, "UNMATCHABLE") == [wide] and "WIDE rule" in copy_of(p), p.stdout


def test_a_git_that_cannot_start_counts_as_a_match(repo, monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    import security_map_filter as F
    def boom(*a, **k):
        raise OSError(7, "Argument list too long")
    monkeypatch.setattr(F.subprocess, "run", boom)
    bad = []
    assert F.reaches("a", "b", ["x/*"], bad) is True and bad == ["x/*"]


def test_a_map_read_whole_is_counted(repo):
    put(repo, ".claude/security_map.md", "## `<api>/x` — Z\n- r\n## `ci/*` — C\n```\nunclosed\n")
    commit(repo, "map")
    branch(repo, **{"other/x": "x\n"})
    p = run(repo)
    assert p.returncode == 3 and "(1 of 2 map sections still carry placeholder globs)" in p.stdout, p.stdout


def test_a_tilde_fence_hides_its_headings_too(repo):
    """Lens B's S26: every fence test used backticks."""
    fenced = "~~~\n## `scripts/*.sh` — Template only\n~~~\n"
    put(repo, ".claude/security_map.md",
        MAP.replace("- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n" + fenced))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.stdout.startswith("SPAWN feat — 1 of 5 "), p.stdout
    assert "Template only" not in copy_of(p)


def test_a_fence_that_never_closes_keeps_its_map_whole(repo):
    put(repo, ".claude/security_map.md", MAP.replace("- **Check:** A08 pinned actions\n",
                                                      "- **Check:** A08 pinned actions\n```\n"))
    commit(repo, "map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert "WHOLE: .claude/security_map.md has a fence or comment that never closes" in p.stdout
    # Kept whole, and its gate reads every heading-shaped line in it, fence or not: a skip here
    # would be read as a searched absence (Phase 395's round, lens A).
    assert p.returncode == 0 and lines(p, "MATCHED") == [".claude/security_map.md (read whole)"], p.stdout
    assert copy_of(p).endswith(MAP.replace("- **Check:** A08 pinned actions\n", "- **Check:** A08 pinned actions\n```\n"))


@pytest.mark.parametrize("heading", ["## `api/*.py` — API", "### `api/*.py`"])
def test_a_map_read_whole_reads_the_headings_after_its_open_fence(repo, heading):
    """Round 2, lens B (C08, C26): the whole-map gate reads every heading-shaped line, a deeper
    one too, including those after the fence that never closes."""
    put(repo, ".claude/security_map.md", "## `docs/**` — Docs\n```\nnever closed\n\n" + heading + "\n- API rule\n")
    commit(repo, "map")
    branch(repo, **{"api/x.py": "x\n"})
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == [".claude/security_map.md (read whole)"], p.stdout


def test_a_comment_that_never_closes_keeps_its_map_whole(repo):
    put(repo, ".claude/security_map.md", MAP.replace("- **Check:** A08 pinned actions\n",
                                                      "- **Check:** A08 pinned actions\n<!--\n"))
    commit(repo, "map")
    branch(repo, **{".github/workflows/ci.yml": "on: push\n"})
    p = run(repo)
    assert "WHOLE: " in p.stdout and p.returncode == 0, p.stdout


# ── the gate ───────────────────────────────────────────────────────────────────────────

def test_a_diff_no_concrete_glob_reaches_is_a_skip_that_names_the_placeholders(repo):
    branch(repo, **{"api/routes/users.py": "x\n"})
    p = run(repo)
    assert p.returncode == 3
    assert p.stdout == ("SKIP feat — no security-map glob matches this diff "
                        "(2 of 5 map sections still carry placeholder globs)\n")
    assert not (repo / "sysop").exists()


def test_with_no_map_the_skip_says_so(repo):
    git(repo, "rm", "-q", ".claude/security_map.md")
    git(repo, "commit", "-q", "-m", "no map")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.returncode == 3 and "(no security map exists)" in p.stdout


def test_a_mixed_section_spawns_on_its_concrete_glob(repo):
    branch(repo, **{"deploy/Dockerfile": "FROM x\n"})
    p = run(repo)
    assert p.returncode == 0
    assert lines(p, "MATCHED") == ["## `deploy/Dockerfile`, `<datajobs Dockerfile>` — Container Build"]


def test_a_section_is_kept_when_its_second_glob_matches(repo):
    """Lens B's S22: matching only a section's first glob dropped a section its second reached."""
    branch(repo, **{".dockerignore": "x\n"})
    put(repo, ".claude/security_map.md", MAP + "\n## `Dockerfile`, `.dockerignore` — Image\n- **Check:** IMAGE rule\n")
    commit(repo, "map")
    git(repo, "switch", "-q", "-c", "feat2", "main")
    put(repo, ".dockerignore", "x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "f2")
    git(repo, "switch", "-q", "main")
    p = run(repo, target="feat2")
    assert lines(p, "MATCHED") == ["## `Dockerfile`, `.dockerignore` — Image"] and "IMAGE rule" in copy_of(p), p.stdout


def test_double_star_matches_a_direct_child(repo):
    """git's `:(glob)`: `api/**/*.py` reaches `api/server.py`; a plain pathspec does not."""
    put(repo, ".claude/security_map.md", MAP + "\n## `api/**/*.py` — Backend\n- **Check:** A01\n")
    commit(repo, "map")
    branch(repo, **{"api/server.py": "x\n"})
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == ["## `api/**/*.py` — Backend"]


def test_a_single_star_does_not_cross_a_directory(repo):
    branch(repo, **{"scripts/sub/run.sh": "echo\n"})
    assert run(repo).returncode == 3


def test_a_deleted_file_reaches_its_section(repo):
    commit(repo, "add", **{"scripts/old.sh": "echo\n"})
    branch(repo, rm=("scripts/old.sh",))
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == ["## `scripts/*.sh` — Shell Scripts"]


def test_a_renamed_file_reaches_the_section_of_its_old_name(repo):
    commit(repo, "add", **{"scripts/old.sh": "echo one two three four five\n"})
    branch(repo, mv=(("scripts/old.sh", "bin/old.sh"),))
    p = run(repo)
    assert p.returncode == 0 and lines(p, "MATCHED") == ["## `scripts/*.sh` — Shell Scripts"]


def test_the_diff_is_the_merge_base_not_the_default_tip(repo):
    """A change on `main` after the branch forked is not the branch's."""
    branch(repo, **{"notes.txt": "n\n"})
    commit(repo, "main moves", **{"scripts/main.sh": "echo\n"})
    assert run(repo).returncode == 3


def test_the_unpushed_main_group_diffs_against_origin(repo, tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=GIT_ENV)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    commit(repo, "local", **{"scripts/local.sh": "echo\n"})
    p = run(repo, target="unpushed-main")
    assert p.returncode == 0 and p.stdout.startswith("SPAWN unpushed-main — 1 of 5 "), p.stdout


# ── the files and the arm ──────────────────────────────────────────────────────────────

def test_the_overlay_comes_first_and_the_full_copy_holds_both_verbatim(repo):
    overlay = "## `src/auth/*.py` — Auth\n- **Check:** A07 OVERLAY rule\n"
    put(repo, ".claude/security_map.project.md", overlay)
    commit(repo, "overlay")
    branch(repo, **{"src/auth/login.py": "x\n"})
    p = run(repo)
    assert lines(p, "MATCHED") == ["## `src/auth/*.py` — Auth"]
    full = Path(lines(p, "FULL")[0]).read_text(encoding="utf-8")
    assert full == ("<!-- .claude/security_map.project.md -->\n" + overlay
                    + "<!-- .claude/security_map.md -->\n" + MAP)
    copy = copy_of(p)
    assert copy.index("OVERLAY rule") < copy.index("# Security map")
    assert "Shell Scripts" not in copy and "Shell Scripts" in full


def test_an_overlay_the_installer_appended_is_read_once(repo):
    """Lens B, HIGH: `install.sh` appends the overlay to the shipped map, so reading both files
    counted, matched and copied every overlay section twice on an installed consumer."""
    overlay = "## `src/*.py` — App Code\n- **Check:** OVERLAY rule\n"
    put(repo, ".claude/security_map.project.md", overlay)
    put(repo, ".claude/security_map.md", MAP + "\n" + overlay)  # what concat_files writes
    commit(repo, "installed shape")
    branch(repo, **{"src/a.py": "x\n"})
    p = run(repo)
    assert lines(p, "MATCHED") == ["## `src/*.py` — App Code"], p.stdout
    assert p.stdout.startswith("SPAWN feat — 1 of 6 "), p.stdout
    assert copy_of(p).count("OVERLAY rule") == 1
    assert Path(lines(p, "FULL")[0]).read_text(encoding="utf-8").count("OVERLAY rule") == 1


def test_an_overlay_edited_since_the_update_is_read_twice_and_loses_nothing(repo):
    old = "## `src/*.py` — App Code\n- **Check:** OLD rule\n"
    put(repo, ".claude/security_map.md", MAP + "\n" + old)
    put(repo, ".claude/security_map.project.md", old.replace("OLD", "NEW"))
    commit(repo, "edited overlay")
    branch(repo, **{"src/a.py": "x\n"})
    copy = copy_of(run(repo))
    assert "OLD rule" in copy and "NEW rule" in copy


def test_the_overlay_is_cut_only_from_the_end_of_the_shipped_map(repo):
    """The full copy is the shipped map verbatim: an overlay whose text also sits inside it (a
    rule restated, as GDP's maps do) loses only the copy `install.sh` appended."""
    overlay = "## `scripts/*.sh` — Shell Scripts\n- **Check:** A03 shell injection\n"
    assert overlay in MAP
    put(repo, ".claude/security_map.project.md", overlay)
    put(repo, ".claude/security_map.md", MAP + "\n" + overlay)
    commit(repo, "installed shape")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    full = Path(lines(run(repo), "FULL")[0]).read_text(encoding="utf-8")
    assert full == ("<!-- .claude/security_map.project.md -->\n" + overlay
                    + "<!-- .claude/security_map.md -->\n" + MAP)


def test_text_before_the_first_heading_is_kept(repo):
    put(repo, ".claude/security_map.project.md", "PREAMBLE rule for every file.\n\n## `src/*.py` — Src\n- r\n")
    commit(repo, "overlay")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert "## `src/*.py` — Src" in lines(p, "OMITTED") and "PREAMBLE rule" in copy_of(p), p.stdout


def test_a_heading_that_opens_a_comment_is_still_a_heading(repo):
    put(repo, ".claude/security_map.md", MAP + "\n## `deps/*.txt` — Deps <!-- note\nhidden\n-->\n- **Check:** DEPS rule\n")
    commit(repo, "map")
    branch(repo, **{"deps/a.txt": "x\n"})
    p = run(repo)
    assert lines(p, "MATCHED") == ["## `deps/*.txt` — Deps <!-- note"], p.stdout


def test_a_map_with_no_final_newline_does_not_run_into_the_next(repo):
    put(repo, ".claude/security_map.project.md", "## `src/*.py` — Src\n- last line")
    commit(repo, "overlay")
    branch(repo, **{"src/a.py": "x\n"})
    copy = copy_of(run(repo))
    assert "- last line\n<!-- .claude/security_map.md -->\n" in copy


def test_each_target_gets_its_own_copy_and_both_land_in_the_main_checkout(repo, tmp_path):
    branch(repo, **{"scripts/run.sh": "echo\n"})
    branch(repo, "feat2", **{".github/workflows/ci.yml": "on: push\n"})
    wt = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "--detach", str(wt), "main")
    a, b = run(wt), run(wt, target="feat2")
    assert a.returncode == b.returncode == 0
    ca, cb = lines(a, "COPY")[0], lines(b, "COPY")[0]
    assert ca != cb
    for c in (ca, cb):
        assert Path(c.rsplit(" (", 1)[0]).parent == (repo / "sysop" / "runtime").resolve()
    assert not (wt / "sysop").exists()
    assert "CI Configuration" in copy_of(b) and "CI Configuration" not in copy_of(a)


@pytest.mark.parametrize("pad,arm", [(0, "inline"), (1, "file")])
def test_the_arm_measures_the_cut_copy(repo, pad, arm):
    """At or below 10,000 characters the copy is pasted; the dropped sections do not count."""
    branch(repo, **{"scripts/run.sh": "echo\n"})
    size = len(copy_of(run(repo)))
    filler = "x" * (10_000 - size - len("\n") + pad)
    big = "## `.github/workflows/*.yml` — CI Configuration\n- **Check:** A08 pinned actions\n" + "y" * 20_000 + "\n"
    put(repo, ".claude/security_map.md", MAP.replace("Read every section that routes your files.",
                                                      "Read every section that routes your files.\n" + filler)
        .replace("## `.github/workflows/*.yml` — CI Configuration\n- **Check:** A08 pinned actions\n", big))
    commit(repo, "pad")
    p = run(repo)
    assert len(copy_of(p)) == 10_000 + pad, p.stdout
    assert lines(p, "ARM") == [arm]


# ── refusals ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args", [("nope", "main"), ("<target>", "main"), ("feat", "<default branch>")])
def test_an_unresolvable_or_unsubstituted_argument_is_exit_2(repo, args):
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo, *args)
    assert p.returncode == 2 and p.stdout == "" and p.stderr.startswith("security_map_filter: ")
    # A placeholder is refused by name, before git reads it as a ref.
    assert ("substitute the target" in p.stderr) is ("<" in "".join(args)), p.stderr
    assert not (repo / "sysop").exists()


def test_a_map_that_is_not_utf8_is_exit_2(repo):
    (repo / ".claude" / "security_map.md").write_bytes(b"## `scripts/*.sh` \xff\n")
    commit(repo, "bad")
    branch(repo, **{"scripts/run.sh": "echo\n"})
    p = run(repo)
    assert p.returncode == 2 and "not UTF-8" in p.stderr


def test_a_glob_git_cannot_read_counts_as_a_match(repo, monkeypatch):
    """A `git diff` that fails would otherwise read as "this glob reaches nothing", and a heading
    token that is prose, not a glob, must not stop every close either: it keeps its section."""
    sys.path.insert(0, str(SCRIPTS))
    import security_map_filter as F
    monkeypatch.chdir(repo)
    bad = []
    assert F.reaches("0" * 40, "HEAD", ["scripts/*.sh"], bad) is True
    assert bad == ["scripts/*.sh"]


# ── the key, and the shipped step ──────────────────────────────────────────────────────

def test_the_security_verdict_key_moves_with_the_filter(repo, tmp_path):
    """The agent is handed the cut copy, so a change to the cut is a change to what it saw."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("gate_verdict.py", "security_map_filter.py", "security_partition.py"):
        shutil.copy2(SCRIPTS / name, scripts / name)
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "### 2b. Check\n\n`model: \"opus\"`, `effort: \"high\"` <!-- sysop:role=security-gate -->\n",
        encoding="utf-8")
    branch(repo, **{"scripts/run.sh": "echo\n"})

    def lookup():
        return subprocess.run([sys.executable, str(scripts / "gate_verdict.py"), "lookup",
                               "security", "feat", "main", str(skill)], cwd=repo,
                              capture_output=True, text=True, env=GIT_ENV)

    key = re.search(r"^KEY: (\w{64})$", lookup().stdout, re.M).group(1)
    sha = git(repo, "rev-parse", "feat")
    rec = subprocess.run([sys.executable, str(scripts / "gate_verdict.py"), "record", "security",
                          "feat", "main", str(skill), sha, key], cwd=repo, capture_output=True,
                         text=True, env=GIT_ENV)
    assert rec.returncode == 0, rec.stderr
    assert lookup().returncode == 0
    for name in ("security_map_filter.py", "security_partition.py"):
        before = (scripts / name).read_bytes()
        (scripts / name).write_bytes(before + b"# changed\n")
        p = lookup()
        assert p.returncode == 3 and "sources" in p.stdout, name
        (scripts / name).write_bytes(before)
        assert lookup().returncode == 0, name


def test_the_shipped_step_runs_the_filter_after_the_lookup_and_before_the_spawn():
    text = text_of(CLOSE_DIR / "SKILL.md")
    step = re.search(r"^3b\. \*\*Spawn the security twin.*?(?=^4\. Collect all verdicts)", text, re.M | re.S)
    assert step, "Step 2b has no security twin (step 3b)"
    step = step.group(0)
    look = step.index('gate_verdict.py lookup security "<target>" "<default branch>"')
    cut = step.index('python3 sysop/scripts/security_map_filter.py "<target>" "<default branch>"')
    spawn = step.index("Spawn one Agent per surviving target")
    assert look < cut < spawn
