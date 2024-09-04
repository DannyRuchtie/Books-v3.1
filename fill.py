import warnings
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb

# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib.epub")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib.epub")

# Setting the environment
EPUB_FILE_PATH = os.path.join("books", "Creative-Selection.epub")
CHROMA_PATH = os.path.join("chroma_db")

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

# Loading the document
def epub_to_text(epub_path):
    book = epub.read_epub(epub_path, options={'ignore_ncx': True})
    text = ""
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text += soup.get_text() + "\n"
    return text

# Error handling for loading EPUB and extracting text
try:
    print("Loading EPUB and extracting text...")
    raw_text = epub_to_text(EPUB_FILE_PATH)
    print("Text extraction complete.")
except Exception as e:
    print(f"Failed to load or parse EPUB file: {e}")
    raw_text = ""

# Splitting the document
print("Splitting the text into chunks...")
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    length_function=len,
)

chunks = text_splitter.split_text(raw_text)
print(f"Splitting complete. Number of chunks created: {len(chunks)}")

# Preparing to be added to ChromaDB
documents = chunks
metadata = [{"source": EPUB_FILE_PATH} for _ in chunks]
ids = [f"ID{i}" for i in range(len(chunks))]

# Error handling for ChromaDB upsert operation



try:
    print("Starting to upsert into ChromaDB...")
    for i in range(0, len(documents), 100):  # Batch upsert in groups of 100 for progress monitoring
        collection.upsert(
            documents=documents[i:i+100],
            metadatas=metadata[i:i+100],
            ids=ids[i:i+100]
        )
        print(f"Upserted batch {i//100 + 1} of {len(documents)//100 + 1}")
    print("Upsert complete.")
except Exception as e:
    print(f"Failed to upsert into ChromaDB: {e}")