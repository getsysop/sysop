# Convention Map — Postgres pack

> Maps file patterns to relevant Postgres + SQLAlchemy conventions from `CLAUDE.md` § Prevention Conventions.
> Use during planning (before writing code) and review (before committing).
> Full rules live in `CLAUDE.md` — these are actionable reminders.

> **Provenance:** these rules were promoted from recurring review findings on the data layer of a hosted subscription web app — SQLAlchemy with separate reader/writer/admin engines and Alembic migrations. They apply to most SQLAlchemy/Postgres projects; the engine-role bullets assume that explicit engine split.

> **Helper names** (e.g., `_latest_obs_sql()`, `validate_identifier()`, `_escape_like()`) are placeholders — use whatever your project names these helpers. The convention is to *have* them.
>
> **Directory and instance placeholders** referenced in this pack: `<sql module>` (Python module owning SQL queries / data-access helpers), `<db config module>` (the file housing the engine instances — typically `db_config.py`), `<db config instance>` (the imported instance whose `.reader_engine` / `.writer_engine` / `.admin_engine` attributes are read at runtime), `<engine>` (one of `reader_engine` / `writer_engine` / `admin_engine`), `<migrations dir>` (Alembic / raw SQL migration scripts directory), `<log sanitizer>` (the project-defined log-redaction helper).
>
> **Cross-pack dependency:** `checks.yml.fragment` in this pack additionally references `<api module>`, `<scripts dir>`, `<datajobs dir>`, and `<datajobs entrypoint>`, all of which are declared in the python pack. The § `<scripts dir>` overlay below also reuses `<scripts dir>` and `<datajobs entrypoint>` as section globs. Installing postgres without python will leave these unsubstituted in the merged `checks.yml` and `convention_map.md`.

---

## `<sql module>/*.py`, `<sql module>/queries/*.py`, `<db config module>` — SQL & Data Layer

- **SQL safety**: Never f-strings for SQL — use parameterized queries or the project's centralized SQL helper (e.g., `_latest_obs_sql()`); validate identifiers with the identifier validator
- **LIKE escaping**: Dynamic values in `LIKE`/`ILIKE` must use the LIKE-escape helper + `ESCAPE '\\'`
- **SQL LIMIT**: All queries returning row data must include a `LIMIT` clause
- **Engine selection**: SELECTs → `reader_engine`; INSERT/UPDATE → `writer_engine`; migrations only → `admin_engine`
- **Engine null guards**: Check `if not <db config instance>.<engine>:` at function entry before `.connect()`/`.begin()` — return safe default + warning log. Apply to private helpers too, even when called from a single guarded entry point.
- **Writer transaction management**: Use `engine.begin()` for writer operations, not `connect()` + manual `commit()` — auto-commits on success, auto-rolls-back on exception
- **Intentional exceptions vs. broad except**: Catch `ValueError`/`TypeError` specifically before `except Exception` when they are API contracts — prevents silent swallowing
- **Batch loop resilience**: Wrap per-item logic in try/except; for SQL batch inserts, use `conn.begin_nested()` (SAVEPOINT) per chunk
- **Error message truncation**: Truncate error messages before DB storage (`error_message[:2000]`)
- **Logging**: User/external data in log statements → `<log sanitizer>()`; exceptions → `<log sanitizer>(str(e)[:500])`, never the raw exception object
- **Logger formatting**: Use `logger.info("msg %s", val)` not f-strings

> AST-backed equivalents: `semgrep-missing-writer-engine-guard`, `semgrep-sql-fstring` (in this pack's `semgrep/` directory)

## `<migrations dir>/*.sql` — Database Migrations

- **Migrations & runtime code co-change**: When a migration changes data semantics (ID consolidation via aliases, unit changes, key deletions, series renames), grep runtime code in the same PR for references to the affected identifiers and update them. Stale hardcoded IDs or unit strings silently produce empty data, wrong labels, or re-seed regressions. Grep targets: backend modules, scripts, frontend data files, any seed scripts.
- **ON CONFLICT target**: Prefer composite PK over UNIQUE-index target for `ON CONFLICT` clauses on tables with composite primary keys — match the pattern used by recent sibling migrations.
- **Test co-change**: Search test directories for assertions on old column defaults, constraints, or unit strings before merging.

## `<scripts dir>/*.py`, `<datajobs entrypoint>` — CLI Scripts and Job Entrypoints (overlay)

> Overlay onto the python pack's base `<scripts dir>` section — only relevant when the consuming project has a Postgres / SQLAlchemy engine layer. A mongo or sqlite overlay would replace this one.

- **Engine-gating env-var error messages**: Engine-unavailable error messages must reference the specific gating env var — `DB_PASS_READER` for reader engine, `DB_PASS_WRITER` for writer engine, `DB_PASS` only for admin engine. Generic `"DB_PASS not set"` misdirects operators to fix the wrong variable.
- **Engine as parameter**: Pass `<engine>` to worker functions; never instantiate engines at module level; wrap in `main()`.
- **Defensive engine null guards in private helpers**: Even when called from a single guarded entry point (`main()`), include `if not <db config instance>.<engine>:` at function entry — silent foot-gun for future refactors that introduce a second caller.
- **Closable engines inside try/finally**: When the closable-resources rule applies to engines specifically, create the engine inside `try` block — not before it.
