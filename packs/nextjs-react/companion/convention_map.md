# Convention Map — Next.js / React pack

> Maps file patterns to relevant Next.js + React + TypeScript conventions from `CLAUDE.md` § Prevention Conventions.
> Use during planning (before writing code) and review (before committing).
> Full rules live in `CLAUDE.md` — these are actionable reminders.

> **Provenance:** these rules were promoted from recurring review findings on the frontend of a hosted subscription web app — Next.js App Router, React, TypeScript. They assume little beyond the framework itself, so they are the most directly portable of Sysop's packs.

> **Helper names** (e.g., `useAbortableFetch()`, `getDisplayError()`, `isSafeHref()`, `useFocusTrap()`, `isAbortError()`) are placeholders for whatever your project names these helpers. The convention is to *have* them.
>
> **Directory placeholders** referenced in this pack and in `checks.yml.fragment`: `<components dir>` (React component files), `<hooks dir>` (custom React hooks), `<app dir>` (Next.js App Router root — `app/` or equivalent), `<frontend lib>` (shared frontend utility modules — `lib/` or equivalent), `<next config>` (Next.js config file — `next.config.ts` / `next.config.js`), `<frontend>` (the frontend project root, e.g., `frontend/` or repo root for single-app projects).

---

## `<components dir>/**/*.tsx` — React Components

- **Fetch calls**: Use `useAbortableFetch()` for all component-level fetches; suppress `AbortError` with `isAbortError()`
- **Fetch redirect guard**: All `fetch()` calls must include `redirect: 'error'` (highest leverage: pre-set in the `useAbortableFetch` wrapper)
- **`'use client'` directive**: Components using React hooks or Framer Motion must include `'use client'`
- **Error display**: Never render `err.message` — use the project's error-display helper (e.g., `getDisplayError()`)
- **Accessibility**: Modals/drawers need focus trap + Escape + `role="dialog"` / `aria-modal`; icon buttons need `aria-label`; `role="tablist"` and `role="radiogroup"` arrow-key handlers must move DOM focus (call `.focus()` on the new selection — state update alone breaks the roving-tabindex contract); toggle buttons need `aria-pressed`; `<select>` needs an accessible name
- **Focus trap reuse**: Use the project's shared focus-trap hook — no copy-pasted inline implementations
- **DOM ID uniqueness**: All `id` attributes in reusable components via `useId()` hook — covers SVG `<defs>`, ARIA-linked IDs, listbox/option IDs, form fields
- **ReactMarkdown**: Allow-list of elements only; links must validate scheme with the safe-href helper
- **setState updater purity**: `setState(prev => ...)` updaters must be pure — no API calls, AbortController mutations, or localStorage writes inside the updater function
- **Object URL revocation**: Pair every `URL.createObjectURL()` with `revokeObjectURL()` on replacement or unmount
- **Nested interactive elements**: Never nest `<button>` inside `<button>` or `<a>` inside `<a>` — invalid HTML5, undefined behavior

> AST-backed equivalent: `semgrep-error-display-jsx` (in this pack's `semgrep/` directory)

## `<hooks dir>/*.ts` — Custom Hooks

- **AbortController cleanup**: Every AbortController ref must be aborted in cleanup; multiple refs → dedicated cleanup `useEffect`
- **Timer cleanup**: `setTimeout`/`setInterval` IDs in `useRef`, cleared on unmount
- **Stale closures**: Use functional `setState(prev => ...)`, `useRef` synced via `useEffect`, or `useCallback` with complete deps
- **Rules of Hooks**: Never place early returns above hook calls; all hooks must execute before conditional returns
- **Fetch calls**: Use `useAbortableFetch()` pattern; suppress `AbortError` with `isAbortError()`. Don't reuse a single instance across `Promise.all`
- **Fetch redirect guard**: All `fetch()` calls must include `redirect: 'error'`; retry paths inherit the option from the primary call
- **AbortError loading state cleanup**: When `isAbortError()` returns early from a catch in a callback (not `useEffect`), clear loading state before `return` — use `finally` or explicit `setState(false)`. Inside a `useEffect` with a `cancelled` guard, the AbortError branch must NOT call `setState` unconditionally — `return` immediately or wrap in `if (!cancelled)` to avoid racing the next mount/run
- **Error display**: Never render `err.message` — use the project's error-display helper
- **setState updater purity**: Functional updaters passed to `setState(prev => ...)` must be pure — no side effects (API calls, AbortController mutations, localStorage writes). Move side effects to the handler after `setState`, or react to new state via `useEffect`
- **Ref.current in JSX render**: Never read `ref.current` in JSX props for values that affect display — use reactive state instead

## `<app dir>/page.tsx`, `<app dir>/**/page.tsx`, `<app dir>/api/**/*.ts`, `<app dir>/embed/**/*.tsx`, `<app dir>/chart-render/**/*.tsx` — Pages & API Routes

- **URL rendering**: Validate URLs from external sources with the safe-href helper before `href`; for programmatic navigation, validate scheme against an allowlist
- **URL validation**: Validate external URLs before `href`; reject `javascript:`, `data:` schemes
- **URL encoding**: `encodeURIComponent()` on all dynamic values in `fetch()` path segments and query params
- **Next.js proxy rewrites**: New backend endpoints need matching rewrite in `next.config.ts`
- **window.open**: Always include `noopener,noreferrer` in features string
- **Error display**: Never render `err.message` — use the project's error-display helper
- **Fetch redirect guard (server + client)**: All `fetch()` calls (server-side AND client-side hooks/lib/components) must include `redirect: 'error'`. Pre-set in the shared `useAbortableFetch` wrapper so consumers inherit the safe default; retry paths must inherit the option from the primary call

> AST-backed equivalents: `semgrep-missing-encode-uri`, `semgrep-error-display-jsx` (in this pack's `semgrep/` directory)

## `<frontend lib>/*.ts`, `<frontend lib>/*.tsx` — Frontend Utilities

- **URL validation**: Safe-href helper for external URLs; scheme allowlist for programmatic navigation
- **URL encoding**: `encodeURIComponent()` for path segments; `URLSearchParams` for query strings
- **Refactor cleanup**: Remove all unused imports, variables, and functions in the same commit as the refactor
- **Error display**: The error-display helper is the canonical helper — keep it in sync with error shapes

## `<app dir>/(auth)/*.tsx`, `<app dir>/layout.tsx`, `<app dir>/global-error.tsx` — App Shell

- **`'use client'` directive**: Components using React hooks or Framer Motion must include `'use client'`
- **Error display**: Never render `err.message` — use the project's error-display helper
- **Accessibility**: Modals/drawers need focus trap + Escape + `role="dialog"` / `aria-modal`; icon buttons need `aria-label`; `role="tablist"`/`role="radiogroup"` arrow keys must move DOM focus
- **Refactor cleanup**: Remove all unused imports, variables, and functions in the same commit as the refactor

## `<frontend>/**/__tests__/*.ts`, `<frontend>/**/__tests__/*.tsx` — Frontend Tests

- **Mock cleanup**: File-level `afterEach(() => { vi.restoreAllMocks(); })` — never only inside test bodies; `vi.stubGlobal` also needs `vi.unstubAllGlobals()`
- **Module-scope `vi.fn()` reset**: `vi.fn()` at module scope must be re-created in `beforeEach` — `vi.restoreAllMocks()` doesn't reset standalone `vi.fn()` call counts
- **Assertion specificity**: Use `toBeInTheDocument()` not `toBeDefined()` for DOM checks; assert known values
- **Meaningful assertions**: At least one meaningful assertion per test; no try/catch that passes on all exceptions
- **Rules of Hooks**: Test setup must not violate hook ordering (relevant for `renderHook` tests)
- **Import from source**: Import functions/constants from production modules — never copy-paste source code into tests
