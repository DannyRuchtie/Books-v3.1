import warnings
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
import base64
import mimetypes
import shutil

# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib.epub")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib.epub")

# Setting the environment
EPUB_FILE_PATH = os.path.join("books", "Creativity-Inc.epub")
CHROMA_PATH = os.path.join("chroma_db")

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

# New function to extract metadata and cover
def extract_book_info(epub_path):
    book = epub.read_epub(epub_path, options={'ignore_ncx': True})
    
    metadata = {}
    for namespace in book.metadata:
        for name, values in book.metadata[namespace].items():
            metadata[name] = values[0] if values else None
    
    # Find the cover image
    cover_item = None
    cover_path = None
    
    # Method 1: Check for cover in metadata
    cover_id = metadata.get('cover')
    
    if cover_id:
        cover_item = book.get_item_with_id(cover_id)
    
    # Method 2: Check for 'cover' in item name
    if not cover_item:
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                if item.get_name().lower().startswith('cover'):
                    cover_item = item
                    break
    
    # Method 3: Check for 'cover' in item name or id
    if not cover_item:
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                if 'cover' in item.get_name().lower() or 'cover' in item.id.lower():
                    cover_item = item
                    break
    
    # Method 4: Use the first image as cover if no other method worked
    if not cover_item:
        images = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_IMAGE]
        if images:
            cover_item = images[0]
    
    if cover_item:
        covers_dir = "covers"
        os.makedirs(covers_dir, exist_ok=True)
        
        # Extract the identifier properly
        identifier = metadata.get('identifier', 'unknown')
        if isinstance(identifier, tuple):
            identifier = identifier[0]  # Use the first element if it's a tuple
        
        # Ensure the identifier is a valid filename
        identifier = "".join(c for c in identifier if c.isalnum() or c in ('-', '_'))
        
        cover_filename = f"{identifier}{os.path.splitext(cover_item.get_name())[1]}"
        cover_path = os.path.join(covers_dir, cover_filename)
        with open(cover_path, 'wb') as f:
            f.write(cover_item.get_content())
    
    # Extract content
    content = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content.append(item.get_content())
    
    return metadata, cover_path, content

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

# Extract book info
print("\n--- Extracting book metadata and content ---")
book_metadata, cover_path, content = extract_book_info(EPUB_FILE_PATH)

print("Book Metadata:")
for key, value in book_metadata.items():
    print(f"  {key}: {value if value is not None else 'Not available'}")

print(f"Cover image extracted: {'Yes' if cover_path else 'No'}")
if cover_path:
    print(f"Cover image saved to: {cover_path}")
else:
    print("No cover image found")

print(f"Number of documents extracted: {len(content)}")

# Add book metadata to ChromaDB
try:
    print("\n--- Adding book metadata to ChromaDB ---")
    # Clean metadata to remove None values
    cleaned_metadata = {k: str(v) if v is not None else "Not available" for k, v in book_metadata.items()}
    cleaned_metadata["type"] = "book_metadata"
    cleaned_metadata["cover_path"] = cover_path if cover_path else "No cover"
    
    metadata_id = f"metadata_{book_metadata['identifier']}"
    
    collection.upsert(
        documents=[str(cleaned_metadata)],
        metadatas=[cleaned_metadata],
        ids=[metadata_id]
    )
    print(f"Book metadata added to ChromaDB successfully with ID: {metadata_id}")
    print(f"Metadata content: {cleaned_metadata}")
except Exception as e:
    print(f"Failed to add book metadata to ChromaDB: {e}")

# Verify metadata was added
try:
    results = collection.get(ids=[metadata_id])
    if results['ids']:
        print(f"Successfully retrieved metadata with ID: {metadata_id}")
        print(f"Retrieved metadata: {results['metadatas'][0]}")
    else:
        print(f"Failed to retrieve metadata with ID: {metadata_id}")
except Exception as e:
    print(f"Error when trying to retrieve metadata: {e}")

# Combine all content into a single string
raw_text = "\n".join([BeautifulSoup(doc, 'html.parser').get_text() for doc in content])

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
metadata = [{
    "source": EPUB_FILE_PATH,
    "book_id": book_metadata['identifier'],
    "title": book_metadata.get('title', 'Unknown'),
    "author": book_metadata.get('author', 'Unknown'),
    "language": book_metadata.get('language', 'Unknown'),
    "cover_path": cover_path if cover_path else "No cover"
} for _ in chunks]

# Generate unique IDs for each chunk
ids = [f"{book_metadata['identifier']}_{i}" for i in range(len(chunks))]

# When upserting chunks, ensure all values are strings
try:
    print("Starting to upsert into ChromaDB...")
    for i in range(0, len(documents), 100):
        batch_documents = documents[i:i+100]
        batch_metadata = [{k: str(v) for k, v in m.items()} for m in metadata[i:i+100]]
        batch_ids = ids[i:i+100]
        
        collection.upsert(
            documents=batch_documents,
            metadatas=batch_metadata,
            ids=batch_ids
        )
        print(f"Upserted batch {i//100 + 1} of {len(documents)//100 + 1}")
    print("Upsert complete.")
except Exception as e:
    print(f"Failed to upsert into ChromaDB: {e}")

# After all upserts are complete
try:
    total_items = collection.count()
    print(f"Total items in collection after upserts: {total_items}")
except Exception as e:
    print(f"Error when trying to count items in collection: {e}")