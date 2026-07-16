// Negative fixtures — none should fire. Patterns sourced from real
// codebase sites: useExportData.ts:229,252, useChartTransforms.ts:116,
// lib/api.ts:47, useAbortableFetch.ts:25.

const url = "/api/example";
const accessToken = "fake-token";
const title = "Example";
const options: RequestInit = {};
const controller = new AbortController();

// ok: missing-fetch-redirect — literal redirect at end of options
fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    redirect: "error",
});

// ok: missing-fetch-redirect — literal redirect with double quotes
fetch(url, { method: "GET", redirect: "error" });

// ok: missing-fetch-redirect — spread options, redirect literal first
// (mirrors useAbortableFetch.ts:25)
fetch(url, { redirect: "error", ...options, signal: controller.signal });

// ok: missing-fetch-redirect — spread options, redirect literal in middle
// (mirrors lib/api.ts:47)
fetch(url, { ...options, redirect: "error", headers: { Authorization: `Bearer ${accessToken}` } });
