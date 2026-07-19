#!/usr/bin/env python3
"""Migrate a bare model-alias literal across the skills tree (the rare case).

NOTE (Phase 69): skills now pin a ROLE, not a model name (see ``_model_roles.py``).
The common model swap — a sunset, a cost change, a better model shipping — is a
one-line edit to ``served_models.yml`` ``roles:``, applied by
``resolve_skill_models.py`` at install/update time. You do NOT run this migrator
for that. It remains only for rewriting bare-alias literals directly (e.g.
changing the role *vocabulary* itself, or a one-off bulk pin rewrite on a tree
that predates the role markers).

Model aliases (``fable``, ``opus``, ``sonnet``, ``haiku``) are pinned as bare
string literals in two places the harness reads literally — there is no
templating layer to indirect them through:

  1. Skill frontmatter ``model: <alias>`` (the frontmatter block of each
     SKILL.md).
  2. Inline ``model: "<alias>"`` pins in prose that get copied into Agent
     tool calls (adversarial-review / judge / verify / execution agents).

When Anthropic sunsets a model, every pin for *that one tier* must move. This
script does it tier-safely: it keys STRICTLY on ``--from``, so the other tiers
(e.g. the ``sonnet`` cheap-tier fix-agent pins, the ``haiku`` trivial-skill
frontmatter) are structurally untouchable — you cannot hit the wrong tier by
construction.

Two classes of match get different treatment:

  * Operative pins (frontmatter ``model:`` lines + inline quoted ``"<alias>"``)
    are REWRITTEN.
  * Freeform prose mentions ("up to N Opus agents", "the Opus convention
    gate", "session default is now Opus") are FLAGGED for human review, not
    rewritten — robo-editing English drifts.

Dry-run by default; pass ``--apply`` to write.

Paths default to the **installed** layout (``.claude/skills/`` +
``.claude/served_models.yml`` resolved from the script's great-grandparent dir), which
is correct when this script ships into a consumer project under ``sysop/scripts/``.
To run against the Sysop source tree itself, pass
``--root core/skills`` (and ``--config core/companion/.claude/served_models.yml``
to check_skill_models.py).

This script touches no database and takes no ``--env``; it intentionally does
NOT use the shared CLI helper (that helper is for DB-targeting scripts).

Usage:
    python sysop/scripts/migrate_skill_model.py --from fable --to opus            # preview
    python sysop/scripts/migrate_skill_model.py --from fable --to opus --apply    # write

After applying, the script prints a checklist of the things it deliberately
does NOT touch (the tier rationale, downstream consumer copies, the flagged
prose). Re-run sysop/scripts/check_skill_models.py to confirm no stale pins remain.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Installed-layout defaults: when this script ships into a consumer project it
# lives at ``<repo>/sysop/scripts/migrate_skill_model.py`` (Phase 128), so
# ``parents[2]`` is the
# consumer repo root and ``.claude/skills`` / ``.claude/served_models.yml`` are
# the installed skill tree + allowlist. In the Sysop source tree the same
# expression points at ``core/companion/`` (which has neither) — run there with
# an explicit ``--root core/skills``.
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

# Alias charset: short aliases (opus) and full IDs (claude-opus-4-8) alike.
_ALIAS = r"[a-z0-9][a-z0-9.\-]*"

# A bare frontmatter pin occupying the whole line: `model: fable` / `model: "fable"`.
_FRONTMATTER_RE = re.compile(rf'^(\s*model:\s*)(["\']?)({_ALIAS})(["\']?)(\s*)$')

# An inline pin embedded in prose. Covers both backtick shapes found in the
# skills: `model: "fable"` (one span) and `model`: `"fable"` (two spans).
_INLINE_RE = re.compile(rf'model[`:\s]*["\']({_ALIAS})["\']')


@dataclass(frozen=True)
class ModelPin:
    """A model alias pinned in a skill file."""

    lineno: int
    alias: str
    kind: str  # "frontmatter" | "inline"


def iter_skill_files(root: Path):
    """Yield every markdown file under *root* in stable order."""
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def extract_model_pins(text: str) -> list[ModelPin]:
    """Return every operative model pin in *text*.

    Frontmatter pins (anchored whole-line ``model: <alias>``) and inline
    quoted pins (``model: "<alias>"`` in prose). Prose mentions of the bare
    word are NOT pins and are not returned. Standalone public helper — Phase 69
    moved the served-model check onto role-aware analysis
    (``_model_roles.analyze_text``), so ``check_skill_models.py`` no longer
    calls this, and ``migrate_text`` uses its own parameterized regexes; kept
    as the tested pin-extraction primitive and the canonical bare-alias
    pin-shape.

    Retained by design, not vestigial: ``_model_roles.py`` (§ its module
    docstring) designates ``migrate_skill_model.py`` the *home of the
    bare-alias pin regexes* and deliberately layers its own broader value
    matcher on top rather than importing these, "so the migrator's API (and
    its tests) are untouched." Do not prune this cluster as dead code without
    also reconciling that design note.
    """
    pins: list[ModelPin] = []
    for i, line in enumerate(text.splitlines(), start=1):
        fm = _FRONTMATTER_RE.match(line)
        if fm:
            pins.append(ModelPin(i, fm.group(3), "frontmatter"))
            continue  # an anchored frontmatter line is never also an inline pin
        for m in _INLINE_RE.finditer(line):
            pins.append(ModelPin(i, m.group(1), "inline"))
    return pins


def migrate_text(
    text: str, from_alias: str, to_alias: str
) -> tuple[str, list[tuple[int, str, str]], list[tuple[int, str]]]:
    """Rewrite operative pins of *from_alias* to *to_alias*.

    Returns ``(new_text, operative_edits, flagged_lines)`` where:
      * operative_edits is ``[(lineno, old_line, new_line), ...]``
      * flagged_lines is ``[(lineno, line), ...]`` — prose mentions of the bare
        word that survive (case-insensitive), for human review. A line can be
        both edited and flagged (an inline pin sitting in a prose sentence that
        also names the model again).
    """
    fa = re.escape(from_alias)
    # These three patterns are parameterized by from_alias (a runtime arg), so
    # they cannot be hoisted to module scope — the legitimate parameterized-regex
    # exception the recompile-inside-def rule documents.
    fm_re = re.compile(rf'^(\s*model:\s*)(["\']?){fa}(["\']?)(\s*)$')  # nosemgrep: recompile-inside-def
    # NB: this rewrites ANY quoted occurrence of the from-alias, which is
    # broader than extract_model_pins()'s `model`-prefixed inline match — a bare
    # quoted "<alias>" in prose (not a real pin) would be rewritten here yet
    # never counted by check_skill_models.py. Dry-run-default + the printed
    # per-line diff (a human reviews before --apply) is the guardrail; in
    # practice these skills only quote an alias as an operative pin.
    inline_quoted_re = re.compile(rf'(["\']){fa}\1')  # nosemgrep: recompile-inside-def
    prose_re = re.compile(rf"\b{fa}\b", re.IGNORECASE)  # nosemgrep: recompile-inside-def

    edits: list[tuple[int, str, str]] = []
    flagged: list[tuple[int, str]] = []
    out: list[str] = []

    for i, raw in enumerate(text.splitlines(keepends=True), start=1):
        nl = "\n" if raw.endswith("\n") else ""
        body = raw[: -len(nl)] if nl else raw
        new = body

        fm = fm_re.match(new)
        if fm:
            new = f"{fm.group(1)}{fm.group(2)}{to_alias}{fm.group(3)}{fm.group(4)}"
        new = inline_quoted_re.sub(rf"\g<1>{to_alias}\g<1>", new)

        if new != body:
            edits.append((i, body, new))
        if prose_re.search(new):
            flagged.append((i, new))

        out.append(new + nl)

    return "".join(out), edits, flagged


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tier-safe model-alias migration across the skills tree.",
    )
    parser.add_argument("--from", dest="from_alias", required=True,
                        help="model alias being sunset (e.g. fable)")
    parser.add_argument("--to", dest="to_alias", required=True,
                        help="replacement alias (e.g. opus)")
    parser.add_argument("--apply", action="store_true",
                        help="write changes to disk (default: dry-run preview)")
    parser.add_argument("--root", default=str(SKILLS_DIR),
                        help="skills directory to scan (default: .claude/skills/)")
    args = parser.parse_args(argv)

    if args.from_alias == args.to_alias:
        print(f"error: --from and --to are identical ({args.from_alias!r})", file=sys.stderr)
        return 2

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: skills directory not found: {root}", file=sys.stderr)
        return 2

    total_edits = 0
    total_flagged = 0
    files_changed = 0
    flagged_total: list[tuple[str, int, str]] = []

    print(f"Migrating model pins: {args.from_alias!r} -> {args.to_alias!r}")
    print(f"Scanning: {_rel(root)}/\n")

    for path in iter_skill_files(root):
        original = path.read_text(encoding="utf-8")
        new_text, edits, flagged = migrate_text(original, args.from_alias, args.to_alias)
        if not edits and not flagged:
            continue

        print(f"  {_rel(path)}")
        for lineno, old, new in edits:
            print(f"    L{lineno}  - {old.strip()}")
            print(f"    L{lineno}  + {new.strip()}")
        for lineno, line in flagged:
            print(f"    L{lineno}  ? prose (review): {line.strip()}")
            flagged_total.append((_rel(path), lineno, line.strip()))
        print()

        total_edits += len(edits)
        total_flagged += len(flagged)
        if edits:
            files_changed += 1
            if args.apply and new_text != original:
                path.write_text(new_text, encoding="utf-8")

    mode = "APPLIED" if args.apply else "DRY-RUN (no files written)"
    print("─" * 60)
    print(f"{mode}: {total_edits} operative pin(s) across {files_changed} file(s); "
          f"{total_flagged} prose mention(s) flagged.")

    if not args.apply and total_edits:
        print("\nRe-run with --apply to write these changes.")

    print("\nNot handled automatically — do these by hand:")
    print("  1. Tier rationale: wherever the per-tier reasoning is documented")
    print("     (served_models.yml comments, skill prose) still names the old")
    print("     tier. Update it.")
    print("  2. served_models.yml: repoint the role (and update served:) so check_skill_models.py")
    print("     stays green; add the replacement alias if not already listed.")
    print("  3. Downstream consumers that installed these skills via the bash")
    print("     installer keep their OWN copies — they pick up this migration on")
    print("     the next sysop-update.sh. A consumer's project-authored skills")
    print("     (not shipped by Sysop) must be migrated in that repo separately.")
    if flagged_total:
        print(f"  4. Reword the {len(flagged_total)} flagged prose mention(s) above that now")
        print("     contradict the pins (e.g. \"session default is now <old>\").")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
