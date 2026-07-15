# Shared: UI Verification Procedure

Invoked by the `/claim-task` Step 7 reviewer-executor sub-agent (post-fix UI
verification) and `/document-work` Step 1c whenever the diff touches
`frontend/`. Probes the dev server, navigates to the changed feature via
Playwright MCP, and checks the browser console + network for regressions.

---

## Step 1: Detect frontend diff

Run:
```bash
git diff --name-only main -- frontend/
```

This covers both committed and uncommitted changes relative to `main`. If the
output is empty, emit:

```
UI verify: no frontend changes, skipping.
```

and return. Do not open the browser.

## Step 2: Probe dev server

```bash
curl -sf http://127.0.0.1:3000 -o /dev/null
```

If the exit code is non-zero, emit:

```
UI verify: dev server not running on :3000 — skipping.
Run 'npm run dev' in frontend/ to enable this gate.
```

and return cleanly (do NOT hard-fail the parent skill).

If the project has a separate backend service (typical for SPA + API split — e.g., Next.js + FastAPI), also probe it. Substitute `<backend-port>` and `<healthcheck-path>` with your project's values:
```bash
curl -sf http://127.0.0.1:<backend-port>/<healthcheck-path> -o /dev/null
```

If the backend is down, emit a **warning** (do not skip):

```
UI verify: backend not running on :<backend-port> — data-driven pages may produce API
errors. Continuing walkthrough; network 5xx will be surfaced as hard fails.
```

Skip this probe entirely for single-process apps (e.g., Streamlit, Rails, Django) where there is no separate backend.

## Step 3: Map changed files to verification targets

**This table is project-specific.** Each project must populate its own changed-file → URL mapping in `<project>/.claude/ui_verify_routes.md` (or inline in this skill if you fork it project-side). See `WORKFLOW.md` for the format. Cap at **4 routes** per invocation to bound runtime. When multiple rows match a single file, prefer the more specific match.

| Changed-file glob | Verification URL(s) | Notes |
|---|---|---|
| `<frontend page glob>` | `http://127.0.0.1:<port>/<route>` | `<when-anonymous-OK or skip-reason>` |
| *(anything else under `<frontend>/**`)* | `http://127.0.0.1:<port>/` + `http://127.0.0.1:<port>/<core-route>` | Conservative fallback |

**If all changed files map to skip rows** (only `settings/**` and/or `embed/**`),
emit:

```
UI verify: all changed files route to auth-gated or deferred paths (settings,
embed). Manual verification required before merging.
```

and return without hard-failing.

## Step 4: Walk each route via Playwright MCP

For each URL collected in Step 3 (max 4):

1. Navigate:
   ```
   mcp__plugin_playwright_playwright__browser_navigate(url=<URL>)
   ```
   This blocks until `DOMContentLoaded`.

2. Hydration settle — wait 3 seconds for React effects and initial data fetches:
   ```
   mcp__plugin_playwright_playwright__browser_wait_for(time=3)
   ```

3. Capture DOM snapshot for diagnostics (not asserted against; referenced in
   failure reports only):
   ```
   mcp__plugin_playwright_playwright__browser_snapshot()
   ```

4. Fetch console log:
   ```
   mcp__plugin_playwright_playwright__browser_console_messages()
   ```

5. Fetch network log:
   ```
   mcp__plugin_playwright_playwright__browser_network_requests()
   ```

## Step 5: Evaluate results

Apply the following rules **per route**:

### Hard fail (abort the parent skill, do not proceed to commit)
- Any console message with `type == "error"`.
- Any HTTP response where the **page URL itself** (the navigated URL, not a
  sub-resource) returned 4xx or 5xx.
- Any sub-resource response with status `>= 500`.

### Ignored (expected for anonymous walks — do not warn or fail)
- `401` or `403` on any of these paths:
  `/api/studio/*`, `/api/templates/*`, `/api/users/me`, `/api/saved/*`,
  `/api/stripe/*`, `/api/auth/*`

### Warn (report but do not fail)
- Console messages with `type == "warn"`.
- Any 4xx sub-resource response that is NOT in the ignored list above.

### Known benign patterns (do not fail or warn)
Extend this list as false positives are identified:
- *(empty for v1 — add patterns here as they surface)*

### Pass
Everything else.

## Step 6: Report

Emit a compact summary block:

**Pass example:**
```
UI verify: 2/2 routes clean.
  ✓ http://127.0.0.1:3000/dashboard — 0 errors, 0 5xx, 1 warning
      WARN  useStudioData: 401 /api/users/me (expected, anonymous)
  ✓ http://127.0.0.1:3000/studio?series=GDPC1 — 0 errors, 0 5xx, 0 warnings
```

**Hard-fail example:**
```
UI verify: FAILED — 1 console error on http://127.0.0.1:3000/

  ERROR  TypeError: Cannot read properties of undefined (reading 'map')
         at LandingNarrativeCharts.tsx:47

  DOM snapshot excerpt:
  [relevant accessibility tree fragment]

Fix the console error above and re-run verification before committing.
```

## Step 7: Fallback & skip catalogue

The following skip reasons are auditable — surface the exact text verbatim in
the parent skill's handoff message so the user knows what was skipped and why:

| Condition | Emitted text |
|---|---|
| No frontend files in diff | `UI verify: no frontend changes, skipping.` |
| Dev server not running | `UI verify: dev server not running on :3000 — skipping. Run 'npm run dev' in frontend/ to enable this gate.` |
| All paths auth-gated or deferred | `UI verify: all changed files route to auth-gated or deferred paths (settings, embed). Manual verification required before merging.` |
| Playwright MCP unavailable | `UI verify: Playwright MCP tools not available in this session — skipping. Verify manually in browser.` |

---

## Alternative: Chrome DevTools MCP

If Playwright MCP is unavailable or you prefer Chrome DevTools:

- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page` → navigate
- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__list_console_messages` → console
- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__list_network_requests` → network
- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_snapshot` → DOM snapshot

Apply identical evaluation logic from Step 5.
