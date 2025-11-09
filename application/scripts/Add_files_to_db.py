import os
import re
import uuid
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

def add_document_with_metadata(db, text_splitter, file_path, splits):
    file_name = os.path.basename(file_path)

    if bool(re.match(r".*\.txt$", file_path, re.IGNORECASE)):
        loader = TextLoader(file_path, encoding='utf-8')
    elif bool(re.match(r".*\.pdf$", file_path, re.IGNORECASE)):
        loader = PyPDFLoader(file_path)
    else:
        return

    data = loader.load()
    print("data length:", len(data))

    for doc in data:
        print("Adding : ", file_path)
        doc.metadata['id'] = str(uuid.uuid4())  # Adding unique ID
        doc.metadata['source'] = file_path  # adding path name
        doc.metadata['name'] = file_name  # Adding file name

        # Split the document into chunks
        chunks = text_splitter.split_documents([doc])

        # Propagate metadata to each chunk
        for chunk in chunks:
            chunk.metadata = doc.metadata.copy()  # Ensure each chunk gets a copy of the metadata
            splits.append(chunk)


def main():
    # Initialize components
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
    embeddings = OpenAIEmbeddings()
    db = Chroma(persist_directory='docs/chroma/', embedding_function=embeddings)

    # Directory to walk through
    directory_path = "newData"
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
