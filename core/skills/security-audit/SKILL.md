---
name: security-audit
description: Deep OWASP-aligned security audit — generates threat-categorized tasks in review_tasks.md
argument-hint: "[--full | --changes-only] [--scope backend|frontend|pipeline|scripts]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Adversarial security audit aligned to the OWASP Top 10. Scans for injection, auth bypass, data exposure, SSRF, XSS, misconfigurations, and dependency vulnerabilities. Produces security-focused batches in `review_tasks.md` grouped by threat category.

> **Helper names** (e.g., `_sanitize_log`, `_escape_like`, `validate_sql_safety`, `_track_failure_best_effort`, `useAbortableFetch`, `isSafeHref`, `getDisplayError`, `MARKDOWN_ALLOWED_ELEMENTS`, `isAllowedRedirectUrl`, `MAX_RESPONSE_BYTES`) referenced throughout this skill are placeholders for project-defined utilities — substitute your project's equivalents from `<project>/.claude/convention_map.md` and pack `security_map.md` files. File-path placeholders (e.g., `<api module>/server.py`, `<api module>/routes/<route>.py`) are similarly project-bound; agents read the actual files specified in your `<project>/.claude/security_map.md` under each Step 4 agent's section pointer below.

## Pre-flight: Permission Guard

Before any work, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `auto` mode + `skipAutoPermissionPrompt: true`, a missing rule for `bash scripts/run_checks.sh` silently halts the security check stage with no actionable error.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(bash scripts/run_checks.sh)`
- `Bash(bash scripts/run_checks.sh:*)`
- `Bash(python scripts/archive_review_tasks.py:*)`
- `Bash(python3 scripts/archive_review_tasks.py:*)`
- `Bash(.venv/bin/python3 scripts/archive_review_tasks.py:*)` — Phase 45b venv-prefixed variant (preferred when the consumer has a venv with PyYAML)

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "runs the bundled check registry (grep + LSP + Semgrep) against security-relevant files, and may need to archive `review_tasks.md` if it exceeds 125KB"). Do not proceed.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 1: Determine Scope (Smart Hybrid)

Parse `$ARGUMENTS` for flags:
- `--full` — force full codebase scan
- `--changes-only` — force incremental scan (changes since last Round)
- `--scope <area>` — restrict to one area (see mapping below)
- If neither `--full` nor `--changes-only`: auto-detect

**Auto-detect logic:**
1. Find the most recent Round date in `review_tasks.md` (e.g., `## Round 5 (2026-02-26)`)
2. If no Rounds exist OR last Round is >7 days ago → **full scan**
3. If last Round is ≤7 days ago → **incremental scan** (changes since that date)

**Scope mapping** (applied as path filter to the file list):

The `--scope` values map to project-specific path sets. Each project declares its own scope mapping under `<project>/CLAUDE.md` § "Scope mapping" — e.g.:

| `--scope` | Paths included (example) |
|-----------|---------------|
| `backend` | `<api module>/` excluding `<data pipeline>/` |
| `frontend` | `<frontend>/` |
| `pipeline` | `<data pipeline>/`, `<prompts dir>/`, `.claude/skills/` |
| `scripts` | `<scripts dir>/`, `<migrations dir>/`, `<datajobs dir>/`, `<data seed dir>/` |
| *(omitted)* | All of the above |

If no scope mapping is defined in the project's CLAUDE.md, fall back to scanning the path roots discovered from `<project>/.claude/security_map.md` section headers.

**Build file list:**
- Full scan: `git ls-files -- <paths>` (filtered by scope)
- Incremental: `git log --since="<last-round-date>" --name-only --pretty=format: -- <paths> | sort -u`
- Exclude: `*.md`, `*.lock`, `*.txt`, `*.csv`, image files, `__pycache__/`, `node_modules/`, `.next/`, `package.json`, `package-lock.json`, `tsconfig.json`, `tsconfig.*.json`
- Keep: `*.yml`, `*.yaml`, and other `*.json` files (may contain security-relevant config — e.g., deploy configs like `firebase.json`, `apphosting.yaml`, `vercel.json`, `cloudbuild.yaml`, plus GitHub Actions workflows)

**Additionally**, always include these security-critical files regardless of scope or scan mode. The exact paths are project-specific — each project declares its always-include list under `<project>/CLAUDE.md` § "Security-critical always-include files". Typical categories:
- Auth and session middleware (e.g., `<auth module>/*.py`, `<auth module>/middleware.py`)
- DB-config and engine selection (e.g., `<db config module>`)
- Frontend framework config and middleware (e.g., `<frontend>/next.config.ts`, `<frontend>/middleware.ts`)
- Container and platform config: `Dockerfile`, `.dockerignore`, deploy configs (e.g., `firebase.json`, `apphosting.yaml`, `vercel.json`)
- `.gitignore` (verify exclusion of `.env`, `*.pem`, `*.key`, `*-credentials.json`, `serviceAccount*.json`)
- CI / build workflows (e.g., `.github/workflows/*.yml`)

**Do NOT read `.env`, `.env.local`, or other unignored-but-local secret files into agent context** — contents are secrets by design, and the security check is whether `.gitignore` excludes them (covered above). Reading `.env` content pipes live credentials into the LLM session.

Report to the user before proceeding:
```
Scan mode:   Full / Incremental (since YYYY-MM-DD)
Scope:       <area or "all">
Files:       <N> files to audit (+<N> security-critical always-include)
```

## Step 2: Collect Existing Task Context

Run these in parallel:
- Read `review_tasks.md` — find the highest `TASK-N` ID (new tasks start at N+1)
- Build a deduplication index: collect all **open** tasks (`[ ]` or `[/]`) with their `file:line` references
- Read `CLAUDE.md` — auth architecture, rate limiting config, SQL safety patterns, DB roles
- Read `.claude/security_map.md` — the security concern map that tells each agent which OWASP checks apply to which file areas
- Read `.claude/convention_map.md` — scoped convention rules per file group (used by Map Coverage Audit in Step 2a)
- Read security-critical files listed above — understand current auth/authz implementation

Record:
- `next_task_id` = highest TASK-N + 1
- `next_batch_number` = highest Batch N + 1
- `open_task_index` = set of `(file, line)` tuples from open tasks

## Step 2a: Map Coverage Audit (Coverage Gaps)

Before launching any audit agents, cross-reference both maps against the actual codebase to find coverage gaps. This is a deterministic check — no LLM needed.

### 2a-1. Files not matched by any security_map section

Parse the `## ` section headers from `.claude/security_map.md` to extract the file globs for each section (the section header format is `## <glob list> — <Section Name>`). Derive the unique top-level path roots from those section globs. Then run `git ls-files -- <derived roots>` and check each code file against the extracted globs. Collect files that don't match any section.

**Exclude from the gap report** (these have negligible security surface):
- Config-only files: `Dockerfile`, deploy configs (e.g., `firebase.json`, `apphosting.yaml`, `vercel.json`), `*.yml`, `*.yaml`, `*.json`, `*.sql`
- Docs: `*.md`
- Pure configuration modules with no user input, no network, and no SQL from external sources (project-specific list — see `<project>/CLAUDE.md` § "Map coverage exclusions")
- Static data files (e.g., `<frontend>/data/*.ts`, `<frontend>/fixtures/*.ts`)
- Container infrastructure files already covered by the `<datajobs entrypoint>` section (e.g., `<datajobs dir>/Dockerfile`, `<datajobs dir>/requirements.txt`)

Report unmatched code files:
```
Security Map Coverage — Unmatched Files:
  <N> code files not matched by any security_map section
  <file list, grouped by directory>
```

### 2a-2. Files not matched by any convention_map section

Parse the `## ` section headers from `.claude/convention_map.md` to extract the file globs for each section. Derive the unique top-level path roots from those section globs. Then run `git ls-files -- <derived roots>` and check each code file against the extracted globs. Collect files that don't match any section.

**Exclude from the gap report** (these are expected to be unmatched):
- Config-only files: `Dockerfile`, deploy configs (e.g., `firebase.json`, `apphosting.yaml`, `vercel.json`), `*.yml`, `*.yaml`, `*.json`, `*.sql`
- Docs: `*.md`
- Small/stable utility modules with no user input or network surface (project-specific list — see `<project>/CLAUDE.md` § "Map coverage exclusions")
- Static data files (e.g., `<frontend>/data/*.ts`, `<frontend>/fixtures/*.ts`)
- Container infrastructure files (e.g., `<datajobs dir>/`)

Report unmatched code files:
```
Convention Map Coverage — Unmatched Files:
  <N> code files not matched by any convention_map section
  <file list, grouped by directory>
```

### 2a-3. Map staleness sweep (stale sections + dead citations)

The checks above run **forward** (code → map: which files lack coverage). This check runs **backward** (map → code: which map content has lost its referent), catching security conventions that went stale when the code moved out from under them. Deterministic — no LLM needed — and it **flags candidates only; it never auto-retires a convention** (the retirement *decision* stays human — see the routing note in 2a-4).

**(a) Stale sections — glob matches no tracked file (a removed category, staleness Mode C).** For each `## <glob list> — <Section Name>` section parsed above (both `security_map.md` and `convention_map.md`), run `git ls-files -- <section globs>`. A section whose globs match **zero** tracked files has lost its scoped surface — flag it. Rule out three look-alikes before treating it as stale: **relocation** (the forward pass found newly-unmatched files in a sibling location → update the glob, don't retire); **aspirational / lead section** (a glob legitimately preceding not-yet-written code → note and skip); **un-substituted placeholder** (a glob still in `<...>` form the consumer has not localized → skip, it's an install artifact).

**(b) Dead citations — a cited symbol is gone (a renamed/deleted helper, staleness Mode B).** For each bullet that cites a concrete in-repo identifier (a backticked symbol naming a project helper/function — e.g. the canonical `_sanitize_log`, `isSafeHref`), run `git grep -nw -- '<symbol>'` across tracked files. Zero hits means the cited symbol was renamed, moved, or deleted — flag the bullet. **Security caveat:** a dead citation on a security helper (a sanitizer, an auth guard, a redactor) is higher-stakes than on a quality helper — the convention almost certainly still applies and the helper was likely renamed, not removed, so default to **refresh the citation to the new symbol** and confirm the protection still exists somewhere before considering retirement. Scope guards (mirroring `_shared/adversarial-review.md` dimension #9 — when you cannot tell, leave it unflagged): skip angle-bracket placeholders (`<api module>`); skip library/framework identifiers (`AbortController`, `yaml.safe_load`) that have no in-repo definition by design — only test identifiers that resolve (or once resolved) to an in-repo definition.

**Distinguish refresh from retirement.** A dead citation usually means refresh the citation (rule still valid, helper renamed). An empty section usually means retirement candidate (category gone). Beware **over-broad-from-birth** (Mode G): a glob that never matched much presents identically to a removed category but is a calibration miss → **tighten the glob, don't retire the rule**. This sweep catches the statically detectable staleness (Modes B and C) only.

Report:
```
Map Staleness — Retirement / Refresh Candidates:
  Stale sections (glob matches 0 tracked files):
    security_map.md   § <Section Name> — <glob>
    convention_map.md § <Section Name> — <glob>
  Dead citations (cited symbol absent from the codebase):
    security_map.md § <Section Name> — bullet cites `<symbol>`
```

### 2a-4. Offer to fix inline

If any check finds gaps or staleness:

```
Security map has <N> file coverage gaps.
Convention map has <M> file coverage gaps.
Map staleness: <Q> stale sections, <R> dead citations.
Fix these before launching audit agents? [y/N]
```

If yes:
- For unmatched files: propose new sections or glob expansions for the relevant map and apply them
- For **dead citations** and **relocated sections**: refresh the citation or update the glob in place — low-stakes map hygiene, apply directly (default to refresh for any security helper). In a **consumer install** (`.claude/sysop.lock` present), edit hygiene that targets a **locally-authored `.project.*` overlay section** in the overlay file, not the regenerated base copy (per `_shared/promotion-write-target.md`); hygiene on a **core/pack-shipped** section refreshes from upstream on the next update, so a base-only edit is transient
- For **stale sections reflecting a genuinely removed category** (a promoted security convention with no code left to govern): **do not delete the CLAUDE.md § Prevention Conventions bullet here.** Record it as a retirement candidate in the final summary report and route the decision to the deliberate, human retirement step (the interactive **Step 9b: Convention Demotion** prompt — symmetric to promotion, and the Tier 2 home where Step 9b also retires the blocking-mechanical rules whose false-positive cost this static map sweep cannot see; for security rules it confirms the protection moved elsewhere before retiring). Tier 1 detects and reports; the retirement *decision* stays human.
- Commit: `git add .claude/convention_map.md .claude/convention_map.project.md .claude/security_map.md .claude/security_map.project.md && git commit -m "docs: update convention_map.md and security_map.md coverage"` (the `.project.*` overlay paths pick up any consumer-install hygiene edits; they no-op in the source repo where the overlays don't exist)

If no (or audit is clean), proceed to Step 2b. Note gaps **and staleness candidates** in the final summary report either way.

## Step 2b: Grep + Tool Pre-Scan (Deterministic Checks)

Before launching LLM agents, run the shared check registry to find mechanical security issues. These produce findings directly — no LLM interpretation needed.

```bash
bash scripts/run_checks.sh --mode security
```

The `--mode security` invocation runs four stages: grep (checks.yml registry), LSP/lint (`pyright`, `eslint`), Semgrep AST, and dependency audit (`pip-audit`). All four share the same `(check_id, file_line, msg)` shape so baseline matching, `--mode` filtering, and `--fail-on-blocking` apply uniformly.

**pip-audit specifics.** Invoked as `pip-audit --strict --format json` against the active venv. Findings are tagged `[pip-audit]`; the single catch-all check_id is `pip-audit-vuln`. Each finding's message text embeds the package name, installed version, CVE/GHSA ID, fix version (when available), and the first 200 chars of the advisory description. Findings anchor at the first discoverable `requirements*.txt` (sorted) because pip-audit reports per-package, not per-line — falls back to `requirements.txt:1` when no requirements file is present. If `pip-audit` is missing the stage skips with an install hint (`pip install pip-audit`).

**ESLint specifics.** Same single catch-all (`lint-error`) used by the codebase-review skill. Frontend findings include `jsx-a11y/*` rules that map to OWASP A07 (auth) and A05 (misconfiguration); they surface here as well so the security audit benefits from them. The original ESLint rule_id is embedded in the message text — read it to triage which OWASP category to file the finding under.

Collect all output lines as "pre-scan findings." Mark each with the appropriate source tag (`[grep]`, `[lsp]`, `[semgrep]`, `[pip-audit]`) in your notes to distinguish from LLM findings — this helps track coverage improvement over time.

Checks with a `notes: "Needs LLM triage"` field in `.claude/checks.yml` require manual verification before recording as findings — the script outputs all matches including potential false positives for those checks. Review the `notes` field in the YAML to understand what to verify.

These findings are treated identically to LLM agent findings in Step 4 (deduplication, batching).

**Stale-rule capture (convention demotion — Tier 2).** Triage produces a verdict on every flagged match, and one verdict is normally discarded: *the rule itself is moot.* When a mechanical check (a `checks.yml` regex, a `semgrep-*` rule, a `pre-commit` letter, or a `pip-audit-vuln` finding) fires on a match that is **not** a real issue **because the security convention it enforces no longer applies** — most often a *version-fix* (a dependency bump or framework upgrade mooted a local guard, change-event Mode E in WORKFLOW.md §3.5), or a category migrated away — record a **stale-verdict** for that rule in the `## Convention fire ledger` (Step 5e). This is the demotion counterpart to Step 8's promotion-candidate extraction. Guards (mirroring the Step 2a-3 staleness discipline and `_shared/adversarial-review.md` dimension #9):
- **Rule moot, not instance exception.** One legitimate exception is *not* a stale-verdict — that is what a baseline entry or `# nosemgrep` is for, and the rule stays. Record a stale-verdict only when the rule keeps flagging things that are **no longer issues at all** because the underlying convention changed.
- **Confirm the protection moved, not vanished.** A security check looking stale is higher-stakes than a quality check: before recording it as moot, confirm the defense it encodes still exists elsewhere (or is genuinely obsolete). When you cannot tell, **do not record** — leave it; if it is real staleness it recurs next round.
- **Blocking rules matter most.** A stale *blocking* rule halts every commit touching the scoped code; capture both blocking and advisory, but retirement value concentrates on blocking rules (Step 9b).

This capture also applies to the Semgrep (Step 2b) and pip-audit stages — any mechanical stage whose hit you judge systemically moot.

<!-- Canonical process: WORKFLOW.md §2.6 (Review — Security) -->
<!-- Check definitions: .claude/checks.yml — see WORKFLOW.md §6.5 -->

## Step 3: Audit by OWASP Category (Map-Guided Agents)

**CRITICAL: Read `.claude/security_map.md` before launching agents.** The security map specifies which OWASP checks apply to which file areas and which to SKIP. Agents must respect both the "Check" and "Skip" lists.

**All audit agents in this step must use `model: "opus"`** — adversarial security analysis requires fresh, sustained reasoning to trace multi-hop attack paths; a missed auth bypass or injection vector has direct production impact. Do not omit, per the **reasoning** role (`.claude/served_models.yml`).

Launch agents **per OWASP category** (not per file area). Each agent receives:
1. A **single OWASP category** (or small group of related categories)
2. The **specific files** that the security map says are relevant to that category
3. The **specific checks** to perform from the security map's "Check" list for those files
4. Instructions to **SKIP** checks the map says are irrelevant

This structure ensures every category is checked by a dedicated agent with a narrow, focused mandate.

### Agent 1: Injection & Prompt Safety (A03)

**Files to read:** All files where A03 is listed under "Check" in `<project>/.claude/security_map.md`. For Sysop-installed projects, these typically come from these pack sections:
- python pack §"API Endpoints" — SQL from external sources, prompt boundary escaping for LLM-using routes
- postgres pack §"SQL & Data Layer" — SQL injection, LIKE escaping, SQL from external sources
- python pack §"Data Pipeline" — alerting-channel message escaping
- python pack §"CLI Scripts" (covers `<scripts dir>/*.py` + `<datajobs entrypoint>` + `<data seed dir>/*.py`) — SQL from external sources, path containment, JOB_ARGS-style validation
- core §"Shell Scripts & Git Hooks" — shell injection, unquoted variable expansions, `eval` on external input
- llm pack §"LLM-using endpoints" + §"LLM-using pipeline modules" — prompt injection in XML boundary tags

**Specific checks per file area:**
- **Routes/server**: Every user/external value interpolated into an LLM prompt boundary tag uses `html.escape()`. Every SQL template from DB/cache passes through `validate_sql_safety()` before execution.
- **Tools**: No f-strings in SQL. All LIKE/ILIKE values use `_escape_like()` + `ESCAPE '\\'`. Identifiers validated with `validate_identifier()`.
- **Ingestion**: Every dynamic value in Slack mrkdwn messages uses `_escape_slack()`. Every external content in LLM prompt XML boundaries uses `html.escape()`.
- **Python scripts**: SQL from external sources (DB rows, config files) validated with `validate_sql_safety()`. File paths from env vars use `os.path.realpath()` + base directory check.
- **Shell scripts**: All variable expansions double-quoted to prevent word splitting/injection. No `eval` or unquoted `$()` on env/user input. No hardcoded secrets (passwords, API keys, project IDs). `set -euo pipefail` at script top.
- **Datajobs**: `JOB_ARGS` validated for length and character allowlist before `shlex.split()`.

**Do NOT check:** XSS (frontend agent handles that), SSRF, auth, dependencies.

### Agent 2: Authentication, Access Control & Data Exposure (A01, A02, A07)

**Files to read:** All files where A01, A02, or A07 is listed under "Check" in `<project>/.claude/security_map.md`. For Sysop-installed projects, these typically come from these pack sections:
- python pack §"Auth" — auth verification completeness, optional vs required auth, token size validation
- python pack §"API Endpoints" — IDOR, tier enforcement, response filtering
- python pack §"Payments" — webhook signature verification, audit trail
- python pack §"Data Pipeline" — pipeline secret validation, OIDC token configuration
- postgres pack §"Database Migrations" — GRANT/REVOKE correctness, sensitive-table exclusion
- python pack §"Backend Tests" + nextjs-react pack §"Frontend Tests" — fake-credential hygiene + test isolation

**Specific checks per file area:**
- **Auth modules**: Token verification on all paths (no bypass). Optional-auth logs failures at WARNING + calls `_track_failure_best_effort()`. Token size validation (>10 KB rejected). Staging = production for security guards.
- **Routes**: Every resource access verifies ownership (no IDOR). Creator-tier mutations use `require_studio_access`. Responses don't expose `owner_id`, `firebase_uid`, `stripe_customer_id`, `client_ip`. Input validation with `Field(max_length=...)`.
- **Stripe**: Webhook HMAC verification. Error messages sanitized. Stripe customer ID not leaked.
- **Pipeline auth**: Secret validated at startup for prod/staging. Timing-safe comparison.
- **Migrations**: Role grants follow least privilege — `app_reader` has SELECT only, `app_writer` restricted to cache/logging tables, `postgres` admin used only for DDL. No `GRANT ALL` on user-data tables.
- **Tests**: No real credentials, API keys, or connection strings in fixtures — tokens are obviously fake (`fake-token-xxx`, `mock-token-xxx`). `APP_ENV=test` set before importing `db_config`. No production API endpoint URLs in frontend mocks.

**Do NOT check:** SQL injection (Agent 1), XSS (Agent 4), SSRF (Agent 3), dependencies.

### Agent 3: SSRF, LLM Security & Configuration (A10, A05, LLM)

**Files to read:** All files where A05, A10, or LLM Security is listed under "Check" in `<project>/.claude/security_map.md`. For Sysop-installed projects, these typically come from these pack sections:
- python pack §"App & Middleware" — rate limiting, env var validation, debug endpoints, brute-force thresholds
- python pack §"Backend Utility Modules" — env var validation correctness, HTTP client lifecycle, thread-safe singleton init
- llm pack §"LLM-using endpoints" + §"LLM-using pipeline" + §"Backend Utility Modules (LLM-adjacent)" — `max_output_tokens`, response-text guards, retry bounds
- python pack §"External API Clients" — `follow_redirects=False`, response size limits, HTTPS enforcement
- python pack §"Data Pipeline" — HTTP client lifecycle, env var validation
- nextjs-react pack §"Security Headers & Proxy" (`<next config>`) — CSP, security headers, Permissions-Policy
- core §"Dockerfile" + §".gitignore" + §".github/workflows" — base image pinning, secrets exclusion, CI permissions, action version pinning

**Specific checks per file area:**
- **Server / rate_limiting**: `max_output_tokens` on ALL `GenerateContentConfig` calls. CORS `ALLOWED_ORIGINS` not `*` in prod. Env vars validated (fail-fast for prod/staging). Debug endpoints disabled. Rate limiting coverage complete. Retry loops have bounded attempts. Brute-force violation thresholds fire alerts.
- **LLM & config utility modules**: `max_output_tokens` on all `GenerateContentConfig` calls, `html.escape()` on user content in XML boundary tags, `if not response.text` guard before `json.loads()`, env var fail-fast for prod/staging, safe-default handling documented.
- **API clients**: `follow_redirects=False` at client level. `https://` scheme on all base URLs. `MAX_RESPONSE_BYTES` enforced. Timeout set. Client cleanup (`close()`).
- **Ingestion**: HTTP client created once, reused, closed in `finally`/shutdown. `follow_redirects=False` at client level.
- **ISR/filtering**: `follow_redirects=False`, timeout set. Singleton init uses `threading.Lock()` around the check-and-create pattern.
- **Frontend config**: CSP has `form-action`, `frame-ancestors`. HSTS includes `includeSubDomains`, `preload`. Permissions-Policy denies unused APIs.
- **Infrastructure**: Dockerfile pins base image by SHA256 digest. `.gitignore` excludes `.env`, `*.pem`, `*.key`. GitHub Actions have `permissions:` block.

**Do NOT check:** SQL injection (Agent 1), auth bypass (Agent 2), XSS beyond CSP (Agent 4).

### Agent 4: XSS & Frontend Security (A03 client-side)

**Files to read:** All files where XSS or A03 (client-side) is listed under "Check" in `<project>/.claude/security_map.md`. For Sysop-installed projects, these typically come from the nextjs-react pack:
- §"React Components" (`<components dir>/**/*.tsx`) — ReactMarkdown, `dangerouslySetInnerHTML`, safe-href validation, `window.open`
- §"Custom Hooks" (`<hooks dir>/*.ts`) — `encodeURIComponent` on fetch URLs
- §"Frontend Utilities" (`<frontend lib>/*.ts`/`*.tsx`) — safe-href implementation, markdown allowed-elements list, redirect validation
- §"Pages & API Routes" (`<app dir>/**/page.tsx`, `<app dir>/api/**/*.ts`, `<app dir>/chart-render/**/*.tsx`) — URL validation, `encodeURIComponent`, HTTPS enforcement, server-side fetch `redirect: 'error'`, internal-render-route guards
- §"App Shell" (`<app dir>/(auth)/**/*.tsx`, `<app dir>/layout.tsx`, `<app dir>/global-error.tsx`, `<app dir>/embed/**/*.tsx`) — error display, no `dangerouslySetInnerHTML`

**Specific checks per file area:**
- **Components**: ReactMarkdown has `allowedElements` (allowlist, not denylist). No `dangerouslySetInnerHTML`. Links from API/LLM validate scheme with `isSafeHref()`. `window.open` includes `noopener,noreferrer`. Error display uses `getDisplayError()`.
- **Hooks**: `encodeURIComponent()` on all dynamic values in `fetch()` URL path segments and query params.
- **Lib/types**: `isSafeHref()` correctly handles edge cases (fragment-only URLs, relative paths, data: scheme). `MARKDOWN_ALLOWED_ELEMENTS` matches canonical set (p, h1-h6, ul, ol, li, strong, em, a, code, pre, blockquote, table, thead, tbody, tr, th, td). `isAllowedRedirectUrl()` prevents open redirects.
- **Pages/API routes**: `isAllowedRedirectUrl()` called before `window.location.href` assignment. Backend URL uses HTTPS in prod. Server-side `fetch()` in RSC/`generateMetadata`/`generateStaticParams` includes `redirect: 'error'`.
- **App shell (layout, global-error, (auth))**: Thin wrappers — check only error display (`getDisplayError()`) and absence of `dangerouslySetInnerHTML`.
- **Embed**: Same as components but in a reduced-permission iframe context; verify no unsafe navigation escapes.
- **Chart-render**: `robots: 'noindex'`, CSP `frame-ancestors 'none'`, slug/tag regex validation with `notFound()` on mismatch, `redirect: 'error'` on fetch.

**Do NOT check:** SQL injection, server-side auth, SSRF, LLM security, dependencies.

### Agent 5: Logging, Audit Trail & Privacy

**Files to read:** All files where Logging or Audit Trail is listed under "Check" in `<project>/.claude/security_map.md`. For Sysop-installed projects, these typically come from these pack sections:
- python pack §"API Endpoints" — audit trail on state mutations (deletions, tier changes, credit grants), rate-limit violation logging
- python pack §"Auth" — auth failure logging completeness
- python pack §"Payments" — audit trail on subscription mutations (with prior-balance capture for credits)
- python pack §"Data Pipeline" — alerting coverage for critical failure paths, alerting-side sanitization (Slack/PagerDuty redaction)
- python pack §"CLI Scripts" — exception sanitization on raw exception messages

**Specific checks per file area:**
- **Routes**: Every content deletion (studio, prompts, embeds) logs at INFO on success with content_type, id, owner. Every credit deduction logs at INFO with uid.
- **Auth**: Every auth rejection path (invalid token, expired, oversized) logs at WARNING with sanitized client IP. `_track_failure_best_effort()` called on every rejection.
- **Stripe**: Tier upgrades log before/after state (free → creator). Cancellations log prior tier and zeroed credits. Credit grants log new balance.
- **Rate limiting**: IP-based and user-based violations both logged at WARNING. Brute-force threshold triggers alert.
- **Alerting**: Critical pipeline failures covered. Cooldown prevents alert spam.
- **Data seed scripts**: Raw exception messages (from `sqlalchemy`, `httpx`, `requests`) wrapped in `_sanitize_log(str(e)[:500])` before `print()` or `logger.*()` calls — connection strings and API keys can surface in exception text.

**Do NOT check:** SQL injection, XSS, SSRF, dependencies, auth correctness (Agent 2 handles that).

### Agent 6: Dependencies (A06)

Dependency scanning runs through `run_checks.sh`: the local pre-scan in Step 2b already runs `pip-audit --strict --format json` against the active venv — **consume those `[pip-audit]`-tagged findings rather than re-running**. (The same scan runs in CI when the consumer adds `pip-audit` to the shipped gate template `scripts/ci/sysop-checks.yml.example` — see WORKFLOW.md § 6.1 "Protecting `main` with CI".) If Step 2b reported `pip-audit not available`, follow the install hint (`pip install pip-audit`) and re-run `bash scripts/run_checks.sh --mode security` before continuing.

Run the supplementary `npm audit` scan (not yet pre-scanned):
- `cd "$(git rev-parse --show-toplevel)/<frontend>" && npm audit --production 2>/dev/null || echo "npm audit not available"`

Also check (manual inspection, not pre-scanned):
- All `requirements.txt` files in the project (root + per-service e.g., `<datajobs dir>/requirements.txt`) for `>=` instead of `==` pins
- Per-service requirements advisories — the local pre-scan only audits the venv on PATH; if the project has separate per-service venvs (e.g., `<datajobs dir>/`), cross-check by reading the CI job log for the most recent main-branch run, or invoke pip-audit manually in the relevant venv if discrepancies are suspected
- GitHub Actions workflows for unpinned action versions or tool installs

Report findings grouped by severity. If tools aren't installed, note this as a gap.

**Severity assignment:**
- 🔴 **High** — default for all security findings (exploitable vulnerability, auth bypass, data exposure)
- 🟡 **Medium** — downgrade only when clearly mitigated by another control (e.g., defense-in-depth gap where the primary control is solid)
- 🟢 **Low** — informational, best practice improvement, defense-in-depth hardening

### Locality Rule (Radial Expansion)

When an agent identifies a finding, it must **expand the search radius concentrically** before moving to the next file or check:

1. **Same call / same line group (~5 lines):** Check adjacent parameters, fields, or arguments for the same omission. If one field is missing `html.escape()`, check every other field in that call.
2. **Same function (~50 lines):** Check other code paths. If a `try` block catches `SpecificError`, trace what other exceptions the body can raise.
3. **Sibling functions (same module):** If you find a missing check on one endpoint, check every sibling endpoint in the same router file.
4. **Enclosing scope:** Check whether the enclosing block changes the semantics of the local pattern.

### Chunked Review for Large Files

For files >300 lines, review in ~200-line chunks. For files >600 lines, review the **last third first**, then middle, then top — this counteracts attention decay where the first functions get thorough checking and the last get skimmed.

## Step 3b: Post-Scan (Pattern Amplification)

After all LLM agents complete, extract the **underlying pattern** from each novel finding and grep the full codebase for sibling instances the agents may have missed. LLM agents are good at contextual analysis but unreliable at exhaustive enumeration — they tend to find one instance per pattern and move on.

For each LLM agent finding:
1. Identify the generalizable pattern (e.g., "403 response without logger.warning", "silent catch of integrity check", "asymmetric audit logging between sibling handlers")
2. Construct a grep query that would match ALL instances of that pattern across the codebase (not just the file the agent checked)
3. Run the grep and compare results against already-tracked findings (both from this audit and open tasks)
4. Any new matches are "post-scan siblings" — add them to the appropriate batch with a note: `*(Post-scan sibling of TASK-NNNN.)*`

**Skip patterns already in `.claude/checks.yml`** — the pre-scan in Step 2b already runs those checks deterministically across the entire codebase; amplifying them duplicates pre-scan results. Check the `checks.yml` registry before constructing a grep; if a check already covers the pattern (e.g., `semgrep-llm-cost-abuse` for `max_output_tokens`, `semgrep-http-client-redirect` for `follow_redirects`, `dangerous-inner-html`), skip amplification and rely on pre-scan. For patterns **not** covered by a pre-scan check — XML prompt-boundary escaping, alerting-channel message escaping, delete-endpoint audit trails, state-mutation success logging — Step 3b post-scan grep amplification IS the primary mechanism; do not skip. Focus Step 3b on patterns that aren't expressible as simple regex — semantic invariants, symmetric-logging gaps, silent-catch integrity failures, multi-line constructs.

**Example amplifications from a real audit** *(chosen to illustrate patterns that pre-scan cannot express as regex):*

| LLM found | Post-scan grep | Siblings caught |
|-----------|---------------|-----------------|
| 403 without logging in `<api module>/routes/<route>.py` | `grep -rn "HTTPException(status_code=403" <api module>/routes/` + verify no nearby `logger.warning` | 1 more in a sibling route file |
| Silent catch of HMAC mismatch in `<api module>/routes/<route>.py` | `grep -rn "compare_digest\|hmac.compare" <api module>/` + verify each mismatch path calls a violation-tracking helper | Integrity-check sites in sibling handlers |
| Asymmetric credit logging (post-balance only) in one `<payments service module>` handler | `grep -rn "logger.info.*credit" <payments service module>` + verify each mutation logs both prior and post balance | Top-up and bonus-grant handlers |

Report post-scan results:
```
Post-scan amplification: <N> patterns grepped → <N> new siblings found
```

## Step 4: Deduplicate and Organize

**Deduplication:** For each finding (from both grep pre-scan, LLM agents, and post-scan siblings), check if `open_task_index` already contains a task at the same `file:line`. If so, skip the finding. Track skipped count for the summary.

**Batch grouping by threat category:**

| Batch name | Categories |
|------------|-----------|
| Injection & SQL Safety | A03 (server-side injection) |
| Authentication & Session | A07 |
| Authorization & Access Control | A01 |
| Data Exposure & Secrets | A02 |
| SSRF & External Requests | A10 |
| XSS & Client-Side Security | A03 (client-side) |
| Security Configuration | A05 |
| Dependency Vulnerabilities | A06 |
| LLM & AI Security | LLM |
| Privacy & Data Retention | Privacy |
| Logging & Monitoring | Logging |

- Only create batches that have ≥1 task
- If a scope filter results in few findings per category, consolidate small batches (≤2 tasks) into an "Additional Security Findings" batch
- Number batches sequentially from `next_batch_number`

## Step 4b: Overlap Analysis

After organizing batches, compute file-level overlap between all batches in this Round:

1. For each batch, collect the set of file paths from its task `file:line` locations (strip line numbers)
2. For each pair of batches, check if their file sets intersect
3. Tag each batch:
   - **No shared files with any other batch** → `Overlap: none`
   - **Shares file(s) with other batches** → `Overlap: batch-N, batch-M` (list all overlapping batch numbers)

This tag is written into the batch header in Step 5c and used by `/auto-fix` to determine which batches can be processed in parallel.

## Step 5: Write to `review_tasks.md`

### 5a. File Bootstrap (if `review_tasks.md` doesn't exist)

Create the file with the standard header:

```markdown
# Code Review Tasks

> Comprehensive security and code quality audit of the full codebase.
> Tasks are organized into batches by file locality so an agent can claim one batch and ship it as a single PR.

---

## Legend

- **Severity**: 🔴 High · 🟡 Medium · 🟢 Low
- **Status**: `[ ]` Open · `[/]` In Progress · `[x]` Done
- **Batch status**: Pending · In Progress · Review Ready · Merged

---
```

### 5b. Round Header

Check if a Round with today's date already exists (e.g., from a `/codebase-review` run earlier today):
- **If yes:** append new batches inside that Round (after the last batch, before the next `---` separator or `## Statistics`)
- **If no:** create a new Round section:

```markdown
## Round N (YYYY-MM-DD) — OWASP Security Audit

```

Use the next Round number (last Round N + 1).

### 5c. Batch Format

For each batch, include the `> **OWASP:**` line to distinguish security batches from quality batches:

```markdown
### Batch N — <Threat Category Name> `Pending`

> **OWASP:** A01, A03 (whichever categories this batch covers)
> **Scope:** <comma-separated file paths or globs>
> **Branch:** `fix/batch-N-<kebab-name>`
> **Verify:** `<test or build command for this scope>`
> **Overlap:** <none | batch-M, batch-P>

- [ ] **TASK-N**: <Imperative title> 🔴
  `<file:line>` — **Exploit scenario:** <how an attacker could exploit this>. **Remediation:** <concrete fix with code suggestion>.

- [ ] **TASK-N+1**: <Imperative title> 🔴
  `<file:line>` — **Exploit scenario:** <description>. **Remediation:** <fix>.
```

Each security task must include:
1. **Exploit scenario** — how an attacker would exploit the finding
2. **Remediation** — concrete fix with specific code or configuration change

### 5d. Statistics Update

If a `## Statistics` section exists, append rows for the new batches. Otherwise, create the Statistics section after the last Round.

### 5e. Convention fire ledger (stale-rule capture)

If Step 2b triage recorded any **stale-verdicts** (mechanical checks that fired on non-issues because their security convention no longer applies), append them to the `## Convention fire ledger` section of `review_tasks.md`. This section is the durable, round-attributed record the demotion gate (Step 9b) recomputes from — the demotion counterpart to the archived-round record the promotion gate reads.

**Placement is load-bearing:** the ledger is a single standalone section at the **end** of `review_tasks.md`, *outside* every `## Round` block, so `archive_review_tasks.py` (which only relocates `## Round N` batch blocks) never moves or drops it. Create it lazily on the first stale-verdict; never put it inside a Round.

```markdown
## Convention fire ledger

> Per-rule stale-verdicts from review-round triage (Step 2b). The demotion gate (Step 9b)
> retires a rule once it accrues stale-verdicts across **2+ distinct rounds**. A rule's rows
> are cleared when Step 9b adjudicates it (retire / demote-to-advisory / tighten / keep).

| Round | Rule ID | Mechanism | Verdict | Why (the change event) |
|-------|---------|-----------|---------|------------------------|
| <N> | `<rule-id>` | checks.yml / semgrep / pre-commit / pip-audit | stale | <one line: which convention moved out from under it> |
```

One row per (rule, round): a rule fires many times in a round but earns at most **one** stale-verdict row per round — this mirrors promotion's "recurred across rounds," not "fired N times this round." Do not add a second row for a rule that already has one for this Round. (When both `/codebase-review` and `/security-audit` run in the same Round, share the one ledger section — append, do not duplicate.)

## Step 6: Report Summary

Print an OWASP coverage table and batch summary:

```
OWASP Security Audit — Round N (YYYY-MM-DD)
Scan: Full / Incremental (since YYYY-MM-DD)
Scope: <area or "all">
Files audited: <N>

Map coverage audit:  security map <N> file gaps, convention map <M> file gaps (fixed inline: yes/no)
Pre-scan (grep):     <N> findings (deterministic)
LLM agents:          <N> findings (contextual)

OWASP Coverage:

| Category | Findings | Source |
|----------|----------|--------|
| A01 Access Control | <N> | grep: N, LLM: N |
| A02 Data Exposure | <N> | grep: N, LLM: N |
| A03 Injection | <N> | grep: N, LLM: N |
| A05 Misconfiguration | <N> | grep: N, LLM: N |
| A06 Dependencies | <N> | scan |
| A07 Authentication | <N> | LLM: N |
| A10 SSRF | <N> | grep: N, LLM: N |
| XSS (A03 client) | <N> | grep: N, LLM: N |
| LLM / AI Security | <N> | grep: N, LLM: N |
| Logging | <N> | grep: N, LLM: N |

Batches:

| Batch | Tasks | 🔴 | 🟡 | 🟢 |
|-------|-------|-----|-----|-----|
| <name> | <n> | <n> | <n> | <n> |
| ...   |       |     |     |     |
| **Total** | **N** | **N** | **N** | **N** |

Duplicates skipped: <N> (already tracked as open tasks)
Task IDs: TASK-<first> through TASK-<last>

Dependency scan: <summary or "pip-audit/npm audit not available — install for coverage">
```

## Step 7: Commit Generated Tasks

After writing to `review_tasks.md`, **always commit the changes** so they survive branch merges and stash operations during `/review-close`:

```bash
git add review_tasks.md review_tasks_archive.md 2>/dev/null
git commit -m "docs: add Round <N> security audit tasks to review_tasks.md"
```

This prevents task loss when `/review-close` later stashes uncommitted changes for branch merges.

## Step 8: Convention Candidate Extraction

After writing all tasks, scan the findings for patterns that could become new Prevention Convention entries:

1. Review all tasks written in this Round and look for **recurring patterns** — security findings that appear 3+ times across different files or that represent a systemic gap not covered by the existing convention bullets in `CLAUDE.md`
2. For each recurring pattern, draft a candidate Prevention Convention bullet following the existing format:
   - Lead with the rule (imperative: "All X must Y")
   - Reference the specific utility, validation function, or security control
   - Match the style of the existing bullets in `CLAUDE.md` § Prevention Conventions
3. For each candidate, also draft a one-line convention map entry and list the `.claude/convention_map.md` sections it should be added to
4. Write candidates to `.pending-docs/convention-candidates.md` using this format (append if the file already exists from a `/codebase-review` run in the same Round):

```markdown
# Convention Candidates — Round N (YYYY-MM-DD)

## Source: /security-audit

| # | Candidate Rule | OWASP Category | Occurrences | Example Tasks | Map Sections |
|---|----------------|----------------|-------------|---------------|--------------|
| 1 | <draft rule text> | A01/A03/A07/etc. | <N> findings | TASK-X, TASK-Y | `<auth module>/*.py`, `<api module>/server.py` |
| 2 | ... | ... | ... | ... | ... |
```

5. If no patterns recur 3+ times, skip this step and note "No convention candidates — all findings were one-off" in the summary

## Step 9: Convention Promotion (Interactive)

If Step 8 produced convention candidates in `.pending-docs/convention-candidates.md`, promote them now rather than deferring to `/review-close`.

> **Where these writes land — read `_shared/promotion-write-target.md` first.** In a **consumer install** (detected by `.claude/sysop.lock`), the base maps `.claude/convention_map.md` / `.claude/security_map.md` / `.claude/checks.yml` are regenerated from upstream on every `sysop-update.sh`, so a promotion written only to a base file is silently lost on the consumer's next update. Dual-write to the `.project.*` overlay per that partial (the mechanism-by-mechanism table). In the **source repo** (no lock) the overlay does not exist; write the base files exactly as below.

1. **Apply the cross-round survival gate, then present.** A candidate is promotable only if its pattern has **recurred across two review rounds** — present in *this* Round's findings **and** in an earlier Round's archived `review_tasks.md`. A 3+ burst confined to this Round is not promotable on its own (it filters out one-off noisy rounds). Recurrence is *computed* from the durable record each round — round-attributed `.claude/convention_map.md` entries + archived `review_tasks.md` Rounds — not maintained as a carried-forward watch-list.
   - For each candidate, check the prior-Round archive for an earlier occurrence of the same pattern.
   - **Cleared the gate (recurred):** present to the user — draft rule text, OWASP category, occurrence count, the earlier Round it first surfaced in, and example tasks. Ask: **promote** or **skip**.
   - **First seen this Round:** do not promote. Note "held for cross-round recurrence — first surfaced Round N" in the summary. This Round's `review_tasks.md` is itself the durable record that lets a future Round detect the recurrence.

2. **For promoted candidates:**
   a. **Choose enforcement mechanism (mechanical-first).** Walk this menu in order and stop at the first option that fits. Document the chosen branch (i/ii/iii/iv) in the promotion report so the routing is auditable. Default is mechanical — prose is the fallback, not the first reach.

      - **(i) `.claude/checks.yml` regex** — when the anti-pattern is a single-line grep with low false-positive rate, gated at review time (CI/`run_checks.sh`). 4-prompt cycle:
         1. Draft an entry following the format of existing checks in `.claude/checks.yml` (id, name, category, severity, paths, include, pattern, negative_pattern, description, convention, used_by, blocking).
         2. Present to the reviewer: `[yes-blocking / yes-advisory / skip]`.
         3. On approval: append the entry to `.claude/checks.yml` — and, in a consumer install, add the identical entry to `.claude/checks.project.yml` so it survives `sysop-update.sh` (per `_shared/promotion-write-target.md`). Set `blocking: true` only if zero false positives have been verified against the current codebase via `bash scripts/run_checks.sh`; otherwise `blocking: false` (advisory).
         4. On skip: log the reason in the promotion report.

      - **(ii) `.claude/semgrep/*.yaml` AST rule** — when the rule needs structural awareness (function arguments, decorator stacking, control flow) but is still mechanical. 4-prompt cycle:
         1. Draft a rule modeled on existing files in `.claude/semgrep/` and read `.claude/semgrep/README.md` for the rule conventions.
         2. Present to the reviewer: `[approve-with-fixture / approve-no-fixture / skip]` (warning: skipping the fixture means no regression lock).
         3. On approve-with-fixture: write the rule and a matching `.claude/semgrep/fixtures/` file capturing both a triggering example and a negative example.
         4. On skip: log the reason in the promotion report.

      - **(iii) `scripts/hooks/pre-commit` regex** — same regex shape as (i) but fires in the developer's editor cycle, not just at CI gate time. Choose (iii) over (i) when immediate local feedback matters more than CI gating; choose (i) over (iii) when the rule applies to file types not staged in typical edits or when CI is the canonical gate. (Choosing both is acceptable when local feedback and CI gating both add value.) 4-prompt cycle:
         1. Draft the check following the existing B-tier (blocking) or A-tier (advisory) pattern in `scripts/hooks/pre-commit`. Append the next unused letter; read the header comment listing for the current range rather than assuming a fixed range.
         2. Present to the reviewer: `[yes-blocking / yes-advisory / skip]`.
         3. On approval: append to `scripts/hooks/pre-commit`, update the header comment listing.
         4. On skip: log the reason in the promotion report.

      - **(iv) Prose fallback in CLAUDE.md** — only when the rule requires semantic reasoning, multi-call context, or judgment that none of (i)–(iii) capture. **Canonical fallback list:** audit-trail symmetry, tier enforcement, response filtering, rate-limit coverage, error caching. OWASP A01/A07 access-control symmetry checks (e.g., tier enforcement, ownership verification across endpoints) typically need semantic reasoning to verify across the route layer and stay prose. If the candidate doesn't match one of these patterns, the reviewer must justify in writing why (i)–(iii) all fail before defaulting to (iv).

   b. **If mechanical (option i, ii, or iii):** the check IS the rule. Add a one-line `> AST-backed equivalent: <rule-id> (in .claude/semgrep/)` reminder (or `equivalents:` plural when multiple) to every matching section of `.claude/convention_map.md` (use the `Map Sections` column from the candidates table). For checks.yml or pre-commit entries, use the analogous form (`> checks.yml: <id>` / `> pre-commit: <letter>`). **Do not** insert a CLAUDE.md prose bullet — that defeats the point of mechanizing. In a consumer install, also mirror the reminder into `.claude/convention_map.project.md` per `_shared/promotion-write-target.md` (the base copy is regenerated away on update; the overlay copy re-supplies it).

   c. **If prose-fallback (option iv):** insert into the correct subsection (Frontend, Backend, or Testing) of `CLAUDE.md § Prevention Conventions`, following the existing bullet format (`CLAUDE.md` is the consumer's own file — no overlay mirror needed). Then add the new convention as a one-line reminder to every matching section of `.claude/convention_map.md` — and, in a consumer install, mirror that reminder into `.claude/convention_map.project.md` per `_shared/promotion-write-target.md`.

   d. **Sweep for existing violations (route by anchor type):** the explicit `[fix-inline / generate-batch / skip]` decision prompt below fires regardless of whether the rule was added mechanically or as prose. Mechanical-rule violation reports replace the **derive-pattern** step below — not the **decision** step.
      1. Decide the anchor type up-front:
         - **Symbol-anchored convention** (e.g., "all callers of `get_verified_user` must also call X", "every `tools.validate_sql_safety` caller needs Y"): use `LSP.findReferences` on the symbol via Claude Code's built-in `LSP` tool. This catches import aliases and renames that grep misses.
         - **Pattern-anchored convention** (e.g., "all `fetch()` calls with dynamic paths need `encodeURIComponent()`", "`str(e)` not allowed in response bodies"): derive a grep pattern from the anti-pattern. Use the `Map Sections` column to scope the search to relevant directories. Search for the **anti-pattern**, not the correct pattern.
         - **Already mechanized** (option a.i or a.ii was taken): skip the derive step and use the rule's first-run output as the violation list. `bash scripts/run_checks.sh` for checks.yml; `semgrep --config .claude/semgrep/<rule>.yaml` for semgrep.
         - **Not mechanically searchable** (requires AST analysis, semantic understanding, or multi-file context): skip and note "Sweep skipped — pattern not mechanically searchable."
      2. Exclude files already tracked as open tasks in `review_tasks.md`.
      3. Present the sweep summary:
         ```
         Convention Sweep — Candidate #<N>: <short name>
         Pattern:  <what was searched for>
         Hits:     <N> across <N> files

           <file1>    (<N> hits)
           <file2>    (<N> hits)

         Action? [fix-inline / generate-batch / skip]
         ```
      4. Wait for the reviewer's decision:
         - **fix-inline** (only offer when hits <=15 AND fix is mechanical): Apply the fix to all files, `git add` the changed files.
         - **generate-batch**: Create a new batch in `review_tasks.md` within the current Round. One task per file, severity 🟡. Use next sequential batch and task IDs.
         - **skip**: Note "Sweep skipped — <N> existing violations" in the report.

3. **Emit promotion summary** before deleting the candidates file: print one line of the form `Promotion summary: <N> total (<M> mechanical / <K> prose)` and include the same line in the commit message body (step 5). Future reviewers can grep ratios with `git log --grep "Promotion summary"`.

4. **Delete** `.pending-docs/convention-candidates.md` after processing all candidates.

5. **Commit** any changes (the `.project.*` overlay paths are the consumer-install dual-write targets from `_shared/promotion-write-target.md`; `2>/dev/null` tolerates their absence in the source repo):
   ```bash
   git add CLAUDE.md .claude/convention_map.md .claude/convention_map.project.md .claude/checks.yml .claude/checks.project.yml .claude/semgrep/ scripts/hooks/pre-commit review_tasks.md 2>/dev/null
   git commit -m "docs: promote <N> conventions from Round <N>

   Promotion summary: <N> total (<M> mechanical / <K> prose)"
   ```

This closes the feedback loop: audits find recurring issues → conventions are proposed → convention map is updated → future code is checked against scoped conventions → fewer audit findings over time.

<!-- Canonical process: WORKFLOW.md §3.5 (Convention promotion lifecycle) -->

## Step 9b: Convention Demotion (Interactive)

Run this **every round, independently of Step 9** — a stale rule accrues whether or not this round produced promotion candidates, so this block must **not** be gated on Step 8 output (Step 9 is; folding the demotion check under that trigger would skip it on quiet rounds — the same reasoning that put the Tier 1 staleness sweep at Step 2a rather than here).

This is the **FP-driven** half of convention demotion. Tier 1 (Step 2a-3) statically detects *map* staleness (sections/citations that lost their code); Step 9b retires the **blocking-mechanical rules** whose false-positive cost the map sweep cannot see — the rules that keep halting commits on things that are no longer issues.

1. **Recompute retirement candidates from the ledger.** Read the `## Convention fire ledger` section of `review_tasks.md` (Step 5e). Group rows by `Rule ID` and count the **distinct Rounds** each rule has a stale-verdict in.
   - **Cleared the cross-round gate (stale-verdicts in 2+ distinct Rounds):** retirement candidate. This is the exact mirror of promotion's cross-round survival gate — a single-round burst of stale-verdicts is held, filtering one-off noisy rounds, just as a single-round burst of true positives is not promotable on its own.
   - **First seen this Round (1 distinct Round):** do not prompt. The ledger row is itself the durable record that lets a future Round detect the recurrence. Note "held for cross-round recurrence — first stale-verdict Round N" in the summary.

   **Also ingest the static removed-category candidates (from Step 2a-3 — no ledger row).** The map staleness sweep routes any *removed-category* candidate here: a promoted **prose** security convention whose `.claude/security_map.md` (or `convention_map.md`) section now matches zero tracked files. A pure-prose convention fires no mechanical check, so it never earns a ledger row — without this path it would be re-detected every round but have nowhere to be retired. These arrive via deterministic static detection, so they **bypass the 2+-round gate** (a zero-match section is already unambiguous). For each, present the stale section + the `CLAUDE.md § Prevention Conventions` bullet, and ask **`[retire / keep]`** — but for a security convention, **confirm the protection it encoded genuinely moved elsewhere (or is obsolete) before retiring**, and bias toward **keep** when unsure (a removed map section can mean the defense moved, not that it is gone). On **retire**, remove the bullet + its now-stale `security_map` / `convention_map` section; count it in the demotion summary's advisory-or-prose tally.

2. **For each ledger-derived retirement candidate, present and decide.** Show: rule id, mechanism (`checks.yml` / `semgrep` / `pre-commit` / `pip-audit`), current `blocking:` status, the Rounds it was judged stale in, and the recorded "why." Then ask: **`[retire / demote-to-advisory / tighten / keep]`**.

   - **retire** — the rule is genuinely moot. Remove it at its mechanism, then strip its mechanized-equivalent reminder from every `.claude/convention_map.md` / `.claude/security_map.md` section that cites it:
      - `checks.yml`: delete the `- id: <rule-id>` entry from `.claude/checks.yml`; remove the matching `> checks.yml: <rule-id>` reminder lines.
      - `semgrep`: delete `.claude/semgrep/<rule>.yaml` **and** its `.claude/semgrep/fixtures/` file; remove the matching `> AST-backed equivalent: <rule-id>` reminder lines.
      - `pre-commit`: delete the `scripts/hooks/pre-commit` check, update the header-comment letter listing; remove the matching `> pre-commit: <letter>` reminder lines.
      - If the rule had also become a **prose** convention bullet, remove that `CLAUDE.md § Prevention Conventions` bullet — the deliberate, human prose-retirement that Tier 1 (Step 2a-4) routes here.
      - Optional hygiene: drop any now-orphaned `<rule-id>` lines from `.claude/checks_baseline.txt` (inert once the check id is gone, but tidy).
      - **Consumer install** (per `_shared/promotion-write-target.md`): retire the rule where it durably lives — a **locally-promoted** rule is in the `.project.*` overlay, so delete it from `.claude/checks.project.yml` / `.claude/convention_map.project.md` / `.claude/security_map.project.md` (editing only the base leaves the overlay to re-supply it on the next update); a **core/pack-shipped** rule can't be deleted from a consumer install (the concat re-supplies it), so suppress a `checks.yml`-mechanism one via an override entry in `.claude/checks.project.yml` (`paths: ["__disabled_no_op__"]`) — a core semgrep/pre-commit rule has no consumer-side suppression and routes genuine retirement upstream (see the partial).
   - **demote-to-advisory** — the rule still catches a real issue sometimes, but the false-positive halt is not worth it. Flip `blocking: true → false` in `.claude/checks.yml` (or move a `pre-commit` letter from the B-tier blocking range to the A-tier advisory range). The signal survives; the commit-halt does not. The lower-regret middle option when "retire" feels premature.
   - **tighten** — the rule is **over-broad from birth** (staleness Mode G), not genuinely moot: it has flagged non-issues since it shipped because its `pattern`/`paths` are too wide. Narrow the regex or glob instead of retiring. Not a retirement; the rule stays, scoped better.
   - **keep** — override the signal: the rule is still valuable despite the false positives. Log the reason in the demotion report.

   **Security caveat (this skill's rules are security rules — apply by default):** before retiring a rule that enforces a security property (a sanitizer, an auth guard, an injection/escape check, a CVE gate), confirm the protection it encodes is **genuinely gone or moved elsewhere** — a stale-looking security check is often a *version-fix* (Mode E: a dependency bump mooted the local check) where the defense should still exist. When unsure, prefer **demote-to-advisory** or **tighten** over **retire**, mirroring the refresh-before-retire discipline in Step 2a-3's security caveat. A missed true positive on a security rule has direct production impact; bias toward keeping.

3. **Clear the adjudicated rule's ledger rows.** For **every** disposition (retire / demote-to-advisory / tighten / keep), delete that rule's rows from the `## Convention fire ledger`. The verdict has been acted on, so the counter resets — this bounds the ledger **and** prevents a "keep" decision from re-prompting every subsequent round. The rule only re-surfaces if fresh staleness recurs across 2+ new Rounds.

4. **Emit demotion summary** — print one line `Demotion summary: <N> retired (<B> blocking / <A> advisory-or-prose)` and include the same line in the commit body. Future reviewers grep the loop with `git log --grep "Demotion summary"` (mirrors the `Promotion summary:` trailer). The `retired` tally counts retirements only — mirroring `Promotion summary:`, which counts only promotions; **demote-to-advisory / tighten / keep** dispositions are noted in the demotion report but not in the tally. If nothing was retired *and* no rule was demoted/tightened, print `Demotion summary: 0 retired` and skip the commit.

5. **Commit** any changes (fold into the Step 9 promotion commit if that ran this round, otherwise a standalone commit; the `.project.*` overlay paths cover consumer-install retirement per `_shared/promotion-write-target.md`):
   ```bash
   git add CLAUDE.md .claude/convention_map.md .claude/convention_map.project.md .claude/security_map.md .claude/security_map.project.md .claude/checks.yml .claude/checks.project.yml .claude/checks_baseline.txt .claude/semgrep/ scripts/hooks/pre-commit review_tasks.md 2>/dev/null
   git commit -m "docs: retire <N> conventions from Round <N>

   Demotion summary: <N> retired (<B> blocking / <A> advisory-or-prose)"
   ```

This closes the demotion half of the loop: a rule that keeps firing on non-issues is caught at triage → recorded round-attributed in the ledger → retired once the staleness survives across rounds → the gate stops halting commits on a convention the codebase has outgrown. Symmetric to the promotion loop above. The one principled asymmetry: promotion *recomputes* recurrence from durable findings (a true positive becomes a task), while demotion must *maintain* the ledger (a stale positive becomes nothing, so its verdict would otherwise be thrown away) — see WORKFLOW.md §3.5.

<!-- Canonical process: WORKFLOW.md §3.5b (Convention demotion lifecycle) -->

End with: "Claim a security batch and start remediating, or run `/codebase-review` for a broader code quality pass."
