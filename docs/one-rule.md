# One rule, end to end

Sysop's public claim is that recurring review findings become machine-enforced rules. The
public repository can't show you that happening — it advances by squash snapshots, so the
granular history lives in a private repo (see [README § Provenance](../README.md#provenance)
for why). A claim you can't inspect is a slogan, whatever the footer says.

This page is the substitute: **one rule traced end to end** — from the review rounds that kept
finding the same mistake, through promotion and compilation, to the check you can run on your
own machine before you've installed anything. Private-history references below carry dates and
commit hashes; you can't independently verify those, and this page doesn't pretend otherwise.
Everything in the last two sections is checkable today, in the repo you're reading.

The rule is `http-client-redirect`, shipped in the [python pack](../packs/python/companion/semgrep/http_client_redirect.yaml).

## 1 · A reviewer finds the same mistake five times

In mid-March 2026 the upstream project (GDP Query System — a FastAPI + Next.js production app)
was running dual-mode review rounds under the workflow that became Sysop. Round 28, an OWASP
security audit dated **2026-03-16**, filed this finding:

> **TASK-883**: Set `follow_redirects=False` explicitly in all pipeline API clients —
> `bea_client.py:131`, `bls_client.py:41`, `fred_client.py:25`, `alphavantage_client.py:131`:
> httpx defaults to `follow_redirects=False` currently, but if the default changes, a
> DNS-poisoned API redirect could target internal endpoints.

Same round, same day: **TASK-884**, the same defect in the email-service client. That's five
call sites of one mistake — an outbound HTTP client constructed without pinning its redirect
behavior — found by hand, in one sitting.

## 2 · The finding is promoted to a written convention

The workflow's rule: a finding that keeps recurring isn't a finding, it's a convention. The
same day as Round 28 (**2026-03-16**, private commit `b5d615a7`), the class was promoted into
the project's prevention conventions, verbatim:

> **Outbound HTTP security**: All `httpx.Client()` and `httpx.AsyncClient()` constructors must
> set `follow_redirects=False` explicitly — library defaults can change between versions, and
> open redirects can leak authorization headers to attacker-controlled servers. URL allowlists
> for outbound fetches in the pipeline must enforce `https://` scheme; reject `http://` to
> prevent MITM content injection.

Here is the part worth being honest about: **the prose didn't end it.** The next day
(**2026-03-17**), Rounds 29 and 30 hand-found four more findings — the alerting client that POSTs
to a Slack webhook and PagerDuty (a redirect would hand both write-credentials to the redirect
target), a client that sends a revalidation secret as a Bearer token, the watchdog's async
client, and a `requests` variant in two scripts. A written convention is advice. Advice scales
exactly as far as whoever is reading it.

## 3 · The convention is compiled to a check

Three days later (**2026-03-20**, private commit `8f29037f`) the project built a shared grep
check registry, and the convention became a pattern: `http-client-redirect`, a deterministic
scan over every `httpx.Client(`/`httpx.AsyncClient(` constructor, run by the same
`run_checks` script on every review pre-scan.

A month later the check was rewritten, and the reason is the part that matters. Grep can't see
function bodies — by **2026-04-20** (private commit `53764e3f`) the pre-scan's text-local
patterns had emitted ~43 false positives across six checks in a single round. So the noisy
greps were ported to Semgrep AST rules that can see constructor kwargs:

> the new AST rules see zero findings on the compliant tree while still flagging synthetic
> violations.

That's the shipped rule you can read today —
[`http_client_redirect.yaml`](../packs/python/companion/semgrep/http_client_redirect.yaml),
sixteen lines. Rules in this loop are maintained like code: promoted on recurrence, rewritten
when they're noisy, [retired when they go stale](./index.html) (the demotion ledger — Move 03
on the landing page).

## 4 · The class goes quiet

After mechanization, the finding class disappears from the review record. Across the rest of
the project's review history (through Round 74, **2026-07-10** — the archive holds 3,298
findings total), the covered-class analysis shows for this convention: **7 findings before
mechanization, 0 after.**

The honest caveat, from the same analysis
([`docs/analysis/REPORT.md`](./analysis/REPORT.md)): for *mechanized* conventions, zero
archive recurrence is partly true by construction — the check runs before review, so a
violation gets caught and fixed upstream of the archive that this analysis mines. That is the
point of the design, but it means "0 recurrences" measures the loop working, not reviewers
squinting harder. The report states which conventions this held for and where the evidence is
weaker (prose-only conventions show no effect separable from ordinary codebase maturation).

## 5 · What a fire actually looks like

"No model in the loop" is a mechanism claim, so here is what the record shows fires looking
like — including the shape it *doesn't* show:

- **2026-04-22** — the edit-time Semgrep scan hook **blocked every edit** to a module until an
  incomplete suppression comment was fixed. No judgment call anywhere: the scanner matched, the
  edit was refused, the suppression was corrected. That incident was itself promoted into a new
  deterministic check (`nosemgrep-sqlalchemy-pair` — suppressions must name both sibling rule
  IDs), which is the loop eating its own cooking.
- **2026-05-13** — secret-scanning rules fired on newly-written test fixtures containing
  JWT-shaped strings. True positives by shape, adjudicated as two documented inline
  suppressions. Fires don't always mean bugs; they always mean a decision gets recorded.
- **2026-05-18/19** — a newly-promoted rule (`json-loads-broad-except`) fired six times on its
  first scan: one real gap (a migration-verification script got an explicit
  `json.JSONDecodeError` branch it lacked), and five false positives that drove a V2 of the
  rule with five `pattern-not` blocks and a new negative fixture, after which the baseline
  emptied.
- And the gap: the record holds **no** instance of `http-client-redirect` itself catching
  brand-new code in CI after promotion. Partly that's the claim working — nobody wrote an
  unguarded client constructor again. Partly it's architecture: in the source project these
  rules enforce at edit time and review pre-scan, not as CI blocks. In a Sysop consumer
  project the same rules sit in `run_checks`, the pre-commit hook, and the shipped CI
  template — wherever you arm them.

One more fire, and this one is in the repo you're reading. The `recompile-inside-def` rule
(promoted **2026-04-30**, same batch) flags `re.compile()` inside a function body. At landing
it caught three sites in the source project — including the checks runner's own memoization
helper — and when the workflow was extracted, it caught the same helper here.
[`core/companion/scripts/run_checks/grep.py:120`](../core/companion/scripts/run_checks/grep.py)
ships with the inline suppression and its reasoning, a documented adjudication you can read.
The sensor is indifferent to whose code it reads, including the code that runs the sensor.

## 6 · Check it yourself

None of the above requires trusting this page. With `semgrep` installed (`brew install semgrep`
or `pip install semgrep`) and this repo cloned:

```bash
# The shipped rule against its shipped fixtures — fires on the bad file, silent on the good one
semgrep --config packs/python/companion/semgrep/http_client_redirect.yaml \
        packs/python/companion/semgrep/fixtures/
```

Or write the violation yourself and watch it get caught:

```bash
printf 'import httpx\nclient = httpx.Client(timeout=5)\n' > /tmp/demo.py
semgrep --config packs/python/companion/semgrep/http_client_redirect.yaml /tmp/demo.py
```

That's the whole claim, executed on your machine: a rule earned from five hand-found defects in
March, firing deterministically in front of you now, with no model anywhere in the loop. The
same convention ships as prose in
[`convention_map.md`](../packs/python/companion/convention_map.md) ("Outbound HTTP security"),
as OWASP-mapped guidance in
[`security_map.md`](../packs/python/companion/security_map.md) (A05, A10), and as the
[`checks.yml` fragment](../packs/python/companion/checks.yml.fragment) that wires the rule into
`run_checks` — the three layers [Anatomy of a pack rule](./packs.md) explains.

## What this page doesn't prove

One rule, one project, and the private anchors (round records, commit hashes) are cited, not
independently checkable — this is a sample you can audit at the shipped end, not a dataset.
The dataset-level claim, with its own limits stated, is on the
[landing page § II](./index.html) and in [`docs/analysis/REPORT.md`](./analysis/REPORT.md).
For how the whole loop fits together, the [monograph](./workflow.html) is the long version.
