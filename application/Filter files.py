"""
Query pgvector rag_chunks by source and write snippets to a file.
Usage: set DB_* env, then run with source query as argument or edit source_to_query below.
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


def retrieve_documents_by_source(source_query: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content, metadata FROM rag_chunks WHERE metadata->>'source' = %s",
                (source_query,),
            )
            return cur.fetchall()


def write_documents_to_file(rows, file_path: str):
    with open(file_path, "w", encoding="utf-8") as f:
        for row in rows:
            doc_id, content, metadata = row[0], row[1], row[2]
            f.write(f"Document ID: {doc_id}\n")
            f.write(f"Metadata: {metadata}\n")
            f.write(f"Content (snippet): {(content or '')[:200]}...\n")
            f.write("-" * 40 + "\n")


if __name__ == "__main__":
    source_to_query = os.environ.get("SOURCE_QUERY", "newData/100+ Water Saving Tips.pdf")
    if len(sys.argv) > 1:
        source_to_query = sys.argv[1]
    rows = retrieve_documents_by_source(source_to_query)
    if rows:
        print(f"Found {len(rows)} chunks with source: {source_to_query}")
        write_documents_to_file(rows, os.path.join(_application_dir, "retrieved_documents.txt"))
        print("Written to retrieved_documents.txt")
    else:
        print("No documents found with the specified source.")
