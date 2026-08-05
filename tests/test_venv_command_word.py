"""Phase 183 — a Sysop-shipped script is never given a `.venv/bin/` command word.

Phase 182 fixed the *script* half of "bare `python3` cannot find PyYAML": five
companion scripts self-resolve a venv (script-anchored first — the file's
ancestors, then the main checkout via git-common-dir — and only then the CWD,
across both `.venv/` and `venv/` layouts). This file guards the *skill*
half — the command word the shipped content prescribes.

`.venv/bin/python3 sysop/scripts/<x>.py` is less portable than the bare form in
the two cases that matter:

  * on a `venv/`-layout, poetry, conda or PEP-668 system-python consumer the
    venv-prefixed word is `command not found` (exit 127) while the bare word
    runs, and
  * inside any linked worktree it is 127 even on a consumer whose MAIN checkout
    has a `.venv`, because a worktree never carries one — which is exactly the
    arm Phase 182 added git-common-dir for.

It is a TRADE, not a strict improvement, and the round's execution lens
falsified the first draft's "strictly": on a host with no `python3` on `PATH` at
all (or a broken pyenv shim) but a working `.venv`, the venv-prefixed word runs
and the bare one exits 127. That population is far smaller than the two above
and it fails loudly rather than wrongly, which is why the trade is worth making
— but the word "strictly" was false and is gone.

Two guards, deliberately different in kind. `TestNoShippedVenvCommandWord`
screens the CLAIM SHAPE across every shipped file: it pins no count, so a new
skill, a new script or a new `.venv/bin/pytest` line all pass untouched, and
only the actual defect reddens. Phase 175 shipped a guard that reddened correct
prose; a count would do it here on the first legitimate addition.
`TestItActuallyRuns` proves the swap by EXECUTION rather than by reading. (An
earlier draft of this docstring attributed a "false green from a command exiting
127" to Phase 173; the round's claims lens checked it and the tree says
otherwise — `PHASE_LOG.md:3936` records that phase's false-green as "arriving
from the harness rather than from a `127`". The reason to execute rather than
read stands on its own; the borrowed anecdote did not, and this file ships to
the public mirror.)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"


# --------------------------------------------------------------------------
# Guard 1 — the claim shape, file-wide
# --------------------------------------------------------------------------

# Derived from the tree, never hardcoded: a script added later is covered the
# day it lands. Phase 182's round caught its own filing under-counting its class
# 5x from a hand-written list, and Phase 183's re-derivation found the filed
# ten was sixteen.
def _shipped_script_stems() -> set[str]:
    stems = set()
    for p in SCRIPTS.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".sh"):
            stems.add(p.name)
    # Three anchors, one per derivation branch, because the round's battery
    # walked through all of them: `rglob`→`glob` silently dropped the
    # `run_checks/` subpackage, and narrowing the suffix filter to `(".py",)`
    # dropped the entire `.sh` half of the inventory. Both survived green.
    assert "validate_tasks.py" in stems, "script inventory did not resolve"
    assert "config.py" in stems, "rglob→glob: the run_checks/ subpackage dropped out"
    assert "claim_task.sh" in stems, "the .sh half of the inventory dropped out"
    return stems


def _shipped_files() -> list[Path]:
    """Files a consumer receives, via `git ls-files`.

    NOT `Path.rglob` — `.claude/worktrees/agent-*/` holds stale untracked copies
    of the whole tree, which inflate a naive walk ~10x and would let this guard
    pass or fail on a directory nobody ships.
    """
    pathspec = ["core/", "docs/", "packs/",
                "README.md", "CONTRIBUTING.md", "install.sh"]
    # `--others --exclude-standard` includes UNTRACKED-but-not-ignored files.
    # Without it the guard is blind exactly when a site is being authored — the
    # round's guard lens planted `core/skills/zz-probe/SKILL.md` carrying the
    # canonical defect and the suite stayed green.
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", *pathspec],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    files = [REPO_ROOT / p for p in out.split("\0") if p]
    # Without this, a `git ls-files` that returns nothing (wrong cwd, a pathspec
    # typo, a future directory rename) makes every assertion below vacuously
    # true while reporting green — the exact shape Phase 149 built the coverage
    # ledger for. The first cut anchored only on `core/` paths, so narrowing the
    # pathspec to `["core/"]` alone survived the round's battery even though
    # `docs/install-and-update.md` is one of the sixteen fixed sites. One anchor
    # per pathspec entry now, so dropping any entry reddens.
    rel = {str(p.relative_to(REPO_ROOT)) for p in files}
    for anchor in ("core/skills/next-task/SKILL.md",
                   "core/companion/docs/WORKFLOW.md",
                   "core/companion/scripts/claim_task.sh",
                   "docs/install-and-update.md",
                   "packs/python/companion/convention_map.md",
                   "README.md",
                   "CONTRIBUTING.md",
                   "install.sh"):
        assert anchor in rel, f"shipped-file scan lost {anchor} — guard is vacuous"
    return files


def _pattern() -> re.Pattern:
    """THE predicate. One writer, so the two calibration tests below exercise
    the same object `_offending_lines` does.

    The first cut of this file inlined the regex at all three call sites; the
    mutation battery then showed that blinding the real one left both
    calibration tests green, because each was validating its own private copy.
    That is Phase 181's six-readers-one-writer defect, reproduced inside the
    guard written to prevent a different one.

    A venv interpreter, whitespace, then (optionally path-prefixed) a shipped
    script name. `.venv/bin/pip install pyyaml` has no script name after it;
    `[[ -x "$root/.venv/bin/python3" ]]` resolver probes have no script name
    either; both stay green by construction rather than by an exclusion list.
    """
    stems = "|".join(re.escape(s) for s in sorted(_shipped_script_stems()))
    # Dotted `-m` spelling too: `sysop.scripts.validate_tasks`. Zero in-tree
    # instances today, but the author-side pass holds a survivor to "impossible
    # to close in kind", not "absent right now".
    dotted = "|".join(
        re.escape(s.rsplit(".", 1)[0]) for s in sorted(_shipped_script_stems())
    )
    # The stem alternation needs a LEFT boundary. Without one, `[^ \t\n]*`
    # swallows any prefix and `.venv/bin/pytest tests/test_validate_tasks.py`
    # reddens — a legitimate line, and `CONTRIBUTING.md` is scanned, which is
    # exactly where "how to run one test" belongs. The round's execution lens
    # found this; it is Phase 175's failure mode inside the guard whose own
    # docstring claims to have avoided it. The operand must therefore be either
    # bare or path-separated, never merely suffixed.
    # The interpreter is `python`-something, not any venv binary. Broadening it
    # to `[A-Za-z0-9._-]+` is what made `.venv/bin/pytest -k validate_tasks.py`
    # redden: the flag allowance ate `-k` and the stem matched bare. Only a
    # Python interpreter can invoke a Sysop script, so this is the real class
    # and it removes the false positive rather than special-casing pytest.
    # `["']?` after the interpreter: a QUOTED path was completely invisible, and
    # it is the shape `WORKFLOW.md` itself teaches ("spell out the
    # absolute-to-repo-root invocation"), which in shell means
    # `"${REPO_ROOT}/.venv/bin/python3" sysop/scripts/…`. Found by the round.
    #
    # The flag group allows a SEPARATED value (`-X utf8`, `-W ignore`, `-m x`),
    # not only the attached form. The first cut's comment claimed `-X` while
    # matching only `-Xutf8` — a coverage claim asserted nowhere and false.
    _flag = r"(?:-[A-Za-z0-9][^ \t]*[ \t]+(?:[a-z][^-][^ \t]*[ \t]+)?)*"
    return re.compile(
        rf"venv/bin/python[0-9.]*[\"']?"           # the venv Python interpreter
        rf"[ \t]+{_flag}"                          # interpreter flags, attached or separated
        rf"[\"']?(?:[^ \t\n\"']*/)?"               # an optional PATH prefix, ending in /
        rf"(?:{stems}|(?:sysop[./])?scripts[./](?:{dotted})\b)"
    )


def _logical_lines(text: str):
    """Yield (first-physical-lineno, logical line), joining shell continuations.

    A guard keyed to a physical line is walked through by a trailing backslash —
    named in the author-side pass as "how people write", not as an adversarial
    case. Zero instances in the tree today; closed anyway, because the pass
    holds a survivor to impossible-in-kind rather than to currently-absent.
    """
    buf, start = None, 0
    for n, raw in enumerate(text.splitlines(), 1):
        if buf is None:
            buf, start = raw, n
        else:
            buf = buf + " " + raw.lstrip()
        if buf.endswith("\\"):
            buf = buf[:-1]
            continue
        yield start, buf
        buf = None
    if buf is not None:
        yield start, buf


def _scan_text(text: str) -> list[tuple[int, str]]:
    """THE scanner. One body, so a test that feeds it synthetic text exercises
    the same code path the file sweep does.

    The battery caught the alternative: with the continuation join living only
    in `_offending_lines`, a test calling `_logical_lines` directly SURVIVED
    reverting the scan to physical lines — validating the helper, not its use.
    That is the same isolation defect `_pattern()` was extracted to fix, one
    function over.
    """
    pat = _pattern()
    hits = []
    for n, line in _logical_lines(text):
        # `Bash(...)` is a permission-rule STRING, never an executed command, and
        # the venv rules stay shipped on purpose for back-compat.
        #
        # The round's guard lens showed this whole-line skip can shelter a real
        # invocation sharing a line with a rule. The obvious closure — blank the
        # `Bash(...)` spans and scan the remainder — was BUILT AND REVERTED: the
        # shipped permission bullets cite the venv rule strings OUTSIDE the
        # parens (`auto-build/SKILL.md:23`, `claim-task/SKILL.md:29` both read
        # "…`Bash(python3 …)` … and the `.venv/bin/python3 …` venv variants…"),
        # so span-blanking reddens two correct shipped lines. Blanking every
        # backticked span instead re-opens the same hole, because the lens's
        # case is backticked too. There is no textual discriminator between
        # citing the venv rule string in a bullet and prescribing it, so the
        # false positive is declined in favour of the gap — Phase 175's
        # direction, and the round had already caught this guard reddening a
        # correct line once. Pinned by test_the_bash_skip_is_a_declared_gap.
        if "Bash(" in line:
            continue
        if pat.search(line):
            hits.append((n, line))
    hits.extend(h for h in _variable_held_hits(text) if h not in hits)
    return sorted(set(hits))


_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=[\"']?([^\"'\s]*)")


def _variable_held_hits(text: str) -> list[tuple[int, str]]:
    """Catch `PY=.venv/bin/python3` … `$PY sysop/scripts/x.py` — the BLIND case.

    The author-side pass declined this as "the judgement no pattern encodes",
    because the only in-tree variable-held venv interpreters are the PROBED
    resolvers and flagging them would redden correct code (Phase 175). The
    round's guard lens refuted that in about twenty lines, and the rule is
    explicit that a declined survivor must be impossible to close *in kind*,
    not merely unattempted — so it is closed here on the lens's own predicate.

    The discriminator is the fallback, not the probe: a probed resolver ALWAYS
    assigns a non-venv candidate too (`run_checks.sh:55` `PYTHON="python3"`;
    `self_check.sh:93` `RC_PY="python3"`; both git-hook examples the same). So
    flag `$VAR <stem>` only when EVERY assignment to VAR in that file is a venv
    path. Zero false positives across the shipped tree; catches the blind case.
    """
    stems = _shipped_script_stems()
    assigns: dict[str, list[str]] = {}
    for _, line in _logical_lines(text):
        m = _ASSIGN_RE.match(line)
        if m:
            assigns.setdefault(m.group(1), []).append(m.group(2))
    venv_only = {
        var for var, vals in assigns.items()
        if vals and all("venv/bin/" in v for v in vals)
    }
    if not venv_only:
        return []
    hits = []
    for n, line in _logical_lines(text):
        for var in venv_only:
            use = re.search(
                rf"\$\{{?{re.escape(var)}\}}?[\"']?[ \t]+[\"']?(?:[^ \t\n\"']*/)?"
                rf"({'|'.join(re.escape(s) for s in sorted(stems))})\b",
                line,
            )
            if use:
                hits.append((n, line))
                break
    return hits


def _offending_lines(files=None, root=REPO_ROOT) -> list[tuple[str, int, str]]:
    """Scan `files` (default: the shipped set) and report every offending line.

    The file list is INJECTABLE for one reason: without it, this function's only
    consumer was a *negative* assertion (`assert not hits`), and a negative
    assertion cannot notice that the thing producing the negative has stopped
    looking. The round's guard lens proved it — reducing the scan to a no-op
    left the suite green, and then all eighteen of the phase's own site
    mutations survived too. The entire product of the phase rested on one line
    no test protected. `test_the_sweep_finds_a_planted_defect` now drives this
    function positively over a temp tree.
    """
    hits = []
    for path in (_shipped_files() if files is None else files):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in _scan_text(text):
            hits.append((str(path.relative_to(root)), n, line.strip()))
    return hits


class TestNoShippedVenvCommandWord:
    def test_no_shipped_file_gives_a_sysop_script_a_venv_command_word(self):
        hits = _offending_lines()
        assert not hits, "venv-prefixed command word for a Sysop script:\n" + "\n".join(
            f"  {f}:{n}: {line[:160]}" for f, n, line in hits
        )

    def test_the_sweep_finds_a_planted_defect(self, tmp_path):
        """POSITIVE coverage of the file sweep — the guard's whole product.

        The round's guard lens reduced `_scan_text`'s consumption to a no-op and
        got 26 passed on a tree carrying the restored defect. Every other test
        here drives `_pattern()` or `_scan_text()` directly; none drove
        `_offending_lines`, and its one consumer asserts a NEGATIVE. This drives
        it end-to-end over real files on disk, so gutting any link in the chain
        (`_shipped_files` → `_scan_text` → `_logical_lines` → `_pattern`) fails
        here instead of passing everywhere.
        """
        clean = tmp_path / "clean.md"
        clean.write_text("Run `python3 sysop/scripts/validate_tasks.py` to check.\n")
        dirty = tmp_path / "dirty" / "SKILL.md"
        dirty.parent.mkdir()
        dirty.write_text(
            "# A skill\n\nSome prose.\n\n"
            "```bash\n.venv/bin/python3 sysop/scripts/validate_tasks.py\n```\n"
        )
        hits = _offending_lines([clean, dirty], root=tmp_path)
        assert len(hits) == 1, hits
        rel, lineno, line = hits[0]
        assert rel == "dirty/SKILL.md", hits
        assert lineno == 6, hits          # the line number must be real, not 0
        assert ".venv/bin/python3" in line, hits

    def test_an_untracked_file_is_in_scope(self):
        """Blind exactly when a site is being authored, until this.

        The round's guard lens planted `core/skills/zz-probe/SKILL.md` carrying
        the canonical defect and the suite stayed green, because the scan was
        `git ls-files` (tracked only). A newly written skill is untracked for
        the whole time someone is writing it — precisely when you want the
        guard. Plants a real file so the `--others` flag is proven, not merely
        asserted to be in the argv.
        """
        probe = REPO_ROOT / "docs" / "_untracked_guard_probe.md"
        assert not probe.exists(), "stale probe file — remove it"
        probe.write_text("`.venv/bin/python3 sysop/scripts/validate_tasks.py`\n")
        try:
            hits = _offending_lines()
            assert any(f.endswith("_untracked_guard_probe.md") for f, _, _ in hits), (
                "an untracked file carrying the defect is invisible to the sweep")
        finally:
            probe.unlink(missing_ok=True)

    def test_the_guard_can_actually_see_the_defect(self):
        """A guard that cannot fail is Phase 123's finding and Phase 159a's.

        Re-runs the real predicate over a file carrying the exact shape the
        phase removed. Without this, deleting the regex body leaves the suite
        green.
        """
        pat = _pattern()
        for bad in (
            ".venv/bin/python3 sysop/scripts/validate_tasks.py",
            ".venv/bin/python sysop/scripts/validate_tasks.py",   # the no-`3` spelling
            "venv/bin/python3 sysop/scripts/next_task.py",        # no leading dot
            "    .venv/bin/python3 sysop/scripts/scope_overlap.py <TASK_ID>",
            "validate with `.venv/bin/python sysop/scripts/validate_tasks.py` — or",
            # Closed by the author-side pass (rule 1, "what it matches on").
            # None of these is adversarial; they are how people write.
            ".venv/bin/python3 -u sysop/scripts/validate_tasks.py",       # flag first
            ".venv/bin/python3 -m sysop.scripts.validate_tasks",         # dotted -m
            ".venv/bin/python3 ${REPO_ROOT}/sysop/scripts/next_task.py",  # abs operand
            ".venv/bin/python3 ./sysop/scripts/next_task.py",             # ./ operand
            ".venv/bin/python3 scripts/validate_tasks.py",                # pre-128 layout
            ".venv/bin/python3\tsysop/scripts/validate_tasks.py",         # tab
            # Found by the round's guard lens — all four were invisible.
            # A QUOTED interpreter is the shape WORKFLOW.md itself teaches
            # ("spell out the absolute-to-repo-root invocation").
            '"${REPO_ROOT}/.venv/bin/python3" sysop/scripts/validate_tasks.py',
            "'.venv/bin/python3' sysop/scripts/validate_tasks.py",
            # A flag with a SEPARATED value. The first cut's comment claimed
            # `-X` while matching only the attached `-Xutf8`.
            ".venv/bin/python3 -X utf8 sysop/scripts/validate_tasks.py",
            ".venv/bin/python3 -W ignore sysop/scripts/validate_tasks.py",
        ):
            assert pat.search(bad), f"guard blind to: {bad}"

    def test_a_backslash_continuation_does_not_walk_through(self):
        """Physical-line keying is the classic bypass; the scan is logical-line.

        Goes through `_scan_text` — the same body the file sweep uses — not
        through `_logical_lines` alone, which is what let the physical-line
        revert survive the battery.
        """
        text = ".venv/bin/python3 \\\n    sysop/scripts/validate_tasks.py\n"
        pat = _pattern()
        assert not any(pat.search(l) for l in text.splitlines()), "premise gone"
        assert _scan_text(text), "continuation walked through the real scanner"

    def test_a_bash_rule_line_is_still_skipped_by_the_real_scanner(self):
        """The `Bash(` skip is load-bearing and must live in the scanner too."""
        assert not _scan_text(
            '- `Bash(.venv/bin/python3 sysop/scripts/validate_tasks.py:*)` — back-compat'
        )

    def test_the_bash_skip_is_a_declared_gap_not_an_oversight(self):
        """A `Bash(` line shelters a real invocation. Declined, with the proof.

        The round's guard lens found this. The closure was BUILT — blank the
        `Bash(...)` spans, scan the remainder — and REVERTED, because the
        shipped permission bullets cite the venv rule strings outside the
        parens, so it reddened two correct lines. Both halves are asserted here
        so the decision cannot quietly rot: if someone re-attempts the closure,
        the second assertion fails and tells them why.
        """
        # The skip must stay keyed to `Bash(`, not to the bare word: widening it
        # would silently drop any line that merely mentions Bash.
        assert _scan_text(
            "Use the Bash tool: .venv/bin/python3 sysop/scripts/validate_tasks.py"
        ), "the rule skip has been widened past `Bash(` and now hides real lines"

        sheltered = ('- `Bash(python3 sysop/scripts/validate_tasks.py)` — run it as '
                     '`.venv/bin/python3 sysop/scripts/validate_tasks.py`')
        assert not _scan_text(sheltered), (
            "the Bash( shelter case is now caught — good, but confirm the two "
            "shipped permission bullets below still pass before keeping it")
        # The reason the closure was reverted: these ship and are correct.
        for shipped in (
            "- `Bash(python3 sysop/scripts/validate_tasks.py)` / "
            "`Bash(python3 sysop/scripts/validate_tasks.py:*)` and the "
            "`.venv/bin/python3 sysop/scripts/validate_tasks.py` / "
            "`.venv/bin/python3 sysop/scripts/validate_tasks.py:*` venv variants "
            "— Step 5.3 post-claim validator.",
        ):
            probe = re.sub(r"Bash\([^)]*\)", " ", shipped)
            assert _pattern().search(probe), (
                "span-blanking no longer reddens this shipped bullet — the "
                "closure may now be safe to adopt; re-check both directions")

    def test_variable_held_interpreter_is_now_caught(self):
        """The bypass the author-side pass declined — closed on the round's proof.

        The declension read "the judgement no pattern encodes". The guard lens
        wrote that pattern in about twenty lines with zero false positives, and
        the rule holds a declined survivor to impossible-in-kind rather than
        unattempted. So it is closed rather than argued for.
        """
        blind = "PY=.venv/bin/python3\n$PY sysop/scripts/validate_tasks.py\n"
        assert _variable_held_hits(blind), "blind variable-held case still invisible"
        assert _scan_text(blind), "the scanner does not consume the new predicate"

    def test_the_probed_resolvers_stay_green(self):
        """Why it was declined in the first place — that reason must still hold.

        A probed resolver always assigns a non-venv fallback too. If this ever
        reddens, the closure has become Phase 175's failure mode and should be
        reverted, not softened.
        """
        for resolver in (
            'if [[ -x "${MAIN_REPO_ROOT}/.venv/bin/python3" ]]; then\n'
            '  PYTHON="${MAIN_REPO_ROOT}/.venv/bin/python3"\n'
            'else\n'
            '  PYTHON="python3"\n'
            'fi\n'
            'exec "$PYTHON" "${SCRIPT_DIR}/run_checks_impl.py" --repo-root "$REPO_ROOT"\n',
            'RC_PY="$MAIN_ROOT/.venv/bin/python3"\n'
            'RC_PY="$MAIN_ROOT/venv/bin/python3"\n'
            'RC_PY="python3"\n'
            '"$RC_PY" sysop/scripts/validate_tasks.py\n',
        ):
            assert not _variable_held_hits(resolver), resolver

    def test_the_real_probed_resolvers_in_the_tree_stay_green(self):
        """Not synthetic fixtures — the actual shipped files.

        The round found the residual paragraph naming TWO such files when the
        tree has FOUR (both git-hook examples too): "the filed N was really M",
        which is the finding this whole phase is built on. Derived from the tree
        so the count cannot go stale a second time.
        """
        checked = 0
        for path in _shipped_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            assigns = (_ASSIGN_RE.match(l) for _, l in _logical_lines(text))
            if not any("venv/bin/" in m.group(2) for m in assigns if m):
                continue
            checked += 1
            assert not _variable_held_hits(text), (
                f"probed resolver reddened: {path.relative_to(REPO_ROOT)}")
        assert checked >= 4, (
            f"expected >=4 shipped files assigning a venv interpreter, saw {checked}")

    def test_narrowed_residuals_other_environment_dir_spellings(self):
        """What stays uncovered, with its reason — narrowed, not the old claim.

        The first draft called variable-held "the one bypass NOT closed", which
        was wrong twice: it is now closed, and it was never the only one. These
        survive because the predicate is anchored on the literal `venv/bin/`
        segment, and widening it to "any interpreter under any environment
        directory" is what would start reddening ordinary absolute paths.
        `.venv/` is this project's house style and the only spelling any shipped
        file uses. The assertion fails loudly if one ever becomes covered, so
        the record gets updated instead of quietly drifting.
        """
        pat = _pattern()
        for uncovered in (
            '.env/bin/python3 sysop/scripts/validate_tasks.py',
            '.tox/py311/bin/python3 sysop/scripts/validate_tasks.py',
            '/opt/conda/envs/proj/bin/python3 sysop/scripts/validate_tasks.py',
        ):
            assert not pat.search(uncovered), (
                "a declared residual is now COVERED — good, but update the "
                f"record instead of leaving this assertion inverted: {uncovered}")

    def test_the_guard_does_not_redden_correct_lines(self):
        """Phase 175's failure mode: a guard that reds on correct prose.

        Every one of these ships today and must stay green.
        """
        pat = _pattern()
        for ok in (
            "fix: python3 -m venv .venv && .venv/bin/pip install pyyaml",
            'if [[ -x "${MAIN_REPO_ROOT}/.venv/bin/python3" ]]; then',
            '  PYTHON="${REPO_ROOT}/.venv/bin/python3"',
            "name it by its venv path explicitly: `.venv/bin/pytest`, `.venv/bin/bean-check`",
            "   Tried .venv/bin/python3 and venv/bin/python3 under ${MAIN_REPO_ROOT}",
            # Verbatim from claim-task/SKILL.md:170 and document-work:209. An
            # earlier draft dropped the "no `&&` compound" clause and presented
            # the paraphrase as a shipped line — the failure mode this repo's
            # Phase 142 and 161 rounds both fired on.
            "# `python3` command word (not `.venv/bin/python3`, no PATH prefix, "
            "no `&&` compound) so",
            "python3 sysop/scripts/validate_tasks.py",
            # Found by the round's execution lens: the stem alternation had no
            # left boundary, so a legitimate "run one test" line reddened.
            # `CONTRIBUTING.md` is scanned and is where such a line belongs.
            ".venv/bin/pytest tests/test_validate_tasks.py",
            ".venv/bin/pytest tests/test_next_task.py -q",
            ".venv/bin/pytest -k validate_tasks.py",
            ".venv/bin/pytest tests/test_scope_overlap.py",
            # The interpreter narrowing handles the four above. THIS one is what
            # the left boundary is for — a venv python running a test FILE whose
            # name merely ends in a shipped stem. Without the boundary the
            # prefix swallows `tests/test_` and the stem matches.
            ".venv/bin/python3 tests/test_validate_tasks.py",
            ".venv/bin/python3 -m pytest tests/test_next_task.py",
        ):
            assert not pat.search(ok), f"guard reddens a correct line: {ok}"


# --------------------------------------------------------------------------
# Guard 2 — execution
# --------------------------------------------------------------------------

# (script argv, exit code, stdout marker) — a marker, not merely rc==0, so a
# script that resolves nothing and prints nothing cannot pass. Phase 182's round
# found nine of ten assertions in the sibling file were negative and vacuous.
INVOCATIONS = [
    (["sysop/scripts/validate_tasks.py"], 0, "OK:"),
    (["sysop/scripts/next_task.py"], 0, "## Next Task"),
    (["sysop/scripts/scope_overlap.py", "FEAT-0001"], 0, "No work in flight"),
    (["sysop/scripts/archive_review_tasks.py"], 0, "No merged/complete batches"),
]


@pytest.fixture(scope="module")
def yamlless_bin(tmp_path_factory):
    """A directory whose `python3` is a real interpreter that cannot import yaml.

    Prepended to PATH so the bare command word resolves to it. Shadowing via
    PYTHONPATH (not a stub that exits 1) keeps the interpreter fully functional,
    so a "fix" that merely deleted the resolution loop would still fail.
    """
    d = tmp_path_factory.mktemp("yamlless_bin")
    (d / "yaml.py").write_text('raise ImportError("No module named \'yaml\'")\n')
    shim = d / "python3"
    shim.write_text(f'#!/bin/sh\nPYTHONPATH="{d}" exec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return d


@pytest.fixture
def consumer(tmp_path):
    root = tmp_path / "proj"
    (root / "sysop" / "scripts").mkdir(parents=True)
    for name in ("validate_tasks.py", "next_task.py", "scope_overlap.py",
                 "archive_review_tasks.py", "_log.py"):
        shutil.copyfile(SCRIPTS / name, root / "sysop" / "scripts" / name)
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 1\n\n"
        "phases:\n  - number: 1\n    title: \"P1\"\n    status: in_progress\n"
        "    current_focus: true\n\n"
        "tasks:\n  - id: FEAT-0001\n    title: A sample task\n    phase: 1\n"
        "    status: open\n    effort: Low\n    blast_radius: single-file\n"
        "    user_action: false\n    depends_on: []\n    surfaced_by: []\n"
        "    body: open/FEAT-0001.md\n"
    )
    (root / "tasks" / "open" / "FEAT-0001.md").write_text(
        "# FEAT-0001\n\n## Key files\n\n- `src/pay.py`\n"
    )
    (root / "review_tasks.md").write_text("# Review Tasks\n")
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True)
    return root


def _venv_with_yaml(root: Path, kind: str) -> None:
    """A venv-shaped site-packages carrying a real PyYAML, plus a bin/python3.

    Copied rather than symlinked so the fixture cannot pass by accident through
    the running interpreter's own sys.path.
    """
    tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = root / kind / "lib" / tag / "site-packages"
    site.mkdir(parents=True)
    import yaml
    src = Path(yaml.__file__).parent
    dst = site / "yaml"
    dst.mkdir()
    for f in src.iterdir():
        if f.is_file():
            shutil.copyfile(f, dst / f.name)
    bindir = root / kind / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    shim = bindir / "python3"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)


def _shell(cmd: str, cwd: Path, yamlless_bin: Path):
    """Run a literal command STRING through a shell, as a skill's bash block does.

    Not `[sys.executable, script]` — an absolute interpreter path can never
    reproduce exit 127, which is the whole defect.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env["PATH"] = f"{yamlless_bin}:{env['PATH']}"
    return subprocess.run(cmd, shell=True, cwd=str(cwd), env=env,
                          capture_output=True, text=True)


class TestItActuallyRuns:
    @pytest.mark.parametrize("argv,code,marker", INVOCATIONS)
    def test_bare_python3_runs_on_a_plain_venv_layout(
        self, consumer, yamlless_bin, argv, code, marker
    ):
        """`venv/` (no leading dot) — the layout the shipped word used to break on."""
        _venv_with_yaml(consumer, "venv")
        assert not (consumer / ".venv").exists()
        r = _shell(f"python3 {' '.join(argv)}", consumer, yamlless_bin)
        assert r.returncode == code, (r.returncode, r.stdout[-400:], r.stderr[-400:])
        assert marker in r.stdout, (r.stdout[:400], r.stderr[:400])

    @pytest.mark.parametrize("argv,code,marker", INVOCATIONS)
    def test_the_old_command_word_is_exit_127_there(
        self, consumer, yamlless_bin, argv, code, marker
    ):
        """The defect itself, executed. This is what Phase 183 removed."""
        _venv_with_yaml(consumer, "venv")
        r = _shell(f".venv/bin/python3 {' '.join(argv)}", consumer, yamlless_bin)
        assert r.returncode == 127, (
            "the pre-183 command word did NOT fail on a venv/ layout — the "
            "fixture no longer reproduces the defect this phase fixed",
            r.returncode, r.stdout[-300:], r.stderr[-300:],
        )

    @pytest.mark.parametrize("argv,code,marker", INVOCATIONS)
    def test_no_regression_on_a_dot_venv_consumer(
        self, consumer, yamlless_bin, argv, code, marker
    ):
        """The half a swap like this usually breaks: the consumer who WAS fine.

        On `.venv/` both words must agree — same rc, same marker — or the fix
        traded one broken population for another.
        """
        _venv_with_yaml(consumer, ".venv")
        bare = _shell(f"python3 {' '.join(argv)}", consumer, yamlless_bin)
        venv = _shell(f".venv/bin/python3 {' '.join(argv)}", consumer, yamlless_bin)
        assert bare.returncode == code, (bare.returncode, bare.stderr[-400:])
        assert marker in bare.stdout, bare.stdout[:400]
        assert venv.returncode == bare.returncode, (venv.returncode, bare.returncode)
        assert marker in venv.stdout, venv.stdout[:400]

    @pytest.mark.parametrize("argv,code,marker", INVOCATIONS)
    def test_no_venv_anywhere_degrades_by_name_not_by_127(
        self, consumer, yamlless_bin, argv, code, marker
    ):
        """The cell the record's matrix claimed but the suite did not pin.

        With no venv at all and a yaml-less `python3`, the bare word must still
        RUN: the two scripts that answer without yaml succeed, and the two that
        need it exit 2 naming the fix. The venv word is 127 — a shell error that
        says nothing about PyYAML — which is the difference this phase bought.
        """
        assert not (consumer / ".venv").exists() and not (consumer / "venv").exists()
        bare = _shell(f"python3 {' '.join(argv)}", consumer, yamlless_bin)
        assert bare.returncode in (0, 2), (bare.returncode, bare.stderr[-300:])
        if bare.returncode == 2:
            assert "requires PyYAML" in bare.stderr, bare.stderr[:300]
            assert "python3 -m venv .venv" in bare.stderr, bare.stderr[:300]
        else:
            assert marker in bare.stdout, bare.stdout[:300]
        dead = _shell(f".venv/bin/python3 {' '.join(argv)}", consumer, yamlless_bin)
        assert dead.returncode == 127, (dead.returncode, dead.stderr[-300:])

    @pytest.mark.parametrize("argv,code,marker", INVOCATIONS)
    def test_bare_python3_works_from_a_linked_worktree(
        self, consumer, yamlless_bin, argv, code, marker
    ):
        """A worktree never carries a venv, even when the main checkout does.

        This is the arm Phase 182 added git-common-dir for, and the reason the
        venv command word is wrong even on a `.venv/` consumer.
        """
        _venv_with_yaml(consumer, ".venv")
        wt = consumer.parent / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "wt", str(wt)],
                       cwd=consumer, check=True, capture_output=True)
        assert not (wt / ".venv").exists()
        r = _shell(f"python3 {' '.join(argv)}", wt, yamlless_bin)
        assert r.returncode == code, (r.returncode, r.stdout[-400:], r.stderr[-400:])
        assert marker in r.stdout, (r.stdout[:400], r.stderr[:400])
        dead = _shell(f".venv/bin/python3 {' '.join(argv)}", wt, yamlless_bin)
        assert dead.returncode == 127, (dead.returncode, dead.stderr[-300:])
