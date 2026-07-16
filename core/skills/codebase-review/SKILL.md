---
name: codebase-review
description: Comprehensive code quality review — generates batched tasks in review_tasks.md
argument-hint: "[--full | --changes-only] [--scope backend|frontend|pipeline|scripts]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

End-of-sprint code quality audit. Scans the codebase for correctness, convention violations, dead code, test gaps, and architectural drift. Produces a new Round (or appends to today's) in `review_tasks.md` with deduplicated, batched tasks ready to be claimed.

## Pre-flight: Permission Guard

Before any work, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `auto` mode + `skipAutoPermissionPrompt: true`, a missing rule for `bash scripts/run_checks.sh` silently halts the check-registry stage with no actionable error.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(bash scripts/run_checks.sh)`
- `Bash(bash scripts/run_checks.sh:*)`
- `Bash(python scripts/archive_review_tasks.py:*)`
- `Bash(python3 scripts/archive_review_tasks.py:*)`
- `Bash(.venv/bin/python3 scripts/archive_review_tasks.py:*)` — Phase 45b venv-prefixed variant (preferred when the consumer has a venv with PyYAML)

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "runs the bundled check registry (grep + LSP + Semgrep) against the codebase, and may need to archive `review_tasks.md` if it exceeds 125KB"). Do not proceed.

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

If no scope mapping is defined in the project's CLAUDE.md, fall back to scanning the path roots discovered from `<project>/.claude/convention_map.md` section headers (see Step 2a-1 below for the parsing logic).

**Build file list:**
- Full scan: `git ls-files -- <paths>` (filtered by scope)
- Incremental: `git log --since="<last-round-date>" --name-only --pretty=format: -- <paths> | sort -u`
- Exclude: `*.md`, `*.lock`, `*.txt`, `*.csv`, image files, `__pycache__/`, `node_modules/`, `.next/`, `package.json`, `package-lock.json`, `tsconfig.json`, `tsconfig.*.json`
- Keep: `*.yml`, `*.yaml`, and other `*.json` files (may contain security-relevant config — e.g., deploy configs like `firebase.json`, `apphosting.yaml`, `vercel.json`, `cloudbuild.yaml`, plus GitHub Actions workflows)

Report to the user before proceeding:
```
Scan mode:   Full / Incremental (since YYYY-MM-DD)
Scope:       <area or "all">
Files:       <N> files to review
```

## Step 2: Collect Existing Task Context

Run these in parallel:
- Read `review_tasks.md` — find the highest `TASK-N` ID (new tasks start at N+1)
- Build a deduplication index: collect all **open** tasks (`[ ]` or `[/]`) with their `file:line` references
- Read `.claude/convention_map.md` — scoped convention rules per file group (this is the primary convention reference for review agents)
- Read `.claude/security_map.md` — scoped OWASP checks per file group (used by Map Coverage Audit in Step 2a)
- Read `CLAUDE.md` — for general context (architecture, env vars, key files) but NOT for convention injection into agents

Record:
- `next_task_id` = highest TASK-N + 1
- `next_batch_number` = highest Batch N + 1
- `open_task_index` = set of `(file, line)` tuples from open tasks
- `convention_sections` = parsed map from `convention_map.md` (file patterns → convention bullets)

## Step 2a: Map Coverage Audit (Coverage Gaps)

Before launching any review agents, cross-reference both maps against the actual codebase and CLAUDE.md Prevention Conventions to find coverage gaps. This is a deterministic check — no LLM needed.

### 2a-1. Files not matched by any convention_map section

Parse the `## ` section headers from `.claude/convention_map.md` to extract the file globs for each section (the section header format is `## <glob list> — <Section Name>`). Derive the unique top-level path roots from those section globs (e.g., `<api module>/`, `<frontend>/`, `<scripts dir>/`, `<tests dir>/`). Then run `git ls-files -- <derived roots>` and check each code file against the extracted globs. Collect files that don't match any section.

**Exclude from the gap report** (these are expected to be unmatched):
- Config-only files: `Dockerfile`, deploy configs (e.g., `firebase.json`, `apphosting.yaml`, `vercel.json`), `*.yml`, `*.yaml`, `*.json`, `*.sql`
- Docs: `*.md`
- Small/stable utility modules with no user input or network surface (project-specific list — see `<project>/CLAUDE.md` § "Map coverage exclusions")
- Static data files (e.g., `<frontend>/data/*.ts`, `<frontend>/fixtures/*.ts`)
- Container infrastructure files (e.g., `<datajobs dir>/Dockerfile`, `<datajobs dir>/requirements.txt`)

Report unmatched code files:
```
Convention Map Coverage — Unmatched Files:
  <N> code files not matched by any convention_map section
  <file list, grouped by directory>
```

### 2a-2. Files not matched by any security_map section

Parse the `## ` section headers from `.claude/security_map.md` to extract the file globs for each section (same header format as convention_map). Derive the unique top-level path roots from those section globs. Then run `git ls-files -- <derived roots>` and check each code file against the extracted globs. Collect files that don't match any section.

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

### 2a-3. CLAUDE.md Prevention Convention bullets not in any convention_map section

Read `CLAUDE.md` § Prevention Conventions (subsections: Frontend, Backend, Testing). For each bullet, extract the bold prefix (the text between `**...**` at the start). Search `.claude/convention_map.md` for each prefix string. Collect any bullets whose prefix does not appear in any convention_map section.

Report orphaned conventions:
```
Convention Map Coverage — Unmapped Conventions:
  <N> Prevention Convention bullets not found in any convention_map section

  Frontend:
    - **<bullet name>**: not mapped to any file section
  Backend:
    - **<bullet name>**: not mapped to any file section
```

### 2a-4. Map staleness sweep (stale sections + dead citations)

The checks above run **forward** (code → map: which files lack coverage). This check runs **backward** (map → code: which map content has lost its referent), catching conventions that went stale when the code moved out from under them. Like the forward checks it is deterministic — no LLM needed — and it **flags candidates only; it never auto-retires a convention** (the retirement *decision* stays human and deliberate — see the routing note in 2a-5).

**(a) Stale sections — glob matches no tracked file (a removed category, staleness Mode C).** For each `## <glob list> — <Section Name>` section parsed above, run `git ls-files -- <section globs>`. A section whose globs match **zero** tracked files has lost its scoped surface — flag it. Before treating an empty section as stale, rule out three look-alikes:
- **Relocation, not removal:** if the forward pass (2a-1 / 2a-2) found newly-unmatched files in a sibling location, the files probably *moved* — the fix is to update the glob, not retire the section.
- **Aspirational / lead section:** a glob may legitimately precede the code so new files get coverage before they are written (§ 5.3 feedback loop). A section added in a recent round for not-yet-created files is not stale — note and skip.
- **Un-substituted placeholder:** a glob still in `<...>` placeholder form matches nothing because the consumer has not localized it to real paths — an install artifact, not staleness. Skip it.

**(b) Dead citations — a cited symbol is gone (a renamed/deleted helper, staleness Mode B).** For each bullet that cites a concrete in-repo identifier (a backticked symbol naming a project helper/function/component — e.g. the canonical `_sanitize_log`, `useAbortableFetch`, `isSafeHref`), run `git grep -nw -- '<symbol>'` across tracked files. Zero hits means the cited symbol was renamed, moved, or deleted — flag the bullet. Scope guards keep false positives down (mirroring the source-verification discipline in `_shared/adversarial-review.md` dimension #9 — when you cannot tell, leave it unflagged):
- Skip angle-bracket placeholders (`<api module>`, `<components dir>`) — not real symbols.
- Skip library/framework identifiers (`AbortController`, `useEffect`, `yaml.safe_load`) — these have no in-repo definition by design, so their absence is not staleness. Only test identifiers that resolve (or once resolved) to an in-repo definition.

**Distinguish refresh from retirement.** A dead citation usually means the *rule is still valid* and only the helper name changed → **refresh the citation**. An empty section usually means the *category is gone* → retirement candidate. But beware **over-broad-from-birth** (Mode G): a glob that never matched much presents identically to a removed category, yet that is a calibration miss, fixed by **tightening the glob, not retiring the rule**. Infer retirement only when the category genuinely existed and was removed. This sweep catches the statically detectable staleness (Modes B and C) only; default-moved, superseded, version-fix, and floor-moved staleness have no static signal and are out of scope here.

Report:
```
Map Staleness — Retirement / Refresh Candidates:
  Stale sections (glob matches 0 tracked files):
    convention_map.md § <Section Name> — <glob>
    security_map.md   § <Section Name> — <glob>
  Dead citations (cited symbol absent from the codebase):
    convention_map.md § <Section Name> — bullet cites `<symbol>`
```

### 2a-5. Offer to fix inline

If any check finds gaps or staleness:

```
Convention map has <N> file coverage gaps and <M> unmapped convention bullets.
Security map has <P> file coverage gaps.
Map staleness: <Q> stale sections, <R> dead citations.
Fix these before launching review agents? [y/N]
```

If yes:
- For unmatched files: propose new sections or glob expansions for the relevant map and apply them
- For unmapped bullets: propose adding the bullet to the relevant existing section(s) and apply them
- For **dead citations** and **relocated sections**: refresh the citation or update the glob in place — low-stakes map hygiene, apply directly. In a **consumer install** (`.claude/sysop.lock` present), edit hygiene that targets a **locally-authored `.project.*` overlay section** in the overlay file, not the regenerated base copy (per `_shared/promotion-write-target.md`); hygiene on a **core/pack-shipped** section refreshes from upstream on the next update, so a base-only edit is transient — note it but don't rely on it persisting
- For **stale sections reflecting a genuinely removed category** (a promoted convention that no longer has any code to govern): **do not delete the CLAUDE.md § Prevention Conventions bullet here.** Record it as a retirement candidate in the final summary report and route the decision to the deliberate, human retirement step (the interactive **Step 9b: Convention Demotion** prompt — symmetric to convention promotion, and the Tier 2 home where Step 9b also retires the blocking-mechanical rules whose false-positive cost this static map sweep cannot see). Tier 1 detects and reports; the retirement *decision* stays human and interactive.
- Commit: `git add .claude/convention_map.md .claude/convention_map.project.md .claude/security_map.md .claude/security_map.project.md && git commit -m "docs: update convention_map.md and security_map.md coverage"` (the `.project.*` overlay paths pick up any consumer-install hygiene edits; they no-op in the source repo where the overlays don't exist)

If no (or audit is clean), proceed to Step 2b. Note gaps **and staleness candidates** in the final summary report either way.

## Step 2b: Grep Pre-Scan (Deterministic Checks)

Before launching LLM agents, run the shared check registry to find mechanical convention violations. These produce findings directly — no LLM interpretation needed.

```bash
bash scripts/run_checks.sh --mode quality
```

Collect all output lines as "pre-scan findings." Mark each with `[grep]` source tag in your notes to distinguish from LLM findings — this helps track coverage improvement over time.

Checks with a `notes: "Needs LLM triage"` field in `.claude/checks.yml` require manual verification before recording as findings — the script outputs all matches including potential false positives for those checks. **Triage each flagged match yourself (the skill runner) — do not delegate to a subagent.** Read the `notes` field in the YAML to understand the false-positive shape, read the surrounding code at each match site, and record only confirmed findings. Subagents spawned in Step 3 get scoped convention bullets, not raw pre-scan matches; triage here keeps that boundary clean.

These findings are treated identically to LLM agent findings in Step 4 (deduplication, batching).

**Stale-rule capture (convention demotion — Tier 2).** Triage produces a verdict on every flagged match, and one verdict is normally discarded: *the rule itself is moot.* When a mechanical check (a `checks.yml` regex, a `semgrep-*` rule, or a `pre-commit` letter) fires on a match that is **not** a real violation **because the convention it enforces no longer applies** — a default moved, a category was migrated away, a dependency bump fixed the underlying issue (the change-event taxonomy in WORKFLOW.md §3.5) — record a **stale-verdict** for that rule in the `## Convention fire ledger` (Step 5e). This is the demotion counterpart to Step 8's promotion-candidate extraction: promotion captures recurring *true* positives, demotion captures recurring *stale* ones. Guards (mirroring the Step 2a-4 staleness discipline and `_shared/adversarial-review.md` dimension #9):
- **Rule moot, not instance exception.** A single legitimate exception (one call site that is genuinely fine) is *not* a stale-verdict — that is what a baseline entry or `# nosemgrep` is for, and the rule stays. Record a stale-verdict only when the rule keeps flagging things that are **no longer violations at all** because the underlying convention changed.
- **When you cannot tell, do not record.** A false positive you do not understand is not yet a stale-verdict. Leave it unrecorded; if it is real staleness it recurs next round.
- **Blocking rules matter most.** A stale *blocking* rule halts every commit that touches the scoped code (the expensive cost); a stale *advisory* rule is low-stakes. Capture both, but retirement value concentrates on blocking rules (Step 9b).

This capture also applies to the LSP/lint pre-scan (Step 2b-2) and the Semgrep pre-scan (Step 2b-3) — any mechanical stage whose hit you judge systemically moot.

<!-- Canonical process: WORKFLOW.md §2.5 (Review — Code Quality) -->
<!-- Check definitions: .claude/checks.yml — see WORKFLOW.md §6.5 -->

## Step 2b-2: LSP / Typechecker / Lint Pre-Scan

Runs as part of the same `run_checks.sh` invocation from Step 2b — no separate command. The LSP and lint stages execute after the grep loop inside `run_checks_impl.py` and emit findings in the same `(check_id, file_line, msg)` shape, so baseline matching, `--mode` filtering, and `--fail-on-blocking` all apply uniformly.

This stage catches categories that grep cannot express: unresolved imports, undefined names, unused bindings (Python via `pyright`), TypeScript type errors (via `tsc --noEmit`), and JavaScript/TypeScript convention violations (via `eslint --format json .`). Binaries resolve through the PATH bootstrap in `run_checks.sh` — the main repo's `.venv/bin` (for `pyright`) and `<frontend>/node_modules/.bin` (for `tsc` and `eslint`) are prepended so worktrees and the main checkout both find them. If a binary or `<frontend>/node_modules` is missing, the relevant half silently skips with a warning on stderr; the pre-scan continues.

**ESLint specifics.** Output is a single catch-all `check_id = "lint-error"` registered in `.claude/checks.yml`. The ESLint rule_id (e.g., `react-hooks/exhaustive-deps`) is embedded in the message text — read it to triage severity (severity 2 → HIGH, severity 1 → MEDIUM in the finding line). The catch-all approach avoids enumerating dozens of rule-specific check IDs while preserving full information. When organising lint findings into batches in Step 4, group by file-area batch per the existing Step 4 batch grouping table; the ESLint rule_id in each message lets you spot-check whether sibling findings share a root cause. The `lint-error` check is registered with `used_by: [codebase-review, security-audit]` because frontend `jsx-a11y/*` rules map to OWASP A07/A05 and benefit both review skills.

Tag LSP and lint findings with `[lsp]` source in your notes (distinct from `[grep]`) for coverage tracking. Check IDs are prefixed `pyright-*`, `tsc-*`, or `lint-*`.

**Triage note:** `pyright-general-warning` and `lint-error` are catch-alls and may include false positives — treat them the same way as grep checks with `notes: "Needs LLM triage"`: read each match, record only confirmed findings.

<!-- Check definitions: .claude/checks.yml (pyright-* / tsc-* / lint-* entries, populated by run_lsp_diagnostics / _run_eslint) -->

## Step 2b-3: Semgrep AST Pre-Scan

Runs as part of the same `run_checks.sh` invocation — no separate command. The Semgrep stage executes after the LSP stage inside `run_checks_impl.py` and emits findings in the same `(check_id, file_line, msg)` shape, so baseline matching, `--mode` filtering, and `--fail-on-blocking` all apply uniformly.

This stage catches patterns that regex cannot express with precision: function-scope guards, JSX-context-only renders, template literal interpolation, and f-string argument detection. It requires `semgrep` (Homebrew: `brew install semgrep`). If the binary is missing, the entire stage silently skips with a one-line warning on stderr; the pre-scan continues. If `.claude/semgrep/` is absent, the stage also skips cleanly.

Tag Semgrep findings with `[semgrep]` source in your notes (distinct from `[grep]` and `[lsp]`) for coverage tracking. Check IDs are prefixed `semgrep-*`.

**Triage note:** These rules have been validated against fixtures and the codebase, but are still in their first review cycle. Treat each finding as a strong suggestion — read the surrounding code before recording. The goal of keeping both the regex and Semgrep versions running is to compare precision over this Round; lower `[semgrep]` hit count vs. `[grep]` for the same convention is expected and correct (AST scope filters false positives).

<!-- Check definitions: .claude/checks.yml (semgrep-* entries, populated by _run_semgrep) -->
<!-- Rules and fixtures: .claude/semgrep/ — see .claude/semgrep/README.md for authoring conventions -->

## Step 3: Review Files with Scoped Conventions

### 3-pre. Convention Scoping (CRITICAL)

**Why:** The full Prevention Conventions list in `CLAUDE.md` has 52+ bullets. Giving all 52 to an agent reviewing 30-50 files produces an 88% noise ratio per file — the agent's attention is diluted across rules that cannot apply. Convention scoping gives each agent ONLY the 5-8 rules relevant to its files, dramatically increasing per-rule attention and catch rate.

**How:** `.claude/convention_map.md` maps file patterns to their applicable conventions. Each review agent receives:
1. The **scoped convention bullets** from the matching convention_map section(s) — these are the SPECIFIC rules to enforce
2. The **general quality checks** (3a–3g below) — these are UNIVERSAL checks that apply to all code

**Agent grouping must follow the convention_map sections.**

**High-value file rule:** Files that are large (>300 lines), have many applicable conventions, or concentrate security-critical logic must get their own dedicated agent — never bundle them with 10+ other files where they'd compete for attention. Mark high-value files in `<project>/CLAUDE.md` under § "High-value files for review" so this skill picks them up — typically: large modules concentrating security-critical logic (auth, payments, rate limiting, sensitive data filtering, LLM-cost-bounded handlers).

| Agent scope | Convention_map section(s) | Files |
|-------------|--------------------------|-------|
| Backend API | python pack §"API Endpoints" | `<api module>/server.py`, `<api module>/routes/**/*.py`, `<api module>/rate_limiting.py` |
| Backend SQL & Data | postgres pack §"SQL & Data Layer" | `<sql module>/*.py`, `<sql module>/queries/*.py`, `<db config module>` |
| Backend Auth | python pack §"Auth" | `<auth module>/*.py` |
| Backend Payments | python pack §"Payments" | `<payments service module>` *(dedicated if payment-critical)* |
| Backend Utility Modules | python pack §"Backend Utility Modules" | `<utility modules>/*.py` |
| Eval Runner | llm pack §"Eval Runner" | `<evals module>/*.py` |
| Pipeline | python pack §"Data Pipeline" + llm pack §"LLM-using pipeline" | `<data pipeline>/*.py`, `<data pipeline>/api_clients/*.py` |
| Frontend Components | nextjs-react pack §"React Components" | `<components dir>/**/*.tsx` |
| Frontend Hooks | nextjs-react pack §"Custom Hooks" | `<hooks dir>/*.ts` |
| Frontend Pages & API | nextjs-react pack §"Pages & API Routes" + §"Frontend Utilities" | `<app dir>/page.tsx`, `<app dir>/**/page.tsx`, `<app dir>/api/**/*.ts`, `<frontend lib>/*.ts`, `<frontend lib>/*.tsx` |
| Frontend App Shell | nextjs-react pack §"App Shell" | `<app dir>/(auth)/**/*.tsx`, `<app dir>/layout.tsx`, `<app dir>/global-error.tsx` |
| Scripts (Python) | python pack §"CLI Scripts" | `<scripts dir>/*.py`, `<datajobs entrypoint>`, `<data seed dir>/*.py` |
| Scripts (Shell) | core §"Shell Scripts & Git Hooks" | `scripts/*.sh`, `scripts/hooks/*` |
| Database Migrations | postgres pack §"Database Migrations" | `<migrations dir>/*.sql` |
| Tests (Frontend) | nextjs-react pack §"Frontend Tests" | `<frontend>/**/__tests__/*.ts`, `<frontend>/**/__tests__/*.tsx` |
| Tests (Backend) | python pack §"Backend Tests" | `<tests dir>/*.py` |
| Infra & Config | core §"Dockerfile" + §".gitignore" + §".github/workflows" | `Dockerfile`, `.dockerignore`, `.github/workflows/*.yml`, other config files |

When constructing each agent's prompt:
- **DO:** Dispatch all review agents in a single tool-call block so they run concurrently. Agents have disjoint file scopes — serial dispatch costs ~5× more wall time with no quality benefit. Skip rows whose file list is empty for the current scope (e.g., incremental scan with no changed files in that area).
- **DO:** Spawn all review agents with `model: "opus"` — the locality rule (3b-1) and chunked review (3b-2) require sustained multi-step reasoning across sibling functions and large files. Do not omit, per the **reasoning** role (`.claude/served_models.yml`).
- **DO:** Copy the exact convention bullets from the matching convention_map section into the agent's prompt as "Conventions to enforce"
- **DO NOT:** Include the full Prevention Conventions list from CLAUDE.md — that defeats the purpose of scoping
- **DO:** Include the general quality checks (3a–3g) for all agents — these are lightweight universal checks, not convention-specific

If a file group spans multiple convention_map sections (e.g., "Pages & API Routes" + "Frontend Utilities"), include bullets from ALL matching sections — the combined set is still much smaller than 52.

### 3a. General Quality Checks (ALL agents)

These universal checks apply to every file regardless of convention_map section:

**Code Quality & Patterns:**
- Naming conventions: PascalCase components, `use` prefix hooks, snake_case Python
- DRY violations: duplicated logic that should use an existing helper
- Dead code: unused imports, unreachable branches, commented-out blocks
- Convention compliance: `// Deferred:` not `// TODO:`

**Correctness:**
- Logic errors, off-by-one, missing null/undefined checks
- Race conditions in async code (missing AbortController, stale closures)
- Error handling gaps: bare `except Exception`, swallowed errors, missing user feedback
- Incorrect types or unsafe casts

**Test Coverage Gaps:** (judge test-worth per `_shared/test-assessment-rubric.md` — the same rubric `/test-audit` uses, so this in-diff dimension and the standing whole-surface audit share one calibration)
- New or modified code without corresponding test additions — but apply the rubric's **negative discipline**: a load-bearing invariant (guard, error path, boundary, security/data-integrity, parser) wants a test; trivial glue / wiring / config does not (don't manufacture busywork tests)
- Stale test assertions that no longer match implementation — and the **covered-but-hollow** tell: a line a coverage report calls "covered" by a test that asserts nothing meaningful
- Missing edge case coverage (empty arrays, error responses, auth failures)
- *(This dimension is diff-scoped and reactive — the changed files of this round. For a standing, whole-surface sweep of unchanged gaps + existing-test health, run `/test-audit`.)*

**Architectural Drift:**
- Bypassed helpers: raw `ROW_NUMBER()` instead of `_latest_obs_sql()`
- Wrong engine imports: using `admin_engine` or `writer_engine` for reads
- Missing auth middleware on new endpoints
- Missing rate limiting on new endpoints
- Direct DB access outside `tools.py`
- Frontend/backend contract drift: TypeScript interfaces not matching backend response shapes

**Performance:**
- N+1 query patterns
- Unbounded fetches (missing LIMIT, fetching all rows when only one needed)
- Missing memoization (`useMemo`/`useCallback`) on expensive computations
- Synchronous blocking in async handlers

**Documentation Gaps:**
- Undocumented endpoints or environment variables (compare against `CLAUDE.md` tables)
- Stale documentation that references removed code or changed behavior

**Basic Security Hygiene:**
- Obvious injection vectors (string interpolation in SQL, unsanitized user input)
- Missing input validation on API endpoints
- Hardcoded secrets or credentials
- Note: Defer deep security analysis to `/security-audit`

### 3b. Scoped Convention Checks (per agent)

Each agent enforces ONLY the convention bullets from its matching `convention_map.md` section(s). These are injected into the agent prompt as a focused checklist. Example for the "Custom Hooks" agent:

> **Conventions to enforce (from convention_map.md § Custom Hooks):**
> - AbortController cleanup: Every AbortController ref must be aborted in cleanup; multiple refs → dedicated cleanup useEffect
> - Timer cleanup: setTimeout/setInterval IDs in useRef, cleared on unmount
> - Stale closures: Use functional setState(prev => ...), useRef synced via useEffect, or useCallback with complete deps
> - Rules of Hooks: Never place early returns above hook calls
> - Fetch calls: Use useAbortableFetch() pattern; suppress AbortError with isAbortError()
> - Error display: Never render err.message — use getDisplayError()

The agent checks EVERY file against EACH of these 6 bullets systematically. With 6 rules instead of 52, the agent can give each rule genuine attention per file.

### 3b-1. Locality Rule (Radial Expansion)

**Why:** LLM agents tend to find one instance of a pattern and move on. But violations cluster — nearby code was written in the same session with the same blind spots, and sibling CRUD functions share the same omissions. Round 44 analysis showed 42% of findings were agent misses; most were partial-pattern blindness (e.g., `html.escape()` applied to 4 of 6 fields, audit logs on create/delete but not update).

**Rule:** When an agent identifies a finding, it must **expand the search radius concentrically** before moving to the next file or convention bullet:

1. **Same call / same line group (~5 lines):** Check adjacent parameters, fields, or arguments for the same omission. If one field in a function call is missing `html.escape()`, check every other field in that call.
2. **Same function (~50 lines):** Check other code paths in the same function. If a `try` block catches `SpecificError` but not `Exception`, trace what other exceptions the body can raise. If a success path has an audit log, check the error and early-return paths.
3. **Sibling functions (same module):** If you find a missing audit log on `update_X`, check `create_X`, `delete_X`, and `list_X` in the same file. CRUD operations are written together and share omissions.
4. **Enclosing scope:** Check whether the *enclosing* block (a `with conn:`, a `try:`, a `useCallback`) changes the semantics of the local pattern. A `try/except: continue` inside a single database connection doesn't provide batch resilience because PostgreSQL aborts the whole transaction.

**Do NOT:** Expand to the whole codebase at this stage — that's what Step 3c (Post-Scan Amplification) does. The locality rule is about exhausting the *neighborhood* before moving on.

### 3b-2. Chunked Review for Large Files

**Why:** Agent attention decays over long files. Conventions stated at the top of the prompt fade from active context by line 800. Round 44 analysis showed agent misses concentrated in the bottom half of large files.

**Rule:** For files >300 lines, agents must review in chunks of ~200 lines. After each chunk, mentally re-state the scoped conventions before continuing. This prevents the "first 3 functions get thorough checking, last 3 get a skim" pattern.

For files >600 lines, review the **last third first**, then the middle, then the top. This counteracts top-of-file attention bias.

**Severity assignment:**
- 🔴 **High** — data integrity risk, security vulnerability, production crash potential
- 🟡 **Medium** — meaningful quality gap, correctness concern, convention violation with consequences
- 🟢 **Low** — minor cleanup, style nit, documentation gap

## Step 3c: Post-Scan (Amplification)

After all LLM agents complete, amplify each novel finding across the codebase. LLM agents are good at contextual analysis but unreliable at exhaustive enumeration — they tend to find one instance per pattern and move on. **Route each finding by anchor type:**

| Anchor type | Method | Example |
|-------------|--------|---------|
| **Symbol** (function, class, module-level constant) | Use `LSP.findReferences` via Claude Code's built-in `LSP` tool — resolves imports, aliases, and renames that grep misses, and won't over-fire on string matches in comments/tests | Missing audit log on `update_embed_chart` → find all references to `update_embed_chart` and check each caller's error path |
| **Pattern** (regex-expressible anti-pattern) | Construct a grep query, respecting the skip list below | `useCallback` with incomplete deps, missing `encodeURIComponent()`, `html.escape()` on some-but-not-all prompt interpolations |
| **Not mechanically searchable** (requires AST, multi-file context, semantic understanding) | Skip amplification — rely on the LLM's local finding | Single-transaction batch insert needing `begin_nested()`, transaction-scope reasoning |

**When a finding is symbol-rooted, default to LSP** even if grep would "work" — grep over-fires on string matches in comments/tests and under-fires on imports/aliases. Only fall back to grep when the LSP tool is unavailable or the symbol is ambiguous (e.g., an overloaded common name like `get`).

For each finding:
1. Identify the anchor — is it a named symbol, a regex-expressible pattern, or neither?
2. Dispatch per the table above.
3. Compare results against already-tracked findings (both from this review and open tasks).
4. Any new matches are "post-scan siblings" — add them to the appropriate batch with a note: `*(Post-scan sibling of TASK-NNNN.)*`

**Skip patterns already in `.claude/checks.yml`** — the pre-scan in Steps 2b and 2b-2 already runs those checks deterministically across the entire codebase; amplifying them duplicates pre-scan results. Before constructing a grep, check the `checks.yml` registry; if a check already covers the pattern (e.g., `missing-mock-cleanup`, `wrong-engine`, `error-display-jsx`, `logger-fstring`, `missing-encode-uri`, `missing-writer-engine-guard`, `exception-logging`, `todo-vs-deferred`, `raw-row-number`, `sql-fstring`, `to-be-defined-dom`, `app-env-default-prod`, `window-open-noopener`, `pyright-*`, `tsc-type-error`, `lint-error`), skip amplification and rely on pre-scan. Focus Step 3c on patterns that aren't expressible as simple regex — asymmetric CRUD logging, partial escaping in multi-field prompts, semantic invariants, multi-line constructs.

**Example amplifications** *(chosen to illustrate patterns that pre-scan cannot express as a simple regex):*

| LLM found | Post-scan grep | Siblings caught |
|-----------|---------------|-----------------|
| `create_<resource>` has `logger.info` success log; `update_<resource>` does not (asymmetric CRUD audit trail) | `grep -rn "^\s*def \(create\|update\|delete\)_" <api module>/routes/ <api module>/tools/` + manually verify each sibling's success path logs at INFO | Sibling mutations in 1–2 other route modules |
| `html.escape()` applied to 4 of 6 interpolated fields in an LLM XML boundary template in `<prompt-builder file>` | Re-read the same file's prompt-builder functions and verify every `{var}` inside a `<tag>...</tag>` boundary is escaped (whole-file check, not cross-file) | Remaining fields in the same or adjacent template |
| Single-transaction batch insert loop in `<analytics file>` crashes the whole batch on one bad row (needs `begin_nested()` SAVEPOINT) | Not mechanically searchable — requires tracing transaction scope across the loop body; skip and rely on the LLM's local finding | — |

Report post-scan results:
```
Post-scan amplification: <N> patterns grepped → <N> new siblings found
```

## Step 4: Deduplicate and Organize

**Deduplication:** For each finding (from pre-scan, LLM agents, and post-scan siblings), check `open_task_index` for a task at the same file within **±5 lines** of the finding's line number. Exact `file:line` match is too strict — intervening unrelated edits shift line numbers without resolving the underlying task, so an exact check re-opens resolved work as "new" findings. If a fuzzy match exists AND the finding's description points at the same underlying issue (same convention, same helper/utility, same anti-pattern keyword), skip the finding. When in doubt, skip — the reviewer can pull the task from the existing batch rather than tracking two near-duplicate tasks. Track skipped count for the summary.

**Batch grouping by file locality:**

| Batch name | Files |
|------------|-------|
| Backend Core | `<api module>/server.py`, `<sql module>/*.py`, `<db config module>`, `<utility modules>/utils.py` |
| Backend Auth & Payments | `<auth module>/*.py`, `<payments service module>` |
| Pipeline Ingestion | `<data pipeline>/` |
| Pipeline Scripts | `<scripts dir>/`, `<prompts dir>/` |
| Frontend Components | `<components dir>/` |
| Frontend Hooks | `<hooks dir>/` |
| Frontend Pages | `<app dir>/*/page.tsx`, `<app dir>/layout.tsx` |
| Frontend Lib | `<frontend lib>/` |
| Migrations & Infra | `<migrations dir>/`, `Dockerfile`, `.github/`, config files |
| Tests | `<tests dir>/`, `<frontend>/**/__tests__/` |

- Only create batches that have ≥1 task
- Number batches sequentially from `next_batch_number`
- Files that don't fit a category go in the closest match or a new "Miscellaneous" batch

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

Check if a Round with today's date already exists (e.g., from a `/security-audit` run earlier today):
- **If yes:** append new batches inside that Round (after the last batch, before the next `---` separator or `## Statistics`). If the existing Round header's suffix only mentions the other audit type (e.g., `— OWASP Security Audit`), update it to `— Code Quality Review + OWASP Security Audit` to reflect the mixed content. Do not renumber the Round.
- **If no:** create a new Round section:

```markdown
## Round N (YYYY-MM-DD) — Code Quality Review

```

Use the next Round number (last Round N + 1).

### 5c. Batch Format

For each batch:

```markdown
### Batch N — <Batch Name> `Pending`

> **Scope:** <comma-separated file paths or globs>
> **Branch:** `fix/batch-N-<kebab-name>`
> **Verify:** `<test or build command for this scope>`
> **Overlap:** <none | batch-M, batch-P>

- [ ] **TASK-N**: <Imperative title> <severity emoji>
  `<file:line>` — <1-2 sentence description with concrete suggested fix>

- [ ] **TASK-N+1**: <Imperative title> <severity emoji>
  `<file:line>` — <Description with suggested fix>
```

### 5d. Statistics Update

If a `## Statistics` section exists, append rows for the new batches. Otherwise, create the Statistics section after the last Round.

### 5e. Convention fire ledger (stale-rule capture)

If Step 2b/2b-2/2b-3 triage recorded any **stale-verdicts** (mechanical checks that fired on non-violations because their convention no longer applies), append them to the `## Convention fire ledger` section of `review_tasks.md`. This section is the durable, round-attributed record the demotion gate (Step 9b) recomputes from — the demotion counterpart to the archived-round record the promotion gate reads.

**Placement is load-bearing:** the ledger is a single standalone section at the **end** of `review_tasks.md`, *outside* every `## Round` block, so `archive_review_tasks.py` (which only relocates `## Round N` batch blocks) never moves or drops it. Create it lazily on the first stale-verdict; never put it inside a Round.

```markdown
## Convention fire ledger

> Per-rule stale-verdicts from review-round triage (Step 2b). The demotion gate (Step 9b)
> retires a rule once it accrues stale-verdicts across **2+ distinct rounds**. A rule's rows
> are cleared when Step 9b adjudicates it (retire / demote-to-advisory / tighten / keep).

| Round | Rule ID | Mechanism | Verdict | Why (the change event) |
|-------|---------|-----------|---------|------------------------|
| <N> | `<rule-id>` | checks.yml / semgrep / pre-commit | stale | <one line: which convention moved out from under it> |
```

One row per (rule, round): a rule fires many times in a round but earns at most **one** stale-verdict row per round — this mirrors promotion's "recurred across rounds," not "fired N times this round." Do not add a second row for a rule that already has one for this Round. (When both `/codebase-review` and `/security-audit` run in the same Round, share the one ledger section — append, do not duplicate.)

## Step 6: Report Summary

Print a summary table:

```
Code Quality Review — Round N (YYYY-MM-DD)
Scan: Full / Incremental (since YYYY-MM-DD)
Scope: <area or "all">
Files scanned: <N>

Convention map audit:    <N> file gaps, <M> unmapped bullets (fixed inline: yes/no)
Security map audit:     <P> file gaps (fixed inline: yes/no)
Pre-scan (grep):        <N> findings (deterministic)
LLM agents:             <N> findings (contextual)
Post-scan amplification: <N> patterns grepped → <N> new siblings found

| Batch | Tasks | 🔴 | 🟡 | 🟢 |
|-------|-------|-----|-----|-----|
| <name> | <n> | <n> | <n> | <n> |
| ...   |       |     |     |     |
| **Total** | **N** | **N** | **N** | **N** |

Duplicates skipped: <N> (already tracked as open tasks)
Task IDs: TASK-<first> through TASK-<last>
```

## Step 7: Commit Generated Tasks

After writing to `review_tasks.md`, **always commit the changes** so they survive branch merges and stash operations during `/review-close`:

```bash
git add review_tasks.md review_tasks_archive.md 2>/dev/null
git commit -m "docs: add Round <N> tasks to review_tasks.md"
```

This prevents task loss when `/review-close` later stashes uncommitted changes for branch merges.

## Step 8: Convention Candidate Extraction

After writing all tasks, scan the findings for patterns that could become new Prevention Convention entries:

1. Review all tasks written in this Round and look for **recurring patterns** — findings that appear 3+ times across different files or that represent a systemic gap not covered by the existing convention bullets in `CLAUDE.md`
2. For each recurring pattern, draft a candidate Prevention Convention bullet following the existing format:
   - Lead with the rule (imperative: "All X must Y")
   - Reference the specific utility or helper if one exists or should be created
   - Match the style of the existing bullets in `CLAUDE.md` § Prevention Conventions
3. For each candidate, also draft a one-line convention map entry and list the `.claude/convention_map.md` sections it should be added to
4. Write candidates to `.pending-docs/convention-candidates.md`. If the file already exists (e.g., from a `/security-audit` run earlier in the same Round), **append** a new `## Source: /codebase-review` section below the existing content rather than overwriting. Keep the top-level `# Convention Candidates — Round N (YYYY-MM-DD)` heading unchanged when appending. Use this format:

```markdown
# Convention Candidates — Round N (YYYY-MM-DD)

## Source: /codebase-review

| # | Candidate Rule | Category | Occurrences | Example Tasks | Map Sections |
|---|----------------|----------|-------------|---------------|--------------|
| 1 | <draft rule text> | Frontend/Backend/Testing | <N> findings | TASK-X, TASK-Y | `<data pipeline>/*.py`, `<scripts dir>/*.py` |
| 2 | ... | ... | ... | ... | ... |
```

5. If no patterns recur 3+ times, skip this step and note "No convention candidates — all findings were one-off" in the summary

## Step 9: Convention Promotion (Interactive)

If Step 8 produced convention candidates in `.pending-docs/convention-candidates.md`, promote them now rather than deferring to `/review-close`.

> **Where these writes land — read `_shared/promotion-write-target.md` first.** In a **consumer install** (detected by `.claude/sysop.lock`), the base maps `.claude/convention_map.md` / `.claude/checks.yml` are regenerated from upstream on every `sysop-update.sh`, so a promotion written only to a base file is silently lost on the consumer's next update. Dual-write to the `.project.*` overlay per that partial (the mechanism-by-mechanism table). In the **source repo** (no lock — Sysop's own tree, or a project authoring maps in place) the overlay does not exist; write the base files exactly as below.

1. **Apply the cross-round survival gate, then present.** A candidate is promotable only if its pattern has **recurred across two review rounds** — present in *this* Round's findings **and** in an earlier Round's archived `review_tasks.md`. A 3+ burst confined to this Round is not promotable on its own (it filters out one-off noisy rounds). Recurrence is *computed* from the durable record each round — round-attributed `.claude/convention_map.md` entries + archived `review_tasks.md` Rounds — not maintained as a carried-forward watch-list.
   - For each candidate, check the prior-Round archive for an earlier occurrence of the same pattern.
   - **Cleared the gate (recurred):** present to the user — draft rule text, category, occurrence count, the earlier Round it first surfaced in, and example tasks. Ask: **promote** or **skip**.
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
         1. Draft the check following the existing B-tier (blocking) or A-tier (advisory) pattern in `scripts/hooks/pre-commit`. Append the next unused letter; read the header comment listing for the current range rather than assuming `B1–B5` / `A1–A11`.
         2. Present to the reviewer: `[yes-blocking / yes-advisory / skip]`.
         3. On approval: append to `scripts/hooks/pre-commit`, update the header comment listing.
         4. On skip: log the reason in the promotion report.

      - **(iv) Prose fallback in CLAUDE.md** — only when the rule requires semantic reasoning, multi-call context, or judgment that none of (i)–(iii) capture. **Canonical fallback list:** audit-trail symmetry, tier enforcement, response filtering, rate-limit coverage, error caching. If the candidate doesn't match one of these patterns, the reviewer must justify in writing why (i)–(iii) all fail before defaulting to (iv).

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

This is the **FP-driven** half of convention demotion. Tier 1 (Step 2a-4) statically detects *map* staleness (sections/citations that lost their code); Step 9b retires the **blocking-mechanical rules** whose false-positive cost the map sweep cannot see — the rules that keep halting commits on things that are no longer violations.

1. **Recompute retirement candidates from the ledger.** Read the `## Convention fire ledger` section of `review_tasks.md` (Step 5e). Group rows by `Rule ID` and count the **distinct Rounds** each rule has a stale-verdict in.
   - **Cleared the cross-round gate (stale-verdicts in 2+ distinct Rounds):** retirement candidate. This is the exact mirror of promotion's cross-round survival gate — a single-round burst of stale-verdicts is held, filtering one-off noisy rounds, just as a single-round burst of true positives is not promotable on its own.
   - **First seen this Round (1 distinct Round):** do not prompt. The ledger row is itself the durable record that lets a future Round detect the recurrence. Note "held for cross-round recurrence — first stale-verdict Round N" in the summary.

   **Also ingest the static removed-category candidates (from Step 2a-4 — no ledger row).** The map staleness sweep routes any *removed-category* candidate here: a promoted **prose** convention whose `.claude/convention_map.md` section now matches zero tracked files. A pure-prose convention fires no mechanical check, so it never earns a ledger row — without this path it would be re-detected every round but have nowhere to be retired (the loop would stay open for exactly this case). These candidates arrive via deterministic static detection, so they **bypass the 2+-round gate** — a section whose glob matches zero tracked files is already unambiguous; there is no false-positive accrual to wait out. For each, present the stale section + the `CLAUDE.md § Prevention Conventions` bullet it promoted, and ask **`[retire / keep]`**. On **retire**, remove the prose bullet and its now-stale `convention_map` section; on **keep**, log why (e.g., aspirational — the code is coming back). Count a retired prose convention in the demotion summary's advisory-or-prose tally.

2. **For each ledger-derived retirement candidate, present and decide.** Show: rule id, mechanism (`checks.yml` / `semgrep` / `pre-commit`), current `blocking:` status, the Rounds it was judged stale in, and the recorded "why." Then ask: **`[retire / demote-to-advisory / tighten / keep]`**.

   - **retire** — the rule is genuinely moot. Remove it at its mechanism, then strip its mechanized-equivalent reminder from every `.claude/convention_map.md` section that cites it:
      - `checks.yml`: delete the `- id: <rule-id>` entry from `.claude/checks.yml`; remove the matching `> checks.yml: <rule-id>` reminder lines.
      - `semgrep`: delete `.claude/semgrep/<rule>.yaml` **and** its `.claude/semgrep/fixtures/` file; remove the matching `> AST-backed equivalent: <rule-id>` reminder lines.
      - `pre-commit`: delete the `scripts/hooks/pre-commit` check, update the header-comment letter listing; remove the matching `> pre-commit: <letter>` reminder lines.
      - If the rule had also become a **prose** convention bullet (rare), remove that `CLAUDE.md § Prevention Conventions` bullet — this is the deliberate, human prose-retirement that Tier 1 (Step 2a-5) routes here.
      - Optional hygiene: drop any now-orphaned `<rule-id>` lines from `.claude/checks_baseline.txt` (inert once the check id is gone, but tidy).
      - **Consumer install** (per `_shared/promotion-write-target.md`): retire the rule where it durably lives — a **locally-promoted** rule is in the `.project.*` overlay, so delete it from `.claude/checks.project.yml` / `.claude/convention_map.project.md` (editing only the base leaves the overlay to re-supply it on the next update); a **core/pack-shipped** rule can't be deleted from a consumer install (the concat re-supplies it), so suppress a `checks.yml`-mechanism one via an override entry in `.claude/checks.project.yml` (`paths: ["__disabled_no_op__"]`) — a core semgrep/pre-commit rule has no consumer-side suppression and routes genuine retirement upstream (see the partial).
   - **demote-to-advisory** — the rule still catches a real issue sometimes, but the false-positive halt is not worth it. Flip `blocking: true → false` in `.claude/checks.yml` (or move a `pre-commit` letter from the B-tier blocking range to the A-tier advisory range). The signal survives; the commit-halt does not. The lower-regret middle option when "retire" feels premature.
   - **tighten** — the rule is **over-broad from birth** (staleness Mode G), not genuinely moot: it has flagged non-violations since it shipped because its `pattern`/`paths` are too wide. Narrow the regex or glob instead of retiring. Not a retirement; the rule stays, scoped better.
   - **keep** — override the signal: the rule is still valuable despite the false positives (the cost of a missed true positive outweighs the triage cost). Log the reason in the demotion report.

   **Security caveat (security-relevant rules):** before retiring a rule that enforces a security property (a sanitizer, an auth guard, an injection/escape check), confirm the protection it encodes is **genuinely gone or moved elsewhere** — a stale-looking security check is often a *version-fix* (Mode E: a dependency bump mooted the local check) where the defense should still exist. When unsure, prefer **demote-to-advisory** or **tighten** over **retire**, mirroring the refresh-vs-retirement discipline in Step 2a-4 (and the higher-stakes security-helper caveat in `/security-audit`'s parallel sweep).

3. **Clear the adjudicated rule's ledger rows.** For **every** disposition (retire / demote-to-advisory / tighten / keep), delete that rule's rows from the `## Convention fire ledger`. The verdict has been acted on, so the counter resets — this bounds the ledger **and** prevents a "keep" decision from re-prompting every subsequent round. The rule only re-surfaces if fresh staleness recurs across 2+ new Rounds.

4. **Emit demotion summary** — print one line `Demotion summary: <N> retired (<B> blocking / <A> advisory-or-prose)` and include the same line in the commit body. Future reviewers grep the loop with `git log --grep "Demotion summary"` (mirrors the `Promotion summary:` trailer). The `retired` tally counts retirements only — mirroring `Promotion summary:`, which counts only promotions; **demote-to-advisory / tighten / keep** dispositions are noted in the demotion report but not in the tally (a demote-to-advisory still commits a `blocking:` flip). If nothing was retired *and* no rule was demoted/tightened, print `Demotion summary: 0 retired` and skip the commit.

5. **Commit** any changes (fold into the Step 9 promotion commit if that ran this round, otherwise a standalone commit; the `.project.*` overlay paths cover consumer-install retirement per `_shared/promotion-write-target.md`):
   ```bash
   git add CLAUDE.md .claude/convention_map.md .claude/convention_map.project.md .claude/checks.yml .claude/checks.project.yml .claude/checks_baseline.txt .claude/semgrep/ scripts/hooks/pre-commit review_tasks.md 2>/dev/null
   git commit -m "docs: retire <N> conventions from Round <N>

   Demotion summary: <N> retired (<B> blocking / <A> advisory-or-prose)"
   ```

This closes the demotion half of the loop: a rule that keeps firing on non-violations is caught at triage → recorded round-attributed in the ledger → retired once the staleness survives across rounds → the gate stops halting commits on a convention the codebase has outgrown. Symmetric to the promotion loop above. The one principled asymmetry: promotion *recomputes* recurrence from durable findings (a true positive becomes a task), while demotion must *maintain* the ledger (a stale positive becomes nothing, so its verdict would otherwise be thrown away) — see WORKFLOW.md §3.5.

<!-- Canonical process: WORKFLOW.md §3.5b (Convention demotion lifecycle) -->

End with: "Run `/security-audit` for a deep OWASP-aligned security pass, or claim a batch and start fixing."
