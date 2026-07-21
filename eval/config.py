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


def resolve_db_url(override: str = None) -> str:
    """
    Resolve the database URL to use for evaluation.
    Priority: override arg > EVAL_DATABASE_URL > DATABASE_URL > DB_* vars > local Docker default
    """
    if override:
        return override

    # Check for eval-specific override
    eval_url = os.environ.get("EVAL_DATABASE_URL")
    if eval_url:
        return eval_url

    # Check for general DATABASE_URL, but skip it if it points to an unreachable Railway host
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Strip quotes that dotenv might leave
        db_url = db_url.strip('"').strip("'")
        # Skip Railway internal URLs — they're unreachable from local
        if ".railway.internal" not in db_url:
            return db_url

    # Check individual DB_* vars
    db_host = os.environ.get("DB_HOST")
    db_user = os.environ.get("DB_USER")
    db_password = os.environ.get("DB_PASSWORD")
    db_name = os.environ.get("DB_NAME")
    db_port = os.environ.get("DB_PORT", "5432")
    if all([db_host, db_user, db_password, db_name]):
        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # Fall back to local Docker default
    print(f"[WARN] No reachable DATABASE_URL found. Falling back to local Docker: {LOCAL_DOCKER_DB_URL}")
    return LOCAL_DOCKER_DB_URL
