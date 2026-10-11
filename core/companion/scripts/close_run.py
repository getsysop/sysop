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

    begin <default-branch> [<branch>...]
        After Step 1, before Step 2a. No branch at all is a cycle of unpushed commits only. Creates the run and records, per branch:
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

`begin`, `load` and `reader` also refuse (exit 2) while a hand-off below is waiting.

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

The unattended land (`Q-411`, Phase 366) reads CLAUDE.md `## Unattended close
class`: `allow:` and `exclude:` path globs and a `blast_radius:` ceiling. CLAUDE.md,
.claude/**, sysop/** and .github/workflows/** are always excluded, as are tasks
that are manual_smoke, solo or user_action, and a branch with a held pending doc.

    class
        Validates the class and prints it, with a `WARN:` line for each path a
        close commits itself that the class does not admit. Exit 2: missing or
        malformed.

    eligible <default-branch> <agent> [<branch>...]
        Half A's selection, after Step 1: one `IN <branch>: ...` or
        `OUT <branch>: <reasons>` line per branch. A branch is IN only when one
        lock names it and reads `agent: <agent>`, its task passes the class, no
        pending doc of its carries `hold:`, and every path it changes since its
        merge base with <default-branch> is admitted. A `NOTE:` line names paths
        local <default-branch>'s unpushed commits add that the class refuses.

    hand-off ... --agent <name>
        Records the hand-off as landable unattended by <name>; refuses without a
        valid class.

    land-check <run-id> <default-branch> --unattended <agent>
        NOT ENABLED: refuses (exit 2) until `Q-411`'s redesign; see UNATTENDED_LAND_ENABLED.
        Half B with no human. Refuses (exit 2) a hand-off made without --agent, or
        by another agent. A `PARKED` hand-off prints its park and exits 4 without
        reading GitHub. Otherwise re-checks the PR, then the class against the PR
        (every path between origin/<default-branch> and the recorded head, the kept
        tasks at the head, their locks' owner, no held-doc branch in report.md), then
        the reviewer, then the PR's check count. Any park writes `PARKED` (exit 4).
        A check count of 0 waits (exit 5) for the hand-off's timeout, counted from
        the first land that found the reviewer clean, then parks.

    park <run-id> <code> <reason>
        The runner's own parks under --unattended (a denied command, a stuck PR).

    unpark <run-id>
        A human clears a park without a new request. `re-request`, `landed` and
        `abandon` clear it too.

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


def cmd_begin(root: Path, default: str, branches: list[str]) -> int:
    if not default or default.startswith("<"):
        print("usage: close_run.py begin <default-branch> [<branch>...]", file=sys.stderr)
        return 3
    if not ref_sha(root, "refs/heads/" + default):
        raise Fail(f"default branch {default!r} does not resolve")
    if awaiting(root):
        raise Refuse(f"a hand-off is waiting for its second reader: {', '.join(awaiting(root))}")
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
    print(f"RESUME: /review-close --resume {run_id}")
    return 0


def cmd_load(root: Path, run_id: str, default: str) -> int:
    run, manifest = open_run(root, run_id, default)
    resumable(run, manifest)
    if awaiting(root):
        raise Refuse(f"a hand-off is waiting for its second reader: {', '.join(awaiting(root))}")
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


def read_second_reader(root: Path) -> dict:
    """`## Second reader` in the project's CLAUDE.md, as `key: value` lines."""
    cfg: dict[str, str] = dict(section_pairs(root, "Second reader", READER_KEYS))
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
        print(f"NOT KEPT: no lock file for {' '.join(gone)} (was Step 4c's heredoc run with --keep-locks?)")
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
    write_json(run / "handoff.json", rec)
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
# The unattended land (`Q-411`, Phase 366). A hand-off made with `--agent <name>` may be landed
# by `land-check --unattended <name>`, with no human: only when the consumer's
# `## Unattended close class` admits every task and every path the PR merges, the reviewer
# reads clean, and checks registered. Anything else parks durably (`PARKED`), and a parked
# hand-off waits for a human: `re-request`, `unpark` or an attended `--land`.
# ---------------------------------------------------------------------------------------------

CLASS_TITLE = "Unattended close class"
CLASS_KEYS = ("allow", "exclude", "blast_radius")
BLAST_ORDER = ("single-file", "single-module", "cross-module", "architectural")
# The files that govern an unattended merge: the class, the reader and the merge policy
# (CLAUDE.md), the permissions and skills (.claude/), the scripts that run the gate (sysop/),
# and CI. Never configurable (Wade, 2026-10-08).
FIXED_EXCLUDE = ("CLAUDE.md", ".claude/**", "sysop/**", ".github/workflows/**")
# Paths a close commits itself (Steps 1b, 4b and 4c). The class must allow them, or every
# land parks; `class` and `eligible` warn about each one it does not.
CLOSE_WRITTEN = ("tasks/index.yml", "tasks/open/TASK-0001.md", "tasks/archive/TASK-0001.md",
                 "PROJECT_STATUS.md", "CHANGELOG.md", "UI_Iterations.md", "review_tasks.md",
                 "review_tasks_archive.md")
PARK_CODES = ("ask", "relay", "hard-fail", "gate-red", "conflict", "class", "reader", "checks",
              "pr-state", "dirty", "after-push")
AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}")  # claim_task.sh's AGENT_NAME rule
# The unattended land is built but NOT enabled (Wade, 2026-10-08, after Phase 366's third round):
# each of three rounds found a way for a PR or the agent to shape what this gate trusts, the last
# two (task fields read at local <default>, which the agent writes; a symlink routing an edit to
# CLAUDE.md or .claude/ around FIXED_EXCLUDE) still open. `land-check --unattended` refuses until
# `Q-411`'s redesign. The tests flip this in-process to keep the mechanism exercised; nothing in
# the shipped CLI sets it.
UNATTENDED_LAND_ENABLED = False


def glob_regex(pat: str, icase: bool = False) -> re.Pattern:
    """A repo-root-anchored path glob: `*` and `?` stay inside one segment, a `**` segment
    matches any number of segments, a trailing `/**` (or `/`) covers the directory's own path
    too, and `icase` matches without regard to case."""
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
        out += "" if last else "/"
    return re.compile(out + r"\Z", re.S | (re.I if icase else 0))


def read_class(root: Path, rev: str = "") -> dict:
    """`## Unattended close class`: `allow:` and `exclude:` (repeatable, space-separated globs)
    and `blast_radius:` (the highest blast radius that may merge unattended). Exclusions match
    without regard to case, because a case-insensitive filesystem writes `.CLAUDE/x` into
    `.claude/`; allows match exactly, which can only refuse more."""
    pairs = section_pairs(root, CLASS_TITLE, CLASS_KEYS, repeatable=("allow", "exclude"), rev=rev)
    cls: dict = {"allow": [], "exclude": [], "ceiling": ""}
    for key, value in pairs:
        if key == "blast_radius":
            if value not in BLAST_ORDER:
                raise Refuse(f"`## {CLASS_TITLE}`: blast_radius must be one of "
                             f"{', '.join(BLAST_ORDER)}: {value!r}")
            cls["ceiling"] = value
        else:
            cls[key] += [(p, glob_regex(p, icase=key == "exclude")) for p in value.split()]
    if not cls["allow"]:
        raise Refuse(f"`## {CLASS_TITLE}`: allow is required (the paths that may merge unattended)")
    if not cls["ceiling"]:
        raise Refuse(f"`## {CLASS_TITLE}`: blast_radius is required")
    cls["fixed"] = [(p, glob_regex(p, icase=True)) for p in FIXED_EXCLUDE]
    return cls


def path_problem(cls: dict, path: str) -> str:
    for pat, rx in cls["fixed"]:
        if rx.match(path):
            return f"{path} (always excluded: {pat})"
    for pat, rx in cls["exclude"]:
        if rx.match(path):
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


def paths_problems(cls: dict, paths: list[str]) -> list[str]:
    bad = [b for b in (path_problem(cls, p) for p in paths) if b]
    if len(bad) > 5:
        bad = bad[:5] + [f"and {len(bad) - 5} more"]
    return bad


def cmd_class(root: Path) -> int:
    print_class(read_class(root), root)
    return 0


def cmd_eligible(root: Path, default: str, agent: str, branches: list[str]) -> int:
    """Half A's selection: one `IN` or `OUT` line per branch. An OUT branch is set aside."""
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
        tip = ref_sha(root, "refs/heads/" + branch)
        if not tip:
            print(f"OUT {branch}: no such branch")
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
        _, base = git(root, "merge-base", "refs/heads/" + default, tip)
        paths = diff_paths(root, base.strip(), tip)
        bad = paths_problems(cls, paths)
        if bad:
            problems.append("paths outside the class: " + "; ".join(bad))
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


def unattended_class_problems(root: Path, run: Path, rec: dict, agent: str, base_oid: str) -> list[str]:
    """The class re-read against what the PR merges: every path between the default branch's
    live tip (which the caller has checked equals local origin) and the recorded head, every
    kept task at the pushed-from commit and at the head, its lock's owner, and no held doc.
    The pushed-from commit is local <default>, which the agent's own unpushed commits can have
    written (round 3): one reason this land is not enabled. The class is read from that tip's CLAUDE.md, which an unattended
    merge can never change, not from the working tree. A stale ref is not used: an older merge
    base can hide a branch reverting a file to its older content."""
    out: list[str] = []
    head = rec["head"]
    origin = base_oid
    try:
        cls = read_class(root, rev=origin)
    except Refuse as e:
        return [str(e)]
    if not ref_sha(root, head):
        return [f"the recorded head {head} is not in this repository"]
    _, base = git(root, "merge-base", origin, head)
    bad = paths_problems(cls, diff_paths(root, base.strip(), head))
    if bad:
        out.append("paths outside the class: " + "; ".join(bad))
    if not rec["kept_locks"]:
        out.append("the hand-off kept no task lock, so no task of this agent's is in it")
    tasks = tasks_at(root, head)
    have_pushed = bool(ref_sha(root, rec["pushed_from"]))
    pushed = tasks_at(root, rec["pushed_from"]) if have_pushed else None
    if not have_pushed:
        out.append(f"the pushed-from commit {rec['pushed_from'][:10]} is not in this repository")
    elif tasks is None or pushed is None:
        out.append("tasks/index.yml at the head or at the pushed-from commit cannot be read "
                   "(a parse failure, or one id named twice)")
    for tid in rec["kept_locks"]:
        if tasks is not None and pushed is not None:
            out += [f"at the pushed-from commit: {p}" for p in task_problems(cls, tid, pushed.get(tid))]
            out += [f"at the head: {p}" for p in task_problems(cls, tid, tasks.get(tid))]
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


def cmd_land_unattended(root: Path, run_id: str, default: str, agent: str) -> int:
    run, rec = open_handoff(root, run_id, default)
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
        print("VERDICT: PARK")
        return 4

    def stop(code: str, lines: list[str]) -> int:
        park(run, rec, code, lines)
        for line in lines:
            print(f"READER: {line}")
        print(f"PARKED: {code}")
        print("VERDICT: PARK")
        return 4

    data = pr_view(root, rec["pr"])
    state = data.get("state")
    if state == "MERGED":
        if data.get("headRefOid") != rec["head"]:
            print(f"READER: merged at {data.get('headRefOid')}, not the recorded head {rec['head']}: "
                  "merged outside this gate, by someone, unread by the second reader")
        print("VERDICT: ALREADY MERGED")
        return 0
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
    # The tip the squash lands on, as GitHub has it now. The PR's `baseRefOid` is the base as of
    # the PR's last head update, which can lag this (round 2), and a class change a human pushes
    # in the gap must count. Local origin must be that tip, or the diff
    # and the class would be read at another commit.
    default = rec["default_branch"]
    ref = gh_json(root, "api", f"repos/{{owner}}/{{repo}}/git/ref/heads/{default}")
    tip = str(ref.get("object", {}).get("sha") or "") if isinstance(ref, dict) \
        and isinstance(ref.get("object"), dict) else ""
    if not SHA.fullmatch(tip):
        return stop("pr-state", [f"GitHub reported no tip for {default}: {tip!r}"])
    local_origin = ref_sha(root, "refs/remotes/origin/" + default)
    if local_origin != tip:
        print(f"READER: origin/{default} here is {local_origin[:10] or 'absent'} and GitHub's is "
              f"{tip[:10]}; fetch origin {default} and land again")
        print("VERDICT: WAIT")
        return 5
    problems = unattended_class_problems(root, run, rec, agent, tip)
    if problems:
        return stop("class", ["outside the unattended class: " + p for p in problems])
    # Step 6's two conditions, read before the merge (Wade, round 1): after it the hand-off is
    # gone and a stop strands local <default>. Both are local reads.
    _, dirty = git(root, "diff", "--name-only", "HEAD", "--")
    if dirty.strip():
        return stop("dirty", ["the main checkout has uncommitted changes to tracked files, which "
                              "Step 6's reset would discard: " + ", ".join(dirty.split()[:10])])
    local = ref_sha(root, "refs/heads/" + rec["default_branch"])
    if not local:
        return stop("hard-fail", [f"local {rec['default_branch']} does not resolve"])
    _, after = git(root, "rev-list", f"{rec['pushed_from']}..{local}",
                   "^refs/remotes/origin/" + rec["default_branch"])
    if after.split():
        return stop("after-push", [f"local {rec['default_branch']} has {len(after.split())} commit(s) "
                                   f"made after the push, which Step 6's reset would drop: "
                                   + ", ".join(c[:10] for c in after.split()[:10])])
    verdict, lines = reader_verdict(
        rec,
        gh_list(root, f"repos/{{owner}}/{{repo}}/pulls/{rec['pr']}/reviews"),
        gh_list(root, f"repos/{{owner}}/{{repo}}/pulls/{rec['pr']}/comments"),
        gh_list(root, f"repos/{{owner}}/{{repo}}/issues/{rec['pr']}/comments"),
        gh_list(root, f"repos/{{owner}}/{{repo}}/issues/{rec['pr']}/reactions"),
        utcnow())
    if verdict == "park":
        return stop("reader", lines)
    for line in lines:
        print(f"READER: {line}")
    if verdict == "wait":
        print("VERDICT: WAIT")
        return 5
    # Checks: command 4b's count, read here so a count of 0 waits instead of stopping. The
    # clock starts at the first land that read the reviewer clean and counted none, and runs
    # for the hand-off's timeout: registration latency gets a whole window of its own.
    roll = gh_json(root, "pr", "view", rec["pr"], "--json", "statusCheckRollup")
    checks = roll.get("statusCheckRollup") if isinstance(roll, dict) else None
    checks = checks if isinstance(checks, list) else []
    count = len(checks)
    failed, pending = check_states(checks)
    if failed:
        return stop("checks", [f"a check did not pass: {f}" for f in failed])
    if count == 0 or pending:
        since = parse_time(rec.get("checks_waiting_since"))
        if since is None:
            since = utcnow()
            rec["checks_waiting_since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            write_json(run / "handoff.json", rec)
        deadline = since + datetime.timedelta(seconds=timeout_seconds(rec["timeout"]) or 0)
        what = (f"{len(pending)} check(s) still running: {', '.join(pending[:5])}" if pending
                else "no check registered on the PR")
        if utcnow() > deadline:
            return stop("checks", [f"{what} at {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')} (counting "
                                   f"from {rec['checks_waiting_since']}, timeout {rec['timeout']})"])
        print(f"READER: {what}; parks at {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        print("VERDICT: WAIT")
        return 5
    print(f"CHECKS: {count}")
    print("VERDICT: MERGE")
    return 0


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
    park(run, rec, code, [reason.strip()])
    print(f"PARKED: {run_id} ({code})")
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
    write_json(run / "handoff.json", rec)
    print(f"UNPARKED: {run_id}")
    return 0


def main(argv: list[str]) -> int:
    usage = ("usage: close_run.py begin <default-branch> [<branch>...] | finish <run-id> | "
             "load <run-id> <default-branch> | check <run-id> <default-branch> | "
             "consume <run-id> [--restore-2b] | reader | class | "
             "eligible <default-branch> <agent> [<branch>...] | "
             "hand-off <default-branch> <branch> <PR> <pushed-from-sha> [--keep-branch] "
             "[--agent <name>] | "
             "seal <run-id> | land-check <run-id> <default-branch> [--unattended <agent>] | "
             "re-request <run-id> <default-branch> | landed <run-id> | abandon <run-id> | "
             "park <run-id> <code> <reason> | unpark <run-id>")
    if not argv:
        print(usage, file=sys.stderr)
        return 3
    cmd, rest = argv[0], argv[1:]
    try:
        root = main_root()
        if cmd == "begin" and rest:
            return cmd_begin(root, rest[0], rest[1:])
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
        if cmd == "eligible" and len(rest) >= 2:
            return cmd_eligible(root, rest[0], rest[1], rest[2:])
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
                raise Refuse("the unattended land is not enabled (Q-411): land this hand-off "
                             f"attended, with /review-close --land {rest[0]}")
            return cmd_land_unattended(root, rest[0], rest[1], rest[3])
        if cmd in ("land-check", "re-request") and len(rest) == 2:
            return (cmd_land_check if cmd == "land-check" else cmd_re_request)(root, rest[0], rest[1])
        if cmd == "park" and len(rest) == 3:
            return cmd_park(root, *rest)
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
