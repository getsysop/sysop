<!-- sysop:model-roles inline=reasoning -->

# Resolving the plan-review preference (shared protocol)

Read by `/claim-task` Step 6. The question it answers is **how much the human wants to be
in the loop on this claim** — and it is resolved *before* any agent spawns, not after.

The reason is not convenience. Planning plus adversarial review takes 5–25 minutes. Asking
afterwards asks someone who may have walked away, so "the human didn't really review it"
starts happening by degradation rather than by choice. Front-loading makes it a declared
decision that is always answerable.

---

## A. Resolution order

Three tiers, highest precedence first. Stop at the first that resolves.

1. **`--review-plan` / `--no-review-plan`** on the invocation — the per-run override.
   Always wins. `--review-plan` → option **A**; `--no-review-plan` → option **B**.
2. **`<project>/CLAUDE.md § Plan review`** — the consumer's durable default. Same
   "consumer declares its shape" pattern as `§ Merge policy` and `§ Pre-merge
   verification`. Read the first non-empty line under the header and match it
   case-insensitively against `always` (→ A), `never` (→ B), or `ask` (→ tier 3).
3. **Ask** — an `AskUserQuestion` with the two options below. This is the fallback when
   nothing is configured, which is also the case where a newcomer most benefits from
   being asked.

**Never prompt when tier 1 or tier 2 resolves.** `/claim-task <CLAIM_ID>` on a configured
project must stay a single command.

**If the section is present but its value is unrecognised, ask — do not guess.** Print what
you found and what shape was expected, then fall through to tier 3. An unrecognised value
is a consumer who tried to configure this and got the spelling wrong; silently picking a
default is how their intent gets lost. (An *absent* section is not an error — that is the
ordinary tier-3 case.)

Print the resolved option once, plainly, before spawning anything, and say which tier
produced it — so the human can see whether their config was actually read:

```
Plan review: A (review the plan before implementing)   (source: CLAUDE.md § Plan review)
Plan review: B (run it)                                (source: --no-review-plan)
Plan review: A (review the plan before implementing)   (source: asked)
```

## B. The two options

| Option | Flow | For |
|---|---|---|
| **A — review the plan first** | planner → reviewer → **human gate** → executor | Work you want to eyeball before it lands. |
| **B — run it** | planner → reviewer → executor | Mechanical or well-specified work; walk away. |

**The reviewer runs on both.** Only the gate differs. This is worth stating because the
tempting simplification — collapse reviewer and executor on the unattended path, since
nobody is waiting — gives the run *nobody is watching* the weaker review property.
`_shared/adversarial-review.md` already records collapsed self-classification as a known
compromise; the autonomous path needs more fresh-eyes rigour, not less.

**A third option, plan-only, is specified but not built** (`tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md`
§ *The three options*, option C — a maintainer-side design doc that is not in the public tree;
its content is summarised here so nothing depends on reaching it: stop after review, write the
reviewed plan back to the task body, release the claim). It needs a `## Plan` body section
`tasks/schema.md` does not define
and a release ordering the skill does not carry. **Say so if a human asks for it rather than
improvising it or silently running option B** — a missing branch nobody wrote down is how
`/claim-task` Steps 7–8 acquired roadmap-only vocabulary in Phase 29, which is the defect
upstream #220 reported.

## C. Guided mode

Guided mode's behavioural overlay is a set of per-skill decision gates for newer builders,
and this preference is exactly such a gate. When guided mode is active it pins the preference
to **A**. (The full design lives in `tools/GUIDED_MODE_SPEC.md`, a maintainer-side doc that is
not in the public tree — the sentence above is the whole contract this file needs.)

**It overrides tier 2, never tier 1.** A human's explicit `--no-review-plan` on a single
invocation still wins — guided mode raises the floor for the unconfigured case; it does not
take the wheel away from someone who reached for it.

## D. The `askUserQuestionTimeout` hazard — a known bad interaction, stated because it
cannot be mechanised

`askUserQuestionTimeout` is a Claude Code setting (`60s` / `5m` / `10m`, **off by default**).
Where it is set, a question left idle closes on its own: it **submits any options the human
had already selected** and tells Claude the human may be away, so Claude proceeds on its own
judgment.

That is precisely the degradation this file's front-loading argument exists to prevent, and
it lands hardest at tier 3 — the ask reached by a consumer who has configured nothing. An
auto-close there has the orchestrator pick an *interaction mode* by itself, and the plausible
autonomous pick is B: run it unattended, land a commit, no human ever in the loop.

**The rule is therefore: treat an auto-closed question as a park, never as an answer — and
it is implementable, because the harness tells you.** The same documented sentence that
describes the hazard also supplies the signal: the dialog "submits any options you'd already
selected **and tells Claude you may be away from your keyboard**, so Claude proceeds on its
own judgment and can re-ask later."

So on any `AskUserQuestion` result that carries an away-from-keyboard / no-response-received
signal alongside its answer, **do not treat the answer as a decision**, even when it names a
real option — a pre-highlighted option really is submitted, so the selection can look
entirely ordinary and the away signal is the only thing separating it from a choice. Stop,
say that the question timed out and no human answered it, and leave the claim unstarted.

**Key on the meaning, not on a literal string.** The exact phrasing the harness injects is
not part of the documented interface — only the fact that Claude is told. A guard matching a
specific sentence would break silently the first time that wording changes, in the direction
that starts unattended implementation runs.

**Two honest limits.** This is prose an agent follows, so it holds only as well as the agent
following it — and it is read at Step 6, potentially hundreds of tool calls before it fires.
And it is a *detection*, not a lock: nothing in the harness prevents an agent from reading
the away signal and proceeding anyway.

**Which is why the durable fix stays consumer config.** Tier 3 is the only tier exposed to
this at all. A consumer who sets `askUserQuestionTimeout` should also set
`<project>/CLAUDE.md § Plan review`, which skips the ask entirely and removes the question
rather than relying on anyone to read it correctly.

Say this to the human when you fall through to tier 3 on a project with no section — one
line, once:

```
note: no CLAUDE.md § Plan review section, so I'm asking. If you use
      askUserQuestionTimeout, set that section instead — I can tell an auto-closed
      question from a real answer and will treat it as a stop, but configuring the
      section removes the question entirely, and this one chooses whether a human
      sees the plan.
```

---

**Why this lives in `CLAUDE.md` rather than a skill edit.** Shipped skills take the standard
overwrite on every update, with no silent prompt-forks (`WORKFLOW.md` § 8.2c), so a consumer
cannot durably configure this by editing `/claim-task`. `CLAUDE.md` is the sanctioned durable
home for consumer-side skill configuration, exactly as it is for `§ Merge policy`.
