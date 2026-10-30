"""The pip-audit stage audits the project's dependency set, not pip-audit's own.

A bare ``pip-audit`` audits the interpreter it is installed into, so a uv-tool,
pipx or Homebrew pip-audit reported its own packages (``certifi``, ``filelock``)
as the project's and missed the project's real advisories (Q-717). The stage
now picks a target: ``uv.lock`` exported to a hashed requirements file, else
every ``requirements*.txt``, else the environment of the interpreter running
the checks. These tests pin that choice at the subprocess boundary; the real
run against pip-audit and uv is recorded in PHASE_LOG.md § Phase 436.
"""
import json
import os
import subprocess
import sys
from unittest.mock import patch

import run_checks.pip_audit as pip_audit_mod
from run_checks.accounting import DEGRADED, EXECUTED, FAILED, SKIPPED, RunReport

RUN = "run_checks.pip_audit.subprocess.run"
VULN = {"dependencies": [{"name": "requests", "version": "2.25.0", "vulns": [
    {"id": "GHSA-j8r2-6x86-q33q", "aliases": [], "fix_versions": ["2.31.0"],
     "description": "d"}]}]}


def _done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _uv_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")


EXPORT = "requests==2.25.0 \\\n    --hash=sha256:00\n"


def _fake_export_then(audit_result, export=EXPORT):
    """A `subprocess.run` stand-in: the `uv export` call writes ``export`` to
    its output file (so cleanup is observable), every pip-audit call returns
    ``audit_result`` and has the file it was given recorded."""
    seen = {"audited": []}

    def run(argv, **kwargs):
        if argv[:2] == ["uv", "export"]:
            path = argv[argv.index("--output-file") + 1]
            with open(path, "w") as fh:
                fh.write(export)
            seen["existed"] = os.path.exists(path)
            return _done()
        with open(argv[argv.index("-r") + 1]) as fh:
            seen["audited"].append(fh.read())
        return audit_result
    return run, seen


def _no_pip():
    return patch("run_checks.pip_audit._has_pip", return_value=False)


def test_uv_lock_is_exported_and_audited_without_pip(tmp_path, capsys):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    fake, seen = _fake_export_then(_done(json.dumps(VULN)))
    with patch(RUN, side_effect=fake) as run:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    export_argv, audit_argv = (c[0][0] for c in run.call_args_list)
    assert export_argv[:len(pip_audit_mod.UV_EXPORT_ARGS)] == pip_audit_mod.UV_EXPORT_ARGS
    assert "--locked" in export_argv and "--all-groups" in export_argv
    assert "--all-extras" in export_argv  # an optional dependency is in the lock
    # A workspace member or local path exports unhashed, and `--disable-pip`
    # then refuses the whole file; `--no-emit-project` alone leaves them in.
    assert "--no-emit-workspace" in export_argv and "--no-emit-local" in export_argv
    assert "--no-emit-project" not in export_argv
    exported = export_argv[export_argv.index("--output-file") + 1]
    assert seen["existed"]
    assert audit_argv[0] == "pip-audit"
    audited = audit_argv[audit_argv.index("-r") + 1]
    assert os.path.dirname(audited) == os.path.dirname(exported)
    assert seen["audited"] == ["requests==2.25.0\n"]
    assert "--disable-pip" in audit_argv and "--no-deps" in audit_argv
    assert run.call_args_list[1][1]["env"] is None
    # The audit names its target, and the export is gone after the run.
    assert "pip-audit: auditing uv.lock" in capsys.readouterr().err
    assert not os.path.exists(exported) and not os.path.exists(audited)
    assert [f[2] for f in findings] and "requests==2.25.0" in findings[0][2]
    assert r.status_of("pip-audit-vuln") == EXECUTED


def test_uv_consumer_anchor_stays_at_pyproject(tmp_path):
    """The anchor is in every baseline key: following the target to uv.lock
    would orphan every accepted entry a uv consumer already holds."""
    _uv_project(tmp_path)
    with patch(RUN, side_effect=_fake_export_then(_done(json.dumps(VULN)))[0]):
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert findings[0][1] == "pyproject.toml:1"


def test_uv_lock_wins_over_requirements_files(tmp_path):
    _uv_project(tmp_path)
    (tmp_path / "requirements.txt").write_text("flask\n")
    fake, _ = _fake_export_then(_done(json.dumps({"dependencies": []})))
    with _no_pip(), patch(RUN, side_effect=fake) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert run.call_args_list[0][0][0][:2] == ["uv", "export"]
    assert "requirements.txt" not in run.call_args_list[1][0][0]


def test_uv_missing_skips_and_never_audits_the_environment(tmp_path, capsys):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    with patch(RUN, side_effect=FileNotFoundError) as run:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert findings == []
    assert run.call_count == 1, "a missing uv must not fall back to the env audit"
    assert r.status_of("pip-audit-vuln") == SKIPPED
    assert r._records["pip-audit-vuln"].reason == "tool-missing"
    assert "uv not on PATH" in r._records["pip-audit-vuln"].detail
    assert "uv not on PATH" in capsys.readouterr().err


def test_stale_lock_fails_the_stage(tmp_path, capsys):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    stale = _done(returncode=2, stderr="error: The lockfile at `uv.lock` needs "
                  "to be updated, but `--locked` was provided.")
    with patch(RUN, return_value=stale) as run:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert findings == [] and run.call_count == 1
    assert r.status_of("pip-audit-vuln") == FAILED
    assert r._records["pip-audit-vuln"].reason == "uv-export"
    assert "needs to be updated" in capsys.readouterr().err


def test_uv_export_timeout_fails_the_stage(tmp_path):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    with patch(RUN, side_effect=subprocess.TimeoutExpired(cmd=["uv"], timeout=300)):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert r.status_of("pip-audit-vuln") == FAILED
    assert r._records["pip-audit-vuln"].reason == "timeout"


def test_every_requirements_file_is_audited_in_its_own_run(tmp_path, capsys):
    """One run with two `-r` is one pip resolve: a hashed file forces
    `--require-hashes` on its unhashed sibling, and disagreeing pins are
    `ResolutionImpossible` (both measured with pip-audit 2.10.1)."""
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    with _no_pip(), patch(RUN, return_value=_done(json.dumps({"dependencies": []}))) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    argvs = [c[0][0] for c in run.call_args_list]
    assert [a[:3] for a in argvs] == [["pip-audit", "-r", "requirements-dev.txt"],
                                      ["pip-audit", "-r", "requirements.txt"]]
    for argv, call in zip(argvs, run.call_args_list):
        assert argv.count("-r") == 1
        # Unpinned files need pip to resolve the transitive set.
        assert "--disable-pip" not in argv
        assert call[1]["env"] is None
    assert ("pip-audit: auditing requirements-dev.txt and requirements.txt"
            in capsys.readouterr().err)


def test_one_failing_requirements_file_fails_the_stage_and_keeps_the_rest(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.25.0\n")
    (tmp_path / "requirements-dev.txt").write_text("nosuchpkg==1\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    broken = _done(returncode=1, stderr="ERROR: No matching distribution for nosuchpkg==1")
    with _no_pip(), patch(RUN, side_effect=[broken, _done(json.dumps(VULN))]):
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert len(findings) == 1 and "requests==2.25.0" in findings[0][2]
    assert r.status_of("pip-audit-vuln") == FAILED
    assert r._records["pip-audit-vuln"].detail.startswith("requirements-dev.txt: ")


def test_a_package_in_two_requirements_files_is_one_finding(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.25.0\n")
    (tmp_path / "requirements-dev.txt").write_text("-r requirements.txt\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    with _no_pip(), patch(RUN, return_value=_done(json.dumps(VULN))) as run:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert run.call_count == 2 and len(findings) == 1
    assert r.status_of("pip-audit-vuln") == EXECUTED


def test_pip_audit_missing_stops_after_the_first_file(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    missing = _done(returncode=1, stderr="/x/python: No module named pip_audit")
    with _no_pip(), patch(RUN, side_effect=[FileNotFoundError(), missing]) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert run.call_count == 2
    assert r.status_of("pip-audit-vuln") == SKIPPED


def test_environment_audit_targets_the_running_interpreter(tmp_path, capsys):
    with patch(RUN, return_value=_done(json.dumps({"dependencies": []}))) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    argv = run.call_args[0][0]
    assert "-r" not in argv
    assert run.call_args[1]["env"]["PIPAPI_PYTHON_LOCATION"] == sys.executable
    assert f"the environment of {sys.executable}" in capsys.readouterr().err


def test_module_fallback_keeps_the_target(tmp_path):
    with patch(RUN, side_effect=[FileNotFoundError(),
                                 _done(json.dumps({"dependencies": []}))]) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    fallback = run.call_args_list[1]
    assert fallback[0][0][:3] == [sys.executable, "-m", "pip_audit"]
    assert fallback[1]["env"]["PIPAPI_PYTHON_LOCATION"] == sys.executable


def test_pipless_interpreter_gets_a_hint(tmp_path, capsys):
    r = RunReport([{"id": "pip-audit-vuln"}])
    pipless = _done(returncode=1, stderr="/x/.venv/bin/python: No module named pip\n"
                    "subprocess.CalledProcessError: Command '['/x', '-m', 'pip']'")
    with patch(RUN, return_value=pipless):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    err = capsys.readouterr().err
    assert r.status_of("pip-audit-vuln") == FAILED
    assert "did NOT run" in err and "has no pip" in err


def test_pipless_hint_only_for_the_environment_audit(tmp_path, capsys):
    """A requirements audit does not read the project interpreter, so its pip
    failure is not the pip-less venv the hint is about."""
    (tmp_path / "requirements.txt").write_text("flask\n")
    pipless = _done(returncode=1, stderr="/x/python: No module named pip\n")
    with _no_pip(), patch(RUN, return_value=pipless):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    err = capsys.readouterr().err
    assert "did NOT run" in err and "has no pip" not in err


def test_pip_audit_module_missing_is_not_the_pipless_hint(tmp_path, capsys):
    """`No module named pip_audit` is a pip-audit crash, not a pip-less venv."""
    crash = _done(returncode=1, stderr="ModuleNotFoundError: No module named 'pip_audit._x'")
    with patch(RUN, return_value=crash):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert "has no pip" not in capsys.readouterr().err


def test_requirements_files_and_the_environment_are_both_audited(tmp_path, capsys):
    """Neither source alone is safe (both measured): the requirements file
    alone read 0 findings for a pyproject project whose only file lists dev
    tools, and the environment alone, under the CI template's setup-python,
    reported only the runner's pip and missed the file's `requests`."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "requirements.txt").write_text("requests==2.25.0\n")
    runner_pip = {"dependencies": [{"name": "pip", "version": "26.0.1", "vulns": [
        {"id": "PIP-1", "aliases": [], "fix_versions": [], "description": "p"}]}]}
    with patch("run_checks.pip_audit._has_pip", return_value=True), \
            patch(RUN, side_effect=[_done(json.dumps(VULN)),
                                    _done(json.dumps(runner_pip))]) as run:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    file_run, env_run = run.call_args_list
    assert file_run[0][0][:3] == ["pip-audit", "-r", "requirements.txt"]
    assert file_run[1]["env"] is None
    assert "-r" not in env_run[0][0]
    assert env_run[1]["env"]["PIPAPI_PYTHON_LOCATION"] == sys.executable
    assert sorted(f[3] for f in findings) == ["GHSA-j8r2-6x86-q33q", "PIP-1"]
    assert (f"auditing requirements.txt and the environment of {sys.executable}"
            in capsys.readouterr().err)


def test_without_pip_only_the_files_are_audited_and_no_hint_is_owed(tmp_path, capsys):
    (tmp_path / "requirements.txt").write_text("requests==2.25.0\n")
    with _no_pip(), patch(RUN, return_value=_done(json.dumps(VULN))) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert run.call_count == 1 and run.call_args[1]["env"] is None
    assert "pyproject.toml" not in capsys.readouterr().err


def test_conflicting_extras_export_again_without_them(tmp_path, capsys):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    conflict = _done(returncode=2, stderr="error: Extras `new` and `old` are "
                     "incompatible with the declared conflicts: {`c[new]`, `c[old]`}")
    fake, seen = _fake_export_then(_done(json.dumps(VULN)))
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if len(calls) == 1:
            return conflict
        return fake(argv, **kw)
    with patch(RUN, side_effect=run):
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert "--all-extras" in calls[0] and "--all-groups" in calls[0]
    assert calls[1][:2] == ["uv", "export"]
    assert "--all-extras" not in calls[1] and "--all-groups" not in calls[1]
    assert "--locked" in calls[1]
    assert len(findings) == 1 and r.status_of("pip-audit-vuln") == DEGRADED
    assert "declared conflicts" in r._records["pip-audit-vuln"].detail
    assert "extras and non-default groups are NOT audited" in capsys.readouterr().err


def test_another_export_failure_is_not_retried(tmp_path):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    with patch(RUN, return_value=_done(returncode=2, stderr="error: boom")) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert run.call_count == 1 and r.status_of("pip-audit-vuln") == FAILED


def test_unpinned_lines_are_named_and_the_stage_is_degraded(tmp_path, capsys):
    """A git or URL source has no version pip-audit can look up (a hashed URL
    line it skips silently), so it is named; a pin from an index that serves
    no hashes is still a pin, and is audited."""
    export = ("gitpkg @ git+https://example.invalid/x@3b5b4ea\n"
              "idna @ https://example.invalid/idna-2.10-py3-none-any.whl \\\n"
              "    --hash=sha256:11\n"
              "-e ./libs/inner\n"
              "certifi==2020.4.5.1\n"
              "requests==2.25.0 \\\n    --hash=sha256:00\n")
    files, unpinned = pip_audit_mod._marker_branches(export)
    assert unpinned == ["gitpkg @ git+https://example.invalid/x@3b5b4ea",
                        "idna @ https://example.invalid/idna-2.10-py3-none-any.whl",
                        "-e ./libs/inner"]
    assert files == ["certifi==2020.4.5.1\nrequests==2.25.0\n"]
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    fake, seen = _fake_export_then(_done(json.dumps(VULN)), export)
    with patch(RUN, side_effect=fake):
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert seen["audited"] == ["certifi==2020.4.5.1\nrequests==2.25.0\n"]
    assert len(findings) == 1
    assert r.status_of("pip-audit-vuln") == DEGRADED
    assert "gitpkg" in r._records["pip-audit-vuln"].detail
    assert "no version pin pip-audit can look up" in capsys.readouterr().err


def test_an_export_of_only_unpinned_lines_is_degraded_not_executed(tmp_path):
    """Zero runs over a lock that did hold dependencies is not a real zero."""
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    fake, _ = _fake_export_then(_done(json.dumps(VULN)), "gitpkg @ git+https://example.invalid/x\n")
    with patch(RUN, side_effect=fake) as run:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert findings == [] and run.call_count == 1
    assert r.status_of("pip-audit-vuln") == DEGRADED


def test_an_empty_lock_is_a_real_zero(tmp_path):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    fake, _ = _fake_export_then(_done(json.dumps(VULN)), "# no dependencies\n")
    with patch(RUN, side_effect=fake):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert r.status_of("pip-audit-vuln") == EXECUTED


def test_conflicting_groups_are_retried_too(tmp_path):
    """uv words a group conflict without "declared" (measured, uv 0.13.6)."""
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    conflict = _done(returncode=2, stderr="error: Groups `a` and `b` are incompatible "
                     "with the conflicts: {`g:a`, `g:b`}")
    fake, _ = _fake_export_then(_done(json.dumps(VULN)))
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return conflict if len(calls) == 1 else fake(argv, **kw)
    with patch(RUN, side_effect=run):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert "--all-groups" not in calls[1]
    assert r.status_of("pip-audit-vuln") == DEGRADED


def test_an_earlier_failure_outlives_a_later_tool_missing(tmp_path):
    (tmp_path / "requirements.txt").write_text("b==1\n")
    (tmp_path / "requirements-dev.txt").write_text("a==1\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    missing = _done(returncode=1, stderr="/x/python: No module named pip_audit")
    with _no_pip(), patch(RUN, side_effect=[_done(returncode=1, stderr="first"),
                                            FileNotFoundError(), missing]):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert r.status_of("pip-audit-vuln") == FAILED


def test_has_pip_reads_the_running_interpreter():
    with patch("importlib.util.find_spec", return_value=None):
        assert pip_audit_mod._has_pip() is False


BRANCHED = (
    "# This file was autogenerated by uv\n"
    "--index-url https://pypi.org/simple\n"
    "jinja2==2.11.2 ; python_full_version < '3.12' \\\n"
    "    --hash=sha256:aa\n"
    "jinja2==3.1.2 ; python_full_version >= '3.12' \\\n"
    "    --hash=sha256:bb \\\n"
    "    --hash=sha256:cc\n"
    "    # via probe\n"
    "Jinja_2==9 \\\n"
    "    --hash=sha256:dd\n"
    "tomli==2.0.1 ; python_full_version < '3.11' \\\n"
    "    --hash=sha256:ee\n"
    "colorama==0.4.6 ; sys_platform == 'win32' \\\n"
    "    --hash=sha256:ff\n"
    "colorama==0.4.6 ; os_name == 'nt' \\\n"
    "    --hash=sha256:ff\n"
)


def test_marker_branches_audit_every_pin_once_without_markers():
    files, unhashed = pip_audit_mod._marker_branches(BRANCHED)
    assert len(files) == 2 and unhashed == []
    first, second = (f.splitlines() for f in files)
    for lines in (first, second):
        assert lines[0] == "--index-url https://pypi.org/simple"
        assert not any(";" in line for line in lines)
    # Hashes go too: the files are audited with --no-deps and install nothing.
    assert not any("--hash" in line for line in first + second)
    assert "jinja2==2.11.2" in first
    assert "jinja2==3.1.2" in second
    assert "tomli==2.0.1" in first
    # One pin under two markers is audited once; a name that only normalises
    # differently is a different package.
    assert sum(line.startswith("colorama==") for line in first + second) == 1
    assert "Jinja_2==9" in first


def test_marker_branches_of_an_empty_export_is_no_run():
    assert pip_audit_mod._marker_branches("# header only\n") == ([], [])


def test_a_package_at_two_versions_is_audited_in_two_runs(tmp_path):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    fake, seen = _fake_export_then(_done(json.dumps({"dependencies": []})), BRANCHED)
    with patch(RUN, side_effect=fake) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert run.call_count == 3  # the export, then one audit per branch file
    assert any("jinja2==2.11.2" in a for a in seen["audited"])
    assert any("jinja2==3.1.2" in a for a in seen["audited"])
    for call in run.call_args_list[1:]:
        assert "--disable-pip" in call[0][0]
    assert r.status_of("pip-audit-vuln") == EXECUTED


def test_an_export_that_wrote_no_file_fails_the_stage(tmp_path):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    with patch(RUN, return_value=_done()) as run:
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert run.call_count == 1
    assert r.status_of("pip-audit-vuln") == FAILED


def test_the_requirements_fallback_says_pyproject_deps_are_not_audited(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "requirements-dev.txt").write_text("pyyaml==6.0.2\n")
    with _no_pip(), patch(RUN, return_value=_done(json.dumps({"dependencies": []}))):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert "declared only in pyproject.toml are NOT audited" in capsys.readouterr().err


def test_has_pip_is_true_when_pip_is_importable():
    with patch("importlib.util.find_spec", return_value=object()):
        assert pip_audit_mod._has_pip() is True


def test_the_first_failing_run_is_the_one_recorded(tmp_path):
    (tmp_path / "requirements.txt").write_text("b==1\n")
    (tmp_path / "requirements-dev.txt").write_text("a==1\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    with _no_pip(), patch(RUN, side_effect=[_done(returncode=1, stderr="first"),
                                            _done(returncode=1, stderr="second")]):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    detail = r._records["pip-audit-vuln"].detail
    assert detail.startswith("requirements-dev.txt: ") and "first" in detail


def test_an_undecodable_export_fails_the_stage(tmp_path, capsys):
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])

    def run(argv, **kw):
        with open(argv[argv.index("--output-file") + 1], "wb") as fh:
            fh.write(b"requests==2.25.0 \xff\xfe\n")
        return _done()
    with patch(RUN, side_effect=run) as mock:
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert findings == [] and mock.call_count == 1
    assert r.status_of("pip-audit-vuln") == FAILED
    assert "could not read uv's export" in capsys.readouterr().err


def test_a_lock_pin_pip_audit_skips_degrades_the_stage(tmp_path, capsys):
    """`torch==2.1.0+cpu` comes back with a skip_reason and no vulns
    (measured, pip-audit 2.10.1); a silent `executed` would read as clean."""
    _uv_project(tmp_path)
    r = RunReport([{"id": "pip-audit-vuln"}])
    skipped = {"dependencies": VULN["dependencies"] + [
        {"name": "torch", "skip_reason": "Dependency not found on PyPI and could "
                                         "not be audited: torch (2.1.0+cpu)"},
        {"name": "x", "skip_reason": "requirement marked as editable"}]}
    fake, _ = _fake_export_then(_done(json.dumps(skipped)))
    with patch(RUN, side_effect=fake):
        findings = pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert len(findings) == 1
    assert r.status_of("pip-audit-vuln") == DEGRADED
    detail = r._records["pip-audit-vuln"].detail
    assert "torch" in detail and "editable" not in detail
    assert "skipped by pip-audit: torch" in capsys.readouterr().err


def test_a_skip_in_a_requirements_or_environment_run_is_not_a_cut(tmp_path):
    """There the project's own package is always skipped, and is not a dependency."""
    (tmp_path / "requirements.txt").write_text("-e .\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    own = {"dependencies": [{"name": "probe", "skip_reason":
                             "Dependency not found on PyPI and could not be audited: probe (0.1)"}]}
    with patch(RUN, return_value=_done(json.dumps(own))):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert r.status_of("pip-audit-vuln") == EXECUTED


def test_the_pipless_pyproject_cut_is_degraded(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "requirements-dev.txt").write_text("black==22.1.0\n")
    r = RunReport([{"id": "pip-audit-vuln"}])
    with _no_pip(), patch(RUN, return_value=_done(json.dumps({"dependencies": []}))):
        pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
    assert r.status_of("pip-audit-vuln") == DEGRADED
    assert "pyproject.toml" in r._records["pip-audit-vuln"].detail
