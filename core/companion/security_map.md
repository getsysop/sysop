# Security Concern Map — Core (workflow meta)

> Maps file patterns to relevant OWASP security checks for files that are part of (or governed by) the Sysop workflow itself.
> Each section lists what TO check and what to SKIP — agents must respect both.
> The bash installer concatenates this file with selected packs' `security_map.md` into the target project's `.claude/security_map.md`.

---

## `scripts/*.sh`, `scripts/hooks/*` — Shell Scripts & Git Hooks

**Check:**
- **A03 Injection**: Variable expansions in command arguments must be double-quoted to prevent word splitting and injection. `eval` and unquoted `$()` on user/env input are injection vectors.
- **A02 Data Exposure**: No hardcoded secrets (passwords, API keys, project IDs) — read from environment variables. Exception messages from subprocesses may leak credentials.
- **A05 Misconfiguration**: `set -euo pipefail` at script top. `source .env` before DB/API operations. Cleanup traps for temp files and locks.

**Skip:** A01 (local execution), A07 (no auth tokens), A10 (SSRF), XSS, LLM

---

## `Dockerfile`, `<datajobs Dockerfile>`, `.dockerignore` — Container Build

**Check:** A05 (base image version pinning, package-manager upgrade before install, non-root user, `.dockerignore` excludes `.env`/secrets)

**Skip:** Everything else

---

## `.gitignore`, `.env*` — Repo Hygiene

**Check:** A02 (secrets exclusion — `.env`, `*.pem`, `*.key`, `*-credentials.json`, `serviceAccount*.json`)

**Skip:** Everything else

---

## `.github/workflows/*.yml` — CI Configuration

**Check:**
- **A05 Misconfiguration**: `permissions:` block with least-privilege, action version pinning (avoid `@main`), `pip-audit` / `npm audit` version pinning
- **A06 Dependencies**: Dependency-scan coverage (every relevant lockfile included), severity thresholds documented

**Skip:** Everything else

---

## `.claude/skills/**/*.md`, `.claude/checks.yml` — Skill Markdown & Check Registry

**Check:**
- **No real credentials in skill markdown**: Grep for API keys, access tokens, passwords, webhook URLs — use placeholders (`$VAR`, `<token>`) instead.
- **No CI-bypass instructions as routine**: `--no-verify`, `SKIP_HOOKS=1`, `--force-with-lease` shortcuts, or equivalent must not be documented as normal workflow. They defeat security pre-commit hooks and reviewer gates. Exceptional emergency procedures must explicitly say "emergency only — requires sign-off from …".
- **Confirmation gates on destructive operations**: Any documented `rm -rf`, `git reset --hard`, `psql -c DROP`, production migration, or cloud deploy command must include an explicit confirmation step in the skill text.
- **`checks.yml` registry hygiene**: Each check must have `used_by` populated; `blocking: true` promotions should cite a baseline verification step; regex patterns with high false-positive rates need `notes:` explaining the triage shape.

**Skip:** Everything else
