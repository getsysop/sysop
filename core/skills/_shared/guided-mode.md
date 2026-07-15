# Guided Mode — Decision-Gate Protocol

Canonical protocol for **guided (teaching) mode**: a behavioral overlay for builders who are growing into the review judgment this workflow assumes. It governs how a skill behaves at the points where it would halt and ask the human to approve, choose, or promote something. Maintain the protocol in one place — this file.

**Inert until activated.** This partial changes nothing on its own. A consumer opts in by adding the `## Guided mode` activation stanza to their `CLAUDE.md` (project-level, or user-level `~/.claude/CLAUDE.md` to make it follow them across projects) — its presence is the toggle; removing it returns to default (senior-operator) behavior. The stanza is always-loaded context, so skills honor the protocol below at top-level decision points without a per-skill reference. (Gates that run inside a cold-context sub-agent — e.g. `/claim-task`'s reviewer-executor — reach full fidelity once a later phase wires each decision-gate skill to cite this file directly; that per-skill wiring is a deferred build.)

---

## The premise

The default workflow assumes you can read a diff and judge it. Guided mode does **not** lower that bar — it works to *shrink and de-risk* the set of calls that actually reach you, and to explain the ones that remain in terms you can own. It never fakes your competence; for each call, it first decides whether the call is even yours to make.

This is the same boundary `/intake` already draws for planning — *argue the decomposition, but never adjudicate whether the venture is worth building* — generalized from the plan to every decision gate.

## When it applies

At every point a skill would halt and ask the human to decide — **plan approval** (`/claim-task`), the **manual-smoke gate** and **stuck-PR halt** (`/review-close`), **convention promotion** (`/codebase-review`, `/security-audit`), and any **`AskUserQuestion`** a skill raises — do all of the following *before* asking anything:

1. **State the decision plainly.** No jargon as a load-bearing word. If a term is unavoidable (`migration`, `auth`, `race condition`), define it in one clause the first time. Say what is actually being decided and what changes downstream if it goes one way versus the other.

2. **Adversarially review your own recommendation.** Apply the same primitive this workflow applies to plans (`_shared/adversarial-review.md`) — but point it at the choice you are about to recommend. Try to refute your own pick. Ask what breaks if you are wrong.

3. **Triage the decision into one of three kinds, and route it:**

   - **A — a genuine tradeoff I can own** (speed vs. safety, scope, which of two acceptable behaviors to build) → present it. Give the honest pros and cons of *each* option, name your recommendation and why, and let me pick. **This is the only case where a balanced pros/cons ledger is the correct output.**

   - **B — a false choice** (one option is simply wrong: a security hole, a data-loss path, a broken invariant) → do **not** present it as a choice. Collapse to the correct answer, do it, and tell me in one line what you protected against and why the other option was never real. Never manufacture pros for the wrong option to fill the ledger.

   - **C — a real tradeoff I can't weigh** (the risk only makes sense if you understand the system's internals) → don't ask. Take the conservative default, do it, and record what you chose and why in the task body. Surface it to me as *information*, not a question.

## The load-bearing rule

You are allowed — and required — to conclude **"this isn't your call."** Do not present a security or data-loss risk as a 50/50 with tidy bullet points on both sides. A balanced ledger on a decision that has a right answer is not diligence; it is **diligence theater**, and it is more dangerous than not asking, because it launders a wrong answer through a process that looks rigorous. When you are unsure which of the three kinds a decision is, treat it as a false choice or an un-weighable one — default to the safe path and explain it — never as a tradeoff to hand me.

## What does not change

The deterministic gates still gate. Pre-commit checks, blocking conventions, worktree isolation, and the security map run exactly as they do in default mode. Guided mode governs only the **human** decision points — it never softens a blocking check into an advisory one. If a gate says no, the answer is no; the plain-language explanation is for understanding, not negotiation.
