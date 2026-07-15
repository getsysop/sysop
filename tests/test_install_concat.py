"""Integration tests for install.sh's concat-file pipeline (Phase 55).

Covers BeanRider ISSUE-0042 (comment-preserving id-collision merge of
`.claude/checks.project.yml`) and ISSUE-0041 (placeholder substitution scoped
to checks.yml `paths:` values; markdown maps never substituted).

The merge and substitution logic lives in python heredocs inside install.sh,
so these tests invoke the real installer against a scratch git consumer in
tmp_path — slower than the unit suite (a few installer runs) but the only
honest coverage. `python3` is resolved to the pytest interpreter via a PATH
prefix so `pick_python_with_yaml()` finds pyyaml.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

# A project checks file whose first rule collides with the python pack's
# `logger-fstring` id. The `# OVERRIDE` comment above it is the BR
# ISSUE-0042 payload — the annotation that the pre-Phase-55 structural
# merge silently dropped on every update cycle.
CHECKS_PROJECT_YML = """\
# Project-specific checks for the test consumer.
checks:
  # OVERRIDE (TASK-0315): duplicate of semgrep-logger-fstring (below); reserved for the pre-commit hook only
  - id: logger-fstring
    name: "f-string Logger Calls (consumer override)"
    category: convention
    severity: info  # downgraded on purpose
    paths: ["custom_app/"]
    include: ["*.py"]
    pattern: 'logger\\.(info|warning|error)\\(f'
    description: "consumer-tuned variant"
    used_by: [codebase-review]
    blocking: false

  - id: project-only-rule
    name: "Project Only"
    category: convention
    severity: low
    paths: ["custom_app/"]
    include: ["*.py"]
    pattern: 'TODO-PROJ'
    description: "non-colliding consumer rule"
    used_by: [codebase-review]
    blocking: false
"""

SUBSTITUTIONS_PROJECT_YML = """\
substitutions:
  "<api module>": "__disabled_no_op__"
  "<totally stale token>": "nothing"
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_consumer(root, files):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run_install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"install.sh failed (rc={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result


def _commit_all(root, msg):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)


@pytest.fixture(scope="module")
def installed_consumer(tmp_path_factory):
    """One fresh install with both an id-colliding checks.project.yml and a
    substitutions file. Shared read-only by the assertion-only tests."""
    root = _make_consumer(
        tmp_path_factory.mktemp("consumer"),
        {
            ".claude/checks.project.yml": CHECKS_PROJECT_YML,
            ".claude/substitutions.project.yml": SUBSTITUTIONS_PROJECT_YML,
        },
    )
    result = _run_install(root, "--packs", "python")
    return root, result


class TestCollisionMerge:
    """ISSUE-0042 — comment-preserving merge on checks[*].id collision."""

    def test_override_comment_survives(self, installed_consumer):
        root, _ = installed_consumer
        merged = (root / ".claude/checks.yml").read_text()
        assert "OVERRIDE (TASK-0315)" in merged
        assert "# downgraded on purpose" in merged

    def test_consumer_entry_replaces_upstream(self, installed_consumer):
        root, _ = installed_consumer
        merged = (root / ".claude/checks.yml").read_text()
        assert merged.count("id: logger-fstring") == 1
        parsed = yaml.safe_load(merged)
        by_id = {c["id"]: c for c in parsed["checks"]}
        assert by_id["logger-fstring"]["severity"] == "info"
        assert by_id["logger-fstring"]["blocking"] is False
        assert "project-only-rule" in by_id

    def test_merged_file_parses_with_unique_ids(self, installed_consumer):
        root, _ = installed_consumer
        parsed = yaml.safe_load((root / ".claude/checks.yml").read_text())
        ids = [c["id"] for c in parsed["checks"]]
        assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"

    def test_assembled_file_has_one_checks_key_per_fragment_survives(
        self, installed_consumer
    ):
        """Lock the single top-level `checks:` invariant the PyYAML parser
        (Phase 68) now depends on.

        The old hand-rolled parser scanned `- id:` lines structure-blind, so
        it was immune to a malformed assembly that left one `checks:` key per
        fragment. `yaml.safe_load` is NOT: on duplicate top-level keys it
        silently keeps only the LAST mapping — which would drop every fragment
        but the last (e.g. the whole core fragment) with no crash. Assert the
        assembled file carries exactly one `checks:` leader AND that a
        core-fragment-only id (first fragment) AND a pack id (later fragment)
        both survive — so a future `strip_yaml_leader` regression fails loudly
        here instead of silently disabling checks.
        """
        root, _ = installed_consumer
        merged = (root / ".claude/checks.yml").read_text()
        leader_count = sum(
            1 for line in merged.splitlines() if line.rstrip() == "checks:"
        )
        assert leader_count == 1, f"expected one top-level checks:, got {leader_count}"
        by_id = {c["id"]: c for c in yaml.safe_load(merged)["checks"]}
        assert "todo-vs-deferred" in by_id   # core fragment (first)
        assert "logger-fstring" in by_id     # python pack fragment (later)

    def test_collision_is_warned_and_merge_is_text_level(self, installed_consumer):
        _, result = installed_consumer
        assert "id-collision: logger-fstring" in result.stdout
        assert "text-level by checks[*].id" in result.stdout
        assert "structural" not in result.stdout  # fallback must not fire

    def test_comment_survives_update_cycles(self, tmp_path):
        """The actual BR regression: the annotation re-dropped on EVERY
        sysop-update.sh cycle, not just at first install."""
        root = _make_consumer(
            tmp_path / "consumer",
            {".claude/checks.project.yml": CHECKS_PROJECT_YML},
        )
        _run_install(root, "--packs", "python")
        for cycle in (1, 2):
            _commit_all(root, f"absorb cycle {cycle}")
            _run_install(root, "--update")
            merged = (root / ".claude/checks.yml").read_text()
            assert "OVERRIDE (TASK-0315)" in merged, f"comment dropped on update {cycle}"
            assert merged.count("id: logger-fstring") == 1


class TestNoCollisionAppend:
    """Existing-behavior guard: the no-collision path already preserved
    comments via text-append; keep it that way."""

    def test_consumer_comment_survives(self, tmp_path):
        project_yml = (
            "checks:\n"
            "  # WHY: catches the project-specific TODO marker\n"
            "  - id: project-only-rule\n"
            "    name: \"Project Only\"\n"
            "    category: convention\n"
            "    severity: low\n"
            "    paths: [\"custom_app/\"]\n"
            "    include: [\"*.py\"]\n"
            "    pattern: 'TODO-PROJ'\n"
            "    description: \"non-colliding consumer rule\"\n"
            "    used_by: [codebase-review]\n"
            "    blocking: false\n"
        )
        root = _make_consumer(
            tmp_path / "consumer",
            {".claude/checks.project.yml": project_yml},
        )
        result = _run_install(root, "--packs", "python")
        merged = (root / ".claude/checks.yml").read_text()
        assert "# WHY: catches the project-specific TODO marker" in merged
        assert "text-append; no id-collision" in result.stdout


class TestSubstitutionScoping:
    """ISSUE-0041 — substitution fires only on checks.yml `paths:` values."""

    def test_paths_values_substituted(self, installed_consumer):
        root, _ = installed_consumer
        parsed = yaml.safe_load((root / ".claude/checks.yml").read_text())
        substituted = [
            c["id"] for c in parsed["checks"]
            if any("__disabled_no_op__" in p for p in c.get("paths", []))
        ]
        assert substituted, "expected <api module> paths to be rewritten"

    def test_sentinel_confined_to_paths_lines(self, installed_consumer):
        root, _ = installed_consumer
        for line in (root / ".claude/checks.yml").read_text().splitlines():
            if "__disabled_no_op__" in line:
                assert line.lstrip().startswith("paths:"), f"leaked outside paths: {line!r}"

    def test_markdown_maps_never_substituted(self, installed_consumer):
        root, _ = installed_consumer
        for name in ("convention_map.md", "security_map.md"):
            text = (root / ".claude" / name).read_text()
            assert "__disabled_no_op__" not in text, f"{name} was garbled"
        # Upstream placeholder tokens stay verbatim as documentation.
        assert "<api module>" in (root / ".claude/convention_map.md").read_text()

    def test_stale_key_reported_used_key_not(self, installed_consumer):
        _, result = installed_consumer
        assert "stale substitutions" in result.stdout
        assert "<totally stale token>" in result.stdout
        # The matched key must NOT be listed as stale.
        stale_block = result.stdout.split("stale substitutions", 1)[1]
        assert "<api module>" not in stale_block.split("Fix:")[0]


# Phase 78: a convention promoted into the `.project.*` overlay (per
# `_shared/promotion-write-target.md`) must survive sysop-update.sh regeneration
# and reappear in the regenerated base map. This locks the overlay-survival
# mechanism the dual-write relies on — the durability that makes writing a
# promotion to the overlay (rather than base-only, the pre-Phase-78 bug) safe.
# (The skills are prose, unreachable by pytest, so this exercises the installer
# mechanism, not a simulated base-only skill write.)
PROMOTED_CHECKS_PROJECT_YML = """\
checks:
  # Promoted from Round 3 (codebase-review Step 9) — additive, no upstream collision.
  - id: promoted-round3-rule
    name: "Promoted Round 3 Rule"
    category: convention
    severity: low
    paths: ["app/"]
    include: ["*.py"]
    pattern: 'BANNED_CALL'
    description: "locally promoted convention"
    used_by: [codebase-review]
    blocking: false
"""

PROMOTED_CONVENTION_MAP_PROJECT_MD = """\
## `app/*.py` — Promoted reminders (Round 3)

- Some project-specific convention bullet.
> checks.yml: promoted-round3-rule
"""


class TestPromotionOverlayDurability:
    """Phase 78 — a convention promoted into the `.project.*` overlay survives
    `--update` regeneration and reappears in the regenerated base map. This is
    the exact durability the promotion-write-target dual-write relies on: the
    YAML-merge path (`checks.project.yml`) and the markdown text-append path
    (`convention_map.project.md`, previously untested)."""

    def test_promoted_overlay_survives_update(self, tmp_path):
        root = _make_consumer(
            tmp_path / "consumer",
            {
                ".claude/checks.project.yml": PROMOTED_CHECKS_PROJECT_YML,
                ".claude/convention_map.project.md": PROMOTED_CONVENTION_MAP_PROJECT_MD,
            },
        )
        _run_install(root, "--packs", "python")

        def _assert_present(stage):
            checks = yaml.safe_load((root / ".claude/checks.yml").read_text())
            ids = {c["id"] for c in checks["checks"]}
            assert "promoted-round3-rule" in ids, f"promoted check dropped after {stage}"
            cmap = (root / ".claude/convention_map.md").read_text()
            assert "promoted-round3-rule" in cmap, f"promoted reminder dropped after {stage}"
            assert "Promoted reminders (Round 3)" in cmap, f"overlay section dropped after {stage}"

        _assert_present("fresh install")
        for cycle in (1, 2):
            _commit_all(root, f"absorb cycle {cycle}")
            _run_install(root, "--update")
            _assert_present(f"update cycle {cycle}")
