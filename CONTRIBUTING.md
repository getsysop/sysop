# Contributing to Sysop

Thanks for being here. Sysop is a self-improving development workflow for AI-assisted coding — deterministic checks, adversarial plan review, and conventions that get *promoted* from recurring review findings so the workflow stops re-catching what it already knows.

The packs are the part you can improve for everyone. Every convention in them is a documented, generalized failure mode of an AI coding agent — a mistake an agent actually made on a real project, caught in review often enough to earn a rule, and mechanized into a deterministic check where the pattern allows. Contributing the conventions your own project promoted raises the floor for every consumer whose agent hasn't made that mistake yet. That shared corpus is why Sysop is open — and it's guarded by the [trust policy](#contribution-trust-policy) below, because pack content runs in privileged places and has to be curated accordingly.

Contributions are welcome, especially the kinds below. One note on expectations first, because it's what keeps this sustainable.

## How this project is maintained

This is maintained **casually, as-is**, with no response-time guarantee. PRs and issues get reviewed when there's time. That's not a brush-off — it's the honest contract that keeps the project alive without turning into a second job. If something sits for a while, a friendly nudge is fine.

## Ways to contribute

- **New or expanded packs** — the most valuable contribution. Several packs ship as placeholders (`streamlit`, `pandas`, `kotlin`, `swift-ios`, `flutter`, `mcp-server`) and are meant to populate from real-world use. If you've run Sysop on a project in one of these stacks (or a new one), your conventions are exactly what's missing. Pack and convention content is proposed **as an issue** — see the [trust policy](#contribution-trust-policy) for why a maintainer authors the final pack change.
- **Bug fixes** — the installer (`install.sh`), the companion scripts (`core/companion/scripts/`), or the skills.
- **New conventions** for an existing pack — see the bar below. Same route: an issue, per the trust policy.
- **Docs** — clarity fixes, examples, typos. Always welcome; just open the PR.

## Reporting friction from real use

The most useful bug reports come from actually running Sysop on a project. Sysop
gives you a channel built for exactly this:

- **Log friction as it happens.** When something Sysop-shipped misbehaves — a skill
  step that referenced a path your project doesn't have, an installer prompt that
  failed, a permission rule the allow-list didn't cover — append it to
  `SYSOP_ISSUES.md` at your project root (the installer seeds this file; the
  template is inside it). Tell your agent to log Sysop friction there *the moment
  you hit it* — the details are freshest before the session moves on. Don't wait
  for a review cycle; `/review-close` Step 7 also captures friction, but a
  tester's densest friction (install, first permission setup, first `/intake`)
  happens before any review cycle exists.
- **Send the entries worth sending with `/report-issues`.** That skill renders
  each open entry as a GitHub issue, files the ones you consent to (per-entry —
  you review the exact body first) against this repo, and marks each filed entry
  so it's never double-sent. It's the bridge from your local log to the issue
  tracker.
- **Tell us what worked, too — with `/share-wins`.** The same log captures
  positive signal: something Sysop did notably well that's worth *protecting from
  a future change* (a guardrail that fired correctly, a step that just worked
  under an unusual setup). Log it as a `[good]` entry (the seed has a template),
  and `/share-wins` shares the ones you consent to as one aggregated comment on
  our "Wins" Discussion — same per-entry, review-the-exact-body-first discipline
  as `/report-issues`. It tells us what *not* to break.

## Before you start

- **Open an issue before a large PR** (a structural change, anything non-trivial). It saves you from building something that doesn't fit and lets us agree on shape first. Use the issue templates.
- **Pack and convention content doesn't need a PR at all** — the issue *is* the contribution. Per the [trust policy](#contribution-trust-policy), a maintainer authors the actual pack change from your proposal, with credit.
- **Small, obvious fixes** (typos, clear bugs) — skip the issue and just open the PR.

## Dev setup

Sysop ships **no runtime dependencies** — it's a meta-repo, not an installable package. The only deps are for its own test suite:

```bash
pip install -r requirements-dev.txt   # pytest + pyyaml
pytest -v                             # full suite (CI runs this on Python 3.13)
```

CI runs `pytest` on every PR; that check must be green to merge.

## Contributing conventions and packs

This is the heart of the project, so it has a real bar:

- **Conventions earn their way in — they aren't dumped in.** The whole model is that a rule is promoted only after a recurring review finding survives across multiple rounds (see `core/companion/docs/WORKFLOW.md` §5). When you propose conventions, say where they come from: what recurring mistake do they catch, and have you actually hit it on a real project? Speculative "best practices" nobody's been bitten by are the thing this project deliberately avoids.
- **Mirror an existing populated pack when sketching a proposal.** `packs/python`, `packs/postgres`, `packs/nextjs-react`, and `packs/llm` are the worked examples of what a maintainer-authored pack ends up containing:
  - `.claude-plugin/plugin.json` — manifest
  - `companion/convention_map.md` — glob → conventions
  - `companion/security_map.md` — OWASP-aligned entries (if applicable)
  - `companion/checks.yml.fragment` — deterministic checks (if applicable)
  - `companion/semgrep/*.yml` — semgrep rules (if applicable)
- **Keep content generic.** Use placeholder vocabulary (`<api module>`, `<components dir>`, `<utility modules>`) rather than your own project's real paths, names, or identifiers. Packs are for everyone; they shouldn't carry one codebase's fingerprints.
- **Adding a whole new pack?** Propose it as a `pack_or_convention` issue sketching that skeleton — registration in `.claude-plugin/marketplace.json` and the README's pack list happens in the maintainer-authored commit.

**Sending conventions upstream with `/contribute-convention`.** If you've run Sysop
on a real project, its `/codebase-review` and `/security-audit` Step 9 loop
promotes recurring findings into your `.claude/*.project.*` overlay — the
conventions this project grew. The `/contribute-convention` skill is the
give-back path for exactly those: it reads the overlay, **strips your project's
fingerprints down to placeholder vocabulary**, surfaces each rule's cross-round
provenance, groups them into one proposal per target pack, and — per-pack, with
you reviewing the exact generalized body first — files them upstream as
`pack_or_convention` issues (dry-run by default; `--execute` to file). It's the
sibling of `/report-issues` (which transports *friction*); this one transports
*conventions*. The bar above still applies — the skill only surfaces conventions
that earned promotion, and shows you the generalization before anything is filed.

**Say which model wrote the strays, if you know.** Optional, on any convention
proposal: naming the generating model or agent family (plus a rough date) helps
separate durable engineering discipline — the corpus's core value — from one
model generation's tics, which become natural retire candidates once that
generation ages out. `/contribute-convention` asks this during its provenance
step; hand-authored proposals can just add a line. Absence is fine — you often
won't know.

## Contribution trust policy

Pack content is a supply chain. Convention prose is loaded into the review
agents that approve code, and mechanical rules run on every consumer's checks
path — so the rules below are load-bearing security properties, not etiquette.
Each exists because of what pack content can *do* once it ships.

- **Convention contributions land as issues, and a maintainer authors the
  actual pack change.** A convention bullet is prose that review agents read
  inside privileged contexts — the map is the reviewer's rubric — which makes
  contributed convention text a prompt-injection surface. Filing it as an issue
  keeps it inert: a maintainer verifies the rule, rewrites it by hand, and
  commits it with credit. Convention PRs are never auto-merged, and a
  convention PR will usually be closed in favor of a maintainer-authored commit
  that credits you — that's the policy working, not your contribution being
  rejected.
- **No contributed git hooks, period.** A git hook is arbitrary code execution
  on every consumer's commit. Hook templates ship from the maintainer only.
  Found a bug in one? File the issue; don't send the patch as a hook edit.
- **Mechanized rules are reviewed like code, because they are code.** A semgrep
  pattern or checks grep is executable enforcement. Review looks specifically
  for inverse logic (a rule that in practice blesses the insecure pattern it
  claims to block) and pathological regexes (a ReDoS-shaped pattern would run
  on every consumer's CI path). Propose the check; the shipped pattern gets the
  same scrutiny as a code change.
- **The merge gate is cross-consumer survival.** Within one project, a
  convention is promoted only after it recurs across review rounds
  (`core/companion/docs/WORKFLOW.md` §5.1). Upstream applies the same gate one
  level up: a convention merges into a pack once more than one project has
  independently hit it. A singleton isn't rejected — it waits as an open,
  credited issue until a second project confirms the pattern. That's what keeps
  the packs a corpus of real, recurring agent failure modes rather than
  accumulated opinions.
- **You can't leak your codebase by accident.** The transport path
  (`/contribute-convention`) generalizes every rule to placeholder vocabulary
  before anything leaves your machine, shows you the exact issue body it would
  file (shown-equals-filed), takes per-pack consent, and defaults to dry-run. A
  rule that can't be generalized without leaking a fingerprint is excluded and
  handed back to you rather than filed. If your employer's policy is "no
  proprietary code leaves the building," this is the property that makes
  contributing compatible with it.

## Pull request process

1. Fork and branch from `main`.
2. Make a focused change — one logical thing per PR.
3. Run `pytest -v` locally; green before you open the PR.
4. Open the PR and fill in the template. CI must pass.
5. PRs are **squash-merged**, so give yours a clear title.

## Licensing of contributions

By submitting a pull request, you agree that your contribution is licensed under the project's **MIT license** (inbound = outbound). There's no CLA. The same applies to convention or pack content proposed in issues — by proposing it, you agree it can be incorporated into the project under MIT.

## Conduct

Be decent and assume good faith. This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md) — harassment or hostility isn't welcome here.

## Questions

Open-ended questions, ideas, and show-and-tell are best in **Discussions** (if enabled). Bugs and concrete proposals go in **Issues** using the templates.
