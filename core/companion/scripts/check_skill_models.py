#!/usr/bin/env python3
"""Fail if any skill model pin's role is undefined or resolves to a non-served model.

This is the proactive half of the model-role workflow (Phase 69, evolving the
Phase 65b allowlist guard). Skills pin a ROLE, not a model name; this check
verifies, for every pin:

  1. the pin is governed by a `<!-- sysop:model-roles … -->` marker (no un-roled pins),
  2. the role is defined in `served_models.yml` `roles:`, and
  3. the role resolves to a model listed under `served:`.

That third rule is what makes a sunset LOUD instead of silent:

    On a sunset → drop the retired model from served_models.yml `served:`
    → any role still mapped to it (3) goes red (exit 1) → repoint the role
    to its replacement (one line) → re-run this check to confirm green.

Without it, a skill pinned to a retired model fails only when someone next runs
that skill. With it, the breakage surfaces the moment the config is edited (or
in pre-commit / CI). The reactive bulk-rewrite half is `migrate_skill_model.py`
(now only needed for the rare role-vocabulary change — the common sunset is the
one-line config edit above).

Marker/config parsing is shared with resolve_skill_models.py via `_model_roles`.

Paths default to the installed layout (`.claude/skills/` + `.claude/served_models.yml`
beside the scripts dir). In the Sysop source tree run with `--root core/skills
--config core/companion/.claude/served_models.yml`.

Requires PyYAML (already a Sysop dependency via run_checks). Touches no database.

Exit codes: 0 = all pins resolve to served models; 1 = at least one violation;
2 = usage error.
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
    find_role_violations,
    iter_skill_files,
    load_roles_config,
)
from migrate_skill_model import SKILLS_DIR  # noqa: E402


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify skill model-role pins resolve to served models.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="role config (default: .claude/served_models.yml)")
    parser.add_argument("--local", default=str(LOCAL_CONFIG),
                        help="consumer override layered on top (default: .claude/served_models.local.yml)")
    parser.add_argument("--root", default=str(SKILLS_DIR),
                        help="skills directory to scan (default: .claude/skills/)")
    parser.add_argument("--list", action="store_true",
                        help="print every pin with its role + resolved model, then exit 0")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    local_path = Path(args.local)
    root = Path(args.root)
    if not config_path.is_file():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"error: skills directory not found: {root}", file=sys.stderr)
        return 2

    roles, served = load_roles_config(config_path, local_path if local_path.is_file() else None)
    served_set = set(served)

    if args.list:
        for path in iter_skill_files(root):
            for r in analyze_text(path.read_text(encoding="utf-8")):
                resolved = roles.get(r.role) if r.role else None
                if r.role is None:
                    mark = "NO-ROLE"
                elif resolved is None:
                    mark = "UNDEF"
                elif resolved not in served_set:
                    mark = "STALE"
                else:
                    mark = "served"
                detail = f"{r.role or '-'} -> {resolved or '?'}"
                print(f"  [{mark:7}] {_rel(path)}:{r.lineno}  {detail}  ({r.kind})")
        return 0

    violations = find_role_violations(root, roles, served)
    if violations:
        rolemap = ", ".join(f"{k}={v}" for k, v in sorted(roles.items())) or "(none)"
        print(f"FAIL: {len(violations)} skill model pin(s) failed role resolution.")
        print(f"      roles: {rolemap}")
        print(f"      served: {', '.join(served) or '(none)'}\n")
        for rel, pin, reason in violations:
            print(f"  {rel}:{pin.lineno}  {reason}")
        print("\nFix: repoint the role in served_models.yml (and update served:), "
              "or add the missing `<!-- sysop:model-roles … -->` marker.")
        return 1

    print(f"OK: all skill model pins resolve to served models "
          f"({', '.join(f'{k}={v}' for k, v in sorted(roles.items()))}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
