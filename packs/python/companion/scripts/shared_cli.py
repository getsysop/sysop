"""Shared CLI bootstrap for scripts that target a database environment.

DB_NAME_MAP resolves each environment to a database name. By default it
reads ``DB_NAME_PROD`` / ``DB_NAME_STAGING`` / ``DB_NAME_DEV`` / ``DB_NAME_TEST``
from the process environment, falling back to ``app_<env>_db`` if the env
var is unset. Override per-environment by exporting ``DB_NAME_<ENV>`` (e.g.
``DB_NAME_PROD=myproject_prod``) or by editing the ``app_<env>_db`` template
to match the project's naming convention.
"""
import argparse
import os
import sys

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # python-dotenv is optional; no-op when unavailable
    def load_dotenv(*_args, **_kwargs):
        return False

DB_NAME_MAP = {
    env: os.environ.get(f"DB_NAME_{env.upper()}", f"app_{env}_db")
    for env in ("prod", "staging", "dev", "test")
}


def create_env_parser(description: str, **kwargs) -> argparse.ArgumentParser:
    """Create an ArgumentParser with a standardized --env flag.

    Callers can add extra arguments before calling parse_args().
    """
    parser = argparse.ArgumentParser(description=description, **kwargs)
    parser.add_argument(
        '--env', choices=['prod', 'staging', 'dev', 'test'], default='dev',
        help='Target environment (default: dev)',
    )
    return parser


def confirm_production(env: str) -> None:
    """Prompt for confirmation when targeting prod or staging. Exits if declined.

    Skips the prompt when stdin is not a TTY (e.g., Cloud Run jobs, piped input).
    """
    if env in ("prod", "staging"):
        if not sys.stdin.isatty():
            print(f"Non-interactive mode — proceeding with {env.upper()} database.")
            return
        confirm = input(
            f"You are about to target the {env.upper()} database. "
            "Type 'yes' to continue: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)


def setup_env(env: str) -> None:
    """Load .env, set APP_ENV, and add agent/ to sys.path for late imports.

    Must be called before importing db_config or other agent modules.
    """
    load_dotenv()
    os.environ["APP_ENV"] = env
    agent_dir = os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agent')
    )
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
