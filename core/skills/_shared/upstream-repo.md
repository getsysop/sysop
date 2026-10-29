# Resolving the upstream Sysop repo (shared protocol)

Read by the three GitHub-touching give-back skills — `/report-issues`,
`/contribute-convention`, `/share-wins`. All three file *outward*, to the Sysop
repo, not to the consumer's own repo, so "which repo" is a question with a
disclosure consequence: the shipped default is a **public** repo, and consumer
friction logs and convention overlays routinely embed security context (an open
vulnerability, a PII-scrub gap, the contents of a review batch).

This partial is the single source of truth for three things each skill needs
before it touches the network: **which repo**, **is it public**, and **does what
we're about to file look sensitive**. None of it redacts anything or blocks a
run — redaction stays the human's call, made by editing the source file, and
per-entry consent stays the real gate.

---

## A. Resolve the target repo

Three tiers, highest precedence first. Stop at the first that yields a slug.

1. **`--repo owner/name`** — the per-run override, passed in `$ARGUMENTS`. Always
   wins. Use for one-off exceptions (filing a single generic entry to public
   upstream from a project whose standing target is private, or vice versa).
2. **`<project>/CLAUDE.md § Sysop upstream repo`** — the consumer's durable
   default. Same "consumer declares its shape" pattern as `§ Merge policy` and
   `§ Pre-merge verification`. Read the first non-empty line under the header;
   strip surrounding whitespace and backticks (both `` `owner/name` `` and a
   bare `owner/name` are valid — the backticked form is the documented
   template). A valid slug matches `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`.
3. **`getsysop/sysop`** — the shipped default, used only when neither of the
   above applies. This repo is **public**.

**Before concluding "absent", look for a near-miss heading.** The exact-match
rule above fails *open* — an unmatched heading is indistinguishable from no
heading, and routes to the public default. So when tier 2 finds nothing, scan
the file's `##` headings for one that plausibly meant this section: anything
containing `upstream repo`, or the pre-rename spellings (`Jig upstream repo`,
`wade-flow upstream repo` — the product was renamed twice). If you find one,
**stop** rather than defaulting, and say which heading you found and what the
exact spelling is. A consumer whose heading is one word off is exactly the
consumer who believes they are protected.

**If the section is present but yields no valid slug, stop — do not fall back to
the default.** A consumer who wrote that section did so to keep something *off*
the public repo; silently defaulting to `getsysop/sysop` because their line had
a typo or a full URL in it is precisely the failure this config exists to
prevent. Print what you found and what shape you expected, and stop:

```
Cannot resolve the upstream repo. CLAUDE.md § Sysop upstream repo is present but
its first line ("<what you found>") is not an owner/name slug. Fix the section
or pass --repo owner/name. Refusing to fall back to the public default.
```

An **absent** section is not an error — that's tier 3, the ordinary case for a
consumer who never configured one.

Print the resolved target once, plainly, before anything is filed. Say which
tier produced it — so the human can see whether their config was actually read —
**and its visibility from § B**, so a healthy private run and a degraded
unverifiable one are never byte-identical on screen. One line, exactly one
`source:` value (it is a choice, not a menu):

```
Target repo: <owner/name>   (source: --repo)   visibility: PUBLIC [verified]
Target repo: <owner/name>   (source: CLAUDE.md § Sysop upstream repo)   visibility: PRIVATE [verified]
Target repo: <owner/name>   (source: default)   visibility: PUBLIC [assumed]
```

**When `--repo` overrides a configured section, say so on its own line** — a
per-run flag silently displacing a standing privacy decision is the one
precedence case worth narrating: `note: --repo <slug> overrides CLAUDE.md
§ Sysop upstream repo (<configured slug>) for this run only.`

Every `gh` call in the skill passes the resolved target explicitly (`--repo
<target>`, or the `<owner>`/`<name>` GraphQL variables). Never rely on the
current directory's remote — that is the consumer's project, not Sysop.

## B. Resolve the target's visibility

Ask GitHub. This is a read-only preflight:

```bash
gh repo view <owner/name> --json visibility --jq .visibility
```

`PUBLIC` / `PRIVATE` / `INTERNAL` on success. **`INTERNAL` nudges** — it is not
public, but it is visible to every member of the org, which is wider than the
"only collaborators" mental model a consumer configuring a private target
usually holds. Only a `[verified] PRIVATE` result suppresses the nudge; treat
everything else as needing one.

The probe is **advisory and non-fatal**. It fails on an offline machine, an
unauthenticated `gh`, a rate limit, or a target you cannot see — none of which
should end the run, and a 404 here does *not* prove the repo is missing (a
private repo you lack access to 404s identically). The skills' existing
"first real `gh` call returned not-found → stop" guard still covers a genuinely
unreachable target; this probe never triggers that stop on its own. If the
command hangs rather than failing fast, treat it as unavailable and move on.

**When the probe fails, fall back to what can be known locally:**

- **Target is the shipped default `getsysop/sysop`** → treat as **PUBLIC**.
  Not a guess: it is the public upstream by definition, which is the whole
  reason this file exists.
- **Target is anything else** (a configured section or a `--repo` override) →
  visibility is **UNKNOWN**. Do not assume private. A consumer who configured a
  private target is the likely case, but "likely" is not "verified", and the
  cost of being wrong is one-directional.

Carry the provenance into every line you print about visibility:

- `[verified]` — the `gh` probe answered.
- `[assumed]` — the probe failed and the fallback above supplied the answer.

This **borrows the bracket-marker convention** of `_shared/fanout-evidence.md`
without reusing its vocabulary, and the difference is deliberate rather than
incidental: that partial's pair is `[verified]` / `[reported]`, and its
`[verified]` means *"I opened the cited `file:line` myself."* Here `[verified]`
means *"GitHub answered when asked."* Same shape, different claim — do not treat
a marker from one context as interchangeable with the other.

Like that partial's markers, these are **self-declared labels, not machine-checked
guarantees**. Nothing in this file executes: it is prose an agent follows, so
every property here holds only as well as the agent following it. Read
`[verified] PRIVATE` as *"the probe said private,"* never as *"filing here is
guaranteed safe."*

## C. Sensitivity nudge

Fires at the **consent step**, over the **exact rendered text you are about to
send** — every field, not only the body. **The title is in scope**: it is the
most-read field, it is usually composed separately from the body, and a title is
a perfectly ordinary place to put the thing that makes an entry sensitive. So is
any label, heading, or metadata line the payload carries.

Local, free, no network. Run it **only when § B's visibility is `PUBLIC`,
`INTERNAL`, or `UNKNOWN`** — a `[verified] PRIVATE` target is the configuration
working and needs no warning.

**Match on whole words, not substrings.** This is the difference between a
useful nudge and one nobody reads: unbounded `RCE` matches *source*, *force*,
and *porcelain*; `PHI` matches *graphics*; `PII` and `token` behave the same. On
a real friction log that noise buries the one true hit. Require a word boundary
on every term below, and treat the short all-caps acronyms as standalone tokens
only.

- `CVE-…`, `GHSA-…`, `CWE-…`
- `vulnerability` / `vulnerable`, `exploit`, `injection`, `traversal`, `SSRF`,
  `XSS`, `RCE`, `bypass`, `unauthorized`, `cross-tenant`
- `secret`, `credential`, `password`, `api key`, `token` *(as a standalone word
  — not `tokenize`, `tokens_used`)*, `.env`, `hardcoded`
- `PII`, `PHI`, `patient`, `customer data`
- `unpatched`, `unfixed`, `not yet fixed`, `still open`
- `security review`, `security audit`, `security_map`, `review_tasks`

Bare severity words (`HIGH`, `CRITICAL`) are deliberately **not** triggers on
their own — they fire on ordinary bug reports and would train the human to skim
past the nudge. The same logic is why the boundary rule is not optional.

**The list is a floor, not the test.** It cannot match a paraphrase, and the
most sensitive sentence in a friction log is often plain English with no listed
term in it — *"an outsider can read another tenant's rows"*, an internal
hostname, a stack trace with real paths, a customer name. So after the keyword
pass, **read the payload once and ask the question the keywords are a proxy
for**: *would this tell a stranger something about this project's security
posture, its data, or its people that the owner would not post deliberately?*
Report what that read finds alongside the keyword hits, and say which is which.

**A corpus whose subject is security defeats a security-keyword scan.**
`/contribute-convention` under `--include-security` reads
`.claude/security_map.project.md`, where those terms *are the subject matter* —
every item matches, and a nudge that fires on everything is the alarm fatigue
this section otherwise guards against. So for that corpus, **substitute a
different question**: generalization strips *fingerprints*, not *subject
matter*, so scan instead for what survived it — real paths, hostnames, service
or product names, env var names, customer or person names, version strings, and
any `CVE-`/`GHSA-` id tying a generic rule to a specific incident. The keyword
list stays in force for the other two skills' corpora.

When the nudge fires, be specific about which items and why, and state the
provenance:

```
⚠  Target <owner/name> is PUBLIC [verified] and 2 of the 5 items below reference
   security context: ISSUE-0008 (matches "unfixed", "review_tasks"), ISSUE-0011
   (matches "credential"). Anything filed there is visible to anyone.
   Redact by editing <source file> and re-running — I will not auto-redact.
   To send these somewhere else, set CLAUDE.md § Sysop upstream repo or pass
   --repo owner/name.
```

Under `INTERNAL`, name the actual audience — "not public" is the wrong summary:

```
⚠  Target <owner/name> is INTERNAL [verified] — visible to every member of that
   org, not only collaborators — and 2 of the 5 items below reference security
   context: ... . Confirm before continuing.
```

Under `UNKNOWN`, say so honestly rather than asserting exposure:

```
⚠  Could not verify the visibility of <owner/name> (gh probe unavailable), and 2
   of the 5 items below reference security context: ... . If that repo is public,
   filing exposes them. Confirm before continuing.
```

**Keep the warning next to the decision.** A skill that batches consent must
re-state the destination and its visibility **in each batch**, and name any
flagged item *in that batch* — one warning printed before a ten-item run is
three prompts upstream by the time the human approves the entry it was about. If
the consent prompt has option labels, a flagged item says so in its own label.

The nudge is a **warning, never a filter**: it drops nothing, edits nothing, and
does not change what per-entry consent offers. Its whole job is to make sure the
human reads the destination and the sensitive item in the same breath.

---

**Why this lives in CLAUDE.md rather than a skill edit.** Shipped skills are
outside Sysop's customization-preservation scope on purpose — they take the
standard overwrite on every update, with no silent prompt-forks (WORKFLOW.md
§ 8.2c). So a consumer cannot durably redirect these skills by editing them.
`CLAUDE.md` is the sanctioned durable home for consumer-side skill
configuration, exactly as it is for `§ Merge policy`.
