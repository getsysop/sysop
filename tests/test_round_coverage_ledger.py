"""Phase 149 — the Tier-0 round coverage ledger.

Phase 138 measured coverage *inside* the fan-out path, so a round that never
dispatched was never measured at all. Provenance: two ordinary review requests
against a real 1,561-file repository on a surface where fan-out demonstrably
works (8 dispatch events in the control run) dispatched nothing, reviewed solo,
opened 13 and 27 files (~0.8% / ~1.7%), and put the *dispatch-set* sizes —
"1,477 reviewable", "955 to audit" — in the round header. Every finding was
correctly `[verified]`; the round simply had no coverage measure of its own.

Three layers, all tested here:

- **The ledger** (§4) — a mandatory coverage line in the durable round header
  of all three audit skills, carrying manifest/opened/grepped/workers.
- **The receipt** (§1) — the marker-clear step's machine-readable copy, so the
  number survives the session. The heredoc body is extracted from the shipped
  SKILL.md and executed here (the test_round_markers.py pattern), so the thing
  under test is the thing that ships.
- **The readers** (§2 `/sitrep`, §3 `self_check.sh`) — which report only
  *self-contradictions*: a round whose own numbers refute its own label, or one
  that closed with no numbers. A thin round that labelled itself thin is
  correct and must stay silent.

The hard constraint this phase inherits (§4): Tier 2's evidence footer stays
fan-out-only. A solo session emitting an Assigned/Opened worker footer would be
fabricating a worker that never existed — considered and rejected in Phase 138,
and the ledger exists precisely so that rejection stays affordable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "codebase-review": REPO_ROOT / "core/skills/codebase-review/SKILL.md",
    "security-audit": REPO_ROOT / "core/skills/security-audit/SKILL.md",
}
TEST_AUDIT = REPO_ROOT / "core/skills/test-audit/SKILL.md"
FANOUT = REPO_ROOT / "core/skills/_shared/fanout-evidence.md"
MARKER_REL = "sysop/runtime/pending-rounds"
RECEIPT_REL = "sysop/runtime/round-receipts"

FULL_LINE = "Full · manifest 1477 · opened 13 · grepped 220 · workers 0, solo: no primitive"

from tests.test_round_markers import (  # noqa: E402
    _marker_path, _repo, _run, clear_src, write_src,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _open_round(root: Path, skill: str = "codebase-review") -> Path:
    w = _run(write_src(skill), root, skill, "")
    assert w.returncode == 0, w.stderr
    return _marker_path(w.stdout)


def _receipts(root: Path) -> list[Path]:
    d = root / RECEIPT_REL
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _write_round(root: Path, line: str | None,
                 title: str = "Code Quality Review", label: str = "code quality",
                 batches: bool = True) -> None:
    """Write the `review_tasks.md` a round would have just committed. The clear
    step reads its ledger back out of THIS file — nothing is passed by argument.

    A bare value is wrapped in the shipped `> **Coverage (…):**` blockquote form
    so every test exercises the shape Step 5b actually writes; pass a string
    already starting with `>` to control the wrapper directly.
    """
    body = f"# Code Review Tasks\n\n## Round 1 (2026-07-25) — {title}\n\n"
    if line is not None:
        if not line.lstrip().startswith(">"):
            line = f"> **Coverage ({label}):** {line}"
        body += line + "\n\n"
    if batches:
        body += ("### Batch 1 — Thing `Pending`\n\n> **Branch:** `x`\n\n"
                 "- [ ] **TASK-1**: t 🟢\n")
    (root / "review_tasks.md").write_text(body, encoding="utf-8")


def _close(root: Path, marker: Path,
           skill: str = "codebase-review") -> subprocess.CompletedProcess:
    return _run(clear_src(skill), root, str(marker))


def _only_receipt(root: Path) -> dict:
    found = _receipts(root)
    assert len(found) == 1, f"expected exactly one receipt, got {found}"
    return json.loads(found[0].read_text())


# ── §1 the receipt ──────────────────────────────────────────────────────────


def test_clear_writes_a_receipt_carrying_the_parsed_ledger(tmp_path):
    for skill, title in (("codebase-review", "Code Quality Review"),
                         ("security-audit", "OWASP Security Audit")):
        root = _repo(tmp_path / f"ok-{skill}")
        marker = _open_round(root, skill)
        label = "security" if skill == "security-audit" else "code quality"
        _write_round(root, FULL_LINE, title=title, label=label)
        r = _close(root, marker, skill)
        assert r.returncode == 0, r.stderr
        rec = _only_receipt(root)
        assert rec["skill"] == skill
        assert rec["kind"] == "Full"
        assert rec["manifest"] == 1477
        assert rec["opened"] == 13
        assert rec["grepped"] == 220
        assert rec["workers"] == 0
        assert rec["solo_reason"] == "no primitive"
        # the receipt stores the committed line verbatim, wrapper and all
        assert rec["line"].endswith(FULL_LINE)
        assert rec["line"].startswith("> **Coverage")
        assert rec["started"] and rec["completed"]
        # the marker is still cleared, and the operator sees the numbers now
        assert not marker.exists()
        assert "opened 13/1477" in r.stdout


def test_receipt_reads_the_committed_round_header_form(tmp_path):
    """The ledger is read back out of `review_tasks.md`, so the parser must
    survive the markdown wrapper and thousands separators the header ships
    with — the honest path must not be the one that yields `unreported`."""
    root = _repo(tmp_path / "hdr")
    marker = _open_round(root)
    _write_round(root, "> **Coverage (code quality):** Sampled (highest-exposure "
                       "modules) · manifest 1,477 · opened 13 · grepped 220 · "
                       "workers 0, solo: harness")
    _close(root, marker)
    rec = _only_receipt(root)
    assert rec["kind"] == "Sampled (highest-exposure modules)"
    assert rec["manifest"] == 1477
    assert rec["opened"] == 13
    assert rec["solo_reason"] == "harness"


def test_the_coverage_line_is_never_a_shell_argument(tmp_path):
    """Regression guard for the reason this is read from a file at all.

    The coverage line contains model-authored prose. Interpolated into a
    double-quoted shell argument it would run command substitution, be split by
    an embedded quote, and — if it contained `;` or `&` — split the command so
    the tail matched no allow-rule (a silent deny under auto mode, stranding the
    marker). This is the hazard `/report-issues` Step 4 and `/share-wins` fixed;
    the fix here is not to escape it but to never put it on a command line."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        opener = "python3 - <<'PY' \"<ROUND_MARKER path from Pre-flight>\""
        at = text.index(opener)
        assert text[at + len(opener)] == "\n", (
            f"{skill}: the clear step grew a second shell argument — the "
            "coverage line must be read from review_tasks.md, not passed in"
        )
        assert "not an argument" in text, skill


def test_a_reason_with_shell_metacharacters_lands_verbatim(tmp_path):
    """End-to-end proof of the above: backticks, $(), $VAR and quotes in the
    solo reason reach the receipt as written, unexecuted and unexpanded."""
    root = _repo(tmp_path / "meta")
    marker = _open_round(root)
    nasty = "no `whoami` / $(id) / $HOME / the \"small\" case"
    _write_round(root, f"Full · manifest 9 · opened 9 · grepped 0 · "
                       f"workers 0, solo: {nasty}")
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    rec = _only_receipt(root)
    assert rec["solo_reason"] == nasty
    assert rec["manifest"] == 9


def test_absent_coverage_line_records_unreported_and_still_clears(tmp_path):
    """An absent number must never read as a clean pass — and must never cost
    the marker cleanup, which would turn a completed round into a false
    abandonment report."""
    root = _repo(tmp_path / "missing")
    marker = _open_round(root)
    _write_round(root, None)
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    rec = _only_receipt(root)
    for f in ("kind", "manifest", "opened", "grepped", "workers"):
        assert rec[f] == "unreported", f
    assert "NOT on the record" in r.stdout
    assert "no coverage line found" in r.stdout
    assert not marker.exists()


def test_no_review_tasks_file_at_all_never_blocks_the_clear(tmp_path):
    root = _repo(tmp_path / "nofile")
    marker = _open_round(root)
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    assert _only_receipt(root)["manifest"] == "unreported"
    assert not marker.exists()


def test_malformed_ledger_never_blocks_the_clear(tmp_path):
    root = _repo(tmp_path / "garbage")
    marker = _open_round(root)
    _write_round(root, "> **Coverage:** ¯\\_(ツ)_/¯ manifest ??? opened lots")
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    rec = _only_receipt(root)
    assert rec["manifest"] == "unreported"
    assert rec["opened"] == "unreported"
    assert not marker.exists()


def test_partial_ledger_names_exactly_the_missing_fields(tmp_path):
    root = _repo(tmp_path / "partial")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 40 · workers 3")
    r = _close(root, marker)
    rec = _only_receipt(root)
    assert rec["manifest"] == 40 and rec["workers"] == 3
    assert rec["opened"] == "unreported" and rec["grepped"] == "unreported"
    assert "opened" in r.stdout and "grepped" in r.stdout
    assert "manifest" not in r.stdout.split("unreported field(s):")[1]


def test_an_unparseable_number_is_unreported_never_truncated(tmp_path):
    """The worst failure this parser can have — worse than not parsing at all.

    `manifest 1.477` and `manifest 1 477` are ordinary thousands separators. A
    permissive numeric class reads them as `1`, and a manifest of 1 makes the
    look-ratio check pass trivially: the collapsed round the ledger exists to
    catch becomes a clean pass, while `self_check.sh` still prints the raw line
    so the human surface looks right. A confidently WRONG number silences the
    alarm; `unreported` raises it."""
    for bad in ("1.477", "1 477", "1.5k", "1477x", "~1477"):
        root = _repo(tmp_path / f"num-{bad.replace(' ', '_').replace('~', 't')}")
        marker = _open_round(root)
        _write_round(root, f"Full · manifest {bad} · opened 13 · grepped 0 · "
                           f"workers 4")
        _close(root, marker)
        rec = _only_receipt(root)
        assert rec["manifest"] == "unreported", (
            f"`manifest {bad}` parsed as {rec['manifest']!r} — a wrong number "
            "is worse than none, because it silences the look-ratio check"
        )
        assert rec["opened"] == 13, "the well-formed siblings must still parse"


def test_the_sampling_basis_cannot_hijack_a_numeric_field(tmp_path):
    """The basis is free text the author is explicitly told to write, and it
    precedes every numeric field. A whole-line regex takes the FIRST match, so
    `Sampled (opened 3 entrypoints)` would report opened=3 over the real 600 —
    and a basis mentioning `manifest` would shrink the denominator, which is
    exactly how a collapsed round buys silence. Parse per segment."""
    cases = [
        ("Sampled (opened 3 entrypoint dirs)", "opened", 600),
        ("Sampled (manifest 40 of the pre-scan hits)", "manifest", 1000),
        ("Scoped (api, workers 2 queues)", "workers", 8),
    ]
    for i, (kind, field, expected) in enumerate(cases):
        root = _repo(tmp_path / f"hijack{i}")
        marker = _open_round(root)
        _write_round(root, f"{kind} · manifest 1000 · opened 600 · grepped 0 · "
                           f"workers 8")
        _close(root, marker)
        rec = _only_receipt(root)
        assert rec[field] == expected, (
            f"{kind!r} hijacked `{field}` → {rec[field]!r}, want {expected}"
        )
        assert rec["kind"] == kind


def test_an_unfilled_template_never_asserts_full(tmp_path):
    """Pasting the Step 5b template without filling it is a realistic slip. It
    must not record a `Full` round that nobody declared — the placeholder
    contains the word `Full`, and a scan-anywhere match would adopt it."""
    root = _repo(tmp_path / "template")
    marker = _open_round(root)
    _write_round(root, "> **Coverage (code quality):** <Full | Scoped (<area>) | "
                       "Sampled (<basis>)> · manifest <N> · opened <M> · "
                       "grepped <G> · workers <K><, solo: <reason>>")
    _close(root, marker)
    rec = _only_receipt(root)
    assert rec["kind"] == "unreported"
    assert rec["manifest"] == "unreported"


def test_kind_comes_from_the_first_segment_only(tmp_path):
    """A `Full` inside a solo reason must not relabel a Sampled round."""
    root = _repo(tmp_path / "relabel")
    marker = _open_round(root)
    _write_round(root, "Sampled (pre-scan hits) · manifest 900 · opened 20 · "
                       "grepped 0 · workers 0, solo: no Full sub-agent primitive")
    _close(root, marker)
    assert _only_receipt(root)["kind"] == "Sampled (pre-scan hits)"


def test_a_merged_round_selects_this_skills_coverage_line(tmp_path):
    """Same-day rounds merge into one header carrying one line per audit type.
    Reading the wrong one would file the quality round's coverage against the
    security audit."""
    root = _repo(tmp_path / "merged")
    marker = _open_round(root, "security-audit")
    (root / "review_tasks.md").write_text(
        "# Code Review Tasks\n\n"
        "## Round 1 (2026-07-25) — Code Quality Review + OWASP Security Audit\n\n"
        "> **Coverage (code quality):** Full · manifest 40 · opened 40 · "
        "grepped 0 · workers 4\n"
        "> **Coverage (security):** Full · manifest 12 · opened 12 · "
        "grepped 0 · workers 6\n\n"
        "### Batch 1 — X `Pending`\n", encoding="utf-8")
    _close(root, marker, "security-audit")
    rec = _only_receipt(root)
    assert rec["manifest"] == 12 and rec["workers"] == 6


def test_ambiguous_merged_lines_yield_unreported(tmp_path):
    """Two candidate lines and no way to tell them apart: record nothing rather
    than the other round's numbers. `unreported` is loud; wrong is silent."""
    root = _repo(tmp_path / "ambiguous")
    marker = _open_round(root)
    (root / "review_tasks.md").write_text(
        "# Code Review Tasks\n\n## Round 1 (2026-07-25) — Mixed\n\n"
        "> **Coverage (alpha):** Full · manifest 40 · opened 40 · workers 4\n"
        "> **Coverage (beta):** Full · manifest 12 · opened 12 · workers 6\n\n"
        "### Batch 1 — X `Pending`\n", encoding="utf-8")
    _close(root, marker)
    assert _only_receipt(root)["manifest"] == "unreported"


def test_only_the_newest_round_header_is_read(tmp_path):
    """`review_tasks.md` accumulates rounds; the receipt describes THIS one."""
    root = _repo(tmp_path / "prior")
    marker = _open_round(root)
    (root / "review_tasks.md").write_text(
        "# Code Review Tasks\n\n## Round 1 (2026-07-01) — Code Quality Review\n\n"
        "> **Coverage (code quality):** Full · manifest 5 · opened 5 · "
        "grepped 0 · workers 1\n\n"
        "### Batch 1 — old `Merged`\n\n- [x] **TASK-1**: t 🟢\n\n"
        "## Round 2 (2026-07-25) — Code Quality Review\n\n"
        "> **Coverage (code quality):** Full · manifest 88 · opened 80 · "
        "grepped 4 · workers 6\n\n"
        "### Batch 2 — new `Pending`\n", encoding="utf-8")
    _close(root, marker)
    assert _only_receipt(root)["manifest"] == 88


def test_a_coverage_line_below_the_first_batch_is_not_read(tmp_path):
    """The ledger is round-level metadata and lives above the first batch. A
    `> Coverage` inside a batch body belongs to that batch's prose, not the
    round, and reading it would attribute batch text to the whole round."""
    root = _repo(tmp_path / "belowbatch")
    marker = _open_round(root)
    (root / "review_tasks.md").write_text(
        "# Code Review Tasks\n\n## Round 1 (2026-07-25) — Code Quality Review\n\n"
        "### Batch 1 — X `Pending`\n\n"
        "> **Coverage (code quality):** Full · manifest 3 · opened 3 · "
        "grepped 0 · workers 1\n", encoding="utf-8")
    _close(root, marker)
    assert _only_receipt(root)["manifest"] == "unreported"


def test_no_receipt_when_there_was_no_marker_to_clear(tmp_path):
    """A receipt asserts 'a round closed here'. With no marker there is no
    round, and on a disarmed install writing one would dirty the tree the
    marker step deliberately refused to touch."""
    root = _repo(tmp_path / "nomarker")
    _write_round(root, FULL_LINE)
    r = _close(root, root / MARKER_REL / "codebase-review.1-1.pending")
    assert r.returncode == 0, r.stderr
    assert "nothing to clear" in r.stdout
    assert _receipts(root) == []


def test_no_receipt_when_the_nonce_refuses(tmp_path):
    """A refused removal means the marker is someone else's round; attributing a
    receipt to it would file this session's coverage under their nonce."""
    root = _repo(tmp_path / "refuse")
    d = root / MARKER_REL
    d.mkdir(parents=True)
    victim = d / "security-audit.111-1.pending"
    victim.write_text("skill: security-audit\nstarted: x\nnonce: 999-9\n")
    _write_round(root, FULL_LINE)
    r = _close(root, victim, "security-audit")
    assert "REFUSING to remove" in r.stdout
    assert victim.exists()
    assert _receipts(root) == []


def test_the_receipt_filename_cannot_escape_the_receipts_dir(tmp_path):
    """`skill` comes from the marker BODY, which the nonce guard already treats
    as possibly hand-built. Unsanitized it builds a path: a `../..` lands the
    receipt outside the gitignored runtime dir, and an un-ignored file at the
    repo root makes /review-close read `dirty` and silently SKIP the close."""
    root = _repo(tmp_path / "traversal")
    d = root / MARKER_REL
    d.mkdir(parents=True)
    m = d / "codebase-review.55-1.pending"
    m.write_text("skill: ../../../PWNED\nstarted: x\nnonce: 55-1\n")
    _write_round(root, FULL_LINE)
    r = _close(root, m)
    assert r.returncode == 0, r.stderr
    assert not (root.parent / "PWNED.55-1.json").exists()
    assert not (root / "PWNED.55-1.json").exists()
    found = _receipts(root)
    assert len(found) == 1
    # sanitized to a flat name — no separator, so it cannot leave the dir
    assert "/" not in found[0].name and os.sep not in found[0].name
    assert found[0].parent == root / RECEIPT_REL
    assert found[0].resolve().is_relative_to((root / RECEIPT_REL).resolve())
    assert not m.exists(), "the marker must still be cleared"


def test_receipt_history_is_bounded_at_fifty(tmp_path):
    root = _repo(tmp_path / "bounded")
    d = root / RECEIPT_REL
    d.mkdir(parents=True)
    old = time.time() - 90_000
    for i in range(60):
        p = d / f"codebase-review.old-{i:03d}.json"
        p.write_text(json.dumps({"skill": "codebase-review", "opened": i}) + "\n")
        os.utime(p, (old + i, old + i))
    marker = _open_round(root)
    _write_round(root, FULL_LINE)
    _close(root, marker)
    kept = _receipts(root)
    assert len(kept) == 50, f"expected the newest 50, got {len(kept)}"
    names = {p.name for p in kept}
    assert "codebase-review.old-000.json" not in names, "oldest should be pruned"
    assert "codebase-review.old-059.json" in names, "newest should survive"


def test_one_unreadable_entry_cannot_disable_the_prune(tmp_path):
    """A whole-loop `except OSError` would let a single dangling symlink (or a
    file another process deleted mid-sort) abort the prune permanently — the
    bound would silently stop existing from that round on."""
    root = _repo(tmp_path / "prune-robust")
    d = root / RECEIPT_REL
    d.mkdir(parents=True)
    old = time.time() - 90_000
    for i in range(60):
        p = d / f"codebase-review.old-{i:03d}.json"
        p.write_text("{}\n")
        os.utime(p, (old + i, old + i))
    (d / "dangling.json").symlink_to(d / "nonexistent-target.json")
    marker = _open_round(root)
    _write_round(root, FULL_LINE)
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    remaining = list(d.glob("*.json"))
    assert len(remaining) <= 51, (
        f"prune aborted — {len(remaining)} receipts kept; one unreadable entry "
        "disabled the bound"
    )


def test_the_receipt_write_leaves_no_temp_file(tmp_path):
    """Written via tempfile + os.replace (the Phase 50/108 atomic convention) so
    a /sitrep glob concurrent with a close never reads a torn receipt."""
    root = _repo(tmp_path / "atomic")
    marker = _open_round(root)
    _write_round(root, FULL_LINE)
    _close(root, marker)
    d = root / RECEIPT_REL
    assert list(d.glob("*.tmp")) == []
    # Atomicity itself cannot be observed from outside a completed write, so
    # the property is pinned at the source: BOTH halves, because keeping the
    # `os.replace` while aiming `tmp` at the destination is a silent no-op that
    # leaves no stray file for the check above to catch.
    for skill, path in SKILLS.items():
        src = path.read_text()
        assert 'tmp = d / (dst.name + ".tmp")' in src, skill
        assert "os.replace(tmp, dst)" in src, skill


def test_both_skills_ship_the_identical_receipt_writer():
    """One contract, two copies. A drift between them is how a fix lands in the
    quality round and silently misses the security round (or the reverse)."""
    def heredoc(p: Path) -> str:
        t = p.read_text(encoding="utf-8")
        s = t.index("python3 - <<'PY' \"<ROUND_MARKER path from Pre-flight>\"")
        return t[s:t.index("\nPY\n", s)]

    bodies = {k: heredoc(v) for k, v in SKILLS.items()}
    assert len(set(bodies.values())) == 1, "the 5f heredocs have diverged"
    assert "round-receipts" in next(iter(bodies.values()))


def test_round_open_probes_the_gitignore_of_both_runtime_dirs(tmp_path):
    """The round writes to pending-rounds/ AND round-receipts/. Probing only the
    first passes on a hand-narrowed .gitignore and lets the receipt dirty the
    tree — the Phase-99.1 chain (un-ignored runtime file → /review-close Step 2a
    reads `dirty` → auto-SKIP → the close silently refuses)."""
    root = _repo(tmp_path / "halfignored",
                 gitignore="sysop/runtime/pending-rounds/\n")
    r = _run(write_src("codebase-review"), root, "codebase-review", "")
    assert r.returncode == 0, r.stderr
    assert "not gitignored" in r.stdout
    assert "round-receipts" in r.stdout
    assert "ROUND_MARKER=" not in r.stdout, (
        "a round opened despite its receipt dir being untracked"
    )


# ── §2 /sitrep reads the receipt ────────────────────────────────────────────


def _plant_receipt(root: Path, **fields) -> Path:
    d = root / RECEIPT_REL
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "skill": "codebase-review", "nonce": "1-1", "started": "x",
        "completed": "y", "kind": "Full", "manifest": 100, "opened": 90,
        "grepped": 5, "workers": 4, "solo_reason": "", "line": "…",
    }
    rec.update(fields)
    p = d / f"{rec['skill']}.{rec['nonce']}.json"
    # ensure_ascii=False mirrors the shipped writer: the ledger's `·` separator
    # must land as UTF-8, not as a · escape self_check.sh would print raw.
    p.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def _kinds(root: Path) -> list[str]:
    import sitrep_survey
    return [d.kind for d in sitrep_survey._find_discrepancies([], [], {}, root)]


def _detail(root: Path, kind: str) -> str:
    import sitrep_survey
    for d in sitrep_survey._find_discrepancies([], [], {}, root):
        if d.kind == kind:
            return d.detail
    raise AssertionError(f"{kind} not reported; got {_kinds(root)}")


def test_sitrep_silent_with_no_receipts(tmp_path):
    assert _kinds(_repo(tmp_path / "none")) == []


def test_sitrep_silent_on_a_healthy_full_round(tmp_path):
    root = _repo(tmp_path / "healthy")
    _plant_receipt(root)
    assert _kinds(root) == []


def test_sitrep_counts_grep_as_looking(tmp_path):
    """The Tier-0 sum, on its own authority: an honestly *sparse* pass — few relevant files
    opened, the rest grepped — is full coverage of a sparse scope, not a gap.
    Dropping `grepped` from the sum would flag exactly the review discipline the
    contract endorses, and a check that fires on the good case gets ignored.

    Attributed to "Tier 2's rule, inherited" until Phase 206: Tier 2's merge check
    reads `Opened` against `Assigned` and sums nothing, and the evidence footer has
    never collected a search-file count, so there was no Tier-2 sum to inherit. The
    ~1/3 threshold IS shared with Tier 2; the arithmetic is not."""
    root = _repo(tmp_path / "sparse")
    _plant_receipt(root, manifest=100, opened=10, grepped=80, workers=3)
    assert _kinds(root) == []


def test_sitrep_flags_a_full_round_that_looked_at_a_fraction(tmp_path):
    """The motivating failure, reduced: Full over 1,477 with 13 opened."""
    root = _repo(tmp_path / "collapsed")
    _plant_receipt(root, manifest=1477, opened=13, grepped=220, workers=0,
                   solo_reason="no primitive")
    detail = _detail(root, "full round covered a fraction of its scope")
    assert "1477" in detail and "233" in detail and "15.8%" in detail
    assert "opened 13" in detail


def test_sitrep_exempts_a_sampled_round_with_identical_numbers(tmp_path):
    """The relabel is the whole point: a round that says it sampled is honest,
    and flagging it would train the consumer to ignore the signal."""
    root = _repo(tmp_path / "sampled")
    _plant_receipt(root, kind="Sampled (highest-exposure)", manifest=1477,
                   opened=13, grepped=220, workers=0, solo_reason="scope")
    assert _kinds(root) == []


def test_sitrep_exempts_a_small_scoped_round(tmp_path):
    """An incremental round's manifest is its own small scope — measuring it
    against the repo would make every honest incremental round a collapse."""
    root = _repo(tmp_path / "incremental")
    _plant_receipt(root, kind="Scoped (frontend/)", manifest=4, opened=4,
                   grepped=0, workers=0, solo_reason="4 files")
    assert _kinds(root) == []


def test_sitrep_flags_an_unreported_ledger(tmp_path):
    root = _repo(tmp_path / "silent")
    _plant_receipt(root, manifest="unreported", opened="unreported")
    detail = _detail(root, "round coverage unreported")
    assert "manifest" in detail and "opened" in detail


def test_sitrep_flags_solo_without_a_stated_reason(tmp_path):
    """Solo is legitimate; an *unexplained* solo on a Full round is the defect."""
    root = _repo(tmp_path / "unexplained")
    _plant_receipt(root, manifest=100, opened=90, grepped=5, workers=0,
                   solo_reason="")
    assert "solo round with no stated reason" in _kinds(root)


def test_sitrep_accepts_solo_with_a_stated_reason(tmp_path):
    root = _repo(tmp_path / "explained")
    _plant_receipt(root, manifest=100, opened=90, grepped=5, workers=0,
                   solo_reason="no sub-agent primitive on this harness")
    assert _kinds(root) == []


def test_sitrep_judges_only_the_newest_receipt_per_skill(tmp_path):
    """Older receipts are history, not an open problem — a fixed round must not
    keep reporting the round it fixed."""
    root = _repo(tmp_path / "newest")
    bad = _plant_receipt(root, nonce="old", manifest=1477, opened=1, grepped=0,
                         workers=0, solo_reason="x")
    os.utime(bad, (time.time() - 9000, time.time() - 9000))
    _plant_receipt(root, nonce="new")
    assert _kinds(root) == []


def test_sitrep_judges_each_skill_independently(tmp_path):
    root = _repo(tmp_path / "perskill")
    _plant_receipt(root, skill="codebase-review")
    _plant_receipt(root, skill="security-audit", manifest=955, opened=27,
                   grepped=0, workers=0, solo_reason="x")
    detail = _detail(root, "full round covered a fraction of its scope")
    assert "security-audit" in detail


def test_sitrep_survives_a_corrupt_receipt(tmp_path):
    """A probe that breaks /sitrep would be a worse defect than the silence it
    reports on."""
    root = _repo(tmp_path / "corrupt")
    d = root / RECEIPT_REL
    d.mkdir(parents=True)
    (d / "codebase-review.x.json").write_text("{not json")
    (d / "codebase-review.y.json").write_text("[]")
    assert _kinds(root) == []


# ── §3 self_check.sh reads the receipt (the loop-mode surface) ──────────────


def _self_check_output(root: Path) -> str:
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(
        ["bash", str(REPO_ROOT / "core/companion/scripts/self_check.sh")],
        cwd=str(root), capture_output=True, text=True, env=env,
    )
    return r.stdout + r.stderr


def test_self_check_surfaces_the_last_round_coverage(tmp_path):
    """Loop mode ships no /sitrep, so this is the only place a loop consumer
    sees a collapsed round."""
    root = _repo(tmp_path / "sc")
    _plant_receipt(root, line=FULL_LINE)
    assert "last round coverage: " + FULL_LINE in _self_check_output(root)


def test_self_check_names_an_unreported_round(tmp_path):
    root = _repo(tmp_path / "sc-silent")
    _plant_receipt(root, opened="unreported", line="")
    out = _self_check_output(root)
    assert "no coverage line recorded" in out
    assert "reads as a clean pass" in out


def test_self_check_picks_the_newest_receipt_not_the_last_name(tmp_path):
    """Receipts are `<skill>.<epoch>-<pid>.json`, so a lexical sort ranks by
    SKILL NAME first — `security-audit.*` beats a newer `codebase-review.*`
    every time. Reporting a stale round as the current one is worse than
    reporting none, because it is the freshness of this line that a consumer
    trusts when deciding whether the last round covered anything."""
    root = _repo(tmp_path / "sc-order")
    old = _plant_receipt(root, skill="security-audit", nonce="1785026816-4888",
                         line="STALE-ROUND-LINE")
    new = _plant_receipt(root, skill="codebase-review", nonce="1785099999-12",
                         line="FRESH-ROUND-LINE")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    os.utime(new, (time.time(), time.time()))
    assert old.name > new.name, "fixture must reproduce the lexical inversion"
    out = _self_check_output(root)
    assert "FRESH-ROUND-LINE" in out
    assert "STALE-ROUND-LINE" not in out


def test_self_check_is_silent_without_receipts(tmp_path):
    assert "last round coverage" not in _self_check_output(_repo(tmp_path / "sc-none"))


# ── §3b the low-look boundary is ONE rule with three implementations ────────
#
# Phase 192 / upstream #367. The rule "a Full round that looked at under 1/3 of
# its manifest contradicts itself" is now implemented three times: the skills'
# Step 5f receipt block (write time, added by this phase), `sitrep_survey.py`
# (`LOW_LOOK_RATIO`), and `self_check.sh` (a literal `* 3`, the loop-mode-only
# surface). Before this phase there were two and NOTHING tested the coupling —
# `grep -rn LOW_LOOK_RATIO tests/` returned nothing — so the constants could
# diverge silently and the write side did not exist at all.
#
# These tests do not grep for the number. They drive all three surfaces with
# the SAME numbers and assert the three verdicts agree, so changing one copy
# alone reddens the suite at a boundary triple rather than at a string.


# (manifest, opened, grepped, expected_contradiction) — straddling looked*3 < manifest
#
# Every triple here is driven through ALL THREE implementations. The round's
# lens 3 showed the first nine were too narrow in three specific ways, each of
# which let a real defect through: no manifest below 9 (so `manifest > 0` could
# be relaxed to `manifest > 5` unnoticed), and — in the cases list's companion
# `_kind_for` below — no parenthesised kind and no non-integer `grepped`.
_BOUNDARY_CASES = [
    (1477, 13, 220, True),    # the motivating failure: 233/1477 = 15.8%
    (1000, 333, 0, True),     # just under: 999 < 1000
    (1000, 334, 0, False),    # exactly at: 1002 !< 1000
    (1000, 400, 200, False),  # healthy: 1800 !< 1000
    (100, 33, 0, True),       # small scope, same rule
    (100, 34, 0, False),
    (9, 3, 0, False),         # grepped counts toward `looked` on every surface
    (9, 1, 2, False),
    (9, 1, 1, True),
    (3, 0, 0, True),          # tiny manifest: `manifest > 0` is the only guard
    (4, 1, 0, True),          # and it must not become `manifest > 5`
    (1, 0, 0, True),
    (0, 0, 0, False),         # zero manifest: no division, no warning
]

# Kind spellings the shipped `parse_coverage` regex admits. `Full (…)` is a
# real, produced value — the round narrowed the write side to `== "Full"` and
# every one of the nine original triples still passed, because all nine used
# the bare spelling.
_FULL_SPELLINGS = ["Full", "Full (whole repo)", "Full (excluding vendored)"]


def _skill_warns(tmp_path, manifest, opened, grepped, skill="codebase-review",
                 kind="Full"):
    """Run the real Step 5f heredoc and report whether it warned."""
    root = _repo(tmp_path)
    marker = _open_round(root, skill)
    _write_round(
        root,
        f"{kind} · manifest {manifest} · opened {opened} · grepped {grepped} · workers 4",
        label=("security" if skill == "security-audit" else "code quality"),
    )
    r = _close(root, marker, skill)
    assert r.returncode == 0, r.stderr
    assert "round-marker: cleared" in r.stdout, "the marker must always clear"
    return "round-receipt: LOW-LOOK" in r.stdout


def _sitrep_flags(tmp_path, manifest, opened, grepped, kind="Full"):
    root = _repo(tmp_path)
    _plant_receipt(root, kind=kind, manifest=manifest, opened=opened,
                   grepped=grepped, workers=4)
    return "full round covered a fraction of its scope" in _kinds(root)


def _self_check_failures(root: Path) -> int:
    """Count `self_check.sh`'s failing lines (`bad`, which prints `✗`).

    Deliberately NOT a substring match on the message. `self_check.sh` runs
    other checks that fail in a bare fixture (there is no `.claude/sysop.lock`),
    so its exit code is not a clean signal either — but the *count* of failing
    lines is, and unlike the sentence it does not change when someone rewords
    the diagnostic. A guard keyed to prose reddens on a correct edit, which is
    the failure this file's own battery caught on the skill side.
    """
    return sum(1 for ln in _self_check_output(root).splitlines()
               if ln.strip().startswith("✗"))


def _self_check_flags(tmp_path, manifest, opened, grepped, kind="Full"):
    """Does self_check.sh report ONE MORE failure than the identical repo whose
    round is healthy? The control fixture differs only in the three numbers."""
    lo = _repo(tmp_path / "subject")
    _plant_receipt(lo, kind=kind, manifest=manifest, opened=opened,
                   grepped=grepped, workers=4)
    hi = _repo(tmp_path / "control")
    _plant_receipt(hi, kind="Full", manifest=1, opened=1, grepped=0, workers=4)
    return _self_check_failures(lo) == _self_check_failures(hi) + 1


def test_the_low_look_boundary_is_identical_on_all_three_surfaces(tmp_path):
    """One rule, three implementations, one boundary.

    This is the coupling `grep -rn LOW_LOOK_RATIO tests/` used to prove absent.
    Change the ratio in any single copy and at least one boundary case below
    disagrees with the other two.
    """
    for i, (manifest, opened, grepped, expected) in enumerate(_BOUNDARY_CASES):
        d = tmp_path / f"c{i}"
        verdicts = {
            "skill 5f (write time)": _skill_warns(d / "skill", manifest, opened, grepped),
            "sitrep_survey.py": _sitrep_flags(d / "sitrep", manifest, opened, grepped),
            "self_check.sh": _self_check_flags(d / "selfcheck", manifest, opened, grepped),
        }
        assert set(verdicts.values()) == {expected}, (
            f"manifest {manifest} opened {opened} grepped {grepped}: the three "
            f"implementations of the low-look rule disagree — {verdicts}"
        )


def test_every_full_spelling_is_treated_alike_on_all_three_surfaces(tmp_path):
    """`Full` is a PREFIX, not a literal, and `parse_coverage`'s own regex
    produces `Full (whole repo)`. The round narrowed the write side to
    `== "Full"` and all nine original boundary triples still passed, because
    every one of them used the bare spelling — so the write/read asymmetry this
    phase closes could be reopened invisibly."""
    for i, kind in enumerate(_FULL_SPELLINGS):
        d = tmp_path / f"k{i}"
        verdicts = {
            "skill 5f (write time)": _skill_warns(d / "skill", 1477, 13, 220, kind=kind),
            "sitrep_survey.py": _sitrep_flags(d / "sitrep", 1477, 13, 220, kind=kind),
            "self_check.sh": _self_check_flags(d / "selfcheck", 1477, 13, 220, kind=kind),
        }
        assert set(verdicts.values()) == {True}, (
            f"kind {kind!r}: the three surfaces disagree — {verdicts}"
        )


def test_a_non_integer_grepped_does_not_switch_the_write_check_off(tmp_path):
    """The round's H1. `unreported` is the value the shipped instruction tells
    an author to write when a field cannot be filled, and gating this check on
    a complete receipt let that documented input turn it off while BOTH readers
    still fired — a 0.9%-coverage `Full` round closing silent, flagged only
    after the commit that made it uncorrectable."""
    for tail in ("grepped unreported · workers 6", "workers 6"):
        root = _repo(tmp_path / tail.replace(" ", "_").replace("·", ""))
        marker = _open_round(root)
        _write_round(root, f"Full · manifest 900 · opened 8 · {tail}")
        out = _close(root, marker).stdout
        assert "round-receipt: LOW-LOOK" in out, (
            f"the write-side check went silent on `{tail}` while both readers "
            "fire on the same numbers"
        )
        # and the round is still correctly reported as incompletely recorded
        if "unreported" in tail or "grepped" not in tail:
            assert "unreported field(s)" in out


def test_the_warning_reports_looked_over_manifest_in_that_order(tmp_path):
    """The round swapped the two numbers — "looked at 1477 of 233 files" — and
    only the `LOW-LOOK` token was asserted, so it shipped green."""
    root = _repo(tmp_path / "order")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 1477 · opened 13 · grepped 220 · workers 4")
    out = _close(root, marker).stdout
    assert "233 of 1477 files" in out, (
        f"the warning does not read `looked of manifest`: {out!r}"
    )


def test_the_marker_clears_even_when_the_receipt_block_raises(tmp_path):
    """The layout claim, actually exercised. `PHASE_LOG` says the constraint is
    asserted by test rather than trusted; before the round no test in the suite
    made the block raise at all, so `p.unlink()` could have been moved inside
    the `try` with the whole suite green."""
    root = _repo(tmp_path / "raises")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 1477 · opened 13 · grepped 220 · workers 4")
    # A FILE where the receipts directory must be: mkdir raises inside the try.
    (root / RECEIPT_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / RECEIPT_REL).write_text("not a directory\n", encoding="utf-8")
    r = _close(root, marker)
    assert "round-receipt: skipped (" in r.stdout, (
        f"fixture did not force the except path: {r.stdout!r}"
    )
    assert r.returncode == 0, r.stderr
    assert not marker.exists(), (
        "the marker was stranded by a failure inside the receipt block — "
        "evidence must never cost the cleanup it rides on"
    )


def test_both_review_skills_warn_at_write_time(tmp_path):
    """The write-side check ships in BOTH generators, not just the quality one.

    The round measured the cost of the earlier two-point version: four defect
    mutations injected into the `security-audit` copy were GREEN against every
    guard this phase added, and died only on the pre-existing byte-identity
    invariant. That invariant is a real defence, but it makes this file's
    coverage of the security copy entirely indirect. Drive the whole boundary
    set through both copies instead.
    """
    for skill in SKILLS:
        for i, (manifest, opened, grepped, expected) in enumerate(_BOUNDARY_CASES):
            got = _skill_warns(tmp_path / f"{skill}-{i}", manifest, opened,
                               grepped, skill)
            assert got is expected, (
                f"{skill}: manifest {manifest} opened {opened} grepped "
                f"{grepped} — write-side warned={got}, expected {expected}"
            )


def test_a_narrowed_round_is_exempt_at_write_time_as_it_is_at_read_time(tmp_path):
    """A round that declared its own narrowness is correct and must stay
    silent. A check that fires on the honest case gets ignored — and both
    readers already exempt Scoped/Sampled, so the write side must too."""
    for kind in ("Sampled (highest-exposure modules)", "Scoped (api)"):
        root = _repo(tmp_path / kind.split()[0].lower())
        marker = _open_round(root)
        _write_round(root, f"{kind} · manifest 1477 · opened 13 · grepped 220 · workers 8")
        r = _close(root, marker)
        assert "round-receipt: LOW-LOOK" not in r.stdout, kind


def test_the_write_time_warning_fires_on_a_fanout_round(tmp_path):
    """The defect #367 reports. The only normative write-side sentence was
    solo-gated (`If you run solo…`) while both readers test the ratio, so a
    fan-out round that covered a fraction landed in the gap: nothing at write
    time, flagged after the commit when the label can no longer be fixed."""
    verdicts = {}
    for tag, tail in (("fanout", "workers 8"),
                      ("solo", "workers 0, solo: no sub-agent primitive"),
                      ("one-worker", "workers 1")):
        root = _repo(tmp_path / tag)
        marker = _open_round(root)
        _write_round(root, f"Full · manifest 1477 · opened 13 · grepped 220 · {tail}")
        verdicts[tag] = "round-receipt: LOW-LOOK" in _close(root, marker).stdout
    assert verdicts == {"fanout": True, "solo": True, "one-worker": True}, (
        f"the warning must key on the ratio, never on the worker count: {verdicts}"
    )


def test_the_warning_never_costs_the_cleanup_it_rides_on(tmp_path):
    """The binding constraint on Step 5f: evidence must never cost the cleanup.
    A round that trips the warning still clears its marker and still writes its
    receipt, because a stranded marker is worse than a mislabeled round."""
    root = _repo(tmp_path / "clears")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 1477 · opened 13 · grepped 220 · workers 8")
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    assert "round-receipt: LOW-LOOK" in r.stdout
    assert not marker.exists(), "the marker must be unlinked even when warning"
    assert _only_receipt(root)["kind"] == "Full"


def test_the_kind_rule_is_not_conditioned_on_staffing():
    """#367's write-side half, and the hole this phase's own battery found.

    The rule that picks `Full` vs `Sampled` used to open "If you run **solo**
    on a scope you cannot open in full" — a staffing condition — while both
    readers of the receipt test the ratio and never look at `workers`. A
    fan-out round that covered a fraction therefore satisfied the write-side
    rule and failed both read-side ones. `_shared/fanout-evidence.md` § Tier 0
    already said the tier "fires on **every** round, fan-out or solo"; the
    skills disagreed with the contract they cite.

    Presence check, and that is all it is: this pins the *rule as stated*, not
    an agent's compliance with it. Reverting the de-gating survived every other
    guard in this file, which is why it exists.
    """
    for skill, path in SKILLS.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        start = next(i for i, ln in enumerate(lines)
                     if ln.startswith("### 3-0."))
        end = next(i for i in range(start + 1, len(lines))
                   if lines[i].startswith("### ") and i > start)
        block = "\n".join(lines[start:end])

        rule = [ln for ln in lines[start:end]
                if "`Sampled`, not `Full`" in ln]
        assert len(rule) == 1, f"{skill}: expected one kind rule, got {len(rule)}"
        rule = rule[0]
        assert "whether you ran solo or dispatched workers" in rule, (
            f"{skill}: the kind rule is conditioned on staffing again: {rule!r}"
        )
        # The rule must state its own TEST. The round redefined the antecedent
        # ("a scope counts as opened in full whenever the round dispatched at
        # least one worker per top-level directory…") and every pinned literal
        # survived, because the rule described a state instead of a measure.
        assert "`opened + grepped` reached the manifest" in rule, (
            f"{skill}: the rule no longer states the arithmetic it means, so "
            f"its antecedent can be redefined around it: {rule!r}"
        )
        assert "Staffing is not part of that test" in rule, skill
        assert "If you run solo on a scope you cannot open in full" not in block, (
            f"{skill}: the retired solo-gated opener is back"
        )

        # D09: the round re-gated the rule by ADDING a sentence elsewhere in
        # the same block — "keep the `Full` label whenever `workers` is
        # non-zero" — leaving every assertion above green. Nothing in this
        # block may make the label conditional on staffing.
        low = block.lower()
        for phrase in ("keep the `full` label", "keep the full label",
                       "in practice this binds a solo round",
                       "counts as opened *in full* whenever",
                       "has covered its scope through them"):
            assert phrase not in low, (
                f"{skill}: Step 3-0 carries staffing-conditional language "
                f"({phrase!r}) — the kind rule is re-gated"
            )
        for ln in lines[start:end]:
            if "workers" in ln.lower() and "full" in ln.lower():
                assert ln is rule or "Staffing is not part" in ln or (
                    "`workers <K>`" in ln), (
                    f"{skill}: a line outside the kind rule ties `workers` to "
                    f"the `Full` label: {ln!r}"
                )


def test_the_warning_says_the_header_is_still_uncommitted(tmp_path):
    """The whole value of moving this check to write time is that the round
    header is still editable. If the message does not say so, the author has no
    reason to act on it now rather than ignore it like the read-side one."""
    root = _repo(tmp_path / "msg")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 1477 · opened 13 · grepped 220 · workers 8")
    out = _close(root, marker).stdout
    # Key on the INSTRUCTION, not on its wording. The round showed that
    # rewording "The round header is NOT committed yet" to "is not yet
    # committed" reddened the suite — a false kill on a correct edit, the
    # exact class the `LOW-LOOK` token exists to avoid, applied to two of the
    # three printed lines but not to this one.
    assert "Sampled (<basis>)" in out, (
        "the warning no longer tells the author what to relabel it to"
    )
    assert "Step 7" in out, (
        "the warning no longer says which step commits the header, so an "
        "author cannot tell that the window is still open"
    )
    # The round rewrote the remediation into "so nothing needs doing now …
    # most rounds should keep the Full label; this line is informational
    # only", keeping both strings above. A warning that tells the author to
    # ignore it is worse than no warning.
    low = out.lower()
    for defeat in ("nothing needs doing", "informational only",
                   "keep the full label", "no action is required",
                   "safe to ignore"):
        assert defeat not in low, (
            f"the LOW-LOOK remediation tells the author to ignore it "
            f"({defeat!r}): {out!r}"
        )


# ── §4 drift guards on the shipped prose ────────────────────────────────────


def test_all_three_audit_skills_carry_the_tier0_ledger():
    for path in (*SKILLS.values(), TEST_AUDIT):
        text = path.read_text(encoding="utf-8")
        assert "Tier 0" in text, path.name
        for field in ("manifest", "opened", "grepped", "workers"):
            assert field in text, f"{path.name}: ledger field {field} missing"


def test_review_skills_put_the_ledger_in_the_durable_round_header():
    """A printed summary dies with the terminal. The round header is committed
    and is what /review-close, /auto-fix and the next reviewer read, so the
    ledger must live there — the failure being that the header carried an
    invented 'N reviewable files' line and nothing else."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        header = text[text.index("### 5b."):text.index("### 5c.")]
        assert "**Coverage" in header, f"{skill}: no coverage line in the round header"
        # The whole field set, in order — `grepped` in particular, since folding
        # it into `opened` is how a sparse pass would inflate itself.
        assert ("manifest <N> · opened <M> · grepped <G> · workers <K>"
                in header), f"{skill}: the round header's ledger fields drifted"
        assert "MANDATORY" in header, skill
        assert "unreported" in header, f"{skill}: no empty-field rule in the header"


def test_review_skills_state_the_dispatch_decision_as_a_step():
    """The measured failure was not an unread instruction — both runs read the
    whole 894/938-line body and reviewed solo anyway. A dispatch bullet inside a
    prose block produces no artifact; a step with a stated output does."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert "### 3-0. Dispatch decision" in text, skill
        assert "STATE IT" in text, skill
        assert "case (c) does not exist" in text, skill
        assert "`Sampled`, not `Full`" in text, skill


def test_manifest_count_is_never_reported_alone():
    """`Files scanned: <N>` / `Files audited: <N>` is the exact field that
    laundered a dispatch-set size into an apparent coverage claim — a 1,561-file
    repo reported as '1,477 reviewable' with 13 files opened. It may not come
    back as a bare count."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        for banned in ("Files scanned: <N>", "Files audited: <N>"):
            assert banned not in text, (
                f"{skill}: `{banned}` is back in the summary — a manifest size "
                "stated alone reads as coverage"
            )
        assert "Coverage (Tier 0):" in text, skill
        # Step 1 still prints a bare `Files: <N>` — that is a legitimate
        # pre-round scoping statement, and by the motivating run's own account
        # it is where the invented "1,477 reviewable files" header claim came
        # from. So it has to carry the framing, or this guard's name promises
        # more than it enforces.
        assert "scope size, not a coverage claim" in text, (
            f"{skill}: Step 1's file count is stated without saying it is not "
            "coverage — the exact misread this phase exists to close"
        )


def test_tier2_footer_stays_fanout_only():
    """The constraint Phase 138 set and this phase must not erode: a solo run
    emitting an Assigned/Opened worker footer fabricates a worker that never
    existed. Tier 0 borrows Tier 2's *measure*, never its *artifact*."""
    text = FANOUT.read_text(encoding="utf-8")
    assert "A run that does not fan out writes no footer" in text
    assert "Do not \"fix\" a silent solo round by making this footer fire on it." in text
    assert "never write one" in text
    assert "Fan-out only" in text


def test_tier0_defines_its_denominator_and_keeps_grep_separate():
    """Two ways the ledger could quietly lie: measuring an incremental round
    against the whole repo (every honest round looks collapsed), and folding
    grep into opened (every sparse pass looks thorough)."""
    text = FANOUT.read_text(encoding="utf-8")
    assert "never the repository total" in text
    assert "separately, never folded into `opened`" in text
    assert "solo is a declared decision, never a silent default" in text.lower()


def test_test_audit_states_it_writes_no_receipt():
    """/test-audit opens no round, so it has no marker to clear and nothing for
    a receipt to attest. Saying so keeps a future author from adding a marker
    lifecycle to make the receipt fire — a round that never existed."""
    text = TEST_AUDIT.read_text(encoding="utf-8")
    assert "writes no round receipt" in text
    assert "deliberate, not an omission" in text
    assert "workers 0, solo: single-agent base path" in text


# ── §5 the ledger must survive archival ─────────────────────────────────────


def _archiver():
    import archive_review_tasks
    return archive_review_tasks


COVER = ("> **Coverage (code quality):** Full · manifest 40 · opened 38 · "
         "grepped 2 · workers 4\n")


def _round_md(batch_status: str) -> list[str]:
    return (
        "# Code Review Tasks\n"
        "\n"
        "## Round 1 (2026-07-25) — Code Quality Review\n"
        "\n"
        + COVER +
        "\n"
        f"### Batch 1 — Thing `{batch_status}`\n"
        "\n"
        "> **Branch:** `review/1`\n"
        "\n"
        "- [x] **TASK-1**: done 🟢\n"
        "\n"
        "## Statistics\n"
    ).splitlines(keepends=True)


def test_the_coverage_line_rides_its_round_into_the_archive():
    """The ledger is round-level metadata sitting between `## Round` and the
    first `### Batch` — a gap the archiver collected into neither the round
    header nor any batch, while removing the round's whole line range. The
    'durable' copy was therefore destroyed at the 125KB rotation: gone from
    review_tasks.md and never written to the archive, with the receipt
    gitignored and pruned at 50. Found by adversarial review, 2026-07-25."""
    art = _archiver()
    rounds = art.parse_archivable_batches(_round_md("Merged"))
    assert len(rounds) == 1 and rounds[0]["all_merged"]
    assert any("Coverage (code quality)" in ln for ln in rounds[0]["preamble"])
    block = "\n".join(art.build_archive_block(rounds))
    assert "Coverage (code quality)" in block, (
        "the round archived without its coverage ledger — the durable record "
        "of how much of the codebase that round opened is now nowhere"
    )
    assert "manifest 40 · opened 38" in block


def test_a_partially_merged_round_does_not_duplicate_its_ledger():
    """Its header stays in the live file (only merged batch ranges are
    removed), so emitting the line into the archive too would leave the same
    ledger in two places, and a third time when the round fully archives.

    The fixture needs a MIX — one merged batch so the round is archivable at
    all, one pending batch so it is not `all_merged`. A wholly-pending round
    is filtered out before `build_archive_block` ever sees it, which would
    make this test pass without asserting anything."""
    art = _archiver()
    md = (
        "# Code Review Tasks\n"
        "\n"
        "## Round 1 (2026-07-25) — Code Quality Review\n"
        "\n"
        + COVER +
        "\n"
        "### Batch 1 — Done `Merged`\n"
        "\n"
        "> **Branch:** `review/1`\n"
        "\n"
        "- [x] **TASK-1**: done 🟢\n"
        "\n"
        "### Batch 2 — Still going `Pending`\n"
        "\n"
        "> **Branch:** `review/2`\n"
        "\n"
        "- [ ] **TASK-2**: open 🟢\n"
        "\n"
        "## Statistics\n"
    ).splitlines(keepends=True)
    rounds = art.parse_archivable_batches(md)
    assert rounds, "fixture must produce an archivable round"
    assert not rounds[0]["all_merged"], "fixture must be a PARTIAL round"
    assert rounds[0]["preamble"], "the ledger is still captured, just not emitted"
    block = "\n".join(art.build_archive_block(rounds))
    assert "Coverage (code quality)" not in block


def test_round_preamble_capture_stops_at_the_first_batch():
    """Batch-level blockquotes (`> **Branch:**`, `> **Scope:**`) belong to their
    batch and must not be hoisted into the round's metadata."""
    art = _archiver()
    rounds = art.parse_archivable_batches(_round_md("Merged"))
    joined = "".join(rounds[0]["preamble"])
    assert "Branch" not in joined
    assert joined.count("Coverage") == 1


def test_self_check_reads_a_receipt_the_shipped_writer_actually_produced(tmp_path):
    """§1 and §3 otherwise never meet: every other self_check test reads a
    fixture-written receipt, so the writer's own serialization was unpinned.
    That is how `ensure_ascii=True` survived — json escapes the ledger's `·`
    to a \\u00b7, json.loads decodes it back for the §1 asserts, and only a
    reader that greps the raw bytes (this one) can see it."""
    root = _repo(tmp_path / "e2e")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 40 · opened 38 · grepped 2 · workers 4")
    _close(root, marker)
    raw = _receipts(root)[0].read_text(encoding="utf-8")
    assert "\\u00b7" not in raw, (
        "the receipt escaped its separator — self_check.sh greps the raw JSON "
        "and would print the escape to the operator"
    )
    out = _self_check_output(root)
    assert "manifest 40 · opened 38" in out
    assert "closed 2" in out or "(closed " in out


def test_self_check_flags_a_full_round_that_reached_a_fraction(tmp_path):
    """The loop-mode surface must make the SAME self-contradiction call /sitrep
    makes — loop mode ships no /sitrep, and docs/loop-mode.md promises this."""
    root = _repo(tmp_path / "sc-collapse")
    _plant_receipt(root, kind="Full", manifest=1477, opened=13, grepped=0,
                   line="Full · manifest 1477 · opened 13 · workers 0")
    out = _self_check_output(root)
    assert "declared Full over 1477 files but reached 13" in out
    assert "relabel the round" in out


def test_self_check_does_not_flag_a_narrowed_round(tmp_path):
    """A round that labelled itself thin is correct. Reddening it here is the
    cry-wolf failure that makes the whole signal worthless."""
    root = _repo(tmp_path / "sc-sampled")
    _plant_receipt(root, kind="Sampled (highest-exposure)", manifest=1477,
                   opened=13, grepped=0, line="Sampled (highest-exposure) · …")
    out = _self_check_output(root)
    assert "declared Full" not in out


def test_self_check_counts_grep_as_looking(tmp_path):
    root = _repo(tmp_path / "sc-sparse")
    _plant_receipt(root, kind="Full", manifest=100, opened=10, grepped=80,
                   line="Full · manifest 100 · opened 10 · grepped 80")
    assert "declared Full over" not in _self_check_output(root)


# ── §6 reader hardening (adversarial round, 2026-07-25) ─────────────────────


def test_sitrep_survives_a_well_formed_receipt_with_wrong_types(tmp_path):
    """The `"unreported"` sentinel check does not establish `int`. A quoted
    "13", a null, or any future format change reached the arithmetic and raised
    — and `_find_discrepancies` is called unguarded, so the traceback took the
    whole of /sitrep down (task queue, locks, worktrees, routing), not just the
    coverage line. A probe that breaks the report is worse than the silence."""
    for i, bad in enumerate(({"opened": "13"}, {"manifest": "1477"},
                             {"manifest": None}, {"workers": "0"},
                             {"kind": 123})):
        root = _repo(tmp_path / f"types-{i}")
        _plant_receipt(root, **bad)
        kinds = _kinds(root)  # must not raise
        assert "round coverage unreported" in kinds, (
            f"{bad}: a non-int field must be reported missing, not consumed"
        )


def test_sitrep_flags_a_narrowed_round_with_no_stated_basis(tmp_path):
    """`Sampled`/`Scoped` turns the look-ratio off, so the basis is the entire
    content of the claim. A bare `Sampled` declares nothing and would otherwise
    buy silence for free — 'always claim Sampled' as a silent escape."""
    for i, kind in enumerate(("Sampled", "Scoped", "Sampled ()")):
        root = _repo(tmp_path / f"basis-{i}")
        _plant_receipt(root, kind=kind, manifest=1477, opened=13, grepped=0,
                       workers=0, solo_reason="harness")
        assert "narrowed round with no stated basis" in _kinds(root), kind


def test_sitrep_accepts_a_narrowed_round_that_names_its_basis(tmp_path):
    root = _repo(tmp_path / "basis-ok")
    _plant_receipt(root, kind="Sampled (highest-exposure modules)",
                   manifest=1477, opened=13, grepped=0, workers=0,
                   solo_reason="no sub-agent primitive")
    assert _kinds(root) == []


def test_sitrep_flags_unexplained_solo_on_a_narrowed_round_too(tmp_path):
    """The missing-reason check is a missing-FIELD check, not a ratio judgment,
    so scoping it inside the `Full` gate made bare `Sampled` switch it off with
    everything else. It belongs outside that gate."""
    root = _repo(tmp_path / "solo-sampled")
    _plant_receipt(root, kind="Sampled (pre-scan hits)", manifest=900,
                   opened=20, grepped=0, workers=0, solo_reason="")
    assert "solo round with no stated reason" in _kinds(root)


def test_the_loop_mode_doc_claim_matches_what_self_check_does():
    """`docs/loop-mode.md` promises loop consumers that `self_check.sh` calls
    out a Full round reaching under a third of its scope. Loop mode ships no
    `/sitrep` (`LOOP_EXCLUDE_SCRIPTS`), so if that comparison ever moves out of
    `self_check.sh` the doc is promising a check nobody ships — a false claim
    about a shipped safeguard on the only surface that has it."""
    doc = (REPO_ROOT / "docs/loop-mode.md").read_text(encoding="utf-8")
    sh = (REPO_ROOT / "core/companion/scripts/self_check.sh").read_text(encoding="utf-8")
    assert "under a third of" in doc
    assert "coverage ledger" in doc
    assert 'R_OPEN + ${R_GREP:-0} ) * 3' in sh, (
        "self_check.sh no longer performs the ratio comparison docs/loop-mode.md "
        "promises — fix one or the other, they must agree"
    )
    assert 'elif [[ "$KIND" == Full* ]]; then' in sh, (
        "the comparison is no longer scoped to Full rounds — a narrowed round "
        "that declared its own thinness would be reddened for it"
    )
    install = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    loop_excl = install.split("LOOP_EXCLUDE_SCRIPTS", 1)[1][:400]
    assert "sitrep_survey.py" in loop_excl, (
        "loop mode now ships /sitrep — the premise of routing this check "
        "through self_check.sh has changed"
    )


# ── §7 the computed anchor: `tracked` ───────────────────────────────────────


def test_the_receipt_counts_tracked_files_itself(tmp_path):
    """`manifest` is the round's own claim, and a round that quietly declares a
    small one looks complete while covering ~1% — the one hole the ledger's
    other guards cannot see, because every number in them is self-reported.
    `tracked` is counted at close from `git ls-files`: the only fact in the
    receipt the round does not author."""
    root = _repo(tmp_path / "tracked")
    for i in range(7):
        (root / f"f{i}.py").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "more"], cwd=root, check=True,
                   capture_output=True)
    marker = _open_round(root)
    _write_round(root, "Full · manifest 2 · opened 2 · grepped 0 · workers 1")
    r = _close(root, marker)
    rec = _only_receipt(root)
    # README.md + .gitignore + 7 sources. `review_tasks.md` is written by the
    # round and not yet committed, so it is untracked — `git ls-files` counts
    # the committed tree, which is the point: an unambiguous number nobody in
    # this round chose.
    assert rec["tracked"] == 9, rec
    assert rec["manifest"] == 2, "the claim is recorded as made, beside the fact"
    assert "of 9 tracked" in r.stdout


def test_tracked_is_counted_not_read_from_the_coverage_line(tmp_path):
    """If it could be sourced from the line it would be self-reported too, and
    the anchor would anchor nothing."""
    root = _repo(tmp_path / "tracked-lie")
    marker = _open_round(root)
    _write_round(root, "Full · manifest 900 · opened 900 · grepped 0 · "
                       "workers 1 · tracked 99999")
    _close(root, marker)
    rec = _only_receipt(root)
    assert rec["tracked"] != 99999
    assert isinstance(rec["tracked"], int) and rec["tracked"] < 10


def test_tracked_precedes_line_in_the_serialized_receipt(tmp_path):
    """self_check.sh extracts the coverage line with a greedy sed that works
    only because `"line"` is the LAST key on its own line — a key added after it
    silently breaks the loop-mode display. Pin the ordering, since nothing else
    does."""
    root = _repo(tmp_path / "keyorder")
    marker = _open_round(root)
    _write_round(root, FULL_LINE)
    _close(root, marker)
    raw = _receipts(root)[0].read_text(encoding="utf-8")
    assert raw.index('"tracked"') < raw.index('"line"')
    assert raw.rstrip().rstrip("}").rstrip().endswith('"'), (
        '"line" is no longer the last key — self_check.sh\'s sed extraction '
        "will pick up whatever now follows it"
    )


def test_tracked_degrades_to_unreported_and_never_blocks_the_clear(tmp_path):
    """Counting is best-effort like everything else on this path: a receipt
    that cannot be enriched must still be written, and the marker still cleared."""
    root = _repo(tmp_path / "nogit")
    marker = _open_round(root)
    _write_round(root, FULL_LINE)
    # Remove the repo's git dir after the round opened — `git ls-files` now fails
    import shutil
    shutil.rmtree(root / ".git")
    r = _close(root, marker)
    assert r.returncode == 0, r.stderr
    assert _only_receipt(root)["tracked"] == "unreported"
    assert not marker.exists()


def test_self_check_displays_the_counted_repository_size(tmp_path):
    root = _repo(tmp_path / "sc-tracked")
    _plant_receipt(root, tracked=1561, line=FULL_LINE)
    out = _self_check_output(root)
    assert "repository had 1561 tracked files at close" in out
    assert "not self-reported" in out


def test_sitrep_shows_the_repository_size_beside_a_narrow_claim(tmp_path):
    """The shrink case: a round declaring a tiny manifest is only visible if the
    reader can see what it declined to speak for."""
    root = _repo(tmp_path / "sitrep-tracked")
    _plant_receipt(root, kind="Sampled", manifest=15, opened=13, grepped=0,
                   workers=2, tracked=1561)
    assert "of 1561 tracked" in _detail(root, "narrowed round with no stated basis")


def test_sitrep_omits_the_repository_size_when_it_is_unknown(tmp_path):
    root = _repo(tmp_path / "sitrep-untracked")
    _plant_receipt(root, kind="Sampled", manifest=15, opened=13, grepped=0,
                   workers=2, tracked="unreported")
    assert "tracked" not in _detail(root, "narrowed round with no stated basis")
