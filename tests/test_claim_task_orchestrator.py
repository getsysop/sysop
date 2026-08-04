"""Guards for `/claim-task`'s orchestrator shape (upstream #220).

The skill used to collapse adversarial review, classification, plan revision,
implementation and the post-fix gates into ONE self-classifying sub-agent. A
real run bypassed all of it -- `EnterPlanMode` -> ~200 tool calls ->
`ExitPlanMode`, no `Agent` call at any point -- and because a review that *did*
run left nothing durable either, the healthy case and the skipped case produced
identical evidence.

**This module has now been destroyed twice by its own adversarial round**, and
the second time is why it looks like this. Round 1: 52 mutations, 46 survived.
Round 2, after a rebuild that reported "37 mutations all killed": an independent
lens ran 100 and watched **74** live. The author's number was self-selected both
times.

**Round 2's diagnosis was structural and it is the design of this file.** Every
property that matters is realized in *code* -- the `python3 - <<'PY'` heredocs
the skill prescribes -- and the guards were matching *prose*. So:

  d = claim_root / run_id   ->   d = claim_root          # all runs share a dir
  main_root = Path(common).resolve().parent -> Path(os.environ['PWD'])
  "OK" if now == pre else "VIOLATED"  ->  ... if now != pre ...
  if resume:  ->  if resume and False:                   # --resume inert again

all four survived, and the first two invert the phase's own headline property.
The "universal artifact-path rule" that was supposed to catch them matched a
literal string occurring **once** in a 954-line file.

**So the code checks now PARSE the code.** `heredocs()` pulls each prescribed
python body out of its fence and `ast.parse`s it; the checks below assert
properties of the syntax tree -- which path components a write is composed
from, which branch a `mkdir` sits in, whether the comparison that selects "OK"
is `==` or `!=`. That is immune to every spelling, and it is *also* the fix for
the over-strictness half: a rewrite to an f-string, a tuple unpack,
`os.replace` for `.rename`, `secrets.token_urlsafe` for `token_hex` or
`rev-parse --verify` all pass, where the previous string checks went red on all
five.

**The prose checks are a TRIPWIRE, not a gate, and this docstring used to overclaim
that.** An earlier version said Steps 7-8 "may contain **only** the conditional clauses
enumerated in `CONDITIONAL_ALLOWLIST`". That is false: the allowlist only gates words
`_CONDITIONAL_RE` already matches, and round 3 walked 24 mutations through it using
phrasings the regex does not contain -- "discretionary", "best-effort", "where practical",
"no longer part of the pipeline", "you needn't". Any word list can be extended one phrase
further than the guard, so this layer catches the common spellings and nothing more. The
properties that must actually hold are checked against the syntax tree above, where a
mutation has to break something real.

**The allowlist mechanics, since they are subtle.** Round 2 walked 13 of
13 optional-ising mutations through a 12-pattern list ("superseded", "retained
for historical interest", "legacy guidance", "bypass this block when...") and
the list can always be extended one phrase further than the guard. Inverted:
Steps 7 and 8 may contain only the conditional clauses enumerated in
`CONDITIONAL_ALLOWLIST` -- verified to be exactly six, all legitimate -- and any
*new* one fires. A future author adding a real conditional adds it to the list,
which is the review checkpoint we want rather than a hole.

Population is `claim-task/SKILL.md`, `_shared/plan-review-preference.md`,
`WORKFLOW.md` § 2.2 and `WORKFLOW_GUIDE.md` § 2 -- the last added because round 2
found it unguarded *and written by the same commit*, the author-side rule-1 case
("derive the population from the source of truth, not from one file") applied to
the guards themselves. `/auto-build` runs the same pipeline shape but was not
rewritten by this phase, and widening to it would fail on work not done.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"
PARTIAL = REPO_ROOT / "core/skills/_shared/plan-review-preference.md"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
GUIDE = REPO_ROOT / "core/companion/docs/WORKFLOW_GUIDE.md"
REVIEW_CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"


# ------------------------------------------------------------------ primitives

_FENCE_RE = re.compile(r"^\s*```(\S*)")
_EXECUTABLE_LANGS = frozenset({"bash", "sh", "shell"})


def norm(s: str) -> str:
    """Prose, comparable.

    Emphasis markers, code ticks and whitespace runs carry no meaning in these
    files, and a guard that treats them as meaning reds on a legitimate rewrite.
    `__` is deliberately NOT stripped as underscore-emphasis: this corpus never
    writes emphasis that way and it *does* write `<CLAIM_ID>__<RUN_ID>`, so
    treating it as markup deleted the separator out of every artifact name.
    """
    s = s.replace("**", "").replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", s).strip()


def bash_blocks(text: str) -> list[str]:
    """One string per ```bash/```sh fence, whole-line comments dropped.

    **Language-aware on purpose.** Re-fencing a prescribed command as ```text and
    commenting it out both survived the first version's checks, because the
    substring was still in the file. Here they remove the block from the
    executable set, so a check asserting a command is prescribed goes red.
    """
    out: list[str] = []
    buf: list[str] = []
    in_fence = live = False
    for raw in text.splitlines():
        m = _FENCE_RE.match(raw)
        if m:
            if in_fence:
                if live:
                    out.append("\n".join(buf))
                buf, in_fence, live = [], False, False
            else:
                in_fence, live = True, m.group(1).lower() in _EXECUTABLE_LANGS
            continue
        if in_fence and live and raw.strip() and not raw.lstrip().startswith("#"):
            buf.append(raw.rstrip())
    return out


def bash_text(text: str) -> str:
    return "\n".join(bash_blocks(text))


_HEREDOC_OPEN_RE = re.compile(r"^python3\s+-\s+<<'PY'(?P<args>.*)$")


def heredocs(text: str) -> list[tuple[str, str]]:
    """(header_line, python_body) for each prescribed `python3 - <<'PY'` block.

    The header is kept because its *quoting* is load-bearing: the park's reason
    argument is free text returned by a sub-agent, and inside double quotes a
    `$(...)` in it executes.
    """
    out: list[tuple[str, str]] = []
    for block in bash_blocks(text):
        lines = block.splitlines()
        header = None
        body: list[str] = []
        for ln in lines:
            if header is None:
                m = _HEREDOC_OPEN_RE.match(ln.strip())
                if m:
                    header = ln.strip()
                continue
            if ln.strip() == "PY":
                out.append((header, "\n".join(body)))
                header, body = None, []
                continue
            body.append(ln)
    return out


def heredoc_containing(text: str, needle: str) -> tuple[str, str] | None:
    """The prescribed block whose python body contains `needle`."""
    for header, body in heredocs(text):
        if needle in body:
            return header, body
    return None


def unfenced(text: str) -> str:
    out: list[str] = []
    in_fence = False
    for raw in text.splitlines():
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(raw)
    return "\n".join(out)


def paragraphs(text: str) -> list[str]:
    return [norm(p) for p in re.split(r"\n\s*\n", unfenced(text)) if norm(p)]


def section(text: str, start: str, end: str | None = None) -> str | None:
    """Slice one step out, or None if its anchor is gone.

    **Returns None rather than raising.** The first version raised `ValueError`
    and its own vacuity floor caught the exception and `continue`d, so the floor
    never executed its assertion. A missing anchor is now a recorded problem.
    """
    i = text.find(start)
    if i < 0:
        return None
    if end is None:
        return text[i:]
    j = text.find(end, i)
    return text[i:] if j < 0 else text[i:j]


# ------------------------------------------------------------------- AST tools


def parse(body: str) -> ast.Module | None:
    try:
        return ast.parse(body)
    except SyntaxError:
        return None


def _assignments(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """name -> every value node assigned to it (a name may be assigned twice, and
    both branches of the resume/mint fork assign the artifact dir)."""
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                for name in _target_names(tgt):
                    out.setdefault(name, []).append(node.value)
    return out


def _target_names(tgt: ast.AST) -> list[str]:
    if isinstance(tgt, ast.Name):
        return [tgt.id]
    if isinstance(tgt, (ast.Tuple, ast.List)):
        names = []
        for el in tgt.elts:
            names.extend(_target_names(el))
        return names
    return []


def tokens_for(tree: ast.AST, varname: str, budget: int = 40) -> set[str]:
    """Every string constant and `$name` reachable from `varname`'s assignments,
    followed transitively.

    Deliberately over-collects rather than modelling `/`-chains exactly: what the
    checks need is *which components compose this path*, and a set answers that
    while surviving f-strings, `.format`, `os.path.join`, `.parent`, `.resolve()`
    and any other spelling. Modelling the chain precisely is what made the
    previous string checks brittle in both directions.
    """
    assigns = _assignments(tree)
    seen: set[str] = set()
    out: set[str] = set()
    stack = [varname]
    while stack and budget > 0:
        budget -= 1
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for node in assigns.get(cur, []):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.add(sub.value)
                elif isinstance(sub, ast.Name):
                    out.add("$" + sub.id)
                    stack.append(sub.id)
                elif isinstance(sub, ast.Attribute):
                    out.add("." + sub.attr)
    return out


# --------------------------------------------------------------------------------------
# Ordered path chains. `tokens_for` below is a SET, and round 3 measured what that costs:
# 22 mutations carried every required token while sending the write somewhere else --
# `(claim_root / run_id).parent`, `claim_root / run_id if False else claim_root`,
# `_mk(claim_root, run_id)` where `_mk` discards its second argument, a dict whose 'used'
# key points at the wrong path. Set membership cannot express "the path IS this
# composition"; only an ordered structural comparison can.
#
# `path_chain` therefore returns the ORDERED components of a *bare* `/`-chain, and None
# for anything else -- a call, a conditional, a subscript, a comprehension, a slice. That
# is deliberately strict: a legitimate rewrite of a path expression is a rename or an
# extracted intermediate (both followed transitively), not a wrapper that changes where
# the write lands.
# --------------------------------------------------------------------------------------

_CHAIN_BUDGET = 14


def _chain_of(node, assigns, depth=0):
    if depth > _CHAIN_BUDGET or node is None:
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _chain_of(node.left, assigns, depth + 1)
        right = _chain_of(node.right, assigns, depth + 1)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        sub = assigns.get(node.id)
        if sub is None or len(sub) != 1:
            return ["$" + node.id]
        # Follow if the value is itself a path expression; otherwise treat the name
        # as an opaque LEAF. `common` is bound to a subprocess call and is a leaf by
        # design -- but so is `main_root = Path(os.environ["PWD"])`, which then fails
        # the expected chain rather than being followed into a false match.
        inner = _chain_of(sub[0], assigns, depth + 1)
        return inner if inner is not None else ["$" + node.id]
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        inner = _chain_of(node.value, assigns, depth + 1)
        return None if inner is None else inner + ["<parent>"]
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id == "Path" and len(node.args) == 1:
            return _chain_of(node.args[0], assigns, depth + 1)
        if isinstance(f, ast.Attribute) and f.attr == "resolve" and not node.args:
            return _chain_of(f.value, assigns, depth + 1)
        # `"{}__{}.md".format(a, b)` -- a filename template. Keep the template AND the
        # argument names, so dropping `.md` or dropping `run_id` both change the chain.
        if isinstance(f, ast.Attribute) and f.attr == "format" and isinstance(f.value, ast.Constant):
            args = [a.id if isinstance(a, ast.Name) else "?" for a in node.args]
            return ["<fmt:{}:{}>".format(f.value.value, ",".join(args))]
        return None
    if isinstance(node, ast.JoinedStr):          # f-string filename
        tmpl, args = "", []
        for v in node.values:
            if isinstance(v, ast.Constant):
                tmpl += str(v.value)
            elif isinstance(v, ast.FormattedValue):
                tmpl += "{}"
                args.append(v.value.id if isinstance(v.value, ast.Name) else "?")
        return ["<fmt:{}:{}>".format(tmpl, ",".join(args))]
    return None


def path_chain(tree, varname):
    """Ordered chains for every assignment to `varname`, or None if any is not a
    bare `/`-chain. A name assigned in both arms of the resume fork yields two."""
    assigns = _assignments(tree)
    nodes = assigns.get(varname)
    if not nodes:
        return None
    out = []
    for n in nodes:
        c = _chain_of(n, assigns, 0)
        if c is None:
            return None
        out.append(c)
    return out


# Every artifact path is this prefix plus its own tail. Pinned once.
MAIN_ROOT_PREFIX = ["$common", "<parent>", "sysop", "runtime"]
CLAIM_PREFIX = MAIN_ROOT_PREFIX + ["claim", "$claim_id"]


def chain_problems(tree, varname, expected_tail, label):
    """`expected_tail` is what must follow CLAIM_PREFIX. A `$` entry matches any
    single name (the resume fork spells the run component `resume`)."""
    chains = path_chain(tree, varname)
    if chains is None:
        return [f"{label}: `{varname}` is not a bare path chain -- a wrapper, call or "
                f"conditional can carry every expected component and still write elsewhere"]
    problems = []
    for c in chains:
        if len(c) != len(CLAIM_PREFIX) + len(expected_tail):
            problems.append(f"{label}: `{varname}` chain is {c!r}, expected "
                            f"{CLAIM_PREFIX + expected_tail!r}")
            continue
        for got, want in zip(c, CLAIM_PREFIX + expected_tail):
            if want == "$" and got.startswith("$"):
                continue
            if got != want:
                problems.append(f"{label}: `{varname}` chain is {c!r}, expected "
                                f"{CLAIM_PREFIX + expected_tail!r}")
                break
    return problems


def calls_named(tree: ast.AST, *names: str) -> list[ast.Call]:
    """Every Call whose callee's final attribute/name is one of `names`."""
    want = set(names)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        label = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if label in want:
            out.append(node)
    return out


def string_constants(tree: ast.AST) -> set[str]:
    return {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


DELETE_CALLS = ("unlink", "rmtree", "remove", "rmdir")


def delete_calls(tree: ast.AST) -> list[str]:
    """Delete verbs, by CALLEE rather than by spelling.

    Round 2 walked ten spellings through a regex list (`find -delete`,
    `git clean`, `: >`, `truncate`, `mv … /tmp`). In python the verb family is
    small and closed, so name the family. `.rename` / `os.replace` /
    `shutil.move` are permitted on purpose: moving a previous run's envelopes
    aside is the sanctioned way to clear the mailbox precisely because it
    destroys nothing.
    """
    return [c.func.attr if isinstance(c.func, ast.Attribute) else c.func.id  # type: ignore[union-attr]
            for c in calls_named(tree, *DELETE_CALLS)]


_SHELL_DELETE_RE = re.compile(
    r"\brm\s|\brmdir\b|-delete\b|\bshred\b|\btruncate\s+-s\s*0|"
    r"\bgit\s+clean\b|^\s*:\s*>|\s>\s*[^|&>]*\.(?:json|md)\s*$|\bcp\s+/dev/null\b",
    re.M,
)


def shell_deletes(text: str) -> list[str]:
    """Shell-level destruction among the executable lines, any spelling."""
    return [ln for ln in bash_text(text).splitlines() if _SHELL_DELETE_RE.search(ln)]


def branch_containing(tree: ast.AST, callee: str) -> list[tuple[ast.If, str]]:
    """(If node, "body"|"orelse") for each `If` with a call to `callee` in one arm."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        for arm in ("body", "orelse"):
            stmts = getattr(node, arm)
            if any(calls_named(s, callee) for s in stmts):
                out.append((node, arm))
    return out


def has_literal_switch(node: ast.AST) -> bool:
    """Does this `if` test contain a boolean/numeric literal?

    `if resume and False:` and `if False:` both make the guarded branch dead
    while leaving the name on the page -- two round-2 survivors, and the second
    of them made `--resume` inert again, the exact defect the rebuild exists to
    fix. A string literal is NOT flagged: `if resume != "":` is a legitimate
    rewrite and the previous check went red on that class.
    """
    return any(
        isinstance(n, ast.Constant) and isinstance(n.value, (bool, int, float))
        for n in ast.walk(node)
    )


def verdict_sense(tree: ast.AST, good: str, bad: str) -> str | None:
    """"eq" | "ne" | None -- the comparison sense that selects `good`.

    Handles both idioms (`x if cmp else y`, and an `if` statement whose arm
    produces the string) so a legitimate refactor between them passes, while
    inverting the comparison -- a round-2 survivor that turned the planner
    integrity check inside out -- does not.
    """
    def sense(test: ast.AST) -> str | None:
        for n in ast.walk(test):
            if isinstance(n, ast.Compare) and n.ops:
                if isinstance(n.ops[0], ast.Eq):
                    return "eq"
                if isinstance(n.ops[0], ast.NotEq):
                    return "ne"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp):
            b = string_constants(node.body)
            o = string_constants(node.orelse)
            if good in b and bad in o:
                return sense(node.test)
            if bad in b and good in o:
                s = sense(node.test)
                return {"eq": "ne", "ne": "eq"}.get(s) if s else None
        if isinstance(node, ast.If):
            b = set().union(*(string_constants(s) for s in node.body)) if node.body else set()
            o = set().union(*(string_constants(s) for s in node.orelse)) if node.orelse else set()
            if good in b and bad in o:
                return sense(node.test)
            if bad in b and good in o:
                s = sense(node.test)
                return {"eq": "ne", "ne": "eq"}.get(s) if s else None
    return None


# ---------------------------------------------------------------- prose tools

_NEGATOR_RE = re.compile(
    r"\b(?:not|never|no|nor|nothing|none|cannot|can't|don't|doesn't|without|"
    r"neither|refus\w*|forbid\w*|prohibit\w*)\b(?!-)",
    re.I,
)
# The trailing `(?!-)` is load-bearing: a hyphen is a word boundary, so `\bno\b`
# matched inside `--no-review-plan` and `no-response-received` and exempted the
# whole clause those words sit in -- two false exemptions caught by this module's
# own battery, one of them on the partial's tier-1 rule.
# Clause boundary, not sentence boundary. Round 2 bypassed a sentence-scoped
# window with `There is no reason to run 7b; it is optional.` and
# `Nothing here is mandatory: 7b is optional.` -- the negator governs the FIRST
# clause and not the second. Within a clause the search is unbounded to the left,
# which is what lets `Do not, under any circumstances and regardless of how long
# the queue is, spawn ...` stay green; a fixed 48-character window went red on it,
# the module's named failure mode of firing on the sentence that forbids the thing.
# A `.` only ends a clause when whitespace follows it. Without the lookahead the
# `.` in `plan.md` split the clause mid-filename, which broke an allowlist entry
# on the healthy file the moment the allowlist was scoped to the clause.
_CLAUSE_END_RE = re.compile(r"[.!?](?=\s|$)|[;:]")


def negated(flat: str, at: int) -> bool:
    left = flat[:at]
    ends = list(_CLAUSE_END_RE.finditer(left))
    if ends:
        left = left[ends[-1].end():]
    return bool(_NEGATOR_RE.search(left))


# Any language that could make a mandatory step optional, framed as retired, or
# reordered. The list is WIDE on purpose and it is not the guard -- the allowlist
# below is. A phrase missing here is caught by nothing, which is why the design
# inverts: what is allowed is enumerated, not what is forbidden.
_CONDITIONAL_RE = re.compile(
    r"\boptional\b|\boptionally\b|omitted by default|skipped by default|"
    r"\bskip(?:ped|ping)?\b|\bomit(?:ted|ting)?\b|may be (?:skipped|omitted)|"
    r"at your discretion|if time (?:permits|allows)|no longer (?:applies|required|needed)|"
    r"\bhistorical\b|\bdeprecated\b|\bsuperseded\b|\blegacy\b|retained (?:for|only)|"
    r"\bbypass(?:ed|es)?\b|only when|only if|\bunless\b|\badvisory\b|not run\b|"
    r"before the reshape|for reference only|kept for context|nice to have|"
    r"\bdoes not run\b|\bneed not\b|\bno need to\b",
    re.I,
)

# The conditional clauses these corpora legitimately contain, pinned normalised.
# Anything else the regex above finds is a NEW one and fires. Derived by
# enumeration against the shipped files, not from memory: `test_the_conditional_
# allowlist_is_exhaustive_and_live` fails if an entry stops appearing, because a
# stale entry is a permanent hole that excuses whatever a future author writes
# near the same words.
CONDITIONAL_ALLOWLIST = (
    # /claim-task Steps 7-8
    "Skip this step entirely when Step 6 resolved to B",          # 7d is option A only
    "the superseded run stays on disk as the record",             # 7d revise mints a new run
    "the halt-on-blocker gate were all bypassed",                 # narrating #220
    "a consumer that has not run the installer",                  # gitignore note
    "do not run from the project root",                           # executor prompt
    "If both are absent, skip",                                   # executor: no verification section
    "skip cleanly with an explicit note if the dev server",       # executor: UI verify
    "Skip the chain when the executor returned",                  # Step 8 auto-mode chaining
    # Bound to its own sentence, not the bare verb phrase. An entry here exempts any
    # match whose word falls inside the span, so a two-word entry would exempt every
    # future "skip the auto-mode chain" anywhere in the file — which is the allowlist
    # hole this list's own design note warns about (proximity is not identity, and
    # neither is a short span).
    "surface the file list the block just printed, skip the auto-mode chain",  # Step 8 STRANDED arm (Phase 180, #322)
    # WORKFLOW.md § 2.2
    "SUPERSEDED | stop | Step 7d's revise rejected",                # routing row 1 (the word itself)
    "classification write for THIS run with verdict: SUPERSEDED",   # 7d revise instruction
    "The SUPERSEDED flip is the other half",                        # its rationale
    "the rows above reach 7a only when it is absent",               # the soundness rule
    "SUPERSEDED, then go back to Step 7-pre",                       # 7d revise instruction
    "The SUPERSEDED flip is the other half",                        # its rationale
    "Solo workflows that bypass /claim-task",                       # solo path, pre-existing
    "call the script directly may omit --lock",                    # (same clause, second token)
    "it makes a skipped review visible",                          # the shape's own argument
)


def new_conditionals(text: str) -> list[str]:
    """Conditional/retirement language not on the allowlist and not negated."""
    flat = norm(unfenced(text))
    hits: list[str] = []
    for m in _CONDITIONAL_RE.finditer(flat):
        # The allowlist is matched against the hit's OWN CLAUSE, not a window
        # around it. A +/-90-character window let a new conditional be smuggled
        # in beside an allowlisted one and inherit its exemption -- found by this
        # phase's own author-side pass, and it is the general shape of an
        # allowlist hole: proximity is not identity.
        starts = [x.end() for x in _CLAUSE_END_RE.finditer(flat[:m.start()])]
        lo = starts[-1] if starts else 0
        nxt = _CLAUSE_END_RE.search(flat, m.end())
        clause = flat[lo:nxt.end() if nxt else min(len(flat), m.end() + 120)]
        # The exemption applies only when the MATCHED WORD lies inside the
        # allowlisted span -- not merely in the same clause. Two weaker forms
        # were defeated by this phase's own author-side pass: a +/-90-character
        # window let a new conditional be smuggled in beside an allowlisted one,
        # and clause-level containment let one ride along INSIDE it
        # ("Step 7b is optional and Row 2 fires only when plan.md is absent").
        # Proximity is not identity, and neither is sharing a sentence.
        rel = m.start() - lo
        exempt = False
        for allowed in CONDITIONAL_ALLOWLIST:
            a = clause.find(allowed)
            if a >= 0 and a <= rel < a + len(allowed):
                exempt = True
                break
        if exempt:
            continue
        if negated(flat, m.start()):
            continue
        hits.append(clause.strip())
    return hits


_STAGE_ORDER = ("pre", "a", "b", "c", "d", "e")
_STAGE_TOKEN_RE = re.compile(r"\b7-?(pre|[a-e])\b", re.I)
_ARROW_CHAIN_RE = re.compile(r"7-?(?:pre|[a-e])(?:\s*(?:->|→|then)\s*7-?(?:pre|[a-e]))+", re.I)
_ORDER_DECLARATION_RE = re.compile(
    r"\b(?:order of operations|run (?:them|these) in order|pipeline order)\b", re.I
)
# Prose that states an order without listing a chain -- four round-2 survivors:
# "Run 7e before 7b on every claim." / "Do 7e first. Then do 7b." /
# "The executor precedes the reviewer." / "Spawn this executor as soon as the
# plan exists; the reviewer's findings are applied afterwards."
_PAIRWISE_ORDER_RE = re.compile(
    r"(7-?(?:pre|[a-e])|executor|reviewer|planner|classification)\s+"
    r"(?:comes\s+)?(?:before|precedes|ahead of|first,? then)\s+"
    r"(?:the\s+)?(7-?(?:pre|[a-e])|executor|reviewer|planner|classification)",
    re.I,
)
_ROLE_ORDER = {"planner": 1, "reviewer": 2, "classification": 3, "executor": 5}


def _rank(tok: str) -> int:
    t = tok.lower().lstrip("7").lstrip("-")
    if t in _STAGE_ORDER:
        return _STAGE_ORDER.index(t)
    return _ROLE_ORDER.get(tok.lower(), -1)


def ordering_violations(text: str) -> list[str]:
    """Any stated order that contradicts 7-pre -> 7a -> 7b -> 7c -> 7d -> 7e."""
    bad: list[str] = []
    for raw in unfenced(text).splitlines():
        line = norm(raw)
        if not line:
            continue
        for m in _ARROW_CHAIN_RE.finditer(line):
            toks = _STAGE_TOKEN_RE.findall(m.group(0))
            idx = [_STAGE_ORDER.index(t.lower()) for t in toks]
            if any(a > b for a, b in zip(idx, idx[1:])):
                bad.append(m.group(0))
        if _ORDER_DECLARATION_RE.search(line):
            toks = _STAGE_TOKEN_RE.findall(line)
            idx = [_STAGE_ORDER.index(t.lower()) for t in toks]
            if len(idx) >= 3 and any(a > b for a, b in zip(idx, idx[1:])):
                bad.append(line[:120])
        for m in _PAIRWISE_ORDER_RE.finditer(line):
            a, b = _rank(m.group(1)), _rank(m.group(2))
            if a >= 0 and b >= 0 and a > b:
                bad.append(m.group(0))
    return bad


def frontmatter_blocks(text: str) -> list[list[str]]:
    """Every `---`-delimited block at the head of the file.

    A SECOND block appended after the first was a round-2 survivor: the reader
    took only the first, so the duplicate silently decided what was denied.
    """
    lines = text.splitlines()
    out: list[list[str]] = []
    i = 0
    while i < len(lines) and lines[i].strip() == "---":
        buf = []
        i += 1
        while i < len(lines) and lines[i].strip() != "---":
            buf.append(lines[i])
            i += 1
        i += 1
        out.append(buf)
        while i < len(lines) and not lines[i].strip():
            i += 1
    return out


def _yaml_scalar_list(raw: str) -> set[str]:
    """Parse a YAML value that may be `a, b, c`, `[a, b, c]`, `"a, b"` or a block
    list. All four are legitimate spellings of the same value; the previous
    hand-rolled `raw.split(",")` went red on three of them."""
    raw = raw.split("#", 1)[0].strip()
    raw = raw.strip("[]")
    raw = raw.strip("\"'")
    return {x.strip().strip("\"'-").strip() for x in re.split(r"[,\n]", raw) if x.strip()}


# ------------------------------------------------------------------ the skill

CANONICAL_STAGES = (
    ("### Step 7-pre", "run + artifact directory"),
    ("### Step 7a", "planner"),
    ("### Step 7b", "reviewer"),
    ("### Step 7c", "classification"),
    ("### Step 7d", "human gate"),
    ("### Step 7e", "executor"),
)


def _code_problems(t: str) -> list[str]:
    """The properties that live in the prescribed heredocs, checked by parsing them."""
    p: list[str] = []

    # --- Step 7-pre: the artifact directory ------------------------------
    hd = heredoc_containing(t, "MOVED_PRIOR_ENVELOPES")
    if hd is None:
        p.append("Step 7-pre's prescribed block is gone, re-fenced or commented out")
    else:
        _, body = hd
        tree = parse(body)
        if tree is None:
            p.append("Step 7-pre's prescribed block is not valid python")
        else:
            p.extend(chain_problems(tree, "d", ["$"], "Step 7-pre"))
            if not calls_named(tree, "token_hex", "token_urlsafe", "token_bytes"):
                p.append("Step 7-pre: the run id lost its random component -- `started:` is "
                         "second-granular and a release+reclaim collides")
            if not any("--git-common-dir" in string_constants(c) for c in calls_named(tree, "run")):
                p.append("Step 7-pre no longer resolves the main repo root via --git-common-dir")

            # The resume arm ADOPTS; only the mint arm creates. Pick the fork by
            # what it DOES (it has both arms and one of them mints), not by the
            # first `if` mentioning `resume` -- the placeholder-substitution
            # guard above it mentions `resume` too, and selecting that one made
            # every check below describe the wrong branch.
            forks = [
                n for n in ast.walk(tree)
                if isinstance(n, ast.If) and n.orelse
                and "resume" in {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)}
                and any(calls_named(s, "mkdir") for s in n.body + n.orelse)
            ]
            if not forks:
                p.append("Step 7-pre no longer forks on --resume between adopting a run and "
                         "minting one")
            else:
                fork = forks[0]
                if has_literal_switch(fork.test):
                    p.append("Step 7-pre's resume branch is switched off by a literal in its test "
                             "-- `--resume` is inert, the defect this rebuild exists to fix")
                if not any(calls_named(s, "exit") for s in ast.walk(fork)):
                    p.append("Step 7-pre's resume arm no longer refuses a run id that names nothing")
                if not any(calls_named(s, "mkdir") for s in fork.orelse):
                    p.append("Step 7-pre no longer creates the run directory on the mint path")
                if any(calls_named(s, "mkdir") for s in fork.body):
                    p.append("Step 7-pre creates a directory on the RESUME path -- a resume adopts "
                             "an existing run, it does not mint one")
                guard = [n for b in fork.body for n in ast.walk(b)
                         if isinstance(n, ast.If) and calls_named(n.test, "is_dir")]
                if not guard:
                    p.append("Step 7-pre's resume arm no longer checks that the named run exists")
                elif has_literal_switch(guard[0].test):
                    p.append("Step 7-pre's resume existence check is switched off by a literal -- "
                             "a resume would adopt a run that was never minted")
            if not calls_named(tree, "rename", "replace", "move"):
                p.append("Step 7-pre no longer MOVES a previous run's envelopes aside -- the hook "
                         "keys them with no run component, so Step 8 would read a stale exec.json")
            if delete_calls(tree):
                p.append(f"Step 7-pre deletes: {sorted(set(delete_calls(tree)))} -- the mailbox is "
                         "cleared by moving, never by destroying evidence")

    # --- Step 7c: the classification write -------------------------------
    hd = heredoc_containing(t, "classified_by")
    if hd is None:
        p.append("Step 7c's classification write is gone, re-fenced or commented out")
    else:
        _, body = hd
        tree = parse(body)
        if tree is None:
            p.append("Step 7c's classification write is not valid python")
        else:
            p.extend(chain_problems(tree, "out", ["$", "classification.md"], "Step 7c"))
            if not calls_named(tree, "write_text"):
                p.append("Step 7c composes the classification but never writes it")
            if "yaml" in imports(tree):
                p.append("Step 7c's classification write imports yaml -- it must be stdlib only, "
                         "or it crashes on a PEP-668 consumer whose bare python3 has no PyYAML")
            if not any(calls_named(n.test, "is_dir") for n in ast.walk(tree) if isinstance(n, ast.If)):
                p.append("Step 7c no longer refuses a run directory that does not exist -- a "
                         "mistyped <RUN_ID> would manufacture a run that Step 1's --resume "
                         "validator then blesses")
            if calls_named(tree, "mkdir"):
                p.append("Step 7c creates the run directory -- only Step 7-pre mints runs")
            if delete_calls(tree):
                p.append("Step 7c deletes something -- nothing is removed mid-lifecycle")

    # --- Step 7c: the park marker ----------------------------------------
    hd = heredoc_containing(t, '"parked"')
    if hd is None:
        p.append("Step 7c's park block is gone, re-fenced or commented out")
    else:
        header, body = hd
        tree = parse(body)
        if tree is None:
            p.append("Step 7c's park block is not valid python")
        else:
            marker_chain = path_chain(tree, "marker")
            want = MAIN_ROOT_PREFIX + ["parked", "<fmt:{}__{}.md:claim_id,run_id>"]
            if marker_chain != [want]:
                p.append("the park marker's path is no longer "
                         "`<main>/sysop/runtime/parked/<CLAIM_ID>__<RUN_ID>.md` -- a directory, a "
                         "different name shape, or a dropped `.md` can never match /review-close "
                         f"Step 4c's `{{tid}}__*.md` glob. Got: {marker_chain!r}")
            p.extend(chain_problems(tree, "art", ["$"], "the park"))
            if not calls_named(tree, "write_text"):
                p.append("the park composes a marker but never writes it")
            if "reason" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}:
                p.append("the park records no reason -- three failure paths park 'with the "
                         "recorded reason'")
            if not any(calls_named(n.test, "is_dir") for n in ast.walk(tree) if isinstance(n, ast.If)):
                p.append("the park no longer refuses a run directory that does not exist")
            if delete_calls(tree):
                p.append("the park deletes something -- a park removes nothing")
            # The reason arrives as free text from a sub-agent. Inside double
            # quotes a `$(...)` in it is command substitution and RUNS.
            # Strip the `<<'PY'` delimiter before reading the positionals -- it is
            # itself a single-quoted token and counting it shifted every index by
            # one, which made this check report the branch name as the reason.
            args = re.findall(r'"[^"]*"|\'[^\']*\'', re.sub(r"<<'PY'", "", header))
            if len(args) < 4:
                p.append("the park block no longer takes four substituted arguments")
            elif not args[3].startswith("'"):
                p.append("the park's reason argument is not single-quoted -- it is free text "
                         "returned by a sub-agent, and inside double quotes a $(...) in it runs")

    # --- Step 7a: the planner integrity verdict --------------------------
    hd = heredoc_containing(t, "planner-integrity")
    if hd is None:
        p.append("Step 7a's post-plan integrity check is gone, re-fenced or commented out")
    else:
        _, body = hd
        tree = parse(body)
        if tree is None:
            p.append("Step 7a's integrity check is not valid python")
        else:
            sense = verdict_sense(tree, "OK", "VIOLATED")
            if sense is None:
                p.append("Step 7a's integrity check no longer decides OK vs VIOLATED by comparing "
                         "the pre-plan and post-plan SHAs")
            elif sense != "eq":
                p.append("Step 7a's integrity verdict is INVERTED -- an unmoved HEAD now reports "
                         "VIOLATED and a planner that committed reports OK")
            if not any("rev-parse" in string_constants(c) for c in calls_named(tree, "run")):
                p.append("Step 7a's integrity check no longer reads HEAD")

    # --- Step 8: the executor's terminal status, recorded per run --------
    hd = heredoc_containing(t, "executor_status")
    if hd is None:
        p.append("Step 8 no longer records the executor's outcome into the run -- without it the "
                 "resume routing has to consult the shared envelope mailbox, which is keyed with "
                 "no run component and which a resume deliberately does not clear")
    else:
        tree = parse(hd[1])
        if tree is None:
            p.append("Step 8's outcome write is not valid python")
        else:
            p.extend(chain_problems(tree, "out", ["$", "outcome.md"], "Step 8"))
            if not calls_named(tree, "write_text"):
                p.append("Step 8 composes an outcome but never writes it")
            if delete_calls(tree):
                p.append("Step 8's outcome write deletes something")

    # --- Step 7a's integrity verdict, recorded per run -------------------
    hd = heredoc_containing(t, "planner-integrity")
    if hd is not None:
        tree = parse(hd[1])
        if tree is not None:
            p.extend(chain_problems(tree, "out", ["$", "planner-integrity.md"], "Step 7a"))
            if not calls_named(tree, "write_text"):
                p.append("Step 7a's integrity check no longer WRITES its verdict -- held only in "
                         "context it is lost to a crash, and the plan it gates then routes to a "
                         "reviewer with nothing recording that it was never re-gated")

    # --- Step 1: the --resume validator ----------------------------------
    hd = heredoc_containing(t, "RESUME_OK")
    if hd is None:
        p.append("Step 1's --resume validation block is gone, re-fenced or commented out")
    else:
        _, body = hd
        tree = parse(body)
        if tree is None:
            p.append("Step 1's --resume validator is not valid python")
        else:
            if not calls_named(tree, "exit"):
                p.append("Step 1's --resume validator no longer refuses an unknown run id")
            if not any("--git-common-dir" in string_constants(c) for c in calls_named(tree, "run")):
                p.append("Step 1's --resume validator no longer resolves the main repo root, so it "
                         "looks somewhere Step 7-pre does not write")
            if delete_calls(tree):
                p.append("Step 1's --resume validator deletes something")
    return p


def orchestrator_problems(text=None) -> list[str]:
    t = SKILL.read_text(encoding="utf-8") if text is None else text
    p: list[str] = _code_problems(t)

    # --- The orchestrator cannot implement -------------------------------
    fms = frontmatter_blocks(t)
    if not fms:
        p.append("frontmatter block is missing or unterminated")
    elif len(fms) > 1:
        p.append(f"{len(fms)} frontmatter blocks -- a second one silently decides what is denied")
    else:
        fm = fms[0]
        keys = [ln for ln in fm if re.match(r"^disallowed-tools\s*:", ln)]
        if not keys:
            p.append("frontmatter lost its `disallowed-tools:` key")
        elif len(keys) > 1:
            p.append(f"frontmatter declares `disallowed-tools:` {len(keys)} times -- YAML is "
                     "last-key-wins, so the duplicate silently decides what is denied")
        else:
            idx = fm.index(keys[0])
            raw = keys[0].split(":", 1)[1]
            for ln in fm[idx + 1:]:
                if re.match(r"^\s*-\s+\S", ln):
                    raw += "\n" + ln
                else:
                    break
            tools = _yaml_scalar_list(raw)
            if tools != {"Edit", "Write", "NotebookEdit"}:
                p.append(f"`disallowed-tools:` no longer denies Edit/Write/NotebookEdit: {sorted(tools)}")
        if any(re.match(r"^(allowed-tools|tools)\s*:", ln) for ln in fm):
            p.append("frontmatter grants tools back with an `allowed-tools:` key alongside the denial")
        model = [ln for ln in fm if re.match(r"^model\s*:", ln)]
        if not model or "opus" not in model[0]:
            p.append("the orchestrator is no longer pinned to the reasoning-tier model")

    flat = norm(unfenced(t))
    for m in re.finditer(r"(?i)\b(?:call|invoke|use|enter)\s+(?:the\s+)?(?:Enter|Exit)PlanMode", flat):
        if not negated(flat, m.start()):
            p.append("the orchestrator is instructed to call a plan-mode tool -- it must never "
                     "enter plan mode")
            break

    # --- The pipeline is genuinely split, and in order -------------------
    positions = []
    for anchor, label in CANONICAL_STAGES:
        i = t.find(anchor)
        if i < 0:
            p.append(f"pipeline lost {anchor} ({label})")
        else:
            positions.append((i, anchor))
    if len(positions) == len(CANONICAL_STAGES):
        if [a for _, a in sorted(positions)] != [a for a, _ in CANONICAL_STAGES]:
            p.append("the pipeline stages are out of order in the file")
    for bad in ordering_violations(t):
        p.append(f"a stated stage order contradicts 7-pre -> 7a -> 7b -> 7c -> 7d -> 7e: {bad!r}")

    # --- Nothing in Steps 7-8 becomes conditional or gets retired --------
    s78 = section(t, "## Step 7: Orchestrate", None)
    if s78 is None:
        p.append("Step 7 is gone")
    else:
        for hit in new_conditionals(s78):
            p.append(f"Steps 7-8 gained conditional or retirement language not on the allowlist: {hit!r}")
        for ln in shell_deletes(s78):
            p.append(f"Steps 7-8 run a destructive command: {ln.strip()!r}")
        # A prose instruction to destroy an artifact. Scoped to an imperative
        # verb IMMEDIATELY followed by one of the things this pipeline must not
        # destroy -- a bare `delete`/`remove` anywhere in 500 lines of prose that
        # discusses deletion at length is not a signal, and keying on one made
        # this check fire on the sentence explaining why nothing is deleted.
        n78 = norm(unfenced(s78))
        for m in re.finditer(
            r"(?i)\b(?:delete|remove|discard|clear|wipe)\s+(?:the\s+|any\s+|all\s+)?"
            r"(?:envelopes?|artifacts?|artifact director\w+|run director\w+|"
            r"plan\.md|review\.md|classification\.md|parked markers?)", n78
        ):
            if negated(n78, m.start()):
                continue
            p.append(f"Steps 7-8 instruct a delete in prose: "
                     f"{n78[max(0, m.start() - 90):m.end() + 40]!r}")
            break

    # --- Step 7b: the reviewer always runs -------------------------------
    s7b = section(t, "### Step 7b", "### Step 7c")
    if s7b is None:
        p.append("Step 7b is gone")
    else:
        n7b = norm(s7b)
        if not re.search(r"\bAlways\b", n7b) or not re.search(
            r"(?:never|not) (?:inherited|skipped)", n7b, re.I
        ):
            p.append("Step 7b no longer states that the reviewer always runs and is never "
                     "inherited or skipped")
        if not re.search(r"adversarial-review\.md", s7b):
            p.append("Step 7b no longer hands the reviewer the shared adversarial-review template")
        # Two corrections, both exposed by Phase 180's reorder of the tail's fences
        # and both pre-existing. (1) Negation is tested at EACH match's own offset;
        # the first version tested it at `n7b.lower().index("classify")` — the first
        # occurrence of the *word*, which is not where the regex matched. (2) The
        # scan runs on the section's PROSE, fences removed. An instruction to
        # classify is prose; the envelope template is not. Once the envelope fence
        # sat directly above `Report findings only.`, its `ERROR: <… if you could
        # not complete the review …>` line put a `not` inside the negation window
        # and this check went blind to a planted self-classification instruction
        # with the whole mutation table green.
        prose7b = norm(unfenced(s7b))
        if any(not negated(prose7b, m.start())
               for m in re.finditer(r"(?i)classify (?:each|the) finding", prose7b)):
            p.append("Step 7b asks the reviewer to classify -- classification is the orchestrator's")

    # --- Step 7c: classification stays one layer up ----------------------
    s7c = section(t, "### Step 7c", "### Step 7d")
    if s7c is None:
        p.append("Step 7c is gone")
    else:
        n7c = norm(s7c)
        if not re.search(r"(?:not|never)\s+delegated", n7c, re.I):
            p.append("Step 7c no longer forbids delegating classification")
        for m in re.finditer(r"(?i)\bspawn\b|\bdelegate\b|\bhand (?:it|this) (?:off|to)\b", n7c):
            if not negated(n7c, m.start()):
                p.append("Step 7c delegates the classification -- it is the orchestrator's own job "
                         "and pushing it one layer down adds no fresh eyes")
                break

    # --- Freshness, resume, and the single entry point -------------------
    s7pre = section(t, "### Step 7-pre", "### Step 7a")
    if s7pre is None:
        p.append("Step 7-pre is gone")
    else:
        n = norm(s7pre)
        if not re.search(r"not in a shell variable|never in a shell variable", n, re.I):
            p.append("Step 7-pre lost the persistence-boundary warning for RUN_ID")
        if not re.search(r"(?:only|sole) (?:re-)?entry point", n, re.I):
            p.append("Step 7-pre no longer declares itself the only entry point to Step 7")
        for stage in ("7a", "7b", "7c", "7d", "7e"):
            if stage not in s7pre:
                p.append(f"Step 7-pre's resume routing table no longer routes to {stage}")

    # Exactly one re-entry point.
    outside = t[t.find("### Step 7a"):] if "### Step 7a" in t else t
    head = t[:t.find("### Step 7-pre")] if "### Step 7-pre" in t else ""
    for chunk in (head, outside):
        for para in paragraphs(chunk):
            if re.search(r"re-ent(?:er|ry|ers|ering)|restart at|lands? (?:directly )?at",
                         para, re.I) and _STAGE_TOKEN_RE.search(para):
                if "7-pre" not in para:
                    p.append(f"a re-entry point other than Step 7-pre is named: {para[:110]!r}")

    # --- The unforgeable artifact stays unforgeable ----------------------
    s7e = section(t, "### Step 7e", "### Failure handling")
    if s7e is None:
        p.append("Step 7e is gone")
    else:
        n7e = norm(s7e)
        m = re.search(r"write to sysop/runtime/subagent-envelopes/", n7e)
        if not m or not negated(n7e, m.start()):
            p.append("the executor is no longer forbidden from writing its own envelope -- that "
                     "converts the one unforgeable artifact into a forgeable one")

    # --- Failure handling: the rule that matters -------------------------
    sfail = section(t, "### Failure handling", "## Step 8")
    if sfail is None:
        p.append("the failure-handling section is gone")
    else:
        nf = norm(sfail)
        # Either phrasing, and the rule is that it is NEGATED wherever it appears:
        # `Never proceed to 7e` and `7e must never be reached without a review` say
        # the same thing, and a guard pinning one spelling reds on the other.
        m = re.search(r"(?i)proceed to 7e", nf)
        alt = re.search(r"(?i)7e (?:must|may) never be reached", nf)
        if not alt and (not m or not negated(nf, m.start())):
            p.append("lost the never-proceed-to-7e-without-a-reviewer rule")
    # `spawn the executor` is deliberately NOT here: it is 7e's own heading and
    # its ordinary description, so keying on it fired on the healthy file. And a
    # match inside quotation marks is exempt -- the failure-handling preamble
    # QUOTES the anti-pattern ("the tempting recovery is \"continue to the
    # executor anyway\""), and firing on it is the module's named failure mode:
    # the sentence forbidding the thing tripping the guard for it.
    for m in re.finditer(r"(?i)proceed to 7e|continue to the executor", flat):
        if flat[:m.start()].count('"') % 2 == 1:
            continue
        if not negated(flat, m.start()):
            p.append(f"something instructs the run to reach the executor regardless: "
                     f"{flat[max(0, m.start()-70):m.start()+50]!r}")
            break

    # --- Step 8 ----------------------------------------------------------
    s8 = section(t, "## Step 8", None)
    if s8 is None:
        p.append("Step 8 is gone")
    else:
        n8 = norm(s8)
        m = re.search(r"delete the envelopes", n8, re.I)
        if not m or not negated(n8, m.start()):
            p.append("Step 8 no longer forbids deleting the envelopes after consumption")
        if not re.search(r"part b", n8, re.I):
            p.append("Step 8 no longer says close-time cleanup is unbuilt (part B) -- it must not "
                     "claim a reader that does not exist")

    # --- Claim kinds: silence reads as not-applicable (Phase 29) ---------
    s7d = section(t, "### Step 7d", "### Step 7e")
    if s7d is None:
        p.append("Step 7d is gone")
    else:
        if not re.search(r"\*\*Review batches:\*\*", s7d):
            p.append("Step 7d's abandon path has no Review batches: clause")
        routed = re.findall(r"(\S+\.sh)\s+--release\s+<BATCH_NUMBER>", s7d)
        if not routed:
            p.append("Step 7d does not route a batch abandon at all")
        for scr in routed:
            if not scr.endswith("batch_work.sh"):
                p.append(f"Step 7d routes a batch abandon at {scr} -- claim_task.sh --release "
                         "hard-exits 1 on a BATCH-* id")
        if not re.search(r"(?:new|fresh) run", norm(s7d), re.I):
            p.append("Step 7d's revise no longer mints a new run -- a revised plan beside the "
                     "previous plan's review.md is the state the routing table cannot tell from "
                     "a reviewed one")

    # --- Both resume arms establish the branch every prompt needs --------
    s2 = section(t, "## Step 2: Read Context", "## Step 3")
    if s2 is None:
        p.append("Step 2 is gone")
    else:
        arms = [a for a in re.split(r"(?=\*\*Review batches:\*\*)", s2)]
        for arm, label in ((arms[0], "the roadmap resume arm"),
                           (arms[-1] if len(arms) > 1 else "", "the review-batch resume arm")):
            if "--resume" not in arm:
                p.append(f"{label} no longer honours --resume")
            # One SENTENCE must tie the branch to the lock it is read from.
            # Requiring the two tokens anywhere in the arm was satisfied by the
            # lock path in the status rows above and by a later mention of the
            # prompts -- so the establishing instruction could be deleted whole
            # and the check stayed green.
            elif not re.search(
                r"(?is)(?:read|take)[^.]{0,200}<BRANCH_NAME>[^.]{0,200}lock"
                r"|lock[^.]{0,200}<BRANCH_NAME>[^.]{0,200}(?:workspace|branch:)", arm
            ):
                p.append(f"{label} never establishes <BRANCH_NAME> and the worktree path from the "
                         "lock -- Step 4 is skipped on a resume, and all three Step 7 prompts "
                         "substitute the branch")

    s4 = section(t, "## Step 4: Claim the Task", "## Step 5")
    if s4 is None:
        p.append("Step 4 is gone")
    else:
        i = s4.rfind("**Review batches:**")
        batch_block = s4[i:] if i >= 0 else ""
        if not batch_block:
            p.append("Step 4 lost its Review batches: clause")
        elif "<BRANCH_NAME>" not in batch_block or "Branch:" not in batch_block:
            p.append("the review-batch claim path never establishes <BRANCH_NAME> off "
                     "batch_work.sh's `Branch:` line")

    # --- Step 6 states the absent option rather than staying silent ------
    s6 = section(t, "## Step 6", "## Step 7")
    if s6 is None:
        p.append("Step 6 is gone")
    elif not re.search(r"specified but (?:not built|unbuilt)", norm(s6), re.I):
        p.append("Step 6 no longer says option C is unbuilt -- silence about a missing branch is "
                 "how Steps 7-8 acquired roadmap-only vocabulary in Phase 29")
    return p


# ---------------------------------------------------------------- the partial


def partial_problems(text=None) -> list[str]:
    t = PARTIAL.read_text(encoding="utf-8") if text is None else text
    p: list[str] = []
    flat = norm(unfenced(t))

    tiers = [(r"--review-plan", "the invocation flag"),
             (r"CLAUDE\.md § Plan review", "the consumer's CLAUDE.md section"),
             (r"\bAsk\b", "the AskUserQuestion fallback")]
    idx = []
    for pat, label in tiers:
        m = re.search(pat, flat)
        if m is None:
            p.append(f"the resolution order lost {label}")
        else:
            idx.append(m.start())
    if len(idx) == 3 and not (idx[0] < idx[1] < idx[2]):
        p.append("the resolution order is inverted -- the flag must outrank the config, which "
                 "outranks the ask")
    if not re.search(r"(?:never|do not) prompt when", flat, re.I):
        p.append("the partial lost the never-prompt-when-it-is-already-resolved rule")

    # NOT keyed on the harness's wording. The previous version asserted the
    # literal string `away from your keyboard`, which is exactly what the rule
    # below forbids -- the guard violated the rule it existed to protect.
    if not re.search(r"auto-clos\w+", flat, re.I):
        p.append("the partial no longer addresses an auto-closed AskUserQuestion at all")
    if not re.search(r"as a park", flat, re.I):
        p.append("the partial lost the park-not-answer rule")
    for m in re.finditer(
        r"(?i)auto-clos\w+[^.]{0,90}?as (?:an? |the )?(?:answer|decision)"
        , flat
    ):
        # Test the negation at the ` as ` clause, not at `auto-clos`: the rule
        # reads "as a park, NEVER as an answer", so the negator sits after the
        # match starts and a check anchored at the start reds on the healthy file.
        at = m.start() + max(m.group(0).lower().rfind(" as "), 0)
        if not negated(flat, at):
            p.append("the partial treats an auto-closed question as a real answer -- the file's "
                     "whole reason for existing")
            break
    if re.search(r"proceed with the selected option", flat, re.I):
        # No negation exemption: there is no legitimate un-negated use, and the
        # nearby "never as an answer" exempted it when there was one.
        p.append("the partial tells the agent to act on an auto-closed selection")
    if not re.search(r"key on the meaning|judge by intent", flat, re.I):
        p.append("the partial lost its don't-match-a-literal-string rule")
    for m in re.finditer(
        r"(?i)match(?:ing)? (?:the |a )?(?:exact |specific )?(?:sentence|wording|phrase|string)", flat
    ):
        if not negated(flat, m.start()) and "would break" not in flat[m.start():m.start() + 140]:
            p.append("the partial now prescribes matching a literal harness sentence -- the "
                     "wording is not part of the interface")
            break

    if not re.search(r"reviewer runs (?:on|under) both", flat, re.I):
        p.append("the partial no longer states the reviewer runs on both options")
    if not re.search(r"overrides tier 2", flat, re.I) or not re.search(r"never tier 1", flat, re.I):
        p.append("guided mode's precedence (overrides tier 2, never tier 1) is gone")
    if not re.search(r"specified but (?:not built|unbuilt)", flat, re.I):
        p.append("the partial no longer says option C is unbuilt")
    for hit in new_conditionals(t):
        if "guided mode" in hit.lower() or "askUserQuestionTimeout" in hit:
            continue
        p.append(f"the partial gained conditional language that softens a rule: {hit!r}")
    return p


# --------------------------------------------------------------- the spec docs


_SPEC_PROPERTIES = (
    (r"(?:never|not) (?:inherited|skipped)", "the reviewer always runs"),
    (r"(?:not|never) delegated", "classification is not delegated to a third sub-agent"),
    (r"sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/", "the artifact directory is keyed per run"),
    (r"in the main checkout", "the artifact directory lives in the main checkout"),
    (r"sysop/runtime/parked/<CLAIM_ID>__<RUN_ID>\.md", "the park writes a marker file"),
    # PRESENT tense on purpose: `were unbuilt as of the last release; they now
    # ship` satisfied a bare `unbuilt` while asserting the opposite.
    (r"are unbuilt|are not built|is not built|have not yet shipped|not yet built",
     "part B's readers and cleanup are unbuilt"),
    (r"(?:only|sole) entry point", "Step 7-pre is the only entry point to Step 7"),
)


def workflow_problems(text=None) -> list[str]:
    """A SUBSET of the same properties, in the file the spec's readers read.

    Seven properties, not the sixty `orchestrator_problems` checks -- an earlier
    docstring said "the same properties" and that was the same overstatement this
    phase criticised elsewhere. What this covers is the shape's load-bearing
    claims: who reviews, who classifies, where the artifacts live, and that part
    B is unbuilt.

    Population was one file while the rules ship in four. Round 2 found
    `WORKFLOW_GUIDE.md` § 2 unguarded *and written by the same commit* -- the
    author-side rule-1 case applied to the guards themselves.
    """
    t = WORKFLOW.read_text(encoding="utf-8") if text is None else text
    p: list[str] = []
    s = section(t, "### 2.2 Planning", "### 2.3 Implementation")
    if s is None:
        return ["WORKFLOW.md § 2.2 Planning is gone"]
    n = norm(s)
    for pat, why in _SPEC_PROPERTIES:
        if not re.search(pat, n, re.I):
            p.append(f"WORKFLOW.md § 2.2 no longer states that {why}")
    for bad in ordering_violations(s):
        p.append(f"WORKFLOW.md § 2.2 states a stage order that contradicts the pipeline: {bad!r}")
    for hit in new_conditionals(s):
        p.append(f"WORKFLOW.md § 2.2 gained conditional language that softens a rule: {hit!r}")
    # Universal, not a presence test: a keyed path elsewhere in the section
    # satisfied a presence check while the working one lost its run component.
    for m in re.finditer(r"sysop/runtime/claim/<CLAIM_ID>/(?!<RUN_ID>)", n):
        p.append(f"WORKFLOW.md § 2.2 spells an artifact path without its run key: "
                 f"{n[max(0, m.start() - 60):m.end() + 20]!r}")
    if re.search(r"(?:they now ship|shipped with it|now ships|shipped alongside)", n, re.I):
        p.append("WORKFLOW.md § 2.2 claims part B ships -- the readers and close-time cleanup "
                 "are unbuilt, and claiming a reader that does not exist is what its own round "
                 "disqualified the first build for")
    if not re.search(r"/claim-task` keeps its three|`/claim-task` now reads and keeps them", t):
        p.append("WORKFLOW.md still describes /claim-task's envelopes as deleted after "
                 "consumption -- Step 8 forbids that delete, and the delete is #220's root cause")
    return p


def guide_problems(text=None) -> list[str]:
    t = GUIDE.read_text(encoding="utf-8") if text is None else text
    p: list[str] = []
    n = norm(t)
    for pat, why in (
        (r"spawns? an independent reviewer", "/claim-task spawns an independent reviewer"),
        (r"classifies the findings itself", "the orchestrator classifies the findings itself"),
        (r"sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/", "artifacts are per-run"),
        (r"manual path", "steps 3-5 are the manual path, not a second set of steps"),
    ):
        if not re.search(pat, n, re.I):
            p.append(f"WORKFLOW_GUIDE.md no longer states that {why}")
    return p


def reader_pairing_problems() -> list[str]:
    """The park filename shape and the reader it was chosen to match, pinned together.

    Round 2: nothing tied `review-close:1017`'s `{tid}__*.md` glob to the park's
    `<CLAIM_ID>__<RUN_ID>.md`, so changing either silently reopens the
    "removed by nothing" defect the filename shape exists to close.
    """
    p: list[str] = []
    rc = REVIEW_CLOSE.read_text(encoding="utf-8")
    if not re.search(r"parked'?\)?\.glob\(f'\{tid\}__\*\.md'\)", rc):
        p.append("/review-close Step 4c no longer globs `{tid}__*.md` under parked/ -- the park "
                 "marker filename shape was chosen to match it, and nothing else removes one")
    skill = SKILL.read_text(encoding="utf-8")
    hd = heredoc_containing(skill, '"parked"')
    if hd is None:
        p.append("the park block is gone, so the pairing cannot be checked")
    else:
        toks = tokens_for(parse(hd[1]) or ast.parse(""), "marker")
        if not any("__" in x and x.endswith(".md") for x in toks if isinstance(x, str)):
            p.append("the park marker no longer produces an `<id>__<run>.md` name, so "
                     "/review-close's glob cannot match it")
    return p


# ------------------------------------------------------------------- the tests


def test_orchestrator_shape_holds():
    assert orchestrator_problems() == []


def test_preference_partial_holds():
    assert partial_problems() == []


def test_workflow_spec_states_the_same_shape():
    assert workflow_problems() == []


def test_workflow_guide_states_the_same_shape():
    assert guide_problems() == []


def test_park_filename_and_its_reader_stay_paired():
    assert reader_pairing_problems() == []


def test_the_conditional_allowlist_is_exhaustive_and_live():
    """Each allowlisted clause must still be IN the file.

    An allowlist is the guard here, so a stale entry is a permanent hole: the
    clause it excuses is gone, and the entry now excuses whatever a future author
    writes near the same words.
    """
    corpus = " ".join(
        norm(unfenced(f.read_text(encoding="utf-8")))
        for f in (SKILL, WORKFLOW, PARTIAL, GUIDE)
    )
    stale = [c for c in CONDITIONAL_ALLOWLIST if c not in corpus]
    assert not stale, f"allowlisted clauses no longer in the file (permanent holes): {stale}"


def test_guards_are_not_vacuous():
    """Every check must be reachable: an empty corpus has to fail loudly.

    The first version **never executed its assertion** -- both probes raised
    `ValueError` in `_section` and hit `continue`. The threshold is high on
    purpose: round 2 measured 12 checks of slack against a threshold of 10, which
    let half the reachable set be deleted with the floor still green.
    """
    for probe in ("", "# nothing here\n", "---\nname: x\n---\n"):
        problems = orchestrator_problems(probe)
        assert len(problems) >= 20, (
            f"orchestrator_problems found only {len(problems)} problems in an empty corpus "
            f"-- most checks are unreachable: {problems}"
        )

    # **An empty corpus proves almost nothing, and round 3 measured exactly how
    # little: all 23 problems it produces are ANCHOR-ABSENCE ("Step 7b is gone",
    # "pipeline lost ### Step 7a"). Every AST check sits behind an
    # `if hd is None` early-out, so the entire code layer -- the checks that
    # carry this phase's headline properties -- could be deleted with the floor
    # green.** The floor that matters therefore feeds a corpus that is
    # STRUCTURALLY VALID and SEMANTICALLY WRONG: every anchor present, every
    # heredoc parseable, and the properties inverted. Each of these must be
    # caught by a check that an anchor-absence probe never reaches.
    skill = SKILL.read_text(encoding="utf-8")
    deep = {
        "artifact dir shared across runs": ("d = claim_root / run_id", "d = claim_root"),
        "artifact dir wrapped away": ("d = claim_root / run_id", "d = (claim_root / run_id).parent"),
        # Anchored on the park block's own next line — twin of `SKILL_MUTATIONS`'
        # entry; see the comment there for why the bare assignment stopped binding
        # the block this probe is about.
        "artifact dir out of the main checkout": (
            'main_root = Path(common).resolve().parent\n'
            'art = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id',
            "main_root = Path(__import__('os').environ['PWD'])\n"
            'art = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id'),
        "classification unkeyed": ('claim_id / run_id / "classification.md"',
                                   'claim_id / "classification.md"'),
        "integrity verdict inverted": ('"OK" if now == pre else "VIOLATED"',
                                       '"OK" if now != pre else "VIOLATED"'),
        "resume branch dead": ("if resume:", "if resume and False:"),
        "envelopes destroyed not moved": ("p.rename(prior / p.name)", "p.unlink()"),
        "park writes a directory": ('"{}__{}.md".format(claim_id, run_id)',
                                    '"{}__{}".format(claim_id, run_id)'),
        "pyyaml back in the classification write": ("import sys, json, subprocess",
                                                    "import sys, json, subprocess\nimport yaml"),
    }
    undetected = []
    for name, (old, new) in deep.items():
        assert old in skill, f"deep-probe anchor is stale ({name}) -- this floor proves nothing"
        i = skill.rindex(old)
        if not orchestrator_problems(skill[:i] + new + skill[i + len(old):]):
            undetected.append(name)
    assert not undetected, (
        f"the code layer is not reachable -- these inversions of the shape's own properties "
        f"are undetected: {undetected}. An anchor-absence probe cannot see this: every AST "
        f"check sits behind an `if hd is None` early-out."
    )
    for probe in ("", "# nothing\n"):
        assert len(partial_problems(probe)) >= 8, "partial_problems is unreachable on an empty corpus"
    assert len(workflow_problems("")) >= 1
    assert len(guide_problems("")) >= 4


def _mutate_last(text: str, old: str, new: str) -> str:
    """Apply at the LAST occurrence.

    `str.replace(old, new, 1)` hits the first match anywhere in the file, and
    this phase added ~400 lines above Step 7 -- which silently retargeted a
    mutation onto an earlier line and let it survive against an untouched gate.
    """
    i = text.rindex(old)
    return text[:i] + new + text[i + len(old):]


# Every mutation keeps the asserted phrases VERBATIM and inverts what the step
# DOES. **The classes are round 2's survivors, not the author's imagination** --
# it ran 100 and 74 lived, so these are copied from its report.
SKILL_MUTATIONS = {
    # -- the code that realizes the phase's headline property (8/8 survived) --
    "all runs share one directory": ("d = claim_root / run_id", "d = claim_root"),
    "classification drops the run key": (
        'claim_id / run_id / "classification.md"', 'claim_id / "classification.md"'),
    # Anchored on the park block's OWN next line, not on the bare `main_root =`
    # assignment. Phase 180 added two more prescribed blocks that resolve the main
    # root the same way, and the later of them sits BELOW the park block — so
    # `_last_sub`'s rindex retargeted this mutation onto a block no check here
    # inspects, and it survived while the park block sat untouched. Same class as
    # Phase 170's first-occurrence retarget, one index over: `rindex` fixed the
    # direction, not the ambiguity. Anchor on something the intended block alone
    # contains.
    "artifact dir back in the worktree": (
        'main_root = Path(common).resolve().parent\n'
        'art = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id',
        "main_root = Path(__import__('os').environ.get('PWD', '.'))\n"
        'art = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id'),
    "classification written to /tmp": (
        'out = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id / "classification.md"',
        'out = Path("/tmp") / "classification.md"'),
    "park drops the run key": (
        'art = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id',
        'art = main_root / "sysop" / "runtime" / "claim" / claim_id'),
    "park writes a directory again": ('"{}__{}.md".format(claim_id, run_id)',
                                      '"{}__{}".format(claim_id, run_id)'),
    # -- resume (7/8 survived) --------------------------------------------
    "resume inert again": ("if resume:", "if resume and False:"),
    "resume adopts a nonexistent run": ("if not d.is_dir():", "if False:"),
    "resume mints instead of adopting": ("    run_id = resume\n", "    run_id = resume\n    d.mkdir(parents=True, exist_ok=True)\n"),
    # -- the integrity verdict inverted -----------------------------------
    "integrity verdict inverted": ('"OK" if now == pre else "VIOLATED"',
                                   '"OK" if now != pre else "VIOLATED"'),
    # -- deletion (14/20 survived) ----------------------------------------
    "envelopes deleted instead of moved": ("p.rename(prior / p.name)", "p.unlink()"),
    "shell rm in Step 8": ("**Do not delete the envelopes here.**",
                           "```bash\nrm -rf sysop/runtime/subagent-envelopes/\n```\n\n**Do not delete the envelopes here.**"),
    "find -delete in Step 8": ("**Do not delete the envelopes here.**",
                               "```bash\nfind sysop/runtime/claim -name '*.md' -delete\n```\n\n**Do not delete the envelopes here.**"),
    "git clean in Step 8": ("**Do not delete the envelopes here.**",
                            "```bash\ngit clean -fdx sysop/runtime/claim/\n```\n\n**Do not delete the envelopes here.**"),
    "truncation in Step 8": ("**Do not delete the envelopes here.**",
                             "```bash\n: > sysop/runtime/subagent-envelopes/exec.json\n```\n\n**Do not delete the envelopes here.**"),
    "prose delete of the artifact dir": (
        "- **abandon** → release the claim, **and commit the release**:",
        "- **abandon** → remove the artifact directory, then release the claim:"),
    # -- optional-ising outside the previously-scanned slices (13/13) -----
    "7a declared optional": ("### Step 7a: Spawn the planner",
                             "### Step 7a: Spawn the planner\n\n> **This step is OPTIONAL and may be skipped.**"),
    "failure handling made advisory": (
        "### Failure handling — one rule per spawn point",
        "### Failure handling — one rule per spawn point\n\n> Optional guidance, applied at your discretion."),
    "step 8 framed as legacy": ("**Do not delete the envelopes here.**",
                                "> Legacy guidance; superseded by close-time cleanup.\n\n**Do not delete the envelopes here.**"),
    "7b superseded framing": ("### Step 7b: Spawn the reviewer",
                              "### Step 7b: Spawn the reviewer\n\n> Superseded by the collapsed reviewer-executor shape."),
    "7c retained-for-history framing": ("### Step 7c: Classify the findings",
                                        "### Step 7c: Retained for historical interest; the current pipeline does not run it. Classify the findings"),
    "7b optional via a semicolon clause": (
        "**Always.** Review is never inherited",
        "**Always.** There is no reason to run 7b; it is optional. Review is never inherited"),
    "7b optional via a colon clause": (
        "**Always.** Review is never inherited",
        "**Always.** Nothing here is mandatory: 7b is optional. Review is never inherited"),
    "7b config-gated skip": (
        "**Always.** Review is never inherited",
        "**Always.** When `<project>/CLAUDE.md § Fast path` is set, bypass this step entirely. Review is never inherited"),
    "7b omit-unless": (
        "**Always.** Review is never inherited",
        "**Always.** Omit this step unless the plan is large. Review is never inherited"),
    # -- reordering in prose (4/4 survived) -------------------------------
    "executor before reviewer, in prose": (
        "### Step 7e: Spawn the executor",
        "### Step 7e: Spawn the executor\n\nThe executor precedes the reviewer."),
    "run 7e before 7b": ("### Step 7e: Spawn the executor",
                         "### Step 7e: Spawn the executor\n\nRun 7e before 7b on every claim."),
    "stage order inverted in a chain": (
        "### Step 7-pre: resolve the run and its artifact directory",
        "### Step 7-pre: resolve the run and its artifact directory\n\n**Order of operations:** 7a → 7e → 7b."),
    # -- scoping / neighbouring blocks (9/11 survived) --------------------
    "7c delegates without the word spawn": (
        "Apply the **Classification Rubric**",
        "Delegate the rubric to a fresh sub-agent for a second opinion. Apply the **Classification Rubric**"),
    "7b asked to classify": ("Report findings only.",
                             "Classify each finding as fixable or blocker yourself. Report findings only."),
    "reviewer template made optional": (
        "copied verbatim from `.claude/skills/_shared/adversarial-review.md`",
        "copied from anywhere you like"),
    "executor writes its own envelope": (
        "Do **NOT** write to `sysop/runtime/subagent-envelopes/`.",
        "Write your envelope to `sysop/runtime/subagent-envelopes/` yourself."),
    "never-proceed softened by a following clause": (
        "**Never proceed to 7e.** This is the single most important rule in the pipeline.",
        "**Never proceed to 7e.** In practice, continue to the executor anyway if the reviewer keeps failing."),
    # -- frontmatter (3/7 survived) ---------------------------------------
    "tools granted back": ("disallowed-tools: Edit, Write, NotebookEdit\n",
                           "allowed-tools: Edit, Write, Bash\ndisallowed-tools: Edit, Write, NotebookEdit\n"),
    "model downgraded": ("model: opus\n", "model: haiku\n"),
    "second frontmatter block": ("disallowed-tools: Edit, Write, NotebookEdit\n---\n",
                                 "disallowed-tools: Edit, Write, NotebookEdit\n---\n\n---\ndisallowed-tools:\n---\n"),
    "duplicate disallowed-tools key": ("disallowed-tools: Edit, Write, NotebookEdit\n",
                                       "disallowed-tools: Edit, Write, NotebookEdit\ndisallowed-tools:\n"),
    "frontmatter guard dropped": ("disallowed-tools: Edit, Write, NotebookEdit\n", ""),
    # -- injection (3/5 survived) -----------------------------------------
    "park reason double-quoted again": ("\"<BRANCH_NAME>\" '<PARK_REASON>'",
                                        '"<BRANCH_NAME>" "<PARK_REASON>"'),
    # -- the originals, which still have to die ---------------------------
    "batch abandon misrouted": ("bash sysop/scripts/batch_work.sh --release <BATCH_NUMBER>",
                                "bash sysop/scripts/claim_task.sh --release <BATCH_NUMBER>"),
    "7c depends on pyyaml again": ("import sys, json, subprocess",
                                   "import sys, json, subprocess\nimport yaml"),
    "plan mode restored": ("### Step 7a: Spawn the planner",
                           "### Step 7a: Spawn the planner\n\nCall `EnterPlanMode` first."),
    "a second re-entry point appears": (
        "**Orchestrator context exhaustion mid-pipeline**",
        "**On a resume, restart at 7e with the parked artifacts as context.**\n\n**Orchestrator context exhaustion mid-pipeline**"),
    "part-B readers claimed as existing": (
        "Close-time cleanup of the artifact set is part B of this reshape and is not built.",
        "Close-time cleanup of the artifact set is owned by `/review-close` Step 4c today."),
    "7d revise re-plans into the same run": (
        "then go back to Step 7-pre and mint a **new** run", "then re-plan into this run"),
    "batch resume loses the branch": (
        "**Read `<BRANCH_NAME>` and the worktree path out of `sysop/runtime/locks/<CLAIM_ID>.lock`**",
        "**Read what you need out of the lock**"),
}


def _fence_mutation(t: str) -> str:
    """Re-fence the classification write as ```text."""
    i = t.rindex('report = {')
    return t[:t.rindex("```bash", 0, i)] + "```text" + t[t.rindex("```bash", 0, i) + len("```bash"):]


def _commented_out_mutation(t: str) -> str:
    """Comment out the CLASSIFICATION write specifically.

    Anchored on its own format string, not on `out.write_text(` -- Step 8's new
    outcome block uses the same variable name, so `rindex` retargeted onto it and
    the mutation stopped testing what it names. Third appearance in this phase of
    "adding text to a file weakens every occurrence-indexed mutation over it".
    """
    j = t.index("# Classification — {} run {}")
    i = t.index("out.write_text(", t.rindex("out = ", 0, j) if "out = " in t[:j] else 0)
    i = t.index("out.write_text(", j - 400)
    return t[:i] + "# " + t[i:t.index("\n", i)] + t[t.index("\n", i):]


def test_orchestrator_guards_kill_semantic_inversions():
    t = SKILL.read_text(encoding="utf-8")
    survivors, no_ops = [], []
    for name, (old, new) in SKILL_MUTATIONS.items():
        if old not in t:
            no_ops.append(name)
            continue
        mutated = _mutate_last(t, old, new)
        if mutated == t:
            no_ops.append(name)
        elif not orchestrator_problems(mutated):
            survivors.append(name)
    for name, fn in (("classification re-fenced as text", _fence_mutation),
                     ("classification write commented out", _commented_out_mutation)):
        mutated = fn(t)
        if mutated == t:
            no_ops.append(name)
        elif not orchestrator_problems(mutated):
            survivors.append(name)
    assert not no_ops, f"mutations became no-ops (stale anchors): {no_ops}"
    assert not survivors, f"mutations survived the guards: {survivors}"


PARTIAL_MUTATIONS = {
    "resolution order inverted": (
        "1. **`--review-plan` / `--no-review-plan`** on the invocation — the per-run override.",
        "1. **Ask** — an `AskUserQuestion`; the flag is consulted last."),
    "auto-closed question becomes the decision": (
        "**do not treat the answer as a decision**", "**treat the auto-closed answer as a decision**"),
    "park rule dropped": ("treat an auto-closed question as a park, never as an answer",
                          "treat an auto-closed question however seems best"),
    "park rule softened by a trailing clause": (
        "as a park, never as an answer", "as a park, never as an answer (in practice, proceed with the selected option)"),
    "literal-string rule inverted": ("**Key on the meaning, not on a literal string.**",
                                     "**Match the exact sentence the harness injects.**"),
    "reviewer no longer runs on both": ("**The reviewer runs on both.**",
                                        "**The reviewer runs on option A only.**"),
    "reviewer optional under B": ("**The reviewer runs on both.**",
                                  "**The reviewer runs on both.** Under option B you may omit it."),
    "guided mode takes tier 1 too": ("**It overrides tier 2, never tier 1.**",
                                     "**It overrides every tier.**"),
    "guided mode made optional": ("**It overrides tier 2, never tier 1.**",
                                  "**It overrides tier 2, never tier 1.** Applying it is optional."),
    "flag demoted to advisory": (
        "on the invocation — the per-run override.\n   Always wins.",
        "on the invocation — advisory only; the config below wins."),
    "never-prompt rule dropped": ("**Never prompt when tier 1 or tier 2 resolves.**",
                                  "**Prompt whenever you are unsure.**"),
    "option C silently offered": ("**A third option, plan-only, is specified but not built**",
                                  "**A third option, plan-only, is available**"),
}


def test_partial_guards_kill_semantic_inversions():
    t = PARTIAL.read_text(encoding="utf-8")
    survivors, no_ops = [], []
    for name, (old, new) in PARTIAL_MUTATIONS.items():
        if old not in t:
            no_ops.append(name)
        elif not partial_problems(_mutate_last(t, old, new)):
            survivors.append(name)
    assert not no_ops, f"partial mutations became no-ops (stale anchors): {no_ops}"
    assert not survivors, f"partial mutations survived the guards: {survivors}"


WORKFLOW_MUTATIONS = {
    "reviewer becomes skippable": ("This step always runs — review is never inherited and never skipped",
                                   "This step runs when the preference calls for it"),
    "classification delegated": ("Not delegated to a third sub-agent", "Delegated to a third sub-agent"),
    "artifact dir loses its run key": (
        "`sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/` **in the main checkout**",
        "`sysop/runtime/claim/<CLAIM_ID>/`"),
    "part B claimed as built": ("are part B of the reshape and are unbuilt",
                                "are part B of the reshape and shipped with it"),
    "part B shipped-as-of-last-release": ("are part B of the reshape and are unbuilt",
                                          "were unbuilt as of the last release; they now ship"),
}


def test_workflow_guards_kill_semantic_inversions():
    t = WORKFLOW.read_text(encoding="utf-8")
    survivors, no_ops = [], []
    for name, (old, new) in WORKFLOW_MUTATIONS.items():
        if old not in t:
            no_ops.append(name)
        elif not workflow_problems(_mutate_last(t, old, new)):
            survivors.append(name)
    assert not no_ops, f"workflow mutations became no-ops (stale anchors): {no_ops}"
    assert not survivors, f"workflow mutations survived the guards: {survivors}"


def test_negative_controls_do_not_fire():
    """A guard that reds on a legitimate rewrite is a defect in the other
    direction, and it is the one that hides.

    **Round 2 measured 21 of 33 legitimate rewrites going red.** Every one it
    named is here, including the three YAML spellings of one frontmatter value,
    the five code refactors that *improve* the block, and the two negated
    prohibitions whose negator sits more than 48 characters left of the verb --
    the module's named failure mode, on its fifth appearance.
    """
    t = SKILL.read_text(encoding="utf-8")
    rewrites = {
        # --- YAML spellings of one value ---------------------------------
        "frontmatter as a flow sequence": t.replace(
            "disallowed-tools: Edit, Write, NotebookEdit",
            "disallowed-tools: [Edit, Write, NotebookEdit]", 1),
        "frontmatter quoted": t.replace(
            "disallowed-tools: Edit, Write, NotebookEdit",
            'disallowed-tools: "Edit, Write, NotebookEdit"', 1),
        "frontmatter as a block list": t.replace(
            "disallowed-tools: Edit, Write, NotebookEdit",
            "disallowed-tools:\n  - Edit\n  - Write\n  - NotebookEdit", 1),
        "a YAML comment after the value": t.replace(
            "disallowed-tools: Edit, Write, NotebookEdit",
            "disallowed-tools: Edit, Write, NotebookEdit  # partial by design", 1),
        "the denied tools reordered": t.replace(
            "disallowed-tools: Edit, Write, NotebookEdit",
            "disallowed-tools: NotebookEdit, Write, Edit", 1),
        # --- code refactors that change nothing semantic ------------------
        "marker name as an f-string": t.replace(
            '"{}__{}.md".format(claim_id, run_id)', 'f"{claim_id}__{run_id}.md"', 1),
        "argv unpacked as a slice": t.replace(
            "claim_id, run_id, branch, reason = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]",
            "claim_id, run_id, branch, reason = sys.argv[1:5]", 1),
        "token_urlsafe for token_hex": t.replace(
            "secrets.token_hex(4)", "secrets.token_urlsafe(6)", 1),
        "os.replace for rename": t.replace(
            "p.rename(prior / p.name)", "__import__('os').replace(p, prior / p.name)", 1),
        "rev-parse --verify": t.replace(
            '"git", "-C", worktree, "rev-parse", "HEAD"',
            '"git", "-C", worktree, "rev-parse", "--verify", "HEAD"', 1),
        "a comment added inside a block": t.replace(
            "import sys, secrets, datetime, subprocess",
            "# resolve the main checkout, then mint or adopt\nimport sys, secrets, datetime, subprocess", 1),
        # --- prose tightenings -------------------------------------------
        "reviewer rule reworded": t.replace(
            "Review is never inherited, never skipped",
            "Review is not inherited from a prior run and is not skipped", 1),
        "sole entry point": t.replace("the only entry point to Step 7", "the sole entry point to Step 7", 1),
        "never in a shell variable": t.replace("not in a shell variable", "never in a shell variable", 1),
        "specified but unbuilt": t.replace("specified but not built", "specified but unbuilt", 1),
        "reflowed whitespace": t.replace(
            "**Always.** Review is never inherited", "**Always.**  Review is never inherited", 1),
        "Always without the period": t.replace(
            "**Always.** Review is never inherited", "**Always** — Review is never inherited", 1),
        "never delegated instead of not delegated": t.replace(
            "**This is not delegated to a third sub-agent**",
            "**This is never delegated to a third sub-agent**", 1),
        "lowercase envelope prohibition": t.replace(
            "Do **NOT** write to `sysop/runtime/subagent-envelopes/`",
            "Do **not** write to `sysop/runtime/subagent-envelopes/`", 1),
        "7e-must-never-be-reached phrasing": t.replace(
            "**Never proceed to 7e.**", "**7e must never be reached without a review.**", 1),
        # --- negated prohibitions with a long clause ----------------------
        "a long-winded prohibition on spawning": t.replace(
            "**This is not delegated to a third sub-agent**",
            "**Do not, under any circumstances and regardless of how long the queue has grown, "
            "spawn a sub-agent for this. This is not delegated to a third sub-agent**", 1),
        "a long-winded prohibition on proceeding": t.replace(
            "**Never proceed to 7e.**",
            "**Under no circumstances, however tempting the shortcut looks after a long run, "
            "proceed to 7e.**", 1),
        "the sentence forbidding the thing": t.replace(
            "**Always.** Review is never inherited",
            "**Always.** Do not skip this step under any preference. Review is never inherited", 1),
    }
    for name, rewritten in rewrites.items():
        assert rewritten != t, f"{name}: no-op rewrite -- the control proves nothing"
        got = orchestrator_problems(rewritten)
        assert got == [], f"guard fired on a legitimate rewrite ({name}) -- over-strict: {got}"


def test_partial_negative_controls_do_not_fire():
    t = PARTIAL.read_text(encoding="utf-8")
    rewrites = {
        "the harness quote reworded": t.replace(
            "and tells Claude you may be away from your keyboard",
            "and tells Claude the human may have stepped away", 1),
        "park rule reflowed": t.replace(
            "treat an auto-closed question as a park, never as an answer",
            "treat an auto-closed question as a park — never as an answer", 1),
        "do-not-prompt phrasing": t.replace(
            "**Never prompt when tier 1 or tier 2 resolves.**",
            "**Do not prompt when tier 1 or tier 2 resolves.**", 1),
        "judge-by-intent phrasing": t.replace(
            "**Key on the meaning, not on a literal string.**",
            "**Judge by intent rather than by exact wording.**", 1),
        "reviewer runs under both options": t.replace(
            "**The reviewer runs on both.**", "**The reviewer runs under both options.**", 1),
        "specified but unbuilt": t.replace("specified but not built", "specified but unbuilt", 1),
    }
    for name, rewritten in rewrites.items():
        assert rewritten != t, f"{name}: no-op rewrite -- the control proves nothing"
        got = partial_problems(rewritten)
        assert got == [], f"guard fired on a legitimate rewrite ({name}) -- over-strict: {got}"
