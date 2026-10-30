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
import glob
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    # PyYAML lives only in the project venv on PEP-668 hosts (BeanRider
    # ISSUE-0049; internal tracker #321). Same probe as clear_user_action.py, so
    # `/intake` and `/onboard` can run `--defaults` as bare `python3` (`Q-676`):
    # script-anchored roots, then the main checkout via git-common-dir, then
    # the CWD; commit a candidate only once `import yaml` succeeds from it.
    # tests/test_venv_pyyaml_bootstrap.py pins the copies identical.
    _roots = []
    # `list(...)` before the slice: slicing `PurePath.parents` is 3.10+.
    for _cand in list(Path(__file__).resolve().parents)[:3]:
        if _cand not in _roots:
            _roots.append(_cand)
    try:
        _r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=5,
            env={_k: _v for _k, _v in os.environ.items()
                 if _k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                               "GIT_INDEX_FILE")},
        )
        if _r.returncode == 0 and _r.stdout.strip():
            _main = (Path(__file__).resolve().parent / _r.stdout.strip()).resolve().parent
            if _main not in _roots:
                _roots.append(_main)
    except (OSError, subprocess.SubprocessError):
        pass
    if Path.cwd() not in _roots:
        _roots.append(Path.cwd())
    _hit = False
    for _root in _roots:
        for _layout in (".venv", "venv"):
            for _site in glob.glob(str(_root / _layout / "lib/python*/site-packages")):
                sys.path.insert(0, _site)
                try:
                    import yaml
                except ImportError:
                    sys.path.remove(_site)
                    continue
                _hit = True
                break
            if _hit:
                break
        if _hit:
            break
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: check_skill_models.py requires PyYAML. fix: python3 -m venv .venv && "
            ".venv/bin/pip install pyyaml   (PEP-668-safe), or activate the venv.",
            file=sys.stderr,
        )
        sys.exit(2)

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
    EffortConfigError,
    RoleAliasError,
    load_role_efforts,
    load_roles_config,
    read_skill_text,
)
from migrate_skill_model import SKILLS_DIR  # noqa: E402

try:
    from _model_roles import managed_pins  # noqa: E402
    _PRESERVED_GATE = False
except ImportError:
    # A consumer's preserved `_model_roles.py` from before `Q-700` must still let the
    # update's gate start (Phase 398's case). Its `analyze_text` already gives a per-pin
    # marker's role, so the rule fits in its API; its gate does not (`_gate_violations`).
    _PRESERVED_GATE = True

    def managed_pins(text: str) -> list:
        return [p for p in analyze_text(text)
                if "sysop:model-roles" in text or p.role is not None]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def _gate_violations(root: Path, roles: dict, served: list, inline_models: list) -> list:
    """The update's gate: `find_role_violations` over the pins `managed_pins` owns.

    A preserved `_model_roles.py` from before `Q-700` judges the file marker alone in
    `managed_only` mode, so a refused value in a step file's only pin for a role would pass.
    There the full check's verdict is kept for the pins the rule owns (round 2, lens C).
    """
    if not _PRESERVED_GATE:
        return find_role_violations(root, roles, served, inline_models, managed_only=True)
    owned = set()
    for path in iter_skill_files(root):
        text = read_skill_text(path)
        if text:
            owned |= {(_rel(path), p.lineno) for p in managed_pins(text)}
    return [v for v in find_role_violations(root, roles, served, inline_models)
            if (v[0], v[1].lineno) in owned]


def _print_defaults(config_path: Path, local_path: Path | None, root: Path) -> int:
    """The role table `Q-676` puts at the front door: the installer's summary, `/intake`
    and `/onboard`. Every value is read from the config, so it stays true when the file
    changes.

    With a skills tree at *root* holding managed pins, the table lists only the roles
    those pins govern and every role they follow, so a loop install is not shown roles it
    has no skill for. It judges nothing itself: before the table it reports what the check
    mode returns for `--managed-only` over that tree, the function the update's gate calls,
    as a fact about these files and the installed skills (three rounds of Phase 398 found each
    re-derivation of the gate wrong). A row whose pins carry another model or effort is marked
    not yet applied (`Q-685`), read from every pin under *root* that names a role, as the
    resolver rewrites them; the mark changes no exit code. With no managed pins it says
    nothing was checked. Exit 1
    when the check fails, as the check mode does, a role cycle or a bad `efforts:` included;
    2 on a config it cannot read."""
    # Imported here, not at the top: a consumer's preserved `_model_roles.py` from before
    # this function existed must still let the check mode start (Phase 398's round 2).
    try:
        from _model_roles import describe_roles
    except ImportError as exc:
        print(f"error: --defaults needs a newer sysop/scripts/_model_roles.py ({exc})",
              file=sys.stderr)
        return 2
    try:
        rows, notes = describe_roles(config_path, local_path)
        roles, served = load_roles_config(config_path, local_path)
        inline_models = load_inline_models(config_path, local_path)
    except ConfigShapeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RoleAliasError, EffortConfigError) as exc:
        print(f"The model-role check fails here: {exc}.")
        print("Fix it in .claude/served_models.local.yml; until then an update applies none of that file.")
        return 1
    pinned: set[str] = set()
    spawning: set[str] = set()
    pins_by_role: dict[str, list] = {}
    if root.is_dir():
        for path in iter_skill_files(root):
            text = read_skill_text(path)
            if not text:
                continue
            # Every pin that names a role, as the resolver rewrites them; these are exactly the
            # managed pins that name one (`managed_pins`), since without a file marker a pin
            # names a role only through its own marker (Phase 402's round 1, lens A; `Q-700`).
            pins = [p for p in analyze_text(text) if p.role]
            for p in pins:
                pins_by_role.setdefault(p.role, []).append(p)
            pinned |= {p.role for p in pins}
            spawning |= {p.role for p in pins if p.kind == "inline"}
    if pinned:
        by_role = {r.role: r for r in rows}
        keep, todo = set(), list(pinned)
        while todo:
            role = todo.pop()
            if role in keep or role not in by_role:
                continue
            keep.add(role)
            todo.append(by_role[role].value)
        rows = [r for r in rows if r.role in keep]
    else:
        spawning = {r.role for r in rows}
    failing = bool(pinned) and bool(_gate_violations(root, roles, served, inline_models))
    if not pinned:
        print(f"No Sysop skills under {root}, so the model-role check was not run.")
    elif failing:
        print("The model-role check fails here: `python3 sysop/scripts/check_skill_models.py")
        print("--managed-only` says why. If it still fails after an update has copied Sysop's")
        print("skills, the update applies none of .claude/served_models.local.yml.")
    source = "served_models.yml" + (" + served_models.local.yml" if local_path else "")
    print(f"Sysop model roles, as mapped by .claude/{source}:")
    width = max([len(r.role) for r in rows] + [4])
    mwidth = max([len(r.model) for r in rows] + [5])
    print(f"  {'role':<{width}}  {'model':<{mwidth}}  {'effort':<7}  what it does, and why")
    stale = False
    for r in rows:
        why = r.about or "-"
        if r.value != r.model:
            why = f"(follows {r.value}) {why}"
        # `Q-685`: the row is what the files map; the pins are what runs. A preserved
        # resolver from before `efforts:`, or a local edit made since the last update,
        # leaves the two apart, and the table did not say so.
        pins = pins_by_role.get(r.role, [])
        models = sorted({p.value for p in pins if p.value != r.model})
        efforts = sorted({p.effort or "session" for p in pins
                          if p.kind == "inline" and p.effort != r.effort})
        if models or efforts:
            stale = True
            carry = []
            if models:
                carry.append(f"model {', '.join(models)}")
            if efforts:
                carry.append(f"effort {', '.join(efforts)}")
            why = f"[not yet applied: the skills pin {'; '.join(carry)}] {why}"
        if r.local:
            why = f"[your override] {why}"
        # A role with no inline pin spawns nothing, so `efforts:` sets nothing for it.
        effort = (r.effort or "session") if r.role in spawning else "-"
        print(f"  {r.role:<{width}}  {r.model:<{mwidth}}  {effort:<7}  {why}")
    reval = notes.get("reevaluated")
    if isinstance(reval, dict) and reval.get("last"):
        nxt = f"; next {reval['next']}" if reval.get("next") else ""
        print(f"Defaults last re-evaluated {reval['last']}{nxt}.")
    print("Effort is what a role's spawned agents run at; 'session' runs at your session's level,")
    print("and '-' marks a role that spawns no agent here.")
    if stale:
        print("A row marked [not yet applied] is what these files map; the installed skills still")
        print("pin the value it names, and that is what runs until an update rewrites the pins.")
        if failing:
            # Round 1, lens A: on a refused mapping "not yet" promised a rewrite the update
            # does not make; the condition is the verdict line's own.
            print("If the check still fails after an update has copied Sysop's skills, that update")
            print("applies none of these rows.")
    cost = notes.get("cost_shape")
    if cost:
        print(" ".join(str(cost).split()))
    shown = [r for r in rows if r.role != "quick"] or rows
    eg = next((r for r in shown if r.role == "executor"), shown[0])
    alt = next((m for m in inline_models if m != eg.model and m in served), eg.model)
    print("To change a role, add one key to .claude/served_models.local.yml, e.g.")
    print("    roles:")
    print(f"      {eg.role}: {alt}")
    print("then run `bash sysop/scripts/sysop-update.sh`: the skills' model pins are rewritten")
    print("by the update, so an edit to the file changes nothing until then.")
    return 1 if failing else 0


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
                             "and pins carrying a per-pin `sysop:role=` marker (`Q-700`) "
                             "— a consumer's own skills in .claude/skills/ are not Sysop's "
                             "to judge (used by install.sh's pre-apply gate)")
    parser.add_argument("--list", action="store_true",
                        help="print every pin with its role + resolved model, then exit 0")
    parser.add_argument("--defaults", action="store_true",
                        help="print each role's model, effort and reason, and how to "
                             "override one; exit 1 when the model-role check fails on "
                             "these files and the installed skills (the skills tree "
                             "is optional)")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    local_path = Path(args.local)
    root = Path(args.root)
    if not config_path.is_file():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return 2
    if args.defaults:
        return _print_defaults(config_path, local_path if local_path.is_file() else None, root)
    if not root.is_dir():
        print(f"error: skills directory not found: {root}", file=sys.stderr)
        return 2

    local_or_none = local_path if local_path.is_file() else None
    # A config that is malformed rather than wrong is a USAGE error (exit 2), not
    # a finding (exit 1). Reporting a stray bracket through the violation code
    # told consumers their model pins were unresolvable when the real problem was
    # a YAML typo — and the shipped pre-commit example repeats that message.
    try:
        try:
            roles, served = load_roles_config(config_path, local_or_none)
        except RoleAliasError as exc:
            print(f"\u274c {exc}", file=sys.stderr)
            print("   Fix the `roles:` map so no role's value chains back to itself.",
                  file=sys.stderr)
            return 1
        inline_models = load_inline_models(config_path, local_or_none)
        try:
            efforts = load_role_efforts(config_path, local_or_none)
        except EffortConfigError as exc:
            print(f"\u274c {exc}", file=sys.stderr)
            print("   Fix the `efforts:` map in served_models.local.yml.", file=sys.stderr)
            return 1
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
                if r.kind == "inline" and r.role in efforts:
                    detail += f" @ {efforts[r.role] or 'session'}"
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
        population += len(managed_pins(text) if args.managed_only else analyze_text(text))
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

    violations = (_gate_violations(root, roles, served, inline_models) if args.managed_only
                  else find_role_violations(root, roles, served, inline_models))
    if violations:
        rolemap = ", ".join(f"{k}={v}" for k, v in sorted(roles.items())) or "(none)"
        print(f"FAIL: {len(violations)} skill model pin(s) failed role resolution.")
        print(f"      roles: {rolemap}")
        print(f"      served: {', '.join(served) or '(none)'}")
        print(f"      inline-legal: {', '.join(inline_models) or '(none)'}\n")
        for rel, pin, reason in violations:
            print(f"  {rel}:{pin.lineno}  {reason}")
        # `Q-295`: this named served_models.yml, which every update replaces, so a consumer
        # who followed it lost the edit and met the refusal again. The override file is the
        # remedy whether or not it exists yet. Each line prints for its own reason only: a
        # role remedy beside a literal failure sent the consumer to an edit that could not
        # clear it (Phase 441's round, lens A). In Sysop's own source tree the mapping is the
        # shipped file itself, and the default override path names nothing there.
        reasons = [reason for _, _, reason in violations]
        companion = config_path.resolve().parent.parent
        source_tree = companion.name == "companion" and (companion.parent / "skills").is_dir()
        fixes = []
        if any(r.startswith(("role ", "undefined role")) for r in reasons):
            if source_tree:
                fixes.append(f"repoint the role in {_rel(config_path)} (and update served:) — "
                             f"in a Sysop source tree it is the shipped mapping.")
            else:
                fixes.append(f"map the role under `roles:` in {_rel(local_path)} (create it if "
                             f"absent). {_rel(config_path)} is Sysop's own mapping and every "
                             f"update replaces it.")
        if any(r.startswith("undefined role") for r in reasons):
            fixes.append("An undefined role is named by a `sysop:role=` or `sysop:model-roles` "
                         "marker: define it under `roles:`, or, in a skill of your own, remove "
                         "the marker.")
        if any(r.startswith("pin has no governing") for r in reasons):
            fixes.append("A pin with no role sits in a file carrying a `sysop:model-roles` "
                         "marker: give it a per-pin `<!-- sysop:role=… -->`, or, in a skill of "
                         "your own, remove the file marker.")
        if any(r.startswith("INLINE pin") for r in reasons):
            fixes.append("A pin judged by its own literal is one Sysop's markers govern: a marker "
                         "governs every pin on its line, and a file marker every pin in the file. "
                         "Put a pin of your own on a line, in a file, that no Sysop marker governs.")
        print("\nFix: " + "\n     ".join(fixes))
        if any("governs an INLINE pin" in reason for reason in reasons):
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
