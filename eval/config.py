"""
Shared configuration for the eval harness.

Database resolution order:
  1. EVAL_DATABASE_URL env var  (preferred for local eval)
  2. DATABASE_URL env var       (falls back to project .env)
  3. DB_HOST / DB_USER / DB_PASSWORD / DB_NAME individual vars
  4. Hardcoded local Docker default from docker-compose.yml

This ensures running `python eval/retrieval_metrics.py` Just Works
against your local Docker pgvector even when the project .env points
at the unreachable Railway production host.
"""

import os
import sys

# Force UTF-8 for stdout/stderr on Windows (cp1252 can't handle emoji)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")

# Add application to path once
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from dotenv import load_dotenv

# Load .env files (application/.env overrides root .env)
load_dotenv(os.path.join(_project_root, ".env"))
_app_env = os.path.join(_application_dir, ".env")
if os.path.exists(_app_env):
    load_dotenv(_app_env, override=True)

# The local Docker default from docker-compose.yml
LOCAL_DOCKER_DB_URL = "postgresql://postgres:password@localhost:5432/waterbot_local"


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal", "db"}


def _host_of(url: str) -> str:
    """Extract the hostname from a postgres URL without importing a parser."""
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_local_url(url: str) -> bool:
    return _host_of(url) in _LOCAL_HOSTS


class RemoteDatabaseBlocked(RuntimeError):
    """Raised when the harness would have used a non-local database."""


def resolve_db_url(override: str = None, allow_remote: bool = None) -> str:
    """
    Resolve the database URL to use for evaluation.
    Priority: override arg > EVAL_DATABASE_URL > DATABASE_URL > DB_* vars > local Docker default

    REMOTE GUARD
    ------------
    EVAL_DATABASE_URL in this project pointed at Railway's public proxy, so
    every eval run — and any ingestion script sharing this resolver — was
    silently reading from and capable of writing to the PRODUCTION database.
    Evaluation should not put read load on production, and an ingest run
    against it is not trivially reversible.

    A non-local URL is therefore refused unless explicitly opted into, via
    allow_remote=True or EVAL_ALLOW_REMOTE=1. The escape hatch is deliberate
    and loud rather than the default.
    """
    if allow_remote is None:
        allow_remote = os.environ.get("EVAL_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes")

    def _check(url: str, source: str) -> str:
        url = url.strip('"').strip("'")
        if is_local_url(url) or allow_remote:
            if not is_local_url(url):
                print(f"[WARN] Using REMOTE database from {source} "
                      f"(host={_host_of(url)}) because remote access is enabled.")
            return url
        raise RemoteDatabaseBlocked(
            f"{source} points at a non-local database (host={_host_of(url)}), "
            f"which is refused by default.\n"
            f"  This guard exists because EVAL_DATABASE_URL pointed at the production\n"
            f"  Railway database, so evaluations ran against live data and an ingest\n"
            f"  script would have written to it.\n"
            f"  To use a local copy (recommended): unset {source}, or set\n"
            f"    EVAL_DATABASE_URL={LOCAL_DOCKER_DB_URL}\n"
            f"  To intentionally target the remote database, set EVAL_ALLOW_REMOTE=1."
        )

    if override:
        return _check(override, "the --db-url override")

    # Check for eval-specific override
    eval_url = os.environ.get("EVAL_DATABASE_URL")
    if eval_url:
        return _check(eval_url, "EVAL_DATABASE_URL")

    # Check for general DATABASE_URL, but skip it if it points to an unreachable Railway host
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Strip quotes that dotenv might leave
        db_url = db_url.strip('"').strip("'")
        # Skip Railway internal URLs — they're unreachable from local
        if ".railway.internal" not in db_url:
            return _check(db_url, "DATABASE_URL")

    # Check individual DB_* vars
    db_host = os.environ.get("DB_HOST")
    db_user = os.environ.get("DB_USER")
    db_password = os.environ.get("DB_PASSWORD")
    db_name = os.environ.get("DB_NAME")
    db_port = os.environ.get("DB_PORT", "5432")
    if all([db_host, db_user, db_password, db_name]):
        return _check(
            f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}",
            "DB_HOST/DB_USER/DB_PASSWORD/DB_NAME",
        )

    # Fall back to local Docker default
    print(f"[WARN] No reachable DATABASE_URL found. Falling back to local Docker: {LOCAL_DOCKER_DB_URL}")
    return LOCAL_DOCKER_DB_URL
