---
name: next-task
description: Show the single next claimable task with effort estimate and blockers
argument-hint: "[--review] [--avoid-inflight]"
model: haiku
disallowed-tools: Edit, Write, NotebookEdit
---
<!-- sysop:model-roles frontmatter=quick -->

Run the deterministic resolver and print its output verbatim.

> **Structural read-only guard (Phase 54):** the `disallowed-tools` frontmatter (Claude Code 2.1.152+) removes the file-write tools while this skill is active. Partial by design — `Bash` stays allowed for the resolver invocation, so the guard covers the dedicated write tools, not shell redirects. Non-Claude-Code harnesses ignore the key.

```bash
.venv/bin/python3 sysop/scripts/next_task.py $ARGUMENTS
```

The script is the source of truth for the selection algorithm — see the module
docstring in `sysop/scripts/next_task.py` for the Step 1–7 spec that used to live in
this file. The selection logic is unchanged from the LLM version; only the
implementation moved (Phase 45a, 2026-05-27, gdp commit `e9b53c4e` backport).

## Exit codes

- **0** — success, including the "no tasks found" / "no pending review batches" paths.
- **1** — schema invariant violation (e.g., `current_focus` count != 1, `schema_version` below the supported minimum, body path escapes `tasks/`). Print stderr verbatim — do not reinterpret.
- **2** — unexpected crash. The script wraps `main()` in a top-level safety net that prints `ERROR: next_task.py crashed: <sanitized>` to stderr.

## Why `model: haiku` is still in the frontmatter

The body is a single Bash call that the harness wraps in a haiku turn to print
stdout back to the user. The LLM is no longer involved in selection logic
(that's now in `sysop/scripts/next_task.py`), but the skill envelope still follows the
same model-frontmatter pattern every read-only lifecycle skill uses. Removing it
would diverge from the convention without precedent.

## Why this skill exists at all

A bare bash call would work just as well from a `Bash` invocation, but routing
through `/next-task` preserves three properties:

1. Discoverability — the skill list still surfaces `/next-task` to humans and
   to agents reading their slash-command catalogue.
2. Argument forwarding — `$ARGUMENTS` lets `/next-task --review` (only pending
   review batches) and `/next-task --avoid-inflight` (prefer a task whose likely
   scope won't collide with a worktree building right now, via
   `sysop/scripts/scope_overlap.py`; the selected task is annotated with its overlap
   verdict — Phase 103) work without teaching every caller the script path.
3. Future flexibility — if a future phase re-introduces LLM logic on top of
   the script's output (e.g., natural-language reformatting for chat surfaces),
   the skill body becomes the place to add it without changing callers.
