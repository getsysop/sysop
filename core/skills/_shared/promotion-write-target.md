# Promotion write target — consumer overlay vs. source repo

Canonical rule for **where** convention-promotion (`/codebase-review` + `/security-audit` Step 9) and demotion (Step 9b) writes land. Referenced from both review skills' Step 9 / 9b and the Step 2a map-coverage commit. Load-bearing because the concat-managed base maps are regenerated on `sysop-update.sh`, so a promotion written **only** to a base map is silently lost on the consumer's next update — the exact failure this rule prevents.

## The two contexts

**Consumer install** — detected by the presence of `.claude/sysop.lock` (written by `install.sh`; absent in the Sysop source tree and any project that authors its maps in place). Here the three concat-managed base files —
`.claude/convention_map.md`, `.claude/security_map.md`, `.claude/checks.yml` — are **regenerated from Sysop's core + pack sources on every `sysop-update.sh`** (WORKFLOW.md § 8.2c). A rule written only to a base file survives until the next update, then vanishes. The consumer's `.project.*` overlay siblings are **never** touched by the installer and are re-appended / re-merged into the base on every update — the durable home for locally-grown conventions.

**Source repo** — no `.claude/sysop.lock` (Sysop's own `core/`+`packs/`, or a project with no installer that authors its maps in place). There is no overlay and no regeneration: write the base files exactly as the Step 9 prose describes and stop. The rest of this partial does not apply.

## What to write where (consumer install)

**Dual-write.** Keep the base-file write the Step 9 prose already describes **and** add the durable overlay write below. The base write takes effect for the current and subsequent review rounds and feeds the cross-round recurrence gate (which reads round-attributed base-map entries) before the next update runs the concat; the overlay write is what survives the update. On update the base copy is regenerated away and the overlay copy re-supplies it — relocated to the appended overlay region (cosmetic). No duplication results, because the base regen strips the in-place copy *before* the overlay is re-appended.

| Promoted artifact (Step 9) | Base write (as today) | Durable overlay write (add — consumer install only) |
|---|---|---|
| **`checks.yml` entry** (option i) | append to `.claude/checks.yml` | also add the identical entry to `.claude/checks.project.yml` (merged into the base by `checks[*].id` on update) |
| **`convention_map.md` reminder line** (option b/c) | add `> checks.yml: <id>` / `> AST-backed equivalent: <id>` / `> pre-commit: <letter>` to each matching base section | also add it to `.claude/convention_map.project.md`, under a `## <glob list> — <Section Name>` header matching the target section's globs (restate the header if the overlay lacks it) so the concat re-supplies it inside a parseable section |
| **`semgrep/*.yaml` rule + fixture** (option ii) | write the new file(s) | *none* — the installer only regenerates files it ships, so a new semgrep filename is never overwritten and survives as-is |
| **`sysop/scripts/hooks/pre-commit` letter** (option iii) | append the check | *none* — `sysop/scripts/hooks/*` is preserved as a consumer-modified managed path (Phase 24b), so the appended letter survives |
| **`CLAUDE.md` prose bullet** (option iv) | insert into `§ Prevention Conventions` | *none* — `CLAUDE.md` is the consumer's own file, never managed |

Both review skills write Step 9 reminders to `convention_map.md` — **including `/security-audit`** (a security rule's mechanized-equivalent reminder still lands in the convention map, not the security map). So the Step 9 promotion commit stages only `.claude/convention_map.project.md .claude/checks.project.yml` for the overlay; `.claude/security_map.project.md` is **not** a Step 9 reminder target. The security map's overlay is the durable home for consumer-authored **security-map sections** — written during initial authoring / Step 2a hygiene and retired at Step 9b — so `.claude/security_map.project.md` is staged by the **Step 2a coverage commit** and the **Step 9b demotion commit**, not the Step 9 promotion commit. The `2>/dev/null` in each `git add` line already tolerates any overlay path that doesn't exist (e.g. in the source repo).

## Demotion (Step 9b) in a consumer install

Retire / demote **where the rule durably lives**, or the update resurrects it:

- A rule **this consumer promoted locally** lives in the overlay (per the table above). Retire it by removing it from `.claude/checks.project.yml` / the `.project.md` section (and, cosmetically, its now-appended base copy). Editing only the base leaves the overlay copy to re-supply the "retired" rule on the next update.
- A rule shipped by **Sysop core / a pack** cannot be durably deleted from a consumer install (the concat re-supplies it every update). To suppress a **`checks.yml`-mechanism** core rule, add an **override** entry to `.claude/checks.project.yml` — an id-collision entry (consumer wins) with `paths: ["__disabled_no_op__"]`, the disabling shape (a sentinel path that resolves to nothing). A core **semgrep** or **pre-commit** rule has no consumer-side suppression (the installer re-copies shipped semgrep files and the pre-commit hook on every update), so route its genuine retirement upstream (open an issue). Genuine retirement of any core/pack rule is an upstream decision, not a consumer edit.

## Why not overlay-only

Skills read the **base** maps at review time — Step 2 / Step 2a parse `.claude/convention_map.md` / `.claude/security_map.md`, and the pre-scan reads `.claude/checks.yml`; none read the `.project.*` siblings directly (they are merged into the base only at install/update time). An overlay-only write would therefore be invisible until the next `sysop-update.sh` re-ran the concat — so a promotion could not take effect, or feed the recurrence gate, in the round that created it. Hence the dual-write.
