# How Sysop got here

The short version, for someone who just found this repo. The full per-phase narrative — every
decision, in order, with its reasoning — is [`PHASE_LOG.md`](../PHASE_LOG.md); fair warning
that it's a working log written for the project's own continuity, not an introduction.

- **Feb 2026** — A solo builder shipping a production FastAPI + Next.js app (GDP Query System)
  with an AI agent starts running structured review rounds: every batch of work gets a quality
  pass and a security pass before merge. Round 1 lands 2026-02-23. The same defects keep
  reappearing in new code.
- **Mar 2026** — The recurring findings become written conventions with a promotion rule (recur
  across rounds → get promoted), a convention map the agent consults on every task, and an
  11-pattern pre-commit hook. By mid-March the map holds ~65 conventions.
- **Mar–Apr 2026** — The mechanically checkable conventions stop being prose: a shared grep
  check registry (2026-03-20), then Semgrep AST rules where grep proved too noisy (April).
  [One rule, end to end](./one-rule.md) traces a single convention through exactly this arc.
- **2026-04-30** — The workflow is extracted into its own repository, keeping the file history
  that records where each rule came from.
- **May 2026** — A second private project installs it. Real consumer friction drives the
  installer, updater, and permission machinery through dozens of fixes.
- **Jun–Jul 2026** — Test suite built out (750+ tests), the evidence dataset is mined and
  published with its limits stated, and the project is renamed twice (wade-flow → jig → sysop)
  after name collisions.
- **2026-07-13** — Public cut as [getsysop/sysop](https://github.com/getsysop/sysop), MIT.
  71 review rounds and 3,298 findings behind it; 78 promoted conventions shipping as packs.
- **Jul 2026** — Cold-read exercises (fresh-context model readers simulating first-time
  adopters) consistently name adoption weight as the reason to pass,
  so the convention loop becomes separately installable: `--mode loop`, the smallest install
  ([loop mode](./loop-mode.md)). Before shipping, it was run end-to-end against a real
  ~60k-line open-source codebase — the loop closed on code the model didn't write, and a
  freshly mechanized convention caught an instance no review round had filed.

Where to go next: [the monograph](./workflow.html) for why it's built this way,
[one rule, end to end](./one-rule.md) for the evidence trail behind a single rule, and
[`PHASE_LOG.md`](../PHASE_LOG.md) when you want the unabridged log.
