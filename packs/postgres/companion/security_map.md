# Security Concern Map — Postgres pack

> Maps file patterns to relevant OWASP security checks for Postgres + SQLAlchemy projects.
> Used by `/security-audit` to focus agents on applicable checks per file area.
> Each section lists what TO check and what to SKIP — agents must respect both.

> **Helper names** (e.g., `_escape_like()`, `validate_identifier()`, `validate_sql_safety()`, `_latest_obs_sql()`) are placeholders for whatever your project names these — adapt to your actual helpers.

---

## `<sql module>/*.py`, `<sql module>/queries/*.py`, `<db config module>` — SQL & Data Layer

**Check:**
- **A03 Injection**: SQL injection (f-strings in SQL, parameter binding correctness, LIKE escaping with `_escape_like()` + `ESCAPE '\\'`), SQL from external sources (`validate_sql_safety()` before execution)
- **A01 Access Control**: Engine selection (SELECTs → `reader_engine`, writes → `writer_engine`, migrations → `admin_engine`), sensitive column/table blocking
- **A05 Misconfiguration**: LIMIT clauses on all row-returning queries, statement timeout configuration

**Skip:** A07 (auth — handled by route layer), A10 (SSRF), XSS, LLM, Privacy, Logging (except exception logging patterns)

---

## `<migrations dir>/*.sql` — Database Migrations

**Check: A01** — GRANT/REVOKE correctness. Two distinct rules:

1. **Role privilege envelope:** `app_reader` has SELECT only; `app_writer` has SELECT + INSERT/UPDATE/DELETE but no DDL; admin role used only for DDL.
2. **Sensitive-table exclusion (defense-in-depth for PII):** NO `GRANT` of ANY privilege (SELECT, INSERT, UPDATE, DELETE, ALL) on PII tables (e.g., `users`, `subscriptions`, `payments`, anything containing user PII or payment data) to non-admin roles — regardless of privilege scope. Row-level access to these tables must go through admin engine, a dedicated filtered VIEW (e.g., `v_public_*`), or a stored procedure. This is a defense-in-depth layer separate from any application-layer sensitive-table check (e.g., a `SENSITIVE_TABLES` constant in your validation module). Deterministic grep checks in this pack's `checks.yml` enforce this. If the agent finds a new GRANT on any sensitive table, file it as CRITICAL.

**Skip:** Everything else
