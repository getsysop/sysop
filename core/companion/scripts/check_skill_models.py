#!/usr/bin/env python3
"""Fail if any skill model pin's role is undefined or resolves to a non-served model.

This is the proactive half of the model-role workflow (Phase 69, evolving the
Phase 65b allowlist guard). Skills pin a ROLE, not a model name; this check
verifies, for every pin:

  1. the pin is governed by a `<!-- sysop:model-roles … -->` marker (no un-roled pins),
  2. the role is defined in `served_models.yml` `roles:`,
  3. the role resolves to a model listed under `served:`, and
  4. a role governing an INLINE pin resolves to a value the Agent tool's `model`
     parameter accepts (Phase 223 — that parameter is a closed enum, so `best`,
     `inherit`, and full model ids are rejected at spawn time even though they
     are legal in frontmatter). Overridable via `inline_models:`, and
  5. the pin's own LITERAL value is one the same enum accepts, checked
     independently of (4). Rules 1-4 all judge what a role *resolves to*; on the
     plugin install path nothing rewrites the file, so the literal in the tree is
     what the harness receives, and a hand-edited one passed all four.

It also refuses to pass an empty population: `--root <dir with no pins>` is a
broken install, not a clean bill of health.

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
2 = the check could not be run (config missing, unreadable or malformed; skills
root missing; nothing to validate). Only 1 is a verdict on the mapping — Phase
244 made `install.sh` say so, after a rc-2 partial install was reported to a
consumer as `REFUSED (unreadable config)` over a perfectly readable config.
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
    ConfigShapeError,
    analyze_text,
    find_role_violations,
    iter_skill_files,
    load_inline_models,
    load_roles_config,
    read_skill_text,
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
    parser.add_argument("--managed-only", action="store_true",
                        help="validate only files carrying a `sysop:model-roles` marker "
                             "— a consumer's own skills in .claude/skills/ are not Sysop's "
                             "to judge (used by install.sh's pre-apply gate)")
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

    local_or_none = local_path if local_path.is_file() else None
    # A config that is malformed rather than wrong is a USAGE error (exit 2), not
    # a finding (exit 1). Reporting a stray bracket through the violation code
    # told consumers their model pins were unresolvable when the real problem was
    # a YAML typo — and the shipped pre-commit example repeats that message.
    try:
        roles, served = load_roles_config(config_path, local_or_none)
        inline_models = load_inline_models(config_path, local_or_none)
    except ConfigShapeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    served_set = set(served)
    inline_set = set(inline_models)

    if args.list:
        for path in iter_skill_files(root):
            text = read_skill_text(path)
            if text is None:
                print(f"  [UNREAD ] {_rel(path)}  (not valid UTF-8 or not readable)")
                continue
            for r in analyze_text(text):
                resolved = roles.get(r.role) if r.role else None
                if r.role is None:
                    mark = "NO-ROLE"
                elif resolved is None:
                    mark = "UNDEF"
                elif resolved not in served_set:
                    mark = "STALE"
                elif r.kind == "inline" and resolved not in inline_set:
                    mark = "NOSPAWN"
                else:
                    mark = "served"
                detail = f"{r.role or '-'} -> {resolved or '?'}"
                print(f"  [{mark:7}] {_rel(path)}:{r.lineno}  {detail}  ({r.kind})")
        return 0

    # A guard that scanned nothing certifies nothing. `--root <empty dir>` used to
    # print OK and exit 0 under any mapping, so a consumer whose skills install
    # failed got a clean bill of health from the check that exists to catch it.
    population = 0
    unreadable: list[Path] = []
    for p in iter_skill_files(root):
        # `Q-346` leg 1: this was an unguarded `read_text`, so a consumer's own
        # latin-1 `.md` anywhere under `.claude/skills/` crashed the checker and
        # `install.sh` printed the traceback as `REFUSED (invalid mapping)`.
        text = read_skill_text(p)
        if text is None:
            unreadable.append(p)
            continue
        if args.managed_only and "sysop:model-roles" not in text:
            continue
        population += len(analyze_text(text))
    if unreadable:
        # Reported, never silent. In managed-only mode these are out of scope
        # by definition (an undecodable file carries no discoverable marker); with
        # the whole tree in scope they are a coverage gap the reader must see.
        print(
            f"note: skipped {len(unreadable)} file(s) under {root} that are not "
            f"valid UTF-8 or not readable — they carry no Sysop model-role marker "
            f"this check can see: "
            + ", ".join(_rel(u) for u in unreadable),
            file=sys.stderr,
        )
    if population == 0:
        scope = "Sysop-managed " if args.managed_only else ""
        print(f"error: no {scope}model pins found under {root} — nothing to validate. "
              f"A skills tree with no pins to check is a broken install, not a "
              f"passing check.", file=sys.stderr)
        return 2

    violations = find_role_violations(
        root, roles, served, inline_models, managed_only=args.managed_only
    )
    if violations:
        rolemap = ", ".join(f"{k}={v}" for k, v in sorted(roles.items())) or "(none)"
        print(f"FAIL: {len(violations)} skill model pin(s) failed role resolution.")
        print(f"      roles: {rolemap}")
        print(f"      served: {', '.join(served) or '(none)'}")
        print(f"      inline-legal: {', '.join(inline_models) or '(none)'}\n")
        for rel, pin, reason in violations:
            print(f"  {rel}:{pin.lineno}  {reason}")
        print("\nFix: repoint the role in served_models.yml (and update served:), "
              "or add the missing `<!-- sysop:model-roles … -->` marker.")
        if any("INLINE pin" in reason for _, _, reason in violations):
            print("     For the INLINE failures above, adding the value to `served:` does "
                  "NOT help — `served:` is Sysop's own sunset allowlist, not the harness's "
                  "enum. Map the role to an alias (e.g. `reasoning: fable`), or extend "
                  "`inline_models:` if your harness really accepts the value.")
        return 1

    scope_note = f" ({len(unreadable)} unreadable file(s) skipped)" if unreadable else ""
    print(f"OK: all skill model pins resolve to served models "
          f"({', '.join(f'{k}={v}' for k, v in sorted(roles.items()))})"
          f"{scope_note}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
