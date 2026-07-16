# Security Concern Map — Python pack

> Maps file patterns to relevant OWASP security checks for Python projects.
> Used by `/security-audit` to focus agents on applicable checks per file area.
> Each section lists what TO check and what to SKIP — agents must respect both.

> **Helper names** (e.g., `_sanitize_log()`, `_filter_user_for_client()`, `validate_sql_safety()`, `redact_api_keys()`) are placeholders for whatever your project names these — adapt to your actual helpers.

---

## `<api module>/routes/**/*.py` — API Endpoints

**Check:**
- **A01 Access Control**: IDOR (ownership verification before resource access), tier enforcement on tier-gated mutations, horizontal privilege escalation (user ID in path params vs. authenticated user)
- **A02 Data Exposure**: Response filtering — internal fields (e.g., `owner_id`, auth-provider UID, payment-provider customer ID, `client_ip`) must not appear in API responses
- **A03 Injection**: SQL from external sources must pass through `validate_sql_safety()`
- **A05 Misconfiguration**: Rate limiting coverage (new endpoints in public-path allowlist or behind user-rate-limit checker), input validation (`Field(max_length=...)`, validated input types like `SafeId` / `BoundedLimit`)
- **A07 Auth**: Auth gate correctness (required vs optional auth on each endpoint), no bypass paths
- **Logging**: Audit trail — state mutations (deletions, tier changes, credit grants) logged at INFO on success; error sanitization (`<log sanitizer>(str(e)[:500])`)

**Skip:** A06 (dependencies), A10 (SSRF — assumes no outbound HTTP to user-supplied URLs in this layer), XSS (server-side)

---

## `<auth module>/*.py` — Auth

**Check:**
- **A07 Auth**: Token verification completeness (all paths verified), token size validation (>10 KB rejected), timing-safe comparisons (`hmac.compare_digest`), staging=production guards (`APP_ENV in ("prod", "staging")`)
- **A01 Access Control**: Optional vs required auth — optional-auth endpoints must log failures; verified-user dependencies must enforce email verification
- **Logging**: Auth failure logging at WARNING with sanitized client IP; failure-tracking function called on every rejection path
- **A02 Data Exposure**: User-data filtering removes sensitive fields before response

**Skip:** A03 (SQL injection), A06 (dependencies), A10 (SSRF), XSS, LLM

---

## `<payments service module>` — Payments

**Check:**
- **A07 Auth**: Webhook signature verification (HMAC), idempotency (duplicate event handling)
- **A02 Data Exposure**: Customer ID not leaked in responses, error messages sanitized
- **Logging**: Audit trail — tier changes, credit grants, subscription cancellations, refunds all logged at INFO on success with before/after state
- **A05 Misconfiguration**: Payments secret key validated at startup for prod/staging

**Skip:** A03 (SQL injection), A10 (SSRF), XSS, LLM

---

## `<api module>/server.py`, `<api module>/rate_limiting.py` — App & Middleware

**Check:**
- **A05 Misconfiguration**: CORS `ALLOWED_ORIGINS` not `*` in prod, env var validation (fail-fast for prod/staging), debug endpoints disabled (`/docs`, `/redoc`, `/openapi.json`), Redis/cache requirement enforcement
- **A01 Access Control**: Rate limiting implementation correctness, brute-force violation tracking and alerting thresholds

**Skip:** A06 (dependencies), A10 (SSRF — internal HTTP clients only)

---

## `<data pipeline>/*.py` — Data Pipeline (excluding API clients)

**Check:**
- **A03 Injection**: Alerting-channel message escaping — `<alerting escape helper>` on ALL dynamic values in the channel's markup/formatting layer (including status, name fields, error messages, numeric fields rendered as text). Applies to any alerting channel: Slack mrkdwn, PagerDuty, Discord, custom webhook.
- **A05 Misconfiguration**: HTTP client lifecycle (create once, reuse, close in `finally`/shutdown); `follow_redirects=False` at client level; env var validation at startup for prod/staging
- **A07 Auth**: Pipeline secret validation at startup, OIDC token configuration
- **A02 Data Exposure**: API key redactor on all error messages before egress to the alerting channel; exception sanitization
- **Resilience**: Batch loop try/except per item — one failure must not crash the batch

**Module-specific notes:**
- Storage clients (e.g., GCS, S3): A03 path injection — validate slug/tag format before constructing object paths. A02 — public buckets must contain only non-sensitive content.
- Renderer / screenshot services: A05 — render URL validated at first use (https:// in prod/staging, isolation per call, per-render timeout enforcement). A10 SSRF — URL scheme enforcement on render URL.

**Skip:** A01 (access control — internal pipeline, auth-gated), XSS (no frontend rendering)

---

## `<data pipeline>/api_clients/*.py` — External API Clients

**Check:**
- **A10 SSRF**: `follow_redirects=False` at client init, `https://` scheme enforcement on base URLs, response size limits (`MAX_RESPONSE_BYTES`)
- **A02 Data Exposure**: API key redaction in error messages
- **A05 Misconfiguration**: Timeout enforcement, API key validation at startup for prod/staging, HTTP client cleanup (`close()`)

**Skip:** A01 (no user access), A03 (no user input in queries), A07 (no auth tokens), XSS, LLM, Logging

---

## `<utility modules>/*.py` — Backend Utility Modules

**Check:**
- **A05 Misconfiguration**: Env var validation correctness (prod/staging fail-fast), safe default handling, HTTP client lifecycle (`follow_redirects=False`, `timeout`), thread-safe singleton initialization
- **A02 Data Exposure**: Error sanitization (`<log sanitizer>(str(e)[:500])`), no internal details in error responses, sensitive column filtering correctness (defense-in-depth layer)

**Skip:** A01 (no direct user access), A03 (no SQL), A07 (no auth), A10 (SSRF), XSS, LLM

---

## `<numeric library module>` — Numeric / Resource-bounded Library

**Check:**
- **A05 Misconfiguration**: Engine null guards before any DB access; enforce `LIMIT` on any observation fetch; validate `len(input) ≤ MAX_*_ROWS` before any pandas/numpy call to prevent CPU/memory exhaustion on unbounded input arrays.
- **A03 Injection**: No f-string SQL; use parameterized queries / centralized SQL helpers only. Validate identifiers with the project's identifier validator.
- **A02 Data Exposure**: Error sanitization — `<log sanitizer>(str(e)[:500])` on all exception logging.

**Skip:** A01, A07, A10, XSS, LLM — pure numeric library, no direct user access, no auth, no network.

---

## `<scripts dir>/*.py`, `<datajobs entrypoint>`, `<data seed dir>/*.py` — CLI Scripts and Job Entrypoints

**Check:**
- **A05 Misconfiguration**: `shared_cli.py` usage (`create_env_parser`, `confirm_production`, `setup_env`), late imports (set `APP_ENV` before importing db-config), engine as parameter (not module-level), no hardcoded database names, script-allowlist enforcement for job dispatchers, format validation on connection strings
- **A03 Injection**: SQL from external sources validated with `validate_sql_safety()` before execution; path containment with `os.path.realpath()`; `JOB_ARGS` / argument validation (length limit, character allowlist before `shlex.split()`); YAML load via `yaml.safe_load()` only (never `yaml.load()` / `yaml.full_load()` — PyYAML's default loader instantiates arbitrary Python objects from `!!python/object` tags). Paired check: `yaml-unsafe-load`.
- **A02 Data Exposure**: Exception sanitization (`<log sanitizer>(str(e)[:500])` — not the raw exception object), no API keys in print output
- **Resilience**: Batch loop try/except per item, HTTP client reuse and cleanup, response size limits on outbound fetches

**Skip:** A07 (auth — CLI tools), A01 (access control — local execution), XSS, LLM

---

## `<tests dir>/*.py` — Backend Tests

**Check:**
- **A02 Data Exposure**: No hardcoded real credentials, API keys, or connection strings in test fixtures. Test tokens should be obviously fake (e.g., `fake-token-xxx`).
- **A05 Misconfiguration**: Test isolation — `APP_ENV=test` must be set before importing db-config. No accidental production database access in tests.

**Skip:** A01, A03, A07, A10, XSS, LLM — tests run locally with mocked services

---

## `pyrightconfig.json` — Python Type Checker Config

**Check:**
- Keep `reportMissingImports` and `reportUndefinedVariable` at `error` (these catch real bugs); do not silently downgrade to `warning` or `none` without a documented reason.

**Skip:** Everything else
