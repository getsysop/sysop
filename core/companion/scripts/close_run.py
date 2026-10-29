#!/usr/bin/env python3
"""close_run.py — the run directory behind `/review-close --prepare` and `--resume`.

A prepare runs Steps 1, 2, 3 and 3c, records its questions instead of asking
them, and stops before Step 3b. A resume asks them in one pass and continues.
This script owns the part of that which must not depend on the runner's
memory: where the run lives, what the prepare saw, and what moved since.

The run lives in the MAIN checkout's `sysop/runtime/close/<run-id>/`
(resolved through git-common-dir, so every linked worktree finds the same one):

    manifest.json        written here; the inputs `check` compares
    branches/<b>.md      written by the runner; one per branch (`begin` names each path)
    close.md             written by the runner; close-wide state
    questions.md         written by the runner; the recorded questions
    answers.md           written by the runner at resume
    halted.md            written by the runner when a prepare halts
    2b/                  `finish` copies Step 2b's runtime files here

Subcommands (each prints one line per fact, and exits 0 unless it says otherwise):

    begin <default-branch> [--agent <name>] [<branch>...]
        After Step 1, before Step 2a. `--agent` (from `--prepare --agent`) is recorded, and
        `finish`'s `RESUME:` line then names the unattended resume. No branch at all is a cycle of unpushed commits only. Creates the run and records, per branch:
        its tip, its lock files and pending docs (by content), and whether its tip
        was already in the default branch; and, for the run: local and origin
        `<default-branch>`, the recorded PR heads, the conventions and maps, and
        `core.hooksPath`. Prints `RUN:`, `DIR:` and one `STATE <branch>: <path>`
        per branch. Exit 1: a branch does not exist, or an input could not be read.

    finish <run-id>
        At the end of Step 3c. Re-reads origin `<default-branch>` (Step 3c fetched
        it), copies `sysop/runtime/2b-conventions.md` and `2b-security.md` into
        `2b/`, and marks the run finished. Prints `QUESTIONS: <n>` and one
        `MOVED DURING PREPARE:` line per input that moved since `begin`.
        Exit 1, marking nothing: a branch has no state file, or `questions.md`
        is missing.

    resumable [--agent <name>]
        Prints the newest prepare's run id, alone on stdout, when a resume can load it
        (finished, not halted, not consumed; with `--agent`, prepared by that agent), so a
        script can chain a night's two sessions. Exit 2 otherwise: never an older run.

    load <run-id> <default-branch>
        First thing at resume. Prints `DIR:`, `QUESTIONS: <n>` and `ANSWERED: <n>`.
        Exit 2 (refused): the run is missing, unparsable, unfinished, halted or
        already consumed, or was prepared against another default branch.

    check <run-id> <default-branch>
        At resume, after Step 1. Same refusals as `load`, then one line per thing
        that must re-run (see `RERUN`/`GONE` below), `NOTE:` lines that re-run
        nothing, and `CURRENT` when nothing moved.

    consume <run-id> [--restore-2b]
        Before Step 3b at resume. Marks the run consumed, so it cannot be resumed
        twice. With `--restore-2b`, copies `2b/`'s files back to `sysop/runtime/`.
        Exit 2: unfinished or already consumed.

`check`'s lines:

    GONE <branch>: merged in <ref>   the tip reached <ref> since the prepare
    GONE <branch>: deleted           the branch is gone and its tip is in neither ref
    RERUN <branch>: <what> moved     tip, lock or pending doc
    RERUN ALL: recorded PR heads changed
    RERUN 2b: <file> changed         CLAUDE.md, a convention map or a security map
    RERUN 3: <ref> moved             local or origin <default-branch>
    NOTE: core.hooksPath ...         reported, re-runs nothing

`begin`, `load` and `reader` also refuse (exit 2) while a hand-off below is waiting,
or while an unattended close's `STOPPED` marker below stands.

The Step 4d split (`/review-close --request-review` and `--land`, `Q-411`) keeps a
hand-off in its own run directory: `handoff.json` (written here), `report.md`
(written by the runner: the `## Step 6` lists and `## Step 8` rows half B needs)
and `AWAITING`, which every other close stops on until the hand-off lands or is
abandoned. The second reader is read from CLAUDE.md `## Second reader`.

    reader
        Validates `## Second reader` and prints it. Exit 2: missing or malformed.

    hand-off <default-branch> <branch> <PR> <pushed-from-sha> [--keep-branch]
        Half A, after Step 4d's push and PR. Checks the PR is open, not a draft,
        from this repository, based on <default-branch>, and headed at <branch>'s
        local tip; records the hand-off; posts the configured request as a PR
        comment. Prints `RUN:`, `DIR:`, `REQUESTED:` and `REPORT:`. Exit 2: another
        hand-off is waiting or being recorded, the config or the PR does not
        qualify, or the SHA is not local <default-branch>'s commit at the push (the
        merge base of it and the head). Exit 1 after recording: the post failed.

    seal <run-id>
        Half A, once report.md is written. Exit 1 names what report.md lacks.
        Prints `LAND: /review-close --land <run-id>`.

    awaiting [--agent <name>]
        Half B's launcher (Phase 423): prints the waiting hand-off's run id, alone on
        stdout, when a land can take it (sealed, still awaiting a merge, not parked
        unless its auto-merge is still to turn off, and with `--agent`, handed off by
        that agent), so a script can start the night's third session. Exit 2 otherwise,
        and while a `STOPPED` marker waits for a human.

    land-check <run-id> <default-branch>
        Half B. Prints the record (`PR:`, `BRANCH:`, `SHAPE:`, `HEAD:`, `PUSHED FROM:`,
        `KEEP BRANCH:`, `REPORT:`), the reviewer's reading (`READER:` lines) and a
        `VERDICT:`. Exit 0: MERGE, or ALREADY MERGED. Exit 4: PARK. Exit 5: WAIT.

    re-request <run-id> <default-branch>
        After a park is fixed on the branch and pushed: records the branch's new
        head and posts the request again.

    landed <run-id>
        Half B, once the PR reads MERGED: removes the locks Step 4c kept and the
        `AWAITING` marker. Exit 2: the PR is not merged.

    abandon <run-id>
        For a PR closed unmerged: removes `AWAITING`, leaves the branch and the
        kept locks. Exit 2 on an open PR (close or land it) or a merged one (land it).

The unattended close (`Q-411`, Phases 366, 374 and 375) reads CLAUDE.md
`## Unattended close class`: `allow:` and `exclude:` path globs and a
`blast_radius:` ceiling, which selection and the signed gate (`close_gate.py`)
read; `code_owner:` and `gate_app:`, which the gate and the land require; and
`attested:`, which the land requires. The governing set is always excluded, compared folded (NFKC, then
casefold): `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `AGENTS.override.md`,
`.mcp.json`, `.gitmodules` and `.gitattributes` anywhere, any `.claude`, `.agents`
or `.codex` directory, `sysop/**`, `.github/**`, `/CODEOWNERS` and
`/docs/CODEOWNERS`; so are tasks that are manual_smoke, solo or user_action, and a
branch with a held pending doc.

    class
        Validates the class and prints it, with a `WARN:` line for each path a
        close commits itself that the class does not admit. Exit 2: missing or
        malformed.

    eligible <default-branch> <agent> [<branch>...]
        Half A's selection, after Step 1: one `IN <branch>: ...` or
        `OUT <branch>: <reasons>` line per branch. A branch is IN only when one
        lock names it and reads `agent: <agent>`, its task passes the class, no
        pending doc of its carries `hold:`, and it merges cleanly onto local
        <default-branch> with every path the merge result changes admitted and no
        symlink or gitlink among them (the merge result GitHub's squash would
        make, as the gate reads it; git 2.40 or newer). A `NOTE:` line names paths
        local <default-branch>'s unpushed commits add that the class refuses.

    hand-off ... --agent <name>
        Records the hand-off as landable unattended by <name>; refuses without a
        valid class.

    land-check <run-id> <default-branch> --unattended <agent>
        Half B with no human (Phase 375). Refuses (exit 2) a hand-off made without
        --agent, or by another agent. A `PARKED` hand-off prints its park and exits
        4 without reading GitHub. Otherwise re-checks the PR; reads the class at the
        default branch's live tip; checks the kept locks' owner and that report.md
        names no held-doc branch; checks Step 6's two local conditions; then the
        server setup with the token `gh` holds (not the code owner, role `write`,
        the rulesets' code-owner review, stale-review dismissal and strict check
        pinning `sysop/close-gate` to `gate_app:`, `current_user_can_bypass: never`
        on each, the gate environment's one branch rule) and the class's
        `attested:` date. Then every registered check must have passed, the gate's
        among them: a failed one parks, a pending or absent one waits (exit 5) for
        the hand-off's timeout, then parks. Then it turns on auto-merge (`gh pr
        merge --auto --squash --match-head-commit`), which merges at once when
        GitHub's rules pass: `VERDICT: ALREADY MERGED` (exit 0), or `VERDICT: ARMED`
        (exit 5) while GitHub waits. Paths, task fields and the reader's verdict are
        the gate's, not this command's. Any park writes `PARKED` (exit 4), and turns
        auto-merge off first when it is on.

    park <run-id> <code> <reason>
        The runner's own parks under --unattended (a denied command, a stuck PR).
        Turns off auto-merge the unattended land turned on.

    unpark <run-id>
        A human clears a park without a new request. `re-request`, `landed` and
        `abandon` clear it too. `unpark` and `re-request` turn off auto-merge the
        unattended land turned on, so the next land re-checks before arming again.

Half A with no human (`Q-664`, Phase 380) is `--prepare --agent <name>`, then
`--resume <run-id> --request-review --agent <name> --unattended`. A park of that close
before Step 4-pre is recorded in the run's `halted.md` and blocks nothing. From Step 4-pre
on it is durable, and so are three Step 3b exits that leave main's pending docs part-written:

    stop <run-id> <step> <reason>
        Writes `STOPPED` in the run directory, naming the step, the reason (the
        recovery included) and the `LOCKS_KEPT:` ids the runner passes as
        `--locks-kept <id>...` after the reason. `begin`, `load`, `reader`,
        `hand-off` and the unattended land refuse while one stands, so no close
        runs until a human clears it. The run directory need not hold a run: the
        marker is written whatever the run's state, since a stop that refused would
        leave the close unguarded.

    clear <run-id>
        A human removes a `STOPPED` marker once its recovery is done, and the
        marker is kept beside it as `STOPPED.cleared-<stamp>`.

A branch park is keyed to the branch's head:

    hold <run-id> <branch> <reason>
        Records `holds/<branch>.json` with the branch's current tip, for a
        `VERDICT: BLOCKED` or a branch question nobody answered. Exit 2: no such
        branch.

    unhold <branch> [<note>]
        A human clears a hold; the record, with the note, is kept as
        `holds/<branch>.json.cleared-<stamp>`. Exit 2: the branch is not held.

    eligible <default-branch> <agent> --held [<branch>...]   (`--held` anywhere after <agent>)
        As `eligible`, and a held branch whose tip is the held head prints
        `OUT <branch>: held at <sha>: <reason>`. A hold whose branch moved, was
        merged into <default-branch> or is gone is removed, with a `NOTE:` line.
        Only the unattended close passes `--held`: an attended close does not read
        holds.

Exit 3 everywhere: a usage error. Exit 1: git or the filesystem failed; the
message names what. A pending doc's frontmatter is read with PyYAML through
`pending_doc_hold.Doc`, the reader the close's other steps share.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import posixpath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote

import pending_doc_hold  # the shared pending-doc reader, and its PyYAML bootstrap

CONVENTION_FILES = (
    "CLAUDE.md",
    ".claude/convention_map.md",
    ".claude/convention_map.project.md",
    ".claude/security_map.md",
    ".claude/security_map.project.md",
)
STEP_2B_FILES = ("2b-conventions.md", "2b-security.md")
BOM = "\ufeff"


class Fail(Exception):
    """A git or filesystem failure: exit 1 with the message."""


class Refuse(Exception):
    """The run cannot be resumed: exit 2 with the message."""


def git(root: Path, *args: str, ok: tuple = (0,)) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except ValueError as e:  # an embedded NUL in an argument (a damaged manifest)
        raise Fail(f"git {' '.join(args)!r}: {e}") from e
    if p.returncode not in ok:
        err = os.fsdecode(p.stderr).strip()
        raise Fail(f"git {' '.join(args)} failed: {err}")
    return p.returncode, os.fsdecode(p.stdout)


def main_root() -> Path:
    p = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True)
    out = os.fsdecode(p.stdout).strip()
    if p.returncode != 0 or not out:
        raise Fail("not inside a git repository")
    common = Path(out)
    if not common.is_absolute():
        common = (Path.cwd() / common).resolve()
    return common.parent


def runs_dir(root: Path) -> Path:
    return root / "sysop" / "runtime" / "close"


def ref_sha(root: Path, ref: str) -> str:
    code, out = git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}", ok=(0, 1))
    return out.strip() if code == 0 else ""


def is_ancestor(root: Path, sha: str, ref: str) -> bool:
    if not sha or not ref_sha(root, ref):
        return False
    # 128: the recorded commit no longer exists (a deleted branch, then gc), so it
    # reached nothing.
    code, _ = git(root, "merge-base", "--is-ancestor", sha, ref, ok=(0, 1, 128))
    return code == 0


def without_smoke_answers(data: bytes) -> bytes:
    """A pending doc's bytes minus its frontmatter `smoke_answers:` block.

    The resume records Step 3c's answers into that block before `check` runs, and the recorder
    keeps every other line byte for byte, so the block is dropped by the recorder's own rule: the
    key line and the indented or `-` lines under it. Anything else that changes still counts.
    """
    bom = BOM.encode("utf-8")
    head = bom if data.startswith(bom) else b""
    data = data[len(head):]
    if not data.startswith(b"---"):
        return head + data
    end = data.find(b"\n---", 3)
    if end == -1:
        return head + data
    kept, skipping = [], False
    for line in data[:end].split(b"\n"):
        if re.match(rb"smoke_answers\s*:", line):
            skipping = True
            continue
        if skipping and line[:1] in (b" ", b"\t", b"-"):
            continue
        skipping = False
        kept.append(line)
    return head + b"\n".join(kept) + data[end:]


def digest(paths: list[Path], normalise=None) -> str:
    """One hash over each file's path and bytes, in path order; "" for none."""
    if not paths:
        return ""
    h = hashlib.sha256()
    for p in sorted(paths, key=str):
        try:
            data = p.read_bytes()
        except OSError as e:
            raise Fail(f"cannot read {p}: {e}") from e
        h.update(os.fsencode(str(p)) + b"\0" + (normalise(data) if normalise else data) + b"\0")
    return h.hexdigest()


def file_sha(p: Path) -> str:
    if not p.exists():
        return "absent"
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError as e:
        raise Fail(f"cannot read {p}: {e}") from e


def lock_branch(p: Path) -> str:
    """The first column-0 `branch:` line, as claim_task.sh reads it."""
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"cannot read lock {p}: {e}") from e
    for line in text.splitlines():
        if line.startswith("branch:"):
            return line[len("branch:"):].strip().strip("\"'")
    return ""


def doc_branch(p: Path) -> str:
    """The pending doc's `branch:`, read as Step 3c's `branch_of` reads it: PyYAML over the
    frontmatter, through `pending_doc_hold.Doc`, the reader the close's other steps share. A
    hand-rolled scan diverged from it on trailing spaces, duplicate keys, folded scalars and
    flow mappings, and a doc it misread was never hashed (round 2)."""
    doc = pending_doc_hold.Doc(p)
    if doc.error:
        raise Fail(f"pending doc {p}: {doc.error}")
    b = str(doc.fm.get("branch") or "").strip()
    return b[len("refs/heads/"):] if b.startswith("refs/heads/") else b


def worktrees(root: Path) -> dict[str, list[Path]]:
    """branch name -> its linked worktree paths, from `git worktree list --porcelain`."""
    _, out = git(root, "worktree", "list", "--porcelain")
    found: dict[str, list[Path]] = {}
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch refs/heads/") and path is not None:
            found.setdefault(line[len("branch refs/heads/"):], []).append(path)
    return found


def lock_workspace(p: Path) -> str:
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"cannot read lock {p}: {e}") from e
    for line in text.splitlines():
        if line.startswith("workspace:"):
            return line[len("workspace:"):].strip().strip("\"'")
    return ""


def branch_inputs(root: Path, default: str, branch: str, wts: dict[str, list[Path]]) -> dict:
    locks = sorted((root / "sysop" / "runtime" / "locks").glob("*.lock"))
    mine = [p for p in locks if lock_branch(p) == branch]
    places = [root] + [w for w in wts.get(branch, []) if w.resolve() != root.resolve()]
    for p in mine:
        ws = lock_workspace(p)
        if ws and Path(ws).resolve() != root.resolve() and Path(ws) not in places:
            places.append(Path(ws))
    docs = []
    for place in places:
        for d in sorted((place / "sysop" / "runtime" / "pending-docs").glob("*.md")):
            if doc_branch(d) == branch:
                docs.append(d)
    tip = ref_sha(root, "refs/heads/" + branch)
    return {
        "tip": tip,
        "lock": digest(mine),
        "doc": digest(docs, without_smoke_answers),
        "merged_at_begin": [r for r in (default, "origin/" + default) if is_ancestor(root, tip, r)],
    }


def run_inputs(root: Path, default: str) -> dict:
    _, heads = git(root, "for-each-ref", "--format=%(refname) %(objectname)",
                   "refs/sysop/merged-pr-heads/")
    _, hooks = git(root, "config", "--get", "core.hooksPath", ok=(0, 1))
    return {
        "local": ref_sha(root, "refs/heads/" + default),
        "origin": ref_sha(root, "refs/remotes/origin/" + default),
        "pr_heads": hashlib.sha256(heads.encode("utf-8", "surrogateescape")).hexdigest(),
        "conventions": {f: file_sha(root / f) for f in CONVENTION_FILES},
        "hooks_path": hooks.strip(),
    }


def write_json(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".manifest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def state_path(run: Path, branch: str) -> Path:
    return run / "branches" / (quote(branch, safe="") + ".md")


def count_questions(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"cannot read {path}: {e}") from e
    return len(re.findall(r"^## Q\d+\b", text, re.M))


def open_run(root: Path, run_id: str, default: str = "") -> tuple[Path, dict]:
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}", run_id):
        raise Refuse(f"not a run id: {run_id!r}")
    run = runs_dir(root) / run_id
    try:
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refuse(f"no run {run_id} under {runs_dir(root)}") from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Refuse(f"run {run_id}: manifest.json does not parse ({e})") from e
    if not well_formed(manifest):
        raise Refuse(f"run {run_id}: manifest.json is not a run manifest")
    if default and manifest.get("default_branch") != default:
        raise Refuse(f"run {run_id} was prepared against {manifest.get('default_branch')!r}, "
                     f"and the default branch is now {default!r}: run a fresh close")
    return run, manifest


def well_formed(m) -> bool:
    """The shape `compare` reads, so a damaged manifest is refused, never a traceback."""
    try:
        run = m["run"]
        ok = (isinstance(m["default_branch"], str) and isinstance(run["conventions"], dict)
              and all(isinstance(run[k], str) for k in ("local", "origin", "pr_heads", "hooks_path")))
        for rec in m["branches"].values():
            ok = ok and all(isinstance(rec[k], str) for k in ("tip", "lock", "doc")) \
                and isinstance(rec["merged_at_begin"], list)
        return bool(ok) and "\\u0000" not in json.dumps(m)  # json.dumps escapes a NUL
    except (KeyError, TypeError, AttributeError):
        return False


def resumable(run: Path, manifest: dict) -> None:
    if not manifest.get("finished"):
        raise Refuse(f"run {run.name} never finished its prepare: run a fresh close")
    if (run / "halted.md").exists():
        raise Refuse(f"run {run.name} halted (see {run / 'halted.md'}): run a fresh close")
    if manifest.get("consumed") or (run / "consumed").exists():
        raise Refuse(f"run {run.name} was already resumed")


def compare(root: Path, manifest: dict, *, include_origin: bool = True) -> list[str]:
    default = manifest["default_branch"]
    now = run_inputs(root, default)
    was = manifest["run"]
    lines = []
    wts = worktrees(root)
    redo_all = now["pr_heads"] != was["pr_heads"]
    for b in sorted(manifest["branches"]):
        rec = manifest["branches"][b]
        tip = ref_sha(root, "refs/heads/" + b)
        # A tip already in either ref at `begin` was not merged since the prepare: step 0b saw
        # it landed, and Steps 4 and 6 finish it.
        reached = [] if rec["merged_at_begin"] else [
            r for r in (default, "origin/" + default) if is_ancestor(root, rec["tip"], r)]
        if tip == rec["tip"] and reached:
            lines.append(f"GONE {b}: merged in {reached[0]}")
            continue
        if not tip:
            lines.append(f"GONE {b}: merged in {reached[0]}" if reached else f"GONE {b}: deleted")
            continue
        cur = branch_inputs(root, default, b, wts)
        moved = [k for k in ("tip", "lock", "doc") if cur[k] != rec[k]]
        if moved:
            lines.append(f"RERUN {b}: {', '.join(moved)} moved")
    if redo_all:
        lines.append("RERUN ALL: recorded PR heads changed")
    for f in CONVENTION_FILES:
        if now["conventions"][f] != was["conventions"].get(f):
            lines.append(f"RERUN 2b: {f} changed")
    if now["local"] != was["local"]:
        lines.append(f"RERUN 3: {default} moved")
    if include_origin and now["origin"] != was["origin"]:
        lines.append(f"RERUN 3: origin/{default} moved")
    if now["hooks_path"] != was["hooks_path"]:
        lines.append(f"NOTE: core.hooksPath was {was['hooks_path'] or '(unset)'}, "
                     f"is {now['hooks_path'] or '(unset)'}")
    return lines


def cmd_begin(root: Path, default: str, branches: list[str], agent: str = "") -> int:
    if not default or default.startswith("<"):
        print("usage: close_run.py begin <default-branch> [--agent <name>] [<branch>...]", file=sys.stderr)
        return 3
    if not ref_sha(root, "refs/heads/" + default):
        raise Fail(f"default branch {default!r} does not resolve")
    if awaiting(root):
        raise Refuse(f"a hand-off is waiting for its second reader: {', '.join(awaiting(root))}")
    refuse_if_stopped(root)
    if agent and not AGENT.fullmatch(agent):
        raise Refuse(f"not an agent name: {agent!r}")
    for b in branches:
        if b.startswith("<") or not ref_sha(root, "refs/heads/" + b):
            raise Fail(f"branch {b!r} does not exist")
    wts = worktrees(root)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{secrets.token_hex(2)}"
    run = runs_dir(root) / run_id
    (run / "branches").mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "default_branch": default,
        "begun": stamp,
        "branches": {b: branch_inputs(root, default, b, wts) for b in sorted(set(branches))},
        "run": run_inputs(root, default),
    }
    if agent:
        manifest["agent"] = agent  # `--prepare --agent`: the night's unattended resume follows
    write_json(run / "manifest.json", manifest)
    print(f"RUN: {run_id}")
    print(f"DIR: {run}")
    for b in sorted(manifest["branches"]):
        print(f"STATE {b}: {state_path(run, b)}")
    return 0


def cmd_finish(root: Path, run_id: str) -> int:
    run, manifest = open_run(root, run_id)
    missing = [b for b in sorted(manifest["branches"])
               if not state_path(run, b).is_file() or state_path(run, b).stat().st_size == 0]
    for b in missing:
        print(f"MISSING STATE {b}: {state_path(run, b)}")
    if not (run / "questions.md").is_file():
        missing.append("questions.md")
        print(f"MISSING: {run / 'questions.md'} (write it, empty of questions if there are none)")
    if missing:
        return 1
    for line in compare(root, manifest, include_origin=False):
        print(f"MOVED DURING PREPARE: {line}")
    (run / "2b").mkdir(exist_ok=True)
    for name in STEP_2B_FILES:
        src = root / "sysop" / "runtime" / name
        if src.is_file():
            shutil.copy2(src, run / "2b" / name)
            print(f"COPIED: {name}")
    manifest["run"]["origin"] = ref_sha(root, "refs/remotes/origin/" + manifest["default_branch"])
    manifest["finished"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(run / "manifest.json", manifest)
    print(f"QUESTIONS: {count_questions(run / 'questions.md')}")
    agent = manifest.get("agent")
    tail = f" --request-review --agent {agent} --unattended" if isinstance(agent, str) and AGENT.fullmatch(agent) else ""
    print(f"RESUME: /review-close --resume {run_id}{tail}")
    return 0


def cmd_resumable(root: Path, agent: str = "") -> int:
    """The newest prepare's run, when a resume can load it: finished, not halted, not
    consumed, and with `--agent`, prepared by that agent. Prints its id alone, so a script can
    chain an unattended night's two sessions. Never an older run: when tonight's prepare halted,
    the run before it may be a human's prepare waiting for answers. Exit 2 otherwise."""
    if agent and not AGENT.fullmatch(agent):
        raise Refuse(f"not an agent name: {agent!r}")
    d = runs_dir(root)
    runs = sorted((r for r in (d.iterdir() if d.is_dir() else [])
                   if RUN_ID.fullmatch(r.name) and (r / "manifest.json").exists()), reverse=True)
    if not runs:
        raise Refuse("no prepared run")
    run, manifest = open_run(root, runs[0].name)
    resumable(run, manifest)
    if agent and manifest.get("agent") != agent:
        raise Refuse(f"run {run.name} was not prepared with --agent {agent}")
    print(run.name)
    return 0


def cmd_awaiting(root: Path, agent: str | None = None) -> int:
    """The one hand-off a land can take, by the checks the unattended `land-check` makes
    before it reads GitHub: no STOPPED marker, a sealed record still awaiting its merge, not
    PARKED, and with `--agent`, that agent's. A park whose disarm failed is printed: its land
    turns auto-merge off. Prints its id alone, so a script can chain the night's land. `agent`
    is None without `--agent`; an empty name is refused, not read as none."""
    if agent is not None and not AGENT.fullmatch(agent):
        raise Refuse(f"not an agent name: {agent!r}")
    refuse_if_stopped(root)
    ids = awaiting(root)
    if not ids:
        raise Refuse("no hand-off is waiting")
    if len(ids) > 1:
        raise Refuse(f"{len(ids)} hand-offs are waiting ({', '.join(ids)}); a hand-off refuses "
                     "while another waits, so a human made this state: land each by its id")
    run, rec = open_handoff(root, ids[0])
    if rec["status"] not in ("awaiting", "request-failed", "requesting"):
        raise Refuse(f"hand-off {run.name} is {rec['status']}: nothing to land")
    if not rec.get("sealed"):
        raise Refuse(f"hand-off {run.name} is unsealed: write its report.md and run "
                     f"`close_run.py seal {run.name}`")
    parked = read_parked(run)
    if parked and not rec.get("armed"):
        raise Refuse(f"hand-off {run.name} is parked ({parked.get('code')}) and waits for a "
                     f"human: read sysop/runtime/close/{run.name}/PARKED")
    owner = (rec.get("unattended") or {}).get("agent") if isinstance(rec.get("unattended"), dict) else None
    if agent is not None and owner != agent:
        raise Refuse(f"hand-off {run.name} was handed off by {'agent ' + repr(owner) if owner else 'no agent'}, "
                     f"not {agent!r}")
    print(run.name)
    return 0


def cmd_load(root: Path, run_id: str, default: str) -> int:
    run, manifest = open_run(root, run_id, default)
    resumable(run, manifest)
    if awaiting(root):
        raise Refuse(f"a hand-off is waiting for its second reader: {', '.join(awaiting(root))}")
    refuse_if_stopped(root)
    print(f"DIR: {run}")
    print(f"QUESTIONS: {count_questions(run / 'questions.md')}")
    print(f"ANSWERED: {count_questions(run / 'answers.md')}")
    return 0


def cmd_check(root: Path, run_id: str, default: str) -> int:
    run, manifest = open_run(root, run_id, default)
    resumable(run, manifest)
    lines = compare(root, manifest)
    for line in lines:
        print(line)
    if not [l for l in lines if not l.startswith("NOTE:")]:
        print("CURRENT")
    return 0


def cmd_consume(root: Path, run_id: str, restore: bool) -> int:
    run, manifest = open_run(root, run_id)
    resumable(run, manifest)
    try:  # O_EXCL: of two concurrent consumes, exactly one succeeds
        os.close(os.open(run / "consumed", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise Refuse(f"run {run.name} was already resumed") from None
    if restore:
        for name in STEP_2B_FILES:
            src = run / "2b" / name
            if src.is_file():
                dest = root / "sysop" / "runtime" / name
                shutil.copy2(src, dest)
                print(f"RESTORED: {dest}")
    manifest["consumed"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(run / "manifest.json", manifest)
    print(f"CONSUMED: {run_id}")
    return 0


# ---------------------------------------------------------------------------------------------
# The Step 4d split (`Q-411`, Phase 365): `--request-review` (half A) and `--land` (half B).
#
# Half A opens the PR, asks the consumer's `## Second reader` for a review, records what half B
# needs, and stops. Half B reads the reviewer's verdict on the recorded head and merges or parks.
# The hand-off lives in its own run directory, `handoff.json` plus the runner's `report.md`, with
# an `AWAITING` marker every other close stops on until the hand-off lands or is abandoned.
# ---------------------------------------------------------------------------------------------

READER_KEYS = ("reviewer", "format", "request", "timeout", "blocking")
READER_FORMATS = ("codex", "approval")
DEFAULT_TIMEOUT = "20m"  # GDP's OPS-CODEX-PR-REVIEW-MANUAL-MODE, "to be set from measurement"
REPORT_LABELS = ("Merged:", "Held-doc branches:", "SKIP:", "4a-SKIP:", "Kept locks:")
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA = re.compile(r"[0-9a-f]{40}")
BADGE = re.compile(r"!\[(P\d+) Badge\]")
SUMMARY_MARK = "<!-- codex-pull-request-review-summary -->"
USAGE_LIMIT = "reached your Codex usage limits"


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def parse_time(value) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def timeout_seconds(value: str) -> int | None:
    m = re.fullmatch(r"([1-9][0-9]{0,4})([mh])", value)
    if not m:
        return None
    return int(m.group(1)) * (60 if m.group(2) == "m" else 3600)


def section_pairs(root: Path, title: str, keys: tuple, repeatable: tuple = (),
                  rev: str = "") -> list[tuple[str, str]]:
    """`## <title>` in the project's CLAUDE.md (the working tree's, or <rev>'s), as (key, value)
    pairs from `key: value` lines. A heading inside a fenced block is not the section; any line
    that is not a known key refuses; a key outside `repeatable` may appear once."""
    path = f"{rev}:CLAUDE.md" if rev else root / "CLAUDE.md"
    if rev:
        name = "CLAUDE.md"
        for _ in range(5):  # a symlinked CLAUDE.md (-> AGENTS.md) is followed inside the commit
            _, entry = git(root, "ls-tree", "-z", rev, "--", name)
            if not entry.startswith("120000 "):
                break
            _, target = git(root, "cat-file", "-p", f"{rev}:{name}")
            name = posixpath.normpath(posixpath.join(posixpath.dirname(name), target.strip()))
            if name.startswith(("../", "/")) or name == "..":
                raise Refuse(f"{rev}:CLAUDE.md is a symlink out of the repository ({target.strip()})")
        path = f"{rev}:{name}"
        code, text = git(root, "cat-file", "-p", f"{rev}:{name}", ok=(0, 128))
        if code:
            raise Refuse(f"{path} does not exist, so there is no `## {title}` section")
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise Refuse(f"{path} does not exist, so there is no `## {title}` section") from None
        except (OSError, UnicodeDecodeError) as e:
            raise Refuse(f"cannot read {path}: {e}") from e
    heading = re.compile(r"[ ]{0,3}##\s+" + re.escape(title) + r"\s*#*\s*")
    lines, found, inside, fence = [], False, False, None
    for line in text.lstrip(BOM).splitlines():
        m = re.match(r"[ ]{0,3}(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not line.strip()[len(m.group(1)):].strip():
                fence = None
            if inside:
                lines.append(line)
            continue
        if fence is None and re.match(r"[ ]{0,3}#{1,2}\s", line):
            inside = bool(heading.fullmatch(line))
            if inside and found:
                raise Refuse(f"{path} has two `## {title}` sections")
            found = found or inside
            continue
        if inside:
            lines.append(line)
    if not found:
        raise Refuse(f"{path} has no `## {title}` section")
    pairs: list[tuple[str, str]] = []
    for line in lines:
        s = line.strip()
        if not s or (s.startswith("<!--") and s.endswith("-->")):
            continue
        m = re.fullmatch(r"([a-z_]+)\s*:\s*(.*?)\s*", s)
        if not m or m.group(1) not in keys:
            raise Refuse(f"`## {title}`: not a `key: value` line with a known key "
                         f"({', '.join(keys)}): {s!r}")
        if m.group(1) not in repeatable and any(k == m.group(1) for k, _ in pairs):
            raise Refuse(f"`## {title}`: {m.group(1)} is given twice")
        pairs.append((m.group(1), m.group(2)))
    return pairs


def read_second_reader(root: Path, rev: str = "") -> dict:
    """`## Second reader` in the project's CLAUDE.md (the working tree's, or <rev>'s), as
    `key: value` lines."""
    cfg: dict[str, str] = dict(section_pairs(root, "Second reader", READER_KEYS, rev=rev))
    for key in ("reviewer", "format", "request"):
        if not cfg.get(key):
            raise Refuse(f"`## Second reader`: {key} is required")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?", cfg["reviewer"]):
        raise Refuse(f"`## Second reader`: reviewer is not a GitHub login: {cfg['reviewer']!r}")
    if cfg["format"] not in READER_FORMATS:
        raise Refuse(f"`## Second reader`: format must be one of {', '.join(READER_FORMATS)}")
    cfg.setdefault("timeout", DEFAULT_TIMEOUT)
    if timeout_seconds(cfg["timeout"]) is None:
        raise Refuse(f"`## Second reader`: timeout must look like 20m or 2h: {cfg['timeout']!r}")
    if cfg["format"] == "codex":
        cfg.setdefault("blocking", "P0 P1")
        sev = cfg["blocking"].replace(",", " ").split()
        if not sev or not all(re.fullmatch(r"P\d+", s) for s in sev):
            raise Refuse(f"`## Second reader`: blocking must list severities like P0 P1")
        cfg["blocking"] = " ".join(sev)
    elif "blocking" in cfg:
        raise Refuse("`## Second reader`: blocking applies to format codex only")
    return cfg


def gh(root: Path, *args: str) -> str:
    try:
        p = subprocess.run(["gh", *args], cwd=str(root), capture_output=True)
    except FileNotFoundError:
        raise Fail("gh is not installed") from None
    if p.returncode != 0:
        err = os.fsdecode(p.stderr).strip().splitlines()
        raise Fail(f"gh {' '.join(args[:3])} failed: {err[0] if err else 'exit ' + str(p.returncode)}")
    return os.fsdecode(p.stdout)


def gh_json(root: Path, *args: str):
    out = gh(root, *args)
    try:
        return json.loads(out)
    except ValueError as e:
        raise Fail(f"gh {' '.join(args[:3])} did not print JSON: {e}") from e


def gh_list(root: Path, path: str) -> list:
    """Every page of a REST list. `--paginate` prints one JSON array per page, back to back."""
    out, items, dec, i = gh(root, "api", "--paginate", path), [], json.JSONDecoder(), 0
    while True:
        while i < len(out) and out[i].isspace():
            i += 1
        if i >= len(out):
            return items
        try:
            page, i = dec.raw_decode(out, i)
        except ValueError as e:
            raise Fail(f"gh api {path} did not print JSON: {e}") from e
        if not isinstance(page, list):
            raise Fail(f"gh api {path} did not print a list")
        items.extend(page)


PR_FIELDS = "number,url,state,isDraft,isCrossRepository,headRefName,headRefOid,baseRefName,baseRefOid"


def pr_view(root: Path, pr: str) -> dict:
    data = gh_json(root, "pr", "view", pr, "--json", PR_FIELDS)
    if not isinstance(data, dict):
        raise Fail(f"gh pr view {pr} did not print an object")
    return data


def awaiting(root: Path) -> list[str]:
    d = runs_dir(root)
    return sorted(p.parent.name for p in d.glob("*/AWAITING")) if d.is_dir() else []


def stopped(root: Path) -> list[str]:
    """Run ids whose unattended close stopped durably (`Q-664`): a human clears each."""
    d = runs_dir(root)
    return sorted(p.parent.name for p in d.glob("*/STOPPED")) if d.is_dir() else []


def refuse_if_stopped(root: Path) -> None:
    ids = stopped(root)
    if ids:
        raise Refuse(f"an unattended close stopped and waits for a human: {', '.join(ids)}; "
                     f"read sysop/runtime/close/{ids[0]}/STOPPED, recover as it says, then run "
                     f"`close_run.py clear {ids[0]}`")


def open_handoff(root: Path, run_id: str, default: str = "") -> tuple[Path, dict]:
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}", run_id):
        raise Refuse(f"not a run id: {run_id!r}")
    run = runs_dir(root) / run_id
    try:
        rec = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refuse(f"no hand-off {run_id} under {runs_dir(root)}") from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Refuse(f"hand-off {run_id}: handoff.json does not parse ({e})") from e
    keys = ("default_branch", "branch", "pr", "url", "head", "pushed_from", "origin_at_push",
            "reviewer", "format", "request", "timeout", "status", "requested_at")
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), str) for k in keys) \
            or not isinstance(rec.get("keep_branch"), bool) \
            or not isinstance(rec.get("kept_locks"), list) \
            or not all(isinstance(t, str) and TASK_ID.fullmatch(t) for t in rec["kept_locks"]):
        raise Refuse(f"hand-off {run_id}: handoff.json is not a hand-off record")
    if rec["format"] not in READER_FORMATS or (rec["format"] == "codex" and not str(rec.get("blocking", "")).split()):
        raise Refuse(f"hand-off {run_id}: handoff.json names no usable reader format or blocking list")
    if default and rec["default_branch"] != default:
        raise Refuse(f"hand-off {run_id} targets {rec['default_branch']!r}, and the default "
                     f"branch is now {default!r}")
    return run, rec


def write_marker(run: Path) -> None:
    (run / "AWAITING").write_text(
        "A /review-close hand-off is waiting for its second reader. Land it with\n"
        f"`/review-close --land {run.name}` (it also finishes a PR merged by hand; if its\n"
        f"request failed, run `python3 sysop/scripts/close_run.py re-request \"{run.name}\" <default branch>`\n"
        f"first), or, once the PR is closed unmerged, give it up with\n"
        f"`python3 sysop/scripts/close_run.py abandon \"{run.name}\"`.\n", encoding="utf-8")


def post_request(root: Path, pr: str, body: str) -> tuple[str, str]:
    # `-f`, never `-F`: `-F body=@codex review` would read a file named "codex review".
    data = gh_json(root, "api", f"repos/{{owner}}/{{repo}}/issues/{pr}/comments",
                   "-f", f"body={body}")
    cid, at = str(data.get("id", "")) if isinstance(data, dict) else "", \
        data.get("created_at", "") if isinstance(data, dict) else ""
    if not cid or not parse_time(at):
        raise Fail("the request comment was posted but GitHub returned no id or created_at")
    return cid, at


def check_pr_for_request(root: Path, pr: str, default: str, branch: str, head: str) -> dict:
    data = pr_view(root, pr)
    problems = []
    if data.get("state") != "OPEN":
        problems.append(f"state is {data.get('state')}")
    if data.get("isDraft"):
        problems.append("it is a draft")
    if data.get("isCrossRepository"):
        problems.append("its head is in another repository")
    if data.get("baseRefName") != default:
        problems.append(f"its base is {data.get('baseRefName')!r}, not {default!r}")
    if data.get("headRefName") != branch:
        problems.append(f"its head branch is {data.get('headRefName')!r}, not {branch!r}")
    if data.get("headRefOid") != head:
        problems.append(f"its head is {data.get('headRefOid')}, and local {branch} is {head}")
    if problems:
        raise Refuse(f"PR {pr}: " + "; ".join(problems))
    return data


def cmd_reader(root: Path) -> int:
    if awaiting(root):
        raise Refuse(f"a hand-off is waiting for its second reader: {', '.join(awaiting(root))}")
    refuse_if_stopped(root)
    cfg = read_second_reader(root)
    for k in READER_KEYS:
        if k in cfg:
            print(f"{k.upper()}: {cfg[k]}")
    return 0


def cmd_hand_off(root: Path, default: str, branch: str, pr: str, pushed_from: str,
                 keep_branch: bool, agent: str = "") -> int:
    if agent and not AGENT.fullmatch(agent):
        raise Refuse(f"not an agent name: {agent!r}")
    if not re.fullmatch(r"[1-9][0-9]*", pr):
        raise Refuse(f"not a PR number: {pr!r}")
    if not SHA.fullmatch(pushed_from):
        raise Refuse(f"not a full commit SHA: {pushed_from!r} (use what Step 4d's 2b printed)")
    runs_dir(root).mkdir(parents=True, exist_ok=True)
    guard = runs_dir(root) / ".hand-off.lock"
    try:  # O_EXCL: of two concurrent hand-offs, exactly one records
        os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise Refuse(f"another hand-off is being recorded ({guard}; remove it if no close is running)") from None
    try:
        return _hand_off(root, default, branch, pr, pushed_from, keep_branch, agent)
    finally:
        guard.unlink(missing_ok=True)


def _hand_off(root: Path, default: str, branch: str, pr: str, pushed_from: str,
              keep_branch: bool, agent: str = "") -> int:
    pending = awaiting(root)
    if pending:
        raise Refuse(f"another hand-off is waiting: {', '.join(pending)}")
    refuse_if_stopped(root)
    cfg = read_second_reader(root)
    if agent:
        read_class(root)  # an unattended hand-off needs a class to land against
    head = ref_sha(root, "refs/heads/" + branch)
    if not head:
        raise Refuse(f"branch {branch!r} does not exist")
    local = ref_sha(root, "refs/heads/" + default)
    if not local:
        raise Fail(f"default branch {default!r} does not resolve")
    _, base = git(root, "merge-base", "refs/heads/" + default, head, ok=(0, 1))
    if pushed_from != base.strip():
        raise Refuse(f"{pushed_from} is not local {default}'s commit at the push "
                     f"({base.strip() or 'no common ancestor'}): use what Step 4d's line 2b printed")
    data = check_pr_for_request(root, pr, default, branch, head)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{secrets.token_hex(2)}"
    run = runs_dir(root) / run_id
    run.mkdir(parents=True)
    rec = {
        "run_id": run_id, "default_branch": default, "branch": branch, "pr": pr,
        "url": str(data.get("url", "")), "head": head, "pushed_from": pushed_from,
        "origin_at_push": ref_sha(root, "refs/remotes/origin/" + default),
        "keep_branch": keep_branch, "kept_locks": [], "status": "requesting",
        "reviewer": cfg["reviewer"], "format": cfg["format"], "request": cfg["request"],
        "timeout": cfg["timeout"], "blocking": cfg.get("blocking", ""),
        "requested_at": "", "request_comment": "", "opened": stamp,
    }
    if agent:
        rec["unattended"] = {"agent": agent}
    write_json(run / "handoff.json", rec)
    write_marker(run)
    print(f"RUN: {run_id}")
    print(f"DIR: {run}")
    try:
        cid, at = post_request(root, pr, cfg["request"])
    except Fail as e:
        rec["status"] = "request-failed"
        write_json(run / "handoff.json", rec)
        raise Fail(f"{e}. The hand-off is recorded as request-failed; run "
                   f"`close_run.py re-request {run_id} {default}` once gh works") from e
    rec.update(status="awaiting", requested_at=at, request_comment=cid)
    write_json(run / "handoff.json", rec)
    print(f"REQUESTED: {cfg['request']!r} from {cfg['reviewer']} at {at}")
    print(f"REPORT: {run / 'report.md'} (write it, then run seal)")
    return 0


def report_kept_locks(text: str) -> list[str] | None:
    for line in text.splitlines():
        if line.startswith("Kept locks:"):
            v = line[len("Kept locks:"):].strip()
            if v in ("", "(none)"):
                return []
            ids = v.replace(",", " ").split()
            return ids if all(TASK_ID.fullmatch(t) for t in ids) else None
    return None


def cmd_seal(root: Path, run_id: str) -> int:
    run, rec = open_handoff(root, run_id)
    if rec["status"] not in ("awaiting", "request-failed", "requesting"):
        raise Refuse(f"hand-off {run_id} is {rec['status']}")
    try:
        text = (run / "report.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"MISSING: {run / 'report.md'}")
        return 1
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"cannot read {run / 'report.md'}: {e}") from e
    missing = [h for h in ("## Step 6", "## Step 8") if not re.search(rf"^{h}\s*$", text, re.M)]
    missing += [l for l in REPORT_LABELS if not re.search(rf"^{re.escape(l)}", text, re.M)]
    for m in missing:
        print(f"MISSING IN report.md: {m}")
    if missing:
        return 1
    kept = report_kept_locks(text)
    if kept is None:
        print("MISSING IN report.md: `Kept locks:` must be task ids or (none)")
        return 1
    gone = [t for t in kept if not (root / "sysop" / "runtime" / "locks" / f"{t}.lock").is_file()]
    if gone:
        print(f"NOT KEPT: no lock file for {' '.join(gone)} (was Step 4c's close_index.py run with --keep-locks?)")
        return 1
    rec["kept_locks"], rec["sealed"] = kept, utcnow().strftime("%Y%m%dT%H%M%SZ")
    write_json(run / "handoff.json", rec)
    print(f"SEALED: {run_id}")
    print(f"LAND: /review-close --land {run_id}")
    return 0


def _codex_summary_rows(body: str) -> list[tuple[str, str]]:
    """(status, short sha) for each table row of a Codex review-summary comment."""
    rows = []
    for line in body.splitlines():
        m = re.match(r"\s*\|[^|]*\|\s*(.*?)\s*\|\s*`([0-9a-f]{7,40})`\s*\|", line)
        if m:
            status = "running" if "Running" in m.group(1) else \
                "completed" if "Completed" in m.group(1) else "other"
            rows.append((status, m.group(2)))
    return rows


def reader_verdict(rec: dict, reviews: list, review_comments: list, comments: list,
                   reactions: list, now: datetime.datetime) -> tuple[str, list[str]]:
    """("merge" | "wait" | "park", detail lines) for the recorded head. Pure: tests drive it."""
    who, head = rec["reviewer"], rec["head"]
    asked = parse_time(rec["requested_at"])
    if asked is None:
        return "park", ["the record has no request time"]
    deadline = asked + datetime.timedelta(seconds=timeout_seconds(rec["timeout"]) or 0)

    def mine(item, key="user"):
        return isinstance(item, dict) and isinstance(item.get(key), dict) \
            and item[key].get("login") == who

    def after(item, key):
        t = parse_time(item.get(key))
        return t is not None and t > asked

    on_head = [r for r in reviews if mine(r) and r.get("commit_id") == head]
    stray = [r for r in reviews if mine(r) and r.get("commit_id") != head and after(r, "submitted_at")]

    def waiting(why: str) -> tuple[str, list[str]]:
        if now > deadline:
            return "park", [f"timed out: {why}; requested {rec['requested_at']}, "
                            f"timeout {rec['timeout']}"] + stray_note
        return "wait", [f"{why}; times out at {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')}"] + stray_note

    stray_note = [f"{who} reviewed {(r.get('commit_id') or '?')[:10]} after the request, not the "
                  f"recorded head {head[:10]}" for r in stray]

    marked = [c for c in comments if mine(c) and SUMMARY_MARK in str(c.get("body", ""))]
    newest = max(marked, key=lambda c: str(c.get("updated_at") or c.get("created_at") or ""),
                 default=None)
    summaries = [str(newest.get("body", ""))] if newest else []
    rows = _codex_summary_rows(summaries[0]) if summaries else []
    if rec["format"] == "codex" and summaries and not rows:
        return "park", [f"cannot read {who}'s review summary: no row names a status and a commit"]
    if rec["format"] == "codex" and any(st == "running" for st, _ in rows):
        return waiting("a Codex review is running")

    if rec["format"] == "approval":
        if not on_head:
            return waiting(f"no review by {who} on {head[:10]}")
        last = max(on_head, key=lambda r: parse_time(r.get("submitted_at")) or asked)
        state = last.get("state")
        if state == "APPROVED":
            return "merge", [f"{who} approved {head[:10]}"]
        if state == "CHANGES_REQUESTED":
            return "park", [f"{who} requested changes on {head[:10]}"]
        return waiting(f"{who}'s latest review on {head[:10]} is {state}, not APPROVED")

    blocking = set(rec.get("blocking", "").split())
    if on_head:
        ids = {r.get("id") for r in on_head}
        found = [c for c in review_comments if mine(c) and c.get("pull_request_review_id") in ids]
        if not found:
            return "park", [f"{who} reviewed {head[:10]} but left no inline finding to read"]
        block, note, unread = [], [], []
        for c in found:
            body = str(c.get("body", ""))
            m = BADGE.search(body[:300])
            title = re.sub(r"</?sub>|!\[[^\]]*\]\([^)]*\)|[*<>]", "", body.splitlines()[0] if body else "").strip()
            where = f"{c.get('path', '?')}:{c.get('line') or c.get('original_line') or '?'}"
            if not m:
                unread.append(f"no severity badge at {where}")
            elif m.group(1) in blocking:
                block.append(f"{m.group(1)} {where} — {title}")
            else:
                note.append(f"{m.group(1)} {where} — {title}")
        if unread:
            return "park", ["cannot read a finding: " + u for u in unread] + block + note
        if block or any(r.get("state") == "CHANGES_REQUESTED" for r in on_head):
            return "park", block + [f"(non-blocking) {n}" for n in note]
        return "merge", [f"(non-blocking) {n}" for n in note] or [f"{who} reviewed {head[:10]}"]

    if any(mine(c) and USAGE_LIMIT in str(c.get("body", "")) and after(c, "created_at")
           for c in comments):
        return "park", [f"{who} reported its usage limit after the request"]
    if rows and not all(s == "completed" and head.startswith(sha) for s, sha in rows):
        return waiting(f"Codex's summary does not show a completed review of {head[:10]}")
    if rows:  # every row completed on this head, and no review of it: no finding
        return "merge", [f"{who}'s summary shows a completed review of {head[:10]} with no finding"]
    # A `+1` names no commit, so it is never a verdict on this head (round 1, record lens: under
    # the PR-reuse shape a review of an earlier head can finish after the request).
    if any(mine(r) and r.get("content") == "+1" and after(r, "created_at") for r in reactions):
        return waiting(f"{who} reacted +1, but a reaction names no commit and no summary "
                       f"comment shows a completed review of {head[:10]}")
    return waiting(f"no verdict from {who} on {head[:10]} yet")


def cmd_land_check(root: Path, run_id: str, default: str) -> int:
    run, rec = open_handoff(root, run_id, default)
    if rec["status"] not in ("awaiting", "request-failed", "requesting"):
        raise Refuse(f"hand-off {run_id} is {rec['status']}: nothing to land")
    if not rec.get("sealed"):
        raise Refuse(f"hand-off {run_id} is unsealed: write its report.md and run "
                     f"`close_run.py seal {run_id}`")
    print(f"PR: {rec['pr']} {rec['url']}")
    print(f"BRANCH: {rec['branch']}")
    print(f"SHAPE: {'integration branch' if rec['branch'].startswith('merge/review-close-') else 'PR reuse'}")
    print(f"HEAD: {rec['head']}")
    print(f"PUSHED FROM: {rec['pushed_from']}")
    print(f"KEEP BRANCH: {'yes' if rec['keep_branch'] else 'no'}")
    print(f"REPORT: {run / 'report.md'}")
    parked = read_parked(run)
    if parked:
        print(f"PARKED: {parked.get('code')} at {parked.get('at')}; this attended land reads the "
              "PR afresh, and a merge clears it")
    data = pr_view(root, rec["pr"])
    state = data.get("state")
    if state != "MERGED" and rec["status"] != "awaiting":
        raise Refuse(f"hand-off {run_id} is {rec['status']}: no review was requested; run "
                     f"`close_run.py re-request {run_id} {default}` first")
    if state == "MERGED":
        if data.get("headRefOid") != rec["head"]:
            print(f"READER: merged at {data.get('headRefOid')}, not the recorded head {rec['head']}: "
                  "merged outside this gate, by someone, unread by the second reader")
        print("VERDICT: ALREADY MERGED")
        return 0
    problems = []
    if state != "OPEN":
        problems.append(f"the PR is {state}, not open")
    if data.get("isDraft"):
        problems.append("the PR is a draft")
    if data.get("isCrossRepository"):
        problems.append("the PR's head is in another repository")
    if data.get("baseRefName") != rec["default_branch"]:
        problems.append(f"the PR's base is {data.get('baseRefName')!r}, not {rec['default_branch']!r}")
    if data.get("headRefOid") != rec["head"]:
        problems.append(f"the PR's head is {data.get('headRefOid')}, not the recorded {rec['head']}")
    if problems:
        for p in problems:
            print(f"READER: {p}")
        print("VERDICT: PARK")
        return 4
    verdict, lines = reader_verdict(
        rec,
        gh_list(root, f"repos/{{owner}}/{{repo}}/pulls/{rec['pr']}/reviews"),
        gh_list(root, f"repos/{{owner}}/{{repo}}/pulls/{rec['pr']}/comments"),
        gh_list(root, f"repos/{{owner}}/{{repo}}/issues/{rec['pr']}/comments"),
        gh_list(root, f"repos/{{owner}}/{{repo}}/issues/{rec['pr']}/reactions"),
        utcnow())
    for line in lines:
        print(f"READER: {line}")
    print(f"VERDICT: {verdict.upper()}")
    return {"merge": 0, "park": 4, "wait": 5}[verdict]


def cmd_re_request(root: Path, run_id: str, default: str) -> int:
    run, rec = open_handoff(root, run_id, default)
    if rec["status"] not in ("awaiting", "request-failed", "requesting"):
        raise Refuse(f"hand-off {run_id} is {rec['status']}")
    head = ref_sha(root, "refs/heads/" + rec["branch"])
    if not head:
        raise Refuse(f"branch {rec['branch']!r} no longer exists locally")
    check_pr_for_request(root, rec["pr"], default, rec["branch"], head)
    cid, at = post_request(root, rec["pr"], rec["request"])
    old = rec["head"]
    rec.update(head=head, status="awaiting", requested_at=at, request_comment=cid)
    rec.pop("checks_waiting_since", None)
    # An arm survives a push and merges the new head (Phase 375's P4), so a new request drops
    # it: the next unattended land re-checks this head before arming again.
    note = disarm(root, rec) if rec.get("armed") else ""
    write_json(run / "handoff.json", rec)
    if note:
        print(f"READER: {note}")
    if (run / "PARKED").exists():
        (run / "PARKED").unlink()
        print("UNPARKED: the request is new, so the park it answered is cleared")
    print(f"HEAD: {old} -> {head}" if old != head else f"HEAD: {head}")
    print(f"REQUESTED: {rec['request']!r} from {rec['reviewer']} at {at}")
    return 0


def _finish_handoff(root: Path, run: Path, rec: dict, status: str) -> None:
    rec["status"], rec[status] = status, utcnow().strftime("%Y%m%dT%H%M%SZ")
    write_json(run / "handoff.json", rec)
    for name in ("AWAITING", "PARKED"):
        try:
            (run / name).unlink()
        except FileNotFoundError:
            pass


def cmd_landed(root: Path, run_id: str) -> int:
    run, rec = open_handoff(root, run_id)
    if rec["status"] not in ("awaiting", "request-failed", "requesting") or not rec.get("sealed"):
        raise Refuse(f"hand-off {run_id} is {rec['status']}"
                     f"{'' if rec.get('sealed') else ', unsealed'}: nothing to land")
    data = pr_view(root, rec["pr"])
    if data.get("state") != "MERGED":
        raise Refuse(f"PR {rec['pr']} is {data.get('state')}, not MERGED: nothing landed")
    if data.get("headRefOid") != rec["head"]:
        print(f"MERGED ELSEWHERE: at {data.get('headRefOid')}, not the recorded head {rec['head']}")
    locks = root / "sysop" / "runtime" / "locks"
    removed, absent = [], []
    for tid in rec["kept_locks"]:
        p = locks / f"{tid}.lock"
        (removed if (p.exists() or p.is_symlink()) else absent).append(tid)
        p.unlink(missing_ok=True)
    _finish_handoff(root, run, rec, "landed")
    print(f"LOCKS_REMOVED: {' '.join(removed) or '(none)'}")
    print(f"LOCKS_ALREADY_ABSENT: {' '.join(absent) or '(none)'}")
    print(f"LANDED: {run_id}")
    return 0


def cmd_abandon(root: Path, run_id: str) -> int:
    run, rec = open_handoff(root, run_id)
    if rec["status"] in ("landed", "abandoned"):
        raise Refuse(f"hand-off {run_id} is already {rec['status']}")
    state = pr_view(root, rec["pr"]).get("state")
    if state == "MERGED":
        raise Refuse(f"PR {rec['pr']} is merged: run `/review-close --land {run_id}`, which finishes it")
    if state != "CLOSED":
        raise Refuse(f"PR {rec['pr']} is {state}: close it first, or land it")
    _finish_handoff(root, run, rec, "abandoned")
    print(f"ABANDONED: {run_id} (PR {rec['pr']} was closed unmerged)")
    print(f"BRANCH: {rec['branch']} (holds Step 4c's consolidation; nothing reached {rec['default_branch']})")
    print(f"LOCKS_KEPT: {' '.join(rec['kept_locks']) or '(none)'}")
    return 0


# ---------------------------------------------------------------------------------------------
# The unattended land (`Q-411`, Phases 366 and 375). A hand-off made with `--agent <name>` may be
# landed by `land-check --unattended <name>`, with no human: only when the server setup holds
# (`setup_problems`), every registered check has passed, the gate's among them, and GitHub's own
# rules then let auto-merge through. Anything else parks durably (`PARKED`), and a parked
# hand-off waits for a human: `re-request`, `unpark` or an attended `--land`.
# ---------------------------------------------------------------------------------------------

CLASS_TITLE = "Unattended close class"
CLASS_KEYS = ("allow", "exclude", "blast_radius", "code_owner", "gate_app", "attested")
BLAST_ORDER = ("single-file", "single-module", "cross-module", "architectural")
# The governing set: files an agent, a reviewer or git itself reads as instructions, so an
# unattended merge may never change one (spec § 10.3 item 2, Phase 367's round 2). Defined by
# name, not by a path list: a basename anywhere, a directory component anywhere, or a root
# path. Never configurable; a consumer's `exclude:` extends it (Wade, 2026-10-08).
GOVERNING_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md",
                   ".mcp.json", ".gitmodules", ".gitattributes")
GOVERNING_DIRS = (".claude", ".agents", ".codex")
GOVERNING_ROOTS = ("sysop", ".github")
GOVERNING_FILES = ("CODEOWNERS", "docs/CODEOWNERS")
FIXED_EXCLUDE = (GOVERNING_NAMES + tuple(f"{d}/" for d in GOVERNING_DIRS)
                 + tuple(f"/{r}/**" for r in GOVERNING_ROOTS) + tuple(f"/{f}" for f in GOVERNING_FILES))
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")  # a user login, not a team
GIT_FLOOR = (2, 40)  # `--attr-source` (2.40); `merge-tree --write-tree` is 2.38
# Paths a close commits itself (Steps 1b, 4b and 4c). The class must allow them, or every
# land parks; `class` and `eligible` warn about each one it does not.
CLOSE_WRITTEN = ("tasks/index.yml", "tasks/open/TASK-0001.md", "tasks/archive/TASK-0001.md",
                 "PROJECT_STATUS.md", "CHANGELOG.md", "UI_Iterations.md", "review_tasks.md",
                 "review_tasks_archive.md")
PARK_CODES = ("ask", "relay", "hard-fail", "gate-red", "conflict", "class", "reader", "checks",
              "pr-state", "dirty", "after-push", "setup")
AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}")  # claim_task.sh's AGENT_NAME rule
# The unattended land, enabled by `Q-411`'s part B (Phase 375). Phase 366 built a client gate and
# left it off, because each of three rounds found a way for a PR or the agent to shape what it
# trusted. The redesign moved the trust to GitHub (spec § 10): `close_gate.py`, a signed check,
# decides paths, task fields and the reader; this land verifies the server setup that makes the
# check binding, then lets GitHub merge. Setting this False refuses every unattended land again.
UNATTENDED_LAND_ENABLED = True


def glob_regex(pat: str, icase: bool = False, cover: bool = False) -> re.Pattern:
    """A repo-root-anchored path glob: `*` and `?` stay inside one segment, a `**` segment
    matches any number of segments, a trailing `/**` (or `/`) covers the directory's own path
    too, and `icase` matches without regard to case. A pattern whose last segment has no wildcard
    also covers everything under the path it names, so a bare directory `X` reads as `X/**`
    (Phase 366's round 3: `exclude: src/billing` excluded nothing under it). With `cover`, every
    pattern covers what is under what it matches, the wildcard included: an exclusion must err
    wide, and `exclude: secrets/*` must still cover `secrets/prod/key.pem` (Phase 374's round 2,
    which caught the narrowing meant for `allow:` applied to `exclude:` too)."""
    if pat.endswith("/"):
        pat += "**"
    if not pat or pat.startswith("/") or "\\" in pat or any(c in pat for c in "[]{}!"):
        raise Refuse(f"`## {CLASS_TITLE}`: not a supported path glob: {pat!r} (root-relative; "
                     "`*`, `?` and `**` only)")
    out = ""
    segs: list[str] = []
    for seg in pat.split("/"):
        if seg in ("", ".", "..") or ("**" in seg and seg != "**"):
            raise Refuse(f"`## {CLASS_TITLE}`: not a supported path glob: {pat!r}")
        if not (seg == "**" and segs and segs[-1] == "**"):  # `**/**` is `**`
            segs.append(seg)
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if seg == "**":
            if not last:
                out += "(?:[^/]+/)*"
            elif i:
                out = out[:-1] + "(?:/.*)?"  # `X/**` is X itself and everything under it
            else:
                out += ".*"
            continue
        out += "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in seg)
        # Only a last segment with no wildcard names a directory that covers what is under it, as
        # in CODEOWNERS: `src/*.py` must not admit `src/a.py/payload.sh` (Phase 374's round).
        out += ("" if any(c in seg for c in "*?") and not cover else "(?:/.*)?") if last else "/"
    return re.compile(out + r"\Z", re.S | (re.I if icase else 0))


def read_class(root: Path, rev: str = "") -> dict:
    """`## Unattended close class`: `allow:` and `exclude:` (repeatable, space-separated globs)
    and `blast_radius:` (the highest blast radius that may merge unattended). Exclusions match
    without regard to case, because a case-insensitive filesystem writes `.CLAUDE/x` into
    `.claude/`; allows match exactly, which can only refuse more. `code_owner:` (the human
    whose approval is the escape hatch, and whom `CODEOWNERS` must name) and `gate_app:` (the
    id of the GitHub App that posts the gate's check) are optional here and required by the
    gate (`close_gate.py`). `attested:` (the date a human attested what no `write` token can
    read: whose credentials the repository's secrets hold, and that workflows cannot approve
    pull requests) is optional here and required by the unattended land."""
    pairs = section_pairs(root, CLASS_TITLE, CLASS_KEYS, repeatable=("allow", "exclude"), rev=rev)
    cls: dict = {"allow": [], "exclude": [], "ceiling": "", "code_owner": "", "gate_app": "",
                 "attested": ""}
    for key, value in pairs:
        if key == "blast_radius":
            if value not in BLAST_ORDER:
                raise Refuse(f"`## {CLASS_TITLE}`: blast_radius must be one of "
                             f"{', '.join(BLAST_ORDER)}: {value!r}")
            cls["ceiling"] = value
        elif key == "code_owner":
            if not LOGIN.fullmatch(value.removeprefix("@")):
                raise Refuse(f"`## {CLASS_TITLE}`: code_owner is not a GitHub login: {value!r}")
            cls["code_owner"] = value.removeprefix("@")
        elif key == "gate_app":
            if not re.fullmatch(r"[1-9][0-9]{0,11}", value):
                raise Refuse(f"`## {CLASS_TITLE}`: gate_app is not a GitHub App id: {value!r}")
            cls["gate_app"] = value
        elif key == "attested":
            try:
                ok = bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)) and \
                    datetime.date.fromisoformat(value) is not None
            except ValueError:
                ok = False
            if not ok:
                raise Refuse(f"`## {CLASS_TITLE}`: attested is not a date (YYYY-MM-DD): {value!r}")
            cls["attested"] = value
        else:
            # An exclusion errs wide: case-insensitive, and NFC on both sides, since APFS and
            # HFS+ treat an NFC and an NFD spelling as one directory (Phase 374's round 3).
            cls[key] += [(p, glob_regex(unicodedata.normalize("NFC", p) if key == "exclude" else p,
                                        icase=key == "exclude", cover=key == "exclude"))
                         for p in value.split()]
    if not cls["allow"]:
        raise Refuse(f"`## {CLASS_TITLE}`: allow is required (the paths that may merge unattended)")
    if not cls["ceiling"]:
        raise Refuse(f"`## {CLASS_TITLE}`: blast_radius is required")
    return cls


def fold(s: str) -> str:
    """NFKC, then casefold: `ſysop` (U+017F) and `ＣＬＡＵＤＥ.md` both reach their governing
    spelling, the way a case-insensitive filesystem or a lenient reader can resolve them."""
    return unicodedata.normalize("NFKC", s).casefold()


_GOV = (frozenset(map(fold, GOVERNING_NAMES)), frozenset(map(fold, GOVERNING_DIRS)),
        frozenset(map(fold, GOVERNING_ROOTS)), frozenset(map(fold, GOVERNING_FILES)))


def governing(path: str) -> str:
    """The governing rule <path> falls under, compared folded, or "". A path that only folds to
    a governing one is governing too: the gate refuses the lookalike as well as the original."""
    names, dirs, roots, files = _GOV
    parts = [fold(p) for p in path.split("/")]
    if parts[-1] in names:
        return next(n for n in GOVERNING_NAMES if fold(n) == parts[-1])
    for part in parts:
        if part in dirs:
            return next(f"{d}/" for d in GOVERNING_DIRS if fold(d) == part)
    if parts[0] in roots:
        return next(f"/{r}/**" for r in GOVERNING_ROOTS if fold(r) == parts[0])
    if "/".join(parts) in files:
        return next(f"/{f}" for f in GOVERNING_FILES if fold(f) == "/".join(parts))
    return ""


def path_problem(cls: dict, path: str) -> str:
    rule = governing(path)
    if rule:
        return f"{path} (always excluded: {rule})"
    for pat, rx in cls["exclude"]:
        if rx.match(path) or rx.match(unicodedata.normalize("NFC", path)):
            return f"{path} (excluded: {pat})"
    if not any(rx.match(path) for _, rx in cls["allow"]):
        return f"{path} (not allowed)"
    return ""


def close_written(root: Path | None) -> list[str]:
    """CLOSE_WRITTEN in the case the repository tracks each root file: Step 4c writes the
    changelog at whatever case is tracked (`changelog.md` in one consumer), and an allow is
    case-sensitive. Untracked names keep their canonical spelling."""
    if root is None:
        return list(CLOSE_WRITTEN)
    _, out = git(root, "ls-files", "-z", "--", ":(top)")
    tracked = [t for t in out.split("\0") if t and "/" not in t]
    names: list[str] = []
    for p in CLOSE_WRITTEN:
        hits = [t for t in tracked if t.lower() == p.lower()] if "/" not in p else []
        names += hits or [p]
    return names


def class_warnings(cls: dict, root: Path | None = None) -> list[str]:
    return [f"WARN: the class does not admit {p}, which a close commits itself; every land "
            f"that carries it parks" for p in close_written(root) if path_problem(cls, p)]


def print_class(cls: dict, root: Path | None = None) -> None:
    print(f"ALLOW: {' '.join(p for p, _ in cls['allow'])}")
    print(f"EXCLUDE: {' '.join(p for p, _ in cls['exclude']) or '(none)'}")
    print(f"ALWAYS EXCLUDED: {' '.join(FIXED_EXCLUDE)}")
    print(f"BLAST_RADIUS: {cls['ceiling']}")
    print(f"CODE_OWNER: {cls['code_owner'] or '(none; the gate requires one)'}")
    print(f"GATE_APP: {cls['gate_app'] or '(none; the gate requires one)'}")
    print(f"ATTESTED: {cls['attested'] or '(none; the unattended land requires one)'}")
    for w in class_warnings(cls, root):
        print(w)


def lock_line(p: Path, key: str) -> str:
    """The first column-0 `<key>:` line of a lock, as the shipped readers line-read it."""
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"cannot read lock {p}: {e}") from e
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line[len(key) + 1:].strip().strip("\"'")
    return ""


def tasks_at(root: Path, commit: str) -> dict[str, dict] | None:
    """Task entries by id in `tasks/index.yml` at <commit>: {} when it has none, None when it
    does not parse."""
    code, out = git(root, "cat-file", "-p", f"{commit}:tasks/index.yml", ok=(0, 128))
    if code:
        return {}
    try:
        data = pending_doc_hold.yaml.safe_load(out) or {}
    except Exception:  # noqa: BLE001 — any PyYAML failure means "cannot read", never "empty"
        return None
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(tasks or [], list):
        return None
    ids = [str(t["id"]) for t in (tasks or []) if isinstance(t, dict) and t.get("id")]
    if len(ids) != len(set(ids)):
        return None  # two entries for one id: which one gates is undecidable
    return {str(t["id"]): t for t in (tasks or []) if isinstance(t, dict) and t.get("id")}


def task_problems(cls: dict, tid: str, entry) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{tid} has no entry in tasks/index.yml"]
    out = [f"{tid} is {flag}" for flag in ("manual_smoke", "solo") if entry.get(flag)]
    if entry.get("user_action"):
        out.append(f"{tid} has user_action set (a held step)")
    br = entry.get("blast_radius")
    if br not in BLAST_ORDER:
        out.append(f"{tid} has no blast_radius")
    elif BLAST_ORDER.index(br) > BLAST_ORDER.index(cls["ceiling"]):
        out.append(f"{tid} is blast_radius {br}, above {cls['ceiling']}")
    return out


def diff_paths(root: Path, base: str, tip: str) -> list[str]:
    """Every path changed between <base> and <tip>. `--no-renames` lists a rename's old path
    as well as its new one, so moving a file out of an excluded path is still seen."""
    _, out = git(root, "diff", "--name-only", "--no-renames", "--ignore-submodules=none", "-z",
                 base, tip)
    return [p for p in out.split("\0") if p]


# GitHub's squash, as `git merge-tree` reproduces it (spec § 10.3 item 3, § 10.7 (8)). GitHub
# does not detect directory renames and ignores `.gitattributes` merge drivers, so renames stay
# file-level and attributes come from the empty tree. The rest of git's merge configuration is
# fixed: `merge_tree` reads no global, system or repository config at all, and these pins sit on
# top of git's defaults. The scratch `GIT_DIR` already reads no tree's `.gitattributes` (its HEAD
# is unborn), and the allowlisted environment drops a caller's `GIT_ATTR_SOURCE`, whose
# `merge=union` made a conflicting merge clean (measured, Phase 374's battery); the empty
# `--attr-source` stays as § 10.3 specifies it. It replaces only the attribute source, though:
# a user's attributes file (`core.attributesFile`, or
# `~/.config/git/attributes` when that is unset) and the system one still apply, and a
# `merge=union` line in either made a conflicting merge clean (measured, Phase 374), so both are
# switched off.
MERGE_PINS = ("-c", "merge.directoryRenames=false", "-c", "merge.renames=true",
              "-c", "merge.renormalize=false", "-c", "core.ignorecase=false",
              "-c", f"core.attributesFile={os.devnull}")
LINK_MODES = ("120000", "160000")  # a symlink, a gitlink


MERGE_ENV_KEEP = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT")


def merge_env() -> dict:
    """The merge's whole environment, built from an allowlist. A denylist let a caller's
    `GIT_COMMON_DIR` bring the repository's config and `info/attributes` back into the scratch
    `GIT_DIR`, and `GIT_GRAFT_FILE` rewrite the history it merges (Phase 374's round 3)."""
    env = {k: os.environ[k] for k in MERGE_ENV_KEEP if k in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1",
               GIT_NO_REPLACE_OBJECTS="1")
    return env


def pinned_git_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_CONFIG") and k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1")
    return env


def git_version(root: Path) -> tuple[int, int]:
    _, out = git(root, "version")
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def merge_tree(root: Path, tip: str, head: str) -> tuple[str, str]:
    """("", tree) for GitHub's squash of <head> onto <tip>, or (why, "") when the merge does not
    complete cleanly: a non-zero `merge-tree` exit is never read as a tree.

    The merge runs in a throwaway, empty `GIT_DIR` whose object store is the repository's own
    (`GIT_OBJECT_DIRECTORY`), so nothing configured in the repository reaches it: not
    `merge.renameLimit` or `core.autocrlf` with `merge.renormalize` (each changed the result,
    Phase 374's round 2), and not `$GIT_DIR/info/attributes`, which no setting switches off. The
    global and system config are dropped too, and its environment is an allowlist (`merge_env`),
    so the merge is git's defaults plus `MERGE_PINS`. The merged tree is written into the repository's store, where the callers
    read it."""
    have = git_version(root)
    if have < GIT_FLOOR:
        raise Fail(f"git {have[0]}.{have[1]} is older than {GIT_FLOOR[0]}.{GIT_FLOOR[1]}, which the "
                   "merge result needs (`--attr-source`); install a newer git")
    _, a = git(root, "rev-parse", "--verify", "--end-of-options", f"{tip}^{{commit}}")
    _, b = git(root, "rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}")
    _, objects = git(root, "rev-parse", "--path-format=absolute", "--git-path", "objects")
    _, fmt = git(root, "rev-parse", "--show-object-format")
    _, empty = git(root, "hash-object", "-t", "tree", os.devnull)
    env = merge_env()
    with tempfile.TemporaryDirectory(prefix="sysop-merge-") as tmp:
        bare = Path(tmp) / "repo.git"
        init = subprocess.run(["git", "init", "-q", "--bare", f"--object-format={fmt.strip()}",
                               "--template=", str(bare)], capture_output=True, env=env)
        if init.returncode != 0:
            raise Fail(f"cannot create the scratch repository for the merge: {os.fsdecode(init.stderr).strip()}")
        env.update(GIT_DIR=str(bare), GIT_OBJECT_DIRECTORY=objects.strip())
        p = subprocess.run(["git", f"--attr-source={empty.strip()}", *MERGE_PINS,
                            "merge-tree", "--write-tree", "--no-messages", a.strip(), b.strip()],
                           capture_output=True, env=env, cwd=tmp)
    if p.returncode != 0:
        why = "conflicts" if p.returncode == 1 else os.fsdecode(p.stderr).strip() or f"exit {p.returncode}"
        return f"does not merge cleanly onto {tip[:10]}: {why}", ""
    tree = os.fsdecode(p.stdout).split("\n", 1)[0].strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
        return f"merge-tree printed no tree: {tree!r}", ""
    return "", tree


def tree_entries(root: Path, tip: str, tree: str) -> list[tuple[str, str, str]]:
    """[(old mode, new mode, path), ...] for every path changed between <tip> and <tree>, with
    `--no-renames`, so a deletion and both sides of a rename count."""
    _, raw = git(root, "diff-tree", "-r", "-z", "--no-renames", "--raw", tip, tree)
    fields = raw.split("\0")
    entries = []
    for meta, path in zip(fields[0::2], fields[1::2]):
        if meta:
            old, new = meta.lstrip(":").split()[:2]
            entries.append((old, new, path))
    return entries


def merge_result(root: Path, tip: str, head: str) -> tuple[str, list[tuple[str, str, str]]]:
    """("", entries) for every path GitHub's squash of <head> onto <tip> would change, or (why, [])
    when it does not merge cleanly. Read from the merge result, not a merge-base diff, which
    misses a path a criss-cross history hides (Phase 367, round 1, H5)."""
    why, tree = merge_tree(root, tip, head)
    return (why, []) if why else ("", tree_entries(root, tip, tree))


def merge_problems(cls: dict, entries: list[tuple[str, str, str]]) -> list[str]:
    """The merge result against the class: no symlink or gitlink on either side of any change,
    and every path admitted (the governing set refused, compared folded)."""
    out = [f"{path} is a symlink or gitlink (mode {old if old in LINK_MODES else new})"
           for old, new, path in entries if old in LINK_MODES or new in LINK_MODES]
    bad = paths_problems(cls, [path for _, _, path in entries])
    if bad:
        out.append("paths outside the class: " + "; ".join(bad))
    return out


def paths_problems(cls: dict, paths: list[str]) -> list[str]:
    bad = [b for b in (path_problem(cls, p) for p in paths) if b]
    if len(bad) > 5:
        bad = bad[:5] + [f"and {len(bad) - 5} more"]
    return bad


def cmd_class(root: Path) -> int:
    print_class(read_class(root), root)
    return 0


def cmd_eligible(root: Path, default: str, agent: str, branches: list[str],
                 held: bool = False) -> int:
    """Half A's selection: one `IN` or `OUT` line per branch. An OUT branch is set aside.
    With `held`, the unattended close's: a held branch at its held head is OUT too."""
    if not AGENT.fullmatch(agent):
        raise Refuse(f"not an agent name: {agent!r}")
    cls = read_class(root)
    print_class(cls, root)
    dtip = ref_sha(root, "refs/heads/" + default)
    if not dtip:
        raise Fail(f"default branch {default!r} does not resolve")
    locks = sorted((root / "sysop" / "runtime" / "locks").glob("*.lock"))
    wts = worktrees(root)
    default_tasks = tasks_at(root, dtip)
    for branch in branches:
        why_held = held_out(root, default, branch) if held else ""
        tip = ref_sha(root, "refs/heads/" + branch)
        if not tip:
            print(f"OUT {branch}: no such branch")
            continue
        if why_held:
            print(f"OUT {branch}: {why_held}")
            continue
        mine = [p for p in locks if lock_branch(p) == branch]
        if not mine:
            print(f"OUT {branch}: not mine: no lock names this branch")
            continue
        if len(mine) > 1:
            print(f"OUT {branch}: {len(mine)} locks name this branch: {' '.join(p.name for p in mine)}")
            continue
        owner = lock_line(mine[0], "agent")
        if owner != agent:
            print(f"OUT {branch}: not mine: its lock reads agent: {owner or '(none)'}")
            continue
        tid = lock_line(mine[0], "task_id") or mine[0].stem
        tasks = tasks_at(root, tip)
        if tasks is None or default_tasks is None:
            print(f"OUT {branch}: tasks/index.yml at its tip or at local {default} does not parse "
                  "(or names one id twice)")
            continue
        # The gating fields are read where the branch cannot write them, local <default>, and
        # where it can, its tip; both must pass, so a branch cannot clear its own task's flags.
        problems = [f"at local {default}: {p}" for p in task_problems(cls, tid, default_tasks.get(tid))]
        problems += [f"at its tip: {p}" for p in task_problems(cls, tid, tasks.get(tid))]
        entry = tasks.get(tid)
        places = [root] + [w for w in wts.get(branch, []) if w.resolve() != root.resolve()]
        ws = lock_line(mine[0], "workspace")
        if ws and Path(ws).resolve() != root.resolve() and Path(ws) not in places:
            places.append(Path(ws))
        for place in places:
            for d in pending_doc_hold.pending_docs(place):
                doc = pending_doc_hold.Doc(d)
                if doc.error:
                    # The main checkout's docs are every branch's; one nobody can read is
                    # attributed to no branch (Step 4c 1c reports it). A branch's own
                    # workspace holds only its own.
                    if place is not root:
                        problems.append(f"pending doc {d} cannot be read: {doc.error}")
                    continue
                b = str(doc.fm.get("branch") or "").strip()
                if b.startswith("refs/heads/"):
                    b = b[len("refs/heads/"):]
                if b == branch and pending_doc_hold.doc_hold(doc.fm):
                    problems.append(f"pending doc {d.name} carries hold:")
        # The merge result onto local <default>, as GitHub's squash would make it, not a
        # merge-base diff (spec § 10.8): the gate reads the same, and a criss-cross hides a
        # governing path from the merge-base diff.
        why, entries = merge_result(root, dtip, tip)
        if why:
            problems.append(why)
        problems += merge_problems(cls, entries)
        paths = [p for _, _, p in entries]
        if problems:
            print(f"OUT {branch}: " + "; ".join(problems))
        else:
            print(f"IN {branch}: {tid}, blast_radius {(entry or {}).get('blast_radius')}, "
                  f"{len(paths)} path(s)")
    otip = ref_sha(root, "refs/remotes/origin/" + default)
    if otip and not is_ancestor(root, dtip, "refs/remotes/origin/" + default):
        _, base = git(root, "merge-base", otip, dtip)
        bad = paths_problems(cls, diff_paths(root, base.strip(), dtip))
        if bad:
            print(f"NOTE: local {default} carries commits origin/{default} lacks, and the PR will "
                  f"carry them; outside the class, so the land will park: " + "; ".join(bad))
    return 0


def read_parked(run: Path) -> dict | None:
    p = run / "PARKED"
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        rec = None
    if not isinstance(rec, dict) or not isinstance(rec.get("lines"), list):
        return {"code": "unreadable", "at": "?", "lines": [f"{p} cannot be read"]}
    return rec


def park(run: Path, rec: dict, code: str, lines: list[str]) -> None:
    """Write `PARKED`: the hand-off waits for a human, and unattended lands read nothing more."""
    at = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(run / "PARKED", {"code": code, "at": at, "lines": lines})
    rec.setdefault("parks", []).append({"code": code, "at": at, "lines": lines})
    write_json(run / "handoff.json", rec)


def handoff_problems(root: Path, run: Path, rec: dict, agent: str) -> list[str]:
    """What only the client can read, so the gate cannot decide it (spec § 10.5): the hand-off
    kept a task lock, each kept lock still reads this agent, and report.md names no held-doc
    branch (`hold:` is frontmatter on a gitignored pending doc, which GitHub never sees). Paths,
    task fields and the reader's verdict are the gate's (Phase 375, Wade: the client stops
    deciding what the gate decides)."""
    out: list[str] = []
    if not rec["kept_locks"]:
        out.append("the hand-off kept no task lock, so no task of this agent's is in it")
    for tid in rec["kept_locks"]:
        lock = root / "sysop" / "runtime" / "locks" / f"{tid}.lock"
        if not lock.is_file():
            out.append(f"{tid}'s kept lock is gone")
        elif lock_line(lock, "agent") != agent:
            out.append(f"{tid}'s lock reads agent: {lock_line(lock, 'agent') or '(none)'}, not {agent}")
    try:
        report = (run / "report.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return out + [f"cannot read report.md: {e}"]
    held = re.search(r"^Held-doc branches:(.*)$", report, re.M)
    if not held or held.group(1).strip() not in ("", "(none)"):
        out.append("report.md names held-doc branches" if held else
                   "report.md has no Held-doc branches: line")
    return out


GATE_CHECK = "sysop/close-gate"  # the check `close_gate.py` posts, and the ruleset pins
GATE_ENVIRONMENT = "sysop-close-gate"  # the environment the gate workflow's job names


def setup_problems(root: Path, cls: dict, default: str) -> list[str]:
    """§ 10.3's server setup, read with the token `gh` holds (the machine user's), before any
    unattended merge. Each read a `write` token can make was measured at Phase 375 on the scratch
    repository; what it cannot read (whose credentials the secrets hold, and
    `can_approve_pull_request_reviews`, a 404) is the human's attestation. Any read that fails
    is a problem: the land does not merge on a setup it could not see."""
    out: list[str] = []
    for key, why in (("code_owner", "the human whose approval is the escape hatch"),
                     ("gate_app", "the app the ruleset pins the gate's check to"),
                     ("attested", "the date a human attested the secrets and workflow-approval "
                                  "settings (WORKFLOW.md § Unattended close gate)")):
        if not cls[key]:
            out.append(f"`## {CLASS_TITLE}` names no {key}: ({why})")
    # A day's grace: a human east of UTC writes a date UTC has not reached yet.
    if cls["attested"] and cls["attested"] > (utcnow() + datetime.timedelta(days=1)).strftime("%Y-%m-%d"):
        out.append(f"`## {CLASS_TITLE}`: attested {cls['attested']} is in the future")

    def read(what: str, *args: str):
        try:
            return gh_json(root, *args)
        except Fail as e:
            out.append(f"cannot read {what}: {e}")
            return None

    me = read("the token's user", "api", "user")
    login = me.get("login") if isinstance(me, dict) else None
    if isinstance(me, dict) and not isinstance(login, str):
        out.append("the token's user has no login")
    if isinstance(login, str):
        if cls["code_owner"] and fold(login) == fold(cls["code_owner"]):
            out.append(f"gh is authenticated as the code owner {login}: the unattended land runs "
                       "as a separate machine user (§ 10.3 item 1)")
        perm = read("the token's permission",
                    "api", f"repos/{{owner}}/{{repo}}/collaborators/{login}/permission")
        role = perm.get("role_name") if isinstance(perm, dict) else None
        if perm is not None and role != "write":
            out.append(f"{login}'s role on the repository is {role!r}, not 'write': an admin or "
                       "maintainer can change the rules this land relies on")
    try:
        rules = gh_list(root, f"repos/{{owner}}/{{repo}}/rules/branches/{default}")
    except Fail as e:
        out.append(f"cannot read the rules on {default}: {e}")
        return out
    rules = [r for r in rules if isinstance(r, dict)]

    def params(kind: str) -> list[dict]:
        return [r["parameters"] for r in rules
                if r.get("type") == kind and isinstance(r.get("parameters"), dict)]

    pr_rules = params("pull_request")
    if not any(p.get("require_code_owner_review") is True and p.get("dismiss_stale_reviews_on_push") is True
               for p in pr_rules):
        out.append(f"no ruleset on {default} requires a pull request with code-owner review and "
                   "stale-review dismissal")
    if any(p.get("require_last_push_approval") is True for p in pr_rules):
        out.append(f"a ruleset on {default} requires last-push approval, which refuses every "
                   "unattended merge (§ 10.7 (1))")
    pinned = [c for p in params("required_status_checks")
              if p.get("strict_required_status_checks_policy") is True
              for c in (p.get("required_status_checks") or []) if isinstance(c, dict)]
    if not any(c.get("context") == GATE_CHECK and str(c.get("integration_id")) == cls["gate_app"]
               for c in pinned):
        out.append(f"no ruleset on {default} requires {GATE_CHECK} from app {cls['gate_app'] or '?'} "
                   "with strict status checks")
    ids = sorted({r.get("ruleset_id") for r in rules if isinstance(r.get("ruleset_id"), int)})
    if not ids:
        out.append(f"no ruleset applies to {default}")
    for rid in ids:
        rs = read(f"ruleset {rid}", "api", f"repos/{{owner}}/{{repo}}/rulesets/{rid}")
        can = rs.get("current_user_can_bypass") if isinstance(rs, dict) else None
        if rs is not None and can != "never":
            out.append(f"this token can bypass ruleset {rid} ({can!r}); anything but 'never' "
                       "refuses (§ 10.3 item 1)")
    env = read(f"the {GATE_ENVIRONMENT} environment",
               "api", f"repos/{{owner}}/{{repo}}/environments/{GATE_ENVIRONMENT}")
    if env is not None:
        policy = env.get("deployment_branch_policy") if isinstance(env, dict) else None
        if policy != {"protected_branches": False, "custom_branch_policies": True}:
            out.append(f"the {GATE_ENVIRONMENT} environment is not set to selected branches "
                       f"({policy!r}): a branch workflow could sign the gate's check")
        else:
            pols = read(f"the {GATE_ENVIRONMENT} environment's branch rules", "api",
                        f"repos/{{owner}}/{{repo}}/environments/{GATE_ENVIRONMENT}/deployment-branch-policies")
            got = [(p.get("name"), p.get("type", "branch")) for p in
                   (pols.get("branch_policies") or [] if isinstance(pols, dict) else []) if isinstance(p, dict)]
            if pols is not None and got != [(default, "branch")]:
                out.append(f"the {GATE_ENVIRONMENT} environment's branch rules are {got!r}, not "
                           f"exactly one branch rule naming {default}")
    return out


def gate_reading(root: Path, head: str, app: str) -> tuple[str, str]:
    """(wait, red) for the gate's check on <head>, read from the check runs of app <app> alone:
    a run of the same name from any other app is ignored, as the ruleset's pin ignores it. The
    newest of the app's runs decides; an unreadable answer waits, so it parks at the timeout."""
    try:
        data = gh_json(root, "api", f"repos/{{owner}}/{{repo}}/commits/{head}/check-runs"
                       f"?check_name={quote(GATE_CHECK, safe='')}&filter=all&per_page=100")
    except Fail as e:
        return f"cannot read {GATE_CHECK}'s check runs: {e}", ""
    runs = data.get("check_runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        return f"{GATE_CHECK}'s check runs did not read as a list", ""
    mine = [r for r in runs if isinstance(r, dict) and isinstance(r.get("app"), dict)
            and str(r["app"].get("id")) == app and r.get("name") == GATE_CHECK]
    others = len([r for r in runs if isinstance(r, dict)]) - len(mine)
    note = f" ({others} run(s) of that name from another app, ignored)" if others else ""
    if not mine:
        return f"no {GATE_CHECK} check from app {app} on the head yet{note}", ""
    last = max(mine, key=lambda r: (str(r.get("started_at") or ""), r.get("id") or 0))
    if last.get("status") != "completed":
        return f"{GATE_CHECK} from app {app} is {last.get('status')}{note}", ""
    if last.get("conclusion") != "success":
        title = (last.get("output") or {}).get("title") if isinstance(last.get("output"), dict) else ""
        return "", f"{GATE_CHECK} from app {app} concluded {last.get('conclusion')}: {title or '(no title)'}"
    return "", ""


def disable_auto(root: Path, pr: str) -> str:
    try:
        gh(root, "pr", "merge", pr, "--disable-auto")
        return "auto-merge turned off"
    except Fail as e:
        return f"auto-merge could not be turned off ({e}): a human turns it off on GitHub"


def disarm(root: Path, rec: dict) -> str:
    """Turn auto-merge off and forget this land's arm; the record is the caller's to write. A
    failure keeps `armed`, so the next park, unpark or re-request tries again."""
    note = disable_auto(root, rec["pr"])
    if note == "auto-merge turned off":
        rec.pop("armed", None)
    return note


PR_FIELDS_UNATTENDED = PR_FIELDS + ",mergeStateStatus,autoMergeRequest,statusCheckRollup"


def cmd_land_unattended(root: Path, run_id: str, default: str, agent: str) -> int:
    run, rec = open_handoff(root, run_id, default)
    refuse_if_stopped(root)
    if rec["status"] not in ("awaiting", "request-failed", "requesting"):
        raise Refuse(f"hand-off {run_id} is {rec['status']}: nothing to land")
    if not rec.get("sealed"):
        raise Refuse(f"hand-off {run_id} is unsealed: write its report.md and run "
                     f"`close_run.py seal {run_id}`")
    owner = (rec.get("unattended") or {}).get("agent") if isinstance(rec.get("unattended"), dict) else None
    if not owner:
        raise Refuse(f"hand-off {run_id} was not requested with --agent: land it attended")
    if owner != agent:
        raise Refuse(f"hand-off {run_id} belongs to agent {owner!r}, not {agent!r}")
    print(f"PR: {rec['pr']} {rec['url']}")
    print(f"BRANCH: {rec['branch']}")
    print(f"SHAPE: {'integration branch' if rec['branch'].startswith('merge/review-close-') else 'PR reuse'}")
    print(f"HEAD: {rec['head']}")
    print(f"PUSHED FROM: {rec['pushed_from']}")
    print(f"KEEP BRANCH: {'yes' if rec['keep_branch'] else 'no'}")
    print(f"REPORT: {run / 'report.md'}")
    parked = read_parked(run)
    if parked:
        print(f"PARKED: {parked.get('code')} at {parked.get('at')}; a human clears it")
        for line in parked["lines"]:
            print(f"READER: {line}")
        if rec.get("armed"):  # a park whose disarm failed: try again, or GitHub merges it
            note = disarm(root, rec)
            write_json(run / "handoff.json", rec)
            print(f"READER: {note}")
        print("VERDICT: PARK")
        return 4
    data: dict = {}

    def stop(code: str, lines: list[str]) -> int:
        # An armed PR would merge while parked: the park turns auto-merge off first.
        if data.get("autoMergeRequest") or rec.get("armed"):
            lines = lines + [disarm(root, rec)]
        park(run, rec, code, lines)
        for line in lines:
            print(f"READER: {line}")
        print(f"PARKED: {code}")
        print("VERDICT: PARK")
        return 4

    def wait(what: str) -> int:
        """Wait on the hand-off's clock (ruling (q)), counted from the first land that waited;
        park at the timeout, so no wait is forever (Phase 366's round 3)."""
        since = parse_time(rec.get("checks_waiting_since"))
        if since is None:
            since = utcnow()
            rec["checks_waiting_since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            write_json(run / "handoff.json", rec)
        deadline = since + datetime.timedelta(seconds=timeout_seconds(rec["timeout"]) or 0)
        if utcnow() > deadline:
            return stop("checks", [f"{what} at {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')} (counting "
                                   f"from {rec['checks_waiting_since']}, timeout {rec['timeout']})"])
        print(f"READER: {what}; parks at {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        print("VERDICT: WAIT")
        return 5

    def merged(data: dict) -> int:
        if data.get("headRefOid") != rec["head"]:
            print(f"MERGED ELSEWHERE: merged at {data.get('headRefOid')}, not the recorded head "
                  f"{rec['head']}: GitHub's rules passed a head this land never checked")
        print("VERDICT: ALREADY MERGED")
        return 0

    data = gh_json(root, "pr", "view", rec["pr"], "--json", PR_FIELDS_UNATTENDED)
    data = data if isinstance(data, dict) else {}
    state = data.get("state")
    if state == "MERGED":
        return merged(data)
    if rec["status"] != "awaiting":
        return stop("reader", [f"the hand-off is {rec['status']}: no review was requested"])
    problems = []
    if state != "OPEN":
        problems.append(f"the PR is {state}, not open")
    if data.get("isDraft"):
        problems.append("the PR is a draft")
    if data.get("isCrossRepository"):
        problems.append("the PR's head is in another repository")
    if data.get("baseRefName") != rec["default_branch"]:
        problems.append(f"the PR's base is {data.get('baseRefName')!r}, not {rec['default_branch']!r}")
    if data.get("headRefOid") != rec["head"]:
        problems.append(f"the PR's head is {data.get('headRefOid')}, not the recorded {rec['head']}")
    if problems:
        return stop("pr-state", problems)
    auto = data.get("autoMergeRequest")
    armed = rec.get("armed") if isinstance(rec.get("armed"), dict) else None
    if auto and not (armed and armed.get("head") == rec["head"]):
        who = (auto.get("enabledBy") or {}).get("login") if isinstance(auto, dict) else None
        method = auto.get("mergeMethod") if isinstance(auto, dict) else None
        return stop("pr-state", [f"auto-merge is on, turned on by {who or '(unknown)'} ({method or '?'}), "
                                 "not by this land at the recorded head"])
    # The class is read at the default branch's live tip, as GitHub has it, which an unattended
    # merge cannot have changed (`CLAUDE.md` is governing). Local origin must be that tip.
    default = rec["default_branch"]
    ref = gh_json(root, "api", f"repos/{{owner}}/{{repo}}/git/ref/heads/{default}")
    tip = str(ref.get("object", {}).get("sha") or "") if isinstance(ref, dict) \
        and isinstance(ref.get("object"), dict) else ""
    if not SHA.fullmatch(tip):
        return stop("pr-state", [f"GitHub reported no tip for {default}: {tip!r}"])
    local_origin = ref_sha(root, "refs/remotes/origin/" + default)
    if local_origin != tip:
        return wait(f"origin/{default} here is {local_origin[:10] or 'absent'} and GitHub's is "
                    f"{tip[:10]}; fetch origin {default} and land again")
    try:
        cls = read_class(root, rev=tip)
    except Refuse as e:
        return stop("class", [str(e)])
    problems = handoff_problems(root, run, rec, agent)
    if problems:
        return stop("class", ["outside the unattended class: " + p for p in problems])
    # Step 6's two conditions, read before the merge (ruling (r)): after it the hand-off is
    # gone and a stop strands local <default>. Both are local reads.
    _, dirty = git(root, "diff", "--name-only", "HEAD", "--")
    if dirty.strip():
        return stop("dirty", ["the main checkout has uncommitted changes to tracked files, which "
                              "Step 6's reset would discard: " + ", ".join(dirty.split()[:10])])
    local = ref_sha(root, "refs/heads/" + default)
    if not local:
        return stop("hard-fail", [f"local {default} does not resolve"])
    if not ref_sha(root, rec["pushed_from"]):
        return stop("hard-fail", [f"the pushed-from commit {rec['pushed_from'][:10]} is not in this repository"])
    _, after = git(root, "rev-list", f"{rec['pushed_from']}..{local}", "^refs/remotes/origin/" + default)
    if after.split():
        return stop("after-push", [f"local {default} has {len(after.split())} commit(s) "
                                   f"made after the push, which Step 6's reset would drop: "
                                   + ", ".join(c[:10] for c in after.split()[:10])])
    problems = setup_problems(root, cls, default)
    if problems:
        return stop("setup", ["the server setup: " + p for p in problems])
    # Every registered check must pass before the merge is armed (ruling (s), kept by Wade at
    # Phase 375): once armed, GitHub merges on the required checks alone. A count of 0, or a
    # check still running, waits on the hand-off's clock (ruling (q)). The gate is left out of
    # the rollup's judgement: it leaves its superseded runs `in_progress` (each run opens one
    # before it evaluates), which `check_states` would read as running for good, and a run of
    # its name from another app is no reading at all. `gate_reading` decides it, newest first.
    checks = data.get("statusCheckRollup")
    checks = checks if isinstance(checks, list) else []
    failed, pending = check_states([c for c in checks if not (
        isinstance(c, dict) and GATE_CHECK in (c.get("name"), c.get("context")))])
    if failed:
        return stop("checks", [f"a check did not pass: {f}" for f in failed])
    # The rollup names no app, and a branch workflow can post a green `sysop/close-gate` as
    # `github-actions` (measured, Phase 375's R1), so the gate's reading is taken from its own
    # app's check runs on the head, as the ruleset's pin takes it.
    gate_wait, gate_red = gate_reading(root, rec["head"], cls["gate_app"])
    if gate_red:
        return stop("gate-red", [gate_red])
    if not checks or pending or gate_wait:
        return wait(f"{len(pending)} check(s) still running: {', '.join(pending[:5])}" if pending
                    else "no check registered on the PR" if not checks
                    else gate_wait)
    print(f"CHECKS: {len(checks)}")
    merge_state = data.get("mergeStateStatus")
    if merge_state == "BEHIND":
        return stop("pr-state", [f"the PR is behind {default}, which strict status checks refuse; "
                                 "a human updates it and re-requests the review"])
    if merge_state == "DIRTY":
        return stop("conflict", [f"the PR does not merge cleanly onto {default}"])
    if not data.get("autoMergeRequest"):
        # `--auto` on a PR GitHub would merge now merges at once (measured, Phase 375: P2); on one
        # still waiting it arms. `--delete-branch` is not passed: with `--auto` it deleted nothing
        # (P3), so Step 6 deletes the branch.
        try:
            gh(root, "pr", "merge", rec["pr"], "--auto", "--squash", "--match-head-commit", rec["head"])
        except Fail as e:
            # The call can fail after GitHub turned auto-merge on (a lost reply), so read the PR
            # again: `stop` turns off whatever it shows (lens 2, Phase 375's round 1).
            try:
                again = gh_json(root, "pr", "view", rec["pr"], "--json", PR_FIELDS_UNATTENDED)
                data = again if isinstance(again, dict) else data
            except Fail:
                rec["armed"] = {"head": rec["head"], "at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "unconfirmed": True}
            if data.get("state") == "MERGED":
                return merged(data)
            return stop("hard-fail", [f"enabling auto-merge failed: {e}"])
        rec["armed"] = {"head": rec["head"], "at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        write_json(run / "handoff.json", rec)
        data = gh_json(root, "pr", "view", rec["pr"], "--json", PR_FIELDS_UNATTENDED)
        data = data if isinstance(data, dict) else {}
        if data.get("state") == "MERGED":
            return merged(data)
        if not data.get("autoMergeRequest"):
            return stop("hard-fail", ["gh reported auto-merge enabled, but the PR shows none and "
                                      "is not merged"])
    armed = rec.get("armed") if isinstance(rec.get("armed"), dict) else {}
    since = parse_time(armed.get("at")) or utcnow()
    deadline = since + datetime.timedelta(seconds=timeout_seconds(rec["timeout"]) or 0)
    if utcnow() > deadline:
        return stop("checks", [f"armed at {armed.get('at')} and not merged by "
                               f"{deadline.strftime('%Y-%m-%dT%H:%M:%SZ')} (mergeStateStatus "
                               f"{merge_state}): GitHub is waiting on something only a human can give"])
    print(f"READER: auto-merge is on (mergeStateStatus {merge_state}); GitHub merges when its rules "
          f"pass; parks at {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print("VERDICT: ARMED")
    return 5


# GitHub's CheckConclusionState and StatusState, read 2026-10-08 by GraphQL introspection.
CHECK_PASSED = ("SUCCESS", "NEUTRAL", "SKIPPED")


def check_states(checks: list) -> tuple[list[str], list[str]]:
    """(failed, pending) names over a `statusCheckRollup`, judged per check on its latest run, as
    branch protection judges it: the rollup keeps superseded runs, so a check that failed and was
    re-run green appears twice (round 2, read off a public PR). A check is keyed by its workflow
    and name (a CheckRun) or its context (a StatusContext). A run of it still going makes it
    pending; otherwise the run started last decides. A CheckRun passes only COMPLETED with
    SUCCESS, NEUTRAL or SKIPPED, a StatusContext only SUCCESS; an entry this cannot read fails."""
    failed, pending = [], []
    runs: dict[tuple, list[dict]] = {}
    for c in checks:
        if not isinstance(c, dict):
            failed.append("(unreadable rollup entry)")
            continue
        status = c.get("__typename") == "StatusContext" or ("state" in c and "status" not in c)
        key = ("status", str(c.get("context") or "?")) if status else \
            ("check", str(c.get("workflowName") or ""), str(c.get("name") or "?"))
        runs.setdefault(key, []).append(c)
    for key, group in runs.items():
        name = key[-1]
        if key[0] == "status":
            last = max(enumerate(group), key=lambda ic: (str(ic[1].get("startedAt") or ""), ic[0]))[1]
            state = last.get("state")
            if state != "SUCCESS":
                (pending if state in ("PENDING", "EXPECTED") else failed).append(f"{name} ({state})")
            continue
        if any(c.get("status") != "COMPLETED" for c in group):
            pending.append(name)
            continue
        last = max(enumerate(group), key=lambda ic: (str(ic[1].get("startedAt") or ic[1].get("completedAt") or ""), ic[0]))[1]
        if last.get("conclusion") not in CHECK_PASSED:
            failed.append(f"{name} ({last.get('conclusion')})")
    return failed, pending


def cmd_park(root: Path, run_id: str, code: str, reason: str) -> int:
    run, rec = open_handoff(root, run_id)
    if rec["status"] not in ("awaiting", "request-failed", "requesting"):
        raise Refuse(f"hand-off {run_id} is {rec['status']}: nothing to park")
    if code not in PARK_CODES:
        raise Refuse(f"not a park code: {code!r} (one of {', '.join(PARK_CODES)})")
    if not reason.strip():
        raise Refuse("a park needs its reason")
    lines = [reason.strip()]
    if rec.get("armed"):
        lines.append(disarm(root, rec))
    park(run, rec, code, lines)
    print(f"PARKED: {run_id} ({code})")
    for line in lines[1:]:
        print(f"READER: {line}")
    return 0


def cmd_unpark(root: Path, run_id: str) -> int:
    run, rec = open_handoff(root, run_id)
    if read_parked(run) is None:
        raise Refuse(f"hand-off {run_id} is not parked")
    if rec["status"] != "awaiting":
        raise Refuse(f"hand-off {run_id} is {rec['status']}: no review was requested, so a land "
                     f"would park again; run `close_run.py re-request {run_id} <default branch>`")
    (run / "PARKED").unlink()
    rec.pop("checks_waiting_since", None)
    note = disarm(root, rec) if rec.get("armed") else ""
    write_json(run / "handoff.json", rec)
    print(f"UNPARKED: {run_id}")
    if note:
        print(f"READER: {note}")
    return 0


# ---------------------------------------------------------------------------------------------
# Half A with no human (`Q-664`, Phase 380; spec § 13): the durable stop and the branch hold.
# ---------------------------------------------------------------------------------------------

RUN_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")


def holds_dir(root: Path) -> Path:
    return runs_dir(root) / "holds"


def hold_path(root: Path, branch: str) -> Path:
    return holds_dir(root) / (quote(branch, safe="") + ".json")


def stamp_now() -> str:
    return utcnow().strftime("%Y%m%dT%H%M%SZ")


def cmd_stop(root: Path, run_id: str, step: str, reason: str, locks: list[str]) -> int:
    if not RUN_ID.fullmatch(run_id):
        raise Refuse(f"not a run id: {run_id!r}")
    # Step 4c prints `LOCKS_KEPT: (none)` when it kept none. Anything else that is not a task id
    # is recorded as given, never refused: a refusing stop would leave the close unguarded.
    locks = [t for t in locks if t != "(none)"]
    odd = [t for t in locks if not TASK_ID.fullmatch(t)]
    locks = [t for t in locks if TASK_ID.fullmatch(t)]
    run = runs_dir(root) / run_id
    run.mkdir(parents=True, exist_ok=True)
    rec = {"run_id": run_id, "step": step.strip(), "reason": reason.strip(),
           "locks_kept": locks, "at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    if odd:
        rec["locks_unparsed"] = odd
    marker = run / "STOPPED"
    if marker.exists():
        prior = read_stopped(marker)
        rec["earlier"] = [prior] + list(prior.pop("earlier", []) or [])
    write_json(marker, rec)
    print(f"STOPPED: {run_id} at {rec['step']}")
    print(f"MARKER: {marker}")
    return 0


def read_stopped(marker: Path) -> dict:
    try:
        rec = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        rec = None
    if not isinstance(rec, dict):
        return {"step": "?", "reason": f"{marker} cannot be read", "locks_kept": []}
    return rec


def cmd_clear(root: Path, run_id: str) -> int:
    if not RUN_ID.fullmatch(run_id):
        raise Refuse(f"not a run id: {run_id!r}")
    marker = runs_dir(root) / run_id / "STOPPED"
    if not marker.exists():
        raise Refuse(f"run {run_id} has no STOPPED marker")
    kept = marker.with_name(f"STOPPED.cleared-{stamp_now()}")
    n = 1
    while kept.exists():  # two clears in one second keep both records
        n += 1
        kept = marker.with_name(f"STOPPED.cleared-{stamp_now()}-{n}")
    os.replace(marker, kept)
    print(f"CLEARED: {run_id} (kept as {kept.name})")
    return 0


def cmd_hold(root: Path, run_id: str, branch: str, reason: str) -> int:
    if not RUN_ID.fullmatch(run_id):
        raise Refuse(f"not a run id: {run_id!r}")
    if not reason.strip():
        raise Refuse("a hold needs its reason")
    head = ref_sha(root, "refs/heads/" + branch) if branch and not branch.startswith("<") else ""
    if not head:
        raise Refuse(f"branch {branch!r} does not exist")
    holds_dir(root).mkdir(parents=True, exist_ok=True)
    write_json(hold_path(root, branch), {
        "branch": branch, "head": head, "reason": reason.strip(), "run_id": run_id,
        "at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")})
    print(f"HELD: {branch} at {head[:12]}")
    return 0


def read_hold(p: Path) -> dict | None:
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), str)
                                            for k in ("branch", "head", "reason")):
        return None
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", rec["head"]):
        return None  # an empty or damaged head must hold, not read as "moved"
    return rec


def cmd_unhold(root: Path, branch: str, note: str) -> int:
    p = hold_path(root, branch)
    if not p.exists():
        raise Refuse(f"branch {branch!r} is not held")
    rec = read_hold(p) or {"branch": branch, "unreadable": True}
    rec["cleared"] = {"at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "note": note.strip()}
    kept = p.with_name(f"{p.name}.cleared-{stamp_now()}")
    write_json(kept, rec)
    p.unlink()
    print(f"UNHELD: {branch}")
    return 0


def held_out(root: Path, default: str, branch: str) -> str:
    """The `OUT` reason for a held branch whose tip is the held head, or "". A hold whose
    branch moved, merged into <default> or is gone is removed here, with a `NOTE:` line."""
    p = hold_path(root, branch)
    if not p.exists():
        return ""
    rec = read_hold(p)
    if rec is None:
        return f"held: {p} cannot be read (a human: fix or `close_run.py unhold {branch}`)"
    tip = ref_sha(root, "refs/heads/" + branch)
    why = ("is gone" if not tip else
           f"moved to {tip[:12]}" if tip != rec["head"] else
           f"is merged into {default}" if is_ancestor(root, tip, "refs/heads/" + default) else
           "landed in a recorded PR head" if git(root, "for-each-ref", "--contains", tip,
                                                  "--format=%(refname)", "refs/sysop/merged-pr-heads/",
                                                  ok=(0, 1, 129))[1].strip() else "")
    if why:
        p.with_name(f"{p.name}.cleared-{stamp_now()}").write_text(
            json.dumps({**rec, "cleared": {"why": why}}, indent=2) + "\n", encoding="utf-8")
        p.unlink()
        print(f"NOTE: {branch}'s hold is cleared: the branch {why}")
        return ""
    return f"held at {rec['head'][:12]}: {rec['reason']}"


def main(argv: list[str]) -> int:
    # `merge_env` ignores `refs/replace/*`; so must every other read, or the base read and the
    # merge diverge (Phase 374's round 4, the client half of round 3's finding).
    os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
    usage = ("usage: close_run.py begin <default-branch> [--agent <name>] [<branch>...] | "
             "finish <run-id> | resumable [--agent <name>] | awaiting [--agent <name>] | "
             "load <run-id> <default-branch> | check <run-id> <default-branch> | "
             "consume <run-id> [--restore-2b] | reader | class | "
             "eligible <default-branch> <agent> [<branch>...] | "
             "hand-off <default-branch> <branch> <PR> <pushed-from-sha> [--keep-branch] "
             "[--agent <name>] | "
             "seal <run-id> | land-check <run-id> <default-branch> [--unattended <agent>] | "
             "re-request <run-id> <default-branch> | landed <run-id> | abandon <run-id> | "
             "park <run-id> <code> <reason> | unpark <run-id> | "
             "stop <run-id> <step> <reason> [--locks-kept <id>...] | clear <run-id> | "
             "hold <run-id> <branch> <reason> | unhold <branch> [<note>]")
    if not argv:
        print(usage, file=sys.stderr)
        return 3
    cmd, rest = argv[0], argv[1:]
    try:
        root = main_root()
        if cmd == "begin" and rest:
            if rest[1:2] == ["--agent"] and len(rest) >= 3:
                return cmd_begin(root, rest[0], rest[3:], agent=rest[2])
            return cmd_begin(root, rest[0], rest[1:])
        if cmd == "resumable" and (not rest or (len(rest) == 2 and rest[0] == "--agent")):
            return cmd_resumable(root, rest[1] if rest else "")
        if cmd == "awaiting" and (not rest or (len(rest) == 2 and rest[0] == "--agent")):
            return cmd_awaiting(root, rest[1] if rest else None)
        if cmd == "finish" and len(rest) == 1:
            return cmd_finish(root, rest[0])
        if cmd in ("load", "check") and len(rest) == 2:
            return (cmd_load if cmd == "load" else cmd_check)(root, rest[0], rest[1])
        if cmd == "consume" and len(rest) in (1, 2) and rest[1:] in ([], ["--restore-2b"]):
            return cmd_consume(root, rest[0], rest[1:] == ["--restore-2b"])
        if cmd == "reader" and not rest:
            return cmd_reader(root)
        if cmd == "class" and not rest:
            return cmd_class(root)
        if cmd == "eligible" and len(rest) >= 2 and rest[2:].count("--held") <= 1:
            names = [b for b in rest[2:] if b != "--held"]
            return cmd_eligible(root, rest[0], rest[1], names, held="--held" in rest[2:])
        if cmd == "hand-off" and len(rest) >= 4:
            opts, keep, agent = rest[4:], False, ""
            while opts:
                if opts[0] == "--keep-branch" and not keep:
                    keep, opts = True, opts[1:]
                elif opts[0] == "--agent" and len(opts) >= 2 and not agent:
                    agent, opts = opts[1], opts[2:]
                else:
                    break
            if not opts:
                return cmd_hand_off(root, *rest[:4], keep_branch=keep, agent=agent)
        if cmd in ("seal", "landed", "abandon", "unpark") and len(rest) == 1:
            return {"seal": cmd_seal, "landed": cmd_landed, "abandon": cmd_abandon,
                    "unpark": cmd_unpark}[cmd](root, rest[0])
        if cmd == "land-check" and len(rest) == 4 and rest[2] == "--unattended":
            if not UNATTENDED_LAND_ENABLED:
                raise Refuse("the unattended land is switched off (UNATTENDED_LAND_ENABLED): land this hand-off "
                             f"attended, with /review-close --land {rest[0]}")
            return cmd_land_unattended(root, rest[0], rest[1], rest[3])
        if cmd in ("land-check", "re-request") and len(rest) == 2:
            return (cmd_land_check if cmd == "land-check" else cmd_re_request)(root, rest[0], rest[1])
        if cmd == "park" and len(rest) == 3:
            return cmd_park(root, *rest)
        if cmd == "stop" and len(rest) >= 3 and (len(rest) == 3 or rest[3] == "--locks-kept"):
            return cmd_stop(root, rest[0], rest[1], rest[2], rest[4:])
        if cmd == "clear" and len(rest) == 1:
            return cmd_clear(root, rest[0])
        if cmd == "hold" and len(rest) == 3:
            return cmd_hold(root, *rest)
        if cmd == "unhold" and len(rest) in (1, 2):
            return cmd_unhold(root, rest[0], rest[1] if len(rest) == 2 else "")
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    except Fail as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(usage, file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
