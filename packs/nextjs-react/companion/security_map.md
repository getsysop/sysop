# Security Concern Map — Next.js / React pack

> Maps file patterns to relevant OWASP security checks for Next.js + React + TypeScript projects.
> Used by `/security-audit` to focus agents on applicable checks per file area.
> Each section lists what TO check and what to SKIP — agents must respect both.

> **Helper names** (e.g., `getDisplayError()`, `isSafeHref()`, `getSafeRedirect()`, `isAllowedRedirectUrl()`, `MARKDOWN_ALLOWED_ELEMENTS`) are placeholders for whatever your project names these — adapt to your actual helpers.

---

## `<frontend>/**/__tests__/*.ts`, `<frontend>/**/__tests__/*.tsx` — Frontend Tests

**Check:**
- **A02 Data Exposure**: No hardcoded real credentials, API keys, or connection strings in test fixtures. Mock tokens should be obviously fake (e.g., `mock-token-xxx`).
- **A05 Misconfiguration**: No accidental production API endpoint URLs in test mocks. All fetch mocks should use relative paths or localhost.

**Skip:** A01, A03, A07, A10, XSS, LLM — tests run locally with mocked services

---

## `<components dir>/**/*.tsx` — React Components

**Check:**
- **XSS**: ReactMarkdown `allowedElements` list present and minimal; NO `dangerouslySetInnerHTML`; safe-href helper on all link hrefs from external/API/LLM sources; `window.open` includes `noopener,noreferrer`
- **A02 Data Exposure**: Error display uses error-display helper — never raw `err.message`

> AST-backed equivalent: `semgrep-error-display-jsx` (in this pack's `semgrep/` directory)

**Skip:** A03 (server injection), A07 (auth — handled by auth layer), A10 (SSRF), A05 (config), A06 (dependencies), LLM (backend concern)

---

## `<hooks dir>/*.ts` — Custom Hooks

**Check:**
- **XSS**: `encodeURIComponent()` on dynamic values in fetch URL path segments and query params
- **Privacy**: AbortController cleanup prevents data leaks from cancelled requests; timer cleanup

**Skip:** A01-A07, A10, LLM — all handled server-side

---

## `<frontend lib>/*.ts`, `<frontend lib>/*.tsx` — Frontend Utilities

**Check:**
- **XSS**: Safe-href helper implementation correctness (scheme allowlist, edge cases like fragment-only URLs), markdown allowed-elements list completeness
- **A01 Access Control**: Open-redirect prevention helper — scheme + origin allowlist correctness

**Skip:** A03 (server injection), A07 (auth), A10 (SSRF), LLM

---

## `<app dir>/page.tsx`, `<app dir>/**/page.tsx`, `<app dir>/api/**/*.ts`, `<app dir>/chart-render/**/*.tsx` — Pages & API Routes

**Check:**
- **XSS**: URL validation before `window.location.href` assignment (allowlist-based redirect helper), `encodeURIComponent()` on fetch URL segments
- **A02 Data Exposure**: HTTPS enforcement for backend URL in prod/staging, payload size validation
- **A05 Misconfiguration**: Revalidation secret handling, auth header forwarding correctness

**Module-specific notes:**
- Internally-screenshotted routes (e.g., `<app dir>/chart-render/[slug]/[tag]/page.tsx`): `robots: 'noindex'`, restrictive CSP (`frame-ancestors 'none'`), slug/tag regex validation with `notFound()`, `redirect: 'error'` on fetch.

> AST-backed equivalents: `semgrep-missing-encode-uri`, `semgrep-error-display-jsx` (in this pack's `semgrep/` directory)

**Skip:** A03 (server injection), A10 (SSRF), LLM

---

## `<app dir>/(auth)/*.tsx`, `<app dir>/layout.tsx`, `<app dir>/global-error.tsx`, `<app dir>/embed/**/*.tsx` — App Shell

**Check:**
- **XSS**: Error display uses the project's error-display helper — never raw `err.message`; no `dangerouslySetInnerHTML`

**Skip:** A01, A03 (SQL injection), A05, A06, A07, A10, LLM, Logging, Privacy — app shell files are thin wrappers with minimal security surface

---

## `<next config>` — Security Headers & Proxy

**Check:**
- **A05 Misconfiguration**: CSP directives completeness (`form-action`, `frame-ancestors`), `X-Frame-Options`, HSTS (`includeSubDomains`, `preload`), `Permissions-Policy` (deny unused APIs), embed route has reduced permissions
- **XSS**: CSP `unsafe-inline` status, `script-src` allowlist minimal
- **A01 Access Control**: API rewrite proxy completeness (missing rewrites → silent 404s in production)

**Skip:** A03 (injection), A07 (auth), A10 (SSRF), LLM
