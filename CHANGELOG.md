# Changelog

What each published snapshot of Sysop changed, newest first. The public repository advances in
squash snapshots rather than granular commits (README § Provenance), so this file is the readable
record of a snapshot: user-facing changes only — behaviour a consumer sees, a page a reader uses,
a check that now runs. Each entry is dated by the snapshot's publication and names the span of
private development phases it carries. The per-phase journal those phases were recorded in is the
maintainer's working record and is not in the public tree.

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
