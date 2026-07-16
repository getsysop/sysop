# Convention Map — LLM pack

> Maps file patterns to relevant LLM-integration conventions from `CLAUDE.md` § Prevention Conventions.
> These conventions are language-agnostic in principle — examples shown in Python (`google.generativeai` / `anthropic` SDKs), but the patterns apply to TypeScript/Node, Go, etc.

> **Helper names** (e.g., `_sanitize_log()`, `redact_api_keys()`) are placeholders — use whatever your project names these helpers.
>
> **Directory placeholders** referenced in this pack: `<api module>` (web framework module hosting LLM-using endpoints), `<evals module>` (LLM eval runner code), `<data pipeline>` (ingestion / batch pipeline code that calls LLM APIs), `<prompts dir>` (Markdown prompt templates loaded at runtime), `<llm utility modules>` (shared LLM-call helpers, response parsers, redaction utilities), `<post-LLM helper module>` (sanitization / output-shaping helpers applied after raw LLM response), `<log sanitizer>` (the project-defined log-redaction helper).
>
> **Cross-pack dependency:** `<api module>` and `<scripts dir>` (referenced in this pack's `checks.yml.fragment`) are also declared in the python pack. Installing llm without python will leave these unsubstituted in the merged `checks.yml`.

---

## `<api module>/server.py`, `<api module>/routes/**/*.py` — LLM-using endpoints

- **LLM output bounds**: All `GenerateContentConfig` calls must include `max_output_tokens` (suggested: 2048 for JSON, 4096 for prose). Without bounds, a crafted query can trigger verbose reasoning that inflates per-request cost arbitrarily.
- **LLM response parsing**: Guard LLM response bodies — check `if not response.text` before `json.loads()`. Catch `json.JSONDecodeError` explicitly before any broad `except Exception`; re-raise as descriptive `ValueError("LLM returned invalid JSON")` so callers distinguish parse failures from upstream outages.

## `<evals module>/*.py` — LLM Eval Runner

- **Secrets in logs**: Never use `logger.exception()` — it dumps full tracebacks that embed Vertex AI / Anthropic request URLs and API key fragments. Use `logger.error("msg: %s", <log sanitizer>(str(e)[:500]))` instead.
- **Logging**: Exceptions → `<log sanitizer>(str(e)[:500])`, never the raw exception. Never `logger.exception()` or `logger.*(..., exc_info=True)` — both bypass redaction; use `%s` style, not f-strings
- **LLM response guards**: Check `if not response.text` (Gemini) or `if not text` (Anthropic) before processing — safety filters and rate limits can produce empty bodies
- **LLM output bounds**: All `GenerateContentConfig` calls must include `max_output_tokens`

## `<data pipeline>/*.py` — LLM-using pipeline modules

- **LLM prompt boundaries**: `html.escape()` user/external content before interpolating into XML-tagged prompts (e.g., `<user_query>`, `<custom_angle>`, `<press_release_content>`) to prevent attackers from closing the tag and injecting arbitrary instructions. Prefer multi-part content (Gemini) where user input is in a separate `Part`
- **LLM response parsing**: Guard LLM response bodies — check `if not response.text` before `json.loads()`. Catch `json.JSONDecodeError` explicitly before any broad `except Exception`; re-raise as descriptive `ValueError`
- **LLM output bounds**: All `GenerateContentConfig` calls must include `max_output_tokens`

> AST-backed equivalent: `semgrep-llm-cost-abuse` (in this pack's `semgrep/` directory)

## `<prompts dir>/releases/*.md` — LLM Prompt Templates (release-specific)

- **Filename convention**: `{release_id}.md` where `release_id` matches `^[a-z0-9-]+$`. Must exactly equal the release_id used in your project's release dispatch logic.
- **Section headers**: Only `## reader`, `## router`, and `## drafter` are parsed by typical prompt-registry implementations. Other top-level headers are silently dropped — use `###` sub-headers if you want a visible outline inside a recognized section.
- **HARD RULES placement**: Per-release behavioral rules that must bind the Drafter or Analyst must appear at the TOP of the `## drafter` section as `**HARD RULE — ...**` bold headers — not inside numbered Operational Rules or at the end of the template. Reason: Gemini and Claude both weight top-of-section content more heavily; buried rules silently fail to constrain output.
- **No dynamic interpolation in templates**: Templates are static Markdown. Any user-supplied or external content gets interpolated at the call site, with `html.escape()` applied before insertion — the template file itself must not contain `{...}` placeholders or f-string markers.
- **Multi-chart instructions**: When the runtime auto-injects chart tags (e.g., `CHART_HEADLINE`), list them under a `MULTI-CHART INSTRUCTIONS` block with the exact marker `**Auto-injected by backend pipeline. Do NOT generate a chart config for this tag. Do NOT place this tag in \`content_md\`.**` — prevents the Drafter from emitting a stale chart config or leaving a placeholder inline.

## `<prompts dir>/*.md` — Standalone LLM Prompt Templates (non-release)

Covers standalone prompt templates that are NOT release-specific (e.g., reviewer, system-instruction templates). Loaded directly via `Path(...).read_text()`, not via a prompt registry.

- **No dynamic interpolation in templates**: Templates are static Markdown. External content interpolated at the call site with `html.escape()` — never `{...}` placeholders or f-string markers.
- **Module-scope load**: Templates are loaded once at module import with an `OSError` guard that sets the prompt string to `""` on failure. The caller must skip (fail-open) when the loaded prompt is empty — crashing because a deploy dropped a prompt file is worse than a disabled feature.
- **HARD RULES placement**: Behavioral rules that must bind the model should appear at the TOP of the file or at the TOP of the relevant section as `**HARD RULE — ...**` bold headers, not inside numbered rules or at the end. LLMs weight top-of-section content more heavily.
