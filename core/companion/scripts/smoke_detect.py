#!/usr/bin/env python3
"""smoke_detect.py — `/review-close` Step 3c: the manual-smoke detection.

    python3 sysop/scripts/smoke_detect.py "<worktree dirs>" "<approved branches>" <default-branch>

Both lists are one newline-separated argument each. Prints `NO_SMOKE_REQUIRED`, or
`SMOKE_REQUIRED: <n> signal(s)` followed by the signal blocks; the first line alone
decides.

The skill text is the contract: `/review-close` Step 3c says what each line and each
exit code means and what the close does with it. This file was that step's heredoc
until Phase 386 (`Q-409` P3), moved verbatim.
"""
import hashlib, os, re, subprocess, sys
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
    try:
        import yaml
    except ImportError:
        print("ERROR: pyyaml not available — install in the project venv", file=sys.stderr)
        sys.exit(2)

repo = Path.cwd().resolve()
main_pd = repo / "sysop/runtime/pending-docs"
_GIT_ENV = dict((_k, _v) for _k, _v in os.environ.items()
            if _k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"))
_GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"
default_branch = (sys.argv[3] if len(sys.argv) > 3 else "").strip()
if not default_branch or "<" in default_branch:
    print("ERROR: pass the name `bash sysop/scripts/default_branch.sh` printed as the third "
          "argument, then re-run Step 3c", file=sys.stderr)
    sys.exit(3)

def git(*args, timeout=15):
    """(returncode, stdout, first stderr line). Never raises: the gate runs before the merge."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=str(repo), capture_output=True,
                           text=True, timeout=timeout, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, (r.stderr.strip().splitlines() or [""])[0]

# Search each approved branch's worktree sysop/runtime/pending-docs/ AND main's (BeanRider ISSUE-0050
# — worktree-authored docs aren't copied to main until Step 3b). Worktrees FIRST: if a doc
# exists in both (a stale copy a prior halted run left in main + the fresher worktree
# original), the worktree — the authoring source of truth — must win the basename dedup
# below, so a newly-added smoke heading is never shadowed by the stale main copy.
search_dirs = []
for _d in sys.argv[1].splitlines():
    _d = _d.strip()
    if _d:
        search_dirs.append(Path(_d) / "sysop/runtime/pending-docs")

# A WORKTREE IS NOT THE ONLY WORKSPACE SHAPE, AND THIS GATE RUNS BEFORE STEP 3B.
# argv[1] is computed from `git worktree list`, which never lists a `claim_task.sh --clone`
# workspace. Step 3b's collect handles that shape — but Step 3b runs *after* this gate, so
# at this moment a clone-authored pending-doc is in neither main nor argv[1], and a doc
# headed for an irreversible pre-merge step scored NO_SMOKE_REQUIRED with nothing to say
# so. Resolve the remaining approved branches the same way Step 3b step 0 does: the lock's
# recorded workspace, then the conventional sibling directory verified by reading its HEAD.
# Additive — argv[1] still wins for any branch it already covers.
_approved = [b.strip() for b in (sys.argv[2] if len(sys.argv) > 2 else "").splitlines() if b.strip()]
_covered = {str(Path(d).resolve()) for d in sys.argv[1].splitlines() if d.strip()}

def _head_branch(d):
    dot = d / ".git"
    if dot.is_file():                       # a worktree/submodule: `gitdir: <path>`
        line = dot.read_text(encoding="utf-8", errors="replace").strip()
        if not line.startswith("gitdir:"):
            return None
        dot = Path(line[len("gitdir:"):].strip())
        if not dot.is_absolute():
            dot = (d / dot).resolve()
    head = dot / "HEAD"
    if not head.is_file():
        return None
    ref = head.read_text(encoding="utf-8", errors="replace").strip()
    return ref[len("ref: refs/heads/"):] if ref.startswith("ref: refs/heads/") else None

branch_ws = {}    # approved branch -> its workspace; the tip read runs there (a clone has its own objects)
for _d in sys.argv[1].splitlines():
    if _d.strip() and _head_branch(Path(_d.strip())):
        branch_ws.setdefault(_head_branch(Path(_d.strip())), Path(_d.strip()))
for _b in _approved:
    _ws = None
    _locks = repo / "sysop" / "runtime" / "locks"
    if _locks.is_dir():
        for _lk in sorted(_locks.glob("*.lock")):
            if not _lk.is_file():
                continue
            _f = {}
            for _line in _lk.read_text(encoding="utf-8", errors="replace").splitlines():
                _k, _sep, _v = _line.partition(":")
                if _sep and _k not in _f:
                    _f[_k] = _v.strip()
            if _f.get("branch") == _b and _f.get("workspace"):
                _ws = Path(_f["workspace"]); break
    if _ws is None:
        # Sibling-glob fallback, reached only when the lock has no `workspace:`.
        # It cannot see WORKTREE_PREFIX exported by another session, and cannot
        # see WORKTREE_ROOT (Phase 262) at all — a relocated workspace is not a
        # sibling. Both limits are the same one: neither variable is recorded,
        # so with `workspace:` gone there is nothing to reconstruct from. A
        # LINKED worktree is still found, because the lock-less path above reads
        # the porcelain listing; the residue is a relocated --clone.
        import os
        _prefix = os.environ.get("WORKTREE_PREFIX") or repo.name
        for _cand in sorted(repo.parent.glob(f"{_prefix}-*")):
            if _cand.is_dir() and _head_branch(_cand) == _b:
                _ws = _cand; break
    if _ws is None:
        continue
    branch_ws.setdefault(_b, _ws)
    try:
        _r = _ws.resolve()
    except OSError:
        continue
    if _r == repo or str(_r) in _covered:      # main's own docs are appended below
        continue
    _covered.add(str(_r))
    search_dirs.append(_ws / "sysop/runtime/pending-docs")

search_dirs.append(repo / "sysop/runtime/pending-docs")

# The heading phrase set is WIDER than the original two (`manual smoke` / `smoke
# required`), because the original was an allowlist over free prose and the gate's
# failure direction is silence: a pending doc headed `OPERATOR ACTION REQUIRED BEFORE
# MERGE` scored NO_SMOKE_REQUIRED and the close proceeded without ever asking (reported
# by a consumer). A false positive here costs one AskUserQuestion with a
# waive option; a false negative is a human never asked about an irreversible step.
# `user ops` is DELIBERATELY not in this set — `user_action: true` is a large, routine
# class, and prompting on all of it would train the operator to waive wholesale. That
# reason is timing-independent and is the whole of it (tasks/schema.md § "User ops"; an
# earlier form also claimed POST-merge timing, which nothing in the tree supports).
# A step that must precede the MERGE is `manual_smoke:`, detected by sources 2 and 3.
heading_re = re.compile(
    r'^ {0,3}(#{1,6})[ \t]+.*('
    r'manual\s+smoke'
    r'|smoke\s+(?:required|test)'
    r'|manual\s+(?:verification|verify|test|check|step)'
    r'|operator\s+action'
    r'|human\s+action'
    r'|requires?\s+a\s+human'
    r'|before\s+merg(?:e|ing)'
    r'|prior\s+to\s+merg(?:e|ing)'
    r')',
    re.IGNORECASE | re.MULTILINE,
)
fm_re = re.compile('^\\ufeff?---\\n(.*?)\\n---', re.DOTALL)   # a BOM must not hide the frontmatter

_fence_line = re.compile(r'^(\s*)(`{3,}|~{3,})(.*)$')

def unfenced(text):
    """`text` with every line of each closed fence blanked to spaces; offsets still index `text`.
    Used only to find where a section ends. A fence still open at the end of the file fences nothing."""
    lines = text.split("\n")
    out, opener, start = list(lines), None, 0
    for i, line in enumerate(lines):
        m = _fence_line.match(line.rstrip("\r"))
        if opener is None:
            if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
                opener, start = m.group(2), i
        elif (m and m.group(2)[0] == opener[0] and len(m.group(2)) >= len(opener)
              and not m.group(3).strip()):
            for j in range(start, i + 1):
                out[j] = " " * len(lines[j])
            opener = None
    return "\n".join(out)

def extract_sections(text):
    masked = unfenced(text)
    for m in heading_re.finditer(text):
        start, depth = m.start(), len(m.group(1))
        end = len(text)
        for nm in re.finditer(r'^ {0,3}(#{1,6})[ \t]+', masked[m.end():], re.MULTILINE):
            if len(nm.group(1)) <= depth:
                end = m.end() + nm.start(); break
        yield text[start:end].rstrip()

def label(md):
    # main-relative when possible; absolute for a worktree-authored doc
    try:
        return str(md.relative_to(repo))
    except ValueError:
        return str(md)

# Collect pending-docs across all search dirs; dedup by basename (first wins,
# worktrees ahead of main) so a doc present in both is counted once, preferring
# the fresher worktree copy.
pending_files = []
seen_names = set()
for pd in search_dirs:
    if not pd.is_dir():
        continue
    for md in sorted(pd.glob("*.md")):
        # Not a branch pending-doc: a fixed-name file the review skills own and delete
        # themselves. It has no `branch:` and no smoke headings, and counting it here
        # makes an empty pending-docs dir look populated. Step 4c excludes it too.
        if md.name == "convention-candidates.md":
            continue
        if md.name in seen_names:
            continue
        seen_names.add(md.name)
        pending_files.append(md)

def truthy(v):
    """`manual_smoke` is documented as a bool — but this gate runs before the merge and
    the validator's type check is warn-shaped in practice. `manual_smoke: "true"` is an
    author saying *ask me*; `is True` alone scored it NO_SMOKE_REQUIRED."""
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "on", "1"))

def id_list(v):
    """`roadmap_ids: T-1` is a scalar, and iterating it walks its CHARACTERS — every
    linkage silently lost. Accept the scalar as a one-element list."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, str)]
    return [str(v)]

def read_fm(md):
    """Frontmatter dict for a pending doc, or {} — parsed ONCE per file.

    `or {}` is NOT enough: safe_load on a single prose line between the delimiters
    returns a truthy `str`, and on a bare list a truthy `list`, so `.get()` below
    raised AttributeError and killed the whole close. Test the type, not truthiness.
    """
    m = fm_re.match(md.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return {}
    try:
        fm = yaml.safe_load(m.group(1))
    except Exception as e:
        sys.exit(f"ERROR: {md} does not parse ({type(e).__name__}: {e}); fix it or move it to "
                 f"sysop/runtime/pending-docs/quarantine/, then re-run Step 3c")
    return fm if isinstance(fm, dict) else {}

fms = {md: read_fm(md) for md in pending_files}

def load_index(text, where):
    try:
        idx = yaml.safe_load(text) or {}
    except Exception as e:
        sys.exit(f"ERROR: {where} does not parse ({type(e).__name__}: {e}); fix it, then re-run Step 3c")
    if not isinstance(idx, dict):
        sys.exit(f"ERROR: {where} is a {type(idx).__name__}, not a mapping; fix it, then re-run Step 3c")
    if not isinstance(idx.get("tasks") or [], list):
        sys.exit(f"ERROR: {where}'s tasks: is a {type(idx.get('tasks')).__name__}, not a list; fix it, then re-run Step 3c")
    return dict((t["id"], t) for t in (idx.get("tasks") or []) if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"])

index_path = repo / "tasks" / "index.yml"
tasks = {}
if index_path.is_file():
    tasks = load_index(index_path.read_text(encoding="utf-8", errors="replace"), "tasks/index.yml")
origin_tasks, origin_note = None, None
if index_path.is_file() and git("remote", "get-url", "origin")[0] == 0:
    oref = f"refs/remotes/origin/{default_branch}"
    frc, _, ferr = git("fetch", "--quiet", "origin", f"+refs/heads/{default_branch}:{oref}", timeout=60)
    rc, osha, _ = git("rev-parse", "--verify", "--quiet", oref + "^{commit}")
    rc2, shown, err2 = git("show", f"{oref}:tasks/index.yml") if rc == 0 else (1, "", "")
    if rc != 0 or rc2 != 0:
        origin_note = (f"ORIGIN INDEX: not read — "
                       + (f"origin/{default_branch} does not resolve" if rc != 0 else err2)
                       + (f"; fetch failed: {ferr}" if frc else "")
                       + "; a hold is judged from the working tree alone")
    else:
        origin_tasks = load_index(shown, f"origin/{default_branch}:tasks/index.yml")
        if frc:
            origin_note = (f"ORIGIN INDEX: fetch failed ({ferr}); read the last-fetched "
                           f"origin/{default_branch}@{osha.strip()[:12]}, which may be behind")
_tip_cache = {}
tip_notes = []

def tip_tasks(rev):
    """The approved branch's own tasks/index.yml at its tip; {} when it cannot be read."""
    if rev not in _tip_cache:
        ws = branch_ws.get(rev)
        at = ["-C", str(ws)] if ws else []
        rc, shown, err = git(*at, "show", f"{rev}:tasks/index.yml")
        _tip_cache[rev] = load_index(shown, f"{rev}:tasks/index.yml") if rc == 0 else {}
        if rc != 0 and git(*at, "cat-file", "-e", f"{rev}:tasks/index.yml")[0] == 0:
            tip_notes.append(f"BRANCH INDEX: not read — `{rev}:tasks/index.yml`: {err}; "
                             "a flag or hold change set only there is not seen")
    return _tip_cache[rev]

def indexes(rev=None):
    return [tasks, origin_tasks or {}] + ([tip_tasks(rev)] if rev else [])

def flagged(tid, rev=None):
    """`manual_smoke` on the working tree, origin/<default branch>, or the branch's own tip."""
    return any(truthy(ix.get(tid, {}).get("manual_smoke")) for ix in indexes(rev))

def entry_of(tid, rev=None):
    return next((ix[tid] for ix in indexes(rev) if tid in ix), {})

def held(t):
    """Held on the working tree, and on origin/<default branch> and every approved branch's tip
    that carries the task: either can release a hold, never add one."""
    if not tasks.get(t, {}).get("user_action"):
        return False
    others = [origin_tasks or {}] + [tip_tasks(b) for b in sorted(approved)]
    return all(bool(ix[t].get("user_action")) for ix in others if t in ix)
approved = set(b.strip() for b in (sys.argv[2] if len(sys.argv) > 2 else "").splitlines() if b.strip())
rc, out, _ = git("rev-parse", "--abbrev-ref", "HEAD")
rc2, out2, _ = git("rev-parse", "--short=12", "HEAD")
head_branch = out.strip() if rc == 0 and out.strip() != "HEAD" else ""
worktree_rev = f"{out.strip()}@{out2.strip()}" if rc == 0 and rc2 == 0 else "HEAD unresolved"

def doc_ids(fm):
    # Phase 23a compat shim: roadmap_ids OR task_ids — the order Step 4c 1c reads them in.
    return id_list(fm.get("roadmap_ids")) or id_list(fm.get("task_ids"))

def branch_of(fm):
    b = str(fm.get("branch") or "").strip()
    return b[len("refs/heads/"):] if b.startswith("refs/heads/") else b

def not_merging(md, fm):
    """A doc in main's pending-docs whose branch is neither approved this run nor the branch
    HEAD is on. With HEAD unresolved, nothing qualifies, so every doc is asked."""
    b = branch_of(fm)
    return bool(md.parent == main_pd and b and head_branch
                and b not in approved and b != head_branch)

def held_ids(md, fm):
    """Ids Step 4c 1c holds this doc on (truthy `user_action`, the round-trip's own test),
    for a doc that is not merging this run."""
    if not not_merging(md, fm):
        return []
    return [t for t in doc_ids(fm) if held(t)]

def doc_hold(fm):
    """The doc's own `hold:` (`Q-625`), read as pending_doc_hold.py reads it: truthy."""
    v = fm.get("hold")
    return (str(v).strip() or "(no reason given)") if v else ""

def held_reasons(md, fm):
    """Why Step 4c 1c holds a doc that is not merging this run; [] for any other doc."""
    if not not_merging(md, fm):
        return []
    hid = held_ids(md, fm)
    return (([f"user_action outstanding: {', '.join(hid)}"] if hid else [])
            + ([f"hold: {doc_hold(fm)}"] if doc_hold(fm) else []))

def not_merging_note(fm, hid):
    b = branch_of(fm)
    rc, out, _ = git("rev-list", "--count", b, "^HEAD")
    if rc != 0:
        where_b = f"branch `{b}` does not resolve here"
    elif out.strip() == "0":
        where_b = f"branch `{b}` is already in HEAD"
    else:
        where_b = f"branch `{b}` has {out.strip()} commit(s) not in HEAD"
    released = [t for t in doc_ids(fm) if tasks.get(t, {}).get("user_action") and not held(t)]
    since = f", held since {fm['held_since']}" if fm.get("held_since") else ""
    why = (f"held by Step 4c 1c ({'; '.join(hid)}){since}" if hid
           else f"not held here: user_action is set locally but not on origin/{default_branch} "
                f"or an approved branch that carries the task ({', '.join(released)}); "
                "Step 4c may still hold it" if released
           else "not held")
    return f"{why}; not merging in this run; {where_b}"

def where(md):
    """Pending docs are untracked runtime files, so the revision is the checkout they sit in."""
    if md.parent == main_pd:
        return "main checkout's sysop/runtime/pending-docs/, read in place"
    return f"workspace of `{_head_branch(md.parents[3]) or '(branch unresolved)'}`, read in place"

def key_of(sec):
    return hashlib.sha256(sec.strip().replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]

def answered_in(md, k):
    prior = fms[md].get("smoke_answers")
    for a in (prior if isinstance(prior, list) else []):
        if (isinstance(a, dict) and str(a.get("section")) == k
                and a.get("decision") in ("confirmed", "unrunnable")):
            return a
    return None

_targets, _target_notes = [], []

def merge_targets():
    """[(sha, label)] the body lands on: local <default branch>, and origin/<default branch>
    unless the local branch already holds it; origin alone when the local branch is behind it.
    Falls back to HEAD, with a note, when the local branch does not resolve."""
    if not _targets:
        def at(ref):
            rc, out, _ = git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
            return out.strip() if rc == 0 else ""
        loc, org, hd = (at(f"refs/heads/{default_branch}"),
                        at(f"refs/remotes/origin/{default_branch}"), at("HEAD"))
        local = (loc, f"{default_branch}@{loc[:12]}") if loc else ((hd, worktree_rev) if hd else None)
        if not loc:
            _target_notes.append(f"`{default_branch}` does not resolve here, so "
                                 + (f"HEAD ({worktree_rev}) stands in for it" if hd else "neither does HEAD"))
        origin = (org, f"origin/{default_branch}@{org[:12]}") if org else None
        if local and origin and origin[0] != local[0]:
            if git("merge-base", "--is-ancestor", local[0], origin[0])[0] == 0:
                _targets.append(origin)
            elif git("merge-base", "--is-ancestor", origin[0], local[0])[0] == 0:
                _targets.append(local)
            else:
                _targets.extend([local, origin])
        elif local or origin:
            _targets.append(local or origin)
    return _targets

def blob_text(loc, ref):
    """(text or None when absent, error or ""). Decoded with replacement, as pending docs are."""
    try:
        r = subprocess.run(["git", *loc, "show", ref], cwd=str(repo), capture_output=True,
                           timeout=15, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    if r.returncode == 0:
        return r.stdout.decode("utf-8", errors="replace"), ""
    exists = git(*loc, "cat-file", "-e", ref)[0] == 0
    return None, (r.stderr.decode("utf-8", errors="replace").strip().splitlines() or ["?"])[0] if exists else ""

def merged_body(at, rev, sha, body_git, tip_text):
    """(texts, READ label, note or None): the body as it will merge, one text per side of a
    conflict, each by `git merge-file --ours`/`--theirs` so neither carries conflict markers.
    A target whose merge cannot be read leaves the tip in the texts and is named in the note."""
    import tempfile
    tip = f"{rev}@{sha[:12]}"
    texts, merged, conflicts, failed, unread = [], [], [], [], []
    targets = merge_targets()
    if not targets:
        failed.append("no merge target resolves")
    for h, lab in targets:
        for loc in ([at, []] if at else [[]]):
            rc, base, e = git(*loc, "merge-base", h, sha)
            if rc == 0:
                break
        else:
            failed.append(f"its merge with {lab} could not be read ({e or 'no merge base'})")
            unread.append(lab); continue
        (target_text, te), (base_text, be) = blob_text(loc, f"{h}:{body_git}"), blob_text(loc, f"{base.strip()}:{body_git}")
        why = (f"`{h[:12]}:{body_git}` could not be read ({te})" if te else
               f"`{base.strip()[:12]}:{body_git}` could not be read ({be})" if be else
               f"{lab} moved or deleted `{body_git}`" if target_text is None and base_text is not None else "")
        if why:
            failed.append(why); unread.append(lab); continue
        target_text, base_text = target_text or "", base_text or ""
        if target_text in (tip_text, base_text):
            continue
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for name, body in (("target", target_text), ("base", base_text), ("branch", tip_text)):
                fp = os.path.join(td, name)
                with open(fp, "w", encoding="utf-8", newline="") as fh:
                    fh.write(body)
                paths.append(fp)
            runs = [git("merge-file", "-p", *flag, *paths) for flag in ([], ["--ours"], ["--theirs"])]
        rc = runs[0][0]
        if not 0 <= rc < 128 or any(r[0] != 0 for r in runs[1:]):
            e = next((r[2] for r in runs if r[2]), "").replace(td + os.sep, "")
            failed.append(f"merging it with {lab} failed ({e or f'exit {rc}'})")
            unread.append(lab); continue
        if rc == 0:
            texts.append(runs[0][1]); merged.append(lab)
        else:
            texts += [runs[1][1], runs[2][1]]; conflicts.append(f"{lab} ({rc} hunk(s))")
    lost = " and ".join(unread) if unread and (merged or conflicts) else "the merge target"
    note = "; ".join(_target_notes + failed) or None
    if note and failed:
        note += f"; a procedure heading {lost} added is not seen"
    if failed or not texts:
        texts.append(tip_text)
    texts = list(dict.fromkeys(texts))
    head = f"{tip} merged with {' and '.join(merged)} —" if merged else f"{tip} —"
    segs = []
    if conflicts:
        segs.append(f"this body CONFLICTS with {', '.join(conflicts)}; each side's version is scanned")
    if failed:
        segs.append(f"the branch tip, read as is: {'; '.join(failed)}; a heading {lost} added is not seen")
    if not segs:
        return texts, (f"{head} the text that is merging; the merge target changed this body" if merged
                       else f"{tip} — the branch tip, the text that is merging"), note
    return texts, f"{head} {'and ' if merged else ''}{'; and '.join(segs)}", note

signals = []     # (source, read, held note or None, carrier doc label or None, key or None, text, approved branch or None)
answered = []    # (source, first line, decision, date, key, carrier doc label)
not_in_run = []

def emit(src, read, carrier, sec, branch=None):
    """One signal. A signal carried by a pending doc gets a KEY naming that doc; an answer
    recorded there is honoured only while the doc is not merging."""
    if branch is None and carrier is not None and branch_of(fms[carrier]) in approved:
        branch = branch_of(fms[carrier])
    if carrier is None:
        signals.append((src, read, None, None, None, sec, branch))
        return
    k = key_of(sec)
    fm = fms[carrier]
    if not_merging(carrier, fm):
        a = answered_in(carrier, k)
        if a:
            answered.append((src, sec.strip().splitlines()[0], a.get("decision"),
                             a.get("date", "?"), k, label(carrier)))
            return
        note = not_merging_note(fm, held_reasons(carrier, fm))
    else:
        note = None
    signals.append((src, read, note, label(carrier), k, sec, branch))

# (a) pending-doc body scan
for md in pending_files:
    # errors="replace": a pending-doc with non-UTF-8 bytes must not kill the close.
    for sec in extract_sections(md.read_text(encoding="utf-8", errors="replace")):
        emit(label(md), where(md), md, sec)

# (a2) STRUCTURAL declaration on the pending doc itself: `manual_smoke: true` in
# frontmatter signals regardless of how — or whether — the procedure is headed. This is
# the heading-independent escape for a hotfix branch with no tasks/index.yml entry; a
# declaration nobody has to phrase correctly cannot be missed by a phrase list.
for md in pending_files:
    if truthy(fms[md].get("manual_smoke")):
        secs = list(extract_sections(md.read_text(encoding="utf-8", errors="replace")))
        if not secs:
            emit(label(md), where(md), md, "(frontmatter `manual_smoke: true`, no procedure "
                                           "section found in this doc — ask the human what it is)")

# (b) index.yml manual_smoke:true cross-check.
#
# TWO linkage sources, because pending-doc frontmatter alone was not one. A task can
# declare `manual_smoke: true`, author its procedure under the sanctioned heading, and
# still be scored NO_SMOKE_REQUIRED when no pending doc's roadmap_ids named it — the
# fully-compliant author was the one the gate did not protect. The lock is the second
# source: it records `branch:`, so a claimed task is linked to this run's approved
# branches by fact rather than by a doc that may be absent or malformed.
smoke_ids = {}   # task id -> the approved branch it merges on, or None
declared = set() # task ids with `manual_smoke: true` on an index read for that link
carriers = {}    # task id -> every pending doc naming it, in scan order
held_links = {}  # a HELD doc links nothing: its task is not merging in this close
# source 1 — pending-doc frontmatter. An undeclared task is linked only by an approved branch.
for md in pending_files:
    fm = fms[md]
    hid = held_reasons(md, fm)
    b = branch_of(fm)
    on = b if b in approved else None
    for tid in doc_ids(fm):
        dec = flagged(tid, on)
        if not dec and not on:
            continue
        carriers.setdefault(tid, []).append(md)
        if dec:
            declared.add(tid)
        if hid:
            held_links.setdefault(tid, md)
        elif on:
            smoke_ids[tid] = smoke_ids.get(tid) or b
        else:
            smoke_ids.setdefault(tid, None)
# source 2 — locks whose `branch:` is one of THIS run's approved branches. Locks are
# canonical under the main repo (git-common-dir), which is CWD here.
if approved:
    locks_dir = repo / "sysop" / "runtime" / "locks"
    if locks_dir.is_dir():
        for lk in sorted(locks_dir.glob("*.lock")):
            lock_branch = ""
            for line in lk.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("branch:"):
                    lock_branch = line[len("branch:"):].strip(); break
            if lock_branch and lock_branch in approved:
                tid = lk.name[:-len(".lock")]
                smoke_ids[tid] = lock_branch
                if flagged(tid, lock_branch):
                    declared.add(tid)
for tid in sorted(set(held_links) - set(smoke_ids)):
    not_in_run.append(f"NOT IN THIS RUN: tasks/index.yml § {tid} — linked only by held doc "
                      f"{label(held_links[tid])}, so its body's procedure is not asked")

seen_lc = "\n".join(s[5] for s in signals).lower()
for tid in sorted(smoke_ids):
    rev = smoke_ids[tid]
    dec = tid in declared
    body_rel = str(entry_of(tid, rev).get("body") or "")
    src = f"tasks/index.yml § {tid}"
    # A task an approved branch claims is merging, so its answers live only in a merging doc.
    docs = carriers.get(tid, [])
    carrier = (next((d for d in docs if not not_merging(d, fms[d])), None) if rev
               else (docs[0] if docs else None))
    # A DECLARED smoke whose body cannot be read, or carries no recognisable
    # procedure heading, is a signal — not silence. The declaration is the ask;
    # a missing procedure makes the ask louder, not absent.
    if not body_rel:
        if dec:
            emit(src, "nothing — no `body:` recorded", carrier,
                 "(manual_smoke: true, but the task has no `body:` — "
                 "ask the human what the procedure is)", rev)
        continue
    body_git = body_rel if body_rel.startswith("tasks/") else "tasks/" + body_rel
    body_path = repo / body_git
    # The path comes from the first index carrying the task; the content from the approved
    # branch's tip, read in that branch's workspace when one is known.
    texts, read, tip_err = None, None, ""
    if rev:
        ws = branch_ws.get(rev)
        at = ["-C", str(ws)] if ws else []
        rc, sha, tip_err = git(*at, "rev-parse", "--verify", "--quiet", rev + "^{commit}")
        rc2, shown, err2 = git(*at, "show", f"{rev}:{body_git}")
        if rc == 0 and rc2 == 0:
            texts, read, mnote = merged_body(at, rev, sha.strip(), body_git, shown)
            if mnote:
                tip_notes.append(f"MERGE NOT READ: tasks/index.yml § {tid} at `{rev}`: {mnote}")
        else:
            tip_err = err2 or tip_err or "ref does not resolve"
    if texts is None and body_path.is_file():
        texts = [body_path.read_text(encoding="utf-8", errors="replace")]
        read = f"working tree ({worktree_rev})" + (
            f" — could NOT be read at `{rev}` ({tip_err}), so this may not be the text "
            "that is merging" if rev else " — no approved branch in this run claims this task")
    if (rev and not dec and not (read or "").startswith(f"{rev}@")
            and git(*(["-C", str(branch_ws[rev])] if rev in branch_ws else []),
                    "cat-file", "-e", f"{rev}:{body_git}")[0] == 0):
        tip_notes.append(f"BODY NOT READ: tasks/index.yml § {tid} at `{rev}` ({tip_err}); "
                         "a procedure heading there is not seen")
    if texts is None:
        if dec:
            emit(src, f"nothing — `{body_git}` not found", carrier,
                 f"(manual_smoke: true, but its body `{body_rel}` is not "
                 f"readable from here — ask the human what the procedure is)", rev)
        continue
    found, shown_here = False, set()
    for sec in (x for t in texts for x in extract_sections(t)):
        found = True
        if sec.lower() in seen_lc or sec in shown_here: continue
        shown_here.add(sec)
        emit(src, read, carrier, sec, rev)
    if not found and dec:
        emit(src, read, carrier,
             "(manual_smoke: true, but no procedure heading matched in "
             f"`{body_rel}` — ask the human what the procedure is)", rev)

print("NO_SMOKE_REQUIRED" if not signals else f"SMOKE_REQUIRED: {len(signals)} signal(s)")
for src, first, decision, date, k, doc in answered:
    print(f"PREVIOUSLY ANSWERED: {src} — {decision} on {date} (key {k}, recorded in {doc}): {first}")
for line in not_in_run:
    print(line)
if origin_note:
    print(origin_note)
for line in tip_notes:
    print(line)
for src, read, note, carrier, k, sec, branch in signals:
    print("---SIGNAL---")
    print(f"SOURCE: {src}")
    print(f"READ: {read}")
    if branch:
        print(f"BRANCH: {branch}")
    if note:
        print(f"NOT MERGING: {note}")
    if carrier:
        print(f"KEY: {k} (record in {carrier})")
    print(sec)
