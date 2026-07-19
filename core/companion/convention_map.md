# Convention Map — Core (workflow meta-conventions)

> Maps file patterns to conventions for files that are part of (or governed by) the Sysop workflow itself.
> These apply regardless of project stack.

> The bash installer concatenates this file with selected packs' `convention_map.md` files into the target project's `.claude/convention_map.md`.

---

## `scripts/*.sh`, `scripts/hooks/*`, `sysop/scripts/*.sh`, `sysop/scripts/hooks/*` — Shell Scripts & Git Hooks

- **`set -euo pipefail`**: All shell scripts must start with `set -euo pipefail` to fail fast on errors, undefined variables, and pipe failures
- **Argument validation**: Validate required arguments early with clear usage messages; never silently default missing args
- **`source .env`**: Scripts that invoke Python with project secrets or run `psql` must `source .env` before the command
- **No hardcoded secrets**: Never hardcode database passwords, API keys, or project IDs — read from environment variables
- **Quoting**: All variable expansions must be double-quoted (`"$VAR"`) to prevent word splitting and globbing on paths with spaces or special characters
- **Cleanup traps**: Scripts that create temporary files or hold locks must use `trap cleanup EXIT` to clean up on exit, error, or interrupt

## `.claude/skills/**/*.md` — Skill Markdown Files (workflow skills)

- **Step numbering**: Preserve the existing ordinal sequence when inserting new steps (e.g., `Step 2b-1`, `Step 2b-2`). Renumbering downstream steps invalidates cross-references in `WORKFLOW.md` and sibling skills.
- **Cross-references**: When adding or renaming a step, grep `WORKFLOW.md` and sibling skill files for references to the changed step number and update them in the same commit.
- **No secrets in examples**: Command examples must use placeholder values (e.g., `$VAR`, `<token>`), never real API keys, DB passwords, or webhook URLs.
- **Runnable command blocks**: Every ```bash``` block should be copy-pasteable as-is — no inline commentary mid-command, no truncation marks, no pseudo-syntax. Use `#` comments for context.
- **Destructive command gating**: Any command that mutates state (`git reset --hard`, `psql -c DROP`, migration execution, deploys) must be preceded by an explicit "ask the user to confirm" instruction in the skill text.
