"""
Remove personal email addresses from chunks already stored in rag_chunks.

New ingests are scrubbed automatically (see the Add_*_to_db scripts); this
script cleans what is already in the database. Shared agency mailboxes
(info@, compliance@, ...) are kept, the same rule the chat output uses.

Usage (from the application directory):
    python scripts/scrub_rag_chunks.py            # dry run: counts only, changes nothing
    python scripts/scrub_rag_chunks.py --apply    # update the affected chunks

Reads DATABASE_URL (or DB_HOST/DB_USER/DB_PASSWORD/DB_NAME/DB_PORT) from the
environment or the project .env. Prints counts only, never the addresses.
Embeddings are kept as they are: removing an email address barely changes a
chunk's meaning, and re-embedding would cost an OpenAI call per chunk.
"""
import argparse
import hashlib
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_application_dir = os.path.dirname(_script_dir)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from guardrails import redact_personal_emails  # noqa: E402


def _connect():
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg.connect(url)
    params = {
        "host": os.getenv("DB_HOST"), "user": os.getenv("DB_USER"), "password": os.getenv("DB_PASSWORD"),
        "dbname": os.getenv("DB_NAME"), "port": os.getenv("DB_PORT", "5432"),
    }
    if not all(params[k] for k in ("host", "user", "password", "dbname")):
        sys.exit("Set DATABASE_URL or DB_HOST, DB_USER, DB_PASSWORD, DB_NAME.")
    return psycopg.connect(**params)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(_application_dir), ".env"))
    changed = []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, doc_id, content FROM rag_chunks WHERE content LIKE '%@%'")
            for chunk_id, doc_id, content in cur.fetchall():
                cleaned = redact_personal_emails(content)
                if cleaned != content:
                    changed.append((chunk_id, doc_id, cleaned))

            documents = sorted({doc_id or "(no doc_id)" for _, doc_id, _ in changed})
            print(f"Chunks with personal email addresses: {len(changed)} in {len(documents)} document(s)")
            for name in documents:
                print(f"  {name}")

            if not args.apply:
                print("Dry run: nothing was changed. Re-run with --apply to update these chunks.")
                return 0
            for chunk_id, _, cleaned in changed:
                cur.execute(
                    "UPDATE rag_chunks SET content = %s, content_hash = %s WHERE id = %s",
                    (cleaned, hashlib.sha256(cleaned.encode("utf-8")).hexdigest(), chunk_id),
                )
        conn.commit()
    print(f"Updated {len(changed)} chunk(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
