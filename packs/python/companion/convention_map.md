# Convention Map — Python pack

> Maps file patterns to relevant Python conventions from `CLAUDE.md` § Prevention Conventions.
> Use during planning (before writing code) and review (before committing).
> Full rules live in `CLAUDE.md` — these are actionable reminders.

> **Provenance:** these rules were promoted from recurring review findings on a hosted, multi-user subscription web app (FastAPI + Postgres, LLM-backed, third-party auth and payments). The API-boundary, logging, and input-validation rules travel widely; the tier-enforcement and payments-adjacent bullets assume a tiered SaaS and are safe to ignore if yours isn't one.

> **Helper names** (e.g., `_sanitize_log()`, `redact_api_keys()`, `_escape_like()`, `validate_identifier()`) are placeholders for whatever your project names these helpers — the convention is to *have* them.
>
> **Glob patterns** like `<api module>/server.py` name your real paths only once you localize them. Do not edit them into the assembled `.claude/convention_map.md` — that file is regenerated on every update. Localized sections belong in the never-managed `.claude/convention_map.project.md` overlay, which is also where `/codebase-review` writes them when its coverage sweep proposes them. (Full explanation: `docs/packs.md` in the Sysop repo.)
>
> **Directory placeholders** referenced in this pack and in `checks.yml.fragment`: `<api module>` (web framework module, e.g., FastAPI app dir), `<auth module>` (auth/user-session code), `<utility modules>` (shared backend utilities), `<payments service module>` (payment-provider integration), `<numeric library module>` (resource-bounded compute helpers — security-only concern, no convention bullets in this pack; declared here so cross-references from `security_map.md` resolve), `<data pipeline>` (ingestion/ETL code), `<scripts dir>` (one-shot CLI scripts), `<datajobs dir>` (long-running batch jobs / scheduled jobs), `<datajobs entrypoint>` (the entry-point file inside `<datajobs dir>`), `<data seed dir>` (initial-data seed scripts), `<tests dir>` (test files).
>
> **Helper placeholders** referenced inline: `<alerting escape helper>` (project-defined helper that escapes / sanitizes dynamic values destined for an alerting channel — Slack, PagerDuty, Discord, or a custom webhook), `<api key redactor>` (project-defined helper that strips credentials from text before egress).
>
> **Instance placeholders** (Python attribute access on a runtime singleton, distinct from path placeholders): `<db config instance>` is the imported instance whose `.reader_engine` / `.writer_engine` / `.admin_engine` attributes are accessed at runtime; `<engine>` is one of those three attribute names. The path placeholder for the file housing this instance is `<db config module>` and lives in the postgres pack.

---

## `<api module>/server.py`, `<api module>/routes/**/*.py`, `<api module>/rate_limiting.py` — API Endpoints

- **Tier enforcement**: Tier-gated mutations need a tier-checking dependency (e.g., `Depends(require_<tier>_access)`), not just a verified-user dependency
- **Rate limiting coverage**: New endpoints must be added to the public-path allowlist or call the user-rate-limit checker
- **Rate-limit violation logging**: All rate-limit 429 responses must log at WARNING with sanitized identifiers (IP or UID) and path
- **Security-relevant rejection logging**: All 4xx security rejections (HTTP 400 prompt-boundary content, 403 ownership/tier, 422 security-validation, 429 rate-limit) must log at WARNING with sanitized identifier + path BEFORE raising
- **No `exc_info=True` on logger calls**: Forbidden alongside `logger.exception()` — both bypass log sanitization. If a stack trace is needed, format manually with `traceback.format_exception` + redact + truncate, log at DEBUG
- **Input validation**: All parameters need `Field(max_length=...)` / `Query(ge=..., le=...)`; use validated input types (e.g., `SafeId`, `BoundedLimit`, `BoundedOffset` patterns)
- **Response filtering**: Strip internal fields (e.g., `owner_id`, `client_ip`, auth-provider UID, payment-provider customer ID) **at the route layer**; do NOT remove from data-access functions — routes need them for ownership checks
- **Error responses**: Never return `str(e)` or exception details — use generic messages
- **Error caching**: Never cache error responses with long TTLs; transient errors → 500 or `Cache-Control: no-store`
- **Audit trail for state mutations**: Log security-relevant state mutations (tier changes, credit grants, content CRUD) at INFO on success — symmetric for all operations
- **Staging = production**: Security guards must use `APP_ENV in ("prod", "staging")`, not just `"prod"`
- **Env var validation**: Security-critical env vars validated at startup; prod/staging → fatal error; dev/test → warning
- **Module-scope regex compilation**: `re.compile()` at module scope as constants, not inside request handlers
- **Logger formatting**: Use `logger.info("msg %s", val)` not `logger.info(f"msg {val}")` — f-strings bypass lazy formatting
- **APP_ENV default consistency**: `os.getenv("APP_ENV", ...)` must default to `"dev"`, not `"prod"` — except in env-validation entry points where fail-closed is intentional

## `<auth module>/*.py` — Auth

- **Auth failure logging**: Optional-auth endpoints must log failures at WARNING + call a failure-tracking function
- **No `exc_info=True` on logger calls**: Forbidden alongside `logger.exception()` — both bypass log sanitization
- **Input size validation before SDK calls**: Reject malformed payloads (e.g., tokens >10 KB) before passing to auth SDKs (Firebase, Auth0, etc.)
- **Staging = production**: Security guards must use `APP_ENV in ("prod", "staging")`, not just `"prod"`
- **Singleton init flag ordering**: Set `_initialized = True` AFTER successful resource creation inside `try`, not before — prevents permanent failure on transient errors
- **Secrets in logs**: Redact credentials from exception messages before logging external service errors
- **Audit trail**: Log state mutations (tier changes, credit grants, content creation, content updates, content deletions) at INFO on success — symmetric for all CRUD operations
- **Logger formatting**: Use `logger.info("msg %s", val)` not f-strings
- **APP_ENV default consistency**: Default to `"dev"`, not `"prod"`

## `<utility modules>/*.py` — Backend Utility Modules

- **Intentional exceptions vs. broad except**: Catch `ValueError`/`TypeError` specifically before `except Exception` when they are API contracts
- **Module-scope regex compilation**: `re.compile()` at module scope, not inside request handlers
- **Logging**: Exceptions → `<log sanitizer>(str(e)[:500])`, never the raw exception. Never `logger.exception()` or `logger.*(..., exc_info=True)` — both bypass redaction
- **Logger formatting**: Use `logger.info("msg %s", val)` not f-strings
- **APP_ENV default consistency**: Default to `"dev"`, not `"prod"`

> Postgres pack overlays SQL safety, engine selection, engine null guards, batch loop resilience (with SAVEPOINTs), and error-message truncation onto utility modules that touch SQL — see `packs/postgres/companion/convention_map.md` § `<sql module>` for those bullets when both packs are installed.

## `<payments service module>` — Payments

- **Audit trail**: Log tier upgrades, subscription changes, credit grants, content creation/updates/deletions at INFO on success — symmetric for all CRUD operations. For balance/credit mutations, capture and log the **prior** balance alongside the new value (the audit trail must answer "did the user actually have N credits before this charge?", not just "what is the balance now?")
- **Input validation**: `Field(max_length=...)` on all Pydantic models; validate input size before payments SDK calls
- **Error responses**: Generic error messages only — never `str(e)` in API responses
- **Secrets in logs**: Strip credentials from exception messages before logging
- **Input size validation before SDK calls**: Reject oversized payloads early before SDK processing
- **Logger formatting**: Use `%s` not f-strings

## `<data pipeline>/*.py`, `<data pipeline>/api_clients/*.py` — Data Pipeline

- **HTTP client lifecycle**: Create `httpx.Client` once, reuse across calls; close in `finally`/context manager
- **Closable resources inside try/finally**: Create closable resources (clients, pools) inside `try` block — not before it
- **Batch loop resilience**: Wrap per-item logic in try/except — one failure must not crash the batch; SQL batch inserts need SAVEPOINTs
- **Alerting-channel message escaping**: All dynamic values in alerting-channel messages → `<alerting escape helper>` (covers digest/summary builders, not just alert functions). Applies to any alerting channel: Slack, PagerDuty, Discord, custom webhook.
- **Alerting sanitization**: Apply `<api key redactor>()` before sending to the alerting channel; pass pre-truncated `str(e)[:N]`, not the raw exception.
- **Thread-safe singletons**: Guard `global` check-and-create patterns with `threading.Lock()`; `close_*()` functions must acquire the same lock
- **Singleton init flag ordering**: Set `_initialized = True` AFTER successful resource creation inside `try`, not before
- **HTML templates**: When embedding dynamic values into HTML attributes, use `html.escape(value, quote=True)`
- **Secrets in logs**: Redact API keys from exception messages before logging
- **Logging**: Exceptions → `<log sanitizer>(str(e)[:500])`, never the raw exception. Never `logger.exception()` or `logger.*(..., exc_info=True)` — both bypass redaction
- **Outbound HTTP security**: `follow_redirects=False` at client level; enforce `https://` scheme on URL allowlists
- **Env var validation**: Security-critical env vars validated at startup; prod/staging → fatal; dev/test → warning
- **Staging = production**: Security guards must use `APP_ENV in ("prod", "staging")`, not just `"prod"`
- **Singleton failure sentinel**: Set `_failed` flag on permanent init failures (missing SDK, credentials) so they aren't retried every call; document intentional-retry vs permanent-failure choice
- **Logger formatting**: Use `%s` not f-strings
- **APP_ENV default consistency**: Default to `"dev"`, not `"prod"`

## `<scripts dir>/*.py`, `<datajobs entrypoint>` — CLI Scripts and Job Entrypoints

- **Dependency management**: Never edit generated `requirements.txt` directly — use `pip-compile` (e.g., via a `compile-deps.sh` wrapper)
- **shared_cli.py**: Use `create_env_parser`, `confirm_production`, `setup_env` (from `shared_cli.py` in this pack) — never duplicate `--env` parsing
- **Late imports**: Set `APP_ENV` (and any other env vars read at import time) first, then import env-dependent modules — never at module top level
- **Sanitize logging**: All exception messages → `<log sanitizer>(str(e)[:500])` before printing/logging
- **SQL from external sources**: Validate via the project's `validate_sql_safety()` before executing SQL from DB rows/config/API responses
- **Path containment**: `os.path.realpath()` + verify starts with expected base directory
- **Closable resources inside try/finally**: Create closable resources (clients, pools) inside `try` block — not before it
- **Env var validation**: Security-critical env vars validated at startup; prod/staging → fatal; dev/test → warning
- **Logger formatting**: Use `%s` not f-strings
- **YAML safe load**: Always use `yaml.safe_load()` — never `yaml.load()` or `yaml.full_load()`. PyYAML's default loader instantiates arbitrary Python objects from `!!python/object` tags (OWASP A03 deserialization). Codified when YAML became load-bearing for `tasks/index.yml` (Phase 16). Paired check: `yaml-unsafe-load`. (The check is file-level: a file that contains both `yaml.load(x)` and `yaml.safe_load(y)` passes because the negative pattern matches the safe call and exempts the whole file. Split mixed-usage files or drop the unsafe call entirely.)

> AST-backed equivalents: `semgrep-logger-fstring`, `semgrep-recompile-inside-def` (in this pack's `semgrep/` directory)
>
> Postgres pack overlays engine-specific bullets (engine-as-parameter, defensive engine null guards, engine-gating env-var error messages) onto this section when both packs are installed — see `packs/postgres/companion/convention_map.md` § `<scripts dir>` for those.

## `<tests dir>/*.py` — Backend Tests

- **Test isolation**: Each test file needs its own `sys.path` setup — never rely on `conftest.py` side effects. **APP_ENV must be set BEFORE `sys.path.insert` and any project import** — db-config, env-validation, etc. read APP_ENV at import time; wrong order silently inherits harness env
- **`@patch` stacking**: Bottom decorator = first positional arg after `self`; verify parameter name bindings
- **Meaningful assertions**: At least one meaningful assertion; no bare `except: pass` patterns
- **Mock cleanup**: Restore patched objects in teardown; leaked mocks cause false positives in subsequent tests
- **Import from source**: Import functions/constants from production modules — never copy-paste source code into tests
