"""Every shipped skill's YAML frontmatter parses under a strict YAML loader.

Nothing in this repo parses skill frontmatter strictly: `_model_roles.py` and the
installer read it line by line, so an unquoted `: ` inside `description:` blocks
nothing here. It still hands a strict consumer — a harness, a plugin validator, a
linter — a mapping error instead of a description. Phase 292 found two skills in
that state (`intake`, `share-wins`) and Phase 326 fixed both; this keeps the class
from coming back one description edit at a time.

PyYAML's `SafeLoader` is not strict on its own: it keeps the last of two duplicate
keys, and it turns `model: yes` into a bool. So the loader here rejects duplicates,
and every known key must come back a string. Phase 326's round showed both gaps.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
SKILL_FILES = sorted(SKILLS.glob("*/SKILL.md"))
STRING_KEYS = ("name", "description", "argument-hint", "model", "disallowed-tools")


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def frontmatter(text: str) -> str:
    lines = text.split("\n")
    assert lines[0] == "---", "a SKILL.md must open with a `---` frontmatter fence"
    end = lines.index("---", 1)
    return "\n".join(lines[1:end])


def parse(text: str):
    """The one parse every test here goes through, so the controls below exercise it."""
    return yaml.load(frontmatter(text), Loader=_UniqueKeyLoader)


def check(path: Path) -> None:
    """The per-skill assertion. Each control below runs a broken file through this very
    function, one control per way the file can be wrong."""
    data = parse(path.read_text(encoding="utf-8"))
    name = path.parent.name
    assert isinstance(data, dict), f"{name}: frontmatter is not a mapping"
    assert data.get("name") == name, f"{name}: `name:` is {data.get('name')!r}"
    for key in STRING_KEYS:
        if key in data:
            assert isinstance(data[key], str), f"{name}: `{key}:` is {type(data[key]).__name__}"
    assert isinstance(data.get("description"), str) and data["description"].strip(), (
        f"{name}: `description:` is missing or empty"
    )
    # An unquoted ` #` starts a YAML comment, so the loader silently cuts the description
    # short. Compare a plain one-line value with what was parsed from it.
    raw = next((ln.split(":", 1)[1].strip() for ln in frontmatter(path.read_text(encoding="utf-8")).split("\n")
                if ln.startswith("description:")), "")
    if raw and raw[0] not in "'\"|>":
        assert data["description"] == raw, f"{name}: `description:` was truncated to {data['description']!r}"


def test_the_population_is_every_shipped_skill() -> None:
    # Derived, not a floor: every skill directory under core/skills (`_shared/` holds
    # partials with no SKILL.md). A floor is lowerable to whatever population survives.
    dirs = sorted(p.name for p in SKILLS.iterdir() if p.is_dir() and p.name != "_shared")
    assert [p.parent.name for p in SKILL_FILES] == dirs


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_frontmatter_is_strict_yaml(path: Path) -> None:
    check(path)


def _skill(tmp_path: Path, body: str) -> Path:
    skill = tmp_path / "intake" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("---\n" + body + "---\nbody\n")
    return skill


@pytest.mark.parametrize("body, raises", [
    # The pre-Phase-326 `intake` shape: an unquoted `: ` inside the description.
    ("name: intake\ndescription: Front door. Interactive: brain-dump.\n", yaml.YAMLError),
    ("name: intake\ndescription: one\ndescription: two\n", yaml.YAMLError),
    ("name: other\ndescription: Front door.\n", AssertionError),
    ("name: intake\ndescription: \"\"\n", AssertionError),
    ("name: intake\ndescription: Front door.\nmodel: yes\n", AssertionError),
    ("name: intake\ndescription: Front door.\nargument-hint: [--x]\n", AssertionError),
    ("name: intake\ndescription: Front door. #1 routing source\n", AssertionError),
    ("name: intake\ndescription: Front door.\ndisallowed-tools:\n", AssertionError),
], ids=["unquoted-colon", "duplicate-key", "name-mismatch", "empty-description",
        "bool-model", "list-argument-hint", "hash-truncation", "blank-disallowed-tools"])
def test_the_check_sees_each_defect(tmp_path: Path, body: str, raises) -> None:
    with pytest.raises(raises):
        check(_skill(tmp_path, body))


def test_the_check_accepts_a_legal_file(tmp_path: Path) -> None:
    check(_skill(tmp_path, "name: intake\ndescription: \"Front door: brain-dump.\"\n"
                           "argument-hint: \"[--x]\"\nmodel: opus\n"))
