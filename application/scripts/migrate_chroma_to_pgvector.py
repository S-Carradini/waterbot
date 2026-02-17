"""
Migrate existing ChromaDB collections (en + es) to pgvector rag_chunks table.
Run from application directory. Requires chromadb (pip install chromadb) for one-time migration.
Set DATABASE_URL (e.g. Railway) or DB_HOST, DB_USER, DB_PASSWORD, DB_NAME.
DATABASE_URL must be: postgresql://USER:PASSWORD@HOST:PORT/DATABASE
(no extra @ in the middle; if password contains @ or :, URL-encode it as %40 or %3A).
Usage: python scripts/migrate_chroma_to_pgvector.py
"""
import hashlib
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_application_dir = os.path.dirname(_script_dir)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from dotenv import load_dotenv
# Load application/.env first, then root .env with override so root (canonical) wins
load_dotenv(os.path.join(_application_dir, ".env"))
load_dotenv(os.path.join(os.path.dirname(_application_dir), ".env"), override=True)


def migrate_locale(chroma_persist_path: str, locale: str, pg_store) -> int:
    try:
        import chromadb
    except ImportError:
        print("❌ chromadb required for migration. pip install chromadb", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(chroma_persist_path):
        print(f"⚠️  Chroma path not found: {chroma_persist_path}, skipping locale={locale}")
        return 0

    client = chromadb.PersistentClient(path=chroma_persist_path)
    # LangChain Chroma uses collection name "langchain" by default
    try:
        coll = client.get_collection("langchain")
    except Exception as e:
        print(f"⚠️  No collection 'langchain' in {chroma_persist_path}: {e}", file=sys.stderr)
        return 0

    result = coll.get(include=["documents", "embeddings", "metadatas"])
    ids = result["ids"]
    documents = result["documents"]
    embeddings = result["embeddings"]
    metadatas = result["metadatas"] or []

    if not ids:
        print(f"   No documents in {chroma_persist_path} for locale={locale}")
        return 0

    doc_ids = []
    chunk_indices = []
    content_hashes = []
    metadatas_ser = []
    for i, (id_, doc, meta) in enumerate(zip(ids, documents, metadatas)):
        meta = meta or {}
        doc_ids.append(meta.get("source", id_))
        chunk_indices.append(i)
        content_hashes.append(hashlib.sha256((doc or "").encode("utf-8")).hexdigest())
        metadatas_ser.append(meta)

    pg_store.upsert_batch(
        ids=ids,
        doc_ids=doc_ids,
        chunk_indices=chunk_indices,
        contents=[d or "" for d in documents],
        embeddings=embeddings,
        metadatas=metadatas_ser,
        content_hashes=content_hashes,
        locale=locale,
    )
    return len(ids)


def main():
    print("🚀 ChromaDB → pgvector migration")
    application_dir = _application_dir

    database_url = os.getenv("DATABASE_URL")
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")

    from managers.pgvector_store import PgVectorStore

    if database_url:
        pg_store = PgVectorStore(db_url=database_url, embedding_function=None)
    elif all([db_host, db_user, db_password, db_name]):
        pg_store = PgVectorStore(
            db_params={"dbname": db_name, "user": db_user, "password": db_password, "host": db_host, "port": "5432"},
            embedding_function=None,
        )
    else:
        print("❌ Set DATABASE_URL or DB_HOST, DB_USER, DB_PASSWORD, DB_NAME", file=sys.stderr)
        sys.exit(1)

    chroma_en = os.path.join(application_dir, "docs", "chroma")
    chroma_es = os.path.join(application_dir, "docs", "chroma", "spanish")

    n_en = migrate_locale(chroma_en, "en", pg_store)
    n_es = migrate_locale(chroma_es, "es", pg_store)

    print(f"✅ Migration complete: {n_en} chunks (en), {n_es} chunks (es)")


if __name__ == "__main__":
    main()
