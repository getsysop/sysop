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

# The two pin kinds do NOT accept the same values, and Phase 223 verified the
# asymmetry by execution rather than by reading a schema.
#
# A FRONTMATTER pin becomes a skill's `model:` field, which the docs describe as
# accepting the same values as `/model` — short aliases, full model ids, and
# meta-values such as `best` — plus `inherit`, which is frontmatter-only and not
# a `/model` alias. An unrecognized value there falls back to the session model
# rather than failing. (That half is docs-derived, not executed: only the inline
# half below was verified by making the calls.)
#
# An INLINE pin is different in kind: a skill body's `model: "<x>"` is copied by
# the agent into the Agent tool's `model` parameter, which is a CLOSED ENUM.
# Passing `best`, `inherit`, or a full model id (`claude-opus-5`) each returns
# `InputValidationError` — verified 2026-08-21 against Claude Code by making the
# calls, not by reading the schema. The failure lands mid-skill at spawn time, in
# every skill the remapped role governs: 13 inline pins today, 12 of them on the
# `reasoning` role, which covers the adversarial-review, judging and audit spawns.
#
# This default is what a consumer's harness accepts today. It is deliberately
# overridable — a harness that accepts more takes `inline_models:` in
# served_models.yml (or extends it in the local overlay) rather than patching
# this tuple, so a widened enum never requires a Sysop release.
INLINE_MODELS_DEFAULT = ("opus", "sonnet", "haiku", "fable")


class ConfigShapeError(ValueError):
    """A role config is syntactically valid YAML but structurally wrong.

    Distinct from "a pin failed validation": a malformed config is a usage error
    (exit 2), not a finding (exit 1). Reporting a YAML typo through the
    violation exit code told consumers their model pins were unresolvable when
    the real problem was a stray bracket.
    """


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
    data = _load_yaml_mapping(config_path)
    roles = {str(k): str(v) for k, v in (data.get("roles") or {}).items()}
    served = [str(s) for s in (data.get("served") or [])]
    if local_path is not None and local_path.is_file():
        ldata = _load_yaml_mapping(local_path)
        roles.update({str(k): str(v) for k, v in (ldata.get("roles") or {}).items()})
        for s in (ldata.get("served") or []):
            if str(s) not in served:
                served.append(str(s))
    return roles, served


def _load_yaml_mapping(path: Path) -> dict:
    """Parse a role config, raising `ConfigShapeError` on anything unusable.

    A syntax error used to surface as a raw traceback with exit 1 — the same
    code as "a pin failed validation" — so the shipped pre-commit example
    reported a stray bracket to the consumer as a model-pin failure. A config
    that parses to a list rather than a map raised `AttributeError` from
    `.get`, one frame further in.
    """
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigShapeError(f"{path}: not valid YAML — {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigShapeError(
            f"{path}: expected a mapping with `roles:` / `served:` keys, "
            f"got {type(data).__name__}"
        )
    return data


def load_inline_models(
    config_path: Path, local_path: Path | None = None
) -> list[str]:
    """Load the values an INLINE pin may resolve to.

    Falls back to ``INLINE_MODELS_DEFAULT`` when the config declares no
    ``inline_models:`` key — absence means "this config predates the key", not
    "anything goes", so the check still runs on an un-updated consumer config.
    A local overlay EXTENDS the list, matching ``served:`` semantics: a harness
    that accepts more values adds them without editing the Sysop-owned file.
    """
    data = _load_yaml_mapping(config_path)
    # Absent and declared are different answers, and the test is key PRESENCE,
    # not truthiness. A missing key means "this config predates the key" and the
    # built-in default applies. A key written as `inline_models:` (YAML null) or
    # `inline_models: []` means the author declared nothing legal, and every
    # inline pin goes red loudly rather than silently inheriting a default they
    # wrote the key to replace. Keying on `data.get(...) is None` conflated the
    # bare-key form with absence, which is the form a consumer reaches by
    # commenting out the list items.
    models: list[str] = (
        _as_model_list(data["inline_models"], config_path)
        if "inline_models" in data
        else [str(s) for s in INLINE_MODELS_DEFAULT]
    )
    if local_path is not None and local_path.is_file():
        ldata = _load_yaml_mapping(local_path)
        if "inline_models" in ldata:
            for value in _as_model_list(ldata["inline_models"], local_path):
                if value not in models:
                    models.append(value)
    return models


def _as_model_list(value: object, source: Path) -> list[str]:
    """Coerce an `inline_models:` value to a list of names, or refuse it.

    A YAML scalar is a string, and iterating a string yields characters — so
    `inline_models: opus` silently became the legal set `{o, p, u, s}` and turned
    every inline pin red with a nonsense diagnostic. A single-value scalar is
    idiomatic YAML and the shipped docs never show the local file's shape, so
    this is a shape a consumer reaches by writing the obvious thing.
    """
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigShapeError(
            f"{source}: `inline_models:` must be a list, got {type(value).__name__} "
            f"({value!r}). Write it as a YAML list:\n  inline_models:\n    - opus"
        )
    return [str(s) for s in value]


def find_role_violations(
    root: Path,
    roles: dict[str, str],
    served: list[str],
    inline_models: list[str] | None = None,
    managed_only: bool = False,
) -> list[tuple[str, PinRole, str]]:
    """Return ``[(relpath, pin, reason), ...]`` for every pin that fails validation.

    **Five** independent failure modes. Four judge the ROLE's target: a pin with
    no governing role marker; a role the config does not define; a role that
    resolves to a non-served model (the loud-sunset signal — drop a model from
    ``served:`` and any role still mapped to it goes red here); and a role
    governing an INLINE pin that resolves to a value the Agent tool's closed
    ``model`` enum rejects (Phase 223 — see ``INLINE_MODELS_DEFAULT``).

    The fifth judges the PIN's own literal value, and it exists because the other
    four do not. They all ask what a role resolves to; none of them reads what the
    shipped file says, so a hand-edited literal passed every one of them — and on
    the plugin install path there is no resolver, so the literal is what the
    harness receives. Phase 223's round, lens 3.

    Both inline modes are scoped to ``kind == "inline"`` on purpose: the same
    value that breaks a spawn is legal in frontmatter, so failing both kinds would
    refuse a correct config.
    """
    served_set = set(served)
    inline_set = set(inline_models if inline_models is not None else INLINE_MODELS_DEFAULT)
    out: list[tuple[str, PinRole, str]] = []
    for path in iter_skill_files(root):
        rel = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        text = path.read_text(encoding="utf-8")
        # `.claude/skills/` is Claude Code's standard user-skill directory, not
        # Sysop's private tree — a consumer's own skill can live beside the
        # shipped ones and legitimately carry a `model:` field. Such a file has no
        # `sysop:model-roles` marker, and validating it produced "pin has no
        # governing marker" for prose Sysop does not own. In `managed_only` mode
        # those files are skipped, because the alternative is telling a consumer
        # to hand their private skill to Sysop's resolver.
        if managed_only and _FILE_MARKER_RE.search(text) is None:
            continue
        for r in analyze_text(text):
            before = len(out)
            if r.role is None:
                out.append((rel, r, "pin has no governing `<!-- sysop:model-roles … -->` marker"))
            elif r.role not in roles:
                out.append((rel, r, f"undefined role {r.role!r} (not in served_models.yml roles:)"))
            elif roles[r.role] not in served_set:
                out.append((rel, r, f"role {r.role!r} -> {roles[r.role]!r} is not in served:"))
            elif r.kind == "inline" and roles[r.role] not in inline_set:
                out.append((rel, r, (
                    f"role {r.role!r} -> {roles[r.role]!r} governs an INLINE pin, but the "
                    f"Agent tool's `model` parameter is a closed enum "
                    f"({', '.join(sorted(inline_set))}). This spawn would fail at call "
                    f"time. Map the role to an alias, or extend `inline_models:` if your "
                    f"harness accepts it."
                )))

            # The pin's LITERAL value, checked independently of its role's target
            # — but only when the arms above found nothing for this pin, so one
            # broken pin is one finding. Reporting it twice inflated the count
            # ("24 pin(s)" for 12 pins) under a header that says "pin(s)".
            # The four arms above all judge what a role *resolves to*; none of them
            # reads what the shipped file actually says, so a hand-edited or
            # mis-merged `model: "best"` passed every one of them. That gap is not
            # academic: on the plugin install path `core/skills/` is consumed
            # verbatim — no installer, no resolver — so the literal in the file IS
            # what the harness receives. Phase 223's round, lens 3.
            if len(out) == before and r.kind == "inline" and r.value not in inline_set:
                out.append((rel, r, (
                    f"INLINE pin holds the literal value {r.value!r}, which the Agent "
                    f"tool's `model` enum rejects ({', '.join(sorted(inline_set))}). "
                    f"Whatever its role resolves to, this is the value the harness "
                    f"receives on the plugin path, where nothing rewrites it. On the "
                    f"bash-installed path, `resolve_skill_models.py --apply` rewrites "
                    f"literals from the mapping; on the plugin path the file must be "
                    f"corrected at source."
                )))
    return out
