# Changelog

What each published snapshot of Sysop changed, newest first. The public repository advances in
squash snapshots rather than granular commits (README § Provenance), so this file is the readable
record of a snapshot: user-facing changes only — behaviour a consumer sees, a page a reader uses,
a check that now runs. Each entry is dated by the snapshot's publication and names the span of
private development phases it carries. The per-phase journal those phases were recorded in is the
maintainer's working record and is not in the public tree.

## 2026-11-05 — v0.2.4, private phases 464–468

- **`v0.2.4`.** This snapshot is tagged `v0.2.4`, with a GitHub Release carrying this entry.
  The next bullet is an instruction; the rest are what changed, each a fix to shipped behaviour or
  to a page that said something the code does not do. `--ref` pins to it as it does to the earlier
  tags, once the tag is fetched into your clone.
- **Run `install.sh --update` when the plugin updates to this snapshot.** Most of the fixes below
  are in `install.sh`, the `pre-merge-commit` skeleton and its example, and scripts under
  `sysop/scripts/`. The plugin delivers the skills; only the bash installer's `--update` (or
  `sysop/scripts/sysop-update.sh`) delivers the rest, so until you run it those fixes do not reach
  you. One fix changes a skill's text with its script: Step 2b's new text runs with the previous
  `convention_size.py`, which measures as it did before, fenced headings included.
- **Three pages stop contradicting the code.** The README said no release tag existed, so a
  `--ref` pin meant a commit SHA; `v0.2.0` through `v0.2.3` are tagged, and `SECURITY.md` lists
  them. The README's deterministic-enforcement bullet now says who demotes a stale rule:
  `/codebase-review` brings it to you from the review rounds' false-positive ledger, and no script
  does it. `docs/history.md` called the source project's 78 promoted conventions "shipping as
  packs", but 78 is what that project promoted, and the packs were mined from it. The repo layout
  in `docs/install-and-update.md` counted the postgres pack's Semgrep rules as 2; it ships 3, two
  of them in one file.
- **`validate_tasks.py` runs in CI.** Its in-progress lock check reads `sysop/runtime/locks/`,
  which is runtime state and never committed, so in CI every in-progress task failed and there
  was no way to turn the check off. `--skip-lock-checks` turns off that check, Invariant 9, and
  nothing else. Every run that passes it prints a line saying lock state was not read, `--quiet`
  included, and the exit code is unchanged. Don't pass it locally or in the pre-commit hook,
  where the locks exist. The validator also now warns about a `completed_date` on an open,
  in-progress or deferred task, which nothing reads, and names an unquoted date on a done task
  instead of calling it missing. `tasks/schema.md` now says what the validator does: a done task
  without a date gets a warning, not an error.
- **A model-role check that skipped something says so in the update's output.** The check and
  the rewrite under `--update` both skip a file they cannot read, such as a non-UTF-8 note of
  your own under `.claude/skills/`. Both reported the skip when run by hand, and the installer
  then dropped the report, so a passing update said nothing about it. They also missed a folder
  they could not open: its files were dropped without a word. And on Python 3.13 and older, a
  folder that could be listed but not entered crashed the check, which the installer reported as
  an invalid mapping. Now an unreadable file or folder is counted, a folder as a folder, and
  the update prints a warning naming it and writes the count into its summary.
- **`run_checks` warns about a `severity` it does not know.** A value outside `low`, `medium`,
  `high` and `critical` used to appear in the report as typed, with nothing to say it was a
  typo. Each such check now draws one `warn:` line on stderr per run, naming it and the value. The run
  is otherwise unchanged, so a private severity word in your own overlay keeps working. Case is
  ignored, and a check with no `severity` is still `medium`.
- **`/review-close` measures your `CLAUDE.md` convention sections correctly.** Step 2b measures
  the sections to choose between pasting them into every reviewer prompt and writing them once.
  The measurement read a `## ` line inside a fenced example as a heading, so a fenced heading
  inside a real section cut it short, which could put a large section on the paste arm, and a
  heading quoted only in an example counted as the section. It also measured only the first of two
  same-named sections, scored a heading with a trailing space as 0, and did not end a section at
  a following `# ` heading. All five are fixed, with the fence and HTML-comment reader the
  security cut beside it already uses, and the heading forms CommonMark allows (two spaces after
  `##`, a closing `##`) now count. A fence that never closes is reported, and so is a section name
  found only inside a fence, which is how a forgotten closer above a real section looks. A file
  without these shapes measures as before.
- **`--update` no longer calls your own layer files' output a local edit.** Its pre-overwrite
  check warned "committed local edits in managed paths … consumer-added content will be lost" in
  three cases where nothing was lost: on the first update after you added a role override to
  `.claude/served_models.local.yml`, which listed the skills the override moves; on every update
  after a `.project.*` overlay had been applied, which listed the base map; and on every update
  with a `.claude/substitutions.project.yml`, which listed `checks.yml`. The check now rebuilds
  the previous install with your layer files, both as they stand and as they were committed when
  each path was last written. Content they produced matches, and a hand edit is still reported.
  Two cases still warn once: the first update with a layer file you have not committed (commit
  it before you run the update), and the first update after a promotion was written into a base
  map and its overlay. The check also now finds your edits when the install target is a
  subdirectory of its repository. Before, it read the repository root's files instead of the
  target's.
- **The `pre-merge-commit` skeleton's pytest block, and its worked example, run the main
  checkout's venv.** Both looked for `.venv` at `git rev-parse --show-toplevel`. In a linked
  worktree that holds the protected branch, that is the worktree, which has no `.venv`, so pytest
  ran on whatever `python3` was first on `PATH`, and a failing suite could pass. From a linked
  worktree, both now find the main checkout through `git rev-parse --git-common-dir`, then this
  checkout's own `.venv`, then `python3`. The example also no longer exits on macOS's bash 3.2
  when there is no `.env`: under `set -e`, a `source` of a missing file ended the hook even with
  `|| true`.

## 2026-11-02 — v0.2.3, private phases 458–463

- **`v0.2.3`.** This snapshot is tagged `v0.2.3`, with a GitHub Release carrying this entry.
  The next bullet is an instruction; every change after it fixes a defect in shipped behaviour.
  `--ref` pins to it as it does to the earlier tags, once the tag is fetched into your clone.
- **Run `install.sh --update` when the plugin updates to this snapshot.** The fixes below are in
  scripts under `sysop/scripts/`, and some change a skill's text with them. The plugin delivers
  the skills; only the bash installer's `--update` (or `sysop/scripts/sysop-update.sh`) delivers
  the scripts, so until you run it the fixes do not reach you. A newer skill over an older script
  can also fail without saying so: the unattended hold and stop below, run against the previous
  `close_run.py`, exit 0 and record the reason as `-`.
- **An unattended `/review-close` records a hold or a stop whose reason quotes code.** Its
  prepare held a branch the convention gate blocked, and its night recorded a durable park, by
  passing the reason inside double quotes to `close_run.py hold` and `stop`. The gate's text
  usually carries backticked identifiers: under `--permission-mode dontAsk` the hold was
  measured denied, and the stop's same shape falls to the same rule, so the hold or the
  `STOPPED` marker was never written, and any other mode ran the backticks as
  a command. Both now pass the reason on stdin through a quoted heredoc (`close_run.py hold
  <run-id> <branch> - <<'SYSOP_REASON_EOF'`), measured admitted under `dontAsk`, and the text is
  recorded intact, on one line. Step 8 now names `close_run.py unhold <branch>` and leaves its note to you.
- **`/review-close` no longer removes a worktree that has moved to another branch.** Step 3b
  took a lock's recorded workspace whenever the directory existed. A worktree since switched to
  another branch was then treated as this branch's, and Step 3b preserved, collected from and
  removed it; a leftover plain directory stopped the close at the collect. A lock's workspace now
  counts only when it is still the branch's checkout: a worktree standing on the branch, or a
  clone that still holds the branch (a finished clone back on the default branch still counts).
  The main checkout of a `--branch` claim is still recognised; otherwise the sibling search runs
  as if the lock named none.
- **`close_run.py re-request` waits for GitHub to see your push.** Run straight after the push,
  it refused because GitHub still reported the old PR head. It now re-reads the PR, 6 times
  5 seconds apart by default (`SYSOP_PR_HEAD_WAIT_TRIES`, `SYSOP_PR_HEAD_WAIT_SECONDS`), while
  GitHub's head is an older commit of your branch; anything else still refuses at once.
  `hand-off` waits the same way when it reuses an existing PR.
- **`close_run.py re-request` no longer asks the second reader twice after a failed hand-off
  request.** When the hand-off's request failed in a way that may have posted the comment anyway
  (a timeout, a reply with no id), a retry posted it again. It now takes an identical comment
  posted since the hand-off opened as that request, as long as the branch has not moved since.
- **The ignored-file check stops flagging tool caches and comments.** `ignored_refs.py` (Step 2a
  step 3a, `/claim-task`, `/auto-build`) no longer reports a file under a cache or build-output
  directory (`.pytest_cache/`, `__pycache__/`, `node_modules/`, `dist/`, `build/` and the rest of
  the list the copy already skips), nor a reference on a line that is only a comment. An ignored
  file your code reads from under, say, `build/` is no longer reported: keep such data elsewhere.
- **A close, `clear_user_action.py` and `backfill_completed_dates.py` no longer lose a concurrent
  claim.** Each rewrote `tasks/index.yml` without the tracker write mutex the claim path takes,
  so a claim committed between one's read and its write was undone, with every command reporting
  success. All three now take the mutex: `/review-close` Step 4c from its read until the rewrite
  is staged, `clear_user_action.py` from its read to its write, and `backfill_completed_dates.py`
  after its history scan, refusing, having written nothing, if the index changed while it
  scanned. A writer that waits past `SYSOP_TRACKER_LOCK_WAIT` (120 seconds by default) refuses
  and changes nothing.
- **The closed-task check names a re-added body the target has since deferred.** A branch that
  adds `tasks/open/T-5.md` and replays after the target moved that task to `tasks/deferred/`
  rebased cleanly and left two live bodies for one task. `/review-close` Step 4a and the push
  guard's closed-task check now print a `CLOSED TASK RE-ADDED:` line for it (`deferred it at`, or
  `undeferred it at` for the reverse move) and route it as they route a re-added closed body.
- **`/review-close` Step 2e stops reporting `/claim-task`'s files absent on every `/auto-build`
  close.** The claim-artifact report judged each run against `/claim-task`'s five files, so an
  `/auto-build` cycle always listed `planner-integrity.md`, `review.md` and `outcome.md` absent.
  A cycle is now judged against the three files `/auto-build` writes (`plan.md`,
  `classification.md`, `revised-plan.md`); a `/claim-task` run reads as before.
- **`close_batch.sh` no longer closes a batch you did not type.** A batch number too long for the
  shell's arithmetic wrapped silently: `18446744073709551623` closed and committed Batch 7. A
  number of more than 18 digits, after leading zeros, is now refused before anything is written,
  and `batch_work.sh` refuses the same lengths, so it never claims a batch `close_batch.sh` cannot
  close.
- **A batch claim interrupted during its commit is no longer resumed as if it had landed.** A
  Ctrl-C or hang-up while `batch_work.sh`'s claim commit ran left the batch `In Progress` on disk
  and uncommitted; a re-run "resumed" at exit 0 and never committed it. The re-run now refuses
  and prints the two ways out, which work from any directory: commit the flip to keep the claim,
  or restore the file and `--release`.
- **`batch_work.sh --release` no longer removes a worktree it did not create.** It removed
  whatever worktree held the batch branch. It now removes one only at the batch's advertised path
  or the lock's recorded workspace; anywhere else needs `--force`. A registration whose directory
  is gone is still cleared without it.
- **`batch_work.sh` and `close_batch.sh` refuse a symlinked `review_tasks.md`** instead of
  replacing the link with a regular file and committing it while the real file kept its old
  status. A `close_batch.sh --dry-run` still reads through the link.
- **`batch_work.sh 007` claims batch 7**, as `close_batch.sh 007` already closed it; it read
  "not found" before. `claim_task.sh`'s pointer from a batch id to `batch_work.sh` no longer
  turns a long number into a different batch.
- **`claim_task.sh --clone` refuses a dangling symlink or a file at the clone path before it
  pushes.** It published the branch to `origin` and then failed in `git clone`. Its refusals now
  say to remove the path or set `WORKTREE_ROOT` / `WORKTREE_PREFIX`; another branch name lands on
  the same path.

## 2026-11-01 — v0.2.2, private phases 451–457

- **`v0.2.2`.** This snapshot is tagged `v0.2.2`, with a GitHub Release carrying this entry.
  Every other change in this entry fixes a defect in shipped behaviour. `--ref` pins to it as it
  does to the earlier tags, once the tag is fetched into your clone.
- **`/review-close` no longer deletes an ignored directory only a worktree holds.** Before
  removing a worktree, Step 3b copies the ignored files only it holds, but a directory ignored as a
  whole (`evals/runs/`) was never read: the copy reported `0 preserved` and the removal deleted
  the only copy. Such a directory now holds the close: `ignored_refs.py --preserve` prints
  `HELD: <dir> (<n> files, <b> bytes)` and exits 4, and the branch is skipped with its worktree
  intact until you move or delete the directory. Caches and build output (`__pycache__`,
  `node_modules`, `.venv`, `venv`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.hypothesis`,
  `.tox`, `.nox`, `.next`, `.nuxt`, `.turbo`, `.cache`, `.gradle`, `.dart_tool`, `dist`, `build`,
  `out`, `target`, `coverage`, `htmlcov`, `*.egg-info`) are never held, so keep data you need out
  of directories with those names; nor is a directory whose files the main checkout already has.
  A directory the copy cannot read stops the close instead.
- **`/auto-fix` and `/auto-judge` no longer run a review title as a command.** Their commits
  put the batch title, and `/auto-fix`'s verify step its own note, inside `git commit -m "…"`,
  where a backtick or `$(…)` is command substitution: a title quoting an identifier in backticks
  lost it from the commit subject, and a title naming a command ran it. Each message is now
  passed through a quoted heredoc (`git commit -F - <<'SYSOP_COMMIT_MSG_EOF'`), which keeps
  the text as written.
  A consumer that allows `Bash(git commit:*)` needs no new rule.
- **`/review-close` Step 3c no longer passes the manual-smoke gate when a branch's recorded
  workspace cannot read it.** A lock kept after its worktree was removed sent the gate's reads of
  the branch tip into a missing directory. Those reads failed, and so did both warnings meant to
  report them, so a `manual_smoke: true` or a smoke procedure set only on the branch read
  `NO_SMOKE_REQUIRED` with nothing printed. A leftover directory that is not a checkout, an
  unrelated repository and a clone whose branch was deleted did the same. Such a workspace is now
  skipped, as is a sibling clone left on an older commit of the branch, and the branch is read
  from the main repository instead.
- **A close stops before a replayed branch puts a closed task's body back.** A branch that added
  a task's body, replayed after a squash of it landed and a later close archived it, re-added a
  stale `tasks/open/<ID>.md` beside the archived copy with no conflict. `pr_head_check.py` now
  prints `CLOSED TASK RE-ADDED:` for it, and `/review-close` Step 4a stops on it under
  `--headless` and skips the branch when attended. `git_check.py closed-tasks` reports it at the
  `direct` push too. Not yet on one route: a published branch merged past a recorded PR head
  still merges from its fork point, which the check does not read. The closed-task check also reads a body's close by its file name before
  git's rename pairing, which missed a close that edited the body beside a near-copy filed as a
  new task.
- **`git_ro.py` runs no program your git config names.** The read-only wrapper that
  `/review-close`'s reviewers and Step 1a read worktrees through refused `--ext-diff` and
  `--textconv` as arguments, but git ran a program named in config without either:
  `core.fsmonitor`, a filter's `clean` or `process`, `diff.external`, a diff driver's `command`
  or `textconv` (whose `cachetextconv` writes a notes ref), and the signature program when
  `log.showSignature` is set. A submodule's own config and a partial clone's on-demand fetch
  could run programs too. These are now turned off for every read; `status -v`, `--submodule` and
  `--ignore-submodules` are refused, and a read of an object a partial clone lacks fails rather
  than fetching it. A worktree file under a clean filter such as LFS is compared unfiltered, so
  one whose stat is stale can read as modified, and a submodule's uncommitted changes are not
  reported. Separately, `git_ro.py diff` no longer misses an edit made in the
  same second its index was written and the same size as the original.

## 2026-10-31 — v0.2.1, private phases 444–450

- **`v0.2.1`.** This snapshot is tagged `v0.2.1`, with a GitHub Release carrying this entry.
  Every other change in this entry fixes a defect in shipped behaviour. `--ref` pins to it as it
  does to `v0.2.0`, once the tag is fetched into your clone.
- **A pending doc whose hold was cleared can be consumed.** `pending_doc_hold.py clear` removes a
  doc's `hold:` and keeps the `held_since:` stamp, and `/review-close` Step 4c item 6 refused any
  stamped doc, so the close after a hold was cleared consolidated the doc and then stopped before
  committing, at every retry. `pending_doc_collect.py consume` now deletes a stamped doc only when
  `pending_doc_hold.py check` routes it, and still refuses one held for its own `hold:`, for an
  outstanding `user_action`, or for sharing a task with a held doc.
- **Two pack semgrep rules now flag the unsafe value, not only a missing keyword.** The python
  pack's `http-client-redirect` passed any `httpx.Client(follow_redirects=...)`, so
  `follow_redirects=True` went unflagged; it now requires `follow_redirects=False`, and flags a
  value held in a name too. The llm pack's `llm-cost-abuse` passed
  `GenerateContentConfig(max_output_tokens=None)`; it now flags `None` as well as a missing
  bound. If you edited your installed copies of either rule, an update replaces them with these.
- **A close stops before it writes a branch's edit into a closed task.** When the merge target
  closed a task (its body moved to `tasks/archive/`) while a branch was editing that body, git
  carried the branch's edit into the closed copy with no conflict. `/review-close` Step 4a now
  names each such body, and each one the target deleted, before it merges: a headless close stops,
  and an attended one shows the diff and asks whether to merge it or skip the branch. Under
  `direct`, the same check runs before the push merges a newer `origin/<default branch>`, where an
  archive move from another clone's close can arrive (`git_check.py closed-tasks`).
- **`validate_tasks.py` refuses a conflict marker in a task body** (Invariant 13). A body resolved
  by hand during a close's rebase could be committed with its markers, because `--continue` runs
  no `pre-commit`; Step 4a now runs the validator first, and it fails on any line starting with
  seven or more `<` or `>` followed by a space or the line's end. Indent a marker a body quotes on purpose.

## 2026-10-30 — v0.2.0, private phases 435–443

- **`v0.2.0`, the first release tag.** This snapshot is tagged `v0.2.0`, with a GitHub Release
  carrying this entry. On the bash path, `--ref` pins to it once the tag is fetched into your
  clone; `SECURITY.md` § *How updates reach you — and how to pin* has the details. Rolling
  `main` stays the default track.
- **A batch claim's worktree reaches the claim commit every time.** The claim read the claim
  commit through a pipe that could close early, and when it did the worktree was left at the
  commit before the claim, with a warning that git could not read it. It now reads the commit
  whole.
- **The close's runner split stops here.** `/review-close`'s runner core is 286,503 bytes, with
  twenty-four step files a close loads only when one is due. Nothing further moves out, and the
  byte budget stays as a guard against the core growing back.
- **A reviewer's scripts start in its own scratch directory.** A spawned reviewer's shell starts in
  the spawner's checkout, under the spawner's credentials, so a fixture path that came out
  wrong once aimed a reviewer's pushes at the real remote; they stopped only at authentication. The adversarial-review procedure now
  has the spawner put four rules in every reviewer's prompt, for its scripts and its git commands:
  begin by changing into the reviewer's private scratch directory, by its literal path, and make no
  git write in its placed checkout, which shares the repository's refs and remotes; check arguments non-empty under `set -u` before any `git -C`, since an empty `-C`
  is the current directory; set `GIT_TERMINAL_PROMPT=0`; and on finding the spawner's checkout
  touched, stop and report, restoring nothing.
- **An update says when it moved Sysop backwards, and a model-role refusal names the right file.**
  When the clone `$SYSOP_SRC` names is checked out older than the installed commit, `--update`
  now says it moved Sysop backwards and how to undo it. When it cannot tell (the clone lacks the
  installed commit, as one from before a re-clone does; the two commits sit on different branches
  or a shallow clone's cut history; or the source is not a git clone), it says so and what to
  check. A refused model-role mapping's `Fix:` line now sends you to
  `.claude/served_models.local.yml`, the file your edit survives in, instead of
  `served_models.yml`, which every update replaces, and prints only the remedies that apply to
  the pins that failed. Its headline no longer claims an override was skipped when you have none
  or that the failing pins are valid; it says Sysop's skills are back at their shipped models
  until the check passes.
- **The pip-audit stage audits the project, not pip-audit.** A bare `pip-audit` audits the
  interpreter it is installed into, so a pip-audit installed as a uv tool, with pipx or by Homebrew
  reported its own packages as the project's and missed the project's real advisories. The stage
  now audits a root `uv.lock` (through `uv export --locked`, with extras and every Python-version
  and platform branch); otherwise each root `requirements*.txt` in its own run together with the
  environment of the interpreter running the checks when it has pip; and it prints which. Where it
  audits less than it set out to (conflicting extras or groups exported without them; a git, URL
  or editable requirement, or a pin pip-audit skips such as a `+cpu` local version; or, with no
  pip in the checks' interpreter, dependencies declared only in `pyproject.toml`) it names what it
  left out and reports the stage `degraded`, not as a clean run. A uv project with no `uv` on `PATH` skips the audit,
  and a stale `uv.lock` fails it; neither falls back to the environment. Reported by an external tester.
- **The pages lead with the problem.** The README and the landing page now open by naming what
  Sysop exists for — one builder producing more code than they can read line by line, with no
  reviewers to add — before the convention loop that makes the approach distinctive; the README
  points at the monograph's preface and the history page from the top, the landing page at the
  preface. The monograph's overview gains a
  short section, *What each part is trusted with*: judgment to a reasoning model, critique to an
  independent agent, mechanical conditions to deterministic tools, risk to the human — where an
  outcome can be checked, the workflow checks it rather than taking an agent's report of it.
  README § Provenance dates the public history's restart and says why. Prompted by an outside
  read of the public pages.

## 2026-10-29 — private phases 433–434, a new repository

- **This repository was deleted and recreated.** The 2026-10-28 reset left `main` at one commit,
  but GitHub keeps every pull request's head ref, and an owner cannot delete those: the 49 merged
  snapshot pull requests still served the old per-phase journal and the retired contact address.
  Deleting the repository is the only owner-side way to retire them, so the history here starts
  again at one commit. Pull request, issue and discussion numbering starts over; the old
  discussions were the maintainer's roadmap posts and were not carried over, and the one open
  issue moved to the maintainer's queue. Install commands, the marketplace slug and
  `getsysop.com` are unchanged; a clone or marketplace copy made before today needs a fresh clone.
- **The skill files no longer cite the maintainer's private record.** Every phase number,
  queue-entry id and name-attributed ruling left the shipped `core/skills/` text (764 of them);
  a reader who followed one found nothing, and a runner never needed it. A test keeps the count at
  zero. `/auto-build`'s own `Phase 6a`–`Phase 7` stage names are unchanged.
- **The `v0.1.0` release and tag are gone.** It dated from 2026-07-15, predated the `sysop/`
  vendor-directory migration, and `install.sh --ref` already refused it; after the history reset it
  was the one tag still pointing at an old snapshot. Pin to a commit SHA, as `SECURITY.md`
  says; a usable release tag comes when there is a checkpoint worth one.

## 2026-10-28 — private phase 432, the reset snapshot

- **The per-phase development journal leaves the public tree.** It had shipped with every
  snapshot since the 2026-07-13 public cut; this file replaces it as the public development
  history, and [`docs/history.md`](./docs/history.md) carries the narrative. The journal named
  the maintainer's rulings, consumer projects and their spend, private tracker numbers and
  operational details that a reader of the repository has no use for.
- **One public contact.** The maintainer address in the plugin manifests, `SECURITY.md`,
  `CODE_OF_CONDUCT.md` and the author of every snapshot commit is `wade@cedarmountainsystems.com`.
  The address it replaces carried a token the leak gate blocks, so the gate's one allowlist
  stage went with it: Pass 1a is a single grep again.
- **README leads with the loop.** The opening now states the distinction the project is built on
  — advice a model is asked to remember versus checks the computer runs — before the lifecycle
  around it; the caveats on the headline figures moved to § Status beside the figures.

## 2026-10-28 — private phases 400–431

- **`/review-close` is about half the size it was in September.** The runner's always-loaded
  core went from 367,128 bytes at the previous snapshot to 287,120: the arms a close rarely takes
  moved into 24 step files under `review-close/steps/`, each loaded only when its trigger fires,
  and the installer and updater deliver them with their digests verified. The split began in the
  previous snapshot (below) and closes here.
- **`/review-close` runs headless.** Under Claude Code's `dontAsk` permission mode the prepare,
  resume and land arms run with no permission denial: every git write is chained after an
  explicit check, read-only git goes through one wrapper, and the rules the install seeds admit
  exactly those calls. The install page's claim that the close's documents were denied headless
  is corrected.
- **`sysop-update.sh --update --mode loop` downgrades a full install** to the loop-only slice
  instead of refusing or re-adding the full set.
- **Claiming and batching, several fixes.** A `--clone` claim checks out its branch, not a
  same-named tag; `batch_work.sh` builds the branch and worktree before it flips a task's status,
  and refuses a claim whose branch is checked out elsewhere; a claimed worktree reads as `ACTIVE`
  rather than `MERGED` so a cleanup pass leaves it alone; `--lock` refuses a review batch.
- **Honest status lines.** A semgrep, pyright or tsc stage that is disabled now reports
  `skipped`, not a pass; a model-role table printed by `--defaults` marks a role whose pins have
  not been applied; two success lines that said less than had happened say what happened.
- **A worktree's own virtualenv goes on `PATH`,** and ESLint discovery skips nested checkouts but
  still reaches `frontend/` and listed submodules.
- **`/sitrep` stops advising removal of a live batch's worktree** when the batch holds no lock.
- **Step 4a's fast-forward refuses a same-named tag,** and a qualified checkout no longer
  detaches.

## 2026-10-21 — private phases 374–399

- **Review sizing by the kind of change.** The adversarial-review governor sets reviewer count by
  what changed — none for a docs-only phase, one execution lens for a one-site fix with tests, two
  for behaviour across sites — and a model role can carry an effort level. The security twin runs
  on the `reasoning` role, with three roles at `high` effort.
- **The role → model → effort table at the front door.** Every install and update that can render
  it ends with the table of which model and effort each role runs at, and which rows are your
  overrides.
- **The `/review-close` split begins.** The installer delivers skill subdirectories; the runner's
  largest always-run heredocs become shipped scripts; Step 4a's conflict recipe, the flag
  sections and Step 4d's arms become step files loaded on demand; a step's arm records a receipt
  of what ran. The always-loaded core went from 579,071 bytes to 367,128 over this span.
- **Step 2b reuses a gate's `APPROVED` verdict** when none of its inputs have moved, and the
  security twin works from a per-target copy of the security map.
- **`--commit-claim` fast-forwards the claim's own worktree** to the claim commit, so a claim's
  worktree no longer reads its task as still open.
- **The nextjs-react pack's `error-display-jsx` grep check is retired;** its Semgrep twin stays.
- **The unattended land is on,** gated by a signed close the GitHub side enforces.

## 2026-10-11 — private phases 347–373

- **The `reasoning` role splits into `planner`, `plan-review` and `executor`,** and every skill
  pins the role it runs under.
- **`/review-close --prepare` and `--resume`,** then `--request-review` and `--land`: the close
  can stop at a review request and be resumed or landed later, by the same session or another.
- **A `--clone` claim brings its commits across;** gitignored files the work reads are checked
  by the resolver's own configuration; a YAML parse that fails in a way other than `YAMLError`
  is still a failure.
- **Squash provenance:** a squash-merged branch's head is recorded as a local ref so the close
  can verify what landed.
- **The Step 3c smoke gate** runs the merged tree, not the branch, and a fenced `#` no longer ends
  a section.
- **`/auto-build --unattended` and `--agent`,** and a JSON contract for `/sitrep` that an unattended
  run reads.

## Earlier

Snapshots from the public cut of 2026-07-13 through 2026-09-30 predate this file.
[`docs/history.md`](./docs/history.md) carries the story from the first review round to the
public cut and on, and [`docs/one-rule.md`](./docs/one-rule.md) traces one convention from a
recurring finding to the check you can run yourself.
