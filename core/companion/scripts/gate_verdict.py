#!/usr/bin/env python3
"""gate_verdict.py — `/review-close` Step 2b: reuse a gate verdict whose inputs have not moved (`Q-667`).

A relaunched close used to re-run both Step 2b gates on a branch whose head had not moved.
This records a gate's `APPROVED` against everything the agent's review depended on, and a
later run that finds the same key reports the recorded verdict instead of spawning. The
skill text is the contract: Step 2b says when each subcommand runs and what each exit means.

The key is a sha256 over, in order:

    gate       convention | security
    tip        the target's commit: the branch tip, or `HEAD` for `unpushed-main`
    base       the merge-base of that commit with `<default branch>`, or with
               `origin/<default branch>` for `unpushed-main`: the two ends of the diff basis
    sources    sha256 of what the agent can be handed: for `convention`, the whole of
               `CLAUDE.md`, the section names given, and the convention map and its overlay
               (Step 2b's `TOTAL` 0 arm hands the map); for `security`, the security map and
               its overlay, and `security_map_filter.py` and `security_partition.py` beside
               this script, which cut the target's copy of them (`Q-666`). An absent file is hashed as absent. Whole files, not sections:
               a section cut by heading ends early at a fenced `## ` line, misses a heading
               with trailing space and reads only the first of two, and in a key each of
               those would reuse a verdict over a rule the agent was handed and never had.
    template   sha256 of the `### 2b.` section of the skill's `SKILL.md`, which holds both
               gates' prompts. An update that changes the step changes every key.
    model      the model on the role's spawn line in that section
    effort     the effort on the same line. A line with none (`served_models.yml`: a role
               mapped to a model with no effort entry passes none) runs at the session's
               effort, which no key can see, so it is never reused.

Records are `sysop/runtime/gate-verdicts/<gate>-<hash of target>.json` in the MAIN checkout
(resolved through git-common-dir, like `close_arms.py`), one per gate and target, replaced
on each record. Only an `APPROVED` with `NOTES: none` is recorded: a reused verdict carries
no notes, so one with notes must run again or `4a-fix` would lose them.

Subcommands, both run from the repo root (the sources are read from the top level of the
checkout either way):

    lookup <gate> <target> <default-branch> <skill-dir> [<section>...]
        Exit 0, printing `REUSE <target> — verdict reused from <utc> (<key>)`: the recorded
        key equals this one. Exit 3, printing `MISS <target> (<key>): <why>`: no record, one
        for other inputs, or a spawn line with no effort; every miss but the last then prints
        `KEY: <the whole key>`. Run it before reading anything the agent will be handed, so
        that `record`'s comparison covers every read. Exit 2: the key could not be computed; the message says why.
    record <gate> <target> <default-branch> <skill-dir> <echoed-sha> <key> [<section>...]
        After the agent returned `VERDICT: APPROVED` and `NOTES: none`. `<echoed-sha>` is the
        first line the agent reported, its pinned checkout's `HEAD`; `<key>` is the `KEY:` the
        lookup printed. Exit 0, printing `RECORDED <target> (<key>)`. Exit 2, recording
        nothing: the echo is not the target's commit now (a misplaced agent, or a tip that
        moved after the spawn), `<key>` is not 64 hex characters, the key is not this one (an
        input moved after the lookup, so the agent reviewed other inputs), the spawn line names
        no effort, or the key could not be computed.

`<section>` arguments are the `convention` gate's, the same set Step 2b step 1 measured, and
the `security` gate takes none. `unpushed-main` names the unpushed-main group, so a branch of
that name is refused: its verdict and the group's would share one record.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GATES = {"convention": "convention-gate", "security": "security-gate"}
UNPUSHED = "unpushed-main"
SOURCES = {
    "convention": ("CLAUDE.md", ".claude/convention_map.md", ".claude/convention_map.project.md"),
    "security": (".claude/security_map.md", ".claude/security_map.project.md"),
}
# The security agent is handed the target's copy of the maps, which the filter cuts with the
# heading pattern it imports.
FILTER = tuple(Path(__file__).resolve().with_name(n) for n in ("security_map_filter.py", "security_partition.py"))
FIELDS = ("gate", "tip", "base", "sources", "template", "model", "effort")
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


class Refuse(Exception):
    """Exit 2 with the message."""


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], capture_output=True, env=GIT_ENV)
    out = os.fsdecode(p.stdout).strip()
    if p.returncode != 0 or not out:
        err = os.fsdecode(p.stderr).strip().splitlines()
        raise Refuse(f"`git {' '.join(args)}` failed: {err[-1] if err else 'no output'}")
    return out


def main_root() -> Path:
    found = Path(git("rev-parse", "--git-common-dir"))
    return (found if found.is_absolute() else (Path.cwd() / found).resolve()).parent


def read_bytes(p: Path):
    """The file's bytes, or None when it does not exist. Anything else is a refusal."""
    try:
        return p.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refuse(f"{p} could not be read ({type(e).__name__}: {e})") from e


def read_text(p: Path) -> str:
    data = read_bytes(p)
    if data is None:
        raise Refuse(f"{p} does not exist")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Refuse(f"{p} is not UTF-8 ({e})") from e


def ends(target: str, default: str) -> tuple:
    if target == UNPUSHED:
        named = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{UNPUSHED}"],
                               capture_output=True, env=GIT_ENV)
        if named.returncode == 0:
            raise Refuse(f"a branch is named {UNPUSHED}, the name of the unpushed-main group: "
                         "rename it, or this gate runs every time")
        tip = git("rev-parse", "--verify", "HEAD^{commit}")
        upstream = git("rev-parse", "--verify", f"origin/{default}^{{commit}}")
        return tip, git("merge-base", upstream, tip)
    tip = git("rev-parse", "--verify", f"{target}^{{commit}}")
    return tip, git("merge-base", git("rev-parse", "--verify", f"{default}^{{commit}}"), tip)


def top_level() -> Path:
    """Where the sources are read: the top level of the checkout the command runs in. A
    relative path read from a subdirectory finds no file, hashes as absent, and stops seeing
    every edit to it."""
    found = Path(git("rev-parse", "--show-toplevel"))
    return found if found.is_absolute() else (Path.cwd() / found).resolve()


def hash_files(paths) -> str:
    h, root = hashlib.sha256(), top_level()
    for rel in paths:
        data = read_bytes(root / rel)
        h.update(f"{rel}\0{'absent' if data is None else sha256(data)}\n".encode())
    return h.hexdigest()


def sources(gate: str, sections: list) -> str:
    if gate == "security":
        if sections:
            raise Refuse("the security gate takes no sections")
        cut = ",".join("absent" if d is None else sha256(d) for d in map(read_bytes, FILTER))
        return f"security:{hash_files(SOURCES['security'])}:{cut}"
    bad = [s for s in sections if not s.strip() or re.match(r"#+\s", s) or re.search(r"<[^<>]*>", s)]
    if not sections or bad:
        raise Refuse(f"pass each section's name as one argument, without its `## `: {bad or sections!r}")
    names = sha256("\0".join(sections).encode())
    return f"convention:{names}:" + hash_files(SOURCES["convention"])


def step_2b(skill_dir: str) -> str:
    """From the `### 2b.` heading to the next line that starts `### `, or the end."""
    lines = read_text(Path(skill_dir) / "SKILL.md").splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.startswith("### 2b. ")]
    if len(starts) != 1:
        raise Refuse(f"{skill_dir}/SKILL.md has {len(starts)} `### 2b.` headings, not 1")
    end = next((i for i in range(starts[0] + 1, len(lines)) if lines[i].startswith("### ")), len(lines))
    return "".join(lines[starts[0]:end])


def spawn_line(section: str, role: str) -> tuple:
    lines = [ln for ln in section.splitlines() if f"<!-- sysop:role={role} -->" in ln]
    if len(lines) != 1:
        raise Refuse(f"Step 2b has {len(lines)} lines marked `sysop:role={role}`, not 1")
    model = re.search(r'model: "([^"]+)"', lines[0])
    effort = re.search(r'effort: "([^"]+)"', lines[0])
    if not model:
        raise Refuse(f"the `sysop:role={role}` line names no model")
    return model.group(1), effort.group(1) if effort else ""


def key_fields(args: list, with_echo: bool) -> tuple:
    need = 6 if with_echo else 4
    if len(args) < need:
        raise Refuse("missing arguments; see the usage in this script's docstring")
    gate, target, default, skill_dir = args[:4]
    echo = (args[4], args[5]) if with_echo else None
    sections = args[need:]
    if gate not in GATES:
        raise Refuse(f"{gate!r} is not a gate: {' or '.join(GATES)}")
    if not target.strip() or not default.strip() or re.search(r"<[^<>]*>", target + default + skill_dir):
        raise Refuse("substitute the target, the default branch and the skill directory")
    tip, base = ends(target, default)
    section = step_2b(skill_dir)
    model, effort = spawn_line(section, GATES[gate])
    fields = {"gate": gate, "tip": tip, "base": base, "sources": sources(gate, sections),
              "template": sha256(section.encode()), "model": model, "effort": effort}
    return target, fields, echo


def key_of(fields: dict) -> str:
    return sha256("".join(f"{k}={fields[k]}\n" for k in FIELDS).encode())


def record_path(gate: str, target: str) -> Path:
    return main_root() / "sysop" / "runtime" / "gate-verdicts" / f"{gate}-{sha256(target.encode())[:16]}.json"


def cmd_lookup(args: list) -> int:
    target, fields, _ = key_fields(args, with_echo=False)
    key = key_of(fields)
    if not fields["effort"]:
        # No `KEY:` line: the skill records only a target whose lookup printed one.
        print(f"MISS {target} ({key[:12]}): the {GATES[fields['gate']]} spawn line names no "
              "effort, so it runs at the session's, and is never reused")
        return 3
    p = record_path(fields["gate"], target)
    data = read_bytes(p)
    if data is None:
        print(f"MISS {target} ({key[:12]}): no recorded verdict")
        print(f"KEY: {key}")
        return 3
    try:
        rec = json.loads(data.decode("utf-8"))
        stored = {k: rec[k] for k in FIELDS}
        verdict, when = rec["verdict"], rec["recorded"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        print(f"MISS {target} ({key[:12]}): the record could not be read ({type(e).__name__})")
        print(f"KEY: {key}")
        return 3
    if rec.get("key") != key or stored != fields or verdict != "APPROVED":
        moved = [k for k in FIELDS if stored.get(k) != fields[k]] or ["verdict"]
        print(f"MISS {target} ({key[:12]}): {', '.join(moved)} changed since {when}")
        print(f"KEY: {key}")
        return 3
    print(f"REUSE {target} — verdict reused from {when} ({key[:12]})")
    return 0


def cmd_record(args: list) -> int:
    target, fields, (echo, given) = key_fields(args, with_echo=True)
    echo = echo.strip().lower()
    if not SHA.fullmatch(echo) or echo != fields["tip"]:
        raise Refuse(f"not recorded: the agent echoed {echo!r} and {target} is {fields['tip']} now")
    if not fields["effort"]:
        raise Refuse(f"not recorded: the {GATES[fields['gate']]} spawn line names no effort")
    given = given.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", given):
        raise Refuse(f"not recorded: {given[:20]!r} is not a key: pass the 64 characters the "
                     "lookup printed after `KEY:`")
    key = key_of(fields)
    if given != key:
        raise Refuse(f"not recorded: the key is {key[:12]} now and the lookup before the spawn "
                     f"printed {given[:12]!r}: an input moved while the agent ran")
    p = record_path(fields["gate"], target)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"key": key, "target": target, **fields, "verdict": "APPROVED", "notes": "none",
           "recorded": utc()}
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".gate-verdict-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    print(f"RECORDED {target} ({key[:12]})")
    return 0


COMMANDS = {"lookup": cmd_lookup, "record": cmd_record}


def main(argv: list) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: gate_verdict.py {{{'|'.join(COMMANDS)}}} ...", file=sys.stderr)
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except Refuse as e:
        print(f"gate_verdict: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
