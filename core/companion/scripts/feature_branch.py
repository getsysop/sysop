#!/usr/bin/env python3
"""feature_branch.py — `/review-close` Step 2a: the landed check, or keep a gitignored file the branch reads.

    python3 sysop/scripts/feature_branch.py landed       "<branch>" "<default branch>"
    python3 sysop/scripts/feature_branch.py keep-ignored "<workspace>" "<path>" "<commit or copy>"

Run from the repo root. `landed` (step 0b) prints `LANDED: …` or `NOT LANDED — <reason>`.
`keep-ignored` (step 3a) carries out one answer about a gitignored file the branch reads:
`commit` adds it to the branch, `copy` puts it in the main checkout. A missing or unknown
subcommand exits 2.

The skill text is the contract: `/review-close` Step 2a, steps 0b and 3a, says what each
line and each exit code means. Both subcommands were that step's two heredocs until
Phase 387 (`Q-409` P3), moved verbatim.
"""
import sys

_SUBCOMMANDS = ('landed', 'keep-ignored')
if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS:
    sys.stderr.write('usage: ' + sys.argv[0] + ' {' + '|'.join(_SUBCOMMANDS) + '} <args>\n')
    sys.exit(2)
_SUBCOMMAND = sys.argv.pop(1)

if _SUBCOMMAND == 'landed':
    import os, subprocess, sys
    from pathlib import Path
    try:
        import yaml
    except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
        import glob, os, subprocess
        _sites = []
        try:
            _r = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                capture_output=True, text=True, timeout=5,
                env=dict((_k, _v) for _k, _v in os.environ.items()
                     if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                                   "GIT_COMMON_DIR", "GIT_INDEX_FILE")),
            )
            _g = _r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            _g = ""
        for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
            for _layout in (".venv", "venv"):
                _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
        sys.path[:0] = _sites
        import yaml
    branch, default = sys.argv[1], sys.argv[2]
    if not branch.strip() or not default.strip() or "<" in branch + default:
        print("UNSUBSTITUTED or empty operand — write the branch and the default branch out. STOP.")
        sys.exit(3)
    def git(*args, cwd=None):
        r = subprocess.run(["git", *args], capture_output=True, cwd=cwd)
        return r.returncode, os.fsdecode(r.stdout).strip()
    import re
    fm_re = re.compile(r"^\ufeff?---\n(.*?)\n---", re.DOTALL)
    held, stamped = [], False
    for doc in sorted(Path("sysop/runtime/pending-docs").glob("*.md")):
        try:
            m = fm_re.match(doc.read_text(encoding="utf-8"))
            fm = yaml.safe_load(m.group(1)) if m else None
        except Exception:
            continue
        if isinstance(fm, dict) and str(fm.get("branch") or "") == branch:
            held.append(doc.name)
            stamped = stamped or bool(fm.get("held_since"))
    if not held:
        print("NOT LANDED — no pending doc in sysop/runtime/pending-docs/ names it")
        sys.exit(0)
    rc, own = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    if rc != 0:
        print(f"NOT LANDED — no local branch {branch}")
        sys.exit(0)
    rc, out = git("for-each-ref", "--contains", own, "--format=%(refname)",
                  "refs/sysop/merged-pr-heads/")
    heads = sorted(out.split(), key=lambda r: (len(r), r)) if rc == 0 else []
    if heads:
        containers = heads
        via, past = f"PR #{heads[0].rsplit('/', 1)[1]}", "past every recorded head"
    elif branch == default or git("merge-base", "--is-ancestor", own, f"refs/heads/{default}")[0]:
        print(f"NOT LANDED — no recorded PR head contains it, and {default} does not")
        sys.exit(0)
    elif not stamped:
        print(f"NOT LANDED — {default} contains it, but no doc naming it carries held_since:")
        sys.exit(0)
    else:
        containers = [f"refs/heads/{default}"]
        via, past = f"in {default}", f"past {default}"
    def noise(where, entry):
        """An untracked symlink whose target this repository ignores, as Step 1-pre reads it."""
        p = os.path.join(where, entry)
        if not os.path.islink(p):
            return False
        target = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
        return git("check-ignore", "-q", target)[0] == 0
    tips = []
    for lk in sorted(Path("sysop/runtime/locks").glob("*.lock")):
        if not lk.is_file():
            continue
        fields = {}
        for line in lk.read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.partition(":")
            if sep and k not in fields:
                fields[k] = v.strip()
        ws = fields.get("workspace") or ""
        if fields.get("branch") != branch or not ws or not Path(ws).is_dir():
            continue
        if Path(ws).resolve() == Path.cwd().resolve():
            continue
        rc, tip = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=ws)
        if rc == 0:
            tips.append((f"workspace {ws}", tip))
        st = git("status", "--porcelain", cwd=ws)[1].splitlines()
        if (git("rev-parse", "--abbrev-ref", "HEAD", cwd=ws)[1] == branch
                and [ln for ln in st if not (ln.startswith("?? ") and noise(ws, ln[3:]))]):
            print(f"NOT LANDED — workspace {ws} has uncommitted work on it")
            sys.exit(0)
    rc, out = git("ls-remote", "origin", f"refs/heads/{branch}")
    if rc != 0:
        print("NOT LANDED — could not read origin's copy of it (git ls-remote failed)")
        sys.exit(0)
    if out:
        tips.append((f"origin/{branch}", out.split()[0]))
    for label, tip in tips:
        if not any(git("merge-base", "--is-ancestor", tip, c)[0] == 0 for c in containers):
            print(f"NOT LANDED — {label} is at {tip[:12]}, {past}")
            sys.exit(0)
    print(f"LANDED: {via} — held doc {', '.join(held)}")

elif _SUBCOMMAND == 'keep-ignored':
    import filecmp, os, re, shutil, subprocess, sys
    from pathlib import Path
    ws, rel, action = sys.argv[1], sys.argv[2], sys.argv[3]
    if (any(re.fullmatch(r"<[a-z][a-z -]*>", a) for a in (ws, rel, action))
            or action not in ("commit", "copy")):
        print("ERROR: placeholder not substituted"); sys.exit(3)
    env = dict((k, v) for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"))
    def git(*a, where=ws):
        r = subprocess.run(["git", "-C", where, *a], capture_output=True, text=True, env=env)
        if r.returncode:
            print("FAILED: git {}: {}".format(" ".join(a), r.stderr.strip())); sys.exit(4)
        return r.stdout.strip()
    src = Path(ws) / rel
    try:
        if action == "commit":
            if src.is_symlink():
                print("FAILED: {} is a symlink; it is not committed".format(rel)); sys.exit(4)
            git("add", "-f", "--", rel)
            git("commit", "-m", "fix: commit {}, which the branch reads".format(rel), "--", rel)
            print("COMMITTED: {} at {}".format(rel, git("rev-parse", "--short", "HEAD")))
        else:
            here = os.getcwd()
            if (os.path.realpath(git("rev-parse", "--absolute-git-dir", where=here))
                    != os.path.realpath(git("rev-parse", "--git-common-dir", where=here))):
                print("FAILED: run this from the main checkout"); sys.exit(4)
            dst = Path(git("rev-parse", "--show-toplevel", where=here)) / rel
            real, base = os.path.realpath(dst), os.path.realpath(ws)
            inside = real == base or real.startswith(base + os.sep)
            if dst.exists() and not inside and filecmp.cmp(src, dst, shallow=False):
                print("ALREADY: {} is in the main checkout".format(rel)); sys.exit(0)
            if os.path.lexists(dst):
                print("REFUSED: {} exists in the main checkout and is not the same file".format(dst))
                sys.exit(5)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print("COPIED: {} -> {}".format(rel, dst))
    except OSError as exc:
        print("FAILED: {}".format(exc)); sys.exit(4)
