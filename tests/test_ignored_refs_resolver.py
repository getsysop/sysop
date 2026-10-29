"""`Q-644` (Phase 356): `ignored_refs.py` reads the consumer's resolver configuration.

Phase 354's check matched a reference by its text alone, so a file named only through a
scoped tsconfig alias (`import a from "@fixtures/a.json"`) or served from a Next.js
`public/` directory (`<img src="/logo.png">`) was never asked about, and the branch merged
without it. Wade ruled on 2026-10-04: read `tsconfig.json`/`jsconfig.json`
`compilerOptions.paths` and a `public/` directory beside a Next config; leave names built at
run time unseen, and say so.

Everything here runs the script against a fixture repository.
"""

from __future__ import annotations

import json

import pytest

from test_ignored_refs import _g, _refs, _repo, _run, _worktree, _write

IGNORE = "*.json\n*.png\n!tsconfig.json\n!jsconfig.json\nsysop/runtime/\n"

TSCONFIG = """{
  // a comment, as tsconfig files carry, and a `//` inside a string that is not one
  "$schema": "https://json.schemastore.org/tsconfig",
  "compilerOptions": {
    "baseUrl": ".",
    /* and a block comment */
    "paths": {
      "@fixtures/*": ["test/fixtures/*"],
      "@cfg/*": ["config/*"],
      "@exact": ["config/exact.json"],
      "@/*": ["src/*"],
    },
  },
}
"""


def _alias_repo(tmp_path, config: str | None = TSCONFIG, name: str = "tsconfig.json"):
    files = {"app/page.ts": "export const x = 1\n"}
    if config is not None:
        files[name] = config
    root = _repo(tmp_path, gitignore=IGNORE, files=files)
    return root, _worktree(root, tmp_path)


def test_premise_the_fixture_tsconfig_is_not_json():
    """The comments and trailing commas are why a plain `json.loads` would not do."""
    with pytest.raises(json.JSONDecodeError):
        json.loads(TSCONFIG)


@pytest.mark.parametrize("line,want", [
    ('import a from "@fixtures/a.json"', "test/fixtures/a.json"),     # the filed shape
    ("import cfg from '@cfg/local'", "config/local.json"),             # extension completed
    ('const e = require("@exact")', "config/exact.json"),              # a pattern with no `*`
    ("import k from `@fixtures/k.json`", "test/fixtures/k.json"),     # a backtick is a quote
])
def test_a_tsconfig_alias_resolves(tmp_path, line, want):
    _, wt = _alias_repo(tmp_path)
    _write(wt, want, "{}")
    _write(wt, "src/page.ts", line + "\n")
    r = _run(wt)
    assert r.returncode == 1 and _refs(r.stdout) == [want], r.stdout + r.stderr
    assert "1 resolver configs read" in r.stdout, r.stdout


def test_without_the_config_the_alias_is_unseen_as_before(tmp_path):
    _, wt = _alias_repo(tmp_path, config=None)
    _write(wt, "test/fixtures/a.json", "{}")
    _write(wt, "src/page.ts", 'import a from "@fixtures/a.json"\n')
    r = _run(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 resolver configs read" in r.stdout, r.stdout


def test_a_jsconfig_is_read_too(tmp_path):
    _, wt = _alias_repo(tmp_path, name="jsconfig.json")
    _write(wt, "test/fixtures/a.json", "{}")
    _write(wt, "src/page.js", "import a from '@fixtures/a.json'\n")
    assert _refs(_run(wt).stdout) == ["test/fixtures/a.json"]


def test_the_nearest_config_governs_and_paths_default_to_its_directory(tmp_path):
    """No `baseUrl`: TypeScript resolves `paths` from the config's own directory."""
    cfg = '{"compilerOptions": {"paths": {"@data/*": ["./data/*"]}}}'
    root = _repo(tmp_path, gitignore=IGNORE, files={"apps/web/tsconfig.json": cfg,
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "apps/web/data/a.json", "{}")
    _write(wt, "data/a.json", "{}")
    _write(wt, "apps/web/src/page.ts", "import a from '@data/a.json'\n")
    _write(wt, "other/page.ts", "import a from '@data/b.json'\n")
    r = _run(wt)
    assert _refs(r.stdout) == ["apps/web/data/a.json"], r.stdout + r.stderr


def test_a_nearer_config_without_paths_defers_to_an_outer_one(tmp_path):
    """Stated, not TypeScript's own rule: without `extends` followed, a package config with
    no `paths` usually inherits them, so deferring trades a question for a missed break."""
    root = _repo(tmp_path, gitignore=IGNORE,
                 files={"tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./fixtures/*"]}}}',
                        "pkg/tsconfig.json": "{}", "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "fixtures/a.json", "{}")
    _write(wt, "pkg/x.ts", 'import a from "@/a.json"\n')
    r = _run(wt)
    assert _refs(r.stdout) == ["fixtures/a.json"], r.stdout + r.stderr
    assert "2 resolver configs read" in r.stdout, r.stdout


def test_the_longest_matching_prefix_wins(tmp_path):
    # Both orders: a "first match wins" and a "last match wins" reading each fail one.
    cfg = ('{"compilerOptions": {"paths": {"@app/*": ["wrong/*"], '
           '"@app/fixtures/*": ["right/*"], "@app/f*": ["wrong2/*"]}}}')
    _, wt = _alias_repo(tmp_path, config=cfg)
    _write(wt, "wrong/fixtures/a.json", "{}")
    _write(wt, "wrong2/ixtures/a.json", "{}")
    _write(wt, "right/a.json", "{}")
    _write(wt, "src/page.ts", "import a from '@app/fixtures/a.json'\n")
    assert _refs(_run(wt).stdout) == ["right/a.json"]


def test_paths_resolve_from_base_url_relative_to_the_config(tmp_path):
    cfg = '{"compilerOptions": {"baseUrl": "./src", "paths": {"@f/*": ["fixtures/*"]}}}'
    root = _repo(tmp_path, gitignore=IGNORE, files={"web/tsconfig.json": cfg,
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    for rel in ("web/src/fixtures/a.json", "web/fixtures/a.json", "src/fixtures/a.json"):
        _write(wt, rel, "{}")
    _write(wt, "web/src/page.ts", "import a from '@f/a.json'\n")
    assert _refs(_run(wt).stdout) == ["web/src/fixtures/a.json"]


def test_a_base_url_outside_the_workspace_resolves_nothing(tmp_path):
    """`_norm` answers None for `..`; read as the root, every alias would resolve there."""
    cfg = '{"compilerOptions": {"baseUrl": "../elsewhere", "paths": {"@f/*": ["f/*"]}}}'
    _, wt = _alias_repo(tmp_path, config=cfg)
    _write(wt, "f/a.json", "{}")
    _write(wt, "src/page.ts", "import a from '@f/a.json'\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout


def test_a_next_config_deleted_in_the_worktree_serves_no_public_directory(tmp_path):
    root = _repo(tmp_path, gitignore=IGNORE, files={"next.config.js": "module.exports = {}\n",
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    (wt / "next.config.js").unlink()
    _write(wt, "public/logo.png", "png")
    _write(wt, "app/page.tsx", '<img src="/logo.png" />\n')
    r = _run(wt)
    assert r.returncode == 0 and "0 resolver configs read" in r.stdout, r.stdout


@pytest.mark.parametrize("pkg", ["{}", "{ not json",
                                 '{"compilerOptions": {"baseUrl": "../..", "paths": {"@f/*": ["f/*"]}}}'])
def test_a_nearer_config_with_no_usable_paths_defers(tmp_path, pkg):
    root = _repo(tmp_path, gitignore=IGNORE,
                 files={"tsconfig.json": '{"compilerOptions": {"paths": {"@f/*": ["f/*"]}}}',
                        "pkg/tsconfig.json": pkg, "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "f/a.json", "{}")
    _write(wt, "pkg/src/x.ts", 'import a from "@f/a.json"\n')
    assert _refs(_run(wt).stdout) == ["f/a.json"]


def test_a_config_deleted_in_the_worktree_is_absent_not_unparsed(tmp_path):
    _, wt = _alias_repo(tmp_path)
    (wt / "tsconfig.json").unlink()
    _write(wt, "src/page.ts", "export const y = 2\n")
    r = _run(wt)
    assert "0 resolver configs read;" in r.stdout, r.stdout


def test_an_alias_applies_only_to_a_quoted_token(tmp_path):
    """A catch-all `"*"` would otherwise map every word on every line."""
    cfg = '{"compilerOptions": {"paths": {"*": ["types/*"]}}}'
    _, wt = _alias_repo(tmp_path, config=cfg)
    _write(wt, "types/data.json", "{}")
    _write(wt, "src/page.ts", "const n = data + 1\n")
    assert _run(wt).returncode == 0
    _write(wt, "src/page.ts", "import d from 'data'\n")
    assert _refs(_run(wt).stdout) == ["types/data.json"]


def test_a_name_built_at_run_time_stays_unseen_and_the_summary_says_so(tmp_path):
    _, wt = _alias_repo(tmp_path)
    _write(wt, "test/fixtures/k.json", "{}")
    _write(wt, "src/page.ts", "const f = await import(`@fixtures/${name}.json`)\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().endswith("names built at run time not read)"), r.stdout


@pytest.mark.parametrize("config", ["{ not json", "[1, 2]",
                                    '{"compilerOptions": {"paths": ["x"]}}'])
def test_an_unparsable_config_is_counted_not_fatal(tmp_path, config):
    _, wt = _alias_repo(tmp_path, config=config)
    _write(wt, "src/page.ts", "export const y = 2\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 resolver configs read, 1 not parsed" in r.stdout, r.stdout


def test_a_branch_claim_reads_the_config_from_the_branch_tip(tmp_path):
    """The working tree of a `--branch` claim's workspace is the default branch at close
    time, so a config the branch added is only in the branch's tree."""
    root = _repo(tmp_path, gitignore=IGNORE)
    _g(root, "checkout", "-q", "-b", "feat/br")
    _write(root, "tsconfig.json", TSCONFIG)
    _write(root, "test/fixtures/a.json", "{}")
    _write(root, "src/a.ts", 'import a from "@fixtures/a.json"\n')
    _g(root, "add", "tsconfig.json", "src/a.ts")
    _g(root, "commit", "-qm", "work")
    _g(root, "checkout", "-q", "main")
    assert not (root / "tsconfig.json").exists()
    r = _run(root, "main", "--branch", "feat/br")
    assert r.returncode == 1 and _refs(r.stdout) == ["test/fixtures/a.json"], r.stdout + r.stderr


# ─────────────────────────────────────────────────────────────────────────────
# A Next.js `public/` directory
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("config", ["next.config.js", "next.config.mjs", "next.config.ts"])
def test_a_root_absolute_url_is_served_from_public_beside_a_next_config(tmp_path, config):
    root = _repo(tmp_path, gitignore=IGNORE, files={config: "export default {}\n",
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "public/logo.png", "png")
    _write(wt, "app/page.tsx", '<img src="/logo.png" />\n')
    r = _run(wt)
    assert r.returncode == 1 and _refs(r.stdout) == ["public/logo.png"], r.stdout + r.stderr


def test_without_a_next_config_public_is_not_read(tmp_path):
    root = _repo(tmp_path, gitignore=IGNORE)
    wt = _worktree(root, tmp_path)
    _write(wt, "public/logo.png", "png")
    _write(wt, "app/page.tsx", '<img src="/logo.png" />\n')
    assert _run(wt).returncode == 0


def test_the_nearest_next_config_owns_the_public_directory(tmp_path):
    root = _repo(tmp_path, gitignore=IGNORE,
                 files={"apps/web/next.config.mjs": "export default {}\n",
                        "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "apps/web/public/logo.png", "png")
    _write(wt, "public/logo.png", "png")
    _write(wt, "apps/web/app/page.tsx", "<img src='/logo.png' />\n")
    assert _refs(_run(wt).stdout) == ["apps/web/public/logo.png"]


def test_a_protocol_relative_url_is_not_a_public_asset(tmp_path):
    root = _repo(tmp_path, gitignore=IGNORE, files={"next.config.js": "module.exports = {}\n",
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "public/logo.png", "png")
    # One component after `//`, so the suffix match (two or more components) cannot hit.
    _write(wt, "app/page.tsx", '<img src="//logo.png" />\n')
    r = _run(wt)
    assert r.returncode == 0, r.stdout
    assert "1 resolver configs read" in r.stdout, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# Phase 356's round (execution lens): the shapes its independent battery walked through
# ─────────────────────────────────────────────────────────────────────────────

def _one(tmp_path, cfg: str, want: str, line: str, where: str = "src/page.ts",
         name: str = "tsconfig.json"):
    _, wt = _alias_repo(tmp_path, config=cfg, name=name)
    _write(wt, want, "{}")
    _write(wt, where, line + "\n")
    return _run(wt)


def test_a_relative_specifier_is_never_mapped_through_paths(tmp_path):
    """TypeScript applies `paths` to a bare specifier only; `./util` is relative."""
    r = _one(tmp_path, '{"compilerOptions": {"baseUrl": "src", "paths": {"*": ["*"]}}}',
             "src/util.json", 'import u from "./util"', where="lib/a.ts")
    assert r.returncode == 0, r.stdout


def test_a_public_url_is_matched_by_its_exact_name(tmp_path):
    """Next serves `public/` files by name; a route `/settings` is not `settings.json`."""
    root = _repo(tmp_path, gitignore=IGNORE, files={"next.config.js": "module.exports = {}\n",
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "public/settings.json", "{}")
    _write(wt, "public/docs/index.json", "{}")
    _write(wt, "app/a.tsx", '<Link href="/settings">a</Link>\n<Link href="/docs">b</Link>\n')
    r = _run(wt)
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("cfg", [
    '{"compilerOptions": {"paths": {"@a/**": ["x/*"]}}}',            # two stars
    '{"compilerOptions": {"paths": {"@a/*": [1, null, "x/*"]}}}',    # non-string targets
    '{"compilerOptions": {"baseUrl": 5, "paths": {"@a/*": ["x/*"]}}}',  # non-string baseUrl
])
def test_a_malformed_paths_entry_never_stops_the_check(tmp_path, cfg):
    r = _one(tmp_path, cfg, "x/b.json", "import b from '@a/b.json'")
    assert r.returncode in (0, 1) and "Traceback" not in r.stderr, r.stdout + r.stderr


def test_an_untracked_config_is_read_before_the_commit(tmp_path):
    """The executors run the check before committing, when a new config is untracked."""
    _, wt = _alias_repo(tmp_path, config=None)
    _write(wt, "tsconfig.json", TSCONFIG)
    _write(wt, "test/fixtures/a.json", "{}")
    _write(wt, "src/page.ts", 'import a from "@fixtures/a.json"\n')
    assert _refs(_run(wt).stdout) == ["test/fixtures/a.json"]


@pytest.mark.parametrize("raw", [
    "﻿" + TSCONFIG,                                    # a byte-order mark
    TSCONFIG.replace("\n", "\r\n"),                         # CRLF, trailing commas before \r
    TSCONFIG.replace('"compilerOptions": {',
                     '"x": "a \\" // not a comment",\n  "compilerOptions": {'),  # escaped quote
])
def test_jsonc_shapes_a_real_config_carries(tmp_path, raw):
    r = _one(tmp_path, raw, "test/fixtures/a.json", 'import a from "@fixtures/a.json"')
    assert _refs(r.stdout) == ["test/fixtures/a.json"], r.stdout + r.stderr


def test_a_symlinked_config_is_counted_not_parsed(tmp_path):
    root = _repo(tmp_path, gitignore=IGNORE, files={"real/tsconfig.base": TSCONFIG,
                                                    "app/page.ts": "export const x = 1\n"})
    (root / "tsconfig.json").symlink_to("real/tsconfig.base")
    _g(root, "add", "-f", "tsconfig.json")
    _g(root, "commit", "-qm", "link")
    wt = _worktree(root, tmp_path)
    _write(wt, "src/page.ts", "export const y = 2\n")
    assert "0 resolver configs read, 1 not parsed" in _run(wt).stdout


def test_overlapping_prefix_and_suffix_do_not_match(tmp_path):
    """`ab*ba` needs at least four characters; `aba` starts and ends right but is too short."""
    r = _one(tmp_path, '{"compilerOptions": {"paths": {"ab*ba": ["x/hit.json"]}}}',
             "x/hit.json", "import h from 'aba'")
    assert r.returncode == 0, r.stdout


def test_a_prefix_tie_goes_to_the_first_pattern(tmp_path):
    r = _one(tmp_path, '{"compilerOptions": {"paths": {"@a/*.json": ["x/*.json"], '
                       '"@a/*": ["y/*"]}}}', "x/b.json", "import b from '@a/b.json'")
    assert _refs(r.stdout) == ["x/b.json"], r.stdout


def test_a_suffix_after_the_star_is_stripped_from_the_match(tmp_path):
    r = _one(tmp_path, '{"compilerOptions": {"paths": {"@icons/*.json": ["assets/*.json"]}}}',
             "assets/home.json", "import i from '@icons/home.json'")
    assert _refs(r.stdout) == ["assets/home.json"], r.stdout


def test_tsconfig_wins_over_jsconfig_in_one_directory(tmp_path):
    root = _repo(tmp_path, gitignore=IGNORE, files={
        "tsconfig.json": '{"compilerOptions": {"paths": {"@a/*": ["ts/*"]}}}',
        "jsconfig.json": '{"compilerOptions": {"paths": {"@a/*": ["js/*"]}}}',
        "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "ts/b.json", "{}")
    _write(wt, "js/b.json", "{}")
    _write(wt, "src/page.ts", "import b from '@a/b.json'\n")
    assert _refs(_run(wt).stdout) == ["ts/b.json"]


@pytest.mark.parametrize("ext", ["cjs", "mts"])
def test_every_next_config_extension_counts(tmp_path, ext):
    root = _repo(tmp_path, gitignore=IGNORE, files={f"next.config.{ext}": "x\n",
                                                    "app/page.ts": "export const x = 1\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "public/logo.png", "png")
    _write(wt, "app/page.tsx", '<img src="/logo.png" />\n')
    assert _refs(_run(wt).stdout) == ["public/logo.png"]
