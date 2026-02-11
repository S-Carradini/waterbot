import os
import re
import sys
import uuid

# Ensure application root is on path when running as script
_script_dir = os.path.dirname(os.path.abspath(__file__))
_application_dir = os.path.dirname(_script_dir)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

load_dotenv(os.path.join(_application_dir, ".env"))

LOCALE = "es"


def add_document_with_metadata(store, text_splitter, file_path, splits):
    file_name = os.path.basename(file_path)

    try:
        if not os.path.exists(file_path):
            print(f"⚠️  Skipping {file_path}: File does not exist", file=sys.stderr)
            return

        if bool(re.match(r".*\.txt$", file_path, re.IGNORECASE)):
            loader = TextLoader(file_path, encoding='utf-8')
        elif bool(re.match(r".*\.pdf$", file_path, re.IGNORECASE)):
            loader = PyPDFLoader(file_path)
        else:
            return

        data = loader.load()
        if not data:
            return

        print(f"📄 Processing {file_name} ({len(data)} pages)")
        for doc in data:
            if not doc.page_content or len(doc.page_content.strip()) == 0:
                continue
            print(f"Adding : {file_path}")
            doc.metadata['id'] = str(uuid.uuid4())
            doc.metadata['source'] = file_path
            doc.metadata['name'] = file_name
            chunks = text_splitter.split_documents([doc])
            for chunk in chunks:
                chunk.metadata = doc.metadata.copy()
                splits.append(chunk)
    except Exception as e:
        print(f"⚠️  Skipping {file_path}: Error - {str(e)}", file=sys.stderr)
        return


def get_store(application_dir):
    embeddings = OpenAIEmbeddings()
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    if not all([db_host, db_user, db_password, db_name]):
        print("❌ pgvector requires DB_HOST, DB_USER, DB_PASSWORD, DB_NAME", file=sys.stderr)
        sys.exit(1)
    from managers.pgvector_store import PgVectorStore
    print("✅ PgVector store initialized (locale=es)")
    return PgVectorStore(
        db_params={"dbname": db_name, "user": db_user, "password": db_password, "host": db_host, "port": "5432"},
        embedding_function=embeddings,
    )


def main():
    print("🚀 Starting RAG loader (Spanish)...")
    print("Backend: pgvector")

    application_dir = _application_dir
    project_root = os.path.dirname(application_dir)
    possible_paths = [
        os.path.join(application_dir, 'newData'),
        os.path.join(project_root, 'application', 'newData'),
        os.path.join(os.getcwd(), 'newData'),
        os.path.join(os.getcwd(), 'application', 'newData'),
    ]
    directory_path = None
    for path in possible_paths:
        if os.path.exists(path):
            directory_path = path
            print(f"✅ Found newData at: {directory_path}")
            break
    if not directory_path:
        print("❌ Could not find newData directory.", file=sys.stderr)
        sys.exit(1)

    try:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
        store = get_store(application_dir)
    except Exception as e:
        print(f"❌ Failed to initialize store: {str(e)}", file=sys.stderr)
        sys.exit(1)

    splits = []
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            add_document_with_metadata(store, text_splitter, file_path, splits)

    if splits:
        try:
            store.add_documents(splits, locale=LOCALE)
            print(f"✅ Successfully added {len(splits)} documents to store (locale=es).")
        except Exception as e:
            print(f"❌ Failed to add documents: {e}", file=sys.stderr)
    else:
        print("⚠️  No documents to add.")

    print("✅ RAG loading complete (Spanish)!")


if __name__ == "__main__":
    main()
