"""A model of how Claude Code matches a `Bash(...)` allow-rule against one command, as measured.

Phase 420 (`Q-665`, `Q-079`) measured it under `--permission-mode dontAsk` on Claude Code
2.1.310, one headless session per call (`tools/phase420_probe.py`, results in `PHASE_LOG.md`
§ Phase 420). What the model encodes, each from a probe:

- The rule is compared with the command text as sent, **quotes included**: `git commit -m
  "docs: x"` binds `Bash(git commit -m "docs: *)` (r2) and not `Bash(git commit -m docs:*)` (c2).
- A trailing ` *` is a plain prefix wildcard; a trailing `:*` needs a word boundary right after
  its prefix, so `Bash(git commit -m "docs:*)` binds no `"docs: …` message (r1), and
  `Bash(git commit -m docs:*)` binds neither `docs:x` (u1) nor `docs: x` (u2).
- A trailing ` *` does not match across a newline, so a message over several lines is denied
  under `Bash(git commit -m "docs: *)` even when its first line matches (n3). A trailing `:*`
  does: the same message binds `Bash(git commit -m:*)` (n8), and a `--jq` argument over two
  lines binds `Bash(gh pr list:*)` (g1).
- A `$(…)` inside double quotes is denied under either kind of rule (n5, n7 under ` *`; g3
  under `:*`). A backtick is unmeasured; the model refuses it to stay on the safe side. An
  `echo` of one, which binds by Claude Code's read-only set and not a rule, was admitted (the
  round's A4); this model covers rules only.
- A compound splits on `&&`, `;` and the rest, each part matched on its own (n2 admitted, n4 a
  `; touch` tail denied). This module matches one part; split before calling it.
- An `exit` and a `{ …; }` group are denied wherever they sit: `<cmd> || exit 1` and
  `<cmd> || { echo x; }` were denied while `<cmd> || echo x` was admitted (the round's A6–A10),
  so a `|| { echo …; exit 1; }` fail-stop binds nothing, whatever rule covers `<cmd>`.

- `test` binds no rule, even with no substitution (`test main = main`, Phase 420's round), so a
  `test "$(…)" = …` check is denied twice over.
- A redirect outside quotes is denied (Phase 380's round); the model refuses an unquoted `>` or
  `<`, and an unquoted `|`, which the caller should have split on.

Unmeasured, and held only by this model: a ` *` rule against a message with no space after
`docs:` (no probe sent `"docs:x"` under `"docs: *`), the exact-match branch (no probe used a rule
without a wildcard), and the backtick refusal.

It is a model for guards, not the matcher: a case it says binds is one a probe admitted or a
shape the probes bracket. Anything else, measure.
"""

from __future__ import annotations


def binds(rule: str, command: str) -> bool:
    """True when the `Bash(...)` rule admits the single command `command`."""
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    if "$(" in command or "`" in command or _unquoted(command, "<>|"):
        return False
    body = rule[len("Bash("):-1]
    if body.endswith(" *"):
        return "\n" not in command and command.startswith(body[:-1])
    if body.endswith(":*"):
        prefix = body[:-2]
        return command == prefix or command.startswith(prefix + " ")
    return command == body


def _unquoted(command: str, chars: str) -> bool:
    """True when one of `chars` appears outside single and double quotes."""
    quote = ""
    for ch in command:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in chars:
            return True
    return False
