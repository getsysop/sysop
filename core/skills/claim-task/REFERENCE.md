# `/claim-task` — editor reference

**You are reading this because you are about to change the skill, not run it.**

`SKILL.md` is the runner. It carries procedure, commands, and a one-line reason **only where the
reason changes what the runner does**. This file carries what the *editor* needs: what a rule
protects, what its loss or softening would change, and where it came from.

Claude Code does not load a skill's sibling files automatically — they are read only when
something points at them — so this file costs the runner nothing and the editor pays for it once.

Notes here anchor to **rule ids and step headings, never line numbers.**

---

## Where new rationale goes

**New rationale is authored here, not in the runner.** When you add a rule to `SKILL.md`, the
runner gets the instruction and — only if it changes what the runner does — one line of reason.
The justification, what the rule's loss or softening would change, and the provenance go here.

This is a rule about *where text is written*, not a size budget. A skill may grow as much as the
work requires; what it may not do is grow by accumulating, in the file an agent reads at runtime,
material that only an editor ever needs.

The case for it is arithmetic rather than taste. Every rule in a runner was added because a review
round asked for it, so no single addition is wrong, and rationale accretes at a rate no later
tidying pass recovers — relocating text after the fact moves a fraction of what the next few
changes add. The cheap intervention is at the point of authorship, which is here.

## What is declared

**Nothing yet, and this file is not coverage.** `/review-close` carries a roster of declared
load-bearing rules, each pinned verbatim by a required check. claim-task has no such roster: its
rules are unprotected by construction, exactly as they were before this file existed.

What this file is, today, is a **destination** — the place the rule above sends rationale, so that
the convention has somewhere to point on the day someone writes the next rule for the claim path. Sections
get added here as rules are declared; an empty roster is an honest statement of where the work has
reached, not a gap to paper over.

## What this skill's rules tend to be about

`/claim-task` claims a task, sets up the worktree, and hands off to an executor — so most of its
rules are about state that two sessions can reach at once, and the reason a rule exists is usually
a race that is invisible in the procedure itself.

## Step 8 — the diagnostic mailbox is bounded, and why the runner is told so

**The rule.** Step 8's `_unparseable_*.json` paragraph states a 7-day retention and says that an
*absent* diagnostic may have aged out, so absence is not evidence the executor never ran.

**What it protects.** Phase 314 added a 7-day reclaim to the mailbox and left this paragraph
describing the old unbounded behaviour, including a worked example — *"a run of this claim from
last week"* — that had become exactly the retention boundary. Neither sentence was flatly false,
which is why it survived: the files do still persist across runs, and an agent still must not
delete them. What changed is that they are now *bounded* rather than permanent, and the runner was
never told.

**What its loss or softening would change.** The operational half is the absence clause, and it is
the only part that earns a line in the runner: an orchestrator that reads an empty mailbox as
proof the executor never ran will report a stranger's silence as this claim's result. Before the
cap that reading was sound, because nothing removed a diagnostic. After it, the same reading is a
false negative that grows with the age of the run. Drop the clause and the skill is not wrong
about any single sentence — it is wrong about what an empty mailbox means, which is the question
the step exists to answer.

**Provenance.** `Q-553`, filed by Phase 314's round, closed by Phase 319. Phase 314 corrected the
three surfaces it was permitted to touch in-branch and could not touch this one, because
`core/skills/**` is never tier 1 under CLAUDE.md's fix-in-branch stanza, at any size. The sharp
part of the record: `Q-334`'s own body had *named* this surface as one of three documenting
retention as intended, and Phase 314 copied that sentence into the archive and wrote "RESOLVED"
beneath it without changing the surfaces. The sibling sentence in `auto-build/SKILL.md`'s
rolling-window refill step was corrected in the same commit; that skill has no reference file, so
its runner carries the bound in a parenthetical and nothing more.

**Adjacent, still open.** `Q-052` — the diagnostics are keyed `_unparseable_<session>_<agent>.json`,
never by claim or phase, so the "go and look" instruction this paragraph gives is still not
filterable by an orchestrator. The cap made that population smaller, not navigable.
