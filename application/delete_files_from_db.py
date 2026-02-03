"""
Delete RAG chunks by source path from pgvector rag_chunks table.
Usage: set DB_* env, then run with source path as argument or edit source_to_delete below.
"""
import os
import sys

_application_dir = os.path.dirname(os.path.abspath(__file__))
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(_application_dir, ".env"))

import psycopg
from pgvector.psycopg import register_vector


def _connect():
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    if not all([db_host, db_user, db_password, db_name]):
        print("Set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME")
        sys.exit(1)
    conn = psycopg.connect(
        dbname=db_name, user=db_user, password=db_password, host=db_host, port="5432"
    )
    register_vector(conn)
    return conn


def delete_documents_by_source(source_query: str) -> int:
    """Delete rows in rag_chunks whose metadata->>'source' matches source_query."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rag_chunks WHERE metadata->>'source' = %s RETURNING id",
                (source_query,),
            )
            deleted = cur.rowcount
        conn.commit()
    return deleted


if __name__ == "__main__":
    source_to_delete = os.environ.get("SOURCE_TO_DELETE", "newData/Nogales Water-2.pdf")
    if len(sys.argv) > 1:
        source_to_delete = sys.argv[1]
    n = delete_documents_by_source(source_to_delete)
    print(f"Deleted {n} chunks with source: {source_to_delete}")
