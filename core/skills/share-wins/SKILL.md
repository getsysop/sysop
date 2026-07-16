---
name: share-wins
description: Share the `[good]` positive-signal entries from SYSOP_ISSUES.md upstream as one aggregated comment on a standing "Wins" Discussion in the Sysop repo — per-entry human consent, shown-equals-posted, then flip each shared entry to `Status: Shared` with a back-ref so re-runs never double-post. Dry-run by default. GitHub-specific by design.
argument-hint: "[--execute] [--repo owner/name]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The **positive-signal** half of Sysop's give-back loop. `/review-close` Step 7
*captures* both kinds of signal into `SYSOP_ISSUES.md`: friction (`ISSUE-NNNN`
entries — bugs in Sysop-shipped content) and wins (`GOOD-NNNN` entries, marked
`[good]` — something Sysop did notably well that's worth *protecting from a
future change*). Two sibling skills transport the friction (`/report-issues`)
and the locally-grown conventions (`/contribute-convention`) upstream. This skill
transports the third thing: the wins.

Without it, a tester round is asymmetric — it tells the maintainer what to
**fix** but not what to **protect**. The `[good]` capture worked (Phase 99), but
the entries died in a local file: nobody upstream ever saw them, so the next
change could quietly "fix" the exact behavior a tester relied on. This closes
that gap.

**This is a GitHub-touching skill** — the third give-back skill after
`/report-issues` and `/contribute-convention`, whose transport shape it mirrors
(permission guard → `gh auth` → resolve upstream repo → render → per-entry
consent → post → annotate the source → report). Like them — and unlike
`/pr-dependabot`, which operates on *your own* repo — it sends **upstream to the
Sysop repo** (`getsysop/sysop` by default). That direction is the whole point.

**Why a Discussion, not an Issue.** A win is not a defect or a proposal — it has
no open/close lifecycle and creates no work item. It is social proof plus a
durable "don't regress this" registry. So it belongs in **GitHub Discussions**,
not the issue tracker, and all of a round's wins go into **one aggregated
comment** on a standing "Wins" thread — not one issue each (the deliberate
contrast with `/report-issues`, which files one issue per entry). This is the
one skill in the family that posts to Discussions via the GraphQL API rather
than `gh issue`.

**The privacy being spent is yours.** A `[good]` entry quotes what worked — skill
names, error text, sometimes details of your setup. So: **per-entry consent is
mandatory**, **dry-run is the default**, and the skill shows you the exact
comment body — every character that would leave your machine — before anything is
posted. It never auto-redacts (lossy, and the call is yours) and never shares an
entry you didn't explicitly pick.

## Pre-flight: Permission Guard

This skill shells out to `gh api graphql` (both to resolve the target Discussion
and to post the comment) and edits `SYSOP_ISSUES.md` in place. Its only network
side effect is posting a Discussion comment (and, once, creating the standing
Wins thread if it doesn't exist yet) — and only under `--execute` after you pick
which entries.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(gh api graphql:*)` — resolve the repo/category/discussion **and** post the
  comment. This is **one rule for both** because a GraphQL query (read) and a
  GraphQL mutation (write) are the *same* `gh api graphql` command — the
  permission classifier cannot tell them apart, so the write path the documented
  happy path requires needs this rule listed.

If it is missing, stop with the `_shared/permission-guard.md` § Algorithm step 4
message (one-line reason: "shares SYSOP_ISSUES.md `[good]` entries upstream as a
Sysop Discussion comment; shells `gh api graphql` against the Sysop repo"). Do
not proceed.

`gh auth status` is read-only and auto-approved under `auto` mode — it is not
listed here (per `_shared/permission-guard.md` § Notes: don't list read-only
ops). The skill's own read queries *are* `gh api graphql` calls (resolving the
repo/thread), but they share that command with the write mutation, so the single
`Bash(gh api graphql:*)` rule above already covers them — there is no separate
read-only rule to add. Editing `SYSOP_ISSUES.md` uses the `Edit` tool, not Bash,
so it needs no allow-rule.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and
continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **`--execute`** — actually post the comment for the entries you consent to.
  **Without it, the skill is read-only** (reads + renders + prints the plan,
  posts nothing, edits nothing).
- **`--repo owner/name`** — override the upstream target repo. Default:
  `getsysop/sysop`. Use this if you forked Sysop, or you're a tester on a private
  Sysop mirror and want wins on that repo (both `getsysop/sysop` and the tester
  mirror have Discussions enabled).

There is no `--include-resolved` analog (`/report-issues` has one): a win has
only two states — `Good — keep` (eligible) and `Shared` (already sent) — so
there is nothing extra to opt into.

## Step 0.5: Confirm `gh` is authenticated

Run `gh auth status`. If it reports not-logged-in, stop and tell the human to
run `gh auth login` (suggest the `! gh auth login` in-session form). Do not
attempt to authenticate on their behalf. Posting to Discussions needs a token
with the `repo` (or `public_repo`) scope — the default `gh auth login` grant
covers it; if a mutation later fails with a scope error, tell the human to run
`gh auth refresh -s repo` rather than looping.

## Step 0.6: Resolve the target repo

Default target is **`getsysop/sysop`** — the upstream Sysop repo, *not* the current
project's own repo. Override with `--repo owner/name`. Print the target once,
plainly, so the human sees where the win lands before anything is posted:
`Target repo for wins: <owner/name>`. Every `gh api graphql` call in this skill
passes the resolved `<owner>`/`<name>` explicitly — never rely on the current
directory's remote, which is the consumer's project, not Sysop.

If `getsysop/sysop` isn't reachable from where you are (e.g. the GitHub rename
hasn't propagated, or you're filing against a fork), the first resolve query will
return a null repository — stop and tell the human the target repo isn't
reachable (pass `--repo` with the correct slug) rather than looping.

## Step 1: Read and classify the `[good]` entries

Read `SYSOP_ISSUES.md` at the **consumer-repo root** (NOT under `.claude/`). If
it's missing, stop with one line: `note: SYSOP_ISSUES.md not present — no wins to
share. (Re-run bash install.sh to seed it, or capture wins via /review-close
Step 7 first.)` and stop.

The file mixes friction (`ISSUE-NNNN`) and wins (`GOOD-NNNN`). **This skill
handles only the wins** — the `[good]` entries. An entry is a win if its heading
carries the `[good]` marker (`## GOOD-NNNN — <title> (<date>)  [good]`) and/or its
`**Status:**` is a win status. Read them with judgment: **this file is
deliberately loose, consumer-restructurable markdown** — the seed template invites
"you can restructure freely" — so do not assume a rigid shape. If an entry looks
like a win but its status is missing or ambiguous, surface it to the human as
"unclear — is this a win to share? (y/n)" rather than silently guessing.

Classify each `[good]` entry by `**Status:**`:

| Status | Eligible to share? |
|---|---|
| `Good — keep` | **yes** |
| `Shared` | no — already sent (skip) |

**Backstop, independent of status:** an entry that already carries a `**Shared:**
<url>` line (written by a prior run, Step 5) is **ineligible** no matter what its
`Status:` says. This is what keeps a re-run from double-posting even if a status
flip was missed. Friction (`ISSUE-NNNN`) entries are out of scope here — ignore
them; they're `/report-issues`' job.

Read the consumer name from the file's H1 (`# Sysop Issues — <consumer>`) — you'll
name it in the comment so cross-repo readers know which project the win came from.
If the H1 has no name, omit it.

If no `[good]` entries are eligible, print `No shareable [good] entries in
SYSOP_ISSUES.md. Nothing to share.` and stop.

## Step 2: Render the wins — always

For **every** eligible entry, print the exact win section it would contribute to
the aggregated comment, so the human reads the full text of each candidate before
consenting. Do this whether or not `--execute` was passed.

Each win renders as one section of the comment body:

```
### <entry title>
<the entry's ### What worked, verbatim>
```

Keep the reporter's words; do not rewrite them. Include only what the entry
actually has. Then print the **full assembled comment** exactly as it would be
posted if every eligible entry were included — this is the shown-equals-posted
payload (the consented subset is re-shown in Step 4 before the actual post):

```
## Wins from <consumer> — <today's date, YYYY-MM-DD>

Positive signal captured while running Sysop — things that worked notably well
and are worth protecting from a future change.

### <win 1 title>
<win 1 ### What worked>

### <win 2 title>
<win 2 ### What worked>

---
Shared from <consumer> via /review-close Step 7 + /share-wins. Sysop commit/install: <from .claude/sysop.lock if readable, else "unknown">.
```

Omit the `<consumer>` bits if no consumer name was found.

**Redaction is the human's call, done by editing the log first.** Before the
consent step, print one reminder — substituting the **resolved target** (the
default `getsysop/sysop`, or the `--repo` override): *"This comment is exactly what
will be posted to `<target>`'s Wins discussion — visible to anyone who can see
that repo. If any of it names a path, secret, or detail you don't want exposed
there, edit `SYSOP_ISSUES.md` to redact it and re-run — I will not auto-redact."*
(Don't hardcode "publicly" — with `--repo` pointed at a private fork or tester
mirror, the discussion is visible only to that repo's collaborators.)

If `--execute` was **not** passed, stop here: print `Dry-run. Re-run with
--execute to choose which wins to share.` and stop. Nothing is posted or edited.

## Step 3: Per-entry consent (mandatory)

Only under `--execute`. Get explicit consent **per entry** — the sibling skills
gate one item at a time on purpose (`/report-issues` Step 3, `/contribute-convention`
Step 7), and it matches this skill's privacy model: the human approves each win
individually, having just read its full text in Step 2. The *transport* is
batched (one comment), but the *consent* is per win — so a human can share three
wins and hold back a fourth that named something they'd rather not expose.

Use `AskUserQuestion`, but **never enumerate all entries in one question** —
`AskUserQuestion` caps options per question (~4) and a full win title overflows an
option label. Ask per entry (a single yes/no "Share this win?"), or batch at most
**4 entries per question** with a short option label (the `GOOD-NNNN` id) and the
full title in the option description. Nothing is shared unless the human
explicitly picks it; an unselected entry is skipped, never defaulted-in.

If the human consents to none, print `Nothing selected. No wins shared.` and stop.

## Step 4: Resolve-or-create the standing Wins discussion, then post one comment

Only under `--execute`, with ≥1 consented entry.

1. **Resolve the repo id + categories.** Query the target repo for its `id`
   (repositoryId) and its discussion categories. Bind the string args with `-f`
   (raw string) — **not** `-F` — so an all-numeric `owner`/`name` (legal on
   GitHub) isn't coerced to a JSON number; reserve `-F` for the one file-read
   field (`body=@<file>`) in step 4:

   ```bash
   gh api graphql \
     -f owner='<owner>' -f name='<name>' \
     -f query='query($owner:String!,$name:String!){
       repository(owner:$owner,name:$name){
         id
         discussionCategories(first:25){ nodes{ id name } }
       }
     }'
   ```

   If `repository` is null, the target isn't reachable — stop (see Step 0.6).
   Then pick the category for **new** discussions: prefer the one named `Show and
   tell` (GitHub's default home for "here's something that worked"); if absent
   (a fork with custom categories), fall back to `General` (a default that's
   almost always present); if neither exists, record "no category" and **keep
   going** — a category is needed only on the *create* path (step 3), so its
   absence must not stop the common case where the thread already exists and only
   a comment is needed. Record the chosen category `id` (categoryId) for step 3.

2. **Find the standing Wins thread.** Query existing discussions oldest-first
   (the standing thread, once created, has the lowest number, so it's always on
   the first page):

   ```bash
   gh api graphql \
     -f owner='<owner>' -f name='<name>' \
     -f query='query($owner:String!,$name:String!){
       repository(owner:$owner,name:$name){
         discussions(first:50, orderBy:{field:CREATED_AT, direction:ASC}){
           nodes{ id number title url }
         }
       }
     }'
   ```

   Match the standing thread by title: prefer an **exact** match on the canonical
   title `Wins — what Sysop did well`; if none, match the first discussion whose
   title **contains** `Wins` (case-insensitive) — this tolerates an emoji prefix
   or a maintainer rename. If multiple match, pick the **oldest** (lowest
   `number`) so runs converge on one thread. Record its `id` (discussionId) and
   `url`. If a thread was found, go straight to step 4 (no category needed).

3. **Create the thread once, if absent.** Only if step 2 found no Wins thread.
   This is the sole step that needs a category — so **stop here** (not in step 1)
   if step 1 found none: print a clear note asking the human to enable a
   `Show and tell` or `General` discussion category on the target repo, and stop.
   Otherwise create the thread in the category from step 1 — an evergreen thread
   whose *body* is a short intro; the round's wins go in the **comment** (step 4),
   so every round — including this first one — appends uniformly. The intro body
   is a fixed constant with no shell-special characters (no `'`, backtick, or `$`),
   so an inline `-f` value is safe here:

   ```bash
   gh api graphql \
     -f repositoryId='<repositoryId>' -f categoryId='<categoryId>' \
     -f title='Wins — what Sysop did well' \
     -f body='A running thread of positive signal from real Sysop use — things worth protecting from a future change. Each comment collects the wins from one Sysop project for a round, shared via /share-wins.' \
     -f query='mutation($repositoryId:ID!,$categoryId:ID!,$title:String!,$body:String!){
       createDiscussion(input:{repositoryId:$repositoryId,categoryId:$categoryId,title:$title,body:$body}){
         discussion{ id url }
       }
     }'
   ```

   Capture the new discussion's `id` (discussionId) and `url`. If the create
   fails, stop — there is nothing to comment into; record the failure and do
   **not** touch the log.

4. **Assemble the final comment and post it — pass the body as a file, never
   inline.** Build the comment body from **only the consented entries** (Step 3),
   in the exact shape Step 2 showed. The body contains backticks, `$`, and code
   spans **by design** (wins quote skill names, error text, `run_checks`
   invocations). Inlining that into a shell string is a real hazard: bash would
   run backtick/`$()` substitutions and break on stray quotes — silently posting
   something *different* from what the human approved (breaking shown-equals-posted)
   and, worst case, **executing** approved *text* as a shell command. This is the
   exact hazard `/report-issues` Step 4 fixed. So:

   - Write the exact assembled body to a temporary file **outside the repo**
     (e.g. `"$TMPDIR/sysop-wins-<date>.md"`) using the `Write` tool — never echo
     it through the shell. It must be **byte-identical** to what you print next.
   - Print the final body once — `Posting this comment to <thread url>:` followed
     by the body — so the human sees the exact consented payload immediately
     before it goes out.
   - Post it, binding the file to the GraphQL `$body` **String** variable with
     `-F body=@<file>` (the `@file` read is a `-F`-only feature — gh reads the
     value from the file with no shell interpolation; a multi-line markdown body
     never triggers `-F`'s literal-`true`/`false`/`null`/integer coercion). Bind
     the opaque `discussionId` with `-f`:

     ```bash
     gh api graphql \
       -f discussionId='<discussionId>' \
       -F body=@"$TMPDIR/sysop-wins-<date>.md" \
       -f query='mutation($discussionId:ID!,$body:String!){
         addDiscussionComment(input:{discussionId:$discussionId,body:$body}){
           comment{ url }
         }
       }'
     ```

   - Delete the temp file after the call returns (success or failure).

   Capture the returned `comment.url`. If the post fails (auth lapse, scope,
   network), **do not** edit the log; record the failure and stop — every
   consented entry keeps `Status: Good — keep` so a re-run retries cleanly.

## Step 5: Flip each shared entry and record the URL

All consented wins went into the **one** comment, so they share the **same**
comment URL. For each entry that was in the posted comment, edit `SYSOP_ISSUES.md`
(via `Edit`, keyed on the unique `## GOOD-NNNN` anchor so the change is surgical):

- Change its `**Status:**` line to `**Status:** Shared`.
- Insert a line immediately below the Status line:
  `**Shared:** <comment url> (<today's date, YYYY-MM-DD>)`.

Leave every other entry — unselected, or a friction `ISSUE-NNNN` entry — exactly
as it was. The `Shared:` line is the durable back-reference (and the Step 1
ineligibility backstop) so a later `/share-wins` run — or a human — sees the win is
already upstream and where it went.

**The post and the flips are not atomic — close the gap loudly.** The comment
posts once, then each entry is flipped one `Edit` at a time. If the post
succeeded but a flip **fails** for some entry (file locked, anchor not found),
that entry keeps `Status: Good — keep` with no `**Shared:**` line — and because
`/share-wins` has no discussion-side duplicate check, a naive re-run would post it
**again**. So if any flip fails after a successful post, do **not** silently
move on: print a prominent warning naming the un-flipped `GOOD-NNNN` id(s), state
plainly that they are **already upstream at `<comment url>`**, and instruct the
human to hand-add the `**Shared:** <comment url> (<date>)` line to each before any
re-run (that line alone is the Step 1 ineligibility backstop). This is the one
re-post window; naming it is how it stays closed.

## Step 6: Report

Print a summary:

```
Shared to <target> — Wins discussion: <thread url>

Shared:      <N> win(s) in one comment → <comment url>
Skipped:     <N> not selected
Ineligible:  <N> already Shared (unchanged)

SYSOP_ISSUES.md edited: <N status flips> (uncommitted — commit the flips when ready)
```

The log edits are left uncommitted, same contract as every other Sysop skill: the
human reviews and commits the status flips intentionally.

## Design notes (reference)

- **Skill, not a script.** Like `/report-issues` and `/contribute-convention`, the
  input is deliberately loose consumer-restructurable markdown; a rigid parser
  would choke on a reshaped log (the failure Phase 68 removed from the check
  loader). Agent-read markdown is the robust tool; the one irreversible side
  effect (posting the comment) is human-gated regardless.
- **Discussion, not Issue.** A win is "protect this," not tracked work — it has no
  open/close lifecycle. Filing it as an issue would create triage load for the
  maintainer for something that needs none. A Discussion comment is the right
  shape (social proof + a durable registry), and a round's wins **aggregate into
  one comment**, not one issue each — the deliberate contrast with `/report-issues`.
- **Standing thread, resolve-or-create.** There is one evergreen "Wins" discussion
  per repo; the skill finds it by title and creates it once if absent, so there's
  **no maintainer-seeding prerequisite** and no fragile hardcoded discussion
  number — the "constant" is the category (`Show and tell`) + the canonical title.
  It self-heals: the first tester to run `/share-wins` establishes the thread; the
  oldest-match rule converges a rare create race onto one thread.
- **Upstream, not local.** Posts to `getsysop/sysop` by default; `--repo` covers
  forks and the tester mirror. The give-back only works if the win reaches the
  maintainer.
- **v1 scope.** Resolve/create the thread + post **one aggregated comment** +
  flip the source entries. **Out:** reactions automation, filing issues, opening
  PRs, any write to the Sysop repo beyond the Wins discussion + its comment.
