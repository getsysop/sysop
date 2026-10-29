   - **First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

      ```bash
      python3 sysop/scripts/close_arms.py loaded "<close-id>" 2b-twin-spawn ccb3252a38b3d00f "<skill directory>"
      ```

      It prints `LOADED: 2b-twin-spawn`. **Exit 2**: stop and show its stderr.

   Spawn one Agent per surviving target, with the same `subagent_type: "general-purpose"`, `model: "opus"`, `effort: "high"` <!-- sysop:role=security-gate --> (the **security-gate** role), the same `isolation: "worktree"`, **the same step-3 placement — its own pinned checkout at the target's commit and its own scratch directory, both made by `review_pins.py add` before the spawn, with the `## Where you are` block and its echo carried verbatim** — and `description: "Security check: <target>"`. The prompt is step 3's, with four substitutions and nothing else changed:

   > **The placement is not optional here either, and this fleet is the easier one to forget.** Step 3's checkouts belong to step 3's agents; these are different agents and need their own, for the same reason step 3 gives one to each lens rather than sharing. A security lens spawned with `isolation` alone reads the default branch — so it reviews a tree with none of the target's new endpoints, handlers or dependencies in it, returns no violations, and its `VERDICT` is carried into step 4 as a clean security gate that can *block* a close but in this state can never raise one. `_shared/adversarial-review.md` § *Running more than one reviewer* governs both fleets; the assertion below counts pinned checkouts from both.

   - the opening line names the security map as the taxonomy: *"Review the diff below for violations of the project's security conventions — the OWASP-category rules in the security map."*
   - `## Project conventions` becomes `## Security map`, carrying the copy (its text, or its `COPY:` path) under the same missing-or-empty STOP rule, then: *"Left out of this copy because every glob in their headings misses this diff: <each `OMITTED:` heading, or none>. The whole map is at <the `FULL:` path>; read a left-out section there if this diff reaches its subject anyway."*
   - the routing example lines become security-shaped (`api/routes/*.py → A01 Broken Access Control`, `<upload handler> → A03 Injection + A08 Data Integrity`), and the `ROUTING:` block reports `<file path> → <map section> (<OWASP categories>)`.
   - the violation line becomes `- <rule> (<map section> › <OWASP category>) — <file>:<line> — <one-line explanation>`.

   Everything else is carried verbatim, and the two that matter most are the do-not-mutate rule and the do-not-create-files rule: this agent has the same tools and the same measured failure modes as step 3's.

   **It carries the same `VERDICT: BLOCKED` authority, and that is an escalation stated rather than slipped in.** A security lens can now stop a close. The alternative — advisory only — was considered and refused: a gate that reports a routed security violation and merges anyway is the state this entry was filed about, one report louder. Step 4 already treats *any* `BLOCKED` as a stop, so no new disposition is needed; what is new is which agents can raise one.
