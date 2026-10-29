"""`_shared/promotion-write-target.md` tells a review skill what survives `--update`.

Both review skills' Step 9 / 9b delegate to that partial, so a false durability claim
there becomes the wrong action in every consumer install. It carried two:

* It said the installer re-copies the pre-commit hook on every update, so a core
  pre-commit letter could only be retired upstream. `install.sh` keeps an edited
  `sysop/scripts/hooks/pre-commit` on `--update` (the WORKFLOW.md § 8.2c preserve
  scope), so a local deletion is durable.
* It said a promoted semgrep rule needs no overlay write. The rule FILE survives, but
  the pre-scan drops every finding of a rule with no `semgrep-<id>` entry in
  `.claude/checks.yml`, and that entry is regenerated away on `--update` unless it is
  also in `.claude/checks.project.yml`.

These tests run the installer and the pre-scan, and read the strings they check for out
of the partial itself, so the prose and the behaviour are tied without pinning wording.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from _prose_guard_helpers import normalize

import run_checks.semgrep as sg_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
PARTIAL = REPO_ROOT / "core" / "skills" / "_shared" / "promotion-write-target.md"
SHIPPED_HOOK = REPO_ROOT / "core" / "companion" / "git-hooks" / "pre-commit"
HOOK = "sysop/scripts/hooks/pre-commit"

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

# The claims this partial used to make. Matched against the normalized, lower-cased text.
# The first needs "every update": a re-install or `--force` DOES replace the hook, and the
# partial now says so, so the verb alone is not the false claim.
_NO_STOP = r"(?:(?!\.\s)[^|])"   # any character except a table bar, up to a sentence end
RETIRED_CLAIMS = [
    # A universal claim that an update replaces the hook. "every/each/any update" (or
    # `--update`) with a replace-verb and the hook named, in either order, one sentence.
    re.compile(r"(?:re-?cop\w*|overwrit\w*|replac\w*|refresh\w*|regenerat\w*)"
               rf"{_NO_STOP}{{0,60}}(?:pre-commit hook|hooks/pre-commit|hooks/\*)"
               rf"{_NO_STOP}{{0,40}}(?<!not )\b(?:every|each|any)\b{_NO_STOP}{{0,12}}update"),
    re.compile(r"(?<!not )\b(?:every|each|any)\b[^.|]{0,12}update"
               rf"{_NO_STOP}{{0,40}}(?:re-?cop\w*|overwrit\w*|replac\w*|regenerat\w*)"
               rf"{_NO_STOP}{{0,40}}(?:pre-commit hook|hooks/pre-commit|hooks/\*)"),
    # `--update` stated to replace the hook with no exception in the same sentence.
    re.compile(r"--update\s+(?:overwrit\w*|replac\w*|re-?cop\w*)"
               rf"{_NO_STOP}{{0,20}}(?:hooks/pre-commit|hooks/\*|pre-commit hook)"),
    re.compile(r"pre-commit\b[^.|]{0,80}\bno consumer-side suppression"),
    re.compile(r"hooks/\S*\s+(?:is|are)\s+(?:overwritten|replaced)\s+with\s+upstream"),
    # Object first: "the pre-commit hook is overwritten on every update".
    re.compile(r"(?:pre-commit hook|hooks/pre-commit|hooks/\*)"
               rf"{_NO_STOP}{{0,30}}\b(?:is|are|gets?)\s+(?:re-?cop\w*|overwrit\w*|replac\w*|regenerat\w*)"
               rf"{_NO_STOP}{{0,30}}(?<!not )\b(?:every|each|any)\b{_NO_STOP}{{0,12}}update"),
]

# A sentence that states its own exception is the true claim, not the retired one:
# "replaces an unedited hook", "only when you have not edited it", "unless …".
_EXCEPTION = re.compile(r"\b(?:unless|only when|only if|except|unedited|not edited|have not edited)\b")


def _sentences(flat: str) -> list[str]:
    return re.split(r"(?<=[.;!?])\s+", flat)


def retired_hits(flat: str, patterns) -> list[str]:
    """Patterns matched by a sentence that carries no stated exception."""
    return [p.pattern for s in _sentences(flat) if not _EXCEPTION.search(s)
            for p in patterns if p.search(s)]


def _partial() -> str:
    return PARTIAL.read_text(encoding="utf-8")


def _row(text: str, artifact: str) -> str:
    rows = [ln for ln in text.splitlines() if ln.startswith(f"| **`{artifact}")]
    assert len(rows) == 1, f"expected one table row for {artifact!r}, found {len(rows)}"
    return rows[0]


def _hook_row() -> str:
    return _row(_partial(), HOOK)


def _quoted(row: str, prefix: str) -> str:
    """The backticked span in `row` that starts with `prefix` — read, never retyped."""
    hits = [s for s in re.findall(r"`([^`]+)`", row) if s.startswith(prefix)]
    assert len(hits) == 1, f"expected one quoted `{prefix}…` in the row, found {hits}"
    return hits[0]


# ---------------------------------------------------------------------- prose -------

def test_the_partial_no_longer_says_the_pre_commit_hook_is_recopied() -> None:
    flat = normalize(_partial()).lower()
    hits = retired_hits(flat, RETIRED_CLAIMS)
    assert not hits, f"the partial restates a retired durability claim: {hits}"


# Promotion writes no round number into a map entry (`> checks.yml: <id>` and its
# siblings carry none); the round lives in the `docs: promote … from Round <N>` commit.
# "round-attributed in the ledger" is true and must stay legal, hence the object.
RETIRED_ROUND_CLAIMS = [
    re.compile(rf"round-attributed{_NO_STOP}{{0,40}}(?:convention[- _]?map|base-map|map entr)"),
    re.compile(r"entry is attributed to the review round"),
    re.compile(rf"(?<!no )map entr\w*{_NO_STOP}{{0,30}}\b(?:records?|carr(?:y|ies)) the round"),
]


_SURFACE_ROOTS = ("core", "packs", "docs", "README.md", "install.sh", "CONTRIBUTING.md",
                  "SECURITY.md", ".github")


def _shipping_surface() -> list[Path]:
    """Every tracked text file a consumer or a public reader gets, derived from git."""
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", *_SURFACE_ROOTS],
        capture_output=True, text=True, check=True).stdout.split()
    # Every tracked file, not an extension list: the hook templates have no extension and
    # the check fragments end in `.fragment`. Binary files are skipped by decoding.
    return [REPO_ROOT / f for f in out]


def test_the_shipping_surface_restates_no_retired_claim() -> None:
    files = _shipping_surface()
    rels = [f.relative_to(REPO_ROOT).as_posix() for f in files]
    for root in _SURFACE_ROOTS:
        assert any(r == root or r.startswith(root + "/") for r in rels), (
            f"the shipping-surface derivation no longer reaches {root}")
    # Named, not derived: the files this guard's claims were found in. A root dropped
    # from `_SURFACE_ROOTS` passes the loop above, and must fail here.
    for must in ("docs/workflow.html", "docs/install-and-update.md", "install.sh",
                 "core/companion/docs/WORKFLOW.md", "core/skills/codebase-review/SKILL.md",
                 "core/companion/git-hooks/pre-commit", "CONTRIBUTING.md",
                 "core/companion/checks.yml.fragment"):
        assert must in rels, f"the shipping surface no longer includes {must}"
    hits = []
    for f in files:
        try:
            raw = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        flat = normalize(raw).lower()
        hits += [f"{f.relative_to(REPO_ROOT)}: {pat}"
                 for pat in retired_hits(flat, RETIRED_CLAIMS + RETIRED_ROUND_CLAIMS)]
    assert not hits, "a shipped file restates a retired claim:\n" + "\n".join(hits)


@pytest.mark.parametrize("text,bad", [
    ("recurrence is computed from round-attributed `.claude/convention_map.md` entries", True),
    ("a promoted entry is attributed to the review round that surfaced it", True),
    ("the staleness is recorded round-attributed in the ledger", False),
    ("Each map entry records the round that promoted it, and the gate reads it", True),
    ("Each map entry carries the round that promoted it.", True),
    ("No map entry records the round that promoted it; the commit does.", False),
    ("The fire ledger is round-attributed. A convention map entry carries no round.", False),
])
def test_the_round_claim_patterns(text: str, bad: bool) -> None:
    flat = normalize(text).lower()
    assert bool(retired_hits(flat, RETIRED_ROUND_CLAIMS)) is bad, text


@pytest.mark.parametrize("bad", [
    "the installer replaces the pre-commit hook on each update",
    "`--update` overwrites `sysop/scripts/hooks/pre-commit` with Sysop's copy",
    "Every `--update` re-copies `sysop/scripts/hooks/pre-commit` from upstream",
    "The pre-commit hook is overwritten on every update.",
    "the installer re-copies the pre-commit hook on every update",
    "The installer overwrites the pre-commit hook on every update.",
    "A core **pre-commit** rule has no consumer-side suppression (see above)",
    "`sysop/scripts/hooks/*` is overwritten with upstream skeletons",
])
def test_the_retired_claim_patterns_each_see_their_claim(bad: str) -> None:
    flat = normalize(bad).lower()
    assert retired_hits(flat, RETIRED_CLAIMS), bad


@pytest.mark.parametrize("true_statement", [
    "A re-install re-copies the pre-commit hook, not every update.",
    "`--update --force` replaces `sysop/scripts/hooks/pre-commit` with Sysop's copy.",
    "`sysop/scripts/hooks/*` is refreshed from upstream unless you have edited a hook.",
    "`--update` replaces `sysop/scripts/hooks/pre-commit` only when you have not edited it.",
    "Each `--update` replaces an unedited `sysop/scripts/hooks/pre-commit` with Sysop's copy.",
    "`--update --force` overwrites the pre-commit hook with Sysop's copy.",
    "A re-install re-copies the pre-commit hook.",
    "Git runs an armed copy of the hook, not this file.",
])
def test_the_retired_claim_patterns_pass_what_is_true(true_statement: str) -> None:
    flat = normalize(true_statement).lower()
    assert not retired_hits(flat, RETIRED_CLAIMS), true_statement


def test_the_demotion_rule_retires_a_pre_commit_letter_locally_and_re_arms() -> None:
    text = _partial()
    # Explicit start and end headings, not `section()`: the slice is fixed at both ends.
    start = text.index("\n## Demotion (Step 9b) in a consumer install\n")
    demotion = text[start:text.index("\n## Why not overlay-only\n", start)]
    sentences = [s for s in re.split(r"(?<=[.])\s+", demotion) if "pre-commit" in s]
    local = [s for s in sentences if f"`{HOOK}`" in s]
    assert local, "the demotion section no longer names the file a letter is deleted from"
    assert any(REARM in s for s in local), (
        "retiring a letter must say the human re-arms: git runs the armed copy, not the "
        "vendored file")
    _assert_rearm_pointer_resolves()


# A skill must not name the arm script (tests/test_hook_autoarm_drift.py, upstream #202:
# arming is a human, main-checkout action). It points the human at the section that does.
REARM = (
    "the human re-arms the hooks from the main checkout (WORKFLOW.md § 4.3; a loop install "
    "ships no WORKFLOW.md, so point at https://github.com/getsysop/sysop/blob/main/docs/loop-mode.md#where-enforcement-lives)")


def _assert_rearm_pointer_resolves() -> None:
    wf = (REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    start = wf.index("\n### 4.3 Git hooks")
    body = wf[start:wf.index("\n### 4.4", start)]
    assert "`bash sysop/scripts/install_hooks.sh`" in body, (
        "WORKFLOW.md § 4.3 no longer gives the arm command the skills point the human at")
    assert (REPO_ROOT / "core" / "companion" / "scripts" / "install_hooks.sh").is_file()
    # Loop installs ship no WORKFLOW.md; the public page the pointer names must give the
    # command, under the heading its `#where-enforcement-lives` anchor resolves to.
    assert "blob/main/docs/loop-mode.md#where-enforcement-lives" in REARM
    lm = (REPO_ROOT / "docs" / "loop-mode.md").read_text(encoding="utf-8")
    start = lm.index("\n## Where enforcement lives\n")
    nxt = lm.find("\n## ", start + 1)
    assert "sysop/scripts/install_hooks.sh" in lm[start: nxt if nxt != -1 else len(lm)], (
        "docs/loop-mode.md § Where enforcement lives no longer gives the arm command")


def test_the_promotion_row_says_the_human_re_arms() -> None:
    assert REARM in _hook_row()
    assert "never arm the hooks from a skill" in _hook_row()
    _assert_rearm_pointer_resolves()


# ------------------------------------------------------------------ installer -------

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _install(target: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    r = subprocess.run(["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"install failed\n{r.stdout}\n{r.stderr}"
    return r


def _installed_consumer(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    _install(root, "--packs", "")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "install sysop", "--no-verify")
    return root


_RETIRE_MARK = "# === ADVISORY CHECKS ===\n"


def _retire_a_line(consumer: Path) -> str:
    """Delete one line from the vendored hook — the shape of a Step 9b retirement."""
    hook = consumer / HOOK
    body = hook.read_text()
    assert body.count(_RETIRE_MARK) == 1, "the shipped hook changed shape; pick another line"
    edited = body.replace(_RETIRE_MARK, "", 1)
    hook.write_text(edited)
    return edited


_SEMGREP_RULE = """rules:
  - id: {rid}
    languages: [python]
    severity: WARNING
    message: fixture rule
    pattern: eval(...)
"""


def _stub(rid: str) -> str:
    return (f"  - id: semgrep-{rid}\n    name: \"{rid}\"\n    category: security\n"
            f"    severity: medium\n    description: \"d\"\n    convention: \"c\"\n"
            f"    used_by: [codebase-review, security-audit]\n    blocking: false\n")


def test_update_keeps_an_edited_pre_commit_hook_and_prints_what_the_partial_quotes(
        tmp_path: Path) -> None:
    consumer = _installed_consumer(tmp_path / "consumer")
    armed = consumer / ".git" / "hooks" / "pre-commit"
    armed_before = armed.read_bytes()
    edited = _retire_a_line(consumer)

    # A promoted semgrep rule, its registry entry in the base only, and a second rule
    # whose entry is dual-written to the overlay as the partial prescribes.
    semgrep = consumer / ".claude" / "semgrep"
    (semgrep / "base_only_rule.yaml").write_text(_SEMGREP_RULE.format(rid="base-only-rule"))
    (semgrep / "dual_rule.yaml").write_text(_SEMGREP_RULE.format(rid="dual-rule"))
    with (consumer / ".claude" / "checks.yml").open("a") as f:
        f.write("\n" + _stub("base-only-rule") + _stub("dual-rule"))
    (consumer / ".claude" / "checks.project.yml").write_text("checks:\n" + _stub("dual-rule"))
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-qm", "retire a letter; promote two semgrep rules",
         "--no-verify")

    # The armed hook is a COPY: editing the vendored file did not change it.
    assert not armed.is_symlink()
    assert armed.read_bytes() == armed_before

    r = _install(consumer, "--update", "--packs", "")

    assert (consumer / HOOK).read_text() == edited, "the edited hook was overwritten"
    assert _quoted(_hook_row(), "⚠ preserved:") in r.stdout, r.stdout

    checks = (consumer / ".claude" / "checks.yml").read_text()
    assert (semgrep / "base_only_rule.yaml").is_file(), "an unshipped rule file was removed"
    assert "id: semgrep-base-only-rule" not in checks, (
        "a base-only registry entry survived the update; the partial says it does not")
    assert checks.count("id: semgrep-dual-rule") == 1, (
        "the overlay-written registry entry is missing or duplicated after the update")


@pytest.mark.parametrize("route", ["force", "accept-upstream", "reinstall", "no-ancestor"])
def test_each_route_the_partial_names_replaces_the_kept_hook(tmp_path: Path,
                                                             route: str) -> None:
    row = _hook_row()
    named = {
        "force": "`--update --force`",
        "accept-upstream": f"`--accept-upstream {HOOK}`",
        "reinstall": "re-install without `--update`",
        "no-ancestor": "`ancestor unreachable`",
    }[route]
    assert named in row, f"the partial no longer names the {route} route"

    consumer = _installed_consumer(tmp_path / "consumer")
    _retire_a_line(consumer)
    _git(consumer, "commit", "-qam", "retire a letter", "--no-verify")

    if route == "force":
        _install(consumer, "--update", "--packs", "", "--force")
    elif route == "accept-upstream":
        _install(consumer, "--update", "--packs", "", "--accept-upstream", HOOK)
    elif route == "reinstall":
        _install(consumer, "--packs", "")
    else:
        lock = consumer / ".claude" / "sysop.lock"
        data = json.loads(lock.read_text())
        data["sysop_commit"] = "0" * 40
        lock.write_text(json.dumps(data, indent=2) + "\n")
        _git(consumer, "commit", "-qam", "unreachable anchor", "--no-verify")
        r = _install(consumer, "--update", "--packs", "")
        assert _quoted(row, "ancestor unreachable") in r.stdout, r.stdout

    assert _RETIRE_MARK in (consumer / HOOK).read_text(), (
        f"the {route} route kept the edited hook; the partial says it replaces it")


# ------------------------------------------------------------------- pre-scan -------

def _canned(rule_id: str) -> subprocess.CompletedProcess:
    out = json.dumps({"results": [{
        "check_id": f"rules.{rule_id}", "path": "x.py", "start": {"line": 1},
        "extra": {"message": "m", "severity": "WARNING", "lines": "eval('a')"}}]})
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=out, stderr="")


def _run(tmp_path: Path, included: dict) -> list:
    (tmp_path / ".claude" / "semgrep").mkdir(parents=True, exist_ok=True)
    (tmp_path / "x.py").write_text("eval('a')\n")
    with patch("run_checks.semgrep.subprocess.run", return_value=_canned("my-rule")):
        return sg_mod._run_semgrep(str(tmp_path), included)


def test_the_prescan_drops_a_rule_with_no_registry_entry(tmp_path: Path) -> None:
    """The partial's reason for the `semgrep-<id>` entry. A non-empty `included` whose
    ids do not name this rule, so the drop is exercised, not the empty early return."""
    row = _row(_partial(), "semgrep/")
    assert "`semgrep-<id>`" in row and "`.claude/checks.project.yml`" in row
    assert _run(tmp_path, {"semgrep-other-rule": {"paths": ["."]}}) == []
    kept = _run(tmp_path, {"semgrep-my-rule": {"paths": ["."]}})
    assert [f[0] for f in kept] == ["semgrep-my-rule"], kept


def test_a_review_skips_a_registry_entry_whose_used_by_omits_it() -> None:
    """The partial's reason for naming `used_by:`. Each review runs the pre-scan with its
    own `--mode`, which `_classify_checks` turns into the `used_by` token it requires."""
    import run_checks.cli as cli
    row = _row(_partial(), "semgrep/")
    assert "`used_by:`" in row and "`codebase-review`" in row and "`security-audit`" in row
    entry = [{"id": "semgrep-my-rule", "used_by": ["codebase-review"]}]
    semgrep_ids = lambda token: cli._classify_checks(entry, active_token=token)[2]
    assert "semgrep-my-rule" in semgrep_ids("codebase-review")
    assert semgrep_ids("security-audit") == {}
