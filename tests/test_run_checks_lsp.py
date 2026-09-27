"""Unit tests for the LSP / typechecker ingest stage (run_checks/lsp.py), Phase 105.

This whole stage had zero coverage while its sibling ingest stages (grep,
coverage, eslint, pip-audit) are exhaustive — and it feeds `--fail-on-blocking`,
so a parser regression here would silently change what blocks a merge. These
cover the pyright + tsc JSON/text parsers (the 0-indexed→1-indexed line
conversion, the rule→check_id mapping, severity mapping, continuation-line
collapse), the `included_ids` filter, every graceful-skip path (binary missing /
timeout / non-JSON / empty / guard-file absent), and the dispatcher routing.

The subprocess boundary is mocked exactly as the coverage stage tests do
(`patch("run_checks.lsp.subprocess.run")`) — no real pyright/tsc binary needed.
Tool-absent is detected via `FileNotFoundError`, not a return code.
"""
import json
import os
import subprocess
from unittest.mock import patch

import run_checks.lsp as lsp


def _completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr="")


def _pyright_json(tmp_path, *, rule="reportMissingImports", severity="error",
                  line=41, message="Import could not be resolved"):
    return json.dumps({
        "generalDiagnostics": [{
            "file": str(tmp_path / "app" / "x.py"),
            "severity": severity,
            "rule": rule,
            "range": {"start": {"line": line}},
            "message": message,
        }]
    })


# ── pyright parser ──────────────────────────────────────────────────────────

class TestPyrightParser:
    def test_emits_finding_per_diagnostic(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(_pyright_json(tmp_path))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert len(out) == 1
        check_id, file_line, msg, _ident = out[0]
        assert check_id == "pyright-missing-imports"
        # pyright's range.start.line is 0-indexed; the +1 makes it 1-indexed.
        assert file_line == "app/x.py:42"
        assert "HIGH" in msg
        assert "Import could not be resolved" in msg

    def test_rule_not_in_included_ids_is_dropped(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(_pyright_json(tmp_path))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-unused-import"})
        assert out == []

    def test_unmapped_warning_becomes_general_warning(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(
                       _pyright_json(tmp_path, rule="reportSomethingNew",
                                     severity="warning"))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-general-warning"})
        assert len(out) == 1
        assert out[0][0] == "pyright-general-warning"
        assert "MEDIUM" in out[0][2]

    def test_unmapped_info_severity_is_dropped(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(
                       _pyright_json(tmp_path, rule="", severity="information"))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-general-warning"})
        assert out == []

    def test_binary_missing_skips_with_warning(self, tmp_path, capsys):
        with patch("run_checks.lsp.subprocess.run", side_effect=FileNotFoundError):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []
        assert "pyright not on PATH" in capsys.readouterr().err

    def test_timeout_skips_with_warning(self, tmp_path, capsys):
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("pyright", 300)):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []
        assert "timeout" in capsys.readouterr().err

    def test_non_json_output_skips_with_warning(self, tmp_path, capsys):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed("not json at all")):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []
        assert "non-JSON" in capsys.readouterr().err

    def test_empty_stdout_returns_empty(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run", return_value=_completed("")):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []


def _tsc(output="", returncode=0, listing="/p/src/a.ts\n", listing_rc=0):
    """A `subprocess.run` stand-in that answers tsc's two calls apart: the
    `--listFilesOnly` probe gets ``listing``, the check gets ``output``."""
    def fake(args, **_kw):
        if "--listFilesOnly" in args:
            return subprocess.CompletedProcess(args, listing_rc, listing, "")
        return subprocess.CompletedProcess(args, returncode, output, "")
    return fake


def _checks(run):
    """The type-check calls a mocked `subprocess.run` received, the listing probe left out."""
    return [c for c in run.call_args_list if "--listFilesOnly" not in c.args[0]]


# ── tsc parser ──────────────────────────────────────────────────────────────

def _make_tsc_frontend(tmp_path):
    """Build the two filesystem guards tsc requires before it shells out."""
    fe = tmp_path / "frontend"
    (fe).mkdir()
    (fe / "tsconfig.json").write_text("{}\n")
    (fe / "node_modules" / "typescript").mkdir(parents=True)
    return tmp_path


class TestTscParser:
    def test_emits_finding(self, tmp_path):
        _make_tsc_frontend(tmp_path)
        out_line = ("src/App.tsx(12,5): error TS2322: "
                    "Type 'string' is not assignable to 'number'.\n")
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=_tsc(out_line)):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert len(out) == 1
        check_id, file_line, msg, _ident = out[0]
        assert check_id == "tsc-type-error"
        # line is group(2)=12, NOT the column group(3)=5.
        assert file_line == "frontend/src/App.tsx:12"
        assert "HIGH" in msg

    def test_collapses_continuation_lines(self, tmp_path):
        _make_tsc_frontend(tmp_path)
        stdout = (
            "src/App.tsx(12,5): error TS2322: Type 'A' is not assignable to 'B'.\n"
            "  Types of property 'x' are incompatible.\n"
        )
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc(stdout)):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert len(out) == 1
        msg = out[0][2]
        assert "Type 'A' is not assignable to 'B'." in msg
        # The continuation line survives via the " — " join.
        assert "Types of property 'x' are incompatible." in msg

    def test_skips_when_tsconfig_absent(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run") as mock_run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert out == []
        assert mock_run.call_count == 0

    def test_warns_when_typescript_module_missing(self, tmp_path, capsys):
        fe = tmp_path / "frontend"
        fe.mkdir()
        (fe / "tsconfig.json").write_text("{}\n")  # tsconfig present, no node_modules
        with patch("run_checks.lsp.subprocess.run") as mock_run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert out == []
        assert mock_run.call_count == 0
        assert "frontend/node_modules/typescript missing" in capsys.readouterr().err

    def test_binary_missing_skips_with_warning(self, tmp_path, capsys):
        _make_tsc_frontend(tmp_path)
        with patch("run_checks.lsp.subprocess.run", side_effect=FileNotFoundError):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert out == []
        assert "tsc not available" in capsys.readouterr().err


class TestTscDiscovery:
    """Phase 327 (`Q-592` line 44). tsc used `<repo>/frontend`, hard-coded here and in
    `run_checks.sh`'s PATH, so it was dead for any other layout while
    `codebase-review/SKILL.md` described `<frontend>` as a placeholder. ESLint already
    discovered its directory; tsc now discovers the same way."""

    def _web(self, tmp_path, *, binary=False):
        web = tmp_path / "web"
        web.mkdir()
        (web / "tsconfig.json").write_text("{}\n")
        (web / "node_modules" / "typescript").mkdir(parents=True)
        if binary:
            bin_dir = web / "node_modules" / ".bin"
            bin_dir.mkdir()
            (bin_dir / "tsc").write_text("#!/bin/sh\n")
            (bin_dir / "tsc").chmod(0o755)
        return web

    def test_a_frontend_not_named_frontend_is_found_and_run(self, tmp_path):
        web = self._web(tmp_path)
        line = "src/App.tsx(12,5): error TS2322: Type 'string' is not assignable.\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc(line)) as run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_args.kwargs["cwd"] == str(web)
        assert [o[1] for o in out] == ["web/src/App.tsx:12"]

    def test_the_projects_own_tsc_binary_is_preferred_over_path(self, tmp_path):
        web = self._web(tmp_path, binary=True)
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_args.args[0][0] == str(web / "node_modules" / ".bin" / "tsc")

    def test_a_local_file_that_cannot_execute_is_not_run(self, tmp_path):
        web = self._web(tmp_path, binary=True)
        (web / "node_modules" / ".bin" / "tsc").chmod(0o644)
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_args.args[0][0] == "tsc", (
            "a non-executable .bin/tsc was chosen over PATH, which fails with EACCES "
            "(PermissionError) — an error no caller here reports as a skip")

    def test_without_a_local_binary_the_bare_name_is_run(self, tmp_path):
        self._web(tmp_path)
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_args.args[0][0] == "tsc"

    def _pkg(self, root, name):
        d = root / name
        d.mkdir(parents=True)
        (d / "tsconfig.json").write_text("{}\n")
        (d / "node_modules" / "typescript").mkdir(parents=True)
        return d

    def test_frontend_wins_when_a_second_typescript_package_exists(self, tmp_path):
        """The round's regression: `frontend/` plus a root, `e2e/` or `tools/` TypeScript
        install ran tsc before discovery and skipped as ambiguous after it."""
        for extra in (".", "e2e", "tools/scripts"):
            root = tmp_path / extra.replace("/", "_").replace(".", "root")
            root.mkdir()
            fe = self._pkg(root, "frontend")
            if extra == ".":
                (root / "tsconfig.json").write_text("{}\n")
                (root / "node_modules" / "typescript").mkdir(parents=True)
            else:
                self._pkg(root, extra)
            with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
                lsp._run_tsc(str(root), {"tsc-type-error"})
            assert len(_checks(run)) == 1, f"{extra}: tsc did not run"
            assert run.call_args.kwargs["cwd"] == str(fe), extra

    def test_two_candidates_without_frontend_skip_loudly(self, tmp_path, capsys):
        self._pkg(tmp_path, "web")
        self._pkg(tmp_path, "admin")
        with patch("run_checks.lsp.subprocess.run") as run:
            assert lsp._run_tsc(str(tmp_path), {"tsc-type-error"}) == []
        assert run.call_count == 0
        err = capsys.readouterr().err
        assert "multiple node_modules/typescript candidates" in err
        assert "explicitly" not in err, "the warning names a setting that does not exist"

    def test_a_symlinked_frontend_is_still_checked(self, tmp_path):
        """The walk does not follow links; tsc read `<root>/frontend` through one before."""
        ext = self._pkg(tmp_path / "outside", "fe")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "frontend").symlink_to(ext, target_is_directory=True)
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
            lsp._run_tsc(str(repo), {"tsc-type-error"})
        assert len(_checks(run)) == 1
        assert run.call_args.kwargs["cwd"] == str(repo / "frontend")

    def test_a_symlinked_frontend_without_an_install_warns(self, tmp_path, capsys):
        """The no-install path reads `<root>/frontend` directly too; through a symlink the walk
        alone found no config and skipped without a word."""
        ext = tmp_path / "outside" / "fe"
        ext.mkdir(parents=True)
        (ext / "tsconfig.json").write_text("{}\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "frontend").symlink_to(ext, target_is_directory=True)
        with patch("run_checks.lsp.subprocess.run") as run:
            lsp._run_tsc(str(repo), {"tsc-type-error"})
        assert run.call_count == 0
        assert "frontend/node_modules/typescript missing" in capsys.readouterr().err

    def test_an_in_repo_symlinked_frontend_keeps_the_pre_discovery_label(self, tmp_path):
        """`frontend -> web`: tsc read `<root>/frontend` before discovery, so its findings say
        `frontend/`. The round-1 union labelled them `web/` on one path and `frontend/` on
        another; conventional-first gives one answer, the pre-phase one."""
        web = self._pkg(tmp_path, "web")
        (tmp_path / "frontend").symlink_to(web, target_is_directory=True)
        line = "src/a.ts(1,7): error TS2322: bad.\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc(line)) as run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_args.kwargs["cwd"] == str(tmp_path / "frontend")
        assert [o[1] for o in out] == ["frontend/src/a.ts:1"]

    def test_a_nested_checkout_is_never_checked_in_this_checkouts_name(self, tmp_path, capsys):
        """Round 2: with no install in `frontend/`, the walk found an in-repo agent worktree's
        install and reported its files as this checkout's. A directory holding `.git` is
        another checkout; the stage must warn about `frontend/` instead, as it did before."""
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "tsconfig.json").write_text("{}\n")
        wt = tmp_path / ".claude" / "worktrees" / "agent-1"
        self._pkg(wt, "frontend")
        (wt / ".git").write_text("gitdir: /elsewhere\n")
        with patch("run_checks.lsp.subprocess.run") as run:
            assert lsp._run_tsc(str(tmp_path), {"tsc-type-error"}) == []
        assert run.call_count == 0
        assert "frontend/node_modules/typescript missing" in capsys.readouterr().err

    def test_a_config_that_lists_no_files_is_skipped_not_reported_clean(self, tmp_path, capsys):
        """Vite's and Nx's default configs list no files and only reference projects, so
        `tsc -p` checks nothing and exits 0. tsc's own listing decides, whatever the config's
        spelling: only lib declarations under node_modules means nothing would be checked."""
        self._pkg(tmp_path, "frontend")
        libs = "/x/node_modules/typescript/lib/lib.d.ts\n/x/node_modules/@types/node/index.d.ts\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("", listing=libs)) as run:
            assert lsp._run_tsc(str(tmp_path), {"tsc-type-error"}) == []
        assert _checks(run) == [], "the check ran after the listing named no project file"
        assert "--listFilesOnly" in run.call_args.args[0]
        assert "no files in the program" in capsys.readouterr().err

    def test_an_empty_listing_is_skipped_too(self, tmp_path):
        self._pkg(tmp_path, "frontend")
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("", listing="")) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert _checks(run) == []

    def test_a_failed_listing_falls_through_to_the_real_run(self, tmp_path):
        """An older tsc without the flag, or a config error, exits nonzero from the listing;
        the stage must run the check, which reports it, rather than skip on no evidence."""
        self._pkg(tmp_path, "frontend")
        err = "error TS5023: Unknown compiler option '--listFilesOnly'.\n"
        line = "src/a.ts(1,7): error TS2322: bad.\n"
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=_tsc(line, returncode=2, listing=err, listing_rc=1)) as run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert len(_checks(run)) == 1
        assert [o[1] for o in out] == ["frontend/src/a.ts:1"]

    def test_a_failed_empty_listing_still_runs_the_check(self, tmp_path):
        """A nonzero listing with nothing on stdout is no evidence of an empty program; only an
        exit-0 listing may skip. Round 2's re-run dropped the exit-code check unseen."""
        self._pkg(tmp_path, "frontend")
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=_tsc("", listing="", listing_rc=1)) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert len(_checks(run)) == 1

    def test_the_skip_warning_leaves_nested_checkouts_out(self, tmp_path, capsys):
        """With no `frontend/`, the warning lists every config the walk finds; a nested
        checkout's config is not this checkout's and must not be named."""
        (tmp_path / "web").mkdir()
        (tmp_path / "web" / "tsconfig.json").write_text("{}\n")
        wt = tmp_path / ".claude" / "worktrees" / "agent-1"
        (wt / "web").mkdir(parents=True)
        (wt / "web" / "tsconfig.json").write_text("{}\n")
        (wt / ".git").write_text("gitdir: /elsewhere\n")
        with patch("run_checks.lsp.subprocess.run"):
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        err = capsys.readouterr().err
        assert "web/node_modules/typescript missing" in err and "worktrees" not in err, err

    def test_an_uninstalled_frontend_config_is_never_replaced_by_another_project(self, tmp_path, capsys):
        """Round 3's HIGH. `frontend/tsconfig.json` with no install beside it used to let the
        walk adopt a sibling project — or a hoisted workspace root — and record `executed` over
        code that was never the frontend's. The config is authoritative: skip loudly, as before
        the phase, with the pre-phase detail string."""
        from run_checks.accounting import RunReport
        for other in ("infra", "."):
            root = tmp_path / ("root" if other == "." else other + "_case")
            (root / "frontend").mkdir(parents=True)
            (root / "frontend" / "tsconfig.json").write_text('{"extends": "../tsconfig.json"}\n')
            if other == ".":
                (root / "tsconfig.json").write_text('{"compilerOptions": {}}\n')
                (root / "node_modules" / "typescript").mkdir(parents=True)
            else:
                self._pkg(root, other)
            r = RunReport([{"id": "tsc-type-error"}])
            with patch("run_checks.lsp.subprocess.run") as run:
                lsp._run_tsc(str(root), {"tsc-type-error": {}}, r)
            assert run.call_count == 0, f"{other}: tsc ran in place of frontend/"
            assert r._records["tsc-type-error"].detail == "frontend/node_modules/typescript absent"
            err = capsys.readouterr().err
            assert "frontend/node_modules/typescript missing" in err
            # The install advice must say a hoisted install cannot satisfy it (round 3, LOW 3).
            assert "a hoisted or workspace-root install is not read" in err

    def test_a_run_with_only_config_located_errors_is_failed(self, tmp_path, capsys):
        """Round 3's MED. tsc suppresses semantic checking while an options diagnostic stands,
        and under tsc 6 those are located IN the config (`tsconfig.json(1,81): error TS5107`),
        so the location-less test alone read the run as clean."""
        from run_checks.accounting import RunReport, FAILED
        self._web(tmp_path)
        r = RunReport([{"id": "tsc-type-error"}])
        msg = "tsconfig.json(1,81): error TS5107: Option 'target=ES5' is deprecated.\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc(msg, returncode=2)):
            assert lsp._run_tsc(str(tmp_path), {"tsc-type-error": {}}, r) == []
        assert r.status_of("tsc-type-error") == FAILED
        assert "did NOT run" in capsys.readouterr().err

    def test_a_zero_exit_json_warning_is_not_a_failure(self, tmp_path):
        self._web(tmp_path)
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=_tsc("tsconfig.json(1,1): error TS5101: x.\n", returncode=0)):
            from run_checks.accounting import RunReport, EXECUTED
            r = RunReport([{"id": "tsc-type-error"}])
            lsp._run_tsc(str(tmp_path), {"tsc-type-error": {}}, r)
        assert r.status_of("tsc-type-error") == EXECUTED

    def test_a_repo_under_a_node_modules_directory_still_has_project_files(self, tmp_path):
        """Round 3: the filter tested the absolute path, so a repo living under any
        `node_modules/` directory had every file excluded and was skipped as solution-style."""
        root = tmp_path / "node_modules" / "proj"
        fe = self._pkg(root, "frontend")
        listing = f"{fe}/src/a.ts\n/x/node_modules/typescript/lib/lib.d.ts\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("", listing=listing)) as run:
            lsp._run_tsc(str(root), {"tsc-type-error"})
        assert len(_checks(run)) == 1

    def test_typescript_only_in_a_nested_checkout_is_said_not_silenced(self, tmp_path, capsys):
        sub = tmp_path / "vendor" / "ui"
        (sub / "node_modules" / "typescript").mkdir(parents=True)
        (sub / "tsconfig.json").write_text("{}\n")
        (sub / ".git").write_text("gitdir: /elsewhere\n")
        with patch("run_checks.lsp.subprocess.run") as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_count == 0
        assert "only inside nested checkouts (vendor/ui)" in capsys.readouterr().err

    def test_a_windows_style_listing_path_is_read_as_node_modules(self, tmp_path):
        self._pkg(tmp_path, "frontend")
        libs = "C:\\x\\node_modules\\typescript\\lib\\lib.d.ts\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("", listing=libs)) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert _checks(run) == []

    def test_a_location_less_config_error_is_a_failed_run_not_a_clean_one(self, tmp_path, capsys):
        """`error TS18003: No inputs were found` has no `path(line,col)`, so nothing parsed and
        the run was recorded `executed` with zero findings (round 2, pre-existing class)."""
        from run_checks.accounting import RunReport, FAILED
        self._web(tmp_path)
        r = RunReport([{"id": "tsc-type-error"}])
        msg = "error TS18003: No inputs were found in config file 'tsconfig.json'.\n"
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc(msg, returncode=2)):
            assert lsp._run_tsc(str(tmp_path), {"tsc-type-error": {}}, r) == []
        assert r.status_of("tsc-type-error") == FAILED
        assert "did NOT run" in capsys.readouterr().err

    def test_a_config_error_beside_located_errors_still_reports_them(self, tmp_path):
        self._web(tmp_path)
        out_text = ("error TS5096: Option 'x' is deprecated.\n"
                    "src/a.ts(1,7): error TS2322: bad.\n")
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc(out_text, returncode=2)):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert [o[1] for o in out] == ["web/src/a.ts:1"]


    def test_a_relative_repo_root_still_runs_the_local_binary(self, tmp_path, monkeypatch):
        """`_node_bin` is run with `cwd=` the frontend dir, so a relative path would be
        resolved twice (`frontend/frontend/...`) and reported as tsc missing."""
        web = self._web(tmp_path, binary=True)
        monkeypatch.chdir(tmp_path)
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
            lsp._run_tsc(".", {"tsc-type-error"})
        assert os.path.isabs(run.call_args.args[0][0])
        assert run.call_args.args[0][0] == str(web / "node_modules" / ".bin" / "tsc")

    def _reason(self, root, effect=None):
        from run_checks.accounting import RunReport
        r = RunReport([{"id": "tsc-type-error"}])
        with patch("run_checks.lsp.subprocess.run", side_effect=effect) as run:
            lsp._run_tsc(str(root), {"tsc-type-error": {}}, r)
        assert _checks(run) == [] if effect else run.call_count == 0
        return r._records["tsc-type-error"].reason

    def test_each_skip_records_its_own_reason(self, tmp_path):
        """The accounting line is what a reader of `skipped` sees; each cause keeps its word."""
        amb = tmp_path / "amb"
        self._pkg(amb, "web")
        self._pkg(amb, "admin")
        assert self._reason(amb) == "misconfigured"
        bare = tmp_path / "bare" / "web"
        bare.mkdir(parents=True)
        (bare / "tsconfig.json").write_text("{}\n")
        assert self._reason(tmp_path / "bare") == "input-missing"
        sol = tmp_path / "sol"
        self._pkg(sol, "frontend")
        assert self._reason(sol, _tsc("", listing="")) == "not-configured"

    def test_several_configs_without_an_install_are_all_named(self, tmp_path, capsys):
        for name in ("web", "admin"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "tsconfig.json").write_text("{}\n")
        with patch("run_checks.lsp.subprocess.run"):
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        err = capsys.readouterr().err
        assert "no node_modules/typescript beside any tsconfig.json (admin, web)" in err, err

    def test_a_missing_binary_names_the_discovered_directory(self, tmp_path, capsys):
        self._web(tmp_path)
        with patch("run_checks.lsp.subprocess.run", side_effect=FileNotFoundError):
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert "(install: (cd web && npm ci))" in capsys.readouterr().err

    def test_a_frontend_without_a_config_does_not_shadow_a_real_project(self, tmp_path):
        """`frontend/` wins only when it QUALIFIES: an install with no `tsconfig.json` beside it
        would run `tsc -p tsconfig.json` where there is no config (round 2, M6)."""
        (tmp_path / "frontend" / "node_modules" / "typescript").mkdir(parents=True)
        web = self._pkg(tmp_path, "web")
        with patch("run_checks.lsp.subprocess.run", side_effect=_tsc("")) as run:
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert run.call_args.kwargs["cwd"] == str(web)

    def test_the_install_advice_names_the_shallowest_config(self, tmp_path, capsys):
        """With no `frontend/`, the advice goes to the shallowest config, not the first in sort
        order (`.claude/...` sorts before `web`)."""
        deep = tmp_path / ".claude" / "copies" / "web"
        deep.mkdir(parents=True)
        (deep / "tsconfig.json").write_text("{}\n")
        (tmp_path / "web").mkdir()
        (tmp_path / "web" / "tsconfig.json").write_text("{}\n")
        with patch("run_checks.lsp.subprocess.run"):
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert "(install: cd web && npm ci)" in capsys.readouterr().err

    def test_the_install_advice_points_at_frontend_before_a_worktree_copy(self, tmp_path, capsys):
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "tsconfig.json").write_text("{}\n")
        wt = tmp_path / ".claude" / "worktrees" / "agent-1" / "frontend"
        wt.mkdir(parents=True)
        (wt / "tsconfig.json").write_text("{}\n")
        with patch("run_checks.lsp.subprocess.run"):
            lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert "(install: cd frontend && npm ci)" in capsys.readouterr().err

    def test_a_config_without_an_install_beside_it_names_its_directory(self, tmp_path, capsys):
        web = tmp_path / "web"
        web.mkdir()
        (web / "tsconfig.json").write_text("{}\n")
        (tmp_path / "node_modules" / "typescript").mkdir(parents=True)  # not beside it
        with patch("run_checks.lsp.subprocess.run") as run:
            assert lsp._run_tsc(str(tmp_path), {"tsc-type-error"}) == []
        assert run.call_count == 0
        assert "web/node_modules/typescript missing" in capsys.readouterr().err


# ── dispatcher ──────────────────────────────────────────────────────────────

class TestDispatch:
    def test_pyright_only_set_does_not_invoke_tsc(self, tmp_path):
        # A pyright-only included set → tsc is never dispatched (guarded on
        # "tsc-type-error" membership). Only pyright shells out.
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed('{"generalDiagnostics": []}')) as mock_run:
            lsp.run_lsp_diagnostics(str(tmp_path), {"pyright-missing-imports"})
        assert mock_run.call_count == 1
        assert "pyright" in mock_run.call_args_list[0].args[0]

    def test_empty_included_set_shells_out_to_nothing(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run") as mock_run:
            out = lsp.run_lsp_diagnostics(str(tmp_path), set())
        assert out == []
        assert mock_run.call_count == 0


# ── Phase 133: per-check paths: scoping (post-filter) ───────────────────────

class TestPathsScoping:
    """When a pyright-*/tsc-* registry entry declares real `paths:`, findings
    outside them are dropped; unlocalized `<placeholder>` entries contribute
    no scoping and the `__disabled_no_op__` sentinel disables the check."""

    def _run_pyright(self, tmp_path, included):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(_pyright_json(tmp_path))):
            return lsp._run_pyright(str(tmp_path), included)

    def test_pyright_in_scope_kept(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["app/"]}})
        assert len(out) == 1

    def test_pyright_out_of_scope_dropped(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["other/"]}})
        assert out == []

    def test_pyright_placeholder_paths_do_not_scope(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["<api module>/"]}})
        assert len(out) == 1, "unlocalized placeholder must not disable the check"

    def test_pyright_sentinel_disables_check(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["__disabled_no_op__"]}})
        assert out == []

    def test_tsc_paths_scope_findings(self, tmp_path):
        m = lsp._TSC_HEADER_RE.match(
            "components/App.tsx(5,3): error TS2322: Bad type")
        assert m
        out_in, out_out = [], []
        lsp._emit_tsc_finding(
            (m, []), str(tmp_path / "frontend"), str(tmp_path),
            {"tsc-type-error": {"id": "tsc-type-error", "paths": ["frontend/"]}},
            out_in)
        lsp._emit_tsc_finding(
            (m, []), str(tmp_path / "frontend"), str(tmp_path),
            {"tsc-type-error": {"id": "tsc-type-error", "paths": ["backend/"]}},
            out_out)
        assert len(out_in) == 1
        assert out_out == []
