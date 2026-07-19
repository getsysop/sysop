#!/usr/bin/env python3
"""Shared model-role primitives: markers, config, resolution (Phase 69).

Skills do not hard-pin a model name. They pin a ROLE via an HTML-comment marker
that Claude Code's frontmatter parser never sees (it lives in the body, not the
`model:` line — a trailing `#` comment on that line is undocumented/risky):

    <!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->   (file-level)
    <!-- sysop:role=mechanical -->                                      (per-pin override,
                                                                        trailing an inline pin)

The file-level marker sets the role for the frontmatter `model:` pin and the
default role for every inline `model: "<x>"` pin in that file. A trailing
per-pin marker overrides the file default for one pin (used where a single file
mixes roles — e.g. /auto-fix's mechanical fix agents vs. its reasoning
verification pass).

This module is the single source for parsing those markers, loading the
role->model config (`served_models.yml` + optional `served_models.local.yml`
override), and resolving a role to a model. Consumed by:

  * resolve_skill_models.py — install/update-time rewrite of marked `model:` values.
  * check_skill_models.py   — CI/pre-commit guard: every pin's role resolves to a served model.

`migrate_skill_model.py` remains the home of the bare-alias pin regexes; this
module imports `iter_skill_files` / `REPO_ROOT` / `SKILLS_DIR` from it and layers
roles on top, so the migrator's API (and its tests) are untouched.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_skill_model import (  # noqa: E402  (path set above)
    REPO_ROOT,
    iter_skill_files,
)

# Config lives beside the installed skills tree. In a consumer project the
# scripts ship to <repo>/sysop/scripts/ (Phase 128), so REPO_ROOT (imported from
# migrate_skill_model.py, resolved via parents[2]) is the repo root and these
# resolve to <repo>/.claude/. In the Sysop source tree pass --config explicitly.
DEFAULT_CONFIG = REPO_ROOT / ".claude" / "served_models.yml"
LOCAL_CONFIG = REPO_ROOT / ".claude" / "served_models.local.yml"

# Role markers (HTML comments — body-only, invisible to the harness).
_FILE_MARKER_RE = re.compile(r"<!--\s*sysop:model-roles\s+([^>]*?)\s*-->")
_PIN_MARKER_RE = re.compile(r"<!--\s*sysop:role=([a-z][a-z0-9_-]*)\s*-->")
_ROLE_CLAUSE_RE = re.compile(r"\b(frontmatter|inline)=([a-z][a-z0-9_-]*)")

# Pin-finding regexes are intentionally BROAD on the value (not the bare-alias
# charset migrate uses): a resolved value can be a full id / ARN / `inherit`,
# and the resolver must still be able to re-find and re-resolve it. A value is
# any run of non-quote chars inside the quotes.
#
# CAVEAT (mirrors migrate_skill_model.py's inline-regex note): under a file-level
# `inline=<role>` default, EVERY `model: "<x>"` / `` `model`: `"<x>"` `` on a body
# line is treated as an operative pin and rewritten. Do not write a non-pin
# `model: "..."` in prose in a file that carries an `inline=` default — it would
# be rewritten under an override. In practice these skills only ever quote a
# model as a real pin (all 23 detected pins are operative); a future author who
# needs a literal `model: "..."` example in such a file should phrase it without
# the `model:`-prefixed quoted form.
_FM_PIN_RE = re.compile(r'^(\s*model:\s*)(["\']?)([^"\'\s#]+)(["\']?)(\s*)$')
_INLINE_PIN_RE = re.compile(r'(model[`:\s]*["\'])([^"\']+)(["\'])')


@dataclass(frozen=True)
class PinRole:
    """A model pin and the role that governs it (``role`` is None if un-roled)."""

    lineno: int
    kind: str  # "frontmatter" | "inline"
    value: str
    role: str | None


def parse_file_roles(text: str) -> tuple[str | None, str | None]:
    """Return ``(frontmatter_role, inline_default_role)`` from the file marker."""
    m = _FILE_MARKER_RE.search(text)
    if not m:
        return (None, None)
    clauses = dict(_ROLE_CLAUSE_RE.findall(m.group(1)))
    return (clauses.get("frontmatter"), clauses.get("inline"))


def _frontmatter_close(lines: list[str]) -> int | None:
    """Line number (1-based) of the closing ``---`` of leading frontmatter, or None."""
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return None


def analyze_text(text: str) -> list[PinRole]:
    """Return every model pin in *text* paired with its governing role.

    Frontmatter pins take the file marker's ``frontmatter=`` role. Inline pins
    take a trailing per-pin ``sysop:role=`` marker if present, else the file
    marker's ``inline=`` default. A pin with no governing role gets ``role=None``
    (check_skill_models.py flags these).
    """
    fm_role, inline_default = parse_file_roles(text)
    lines = text.splitlines()
    fm_close = _frontmatter_close(lines)
    out: list[PinRole] = []
    for i, line in enumerate(lines, start=1):
        if fm_close is not None and i < fm_close:
            m = _FM_PIN_RE.match(line)
            if m:
                out.append(PinRole(i, "frontmatter", m.group(3), fm_role))
                continue
        pm = _PIN_MARKER_RE.search(line)
        line_role = pm.group(1) if pm else inline_default
        for im in _INLINE_PIN_RE.finditer(line):
            out.append(PinRole(i, "inline", im.group(2), line_role))
    return out


def resolve_text(text: str, roles: dict[str, str]) -> tuple[str, list[tuple]]:
    """Rewrite each pin's value to its role's model.

    Returns ``(new_text, changes)`` where changes is
    ``[(lineno, kind, role, old_value, new_value), ...]``. Pins whose role is
    None or absent from *roles* are left untouched (a structural error the
    caller surfaces); pins already at the target value are skipped.
    """
    records = analyze_text(text)
    if not records:
        return text, []
    keep_nl = text.splitlines(keepends=True)
    by_line: dict[int, list[PinRole]] = {}
    for r in records:
        by_line.setdefault(r.lineno, []).append(r)
    changes: list[tuple] = []
    for lineno, recs in by_line.items():
        raw = keep_nl[lineno - 1]
        nl = "\n" if raw.endswith("\n") else ""
        body = raw[: -len(nl)] if nl else raw
        new = body
        for r in recs:
            if r.role is None or r.role not in roles:
                continue
            target = roles[r.role]
            if r.value == target:
                continue
            if r.kind == "frontmatter":
                new = _FM_PIN_RE.sub(
                    lambda m: f"{m.group(1)}{m.group(2)}{target}{m.group(4)}{m.group(5)}",
                    new,
                )
            else:
                def _repl(m, _old=r.value, _new=target):
                    return f"{m.group(1)}{_new}{m.group(3)}" if m.group(2) == _old else m.group(0)
                new = _INLINE_PIN_RE.sub(_repl, new)
            changes.append((lineno, r.kind, r.role, r.value, target))
        keep_nl[lineno - 1] = new + nl
    return "".join(keep_nl), changes


def load_roles_config(
    config_path: Path, local_path: Path | None = None
) -> tuple[dict[str, str], list[str]]:
    """Load ``(roles, served)`` from *config_path*, layering *local_path* on top.

    Local ``roles`` keys override (local wins); local ``served`` entries extend
    the allowlist. PyYAML is required (Sysop's run_checks already depends on it).
    """
    import yaml

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    roles = {str(k): str(v) for k, v in (data.get("roles") or {}).items()}
    served = [str(s) for s in (data.get("served") or [])]
    if local_path is not None and local_path.is_file():
        ldata = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        roles.update({str(k): str(v) for k, v in (ldata.get("roles") or {}).items()})
        for s in (ldata.get("served") or []):
            if str(s) not in served:
                served.append(str(s))
    return roles, served


def find_role_violations(
    root: Path, roles: dict[str, str], served: list[str]
) -> list[tuple[str, PinRole, str]]:
    """Return ``[(relpath, pin, reason), ...]`` for every pin that fails validation.

    Three independent failure modes: a pin with no governing role marker; a role
    that the config does not define; a role that resolves to a non-served model
    (the loud-sunset signal — drop a model from ``served:`` and any role still
    mapped to it goes red here).
    """
    served_set = set(served)
    out: list[tuple[str, PinRole, str]] = []
    for path in iter_skill_files(root):
        rel = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        for r in analyze_text(path.read_text(encoding="utf-8")):
            if r.role is None:
                out.append((rel, r, "pin has no governing `<!-- sysop:model-roles … -->` marker"))
            elif r.role not in roles:
                out.append((rel, r, f"undefined role {r.role!r} (not in served_models.yml roles:)"))
            elif roles[r.role] not in served_set:
                out.append((rel, r, f"role {r.role!r} -> {roles[r.role]!r} is not in served:"))
    return out
