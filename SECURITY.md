# Security Policy

Sysop is client-side developer tooling — markdown skills, bash/python scripts, and git hooks that run locally inside your own repositories. There is no hosted service and no telemetry; the only outbound calls are ones you invoke explicitly (the `gh`-based skills, and whatever your own `checks.yml` commands do).

## Reporting a vulnerability

If you find a security issue — for example a script that can be made to execute untrusted input, a hook that leaks secrets into logs or command lines, or an injection path through task/config files — please report it privately rather than opening a public issue:

- **GitHub:** [private vulnerability reporting](https://github.com/getsysop/sysop/security/advisories/new) (the "Report a vulnerability" button on the Security tab), or
- **Email:** wade@gdpquery.ai

Include the affected file or skill, a reproduction, and the impact you see. This project is maintained casually (see README § Support expectations), but genuine security reports are the exception I try to handle promptly.

## Supported versions

The default track is rolling `main` — both install paths follow the latest commit, and security fixes land there. On top of that, reviewed checkpoints are cut as **tagged releases** (`vX.Y.Z`, with a GitHub Release and a `CHANGELOG.md` entry). A tag marks a point that was reviewed and shipped; it is what a cautious consumer can pin to.

## How updates reach you — and how to pin

Sysop has no auto-update server: updates propagate because you (or your agent) pull the latest source. That also means a bad update — a compromised maintainer account, or a malicious merge — would reach you the same way. Pinning to a reviewed release tag is the mitigation.

- **Bash-installer path** — tracks the HEAD of your local Sysop clone by default (`bash scripts/sysop-update.sh` copies whatever that clone is checked out at). To pin to a reviewed release instead:
  ```bash
  bash install.sh <target> --packs <packs> --ref v0.1.0   # fresh install, pinned
  bash scripts/sysop-update.sh --ref v0.1.0               # update, pinned
  ```
  The tag must exist in your clone (`git -C "$SYSOP_SRC" fetch --tags`). The lock records the tag's commit, so `--check` later shows how far behind HEAD you are. Omit `--ref` to track HEAD.
- **Claude Code plugin path** — tracks HEAD by commit SHA. The manifests deliberately omit a `version` field so plugin auto-update works per-commit (adding one would freeze updates until a manual bump, and Claude Code has no consumer-side "install `sysop@1.0.0`" pin). To hold a known state, disable auto-update for the Sysop marketplace (`/plugin` → Marketplaces → Sysop → Auto-update off) and update deliberately; for a hard pin, use the bash path at a `--ref` tag. A dedicated stable-channel marketplace may be added later if there's demand.

## Maintainer posture

The org account uses 2FA, and `main` is protected (a required test check runs on every PR). Convention/pack contributions land as **issues** the maintainer authors into the repo, never as auto-merged content — the curation rules that keep an open convention corpus safe to accept into are documented in [`CONTRIBUTING.md` § Contribution trust policy](CONTRIBUTING.md).

## Scope note

Sysop's skills instruct an AI agent; its deterministic floor (git hooks, `run_checks`, the validators) is the enforcement surface. A report that the **scripts or hooks execute or leak something they shouldn't** is a security report. A report that an *agent* can be talked past a prose instruction is expected behavior of the design (that's what the deterministic floor exists for) — file it as a regular issue if the floor should be extended to cover it.
