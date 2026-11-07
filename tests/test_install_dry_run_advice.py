"""install.sh's dry-run closing line advises an apply that will work.

A dry run never reaches `confirm "Proceed?"` (it sits inside
`if [[ "$DRY_RUN" -eq 0 ]]`), but the apply it advises does, and `confirm`
refuses with exit 1 when no terminal can be opened and `--yes` was not given.
So when the apply would hit that gate — no terminal, the shape of an agent's
tool call or CI — the closing line must name `--yes`; when `--yes` was already
given, it keeps it; only an interactive run without `--yes` gets the bare line.

The predicate is `_tty_openable` (an open of `/dev/tty`), the same one
`_require_tty_or_flag` runs. A test subprocess inherits the pytest session's
controlling terminal when one exists, so a plain `subprocess.run` is
interactive on a maintainer's laptop and non-interactive on CI. Each test
therefore fixes the condition it means: `start_new_session=True` detaches the
child from any terminal, and `pty.fork()` gives it one.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
SHIM = "sysop/scripts/sysop-update.sh"

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

BARE = "Dry-run complete. Re-run without --dry-run to apply."
WITH_YES = "Dry-run complete. Re-run without --dry-run and with --yes to apply."


def _env():
    env = dict(os.environ)
    # Put the pytest interpreter's dir on PATH so pick_python_with_yaml() finds
    # a pyyaml-capable python3 (the concat suite's convention).
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    env["SYSOP_SRC"] = str(REPO_ROOT)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _target(tmp_path, name="tgt"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# scratch\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _detached(argv, cwd):
    """Run with no controlling terminal: `/dev/tty` cannot be opened."""
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          env=_env(), start_new_session=True, timeout=600)


def _installed(tmp_path):
    """A committed core-only install, ready for --update."""
    tgt = _target(tmp_path)
    r = _detached(["bash", str(INSTALL_SH), str(tgt), "--packs", "", "--no-arm-hooks",
                   "--yes"], tgt)
    assert r.returncode == 0, r.stdout + r.stderr
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")
    return tgt


def _closing(out):
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    assert lines, "no output"
    return lines[-1]


# ── no terminal: the advice names --yes ─────────────────────────────────────

def test_fresh_dry_run_without_a_terminal_advises_yes(tmp_path):
    tgt = _target(tmp_path)
    r = _detached(["bash", str(INSTALL_SH), str(tgt), "--packs", "", "--no-arm-hooks",
                   "--dry-run"], tgt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _closing(r.stdout) == WITH_YES, r.stdout[-2000:]


def test_update_dry_run_without_a_terminal_advises_yes(tmp_path):
    tgt = _installed(tmp_path)
    r = _detached(["bash", str(INSTALL_SH), str(tgt), "--update", "--dry-run"], tgt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _closing(r.stdout) == WITH_YES, r.stdout[-2000:]


def test_shim_dry_run_without_a_terminal_advises_yes(tmp_path):
    tgt = _installed(tmp_path)
    r = _detached(["bash", SHIM, "--dry-run"], tgt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _closing(r.stdout) == WITH_YES, r.stdout[-2000:]


def test_adopt_dry_run_without_a_terminal_advises_yes(tmp_path):
    tgt = _installed(tmp_path)
    (tgt / ".claude" / "sysop.lock").unlink()
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "pre-lock install")
    r = _detached(["bash", str(INSTALL_SH), str(tgt), "--adopt", "--packs", "",
                   "--dry-run"], tgt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _closing(r.stdout) == WITH_YES, r.stdout[-2000:]


def test_the_advised_apply_runs_and_the_bare_one_still_refuses(tmp_path):
    """The gate stays: without a terminal the bare apply exits 1 and writes
    nothing, and the apply as advised (with --yes) succeeds."""
    tgt = _installed(tmp_path)
    bare = _detached(["bash", SHIM], tgt)
    assert bare.returncode == 1, bare.stdout + bare.stderr
    assert "Re-run with --yes" in bare.stderr, bare.stderr
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(tgt), check=True,
                            capture_output=True, text=True).stdout
    assert status == "", status
    advised = _detached(["bash", SHIM, "--yes"], tgt)
    assert advised.returncode == 0, advised.stdout + advised.stderr


# ── a terminal: bare unless --yes was given ─────────────────────────────────

# Forking a pty from the pytest worker would fork a multi-threaded process
# (Python warns that the child may deadlock), so a fresh single-threaded
# interpreter does the fork: the pty slave becomes the child's controlling
# terminal, and the helper relays its output and exit code.
_PTY_HELPER = r"""
import os, pty, sys
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.argv[1], sys.argv[1:])
out = bytearray()
while True:
    try:
        data = os.read(fd, 65536)
    except OSError:  # EIO: the child closed the slave
        break
    if not data:
        break
    out += data
_, status = os.waitpid(pid, 0)
sys.stdout.buffer.write(bytes(out))
sys.exit(os.waitstatus_to_exitcode(status))
"""


def _on_a_pty(argv, cwd):
    """Run `argv` with a pty as its controlling terminal; return (rc, output)."""
    r = subprocess.run([sys.executable, "-c", _PTY_HELPER, *argv], cwd=str(cwd),
                       capture_output=True, env=_env(), start_new_session=True,
                       timeout=600)
    out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    return r.returncode, out


def test_interactive_dry_run_gives_the_bare_advice(tmp_path):
    """With a terminal the apply can ask `Proceed?`, so --yes is not needed."""
    tgt = _target(tmp_path)
    rc, out = _on_a_pty(["bash", str(INSTALL_SH), str(tgt), "--packs", "",
                         "--no-arm-hooks", "--dry-run"], tgt)
    assert rc == 0, out[-2000:]
    assert _closing(out) == BARE, out[-2000:]


def test_a_redirected_stdin_with_a_terminal_gives_the_bare_advice(tmp_path):
    """`confirm` reads its answer from `/dev/tty`, not stdin, so a run whose stdin
    is redirected can still be asked `Proceed?` when a terminal exists. The advice
    must follow the gate's predicate (an open of `/dev/tty`), not `[ -t 0 ]`."""
    tgt = _target(tmp_path)
    rc, out = _on_a_pty(["bash", "-c", 'exec "$@" < /dev/null', "bash", "bash",
                         str(INSTALL_SH), str(tgt), "--packs", "", "--no-arm-hooks",
                         "--dry-run"], tgt)
    assert rc == 0, out[-2000:]
    assert _closing(out) == BARE, out[-2000:]


def test_interactive_dry_run_with_yes_keeps_it(tmp_path):
    tgt = _target(tmp_path)
    rc, out = _on_a_pty(["bash", str(INSTALL_SH), str(tgt), "--packs", "",
                         "--no-arm-hooks", "--dry-run", "--yes"], tgt)
    assert rc == 0, out[-2000:]
    assert _closing(out) == WITH_YES, out[-2000:]
