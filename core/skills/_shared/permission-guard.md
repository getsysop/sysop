# Permission guard (shared step)

Several Sysop skills perform git operations that Claude Code's `auto`
permission mode classifies as needing approval (e.g., `git merge --ff-only`
into `main`, `git worktree remove`, `git push origin --delete`). When the user
runs with `permissions.defaultMode: "auto"` and `skipAutoPermissionPrompt: true`
in `~/.claude/settings.json`, those denials surface as opaque silent halts —
worst-case mid-merge, with worktrees half-applied.

`bash install.sh` writes a project-scoped allow-list to
`<target>/.claude/settings.json` covering every command the documented skills
invoke. This guard exists so a skill fails *loudly* and *early* if that file
is missing or has been edited to drop a rule the skill depends on.

## How to invoke from a skill

Each skill that touches the network or rewrites branch state should run this
guard as its **Step 0**, before any other work. The skill names the specific
rules it depends on; the guard reads the merged permission view and reports
which (if any) are missing.

## Algorithm

1. Resolve the project's `.claude/settings.json`. If absent, fall through to
   step 4.
2. Parse JSON. Read `permissions.allow` (a list of rule strings). Empty list
   if the key is absent.
3. For each rule in the skill's *required* list, check whether the same string
   appears in `permissions.allow`. (Exact-string match — Claude Code's
   permission model is string-equality, not glob-equivalence, when comparing
   allow-rules.)
4. If any required rule is missing, **stop with a clean error**:

   ```
   ❌ Missing required permission rule(s) in .claude/settings.json:
        - <rule 1>
        - <rule 2>

      These are required because /<skill name> performs <one-line reason>.

      Fix one of:
        (a) Re-run `bash install.sh <target>` to regenerate the allow-list
            (merges with any rules you've added).
        (b) Run `/permissions add Bash(<missing rule>)` for each missing rule.
        (c) Edit `.claude/settings.json` by hand and re-source by running
            `/permissions reload` (or restart Claude Code).

      If you intentionally removed the rule, re-run /<skill> with
      `--skip-permission-guard` to override (last-resort; may strand the
      session mid-operation if auto-mode classifier denies).
   ```

5. If all required rules are present, proceed to Step 1.

## Notes for skill authors

- Required rules should be the **minimum** set the skill's documented happy
  path invokes. Don't list rules for optional steps the user can decline.
- Don't list `Bash(git status:*)`, `Bash(git log:*)`, etc. — read-only ops
  are auto-approved under `auto` mode and don't need allow-rules.
- The guard reads only `<project>/.claude/settings.json`. Global rules in
  `~/.claude/settings.json` are NOT checked, because user-global state is
  fragile (it changes when the user toggles modes). The project file is the
  contract.
- The `--skip-permission-guard` escape hatch is documented for the rare case
  where a user has good reason to bypass (e.g., they've configured equivalent
  rules under a different name). Skills should still print a one-line warning
  when this flag is used.
