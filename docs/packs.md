# Anatomy of a pack rule

Sysop's packs are the corpus: each rule is a documented, generalized failure mode of an AI
coding agent, earned from a finding that kept recurring on a real project. This page explains
what a pack rule *is*, why it ships full of `<angle bracket>` placeholders, and how those rules
actually reach your code — so you can judge, before installing, how much of a pack transfers to
your project.

If you browsed a pack's convention map from the README and thought *"these aren't concrete rules
I get for free — I'd have to map them onto my codebase myself"*: that reading is correct, and
this page explains who does the mapping and when.

One scoping fact worth knowing up front: packs are entirely convention-loop content — maps,
checks, semgrep rules, and their support files. Nothing in a pack depends on the task queue or
merge gate, so every pack applies in full under the smallest install, [loop mode](./loop-mode.md).

## How a rule is born

A rule starts concrete. Here are two rules from the API-endpoint section of the convention map of
the project Sysop was extracted from (the full seven-bullet section ships verbatim as the worked
example in [`WORKFLOW.md` § 6.2](../core/companion/docs/WORKFLOW.md)):

```markdown
## `agent/server.py`, `agent/routes/*.py` — API Endpoints

- **Tier enforcement**: Creator-tier mutations need `Depends(require_studio_access)`, not just `get_verified_user`
- **Response filtering**: Never expose `owner_id`, `firebase_uid`, `client_ip`, `stripe_customer_id` in responses
```

Every clause there is a real defect that recurred across review rounds until it was promoted to a
written rule. That is the loop working — but the rule as written is welded to one codebase. Nobody
else has an `agent/` directory, a Creator tier, or a `require_studio_access` dependency.

## The same rule, as shipped

Promotion into a pack generalizes it. These are the same two rules as they ship in the
[python pack](../packs/python/companion/convention_map.md)'s corresponding section:

```markdown
## `<api module>/server.py`, `<api module>/routes/**/*.py`, ... — API Endpoints

- **Tier enforcement**: Tier-gated mutations need a tier-checking dependency
  (e.g., `Depends(require_<tier>_access)`), not just a verified-user dependency
- **Response filtering**: Strip internal fields (e.g., `owner_id`, `client_ip`, auth-provider UID,
  payment-provider customer ID) **at the route layer**; do NOT remove from data-access functions —
  routes need them for ownership checks
```

Read the two side by side and the generalization is visible: `agent/` became `<api module>`,
`firebase_uid` became "auth-provider UID", `stripe_customer_id` became "payment-provider customer
ID", `require_studio_access` became `require_<tier>_access`. The placeholder vocabulary is what
makes the rule portable — and it is also why the shipped form reads as abstract. Those are the
same property.

Note the shipped version is *not* merely the original with names blanked out. It gained a clause
("at the route layer; do NOT remove from data-access functions — routes need them for ownership
checks") that the original didn't need to say. Generalizing forces the rule to explain itself.

Each pack's header block lists every placeholder it uses and what kind of module each one means —
`<api module>` (web framework module), `<auth module>` (auth/user-session code), and so on. That
block is the dictionary for reading the rest of the file.

## How rules reach your code

Two layers, and they work differently. This distinction is the thing worth understanding:

**The maps (`convention_map.md`, `security_map.md`) keep their placeholders — permanently, on
purpose.** Nothing substitutes them at install time. Mechanically rewriting them was tried and
reverted: byte substitution mangled section headers into junk like `## __disabled_no_op__/*.py —
Auth`, and the placeholder tokens are accurate documentation as they stand.

What that means in practice depends on which skill is reading the map, and the difference is worth
knowing:

- **`/security-audit` resolves placeholders by inference.** It instructs its agents to substitute
  your project's equivalents while reading — so it works against the maps as shipped. The mapping
  happens in the agent's head.
- **`/codebase-review` matches on the globs.** Each section header is a glob list
  (`## <api module>/server.py, ... — API Endpoints`), and a review agent receives the convention
  bullets from the sections whose globs match the file under review. A glob still in `<api module>`
  form matches no file on disk, so **those sections deliver no rules until the globs name your real
  paths.** The skill knows this and won't mislead you: its coverage sweep reports files matched by
  no section, and it explicitly declines to flag placeholder globs as "stale" — they're an install
  artifact, not rot.

So a freshly installed pack is not inert, but it isn't fully wired either. Localizing the globs is
real work, and the review loop is what drives it: run `/codebase-review`, and its coverage sweep
surfaces the unmatched files and proposes sections or glob expansions naming your actual layout.

**The checks (`checks.yml`) do get concretized**, because a grep pattern can't infer anything — a
check scoped to `<api module>/` matches no file on disk and silently does nothing. So you author
`.claude/substitutions.project.yml` mapping each token to a real path:

```yaml
substitutions:
  "<api module>": "api"
  "<tests dir>": "tests"
```

and the installer rewrites `paths:` values in `.claude/checks.yml` so the checks fire against your
tree. This applies to `paths:` values in that one file — nothing else. Full details in
[configuration.md § Placeholder substitution](./configuration.md#placeholder-substitution-phase-25).

So: **checks are concretized mechanically from a file you author; maps are localized through use** —
by inference for the security audit, and by naming your real globs for the code review.

## What you own — and where localization lands

This is the part to get right, because the obvious move is the wrong one.

The assembled `.claude/convention_map.md` is a **managed file**. The installer regenerates it on
every `--update`, so editing your real paths into it directly works right up until your next update
silently reverts them. Don't localize there.

Your durable surface is the overlay: `.claude/convention_map.project.md` and
`.claude/security_map.project.md` are never managed, never overwritten, and appended to the
assembled map. Sections naming your real paths belong there, and that is where `/codebase-review`
writes map hygiene when it's running against an install rather than this repo. See
[configuration.md](./configuration.md#config--never-managed-overlay-files).

The consequence worth stating plainly: an upstream pack section and your localized version coexist
in the assembled file — the placeholder section stays, matching nothing, while your overlay section
carries the real globs. That's the current design, and it means adopting a pack's glob-scoped rules
costs some deliberate work rather than none.

When a rule you wrote locally turns out to be general, `/contribute-convention` offers it upstream —
generalized to placeholder vocabulary, and shown to you exactly as it would be filed, before
anything is sent.

## Where each pack came from

Packs populate from real projects, which is the point — and also the honest limit on how well they
transfer. Nothing here was hand-written from a best-practices article. For one rule's full paper
trail — the review rounds that kept finding it, the promotion, the compiled check you can run —
see [One rule, end to end](./one-rule.md).

| Pack | Mined from | What that means for transfer |
|---|---|---|
| `python` | The extraction source: a hosted, multi-user subscription web app — FastAPI backend, Postgres, LLM-backed answers, third-party auth and payments. | Strong on API-boundary, logging, and input-validation rules. The tier-enforcement and payments-adjacent bullets assume a tiered SaaS; a generic FastAPI service can ignore those sections rather than map them. |
| `postgres` | The same app's data layer — SQLAlchemy with separate reader/writer/admin engines, Alembic migrations. | Rules assume an explicit engine split and a project-defined log sanitizer. Useful with any SQLAlchemy/Postgres project; the engine-role bullets need that split to mean anything. |
| `nextjs-react` | The same app's frontend — Next.js App Router, React, TypeScript. | The most directly portable of the four: fetch/abort, error display, accessibility, and markdown-rendering rules assume little beyond the framework. |
| `llm` | The same app's LLM integration — hosted models serving many users on paid tiers. | Shaped for multi-tenant LLM-backed APIs: rate limiting, tier enforcement, prompt-boundary guards, response filtering. A single-user or local-model integration will find much of it inapplicable. |
| `beancount` | BeanRider — a personal-finance pipeline ingesting raw vendor exports into a Beancount ledger. | Covers the "raw vendor dump → normalized double-entry" shape; assumes local, single-user data rather than a hosted service. |

Four of the five come from one product, so they share its shape. That is a real limitation, not a
temporary one to be papered over — a pack earns breadth by being used on more projects, which is
what `/contribute-convention` and the friction log are for. The six placeholder packs
(`streamlit`, `pandas`, `kotlin`, `swift-ios`, `flutter`, `mcp-server`) ship as manifests only and
stay that way until real use populates them; an empty pack is more honest than an invented one.

## No framework-specific rules yet

There are no FastAPI-specific, Django-specific, or Flask-specific rule sets — the python pack's
web-framework rules were mined from a FastAPI app and mention FastAPI constructs where the original
rule did, but the pack is not organized by framework. That is a gap, and the way it closes is the
same loop as everything else here: real projects, real recurring findings, promoted and generalized.
