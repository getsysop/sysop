#!/usr/bin/env python3
"""Resolve skill model-role markers to concrete models (Phase 69).

Skills ship pinning a ROLE, not a model (see `_model_roles.py`). At install and
update time this script rewrites every marked `model:` value to the model the
project's config maps that role to:

    reasoning  -> served_models.yml roles.reasoning   (default: opus)
    mechanical -> ...roles.mechanical                  (default: sonnet)
    quick      -> ...roles.quick                       (default: haiku)

`served_models.local.yml` (consumer-owned, never overwritten) layers on top so a
project can pick its own models without losing sunset updates to the Sysop-owned
defaults.

Under the DEFAULT config this is a no-op (reasoning->opus, etc., are already the
literals in the shipped skills), so a default install diverges from source by
zero bytes. It does real work only when a role is remapped. install.sh runs it
with `--apply` after copying the skills tree; a consumer who edits their config
can re-run it the same way.

Dry-run by default; pass --apply to write. Paths default to the installed layout
(`.claude/skills` + `.claude/served_models.yml` beside the scripts dir); pass
`--root` / `--config` to run against the Sysop source tree.

Exit codes: 0 = ok (resolved or clean); 1 = a pin references an undefined /
missing role (nothing written — fix the marker or the config); 2 = usage error.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _model_roles import (  # noqa: E402  (path set above)
    DEFAULT_CONFIG,
    LOCAL_CONFIG,
    REPO_ROOT,
    analyze_text,
    iter_skill_files,
    RoleAliasError,
    load_roles_config,
    read_skill_text,
    resolve_text,
)
from migrate_skill_model import SKILLS_DIR  # noqa: E402


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _unresolvable(root: Path, roles: dict) -> list[tuple[str, int, str]]:
    """Pins whose role is None or undefined — a structural error; refuse to write.

    Scoped to files carrying a `sysop:model-roles` marker (Phase 223). `.claude/
    skills/` is Claude Code's standard user-skill directory, so a consumer's own
    skill can sit beside the shipped ones and legitimately carry a `model:` field
    with no Sysop marker. Judging those made a valid override unappliable forever
    — the resolver refused to write anything, and the only remedy it named was to
    add a Sysop marker, which would hand the consumer's private skill to this
    rewriter on every update. A file Sysop does not mark is a file Sysop does not
    own; the "never half-applies" guarantee still holds over the files it does.
    """
    bad: list[tuple[str, int, str]] = []
    for path in iter_skill_files(root):
        text = read_skill_text(path)
        # A file this script cannot decode cannot carry a discoverable marker, so
        # it lands in the same bucket as the unmarked file below. `Q-346` leg 1's
        # class: guarding only `check_skill_models.py` moved the crash here.
        if text is None or "sysop:model-roles" not in text:
            continue
        for r in analyze_text(text):
            if r.role is None:
                bad.append((_rel(path), r.lineno, "pin has no sysop:model-roles marker"))
            elif r.role not in roles:
                bad.append((_rel(path), r.lineno, f"undefined role {r.role!r}"))
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite skill model-role markers to the configured models.",
    )
    parser.add_argument("--root", default=str(SKILLS_DIR),
                        help="skills directory to resolve (default: .claude/skills/)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="role config (default: .claude/served_models.yml)")
    parser.add_argument("--local", default=str(LOCAL_CONFIG),
                        help="consumer override layered on top (default: .claude/served_models.local.yml)")
    parser.add_argument("--apply", action="store_true",
                        help="write changes to disk (default: dry-run preview)")
    parser.add_argument("--quiet", action="store_true", help="print only the summary line")
    args = parser.parse_args(argv)

    root = Path(args.root)
    config = Path(args.config)
    local = Path(args.local)
    if not root.is_dir():
        print(f"error: skills directory not found: {root}", file=sys.stderr)
        return 2
    if not config.is_file():
        print(f"error: config not found: {config}", file=sys.stderr)
        return 2

    try:
        roles, _ = load_roles_config(config, local if local.is_file() else None)
    except RoleAliasError as exc:
        print(f"\u274c {exc}", file=sys.stderr)
        print("   Fix the `roles:` map so no role's value chains back to itself.",
              file=sys.stderr)
        return 1

    bad = _unresolvable(root, roles)
    if bad:
        print("error: skill model pins reference roles the config does not define:", file=sys.stderr)
        for rel, lineno, why in bad:
            print(f"  {rel}:{lineno}  {why}", file=sys.stderr)
        print("  Fix the skill marker or add the role to served_models.yml. Nothing written.",
              file=sys.stderr)
        return 1

    total = 0
    files_changed = 0
    unreadable: list[Path] = []
    for path in iter_skill_files(root):
        original = read_skill_text(path)
        if original is None:
            # `Q-346` leg 1, found by running the checker's fix: with the gate no
            # longer crashing, the EXECUTOR crashed on the same latin-1 file and
            # the whole resolution was reported as "skipped". Skipping the one
            # file it cannot decode keeps the "never half-applies" contract over
            # the files this script owns, and the skip is disclosed below rather
            # than absorbed.
            unreadable.append(path)
            continue
        new_text, changes = resolve_text(original, roles)
        if not changes:
            continue
        files_changed += 1
        total += len(changes)
        if not args.quiet:
            print(f"  {_rel(path)}")
            for lineno, kind, role, old, new in changes:
                print(f"    L{lineno}  {kind:11} {role}: {old} -> {new}")
        if args.apply and new_text != original:
            path.write_text(new_text, encoding="utf-8")

    if unreadable:
        print(
            f"  note: skipped {len(unreadable)} file(s) that are not valid UTF-8 "
            f"or not readable, so they carry no Sysop marker to resolve: "
            + ", ".join(_rel(u) for u in unreadable),
            file=sys.stderr,
        )
    mode = "APPLIED" if args.apply else "DRY-RUN (no files written)"
    rolemap = ", ".join(f"{k}={v}" for k, v in sorted(roles.items()))
    print(f"{mode}: {total} pin(s) across {files_changed} file(s) resolved [{rolemap}].")
    if not args.apply and total:
        print("Re-run with --apply to write these changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
