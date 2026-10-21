#!/usr/bin/env python3
"""close_arms.py — the trigger receipt behind `/review-close`'s step files (`Q-409` P2).

Some of `/review-close`'s text lives in step files under the skill's `steps/` directory
instead of `SKILL.md`, and the runner reads one only when its arm fires. A `Read` leaves
nothing a later step can check, so a command decides each trigger and records that the arm
became due, and each arm's first command records its load with a digest of the arm file the
runner was handed, checked against that file. Step 8's `check` then names every arm that was
due and never loaded. The skill text is the contract: each step says what the output and
each exit mean.

The receipt is `sysop/runtime/close-arms/<close-id>.tsv` in the MAIN checkout (resolved
through git-common-dir, like the other runtime readers, so every linked worktree finds the
same one). It is append-only, one tab-separated record per line, and a line of any other
shape makes the receipt unreadable:

    begin     <utc>
    policy    <direct|pr>  <source>
    required  <arm-id>     <utc>
    loaded    <arm-id>     <digest>  <utc>
    checked   <utc>        <ok | missing N>

Subcommands (each prints one line per fact):

    begin <flags> <arm-id>...
        Before the flag sections and Step 1, from the main checkout's top level. `<flags>` is
        one argument: the invocation's flags, each with its value, space-separated, or empty.
        The arm ids are every arm the skill's `SKILL.md` marks. Prints `CLOSE: <close-id>`,
        then `ARM: prepare-resume` when the flags hold `--prepare` or `--resume`,
        `ARM: request-review-land` when they hold `--request-review` or `--land`, and
        `ARM: 4d-pr` as well under `--land`, which runs Step 4d's `pr` commands without
        reaching Step 4d; each is recorded `required`. With none of those, `ARM: none`.
        Exit 2, creating nothing: a flag it does not know, a flag without its value or given
        twice, a combination the skill does not run (`FLAG_SETS`), `--request-review`,
        `--land` or `--agent` under a merge policy other than `pr`, arms that are not the ones this script
        knows (the skill and `sysop/scripts/` are from different versions), or a merge policy
        `policy` would refuse. Each stops the close before any step that changes a worktree.
        Also removes receipts
        older than 30 days that have nothing left to report: a Step 8 checked them, or they
        hold no arm required and never loaded. An unchecked receipt with an unloaded arm, or
        one that cannot be read, stays until a human deletes it.
    policy <close-id>
        Step 4-pre. Reads `## Merge policy` from the `CLAUDE.md` at the top level of the
        checkout it runs in, records it, and prints `POLICY: <direct|pr>` and `SOURCE: <why>`.
        The read: fenced lines skipped; the first word of the first non-blank line after the
        heading, split on spaces and tabs, backticks and emphasis marks dropped, lower-cased;
        `direct` when the file, the section or its word is absent. It refuses a word other
        than `direct` or `pr`, and any other heading that starts with the words
        (`## Merge policy: pr`, `### Merge Policy`, `## Merge policy — pr`, and an unrelated
        `### Merge policy history`, which the message says to rename).
        Exit 2, recording nothing: either refusal. A close must not push `main` on a guess.
    read-policy <dir>
        The same read of `<dir>/CLAUDE.md`, recording nothing: prints the policy, or exits 2
        with the refusal. `close_batch.sh` reads the policy through it, so there is one reader.
    arm <close-id> <step>
        Where the arm a step runs follows from a recorded fact. Today one step, `4d`: under
        the latest recorded policy `direct` it records `required 4d-direct` and prints
        `ARM: 4d-direct`; under `pr`, `required 4d-pr` and `ARM: 4d-pr`. Exit 2: no policy
        recorded.
    conflicts <close-id>
        Step 4a item 4, at each stop of a merge or rebase. Prints
        `CONFLICTED: <path>` per path git left unmerged (`CONFLICTED: none` for none). When
        one is a Sysop-written shared append file (`tasks/index.yml`, `review_tasks.md`, or any
        `.md` under `tasks/`, the task bodies among them) it records
        `required 4a-append` and prints `ARM: 4a-append`; otherwise `ARM: none`. Exit 2: git
        could not list the unmerged paths.
    notes <close-id> <count>
        Step 4a-fix, after the merges: `<count>` is the number of notes Step 2b collected,
        one per bullet under a `NOTES:` block (`NOTES: none` is 0). Above 0 it records `required 4a-fix` and prints `ARM: 4a-fix`; at 0 it
        prints `ARM: none`. Exit 2: the count is not a whole number.
    exited <close-id> <arm-id> <code>
        Where an arm's trigger is a command's exit code, run after that command with the code
        written out. Today one step's two arms (`EXIT_ARMS`): Step 3b's collect
        (`3b-collect-exit`) and its `git worktree remove` (`3b-rollback`). A code other than 0
        records `required <arm-id>` and prints `ARM: <arm-id>`; 0 prints `ARM: none`. Exit 2,
        recording nothing: an arm `EXIT_ARMS` does not hold, or a code that is not a whole
        number from 0 to 255.
    loaded <close-id> <arm-id> <digest> <skill-dir>
        An arm file's first command. Records the load when `<digest>` is the digest of
        `<skill-dir>/steps/<arm-id>.md`: the first 16 hex of the sha256 of its text with this
        line left out, and every line carrying a `<!-- sysop:role=... -->` marker, whose model
        and effort the install-time resolver rewrites to the consumer's mapping. Exit 2, recording nothing: the arm is unknown, the file is missing,
        or the digest is not that file's.
    check <close-id> [<skill-dir>]
        Step 8. Prints `ARMS: required <n>, loaded <n>` and one `ARM NOT LOADED: <arm-id>`
        per arm required and never loaded. With the skill's directory it also prints what
        the run paid: `CORE: <bytes>` (`SKILL.md`), `LOADED: <arm-id> <bytes>` per arm
        loaded, and `SHARED: <file> <bytes>` per shared file the core reads on every close
        that lands. Exit 1 when an arm is named: the receipt stays, recorded as checked.
        Exit 0: the receipt is removed, since Step 8 carries its lines.
    unchecked [--hours <h>]
        For `self_check.sh`: one `UNCHECKED: <close-id> <arm-id>` line per receipt older
        than <h> hours (default 24) that no `check` read and that holds a required arm no
        `loaded` matched, and one `UNREADABLE: <file> (<why>)` per receipt that cannot be
        read. Prints nothing when there is neither, or no receipt directory.

Exit 2 also covers a malformed close id, a missing receipt, and not being in a repository.
"""
import datetime
import hashlib
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

# The arms this script knows. `begin` refuses a skill that marks any other set.
ARMS = frozenset({"3b-collect-exit", "3b-rollback", "4a-append", "4a-fix", "4d-direct",
                  "4d-pr", "prepare-resume", "request-review-land"})
# (step, recorded policy) -> the arm that step runs.
ARM_FOR = {
    ("4d", "direct"): "4d-direct",
    ("4d", "pr"): "4d-pr",
}
# The flags `/review-close` takes. A value flag's next word is its value.
VALUE_FLAGS = {"--resume", "--land", "--agent"}
FLAGS = VALUE_FLAGS | {"--dry-run", "--prepare", "--request-review", "--unattended",
                       "--skip-permission-guard"}
# The combinations the skill runs, `--skip-permission-guard` aside, which goes with any.
FLAG_SETS = {frozenset(s) for s in (
    (), ("--dry-run",), ("--prepare",), ("--prepare", "--agent"), ("--resume",),
    ("--resume", "--request-review"), ("--resume", "--request-review", "--agent"),
    ("--resume", "--request-review", "--agent", "--unattended"),
    ("--request-review",), ("--request-review", "--agent"),
    ("--land",), ("--land", "--agent", "--unattended"),
)}
# flag -> the flag arm it makes due, in the order `begin` prints them.
FLAG_ARMS = (("--prepare", "prepare-resume"), ("--resume", "prepare-resume"),
             ("--request-review", "request-review-land"), ("--land", "request-review-land"),
             ("--land", "4d-pr"))
# A value's shape: a run id (`close_run.py`'s) or an agent name (`claim_task.sh`'s rule).
VALUE = {"--resume": re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}"),
         "--land": re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}"),
         "--agent": re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}")}
# The arms `conflicts` and `notes` make due.
CONFLICT_ARM = "4a-append"
NOTES_ARM = "4a-fix"
# The arms `exited` makes due: each one's trigger is a command's non-zero exit.
EXIT_ARMS = frozenset({"3b-collect-exit", "3b-rollback"})
ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{4}")
LOADED_LINE = re.compile(r"close_arms\.py loaded ")
# `resolve_skill_models.py` rewrites the pin on a line carrying this marker (`_model_roles.py`
# `_PIN_MARKER_RE`), so the digest cannot include it or a consumer's role override would make
# every load a mismatch.
ROLE_LINE = re.compile(r"<!--\s*sysop:role=")


class Refuse(Exception):
    """Exit 2 with the message."""


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def rev_parse(flag: str) -> Path:
    p = subprocess.run(["git", "rev-parse", flag], capture_output=True, env=GIT_ENV)
    out = os.fsdecode(p.stdout).strip()
    if p.returncode != 0 or not out:
        raise Refuse("not inside a git repository")
    found = Path(out)
    return found if found.is_absolute() else (Path.cwd() / found).resolve()


def main_root() -> Path:
    """Where runtime state lives: the parent of the git common directory, as every other
    runtime reader resolves it (`close_run.py`, `sitrep_survey.py`, `self_check.sh`)."""
    return rev_parse("--git-common-dir").parent


def top_level() -> Path:
    """Where `CLAUDE.md` is read: the top level of the checkout the command runs in, as
    `close_batch.sh` reads it. The common directory's parent is not the repository under
    `--separate-git-dir` or in a submodule, and a `pr` policy read from there is `direct`."""
    return rev_parse("--show-toplevel")


def receipts(root: Path) -> Path:
    return root / "sysop" / "runtime" / "close-arms"


def receipt(close_id: str, must_exist: bool = True) -> Path:
    if not ID.fullmatch(close_id):
        raise Refuse(f"{close_id!r} is not a close id: substitute the one `begin` printed")
    p = receipts(main_root()) / f"{close_id}.tsv"
    if must_exist and not p.is_file():
        raise Refuse(f"no receipt for {close_id}: `begin` did not run in this "
                     "repository, or the id is not this close's")
    return p


def append(p: Path, *fields: str) -> None:
    with open(p, "a", encoding="utf-8") as f:
        f.write("\t".join(fields) + "\n")


# record kind -> its field count, the kind included.
SHAPES = {"begin": 2, "policy": 3, "required": 3, "loaded": 4, "checked": 3}


class Vanished(Exception):
    """The receipt was removed after it was listed: a concurrent Step 8 or prune."""


def records(p: Path) -> list:
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise Vanished(p.name) from e
    except (OSError, UnicodeDecodeError) as e:
        raise Refuse(f"receipt {p.name} could not be read ({type(e).__name__}: {e})") from e
    out = []
    for n, ln in enumerate(text.split("\n"), 1):
        if not ln and n == text.count("\n") + 1:
            break
        r = ln.split("\t")
        if SHAPES.get(r[0]) != len(r) or not all(r):
            raise Refuse(f"receipt {p.name} is damaged at line {n}: {ln[:60]!r}")
        out.append(r)
    return out


# Any heading that starts with the words. Narrowing it to the forms that name the setting was
# tried in Phase 388 and its third round found `## Merge policy — pr` read as no section, so
# `direct`: a refusal is loud and a wrong `direct` pushes `main`. An unrelated heading such as
# `### Merge policy history` is refused too, and the message says to rename it.
HEADING = re.compile(r"[ \t]{0,3}#{1,6}[ \t]*merge[ \t]+policy\b", re.I)
FENCE = re.compile(r"[ \t\f\v]*(```|~~~)")


def read_policy(root: Path) -> tuple:
    """`(policy, why)`, or `("", why)` for a refusal. See `policy` above for the rules."""
    f = root / "CLAUDE.md"
    try:
        # Bytes, decoded with `replace`: an undecodable byte elsewhere in a consumer's
        # CLAUDE.md must not change the answer.
        text = f.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return "direct", "no readable CLAUDE.md"
    fence = found = False
    for ln in re.split(r"\r\n|\r|\n", text):   # CommonMark's line endings
        if FENCE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        words = [w for w in re.split(r"[ \t]+", ln) if w]
        if found and words:
            word = re.sub(r"[`*_]", "", words[0]).lower()
            if word in ("direct", "pr"):
                return word, "declared in CLAUDE.md ## Merge policy"
            if words[0].startswith("#"):
                return "direct", "## Merge policy in CLAUDE.md is empty; default direct"
            return "", f"## Merge policy in CLAUDE.md holds {words[0]!r}, not direct or pr"
        if found:
            continue
        if re.fullmatch(r"## Merge policy[ \t]*", ln):
            found = True
        elif HEADING.match(ln):
            return "", (f"CLAUDE.md has the heading {ln.strip()!r}. If it is the merge policy, "
                        "write the heading as exactly `## Merge policy` with `direct` or `pr` "
                        "below it; if it is about something else, rename it so it does not start "
                        "with the words `Merge policy`")
    return "direct", "no ## Merge policy in CLAUDE.md; default direct"


def digest_of(text: str) -> str:
    kept = [ln for ln in text.split("\n")
            if not LOADED_LINE.search(ln) and not ROLE_LINE.search(ln)]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()[:16]


PRUNE_DAYS = 30


def parse_flags(text: str) -> dict:
    """`{flag: value or ""}` for `begin`'s `<flags>` argument, or a refusal."""
    words = text.split()
    out: dict = {}
    i = 0
    while i < len(words):
        w = words[i]
        if w not in FLAGS:
            raise Refuse(f"{w!r} is not a /review-close flag: write out only the flags the "
                         f"invocation gave, each with its value ({' '.join(sorted(FLAGS))})")
        if w in out:
            raise Refuse(f"{w} is given twice")
        value = ""
        if w in VALUE_FLAGS:
            value = words[i + 1] if i + 1 < len(words) else ""
            if not VALUE[w].fullmatch(value):
                raise Refuse(f"{w} takes a value and {value!r} is not one: "
                             + ("a run id, `<yyyymmdd>T<hhmmss>Z-<4 hex>`" if w != "--agent"
                                else "an agent name"))
            i += 1
        out[w] = value
        i += 1
    if frozenset(out) - {"--skip-permission-guard"} not in FLAG_SETS:
        raise Refuse(f"/review-close does not run with the flags {' '.join(sorted(out))}. "
                     "It runs with no flags, --dry-run, --prepare [--agent <name>], "
                     "--resume <run-id> [--request-review [--agent <name> [--unattended]]], "
                     "--request-review [--agent <name>], or --land <run-id> "
                     "[--unattended --agent <name>]; --skip-permission-guard goes with any")
    return out


def cmd_begin(args: list) -> int:
    if not args:
        raise Refuse("usage: begin <flags> <arm-id>...")
    if args[0] in ARMS:
        raise Refuse("begin takes the flags first, as one argument (\"\" for none), then the "
                     "arm ids. If the skill's `begin` line has `\"<flags>\"`, write it out; if it "
                     "has none, the skill and sysop/scripts/ are from different versions: run "
                     "sysop/scripts/sysop-update.sh, then the close")
    flags, arms = parse_flags(args[0]), args[1:]
    if set(arms) != ARMS or len(arms) != len(ARMS):
        raise Refuse(f"the skill marks arms {sorted(arms)} and this close_arms.py knows "
                     f"{sorted(ARMS)}: the skill and sysop/scripts/ are from different "
                     "versions. Run sysop/scripts/sysop-update.sh, then the close")
    policy, why = read_policy(top_level())
    if not policy:
        raise Refuse(why)
    if policy != "pr" and {"--request-review", "--land", "--agent"} & set(flags):
        raise Refuse(f"--request-review, --land and --agent need `## Merge policy` `pr` in CLAUDE.md, "
                     f"and it reads {policy} ({why})")
    due = list(dict.fromkeys(arm for flag, arm in FLAG_ARMS if flag in flags))
    close_id = f"{utc()}-{secrets.token_hex(2)}"
    p = receipt(close_id, must_exist=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in sorted(p.parent.glob("*.tsv")):
        try:
            if (now - old.stat().st_mtime) / 86400 < PRUNE_DAYS:
                continue
            recs = records(old)
            if missing_arms(recs) and not any(r[0] == "checked" for r in recs):
                continue
            old.unlink()
        except (OSError, Refuse, Vanished):
            continue
    append(p, "begin", utc())
    for arm in due:
        append(p, "required", arm, utc())
    print(f"CLOSE: {close_id}")
    for arm in due or ["none"]:
        print(f"ARM: {arm}")
    return 0


def cmd_policy(args: list) -> int:
    if len(args) != 1:
        raise Refuse("usage: policy <close-id>")
    p = receipt(args[0])
    policy, source = read_policy(top_level())
    if not policy:
        raise Refuse(source)
    append(p, "policy", policy, source)
    print(f"POLICY: {policy}")
    print(f"SOURCE: {source}")
    return 0


def cmd_read_policy(args: list) -> int:
    if len(args) != 1:
        raise Refuse("usage: read-policy <dir>")
    policy, why = read_policy(Path(args[0]))
    if not policy:
        raise Refuse(why)
    print(policy)
    return 0


def cmd_arm(args: list) -> int:
    if len(args) != 2:
        raise Refuse("usage: arm <close-id> <step>")
    if args[1] not in {step for step, _ in ARM_FOR}:
        raise Refuse(f"unknown step {args[1]!r}: the steps with arms are "
                     f"{sorted({step for step, _ in ARM_FOR})}")
    p = receipt(args[0])
    policies = [r[1] for r in records(p) if r[0] == "policy" and len(r) > 1]
    if not policies:
        raise Refuse(f"no policy recorded for {args[0]}: run Step 4-pre's "
                     "`close_arms.py policy` first")
    arm = ARM_FOR.get((args[1], policies[-1]))
    if arm is None:
        print("ARM: none")
        return 0
    append(p, "required", arm, utc())
    print(f"ARM: {arm}")
    return 0


def shared_append(path: str) -> bool:
    """A path whose conflict `steps/4a-append.md` resolves: `tasks/index.yml`,
    `review_tasks.md`, and any `.md` under `tasks/`, which takes in the body files that
    conflict beside their index entries. Over-matching costs one read of the arm."""
    return path in ("tasks/index.yml", "review_tasks.md") or (
        path.startswith("tasks/") and path.endswith(".md"))


def cmd_conflicts(args: list) -> int:
    if len(args) != 1:
        raise Refuse("usage: conflicts <close-id>")
    p = receipt(args[0])
    # `--no-relative`: a consumer's `diff.relative` would list only the paths under the
    # directory the command runs in, and hide a shared file's conflict.
    g = subprocess.run(["git", "diff", "--name-only", "--no-relative", "--diff-filter=U", "-z"],
                       capture_output=True, env=GIT_ENV)
    if g.returncode != 0:
        raise Refuse("git could not list the unmerged paths: "
                     f"{os.fsdecode(g.stderr).strip() or 'exit ' + str(g.returncode)}")
    paths = list(dict.fromkeys(x for x in g.stdout.split(b"\0") if x))
    arm = CONFLICT_ARM if any(shared_append(os.fsdecode(x)) for x in paths) else None
    if arm:
        append(p, "required", arm, utc())
    # Bytes, as git gave them: a path that is not UTF-8 must not stop the report.
    out = sys.stdout.buffer
    for path in paths:
        out.write(b"CONFLICTED: " + path + b"\n")
    if not paths:
        out.write(b"CONFLICTED: none\n")
    out.write(f"ARM: {arm or 'none'}\n".encode())
    out.flush()
    return 0


def cmd_notes(args: list) -> int:
    if len(args) != 2:
        raise Refuse("usage: notes <close-id> <count>")
    p = receipt(args[0])
    if not re.fullmatch(r"[0-9]+", args[1]):
        raise Refuse(f"{args[1]!r} is not a count: write out the number of notes Step 2b "
                     "collected, one per bullet under a NOTES: block")
    if int(args[1]) == 0:
        print("ARM: none")
        return 0
    append(p, "required", NOTES_ARM, utc())
    print(f"ARM: {NOTES_ARM}")
    return 0


def cmd_exited(args: list) -> int:
    if len(args) != 3:
        raise Refuse("usage: exited <close-id> <arm-id> <code>")
    close_id, arm, code = args
    if arm not in EXIT_ARMS:
        raise Refuse(f"unknown arm {arm!r}: the arms an exit code makes due are "
                     f"{sorted(EXIT_ARMS)}")
    if not re.fullmatch(r"[0-9]{1,3}", code) or int(code) > 255:
        raise Refuse(f"{code!r} is not an exit code: write out the number the command "
                     "exited with, 0 to 255")
    p = receipt(close_id)
    if int(code) == 0:
        print("ARM: none")
        return 0
    append(p, "required", arm, utc())
    print(f"ARM: {arm}")
    return 0


def cmd_loaded(args: list) -> int:
    if len(args) != 4:
        raise Refuse("usage: loaded <close-id> <arm-id> <digest> <skill-dir>")
    close_id, arm, digest, skill = args
    p = receipt(close_id)
    if arm not in ARMS:
        raise Refuse(f"unknown arm {arm!r}")
    step = Path(skill) / "steps" / f"{arm}.md"
    try:
        text = step.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Refuse(f"{step} could not be read ({type(e).__name__}): write the skill "
                     "directory the stub in SKILL.md named in place of <skill directory>") from e
    if digest != digest_of(text):
        raise Refuse(f"DIGEST MISMATCH for {arm}: {digest!r} is not the digest of {step}. "
                     "Either the line was not copied from that file, or the file was edited "
                     "after it shipped; `sysop/scripts/sysop-update.sh` restores it")
    append(p, "loaded", arm, digest, utc())
    print(f"LOADED: {arm}")
    return 0


def missing_arms(recs: list) -> list:
    loaded = {r[1] for r in recs if r[0] == "loaded" and len(r) > 1}
    out = []
    for r in recs:
        if r[0] == "required" and len(r) > 1 and r[1] not in loaded and r[1] not in out:
            out.append(r[1])
    return out


# Shared files the core reads on every close that lands (Step 4d's push).
SHARED = ("_shared/main-push-guard.md",)


def size(p: Path) -> str:
    try:
        return str(p.stat().st_size)
    except OSError:
        return "unknown"


def cmd_check(args: list) -> int:
    if len(args) not in (1, 2):
        raise Refuse("usage: check <close-id> [<skill-dir>]")
    p = receipt(args[0])
    recs = records(p)
    required = {r[1] for r in recs if r[0] == "required" and len(r) > 1}
    loaded = [r[1] for r in recs if r[0] == "loaded" and len(r) > 1]
    missing = missing_arms(recs)
    print(f"ARMS: required {len(required)}, loaded {len(set(loaded) & required)}")
    for arm in missing:
        print(f"ARM NOT LOADED: {arm}")
    skill = Path(args[1]) if len(args) == 2 and args[1] else None
    if skill is not None and (skill / "SKILL.md").is_file():
        print(f"CORE: {size(skill / 'SKILL.md')}")
        for arm in dict.fromkeys(loaded):
            print(f"LOADED: {arm} {size(skill / 'steps' / f'{arm}.md')}")
        for rel in SHARED:
            print(f"SHARED: {rel} {size(skill.parent / rel)}")
    elif len(args) == 2:
        print(f"CORE: unknown (no SKILL.md in {args[1]!r})")
    if missing:
        append(p, "checked", utc(), f"missing {len(missing)}")
        return 1
    p.unlink()
    return 0


def cmd_unchecked(args: list) -> int:
    hours = 24.0
    if args:
        if len(args) != 2 or args[0] != "--hours":
            raise Refuse("usage: unchecked [--hours <h>]")
        try:
            hours = float(args[1])
        except ValueError:
            raise Refuse(f"--hours takes a number, not {args[1]!r}") from None
    d = receipts(main_root())
    if not d.is_dir():
        return 0
    now = time.time()
    for p in sorted(d.glob("*.tsv")):
        try:
            if (now - p.stat().st_mtime) / 3600 < hours:
                continue
        except OSError:   # removed by a concurrent Step 8 since the glob
            continue
        try:
            recs = records(p)
        except Vanished:
            continue
        except Refuse as e:
            print(f"UNREADABLE: {p.name} ({e})")
            continue
        if any(r[0] == "checked" for r in recs):
            continue
        for arm in missing_arms(recs):
            print(f"UNCHECKED: {p.stem} {arm}")
    return 0


COMMANDS = {"begin": cmd_begin, "policy": cmd_policy, "read-policy": cmd_read_policy, "arm": cmd_arm,
            "conflicts": cmd_conflicts, "notes": cmd_notes, "exited": cmd_exited,
            "loaded": cmd_loaded, "check": cmd_check, "unchecked": cmd_unchecked}


def main(argv: list) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: close_arms.py {{{'|'.join(COMMANDS)}}} ...", file=sys.stderr)
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except Refuse as e:
        print(f"close_arms: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
