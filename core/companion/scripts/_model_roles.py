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
    read_skill_text,
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
# model as a real pin (every pin `check_skill_models.py --list` prints is
# operative); a future author who
# needs a literal `model: "..."` example in such a file should phrase it without
# the `model:`-prefixed quoted form.
_FM_PIN_RE = re.compile(r'^(\s*model:\s*)(["\']?)([^"\'\s#]+)(["\']?)(\s*)$')
_INLINE_PIN_RE = re.compile(r'(model[`:\s]*["\'])([^"\']+)(["\'])')

# EFFORT (`Q-675`, Phase 381). The Agent tool takes a per-spawn `effort` since Claude Code
# 2.1.292, and an inline pin may carry one: an effort segment written IMMEDIATELY after the
# model pin, as its own code span, in the pin's style —
#
#     `model`: `"sonnet"`, `effort`: `"high"`       (the backticked-key style)
#     `model: "sonnet"`, `effort: "high"`           (the one-span style)
#
# The segment belongs to the pin before it, so it takes that pin's role. Position is the
# whole binding: the resolver inserts, rewrites or removes the segment there and nowhere
# else, so an `effort:` mentioned elsewhere on the line is prose, not a pin. Frontmatter
# pins carry no effort; a frontmatter skill runs in the main conversation at the session's
# own level.
_INLINE_PIN_EFFORT_RE = re.compile(
    r'(model[`:\s]*["\'])([^"\']+)(["\'])(`?)'
    r'(,\s*`effort(?:`:\s*`|:\s*)"([^"]*)"`)?'
)

#: The levels the Agent tool's `effort` parameter accepts — a closed enum, like `model`.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
#: The value that means "pass no effort": the spawn runs at the session's level. Also what a
#: local overlay writes to undo a shipped effort (`efforts: {executor: none}`).
NO_EFFORT = "none"

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
# every skill the remapped role governs — `check_skill_models.py --list` prints
# the live set; `reasoning` and the roles that follow it cover the planning,
# adversarial-review, execution, judging and audit spawns.
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
    #: The effort segment's literal after an inline pin, or None when the pin carries none.
    effort: str | None = None


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
        for im in _INLINE_PIN_EFFORT_RE.finditer(line):
            out.append(PinRole(i, "inline", im.group(2), line_role, im.group(6)))
    return out


def managed_pins(text: str) -> list[PinRole]:
    """The pins in *text* that Sysop owns: every pin under a file marker, else each marked line's.

    A `sysop:model-roles` file marker hands the whole file to Sysop, so an unmarked pin there
    is an error. A per-pin `sysop:role=` marker hands over every pin on its line, as it governs
    them (`analyze_text`, `_resolve_line_efforts`), and nothing else: a step file
    (`review-close/steps/*.md`) has no frontmatter and carries per-pin markers alone, and a
    consumer's skill may copy one marked line beside pins of its own. Without a file marker a
    pin carries a role only through its line's marker, so the rest stay out of scope. The
    gate, the population count, `--defaults` and the resolver's refusal judged the file marker
    alone and could not see a step file's pin (`Q-700`).
    """
    pins = analyze_text(text)
    if _FILE_MARKER_RE.search(text):
        return pins
    return [p for p in pins if p.role is not None]


def resolve_text(
    text: str, roles: dict[str, str], efforts: dict[str, str | None] | None = None
) -> tuple[str, list[tuple]]:
    """Rewrite each pin's value to its role's model, and each inline pin's effort.

    Returns ``(new_text, changes)`` where changes is
    ``[(lineno, kind, role, old_value, new_value), ...]``; an effort change has kind
    ``"effort"`` and ``None`` for an absent segment. Pins whose role is None or absent
    from *roles* are left untouched (a structural error the caller surfaces); pins
    already at the target value are skipped. With *efforts* None the effort segments
    are left exactly as they are, which is what a caller predating `Q-675` gets.
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
        if efforts is not None:
            new = _resolve_line_efforts(new, recs, roles, efforts, lineno, changes)
        keep_nl[lineno - 1] = new + nl
    return "".join(keep_nl), changes


def _effort_segment(model_key: str, level: str) -> str:
    """The effort segment in the style of the pin it follows (see `_INLINE_PIN_EFFORT_RE`)."""
    if "`" in model_key:
        return f', `effort`: `"{level}"`'
    return f', `effort: "{level}"`'


def _resolve_line_efforts(line, recs, roles, efforts, lineno, changes):
    """Insert, rewrite or remove the effort segment after each inline pin on *line*.

    Every inline pin on one line shares that line's role (a per-pin marker governs its
    whole line), so the target is computed once from the first inline record.
    """
    inline = [r for r in recs if r.kind == "inline"]
    if not inline:
        return line
    role = inline[0].role
    if role is None or role not in roles:
        return line
    target = efforts.get(role)

    def _repl(m):
        current = m.group(6)
        if current == target:
            return m.group(0)
        changes.append((lineno, "effort", role, current, target))
        head = m.group(1) + m.group(2) + m.group(3) + m.group(4)
        return head if target is None else head + _effort_segment(m.group(1), target)

    return _INLINE_PIN_EFFORT_RE.sub(_repl, line)


def load_roles_config(
    config_path: Path, local_path: Path | None = None
) -> tuple[dict[str, str], list[str]]:
    """Load ``(roles, served)`` from *config_path*, layering *local_path* on top.

    Local ``roles`` keys override (local wins); local ``served`` entries extend
    the allowlist. PyYAML is required (Sysop's run_checks already depends on it).
    """
    data = _load_yaml_mapping(config_path)
    roles = {str(k): str(v) for k, v in _as_role_map(data.get("roles"), config_path).items()}
    served = [str(s) for s in (data.get("served") or [])]
    if local_path is not None and local_path.is_file():
        ldata = _load_yaml_mapping(local_path)
        roles.update({str(k): str(v) for k, v in _as_role_map(ldata.get("roles"), local_path).items()})
        for s in (ldata.get("served") or []):
            if str(s) not in served:
                served.append(str(s))
    return _resolve_role_aliases(roles), served


class EffortConfigError(ValueError):
    """An `efforts:` entry names no role, or a level the Agent tool does not accept.

    A verdict on the mapping (exit 1), not a malformed file (exit 2) — the same split
    `RoleAliasError` keeps. A typo'd role key is refused rather than ignored, because an
    ignored `exectuor: high` is a spawn running at a level nobody chose.
    """


def load_role_efforts(
    config_path: Path, local_path: Path | None = None
) -> dict[str, str | None]:
    """Return ``{role: level or None}`` for every role, from ``efforts:`` (`Q-675`).

    A role with an ``efforts:`` entry takes it (``none`` means no effort argument). A role
    without one follows the role its value names, as its model does, so
    ``plan-review: reasoning`` runs at ``reasoning``'s effort until it is given its own.
    A role whose value is a model, with no entry, gets None: its spawns pass no effort and
    run at the session's level, which is what every pin did before `Q-675`. Local entries
    win over shipped ones, key by key.
    """
    data = _load_yaml_mapping(config_path)
    raw_roles = {str(k): str(v) for k, v in _as_role_map(data.get("roles"), config_path).items()}
    efforts = _as_effort_map(data.get("efforts"), config_path)
    if local_path is not None and local_path.is_file():
        ldata = _load_yaml_mapping(local_path)
        raw_roles.update({str(k): str(v) for k, v in _as_role_map(ldata.get("roles"), local_path).items()})
        efforts.update(_as_effort_map(ldata.get("efforts"), local_path))
    unknown = sorted(k for k in efforts if k not in raw_roles)
    if unknown:
        raise EffortConfigError(
            f"`efforts:` names {', '.join(repr(k) for k in unknown)}, which "
            f"{'is not a role' if len(unknown) == 1 else 'are not roles'} in `roles:`"
        )
    bad = sorted(f"{k}: {v!r}" for k, v in efforts.items()
                 if v not in EFFORT_LEVELS and v != NO_EFFORT)
    if bad:
        raise EffortConfigError(
            f"`efforts:` holds a level the Agent tool does not accept ({'; '.join(bad)}); "
            f"use one of {', '.join(EFFORT_LEVELS)}, or `{NO_EFFORT}` for no effort argument"
        )
    out: dict[str, str | None] = {}
    for role in raw_roles:
        seen = [role]
        current = role
        while current not in efforts and raw_roles.get(current) in raw_roles \
                and raw_roles[current] not in seen:
            current = raw_roles[current]
            seen.append(current)
        level = efforts.get(current)
        out[role] = None if level in (None, NO_EFFORT) else level
    return out


@dataclass(frozen=True)
class RoleRow:
    """One role as `check_skill_models.py --defaults` prints it (`Q-676`)."""

    role: str
    #: What `roles:` maps it to: a model, or the name of the role it follows.
    value: str
    model: str
    #: The effort its inline spawns pass, or None for the session's level.
    effort: str | None
    #: True when the local overlay sets the role's model or its effort.
    local: bool
    about: str | None


def describe_roles(
    config_path: Path, local_path: Path | None = None
) -> tuple[list[RoleRow], dict]:
    """Return ``(rows, notes)``: every role in file order, and the file's `reevaluated:` /
    `cost_shape:` keys. Models and efforts come from the loaders the checker and the
    resolver use, so the table cannot disagree with what a role resolves to."""
    roles, _served = load_roles_config(config_path, local_path)
    efforts = load_role_efforts(config_path, local_path)
    data = _load_yaml_mapping(config_path)
    raw = {str(k): str(v) for k, v in _as_role_map(data.get("roles"), config_path).items()}
    about = _as_text_map(data.get("about"))
    local_keys: set[str] = set()
    if local_path is not None and local_path.is_file():
        ldata = _load_yaml_mapping(local_path)
        lroles = {str(k): str(v) for k, v in _as_role_map(ldata.get("roles"), local_path).items()}
        raw.update(lroles)
        local_keys = set(lroles) | set(_as_effort_map(ldata.get("efforts"), local_path))
    rows = [RoleRow(role, raw[role], roles[role], efforts.get(role), role in local_keys,
                    about.get(role)) for role in raw]
    notes = {"reevaluated": data.get("reevaluated"), "cost_shape": data.get("cost_shape")}
    return rows, notes


def _as_text_map(value: object) -> dict[str, str]:
    """`about:` as ``{role: line}``. Display text only, so a malformed value prints dashes
    rather than refusing the table."""
    if not isinstance(value, dict):
        return {}
    return {str(k): " ".join(str(v).split()) for k, v in value.items() if v is not None}


def _as_role_map(value: object, source: Path) -> dict:
    """`roles:` as a mapping, or a shape error (exit 2). A scalar `roles: high` raised
    `AttributeError` from `.items()` at exit 1, which `install.sh` printed as
    `REFUSED (invalid mapping)`: a verdict made from a crash (Phase 381 round, lens 3)."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigShapeError(
            f"{source}: `roles:` must be a mapping of role to model, got "
            f"{type(value).__name__} ({value!r}). Write it as:\n  roles:\n    reasoning: fable"
        )
    return value


def _as_effort_map(value: object, source: Path) -> dict[str, str]:
    """Coerce an `efforts:` value to ``{role: level}``, or refuse its shape."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigShapeError(
            f"{source}: `efforts:` must be a mapping of role to level, got "
            f"{type(value).__name__} ({value!r}). Write it as:\n  efforts:\n    executor: high"
        )
    return {str(k): (NO_EFFORT if v is None else str(v)) for k, v in value.items()}


# How deep a chain of role-to-role references may go. Two is enough for every
# shape Sysop ships and the limit is stated rather than implied, so a longer
# chain is a loud error instead of a silent truncation.
_MAX_ALIAS_DEPTH = 8


class RoleAliasError(ValueError):
    """A cycle or an over-long chain in the `roles:` alias graph.

    Distinct from the ValueError `_load_yaml_mapping` raises for a malformed
    config, because the two are different exit codes the callers pin: a YAML
    typo is a USAGE error (2) and must not be reported as the consumer's model
    mapping being wrong (1). Catching the base class here collapsed that
    distinction and reddened three pre-existing guards.
    """


def _resolve_role_aliases(roles: dict[str, str]) -> dict[str, str]:
    """Let a role's value name ANOTHER ROLE, and resolve it to that role's model.

    Phase 262. A narrow role split — `convention-gate`, which governed one pin (two since Phase 328) —
    needed a default, and a hard-coded one was WRONG in a way that only showed up
    on upgrade. A consumer who had set `reasoning: sonnet` (the documented cheap
    lever) had both Step 2b agents on sonnet; adding `convention-gate: opus` as a
    literal silently moved the convention agent — the most-run deep spawn, and the
    expensive one — back to opus on their next `--update`, with nothing in the
    output naming it. Two keys would then be needed to buy what one key used to.

    `convention-gate: reasoning` expressed the thing that was true then: the role
    FOLLOWED `reasoning` unless the consumer said otherwise. A local override of
    `reasoning` flowed through; a local override of `convention-gate` won over it.
    (Since Phase 381 the gate ships as the literal `sonnet`, on the maintainer's
    decision, and `planner` / `plan-review` are the shipped roles that follow
    `reasoning`.) Either way the default install resolves to exactly the literals
    already in the shipped skills, so it stays a zero-byte no-op.

    Fail-closed is preserved, which is why this is an alias table and not a
    fallback: a value that is neither a role name nor a served model still
    reaches `check_skill_models.py` as-is and is rejected there, so a MISSPELLED
    role name does not silently inherit anything. A cycle raises rather than
    looping or picking a winner.
    """
    out: dict[str, str] = {}
    for role in roles:
        seen = [role]
        value = roles[role]
        depth = 0
        while value in roles and value not in seen:
            seen.append(value)
            value = roles[value]
            depth += 1
            if depth > _MAX_ALIAS_DEPTH:
                raise RoleAliasError(
                    f"role alias chain from {role!r} exceeds {_MAX_ALIAS_DEPTH} hops: "
                    + " -> ".join(seen)
                )
        if value in roles and value in seen:
            raise RoleAliasError(
                "role alias cycle: " + " -> ".join(seen + [value])
            )
        out[role] = value
    return out


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
    except UnicodeDecodeError as exc:
        # `Q-346` leg 1's class, one input over: a config saved in a non-UTF-8
        # encoding escaped the YAMLError catch as a traceback, which `install.sh`
        # then printed as a verdict on the mapping. A config it cannot decode is
        # a config it cannot read — the same answer ConfigShapeError already
        # carries, and the same exit code (2).
        raise ConfigShapeError(f"{path}: not valid UTF-8 — {exc}") from exc
    except OSError as exc:
        # The OTHER half of the same class, and the first cut of this catch left
        # it open. `read_skill_text` guards `(UnicodeDecodeError, OSError)` and
        # this one guarded only the decode; `load_roles_config` gates on
        # `is_file()`, which a mode-000 file passes. So an unreadable
        # `served_models.local.yml` — the documented, never-overwritten override
        # file — raised `PermissionError`, exited 1, and `install.sh` printed
        # `REFUSED (invalid mapping)` with the traceback under it: byte for byte
        # the shape this phase says it closed, on a config that parses fine.
        # Found by this phase's own execution lens.
        raise ConfigShapeError(f"{path}: cannot be read — {exc}") from exc
    except Exception as exc:
        # `Q-621`: PyYAML's constructors raise more than `YAMLError` — `ValueError`
        # for `2026-09-31`, `KeyError` for `!!bool abc`, and others. Still not valid YAML.
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
        text = read_skill_text(path)
        # Unreadable/undecodable is skipped, same as an unmarked file: see
        # `read_skill_text`. Both loops that walk this tree must agree, or the
        # population count passes and this one crashes one call later.
        if text is None:
            continue
        # `.claude/skills/` is Claude Code's standard user-skill directory, not
        # Sysop's private tree — a consumer's own skill can live beside the
        # shipped ones and legitimately carry a `model:` field. Such a file has no
        # `sysop:model-roles` marker, and validating it produced "pin has no
        # governing marker" for prose Sysop does not own. In `managed_only` mode
        # those files are skipped, because the alternative is telling a consumer
        # to hand their private skill to Sysop's resolver. A per-pin marker hands over its
        # own pin and nothing else (`managed_pins`, `Q-700`).
        for r in (managed_pins(text) if managed_only else analyze_text(text)):
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
            # The effort segment's literal, for the same reason as the arm above: on the
            # plugin path nothing rewrites it, and the Agent tool's `effort` is a closed
            # enum too (`Q-675`).
            if len(out) == before and r.kind == "inline" and r.effort is not None \
                    and r.effort not in EFFORT_LEVELS:
                out.append((rel, r, (
                    f"INLINE pin carries the effort {r.effort!r}, which the Agent tool's "
                    f"`effort` enum rejects ({', '.join(EFFORT_LEVELS)}). Remove the segment "
                    f"to pass no effort, or set the role's level under `efforts:`."
                )))
    return out
