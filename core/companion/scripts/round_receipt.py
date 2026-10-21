#!/usr/bin/env python3
"""round_receipt.py — `/codebase-review` and `/security-audit` Step 5f: clear the round marker and write the round receipt.

    python3 sysop/scripts/round_receipt.py "<ROUND_MARKER path from Pre-flight>"

Run right after the round's `review_tasks.md` write. Reads the coverage line back out of
the round header just written, writes the receipt, and clears the marker.

The skill text is the contract: each skill's Step 5f says what the output and each exit
mean. Both skills carried this program as an identical heredoc until Phase 386 (`Q-409`
P3, with `Q-665`'s command-length limit); it now ships once, in loop mode too.
"""
import json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

p = Path(sys.argv[1]).resolve()
if not p.is_file():
    print(f"round-marker: nothing to clear at {p}")
    raise SystemExit(0)
# Ownership rests on passing the ROUND_MARKER= path THIS session captured at
# round-open — that is what keeps a concurrent session's marker safe. The
# filename/body nonce cross-check below is a secondary integrity guard: it
# refuses to delete a marker whose name and contents disagree (a hand-built or
# corrupted file), but it cannot tell one valid marker from another. So: only
# ever pass your own captured path here.
want = p.name.split(".")[-2] if p.name.endswith(".pending") else ""
fields = {}
try:
    marker_text = p.read_text(encoding="utf-8")
except (OSError, UnicodeDecodeError) as e:
    print(f"round-marker: REFUSING to remove {p.name} — it could not be read "
          f"({type(e).__name__}: {e}), so its nonce cannot be checked")
    raise SystemExit(0)
for ln in marker_text.splitlines():
    if ":" in ln:
        k, v = ln.split(":", 1)
        fields.setdefault(k.strip(), v.strip())
got = fields.get("nonce", "")
if want and got and want != got:
    print(f"round-marker: REFUSING to remove {p.name} — nonce mismatch "
          f"(file says {got}, path says {want}); not this session's marker")
    raise SystemExit(0)


# Tier-0 round receipt (_shared/fanout-evidence.md § Tier 0): the machine
# readable copy of the coverage line, so self_check.sh and /sitrep can surface a
# collapsed round without re-reading review_tasks.md. Written ONLY on the
# successful clear path — a receipt asserts "a round closed here". Every failure
# below is swallowed: evidence must never cost the cleanup it rides on.
# Why each selector rule exists: REFERENCE.md § Step 5f.
FANOUT_HEAD = re.compile(r"\s*>\s*(?:\*\*)?\s*fan[-\s]?out\s+coverage\b"
                         r"\s*(?:\(([^)]*)\))?\s*(?:\*\*)?\s*:?\s*(?:\*\*)?\s*",
                         re.I)
TAGS = ("quality", "security")


def round_header(root):
    """The `>` lines of the LAST `## Round` section, above its first batch."""
    f = root / "review_tasks.md"
    if not f.is_file():
        return []
    found, cur = [], None
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("## Round "):
            cur = []
            found.append(cur)
        elif cur is not None:
            if ln.startswith("## ") or ln.startswith("### "):
                cur = None
            elif ln.lstrip().startswith(">"):
                cur.append(ln)
    return found[-1] if found else []


def tag_of(skill):
    """This skill's tag, or None for a marker naming neither review skill."""
    if "security" in skill:
        return "security"
    return "quality" if ("codebase" in skill or "quality" in skill) else None


def label_of(ln):
    """The `(…)` label after `Coverage`, lower-cased; None when there is none."""
    m = re.search(r"coverage\s*\(([^)]*)\)", ln, re.I)
    return m.group(1).lower() if m else None


def read_coverage(header, skill):
    """This skill's coverage line from the round header, or "" when unsure."""
    tag = tag_of(skill)
    lines = [ln for ln in header if "Coverage" in ln and not FANOUT_HEAD.match(ln)]
    if tag is None or not lines:
        return ""
    hit = [ln for ln in lines if tag in (label_of(ln) or "")]
    if hit:
        return hit[0] if len(hit) == 1 else ""
    # No label names this skill: fall back over lines whose label names no skill.
    neutral = [ln for ln in lines if not any(t in (label_of(ln) or "") for t in TAGS)]
    whole = [ln for ln in neutral if tag in ln.lower()]
    if len(whole) == 1:
        return whole[0]
    return lines[0] if len(lines) == 1 and neutral else ""


def read_fanout(header, skill):
    """This skill's `Fan-out coverage` line, or "". A lone unlabelled line is taken
    only when the header holds at most one coverage line."""
    tag = tag_of(skill)
    fan = [ln for ln in header if FANOUT_HEAD.match(ln)]
    if tag is None:
        return ""
    hit = [ln for ln in fan
           if tag in (FANOUT_HEAD.match(ln).group(1) or "").lower()]
    if len(hit) == 1:
        return hit[0]
    ncov = sum(1 for ln in header if "Coverage" in ln and not FANOUT_HEAD.match(ln))
    if (not hit and len(fan) == 1 and FANOUT_HEAD.match(fan[0]).group(1) is None
            and ncov <= 1):
        return fan[0]
    return ""


def parse_fanout(line):
    """Per-worker `[opened, assigned]` pairs and the wave count.

    As strict as parse_coverage: an item that is not exactly
    `[<label>] <opened>/<assigned>` makes the whole list `unreported` (the text
    is kept beside it), because a partial list reads as fewer workers than ran.
    Items split on `·`, `;` or `, ` — a comma with no space is a thousands mark.
    """
    body = line[FANOUT_HEAD.match(line).end():] if FANOUT_HEAD.match(line) else line
    # Step 3c's report ends its ratios with this tail; copying it is not an error.
    body = re.sub(r";\s*\d+\s+(?:batch|agent)(?:\(e?s\)|e?s)?\s+flagged\s+low-opened\s*",
                  " ", body, flags=re.I)
    segs = [s.strip() for s in body.split("·")]
    out = {"ratios": "unreported", "waves": "unreported"}
    w = re.fullmatch(r"(\d+)\s*waves?(?:\s*\(s\))?", segs[-1], re.I)
    if w:
        out["waves"] = int(w.group(1))
        segs = segs[:-1]
    num = r"(\d{1,3}(?:,\d{3})+|\d+)"
    item = re.compile(r"(?:(.*?)(?:\s*[:=]\s*|\s+))?" + num + r"\s*/\s*" + num
                      + r"(?:\s*\([^)]*\))?")
    pairs = []
    for s in segs:
        for it in re.split(r"\s*;\s*|,\s+", s):
            if not it.strip():
                continue
            m = item.fullmatch(it.strip())
            if not m or re.search(r"\d\s*/\s*\d", m.group(1) or ""):
                return out
            pairs.append([int(m.group(2).replace(",", "")),
                          int(m.group(3).replace(",", ""))])
    if pairs:
        out["ratios"] = pairs
    return out


def parse_coverage(line):
    """Parse PER SEGMENT, matching each value whole.

    A whole-line regex is not safe here: a sampling basis is free text the
    author is told to write, so `Sampled (opened 3 entrypoints)` would hijack
    `opened`, and a loose numeric class truncates `manifest 1.477` to `1`. Both
    yield a confidently WRONG number, which is strictly worse than `unreported`
    — a shrunken denominator silences the very alarm this ledger exists to
    raise. Anything that is not exactly `<name> <digits>` is unreported.
    """
    body = line.split(":**", 1)[-1] if ":**" in line else line
    out = {k: "unreported" for k in ("manifest", "opened", "grepped", "workers")}
    out["kind"], out["solo_reason"] = "unreported", ""
    segs = [s.strip() for s in body.split("\u00b7")]
    for s in segs:
        head, sep, tail = s.partition(", solo:")
        if sep:
            out["solo_reason"] = tail.strip()
        m = re.fullmatch(r"(manifest|opened|grepped|workers)\s+([0-9][0-9,_]*)",
                         head.strip())
        if m:
            out[m.group(1)] = int(m.group(2).replace(",", "").replace("_", ""))
    if segs:
        # Kind is read from the FIRST segment only, so a `Full` occurring later
        # (in a solo reason, say) cannot relabel a round, and the unfilled
        # template placeholder stays `unreported` instead of asserting `Full`.
        m = re.fullmatch(r"(Full|Scoped|Sampled)(\s*\([^)]*\))?", segs[0].strip())
        if m:
            out["kind"] = m.group(0).strip()
    return out


try:
    skill = fields.get("skill", "unknown")
    receipt = {"skill": skill, "nonce": got or want,
               "started": fields.get("started", "unreported"),
               "completed": time.strftime("%Y-%m-%dT%H:%M:%S")}
    # parents: [0] pending-rounds, [1] runtime, [2] sysop, [3] repo root.
    header = round_header(p.parents[3])
    line = read_coverage(header, skill)
    receipt.update(parse_coverage(line))
    # The one number in this receipt that is NOT self-reported. `manifest` is
    # the round's own claim, and shrinking it is the one way to make a thin
    # round look complete with no visible tell — so record a fact beside it.
    # This is a RAW tracked-file count, deliberately not scope- or exclusion-
    # aware: `manifest < tracked` is normal and is not a defect. It exists so a
    # reader can see what fraction of the repository the round spoke for, the
    # same trick as putting `opened` beside `manifest` one level down.
    # MUST stay ahead of "line": self_check.sh extracts the coverage line with a
    # greedy sed that relies on "line" being the last key in the object.
    receipt["tracked"] = "unreported"  # set first: no path may leave it unset,
    try:                               # or the summary print below KeyErrors
        ls = subprocess.run(["git", "-C", str(p.parents[3]), "ls-files"],
                            capture_output=True, text=True)
        if ls.returncode == 0:
            receipt["tracked"] = len(ls.stdout.splitlines())
    except Exception:
        pass
    # The Step 5b fan-out line (also ahead of "line"): a dict when present,
    # `unreported` when workers ran and the line is missing, None when solo or
    # when `workers` itself is unreported (the `miss` print already says so).
    fan = read_fanout(header, skill)
    if fan:
        receipt["fanout"] = {"text": fan.strip(), **parse_fanout(fan)}
    elif isinstance(receipt["workers"], int) and receipt["workers"] > 0:
        receipt["fanout"] = "unreported"
    else:
        receipt["fanout"] = None
    receipt["line"] = line.strip()
    d = p.parent.parent / "round-receipts"
    d.mkdir(parents=True, exist_ok=True)
    # Both components are sanitized before they build a path: `skill` comes from
    # the marker BODY, which the nonce guard above already treats as possibly
    # hand-built, and an unsanitized `../..` there would land the receipt
    # outside the gitignored runtime dir and dirty the tree.
    safe = lambda s: (re.sub(r"[^A-Za-z0-9._-]", "_", str(s))[:64] or "unknown")
    dst = d / f"{safe(receipt['skill'])}.{safe(receipt['nonce'])}.json"
    # mkstemp, not a fixed `<dst>.tmp` (`Q-448`): a temp name derived from its
    # target is the class that entry closed tree-wide. Here `dst` already carries
    # the round's nonce, so two sessions could only collide by closing the same
    # round at once — this finishes the class rather than stopping a bleed.
    # `dir=d` keeps the replace same-filesystem;
    # the suffix is `.tmp`, never `.json`, so a reader's `*.json` glob cannot open
    # a half-written receipt; the mode is what `open()` would have created
    # (mkstemp makes 0600); and the cleanup arm re-raises after unlinking,
    # because a uniquely named leak is never overwritten by a later run.
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=dst.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, dst)  # atomic: a concurrent reader never sees a torn file
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:  # bounded history: keep the newest 50, prune the rest
        def age(f):
            try:
                return f.stat().st_mtime
            except OSError:
                return 0.0
        for old in sorted(d.glob("*.json"), key=age)[:-50]:
            try:  # per-file, so one unreadable entry cannot disable the bound
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass
    miss = [k for k in ("kind", "manifest", "opened", "grepped", "workers")
            if receipt[k] == "unreported"]
    if miss:
        print("round-receipt: unreported field(s): " + ", ".join(miss)
              + " — this round's coverage is NOT on the record"
              + ("" if line else "; no coverage line found in the round header"))
    else:
        print(f"round-receipt: {receipt['kind']} — opened {receipt['opened']}"
              f"/{receipt['manifest']} of {receipt['tracked']} tracked, "
              f"{receipt['workers']} worker(s)")
    # `FANOUT-UNREPORTED` is a stable token, like `LOW-LOOK` below.
    fo = receipt["fanout"]
    if fo == "unreported":
        print(f"round-receipt: FANOUT-UNREPORTED — {receipt['workers']} "
              "worker(s) dispatched, but the round header has no `Fan-out "
              "coverage` line for this skill; the per-worker ratios are NOT on "
              "the record")
        print("round-receipt:   A written receipt is never rewritten, so this "
              "one stays `unreported`; add the line to the header anyway (Step 5b), "
              "before the Step 7 commit, so the round record carries the ratios.")
    elif isinstance(fo, dict) and "unreported" in (fo["ratios"], fo["waves"]):
        print("round-receipt: fan-out line kept as text only — its ratios or "
              "wave count do not parse; write `<label> <opened>/<assigned>, …"
              " · <W> wave(s)`")
    # The WRITE-side half of the low-look test. Both readers of this receipt
    # already apply this exact arithmetic — `/sitrep` (sitrep_survey.py,
    # LOW_LOOK_RATIO) and `self_check.sh` (a literal `* 3`) — but both run
    # AFTER the Step 7 commit, against a one-shot JSON snapshot. By then the
    # label cannot be corrected: editing `review_tasks.md` does not rewrite a
    # receipt, and this block has already unlinked the marker. Step 5f runs
    # BEFORE that commit, so this is the one moment relabelling is still free,
    # and the round author is the one person who knows the basis to name.
    #
    # Ratio, never worker count: a fan-out round reaches this too. That
    # asymmetry — a solo-gated rule at dispatch, a ratio-gated one at read —
    # is the defect this check closes.
    #
    # OUTSIDE the `miss` branch on purpose, and this is not a style choice.
    # The shipped instruction two steps up says a round that cannot fill a
    # field writes `unreported` in it — so `grepped unreported` is a
    # DOCUMENTED input, and gating this check on a complete receipt let the
    # documented input switch the check off while BOTH readers still fired
    # (they exclude `grepped` from their own required set and read a non-int
    # as 0). Match them: `grepped` contributes when it is an int and
    # contributes 0 otherwise, and the check runs on whatever is present.
    #
    # WARN, NEVER ABORT. This whole block is wrapped in a try/except and
    # `p.unlink()` sits outside it, deliberately: evidence must never cost the
    # cleanup it rides on. A hard gate here would trade a mislabeled round for
    # a stranded marker, which is the worse failure.
    #
    # Three copies of this constant now exist (here, sitrep_survey.py,
    # self_check.sh) and are pinned equal by
    # tests/test_round_coverage_ledger.py — that test names all three.
    #
    # `LOW-LOOK` is a STABLE TOKEN, not prose. It is what the test and any
    # consumer grep keys on, so the sentences around it stay free to be
    # reworded. Keying a guard on the human wording is what makes a guard
    # redden on a correct edit, and a guard that reddens on correct edits
    # teaches the next maintainer to weaken it.
    LOW_LOOK_RATIO = 3
    _man, _opened, _grepped = receipt["manifest"], receipt["opened"], receipt["grepped"]
    if (str(receipt["kind"]).startswith("Full") and isinstance(_man, int)
            and _man > 0 and isinstance(_opened, int)):
        looked = _opened + (_grepped if isinstance(_grepped, int) else 0)
        if looked * LOW_LOOK_RATIO < _man:
            try:  # a hand-edited manifest can be large enough to overflow the
                pct = f" ({100.0 * looked / _man:.1f}%)"   # float divide, and
            except OverflowError:                          # losing the whole
                pct = ""                                   # warning to that is
            print(f"round-receipt: LOW-LOOK — labelled Full but looked at "   # worse
                  f"{looked} of {_man} files{pct}: "
                  f"opened {_opened} + grepped {_grepped}")
            print("round-receipt:   Once committed, this round reads as a "
                  "self-contradiction to the coverage readers — `/sitrep` "
                  "where it is installed, and `self_check.sh` when this is "
                  "the newest receipt.")
            print("round-receipt:   The round header is NOT committed yet "
                  "(Step 7 does that). Relabel it now as `Sampled (<basis>)` "
                  "naming what chose the subset — or widen the round. After "
                  "the commit the receipt is fixed and this cannot be "
                  "corrected.")
except Exception as exc:
    print(f"round-receipt: skipped ({exc.__class__.__name__}) — clearing anyway")

p.unlink()
print(f"round-marker: cleared {p.name}")
