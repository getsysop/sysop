#!/usr/bin/env python3
"""smoke_record.py — `/review-close` Step 3c: record a smoke answer in the pending doc.

    python3 sysop/scripts/smoke_record.py "<the doc the KEY line names>" "<the KEY's 16 hex>" "<confirmed or unrunnable>"

Writes the answer into the doc's `smoke_answers:` and changes no other line, then prints
`RECORDED: …`. Anything it cannot record safely, including a waiver, is `REFUSING: …` with a
non-zero exit and no write. Exit 2 means PyYAML is not available.

The skill text is the contract: `/review-close` Step 3c says when to run it and what each
outcome means. This file was that step's heredoc until Phase 387 (`Q-409` P3), moved
verbatim.
"""
import os, re, sys, tempfile
from datetime import date
from pathlib import Path
try:
    import yaml
except ImportError:  # PyYAML lives only in the project venv
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

key, decision = sys.argv[2].strip(), sys.argv[3].strip()
if decision not in ("confirmed", "unrunnable"):
    sys.exit(f"REFUSING: {decision!r} is not recorded — only confirmed or unrunnable, never a waiver")
if not re.fullmatch(r"[0-9a-f]{16}", key):
    sys.exit(f"REFUSING: {key!r} is not the 16-hex value of a KEY: line")
doc = (Path.cwd() / sys.argv[1]).resolve()
pd = doc.parent
if pd.parts[-3:] != ("sysop", "runtime", "pending-docs") or not doc.is_file():
    sys.exit(f"REFUSING: {sys.argv[1]} is not a doc in a sysop/runtime/pending-docs/ directory")
try:
    raw = doc.read_bytes().decode("utf-8")
except UnicodeDecodeError:
    sys.exit(f"REFUSING: {doc.name} is not valid UTF-8 — record it by hand")
nl = "\r\n" if "\r\n" in raw else "\n"
if nl == "\r\n" and raw.count("\n") != raw.count("\r\n"):
    sys.exit(f"REFUSING: {doc.name} mixes line endings — record it by hand")
text = raw.replace("\r\n", "\n")
m = re.match('^\\ufeff?---\\n(.*?)\\n---', text, re.DOTALL)
try:
    fm = yaml.safe_load(m.group(1)) if m else None
except Exception:
    fm = None
if not isinstance(fm, dict):
    sys.exit(f"REFUSING: {doc.name} has no frontmatter mapping to record into")
prior = fm.pop("smoke_answers", [])
if not isinstance(prior, list):
    sys.exit(f"REFUSING: {doc.name}'s smoke_answers is not a list — fix it by hand")
entries = [a for a in prior if not (isinstance(a, dict) and str(a.get("section")) == key)]
entries.append(dict(section=key, decision=decision, date=date.today().isoformat()))
# Replace only the smoke_answers block, and write it first. Every other line stays byte-for-byte.
kept, skipping = [], False
for line in m.group(1).split("\n"):
    if re.match(r"smoke_answers\s*:", line):
        skipping = True
        continue
    if skipping and line[:1] in (" ", "\t", "-"):
        continue
    skipping = False
    kept.append(line)
new_fm = "\n".join([yaml.safe_dump(dict([("smoke_answers", entries)]), sort_keys=False,
                                   default_flow_style=False, allow_unicode=True,
                                   width=120).rstrip("\n")] + kept)
try:
    check = yaml.safe_load(new_fm)
except Exception:
    check = None
if not isinstance(check, dict) or check.pop("smoke_answers", None) != entries or check != fm:
    sys.exit(f"REFUSING: rewriting {doc.name} would change another frontmatter key — record it by hand")
fd, tmp = tempfile.mkstemp(dir=str(pd), prefix=".smoke-answer-", suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline=nl) as f:
        f.write(text[:m.start(1)] + new_fm + text[m.end(1):])
    os.chmod(tmp, doc.stat().st_mode & 0o7777)   # mkstemp creates 0600
    os.replace(tmp, doc)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)
print(f"RECORDED: {doc.name} — {decision} for key {key}")
