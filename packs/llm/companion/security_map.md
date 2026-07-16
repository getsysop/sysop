# Security Concern Map — LLM pack

> Maps file patterns to relevant OWASP security checks for files that integrate with LLM SDKs.
> Examples assume Python (`google.generativeai` / `anthropic` SDKs); the principles apply to any language/SDK pair.
> Each section lists what TO check and what to SKIP — agents must respect both.

> **Helper names** (e.g., `_sanitize_log()`, `redact_api_keys()`, `html.escape()`) are placeholders or canonical Python references — adapt to your language.

---

## `<api module>/server.py`, `<api module>/routes/**/*.py` — LLM-using endpoints

**Check:**
- **LLM Security**: `max_output_tokens` on ALL LLM generation calls (`GenerateContentConfig` or equivalent), retry bounds on LLM calls, request timeout enforcement
- **A03 Injection**: Prompt injection — `html.escape()` on user content interpolated into LLM prompt boundary tags (e.g., `<user_query>`, `<custom_angle>`, `<press_release_content>`)

**Skip:** A06 (dependencies), A10 (SSRF — internal LLM calls go to provider, not user-supplied URLs)

---

## `<data pipeline>/*.py` — LLM-using pipeline modules

**Check:**
- **LLM Security**: Prompt injection — `html.escape()` on ALL content interpolated into XML boundary tags; `max_output_tokens` on all LLM calls; retry bounds
- **A02 Data Exposure**: API key redaction on all error messages before sinks (Slack, PagerDuty, etc.) — `<api key redactor>()` with pre-truncated `str(e)[:N]`

**Skip:** A01 (auth-gated internal pipeline), XSS (no frontend rendering)

---

## `<llm utility modules>/*.py` — Backend Utility Modules (LLM-adjacent)

**Check:**
- **LLM Security**: `max_output_tokens` on all LLM generation calls, `html.escape()` on user content interpolated into LLM prompt boundary tags, guard `response.text` (Gemini) / `text` (Anthropic) before `json.loads()`

**Skip:** A01, A03 (no SQL), A10 (SSRF), XSS

---

## `<post-LLM helper module>` — Post-LLM String Helpers

**Check:**
- **LLM Security**: Design invariant — any post-LLM transformation (e.g., attribution suffix, output sanitizer, tag injector) MUST be applied post-LLM and MUST NOT be interpolated into any prompt or system instruction. A prompt-injection test (target string absent from `send_message` / `messages.create` call args) gates this at the endpoint level.
- **A02 Data Exposure**: No logging, no exception surface — pure string functions.

**Skip:** A01, A03, A05, A07, A10, XSS — no IO, no SQL, no auth, no network surface.

---

## `<evals module>/*.py` — LLM Eval Runner

**Check:**
- **LLM Security**: `max_output_tokens` on all LLM generation calls; guard `response.text` / `text` before processing
- **A02 Data Exposure**: Never use `logger.exception()` — dumps full tracebacks with provider request URLs and API key fragments. Use `logger.error("msg: %s", <log sanitizer>(str(e)[:500]))` instead.
- **Logging**: Exceptions → `<log sanitizer>(str(e)[:500])`, never the raw exception

**Skip:** A01 (no user access), A03 (no SQL), A07 (no auth), A10 (SSRF), XSS

---

## `<prompts dir>/**/*.md` — LLM Prompt Templates (release-specific and standalone)

**Check:** None — static Markdown templates with no dynamic interpolation. User-supplied content is inserted at the call site (orchestrator for Drafter, reviewer for the critic, etc.), where prompt-injection defenses (`html.escape()` around user content, XML boundary tags, `max_output_tokens`) already apply. The template file itself has no attack surface.

**Skip:** A01, A03, A05, A07, A10, XSS, LLM prompt injection, logging sanitization — all enforced at the interpolation site, not here.
