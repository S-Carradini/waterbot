"""
Migrate historical DynamoDB messages into PostgreSQL messages table.

Reads all items from the DynamoDB messages table and inserts them into
PostgreSQL, skipping any that already exist (idempotent). DynamoDB is
read-only — nothing is modified there.

Designed to run as a one-off ECS task (same VPC/creds as the app) via:
  aws ecs run-task --overrides '{"containerOverrides":[{
    "name":"WaterbotAppContainer",
    "command":["python","scripts/migrate_dynamo_to_postgres.py","--execute"]
  }]}'

Without --execute, runs in dry-run mode (no writes to PostgreSQL).

Env vars (already present in the ECS task definition):
  DB_HOST, DB_USER, DB_PASSWORD, DB_NAME  (or DATABASE_URL)
  MESSAGES_TABLE  (DynamoDB table name)
  AWS_REGION (defaults to us-east-1 for DynamoDB)
"""

import argparse
import datetime
import json
import logging
import os
import sys
from decimal import Decimal

_script_dir = os.path.dirname(os.path.abspath(__file__))
_application_dir = os.path.dirname(_script_dir)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(_application_dir, ".env"))
load_dotenv(os.path.join(os.path.dirname(_application_dir), ".env"), override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def pg_connect():
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
    )


def ensure_columns(conn):
    """Add reaction and user_comment columns if they don't exist yet."""
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reaction SMALLINT;")
    cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS user_comment TEXT;")
    cur.close()
    conn.autocommit = False


def scan_dynamo(table_name: str) -> list[dict]:
    """Full scan of the DynamoDB messages table. Returns all items."""
    import boto3

    region = os.getenv("AWS_REGION", "us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    items = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
        log.info("Scanned %d items so far...", len(items))

    log.info("DynamoDB scan complete: %d items total.", len(items))
    return items


def get_existing_keys(conn) -> set[tuple[str, str]]:
    """Return set of (session_uuid, msg_id) already in PostgreSQL."""
    cur = conn.cursor()
    cur.execute("SELECT session_uuid, msg_id FROM messages;")
    keys = {(row[0], row[1]) for row in cur.fetchall()}
    cur.close()
    return keys


def parse_source(raw) -> str | None:
    """Convert DynamoDB source field to a JSON string suitable for JSONB column."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        # Already JSON?
        if raw.startswith("[") or raw.startswith("{"):
            try:
                json.loads(raw)
                return raw
            except json.JSONDecodeError:
                pass
        # Wrap bare string as a JSON array
        return json.dumps([raw])
    if isinstance(raw, (list, dict)):
        return json.dumps(raw, default=str)
    return json.dumps([str(raw)])


def parse_timestamp(raw) -> datetime.datetime:
    """Parse ISO 8601 timestamp string; fall back to now() if unparseable."""
    if raw is None:
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        return datetime.datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        log.warning("Unparseable timestamp %r, using now()", raw)
        return datetime.datetime.now(datetime.timezone.utc)


def convert_decimal(val):
    """Convert Decimal values from DynamoDB to int or None."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return int(val)
    return val


def transform(item: dict) -> dict:
    """Map a DynamoDB item to a PostgreSQL row dict."""
    return {
        "session_uuid": item.get("sessionId", ""),
        "msg_id": str(item.get("msgId", "")),
        "user_query": item.get("userQuery", ""),
        "response_content": item.get("responseContent", ""),
        "source": parse_source(item.get("source")),
        "chatbot_type": "waterbot",
        "created_at": parse_timestamp(item.get("timestamp")),
        "reaction": convert_decimal(item.get("reaction")),
        "user_comment": item.get("userComment"),
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate DynamoDB messages to PostgreSQL")
    parser.add_argument("--execute", action="store_true", help="Actually write to PostgreSQL (default is dry-run)")
    args = parser.parse_args()

    table_name = os.getenv("MESSAGES_TABLE")
    if not table_name:
        log.error("MESSAGES_TABLE env var is not set. Cannot scan DynamoDB.")
        sys.exit(1)

    # Check PostgreSQL connectivity
    database_url = os.getenv("DATABASE_URL")
    db_host = os.getenv("DB_HOST")
    if not database_url and not db_host:
        log.error("No PostgreSQL config found (DATABASE_URL or DB_HOST). Cannot proceed.")
        sys.exit(1)

    log.info("=== DynamoDB -> PostgreSQL Migration ===")
    log.info("DynamoDB table: %s", table_name)
    log.info("Mode: %s", "EXECUTE" if args.execute else "DRY RUN")

    # 1. Scan DynamoDB
    items = scan_dynamo(table_name)
    if not items:
        log.info("No items found in DynamoDB. Nothing to migrate.")
        return

    # 2. Connect to PostgreSQL and ensure schema
    conn = pg_connect()
    ensure_columns(conn)

    # 3. Get existing keys to separate updates from inserts
    existing = get_existing_keys(conn)
    log.info("Existing PostgreSQL messages: %d", len(existing))

    # 4. Transform and split into updates (existing rows) vs inserts (new rows)
    to_update = []  # rows that already exist in PG — update reaction/comment only
    to_insert = []  # rows not in PG — full insert
    for item in items:
        row = transform(item)
        key = (row["session_uuid"], row["msg_id"])
        if key in existing:
            # Only update if DynamoDB has rating data worth merging
            if row["reaction"] is not None or row["user_comment"]:
                to_update.append(row)
        else:
            to_insert.append(row)

    log.info("To update (merge ratings): %d  |  To insert (new): %d  |  Total scanned: %d",
             len(to_update), len(to_insert), len(items))

    if not to_update and not to_insert:
        log.info("Nothing to migrate.")
        conn.close()
        return

    if not args.execute:
        log.info("DRY RUN — no writes to PostgreSQL. Re-run with --execute to apply.")
        for r in (to_update + to_insert)[:3]:
            log.info("  Sample: session=%s msg=%s reaction=%s comment=%s",
                     r["session_uuid"][:12], r["msg_id"][:12],
                     r["reaction"], r.get("user_comment", "")[:40] if r.get("user_comment") else "")
        conn.close()
        return

    # 5a. Update existing rows with rating data from DynamoDB
    update_sql = """
        UPDATE messages SET reaction = %s, user_comment = %s
        WHERE session_uuid = %s AND msg_id = %s
          AND (reaction IS NULL AND user_comment IS NULL);
    """
    cur = conn.cursor()
    updated = 0
    for row in to_update:
        try:
            cur.execute(update_sql, (
                row["reaction"],
                row["user_comment"],
                row["session_uuid"],
                row["msg_id"],
            ))
            updated += cur.rowcount
        except Exception as e:
            log.error("Failed to update session=%s msg=%s: %s", row["session_uuid"], row["msg_id"], e)
            conn.rollback()
            cur = conn.cursor()
            continue

    # 5b. Insert rows that don't exist in PostgreSQL
    insert_sql = """
        INSERT INTO messages (session_uuid, msg_id, user_query, response_content, source, chatbot_type, created_at, reaction, user_comment)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    inserted = 0
    for row in to_insert:
        try:
            cur.execute(insert_sql, (
                row["session_uuid"],
                row["msg_id"],
                row["user_query"],
                row["response_content"],
                row["source"],
                row["chatbot_type"],
                row["created_at"],
                row["reaction"],
                row["user_comment"],
            ))
            inserted += 1
        except Exception as e:
            log.error("Failed to insert session=%s msg=%s: %s", row["session_uuid"], row["msg_id"], e)
            conn.rollback()
            cur = conn.cursor()
            continue

    conn.commit()
    cur.close()
    conn.close()

    log.info("=== Migration Complete ===")
    log.info("Updated: %d  |  Inserted: %d  |  Total scanned: %d", updated, inserted, len(items))


if __name__ == "__main__":
    main()
