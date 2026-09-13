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
- **Jun–Jul 2026** — Test suite built out (900+ tests by mid-July, past 1,800 by the end of it), the evidence dataset is mined and
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
- **Aug 2026** — A sustained defect sweep, sequenced by who meets the problem first: the loop
  surface a newcomer sees in their first hour, then the close path, then the batch machinery
  underneath both. The install path was certified by running it from a cold clone rather
  than assumed to work, and the month ended with the suite past 4,900 tests. The pattern worth reporting is the one that
  held throughout: six phases in this stretch built a mechanism, had their own review round
  reject it, and shipped the round's record instead of the mechanism — one of them shipping
  nothing else at all. A review gate strong enough to reject the work of the person running it,
  with the rejection written down, is the thing the rest of this is trying to buy.
- **Sep 2026** — Two findings about things that had been assumed rather than checked. The
  claim path turned out not to survive concurrent use: two sessions claiming at the same
  moment share one checkout, so the second one's rewrite of the shared tracker quietly
  includes the first one's uncommitted edit, and whichever commits first commits both. The
  other run then has nothing to commit, fails, and reports that nothing was claimed — over a
  status change that had in fact just landed. In 97 of 100 trials a harness ran; three got
  through, which is the part worth stating, because an intermittent failure is the kind a
  team argues about rather than fixes. Worktree isolation had been quietly read as isolation of the whole operation, on this
  project's own documentation pages included. Claims and closes now take a lock before they
  touch the tracker, and a lock left behind by a killed process is refused rather than broken:
  a claim's critical section contains a network fetch, so a live holder and a dead one look
  alike, and breaking it blind would restore the bug. Two members of the same class were known and
  unfixed when that was written. One of them — the task queue's own index — was closed within the
  month, by moving the write into a script and giving that script the tracker lock the batch writers
  already used — it had held its own per-task claim lock all along, but took no part in that one; the
  first write-up had
  guessed it would need a design of its own, and it did not. The other is still open and still
  written down. Separately, the publication path's last unread surface was closed —
  every other gate here read a file tree or a path, and the one that read a commit read only
  its author and committer addresses, so nothing had ever read a commit *message*,
  while a squash-merge folds a pull request's title and body into a public commit that a
  force-push cannot take back. The rest of the month ran the same instinct over directories
  rather than files. A workspace already sitting at the path a claim wanted was adopted on the
  strength of being a directory — but it can just as easily belong to a second checkout of the
  same project, and adopting that one wires two sessions into a single tree while the lock
  records a workspace nobody is building in. Identity is now established before adoption: that
  the directory is this repository's, that it is on the branch the lock claims, and, for a
  cloned workspace, that its origin is the same repository. It had to reach the second of the two scripts
  that build workspaces twice over, because both reports named only the first: the fixing phase caught
  the identity half itself by asking whether the class was wider than its brief, and a phase later a
  review round caught the branch half. Later in the month the same instinct turned on the project's own
  documented advice. A rollback step was restoring a file the wrong way: it restored from what had
  been staged rather than from the last commit, so a rollback over an already-staged change
  reported success and changed nothing. The obvious repair was the form the project's own workflow
  spec already recommended — and running it showed why that form was worse. Where the staged change
  belongs to a second session, it throws that work away; measured, one session's rollback silently
  reset another session's claimed task back to unclaimed, exiting successfully and printing
  nothing. What ships instead checks the outcome rather than choosing between the two forms. The
  postscript is the part worth keeping: one phase later, checking something by hand, the same
  mistake was made again — a file restored the first way, discarding work that had not been
  committed — by the session that had read the warning written down the day before. The other
  thread of the month was a class of files with predictable temporary names, where a writer that
  saves by writing alongside its target and renaming collides with any second writer doing the
  same; nine of those were found and converted. The instrument that certified that sweep complete
  turned out to be reading about nine-tenths of the lines it reported reading, and it was not
  review that found it — review had read it closely more than once — but a probe that measured its
  reach.
  Later in the month, a question the queue had never been asked got an answer: what to do with the
  thing you notice while working on something else. It is now three tiers — fix it in the branch
  under stated conditions, extend an open task, or file a new one — with a never-list that is
  mostly an ordinary enumeration and ends in one member written as a property of the change
  instead, because an enumeration rots: any edit that would weaken or remove a check is excluded
  at every size, whatever file it lives in. A tier-1 fix is declared in the task body and checked against the
  branch's own diff at close; a filing has to name what it blocks, and everything that does not
  goes to a flat notes file that nothing routes off. Alongside it, three fixes to the same
  confusion in three different places: a narration handed to review is now stamped with the
  revision it was written against, so a branch that kept moving is caught rather than merged on a
  stale account of itself; the recovery paths around that step, three of which had been
  documented as remedies and were destroying the records they existed to protect, were each fixed
  differently — one prescription deleted outright, one step rewritten to undo itself by restoring
  what it displaced, and the rollback given the population it had been missing plus a refusal to
  remove a last remaining copy; and the installer stopped reading "I could not open the
  lock" as "there is no lock", which had been quietly resetting the two dates that file exists to
  keep. Then the review round turned on itself. An isolated reviewer is created from the
  default branch, not from the commit being reviewed, so on any unmerged branch every lens had been
  reading the tree as it was before the change — finding nothing, which looks exactly like finding
  nothing wrong. The remedy had been written down for a month and was skipped anyway across four
  consecutive phases, so what shipped was not a third copy of the rule but a place to stand: the
  requirement moved into the text read at the moment an agent is spawned, and each round now has to
  record, in a file a test reads, which commit its reviewers actually stood on.

Where to go next: [the monograph](./workflow.html) for why it's built this way,
[one rule, end to end](./one-rule.md) for the evidence trail behind a single rule, and
[`PHASE_LOG.md`](../PHASE_LOG.md) when you want the unabridged log.
