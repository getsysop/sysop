# Permission guard (shared step)

Several Sysop skills perform git operations that an agent harness may refuse
(e.g., `git merge --ff-only` into `main`, `git worktree remove`,
`git push origin --delete`). In Claude Code, the mode that makes such a refusal
**non-interactive** is `permissions.defaultMode: "dontAsk"` — it "auto-denies
every tool call that would otherwise prompt you," running only calls matching
`permissions.allow`, read-only Bash commands, and calls a `PreToolUse` hook
approved. Under that mode a missing allow-rule surfaces as an opaque halt —
worst-case mid-merge, with worktrees half-applied. Under `auto` the classifier
can also block a call; the denial *is* surfaced (a notification, plus a retry
entry under `/permissions` → *Recently denied*), but the skill's step still
failed, so the pre-flight is still worth more than the mid-merge discovery.

`bash install.sh` writes a project-scoped allow-list to
`<target>/.claude/settings.json` covering every command the documented skills
invoke. This guard exists so a skill fails *loudly* and *early* if that file
is missing or has been edited to drop a rule the skill depends on.

> **Correction (Phase 152, 2026-07-26).** Earlier revisions of this file named
> the hazard as `permissions.defaultMode: "auto"` with
> `skipAutoPermissionPrompt: true`. A `claude-code-guide` probe of the official
> permissions, settings and changelog docs found **no such key as
> `skipAutoPermissionPrompt`**, and found that `auto`-mode denials are surfaced
> rather than silent. The documented no-prompt-denial mode is `dontAsk`. The
> hazard is real and was observed in a consumer (BeanRider, 2026-05-12 — a
> `git merge --ff-only` refused with no prompt, stranding the session
> mid-merge); only the configuration name was wrong.

**This guard is Claude-Code-only.** `.claude/settings.json` is the *Claude Code*
harness contract; on any other harness it binds nothing. If you are not running
under Claude Code (e.g. the Codex CLI, whose policy surfaces are `config.toml`,
named profiles, and the `--sandbox`/`--ask-for-approval` flags), **skip this
guard entirely** — skipped-not-failed, straight to the skill's own Step 1 —
rather than spending calls reading a file that is not your harness's policy
surface. Sysop also deliberately does not write a permissive profile for any
non-Claude harness: sandbox and approval policy are the consumer's trust
boundary.

## How to invoke from a skill

Each skill that touches the network or rewrites branch state should run this
guard as its **Step 0**, before any other work. The skill names the specific
rules it depends on; the guard reads the merged permission view and reports
which (if any) are missing.

## Algorithm

1. Resolve the project's `.claude/settings.json`. Also read
   `.claude/settings.local.json` if present — it is project-scoped and takes
   precedence over `settings.json`, so a rule or mode set there is in force.
   If **neither** file exists, treat `permissions.allow` as empty and go
   straight to step 5 (every required rule is unsatisfied).
2. Parse JSON. Read `permissions.allow` from each (union them — allow-rules are
   additive across settings files). Empty list if the key is absent.
3. **Read `permissions.defaultMode`** (`settings.local.json` wins over
   `settings.json`). If it is `"bypassPermissions"`, the allow-list is **inert**
   — the docs are explicit that "allow rules have no effect in
   `bypassPermissions` because everything else is already approved" — so the
   halt this guard prevents cannot occur. Compute the missing set anyway, print
   the skipped-not-failed note from step 5, and **hand off to the skill's own
   Step 1** (not step 1 of this algorithm). Do not stop.
4. For each rule in the skill's *required* list, check whether the allow-list
   satisfies it. A rule is satisfied by an **exact string match**, or by a
   **broader allow-rule that already covers it** — a rule whose text is the
   required rule's command truncated at a word boundary and closed with a
   trailing wildcard. `Bash(git:*)` and `Bash(git worktree:*)` both satisfy a
   requirement for `Bash(git worktree list:*)`; `Bash(git worktree list)` does
   **not** (no trailing wildcard, so it matches only the bare invocation).
   Checking exact strings alone would report a false miss against a consumer
   whose config is broader than ours but equivalent for our purposes.
5. If any required rule is unsatisfied, **stop with a clean error**:

   ```
   ❌ Missing required permission rule(s) in .claude/settings.json:
        - <rule 1>
        - <rule 2>

      These are required because /<skill name> performs <one-line reason>.

      Fix one of:
        (a) Re-run `bash install.sh <target>` to regenerate the allow-list
            (merges with any rules you've added).
        (b) Run `/permissions` to open the permissions UI and add the missing
            rules there — the fastest path, and it applies to this session.
        (c) Add them to `permissions.allow` in `.claude/settings.json` by hand.
            Claude Code watches its settings files and hot-reloads `permissions`,
            so the edit applies to this session — no restart needed. `/status`
            lists the loaded setting sources if you want to confirm it took.

      If you intentionally removed the rule, or you know this session's
      effective mode makes `permissions.allow` inert (e.g. it was started with
      `--dangerously-skip-permissions`), re-run /<skill> with
      `--skip-permission-guard` to override.
   ```

   When step 3 skipped the check, print this instead and continue:

   ```
   ⚠️  permission guard: skipped — defaultMode is "bypassPermissions", so the
      allow-list is inert and no call can be denied.
      Drift report: N required rule(s) are missing and WOULD block this skill
      under "dontAsk":
        - <rule 1>
      Re-run `bash install.sh <target>` to close the gap before switching modes.
   ```

   With no missing rules, one line is enough:
   `permission guard: skipped (defaultMode=bypassPermissions); all N required rules present.`

6. If all required rules are satisfied, hand off to the skill's own Step 1.

## Notes for skill authors

- Required rules should be the **minimum** set the skill's documented happy
  path invokes. Don't list rules for optional steps the user can decline.
- Don't list read-only `git` — `git log`, `git status`, `git branch`,
  `git diff`, `git rev-parse`, `git rev-list`, `git show`. Claude Code
  auto-approves "read-only forms of `git`" **in every mode**, alongside a
  built-in set the docs introduce with *"these include"* — `ls`, `cat`, `echo`,
  `pwd`, `head`, `tail`, `grep`, `find`, `wc`, `which`, `diff`, `stat`, `du`,
  `cd`. Listing them makes a skill hard-stop on a fresh install for rules that
  never needed to ship. **Two caveats the same section states:** the set is
  documented as non-exhaustive and its `git` members are never enumerated, so
  "is *this* subcommand read-only?" is an inference; and commands from the set
  still prompt when an unquoted glob is present (the glob could expand to a
  write flag) and when `cd` into a different directory is compounded with them —
  which is the shape `/auto-fix` and `/auto-judge` use (`cd <worktree> && git …`).
- **`git worktree list` is the one deliberate exception.** It ships a rule
  (`Bash(git worktree list:*)`) and skills do list it. The docs verify the
  read-only-`git` category but never enumerate its members, and `worktree` is a
  subcommand namespace whose siblings (`add`, `remove`) plainly write — so
  whether the classifier reads `worktree list` as read-only is an inference, not
  a documented fact. One cheap rule beats depending on that inference in
  `/review-close` Step 1a, whose whole classification pass reads it.
- **Treat `gh` as NOT auto-approved.** The documented read-only set names `git`
  and never mentions the GitHub CLI. Because that set is explicitly
  non-exhaustive, `gh`'s absence is a strong inference rather than a stated
  fact — so Sysop ships a rule for *every* `gh` invocation, including read-only
  ones like `gh auth status`, `gh repo view` and `gh pr checks`. What is settled
  is the authoring rule: do not justify omitting a `gh` rule by calling the
  command read-only.
- **A rule authorizes a command, not a step — read the bash before adding one.**
  Rules match the literal text the model sends, before shell expansion, and a
  compound command splits on `&&`, `||`, `;`, `|`, `|&`, `&` and newlines with
  each part matched independently. So an unexpanded variable *argument* does not
  defeat a trailing wildcard (`Bash(git add:*)` matches a bare
  `git add -A -- "$p"`), but four shapes do defeat an otherwise-correct rule:
  a variable **command word** (`$PY script.py`); an **assignment capture**
  (`REF="$(gh pr create …)"` — a rule does not match past an assignment of any
  variable outside a fixed known-safe set, so `NODE_ENV=test npm test` *does*
  match `Bash(npm test *)` while an ordinary capture does not); a **loop**
  (`for p in …; do … ; done` splits into parts including `for p in …` and
  `done`, which match nothing); and a **`|| true` tail** (`true` is not in the
  documented read-only set — an inference, since that set is non-exhaustive, but
  the safe way to bet). None of the four is fixable by widening a rule, so the
  fix is always at the call site — Phase 153 reshaped Sysop's own, and
  `WORKFLOW.md` § 8.2a *Invocation shapes* records both what changed and the
  three classes that remain uncovered (runtime-set loops, assignments sharing a
  block, and quoting). Three authoring rules follow:
    - **Need a value produced earlier? Write it out, quoted.** Assume nothing
      survives from one fenced block to the next — the boundary is the block,
      not the step (`WORKFLOW.md` § 8.2a *Persistence boundary*), so a variable
      set under the same heading is still empty here — and the assignment costs
      the invocation its rule match besides. Quote it: an unsubstituted
      `"<PR>"` fails loudly, while an unquoted `<PR>` is a bash redirection and
      an *empty* operand makes `gh` silently pick the current branch.
    - **Need to tolerate a failing command? Use `|| echo "<why>"`, never
      `|| true`.** `echo` *is* in the documented built-in set, so the compound
      stays authorized, and the reader gets told why the failure was expected.
    - **Redirections are not separators.** `2>/dev/null` never cost a match;
      only the `|| true` after it did. Don't strip redirections for permission
      reasons.
- The guard reads `<project>/.claude/settings.json` and
  `.claude/settings.local.json`. Global rules in `~/.claude/settings.json` are
  NOT checked, because user-global state is fragile (it changes when the user
  toggles modes). The project files are the contract.
- **The mode read is best-effort, and wrong in two directions.** Command-line
  arguments and managed settings outrank both project files, so (a) a session
  started with `--dangerously-skip-permissions` looks like a non-bypass config
  and still hard-stops — `--skip-permission-guard` is the sanctioned override
  there; and (b) a project file declaring `bypassPermissions` that a CLI flag
  downgraded will skip the check, degrading to the pre-guard status quo *plus* a
  printed drift report. A third case: **cloud sessions (Claude Code on the web)
  do not honor `bypassPermissions` or `dontAsk` from settings files at all**, so
  a project file declaring bypass reads as inert there while the allow-list is
  fully live. Note also that Claude Code v2.1.142+ **ignores
  `defaultMode: "auto"` set in either project file** (a repository cannot grant
  itself auto mode), so the value read here is never `auto`.
- The `--skip-permission-guard` escape hatch is documented for the rare case
  where a user has good reason to bypass (e.g., they've configured equivalent
  rules under a different name). Skills should still print a one-line warning
  when this flag is used.
