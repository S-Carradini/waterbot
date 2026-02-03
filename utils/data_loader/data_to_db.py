###########################################################################
#####  Loads documents into pgvector RAG store. Requires REFACTOR.   #####
#####  Prefer application/scripts/Add_files_to_db.py for ingestion.   #####
###########################################################################

import os
import re
import sys

# Allow importing application managers when run from repo root
_app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "application"))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_community.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OpenAIEmbeddings

api_key_file_path = os.path.join(os.path.dirname(__file__), "openai_api_key.txt")
if os.path.isfile(api_key_file_path):
    with open(api_key_file_path, "r") as f:
        os.environ.setdefault("OPENAI_API_KEY", f.read().strip())

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
directory_path = os.path.join(os.path.dirname(__file__), "..", "Data")

splits = []
for root, dirs, files in os.walk(directory_path):
    for file in files:
        file_path = os.path.join(root, file)
        print("file path", file_path)
        if re.match(r".*\.txt$", file_path, re.IGNORECASE):
            loader = TextLoader(file_path, encoding="utf-8")
            data = loader.load()
        elif re.match(r".*\.pdf$", file_path, re.IGNORECASE):
            loader = PyPDFLoader(file_path)
            data = loader.load()
        else:
            continue
        splits.extend(text_splitter.split_documents(data))

if not splits:
    print("No documents to load.")
    sys.exit(0)

embeddings = OpenAIEmbeddings()
db_host = os.getenv("DB_HOST")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")
if not all([db_host, db_user, db_password, db_name]):
    print("Set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME for pgvector.")
    sys.exit(1)

from managers.pgvector_store import PgVectorStore

store = PgVectorStore(
    db_params={"dbname": db_name, "user": db_user, "password": db_password, "host": db_host, "port": "5432"},
    embedding_function=embeddings,
)
store.add_documents(splits, locale="en")
print("Done.")
