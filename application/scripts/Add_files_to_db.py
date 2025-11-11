import os
import re
import uuid
import sys
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

# Load environment variables from .env file
load_dotenv()

def add_document_with_metadata(db, text_splitter, file_path, splits):
    file_name = os.path.basename(file_path)

    try:
        if bool(re.match(r".*\.txt$", file_path, re.IGNORECASE)):
            loader = TextLoader(file_path, encoding='utf-8')
        elif bool(re.match(r".*\.pdf$", file_path, re.IGNORECASE)):
            loader = PyPDFLoader(file_path)
        else:
            return

        data = loader.load()
        print(f"data length: {len(data)}")

        for doc in data:
            print(f"Adding : {file_path}")
            doc.metadata['id'] = str(uuid.uuid4())  # Adding unique ID
            doc.metadata['source'] = file_path  # adding path name
            doc.metadata['name'] = file_name  # Adding file name

            # Split the document into chunks
            chunks = text_splitter.split_documents([doc])

            # Propagate metadata to each chunk
            for chunk in chunks:
                chunk.metadata = doc.metadata.copy()  # Ensure each chunk gets a copy of the metadata
                splits.append(chunk)
    except Exception as e:
        print(f"❌ Error processing {file_path}: {str(e)}", file=sys.stderr)
        raise


def main():
    print("🚀 Starting RAG loader...")
    print(f"Working directory: {os.getcwd()}")
    print(f"OPENAI_API_KEY: {'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
    
    # Get the script's directory and resolve paths relative to it
    script_dir = os.path.dirname(os.path.abspath(__file__))
    application_dir = os.path.dirname(script_dir)  # Go up from scripts/ to application/
    project_root = os.path.dirname(application_dir)  # Go up from application/ to project root
    
    # Try multiple possible locations for newData directory
    possible_paths = [
        os.path.join(application_dir, 'newData'),  # application/newData
        os.path.join(project_root, 'application', 'newData'),  # project_root/application/newData
        os.path.join(os.getcwd(), 'newData'),  # current_dir/newData
        os.path.join(os.getcwd(), 'application', 'newData'),  # current_dir/application/newData
    ]
    
    directory_path = None
    for path in possible_paths:
        if os.path.exists(path):
            directory_path = path
            print(f"✅ Found newData directory at: {directory_path}")
            break
    
    if not directory_path:
        print(f"❌ Could not find newData directory. Tried:", file=sys.stderr)
        for path in possible_paths:
            print(f"   - {path}", file=sys.stderr)
        sys.exit(1)
    
    # Initialize components
    try:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
        embeddings = OpenAIEmbeddings()
        # Use path relative to application directory for ChromaDB
        chroma_path = os.path.join(application_dir, 'docs', 'chroma')
        db = Chroma(persist_directory=chroma_path, embedding_function=embeddings,collection_metadata={"hnsw:space": "cosine"})
        print("✅ ChromaDB initialized")
    except Exception as e:
        print(f"❌ Failed to initialize ChromaDB: {str(e)}", file=sys.stderr)
        sys.exit(1)
    
    pdf_count = len([f for f in os.listdir(directory_path) if f.lower().endswith('.pdf')])
    print(f"📄 Found {pdf_count} PDF files in {directory_path}")
    
    batch_size = 20
    batch = []
    batch_count = 0

    # Walk through the directory and add documents in batches
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            batch.append(file_path)
            # When the batch size is reached, process and clear the batch
            if len(batch) >= batch_size:
                process_batch(batch, db, text_splitter)
                batch = []  # Clear the batch
                batch_count += 1
                print(f"Batch {batch_count} processed.")

    # Process any remaining files in the last batch
    if batch:
        process_batch(batch, db, text_splitter)
        print(f"Final batch {batch_count + 1} processed.")
    
    print("✅ RAG loading complete!")

def process_batch(batch, db, text_splitter):
    splits = []
    for file_path in batch:
        add_document_with_metadata(db, text_splitter, file_path, splits)
    
    # Add documents to the database
    try:
        db.add_documents(documents=splits)
        print(f"Successfully added {len(splits)} documents from the batch to ChromaDB.")
    except Exception as e:
        print(f"Failed to add documents to ChromaDB: {e}")

if __name__ == "__main__":
    main()
