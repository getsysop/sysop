"""A skill's runner text, wherever it lives (Phase 384, `Q-409` P1).

`tools/RUNNER_CORE_SPLIT_SPEC.md` splits a skill's `SKILL.md` into a core plus step files
under `<skill>/steps/`, each read only when its arm fires. Phase 382 measured what that does
to a guard that enumerates `glob("*/SKILL.md")`: a defect planted in a step file was caught in
`SKILL.md` and missed in the step file. This module is the one place a guard asks "what text
does this skill's runner read" instead.

* `step_files(skill_dir)`: every `.md` below the skill's top level, with the installer's own
  skips (`install.sh` `_install_skill_tree`): dotfiles, `__pycache__/`, symlinked directories.
  `REFERENCE.md` and any other top-level sibling of `SKILL.md` are editor text and excluded.
* `skill_text(skill_dir)`: `SKILL.md` with each `<!-- sysop:arm=<name> -->` line replaced by
  `steps/<name>.md`, in document order. A marker whose step file is missing raises. A step
  file no marker names is appended, so it is still scanned: text the runner cannot reach is
  a defect of its own, and a guard that skipped it would hide one.
* `runner_files(skills_dir)`: each `SKILL.md`, then its step files, for a guard that reports
  per file.
* `runner_texts(skills_dir)`: `{skill name: skill_text}`, for a guard that judges per skill.
* `skill_of(path, skills_dir)`: the skill a runner file belongs to (a step file's parent is
  `steps`, not the skill).
* `text_of(path)`: `skill_text` for a `SKILL.md` path, the file as it is otherwise (Phase 385),
  for a reader that keeps one path per file and changes only its read.
* `runner_key(path)` / `fold_steps(paths)`: a step file stands for its skill's `SKILL.md`
  (Phase 385), for a per-file census that pins which file carries a match.

Class E readers (`test_reader_census.py`, `test_skill_frontmatter_parses.py`) want the core
alone and must not use this. `test_skill_runner_text.py`'s static guard holds the line.
"""
from __future__ import annotations

import re
from pathlib import Path

from _prose_guard_helpers import _fence_state

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"

# A marker is a whole line outside any fence. Its name is one or more `/`-separated
# segments, each starting with a letter or digit, so `..` cannot climb out of `steps/`.
_MARKER = re.compile(r"^<!-- sysop:arm=(\S+) -->[ \t]*$")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def _walk(d: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(d.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_dir():
            if p.is_symlink() or p.name == "__pycache__":
                continue
            out += _walk(p)
        elif p.is_file() and p.suffix == ".md":
            out.append(p)
    return out


def step_files(skill_dir: Path) -> list[Path]:
    """Every `.md` in the skill's subdirectories, sorted, with the installer's skips."""
    out: list[Path] = []
    for p in sorted(skill_dir.iterdir()):
        if p.is_dir() and not p.is_symlink() and p.name != "__pycache__" \
                and not p.name.startswith("."):
            out += _walk(p)
    return out


def skill_text(skill_dir: Path) -> str:
    """`SKILL.md` with each arm marker spliced, and unreferenced step files appended.

    The marker line becomes the step's text less exactly one trailing newline, so the
    splice reproduces the unsplit file byte for byte whether the blank line after a moved
    section stayed in the core or moved with it (Phase 384's round: `rstrip` lost it). A
    marker inside a fence is an example, not an arm."""
    skill_dir = Path(skill_dir)
    lines = (skill_dir / "SKILL.md").read_text(encoding="utf-8").split("\n")
    used: set[Path] = set()
    out: list[str] = []
    for i, fenced in _fence_state(lines):
        m = None if fenced else _MARKER.match(lines[i])
        if not m:
            out.append(lines[i])
            continue
        name = m.group(1)
        if not _NAME.fullmatch(name):
            raise ValueError(f"{skill_dir.name}/SKILL.md:{i + 1}: arm name {name!r} is not "
                             "a path below steps/")
        step = skill_dir / "steps" / f"{name}.md"
        if not step.is_file():
            raise FileNotFoundError(
                f"{skill_dir.name}/SKILL.md marks arm {name!r}, and "
                f"steps/{name}.md does not exist")
        used.add(step)
        body = step.read_text(encoding="utf-8")
        out.append(body[:-1] if body.endswith("\n") else body)
    text = "\n".join(out)
    for step in step_files(skill_dir):
        if step not in used:
            text = text.rstrip("\n") + "\n\n" + step.read_text(encoding="utf-8")
    return text


def text_of(path: Path, errors: str = "strict") -> str:
    """A file's text as its reader should see it: a `SKILL.md` is `skill_text` of its
    directory, and any other file is read as it is (with `errors`, for a reader that scans
    binary-adjacent files). For a reader that keeps a path per file (a dict keyed by path, a
    list of files to scan) and changes only its read expression."""
    path = Path(path)
    if path.name == "SKILL.md":
        return skill_text(path.parent)
    return path.read_text(encoding="utf-8", errors=errors)


def runner_key(path):
    """The path a per-file census should key a runner file by: a step file's skill's
    `SKILL.md`, and anything else itself. Same type as given (`str` or `Path`).

    A census that pins *which file* carries a match (an exact population, an allowlist
    keyed by file, a per-file count) changes key when a step moves, and goes red on a move
    that changed nothing a runner reads. Phase 384 keyed the screens' corpus this way."""
    p = Path(path)
    for anc in list(p.parents)[1:]:
        if (anc / "SKILL.md").is_file():
            if _is_step(anc, p):
                key = anc / "SKILL.md"
                return key if isinstance(path, Path) else key.as_posix()
            break
    return path


def _is_step(skill_dir: Path, p: Path) -> bool:
    """`p` is one of `step_files(skill_dir)`, decided from its path: a `.md` file below a
    subdirectory, through no dot, `__pycache__` or symlinked directory."""
    if p.suffix != ".md" or p.name.startswith(".") or not p.is_file():
        return False
    d = p.parent
    while d != skill_dir:
        if d.name.startswith(".") or d.name == "__pycache__" or d.is_symlink():
            return False
        d = d.parent
    return True


def fold_steps(paths) -> list:
    """`paths` with each step file replaced by its skill's `SKILL.md`, once, at the first
    position either appears. Read each `SKILL.md` it returns with `text_of`, so the step
    text is still scanned, once, under the key the census had before the move."""
    out, seen = [], set()
    for p in paths:
        k = runner_key(p)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _skill_dirs(skills_dir: Path) -> list[Path]:
    return sorted(p.parent for p in Path(skills_dir).glob("*/SKILL.md"))


def runner_files(skills_dir: Path = SKILLS_DIR) -> list[Path]:
    """Each skill's `SKILL.md` followed by its step files."""
    out: list[Path] = []
    for d in _skill_dirs(skills_dir):
        out += [d / "SKILL.md", *step_files(d)]
    return out


def runner_texts(skills_dir: Path = SKILLS_DIR) -> dict[str, str]:
    """`{skill name: skill_text}` for every skill directory holding a `SKILL.md`."""
    return {d.name: skill_text(d) for d in _skill_dirs(skills_dir)}


def skill_of(path: Path, skills_dir: Path = SKILLS_DIR) -> str:
    """The skill directory's name for any file under it."""
    return Path(path).resolve().relative_to(Path(skills_dir).resolve()).parts[0]
