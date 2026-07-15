---
name: contribute-convention
description: Package this project's locally-grown conventions (the never-managed .claude/*.project.* overlay) as pack/convention proposals and file them upstream to the Sysop repo — generalized to placeholder vocabulary, provenance surfaced, one issue per target pack, per-pack human consent. Dry-run by default. GitHub-specific by design.
argument-hint: "[--execute] [--repo owner/name] [--include-security]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The **give-back half** of Sysop's "grow your own pack from real use" loop. Sysop's
whole pack model is that conventions *earn their way in* from recurring review
findings — and every populated pack (`python`, `postgres`, `nextjs-react`,
`llm`, `beancount`) got there because someone ran Sysop on a real project and
promoted what kept recurring. This skill is how a *consumer* sends that back
upstream: it reads the conventions this project promoted locally, strips them of
project fingerprints, and files them to the Sysop repo as pack/convention
proposals.

Without it, the give-back is asymmetric. `/report-issues` transports *friction*
(bugs in Sysop-shipped content) upstream, but there is **no** automated path for
the more valuable contribution CONTRIBUTING.md names first — a locally-promoted
convention or a grown pack. Today that means a hand-authored GitHub issue, the
exact manual step the transport skills exist to remove. This closes it.

**This is a GitHub-touching skill** — the third in the `pr-*`/reporting family
after `/pr-dependabot` and `/report-issues`, and it mirrors `/report-issues`'
transport shape closely (permission guard → `gh auth` → resolve upstream repo →
render → per-item consent → `gh issue create` → annotate the source → report).
Like `/report-issues` — and unlike `/pr-dependabot`, which operates on your own
repo — it files **upstream to the Sysop repo** (`getsysop/sysop` by default). That
direction is the whole point.

**The privacy being spent is your project's fingerprints.** A locally-grown
convention quotes your real paths, helper names, and sometimes your threat model.
Packs are for everyone; they must not carry one codebase's fingerprints
(CONTRIBUTING.md § "Keep content generic"). So the load-bearing step is
**generalization** — rewriting each rule into placeholder vocabulary — and the
safety property is **shown-equals-filed**: the skill prints the exact generalized
text, every character that would leave your machine, before anything is filed.
**Per-pack consent is mandatory**, **dry-run is the default**, and the skill
never files a pack-group you didn't explicitly pick.

## Pre-flight: Permission Guard

This skill shells out to `gh` and edits your `.claude/*.project.*` overlay files
in place (to annotate what was contributed). Its only network side effect is
creating GitHub issues, and only under `--execute` after you pick which pack
groups.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(gh issue create:*)` — file the consented proposals (only reached under `--execute`)
- `Bash(gh issue list:*)` — pre-file duplicate check (soft, read-only)

These are the **same two rules `/report-issues` requires** — a project set up for
that skill already has them. If either is missing, stop with the
`_shared/permission-guard.md` § Algorithm step 4 message (one-line reason:
"files locally-grown conventions upstream as pack/convention proposals; shells
`gh issue create` against the Sysop repo"). Do not proceed.

`gh auth status` and `gh repo view` are read-only and auto-approved under `auto`
mode — they are not listed here (per `_shared/permission-guard.md` § Notes:
don't list read-only ops). Editing the overlay uses the `Edit` tool, not Bash,
so it needs no allow-rule.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and
continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **`--execute`** — actually create issues for the pack groups you consent to.
  **Without it, the skill is read-only** (reads + generalizes + prints the
  proposals, files nothing, edits nothing).
- **`--repo owner/name`** — override the upstream target repo. Default:
  `getsysop/sysop`. Use this if you forked Sysop and want proposals on your fork.
- **`--include-security`** — also surface entries from
  `.claude/security_map.project.md` (a project's security conventions). Off by
  default because a security map can encode threat-model detail that wants a
  more careful generalization pass; when you opt in, the same shown-equals-filed
  generalization discipline applies, just with extra scrutiny.

## Step 0.5: Confirm `gh` is authenticated

Run `gh auth status`. If it reports not-logged-in, stop and tell the human to
run `gh auth login` (suggest the `! gh auth login` in-session form). Do not
attempt to authenticate on their behalf.

## Step 0.6: Resolve the target repo

Default target is **`getsysop/sysop`** — the upstream Sysop repo, *not* the current
project's own repo. Override with `--repo owner/name` (forks). Print the target
once, plainly, so the human sees where proposals will land before any are filed:
`Target repo for new proposals: <owner/name>`. Every `gh issue` call in this
skill passes `--repo <target>` explicitly — never rely on the current
directory's remote, which is the consumer's project, not Sysop.

If `getsysop/sysop` isn't reachable from where you are (e.g. the GitHub rename
hasn't propagated, or you're filing against a fork), a `gh issue create` will
404 — pass `--repo` with the correct slug. If the first `gh issue list` in
Step 8 fails with a not-found error, stop and tell the human the target repo
isn't reachable rather than looping.

## Step 1: Confirm this is a consumer install with a locally-grown overlay

The read source is the **never-managed overlay** — the `.claude/*.project.*`
files that are the durable home for conventions this project promoted locally
(the Phase 78 promotion write target). Base maps (`.claude/convention_map.md`,
`.claude/checks.yml`, `.claude/security_map.md`) are Sysop-shipped and regenerated
on every `sysop-update.sh`; **never read them here** — they are already upstream,
so contributing them back is meaningless.

Detect the two contexts (per `_shared/promotion-write-target.md`):

- **Consumer install** — `.claude/sysop.lock` is present. Look for overlay files
  `.claude/convention_map.project.md`, `.claude/checks.project.yml`, and (only
  with `--include-security`) `.claude/security_map.project.md`. If none exist or
  they contain no consumer-authored entries, print `No locally-grown conventions
  found in .claude/*.project.* — nothing to contribute. (Conventions land in the
  overlay when /codebase-review or /security-audit Step 9 promotes a recurring
  finding.)` and stop.
- **Source tree** — `.claude/sysop.lock` is absent (you are inside the Sysop repo
  itself, or a project that authors its maps in place). There is no overlay to
  read. Print `This looks like the Sysop source tree (no .claude/sysop.lock) — its
  maps are the upstream source, not a consumer overlay. Nothing to contribute
  from here.` and stop.

The overlay is **deliberately loose, consumer-restructurable markdown** — the
same property `/report-issues` relies on for the friction log. Read it with
judgment; do not assume a rigid shape. Read the consumer name from `.claude/sysop.lock`
(or the overlay H1) so you can attribute the proposal's origin ("grown in
`<consumer>`") without leaking it into the generalized rule text.

## Step 2: Parse the overlay into candidate conventions

From `convention_map.project.md`, read each glob-section (`## <globs> — <Section
Name>`) and its bullets. From `checks.project.yml`, read each check entry. From
`security_map.project.md` (only under `--include-security`), read each entry.

**Exclude, do not contribute:**

- **Suppression / override entries in `checks.project.yml`** — a check entry
  that is a *local policy choice* rather than a novel rule. Skip it in any of
  these shapes (per `_shared/promotion-write-target.md`):
  - its `paths:` **contains** the disabling sentinel `__disabled_no_op__` — match
    by **containment**, not exact string: the sentinel appears with a trailing
    slash or alongside other paths (e.g. `["__disabled_no_op__/", "<dir>/"]`),
    not only as `["__disabled_no_op__"]`;
  - it carries `used_by: []` (disabled by having no consumer stage);
  - **its `id` already exists in the installed base `.claude/checks.yml`** — then
    it is an *override* of a Sysop-shipped check (consumer wins on id-collision),
    i.e. local policy, and the check itself is already upstream. Read the base
    `checks.yml` for this id comparison **only**.

  Only a check whose `id` is **novel** (absent from the base `checks.yml`) and
  not disabled is a candidate.
- **Bullets that merely restate a Sysop-shipped convention.** In a consumer install
  the installer **appends your `.project.md` verbatim** into the base
  `.claude/convention_map.md` (WORKFLOW.md § 8.2c) — so *every* overlay bullet
  also appears in the base map's appended region, which is **your own reflection,
  not upstream evidence**. A naive "is this bullet in the base map?" check would
  therefore exclude every candidate. Instead, compare each candidate **only
  against the base map's upstream region** = the base-map text with your appended
  overlay subtracted (you already read `.project.md` directly in Step 1, so
  remove that exact text first, then compare against what remains). A candidate
  that matches a bullet in the *remaining upstream region* is already shipped by
  a Sysop core/pack map — skip it. (Read the base map for this comparison **only** —
  never as a contribution source.)
- **Candidates already sent upstream by a prior run** — the double-file backstop
  (written in Step 8), keyed **per candidate, not per section**:
  - a **markdown bullet** is ineligible if it is named in a section's
    `> Contributed upstream: <url> (<date>) — filed: <bullet subjects>`
    annotation;
  - a **`checks.project.yml` entry** is ineligible if it carries a
    `# Contributed upstream: <url> (<date>)` YAML comment on the line(s) above it
    (`>` is a YAML block-scalar indicator, not a comment, so checks use a `#`
    comment — not the markdown `>` form).

  Because this is per-candidate, a section that was only *partly* contributed
  stays eligible for the bullets no prior annotation names (newly promoted since,
  previously deferred as needs-manual-generalization, or dropped at consent) —
  re-running to send a section's remainder is **supported, not blocked**. Note
  anything genuinely already-sent as "already contributed" in the final report.

Every surviving bullet/entry is a **candidate**. Carry its source glob(s) / check
`id` so Step 4 can map it to a target pack and Step 8 can annotate the right
section or entry.

## Step 3: Discover provenance for each candidate

Provenance is Sysop's earn-their-way bar, and this skill enforces it by *showing*
it rather than asking the human to assert it by hand. For each candidate, search
`review_tasks.md` (consumer-repo root) for evidence the rule earned promotion:

- A rule that recurred across **2+ distinct `## Round N` blocks**, or is named in
  a `Promotion summary:` trailer, or appears in the `## Convention fire ledger`
  → record it: `recurred across Rounds N and M` (or the promotion-summary
  citation). This is the promotion-grade signal.
- **No match** → the overlay entry was likely hand-authored at bootstrap (a
  common, legitimate case — a project can seed its own conventions before ever
  running the Step 9 loop). Record `no in-repo round provenance found`. **Do not
  fabricate provenance and do not silently drop the candidate.**

**Collect the human's attestation here — as a normal conversational turn, before
rendering (Step 6), never at consent (Step 7).** For candidates with `no in-repo
round provenance found`, ask the human in one plain question what recurring
mistake the rule catches and roughly how often they've hit it (the
`pack_or_convention` template's "Where these come from" field). Take the answer
as free text — and treat it as **project text like any other**: it flows through
Step 4 generalization (a hasty answer can name a real path or vendor) and then
appears in the Step 6 body the human reviews, so shown-equals-filed still holds.
Collecting it at Step 7 instead would splice unreviewed, ungeneralized text into
an already-shown body — **do not do that.**

**Same turn, one optional extra — model provenance.** Ask which model or agent
family generated the stray code these conventions kept catching, and roughly
when ("<model family>, 2026-Q2" is plenty). This is dataset metadata for the
maintainer: it helps separate durable engineering discipline (model-agnostic —
the corpus's core value) from a single model generation's tics, which become
natural retire candidates once that generation ages out. **Optional; absence is
honest** — the human may simply not know. Never infer it yourself from git
history or session logs, and never press. The answer is project text like the
attestation: it flows through Step 4 generalization and appears in the Step 6
body, so shown-equals-filed holds.

Never invent a round number or a recurrence count. If `review_tasks.md` is
absent entirely, every candidate is `no in-repo round provenance found` — that
is fine; the human attests here.

## Step 4: Generalize each candidate — strip project fingerprints

This is the heart of the skill and the reason it's a reasoning task, not a
script. Rewrite each candidate into **placeholder vocabulary** so the rule is
useful to everyone and carries no codebase's fingerprints (CONTRIBUTING.md §
"Keep content generic"). Use the **same placeholder vocabulary the target pack
already teaches** — every populated pack's `convention_map.md` opens with a
placeholder glossary (`<api module>`, `<auth module>`, `<scripts dir>`,
`<tests dir>`, `<utility modules>`, …). The generalization is exactly the
transform the maps already model. **Apply it to the rule text *and* to any
human attestation collected in Step 3** — the attestation is project text too, so
it gets the same fingerprint-strip before it reaches the Step 6 body.

Apply, per candidate:

- **Real paths → placeholder globs.** `parsers/*.py` → `<data parser dir>/*.py`;
  `scripts/*.py` → `<scripts dir>/*.py`. Reuse an existing pack placeholder when
  one fits; coin a descriptive one (`<foo module>`) when none does, and list any
  coined placeholders so the maintainer can reconcile vocabulary.
- **Real helper / symbol names → placeholder or canonical-example.**
  `_sanitize_customer_field()` → `<field redactor>`. The packs keep some helper
  names as *canonical
  examples* with a header note that they're placeholders (`_sanitize_log`,
  `useAbortableFetch`) — you may keep a helper name that way if it reads as a
  clear archetype, but add the "(placeholder for your project's equivalent)"
  framing; otherwise placeholder it.
- **In-repo cross-references → drop or generalize.** `See CLAUDE.md § Data
  integrity`, `See src/db/writer.py:102`, `(in this pack's semgrep/
  directory)` — these point at *this* project's files and mean nothing
  upstream. Drop the file:line refs; keep a generic pointer only if it stands on
  its own ("mirror the atomic-rewrite pattern").
- **Project / service / vendor names → out.** The consumer's project name,
  internal service names, real vendor integrations named only to identify this
  codebase — remove. (A vendor named because the *rule is about that vendor's
  SDK* stays; a vendor named only as this project's example goes.)

**Two discipline guards — do not skip:**

1. **Don't gut the rule to generalize it.** A convention rewritten into
   "handle errors properly" is worthless. Keep it concrete and actionable —
   fingerprint-free, not detail-free. The test: could a reviewer on a *different*
   project act on this bullet as written?
2. **If you cannot generalize a candidate without either leaking a fingerprint
   or gutting the rule, exclude it from the auto-filed set** and surface it in
   the report as "needs manual generalization — left for you to reword and
   re-run." Better to under-contribute than to leak or to ship a vague rule.

## Step 5: Classify each candidate by target pack and group

Map each generalized candidate to a target pack by its glob/subject:

- **An existing populated pack** (`python`, `postgres`, `nextjs-react`, `llm`,
  `beancount`) → "expand `<pack>`".
- **A placeholder pack** (`streamlit`, `pandas`, `kotlin`, `swift-ios`,
  `flutter`, `mcp-server`) → "populate the `<pack>` placeholder".
- **A stack with no pack yet** → "new pack `<stack>`". For a new pack, also
  sketch the 4-part skeleton CONTRIBUTING.md asks for (`plugin.json`,
  `convention_map.md`, `security_map.md` if applicable, `checks.yml.fragment` /
  `semgrep/*.yml` if applicable) — a proposal outline, not the files.

**Group candidates into one proposal issue per target pack** (the ratified
grouping). All candidates mapping to the same pack become a single "expand
`<pack>`" proposal; a second pack gets its own issue. This matches how
CONTRIBUTING.md frames "a pack" as the contribution unit and how a maintainer
triages and relabels. The per-group consent in Step 6 still lets the human drop
individual bullets from a group before it files.

## Step 6: Render each pack group as its proposed issue — always

For **every** pack group, construct and print the exact issue that *would* be
filed, so the human reviews the full payload before consenting. Do this whether
or not `--execute` was passed.

**Title:** `[<consumer>] <pack> pack: <n> convention(s) from real use` (or, for a
new pack, `[<consumer>] New pack proposal: <stack>`). The `[<consumer>]` prefix
tells cross-repo readers which project the conventions were grown in; omit it if
no consumer name was found.

**Label:** `enhancement` for every proposal (this is the `pack_or_convention`
shape, not the `bug_report` shape `/report-issues` uses).

**Body:** map onto the `pack_or_convention.md` issue-template shape. Render it as
literal markdown the human can read in full:

```
**Stack / pack**
<target pack — e.g. "existing `python` pack" / "the `flutter` placeholder" /
"a new `<stack>` pack">

**Where these come from**
<per-candidate provenance from Step 3: "recurred across Rounds N and M" where
found; where not found, the human's attestation collected in Step 3 and
generalized in Step 4 — "grown in <consumer>; catches <the recurring mistake,
generalized>">

**Model provenance:** <generating model/agent family + rough date, only when
the human offered it in Step 3 — omit this line entirely when unknown>

**What it would contain**
- convention_map bullets (glob → rule):
  <the generalized bullets from Step 4, each with its placeholder glob>
- security_map entries, if any:
  <generalized security entries, only under --include-security>
- Mechanical checks (grep / semgrep), if applicable:
  <generalized check ids + patterns from checks.project.yml, placeholder paths>

**Have you used Sysop on the project this came from?**
Yes — grown in <consumer> (via .claude/*.project.* overlay / /contribute-convention).

**Anything else**
<coined placeholders to reconcile; new-pack skeleton sketch; anything flagged>
```

Include only the sub-parts a group actually has. Do not invent content. **Show
every character** — this is the no-fingerprints contract: the human's chance to
catch a leaked path or an over-generalized rule before it's public.

Before consent, print one reminder: *"These bodies are exactly what will be
filed publicly on `<target>`. If any still contains a real path, name, or
identifier you don't want public, or a rule that reads too vaguely to act on,
tell me to revise it or edit the overlay and re-run — I will not file anything
you haven't reviewed."*

If `--execute` was **not** passed, stop here: print `Dry-run. Re-run with
--execute to choose which pack proposals to file.` and stop. Nothing is filed or
edited.

## Step 7: Per-pack consent (mandatory)

Only under `--execute`. Get explicit consent **per pack group** — the sibling
skills gate one item at a time on purpose (`/report-issues` Step 3,
`/review-close` Steps 3c/2d), and it matches this skill's privacy model: the
human approves each generalized body individually, having just read it.

Use `AskUserQuestion`, but **never enumerate all groups in one question** —
`AskUserQuestion` caps options (~4) and a full title overflows a label. Ask per
pack group (a single "File this proposal?"), or batch at most **4 groups per
question** with a short label (the pack name) and the full title in the option
description. Consent is a **pure yes/no pick** — every no-provenance group
already carries the human's attestation gathered in Step 3 and shown in the
Step 6 body, so nothing new is collected here (splicing free text in at consent
would break shown-equals-filed). Nothing is filed unless the human explicitly
picks it; an unselected group is skipped, never defaulted-in.

If the human consents to none, print `Nothing selected. No proposals filed.` and
stop.

## Step 8: File each consented group and annotate the overlay

For each selected pack group, in order:

1. **Soft duplicate check:** run
   `gh issue list --repo <target> --state all --search '<pack> pack convention'`,
   searching on the plain pack + subject **without** the `[<consumer>]` prefix
   (brackets weaken GitHub phrase matching). If a clearly-matching open proposal
   already exists, surface it (`possible duplicate: <url>`) and ask whether to
   file anyway (default: skip).

2. **File it — pass the body as a file, never inline.** Convention bodies are
   dense with backticks, `$`, and code spans **by design** (glob patterns, code
   examples, `re.compile()` snippets). Inlining that into a double-quoted
   `--body "<body>"` is a real hazard: bash would run backtick/`$()`
   substitutions and break on stray quotes — silently filing something
   *different* from what the human approved (breaking shown-equals-filed) and,
   worst case, **executing** approved *text* as a shell command. This is the
   exact hazard `/report-issues` Step 4 fixed. So:

   - Write the exact rendered body (identical to Step 6) to a temporary file
     **outside the repo** (e.g. `"$TMPDIR/sysop-pack-<pack>.md"`) using the `Write`
     tool — never echo it through the shell.
   - Keep the `--title` a plain one-line summary and pass it **single-quoted**;
     if the title contains a backtick, `$`, or a single quote, render a clean
     equivalent (the full text still rides in the body file).
   - Then:
     ```bash
     gh issue create --repo <target> --title '<title>' --label enhancement --body-file "$TMPDIR/sysop-pack-<pack>.md"
     ```
   - Delete the temp file after the call returns (success or failure).

   `gh issue create` prints the new issue URL — capture it. If the call fails
   (auth lapse, network), **do not** annotate the overlay; record the failure
   and move on. If the `enhancement` label doesn't exist (a fresh fork may not
   have it), retry once without `--label` and note it.

3. **Annotate the source overlay — per candidate, so the Step-2 backstop is
   precise** (via `Edit`, surgically). The two overlay formats need different
   marker shapes:

   - **`convention_map.project.md` / `security_map.project.md` sections** — at the
     end of each section that contributed ≥1 bullet, append:
     `> Contributed upstream: <issue url> (<today's date, YYYY-MM-DD>) — filed: <short subjects of the bullets that went up>`.
     The `filed:` list is what makes the backstop **per-bullet**: a later run
     excludes only the named bullets and leaves the section's remainder eligible
     (Step 2). This uses the overlay's own `>`-annotation shape (the same shape as
     its `> checks.yml:` / `> AST-backed equivalents:` provenance lines).
   - **`checks.project.yml` entries** — insert a YAML comment on the line above
     each contributed entry:
     `# Contributed upstream: <issue url> (<today's date, YYYY-MM-DD>)`. A `>`
     line is a YAML block-scalar indicator, **not** a comment, so checks must use
     `#` — matching the marker Step 2 looks for.

   Both markers are durable because `.claude/*.project.*` is never touched by the
   installer. Leave every non-contributed section / entry untouched.

## Step 9: Report

Print a summary:

```
Contributed to <target>:

Filed:        <N> pack proposal(s) (<pack> → <url>, one per line)
Skipped:      <N> not selected · <N> possible-duplicate · <N> failed-to-file
Excluded:     <N> already-upstream (verbatim pack rule) · <N> suppression entries ·
              <N> needs-manual-generalization (listed below)
Already sent: <N> candidates carrying a prior Contributed-upstream marker (unchanged)

<if any needs-manual-generalization: list each with the reason it couldn't be
 auto-generalized>

Overlay annotated: <N candidates> marked Contributed upstream (uncommitted —
commit the annotations when ready)
```

The overlay edits are left uncommitted, same contract as every other Sysop skill:
the human reviews and commits the annotations intentionally.

## Design notes (reference)

- **Skill, not a script.** Like `/report-issues`, the input is deliberately
  loose consumer-restructurable markdown and the core work — generalizing a rule
  into fingerprint-free placeholder vocabulary without gutting it — is judgment,
  not parsing. A rigid parser would choke on a reshaped overlay (the failure
  Phase 68 removed from the check loader) *and* couldn't do the generalization at
  all. The one irreversible side effect (`gh issue create`) is human-gated
  regardless. If a future consumer's overlay volume makes the manual render
  tedious, a helper that emits a structured candidate list is the escape hatch —
  a revisit, not built now.
- **Overlay, not base maps.** Reads only `.claude/*.project.*` — the durable home
  for *this project's* promoted conventions (Phase 78). The Sysop-shipped base
  maps are already upstream; reading them as a contribution source would propose
  Sysop's own conventions back to Sysop. The base map is read once, in Step 2, only
  to *exclude* verbatim restatements.
- **Provenance shown, not asserted.** CONTRIBUTING.md asks a human contributor to
  attest where a convention came from. This skill surfaces the `review_tasks.md`
  cross-round evidence directly when it exists, and asks for an honest one-line
  attestation when it doesn't — never fabricating a recurrence count. That is the
  earn-their-way bar, mechanized.
- **Upstream, not local.** Files to `getsysop/sysop` by default; `--repo` covers
  forks. The give-back only works if it reaches the maintainer.
- **v1 scope.** Generalize + provenance + file a *proposal issue* (per
  CONTRIBUTING's "open an issue before a large PR"). **Out:** auto-opening PRs,
  auto-editing `packs/`, any write to the Sysop repo beyond an issue.
