# Semgrep AST Rules

This README documents the universal authoring conventions for Semgrep rules used in the Sysop check pipeline. **Rule YAMLs and fixtures live in each pack's `companion/semgrep/` directory**, not here — the Phase 3 installer collects rules from the selected packs into the project-side `.claude/semgrep/`.

Rules augment the regex-based checks in each pack's `companion/checks.yml.fragment` (concatenated into the project-side `.claude/checks.yml`). They are invoked by `sysop/scripts/run_checks_impl.py` (`_run_semgrep()`) alongside the grep and LSP passes whenever `bash sysop/scripts/run_checks.sh` runs.

## When to add a Semgrep rule vs a regex check

**Use a regex check (`checks.yml.fragment` `pattern:`)** when:
- The pattern is unambiguous in text (e.g., `grant-sensitive-table` looks for specific SQL keywords in migration files)
- You need invert-file checks (`invert_file_check: true`) to flag files that *lack* a pattern
- The check runs on file names or paths, not code content

**Use a Semgrep rule (this directory)** when:
- A regex over-fires and the false positives require manual triage (`notes: "Needs LLM triage"` in checks.yml)
- The check needs function-scope context (e.g., "this function lacks an early-return guard")
- The check is JSX-context-specific (e.g., "only when rendered, not when logged")
- The check involves template literal interpolation with negation (e.g., "missing encodeURIComponent")

Both run every scan. Use the A/B hit-count comparison across `/codebase-review` Rounds to measure precision before removing the regex twin.

## Rule authoring conventions

### File naming
`<snake_case_id>.yaml` matching the `id:` field (which is bare, without the `semgrep-` prefix). `_run_semgrep()` prepends `semgrep-` at result-mapping time so the check ID in findings is `semgrep-<id>`.

### Severity mapping
| YAML severity | Mapped to |
|---|---|
| `ERROR` | HIGH |
| `WARNING` | MEDIUM |
| `INFO` | LOW |

### Paths
`paths:` in the YAML is **optional**. The Python caller (`run_checks_impl.py`) filters results by `included_ids`, and — as of Phase 133 — the pack's `checks.yml.fragment` stub entry's `paths:` post-filters the rule's findings, so path scoping belongs in the stub entry, not in the rule YAML. Omit `paths:` from new rules — `paths.include` in the YAML causes semgrep to skip fixture files during `semgrep scan --config <rule>.yaml fixtures/` testing because the fixture paths don't match the rule's include patterns (the loop-mode dogfood hit exactly this: a path-restricted rule whose positive/negative fixtures never matched). If a rule genuinely must carry its own `paths.include`, add the fixtures glob (`**/fixtures/**`) to that include so the fixture run still exercises it.

Existing rules carry `paths:` for historical documentation reasons; do not add it to new rules.

### Fixtures
Add positive (should-flag) and negative (should-not-flag) fixtures in the pack's `companion/semgrep/fixtures/` directory for every rule. Run from the pack root:
```bash
semgrep scan --config <pack>/companion/semgrep/<rule>.yaml \
  <pack>/companion/semgrep/fixtures/<rule>_positive.* \
  <pack>/companion/semgrep/fixtures/<rule>_negative.* \
  --metrics=off --no-git-ignore
```
Expected: positive files produce findings; negative files produce 0 findings.

### Metavariable naming
- `$F` — function name
- `$METHOD` — method name (e.g., `begin`, `connect`)
- `$EXPR` — interpolated expression
- `$LOGGER` — logger variable name
- `$CONN` — database connection variable
- `$TAG` — JSX element tag
- `$ERR` — error variable name

## Current rules

Rule files live in each pack's `companion/semgrep/` directory. Each rule corresponds 1:1 with a `semgrep-<id>` stub entry in the same pack's `companion/checks.yml.fragment`. To see what rules a pack ships, list `<pack>/companion/semgrep/*.yaml`.

| Pack | Rules |
|---|---|
| `packs/python/companion/semgrep/` | `http_client_redirect.yaml`, `logger_fstring.yaml`, `recompile_inside_def.yaml` |
| `packs/postgres/companion/semgrep/` | `missing_writer_engine_guard.yaml`, `sql_fstring.yaml` |
| `packs/nextjs-react/companion/semgrep/` | `abort_error_setstate.yaml`, `error_display_jsx.yaml`, `missing_encode_uri.yaml`, `missing_fetch_redirect.yaml` |
| `packs/llm/companion/semgrep/` | `llm_cost_abuse.yaml` |

The check ID in findings is `semgrep-<rule_id>` — `_run_semgrep()` prepends the prefix at result-mapping time.

## Graduating a rule

1. After a `/codebase-review` Round, manually triage both the Semgrep findings and the regex findings for the same rule.
2. Compute FPR = FP / (FP + TP) for each. If semgrep FPR < regex FPR **and** semgrep recall ≥ regex recall, the rule is ready to promote.
3. Remove the `pattern:` field from the pack's `checks.yml.fragment` entry (the regex check) and set `notes:` to `"AST-backed by semgrep-<id>"`.
