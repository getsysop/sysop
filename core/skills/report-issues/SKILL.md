---
name: report-issues
description: File eligible SYSOP_ISSUES.md friction entries upstream as GitHub issues on the Sysop repo — per-entry human consent, mapped onto the bug-report template, then flip each filed entry to `Filed to Sysop` with its issue URL. Dry-run by default. GitHub-specific by design.
argument-hint: "[--execute] [--repo owner/name] [--include-resolved]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The **transport half** of Sysop's friction log. `/review-close` Step 7 *captures*
friction into `SYSOP_ISSUES.md` at the moment it happens (while live context still
holds the silent-deny / shell-escape memory); this skill *sends* the entries
worth sending upstream, as GitHub issues on the Sysop repo.

Without it, the friction log is a dead end for anyone but the maintainer: the
capture worked, but nothing files. That's fine when one person owns both the
consumer project and the Sysop repo — they just read the file. For an **external
tester** it strands the single most valuable output of a tester round (the
install / permission-rule / first-`/intake` friction) in a local file nobody
upstream ever sees. This skill closes that gap.

**This is a GitHub-touching skill** — the second in the `pr-*`/reporting family
after `/pr-dependabot`. It shells out to `gh` (the GitHub CLI) and therefore
requires `gh` installed + authenticated. Unlike `/pr-dependabot`, which operates
on *your own* repo, this one files **upstream to the Sysop repo** (the public
`getsysop/sysop` unless you've configured otherwise — Step 0.6) — that direction
is the whole point.

**The privacy being spent is yours.** Friction entries quote your error text and
your file paths. So: **per-entry consent is mandatory**, **dry-run is the
default**, and the skill shows you the exact issue body — every character that
would leave your machine — before anything is filed. It never auto-redacts
(lossy, and the call is yours) and never files an entry you didn't explicitly
pick.

## Pre-flight: Permission Guard

This skill shells out to `gh` and edits `sysop/SYSOP_ISSUES.md` in place. Its only
network side effect is creating GitHub issues, and only under `--execute` after
you pick which entries.

Read `.claude/settings.json` (and `.claude/settings.local.json` if present) and confirm `permissions.allow` satisfies:

- `Bash(gh issue create:*)` — file the consented entries (only reached under `--execute`)
- `Bash(gh issue list:*)` — pre-file duplicate check (soft, read-only)

If either is unsatisfied, stop with the `_shared/permission-guard.md` § Algorithm
step 5 message (one-line reason: "files SYSOP_ISSUES.md friction entries upstream
as GitHub issues; shells `gh issue create` against the Sysop repo"). Do not
proceed — unless the guard's step 3 mode check applies.

`gh auth status` and the `gh repo view` visibility probe are **not** listed as
required rules — their absence must not stop the run. Both ship in the template
allow-list (`Bash(gh auth status)`, `Bash(gh repo view:*)`), because `gh` is not
in Claude Code's built-in read-only set and every `gh` call therefore needs a
rule; under `dontAsk` an unlisted one is auto-denied. They stay off the required
list because each fails loudly on its own terms — a denied auth check reads the
same as not-logged-in and stops the skill with a visible message, and a denied
visibility probe degrades per `_shared/upstream-repo.md` § B rather than
halting. Editing `sysop/SYSOP_ISSUES.md` uses the `Edit` tool, not
Bash, so it needs no allow-rule.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and
continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **`--execute`** — actually create issues for the entries you consent to.
  **Without it, the skill is read-only** (reads + renders + prints the plan,
  files nothing, edits nothing).
- **`--repo owner/name`** — override the upstream target repo for this run.
  Beats every other source. Absent, the target comes from `<project>/CLAUDE.md
  § Sysop upstream repo` if that section exists, else the shipped default
  `getsysop/sysop`. Use the flag for one-off exceptions and a fork; use the
  CLAUDE.md section for a standing default (see Step 0.6).
- **`--include-resolved`** — also surface entries marked `Fixed in <consumer>
  <date>` (friction you fixed locally mid-cycle). Off by default; those are
  still upstream signal — Sysop's seeded ruleset/templates were incomplete — but
  they're lower urgency than open friction, so you opt in.

## Step 0.5: Confirm `gh` is authenticated

Run `gh auth status`. If it reports not-logged-in, stop and tell the human to
run `gh auth login` (suggest the `! gh auth login` in-session form). Do not
attempt to authenticate on their behalf.

## Step 0.6: Resolve the target repo and its visibility

Follow `_shared/upstream-repo.md` — the shared protocol for all three give-back
skills. In short: `--repo` beats `<project>/CLAUDE.md § Sysop upstream repo`
beats the shipped default `getsysop/sysop` (which is **public**); a present-but
-unparseable section is a hard stop, never a silent fall-back to the default.
Print the target and its source once, plainly, before anything is filed:
`Target repo for new issues: <owner/name>   (source: ...)`. Then probe
visibility (`gh repo view ... --json visibility`), carrying `[verified]` or
`[assumed]` per that partial's § B. Every `gh issue` call in this skill passes
`--repo <target>` explicitly — never rely on the current directory's remote,
which is the consumer's project, not Sysop.

**The sensitivity nudge runs later, not here.** It needs the exact rendered payload, which does not exist yet at this step; it fires at the consent gate (Step 2, just before Step 3) per `_shared/upstream-repo.md` § C. Carry this step's resolved target and visibility forward to it.

Reachability is separate from visibility. If the resolved target doesn't exist
from where you are (a fork slug typo, a private repo you lack access to), a `gh
issue create` will 404 — the visibility probe failing is *not* proof of that, so
it never stops the run on its own. If the very first `gh issue list` in Step 4
fails with a not-found error, stop and tell the human the target repo isn't
reachable rather than looping.

## Step 1: Read and classify the friction log

Read `sysop/SYSOP_ISSUES.md` — inside the `sysop/` vendor dir at the consumer-repo
root (Phase 128; NOT under `.claude/`, and no longer at the bare repo root). If a
pre-Phase-128 install left it at the root, read that instead rather than
reporting nothing. If neither exists, stop with one line: `note:
sysop/SYSOP_ISSUES.md not present — nothing to report. (Re-run bash install.sh to
seed it, or capture friction via /review-close Step 7 first.)` and stop.

Read the entry blocks (each begins `## ISSUE-NNNN — <title> (<date>)`). **This
file is deliberately loose, consumer-restructurable markdown** — the seed
template invites "you can restructure freely." So *read* it with judgment; do
not assume a rigid shape. If an entry's `Status:` is missing or ambiguous,
surface it to the human as "unclear status — treat as eligible? (y/n)" rather
than silently guessing either way.

Classify each entry by `**Status:**`:

| Status | Eligible to file? |
|---|---|
| `Open` | **yes** |
| `Prompt-ready` | **yes** |
| `Fixed in <consumer> <date>` | only with `--include-resolved` |
| `Filed to Sysop` | no — already sent (skip) |
| `Fixed in Sysop v…` | no — already resolved upstream (skip) |

**Backstop, independent of status:** an entry that already carries a `**Filed:**
<url>` line (written by a prior run, Step 5) is **ineligible** no matter what its
`Status:` says. This is what keeps a re-run — including a `--include-resolved`
re-run over a `Fixed in <consumer>` entry — from double-filing, even if a status
flip was missed.

Also read the consumer name from the file's H1 (`# Sysop Issues — <consumer>`) —
you'll prefix issue titles with it so cross-repo readers know which project the
friction came from. If the H1 has no name, omit the prefix.

If no entries are eligible, print `No eligible entries in SYSOP_ISSUES.md. Nothing
to file.` and stop.

## Step 2: Render each candidate as its proposed issue — always

For **every** eligible entry, construct and print the exact issue that *would*
be filed, so the human reviews the full payload before consenting. Do this
whether or not `--execute` was passed.

**Title:** `[<consumer>] <entry title>` (drop the `ISSUE-NNNN —` prefix and the
trailing `(date)`; keep the human-readable title). Omit the `[<consumer>]`
prefix if no consumer name was found.

**Label:** `bug` for every entry (v1). A friction-log entry is a defect report
in Sysop-shipped content by definition; the rare entry that's really a pack or
convention *proposal* still files fine as `bug` and the maintainer relabels it
`enhancement` on triage. (Auto-picking `enhancement` was dropped for v1: it
would need the `pack_or_convention` body shape, not the `bug_report` one, and
the friction log's shape is bug-report-shaped — not worth the divergence yet.)

**Body:** map the entry's sections onto the `bug_report` template shape. Render
it as literal markdown the human can read in full:

```
**What happened**
<the entry's ### What happened, verbatim>

**To reproduce**
<repro steps drawn from ### What happened / ### Verification, if present>

**Diagnosis (reporter's)**
<the entry's ### Diagnosis>

**Proposed fix (reporter's)**
<the entry's ### Proposed fix>

**Workaround the reporter used (if any)**
<the entry's ### Workaround in <consumer>, if present — useful upstream signal
that the tester was blocked and how they unblocked>

**Environment**
- Reported from: <consumer> (via SYSOP_ISSUES.md / /report-issues)
- Sysop commit or install date: <from .claude/sysop.lock if readable, else "unknown">
```

Include only the sections the entry actually has — a loose entry may omit some.
Do not invent content. Keep the reporter's words; don't rewrite their diagnosis
into your own.

**Redaction is the human's call, done by editing the log first.** Before the
consent step, print one reminder — substituting the **resolved target** from
Step 0.6: *"These bodies are exactly what will be filed to `<target>` — visible
to anyone who can see that repo. If any contains a path, secret, or data you
don't want exposed there, edit `sysop/SYSOP_ISSUES.md` to redact it and re-run —
I will not auto-redact."* (Don't hardcode "publicly" — with the target pointed
at a private repo, the issues are visible only to that repo's collaborators.)

**Then run the sensitivity nudge** (`_shared/upstream-repo.md` § C) against the
rendered bodies above, and print it when the Step 0.6 visibility is `PUBLIC`,
`INTERNAL`, or `UNKNOWN`. This is the step that catches the trap this skill is
most exposed to: friction entries routinely quote the security context that
produced the friction (an unfixed scrub gap, the contents of an open review
batch), and the shipped default target is public. The nudge names which entries
matched and why, states `[verified]`/`[assumed]`, and points at both remedies —
redact the log, or retarget via `§ Sysop upstream repo` / `--repo`. It filters
nothing; per-entry consent below is still the gate.

**Scan the issue *titles* too, not only the bodies.** Titles are composed
separately in Step 2 and are the most-read field on a GitHub issue — a body that
reads as a routine tooling complaint can sit under a title that names the system,
the data, or the customer.

If `--execute` was **not** passed, stop here: print `Dry-run. Re-run with
--execute to choose which of these to file.` and stop. Nothing is filed or
edited.

## Step 3: Per-entry consent (mandatory)

Only under `--execute`. Get explicit consent **per entry** — the sibling skills
gate one item at a time on purpose (`/review-close` Steps 3c/2d), and it matches
this skill's privacy model: the human approves each body individually, having
just read it in Step 2.

Use `AskUserQuestion`, but **never enumerate all entries in one question** —
`AskUserQuestion` caps options per question (~4) and a full issue title overflows
an option label. Ask per entry (a single yes/no "File this one?"), or batch at
most **4 entries per question** with a short option label (the `ISSUE-NNNN` id)
and the full title in the option description. Nothing is filed unless the human
explicitly picks it; an unselected entry is skipped, never defaulted-in.

**Carry the destination into each question, not just the Step 2 preamble.** When
the Step 0.6 visibility is `PUBLIC`, `INTERNAL`, or `UNKNOWN`, every consent
question restates the target and its visibility in the question text
(`Filing to <owner/name> — PUBLIC [verified]. File this one?`), and any entry the
Step 2 nudge flagged carries a marker in its own option label
(`ISSUE-0008 ⚠ security context`). With batches of 4, a single warning printed
before a ten-entry run is two questions upstream by the time the entry it was
about comes up for approval — which is the same as not having warned.

If the human consents to none, print `Nothing selected. No issues filed.` and
stop.

## Step 4: File each consented entry

For each selected entry, in order:

1. **Soft duplicate check:** run
   `gh issue list --repo <target> --state all --search '<title>'`, searching on
   the plain title **without** the `[<consumer>]` prefix (the brackets weaken
   GitHub phrase matching). If a clearly-matching issue already exists, surface
   it (`possible duplicate: <url>`) and ask whether to file anyway (default:
   skip). This guards against a re-run after a partial failure, or an entry
   someone already filed by hand.

2. **File it — pass the body as a file, never inline.** The body contains
   backticks, `$`, and quotes **by design** (the seed template mandates raw
   error text and code spans in `### What happened` / `### Proposed fix`).
   Inlining that into a double-quoted `--body "<body>"` is a real hazard: bash
   would run backtick/`$()` substitutions and break on stray quotes — silently
   filing something *different* from what the human approved (breaking the
   shown-equals-filed promise) and, worst case, **executing** approved *text* as
   a shell command. So:

   - Write the exact rendered body (identical to what Step 2 printed) to a
     temporary file **outside the repo** (e.g. `"${TMPDIR:-/tmp}/sysop-issue-<id>.md"`)
     using the `Write` tool — never echo it through the shell. Keep the
     `:-/tmp` fallback: macOS sets `TMPDIR`, most Linux shells do not, and a bare
     `"$TMPDIR/…"` collapses to `/sysop-issue-<id>.md` — an unwritable root path,
     so the filing fails on the consumers least likely to have `TMPDIR` set
     (Phase 153). Every Sysop skill that stages a body file uses this form.
   - Keep the `--title` a plain one-line summary and pass it **single-quoted**;
     if the source title contains a backtick, `$`, or a single quote, render a
     clean equivalent for the title (the full original text still rides in the
     body file). Titles are short human summaries — this is a light touch, not
     redaction.
   - Then:
     ```bash
     gh issue create --repo <target> --title '<title>' --label bug --body-file "${TMPDIR:-/tmp}/sysop-issue-<id>.md"
     ```
   - Delete the temp file after the call returns (success or failure).

   `gh issue create` prints the new issue URL — capture it. If the call fails
   (auth lapse, missing label, network), **do not** edit the log entry; record
   the failure and move to the next entry. If the `bug` label doesn't exist
   (a fresh fork may not have it), retry once without `--label` and note it.

## Step 5: Flip the entry and record the URL

For each entry that filed successfully, edit **the same file Step 1 read** —
`sysop/SYSOP_ISSUES.md`, or the bare-root copy if that is where Step 1 resolved
it — via `Edit`, keyed on the unique `## ISSUE-NNNN` anchor so the change is
surgical. Writing to a path Step 1 did not read would fail *after* the issue is
already filed, and the status flip is the only thing stopping a re-run from
double-posting:

- Change its `**Status:**` line to `**Status:** Filed to Sysop` — **whatever it was
  before** (`Open`, `Prompt-ready`, or a `Fixed in <consumer>` entry filed under
  `--include-resolved`). Every successfully-filed entry ends up `Filed to Sysop`;
  the "was fixed locally" history stays in the entry's body.
- Insert a line immediately below the Status line:
  `**Filed:** <issue url> (<today's date, YYYY-MM-DD>)`.

Leave every other entry — skipped, unselected, or failed-to-file — exactly as it
was. The `Filed:` line is the durable back-reference (and the Step 1 ineligibility
backstop) so a later `/report-issues` run — or a human — sees the entry is already
upstream and where it went.

## Step 6: Report

Print a summary:

```
Reported to <target>:

Filed:       <N> (<title> → <url>, one per line)
Skipped:     <N> not selected · <N> possible-duplicate · <N> failed-to-file
Ineligible:  <N> already Filed/Fixed (unchanged)

SYSOP_ISSUES.md edited: <N status flips> (uncommitted — commit the flips when ready)
```

The log edits are left uncommitted, same contract as every other Sysop skill: the
human reviews and commits the status flips intentionally.

## Design notes (reference)

- **Skill, not a script.** Unlike `/pr-dependabot` (which shells to
  `pr_dependabot.py` because classifying ~50 PRs needs deterministic rules),
  this skill has no classification problem and a deliberately loose input: the
  friction log is consumer-restructurable markdown the seed template explicitly
  invites you to reshape. A rigid parser would silently choke on a tester's
  reformatted log — the same failure mode Phase 68 removed from the check config
  loader. Agent-read markdown is the robust tool here; the one irreversible side
  effect (`gh issue create`) is human-gated regardless. If a future consumer's
  volume makes the manual render tedious, a `report_issues.py` that emits a
  structured plan is the escape hatch — filed as a revisit, not built now.
- **Upstream, not local.** Files to `getsysop/sysop` by default because the whole
  purpose is getting a tester's friction to the maintainer. This is the one place
  a `pr-*`-family skill points away from the current repo on purpose. That
  default is *public*, though, and friction entries carry consumer security
  context — so the target is a first-class consumer config (`CLAUDE.md § Sysop
  upstream repo`, durable) with `--repo` as the per-run override on top, and a
  sensitivity nudge fires before consent when the resolved target isn't a
  verified-private repo.
- **Earlier capture is nudged, not a separate mechanism.** The primary capture
  point is `/review-close` Step 7, but a tester's densest friction (install,
  first permission-rule setup, first `/intake`) happens before any review-close
  cycle exists. Docs cover it (CONTRIBUTING.md + README tell testers to log
  friction as it happens), backed by capture nudges in `install.sh`'s closing
  "Next steps" and at the end of `/intake`.
