import warnings
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
import re

# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib.epub")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib.epub")

# Setting the environment
EPUB_FILE_PATH = os.path.join("books", "Creativity-Inc.epub")
CHROMA_PATH = os.path.join("chroma_db")
USER_ID = "79c8d98e-b923-48f4-b2bd-0feeb4285419"  # Hard-coded user_id

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

def extract_book_info(epub_path):
    book = epub.read_epub(epub_path, options={'ignore_ncx': True})
    
    metadata = {}
    for namespace in book.metadata:
        for name, values in book.metadata[namespace].items():
            metadata[name] = values[0] if values else None
    
    cover_item = None
    cover_path = None
    
    # Find cover image (simplified)
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            if 'cover' in item.get_name().lower() or 'cover' in item.id.lower():
                cover_item = item
                break
    
    if cover_item:
        covers_dir = "covers"
        os.makedirs(covers_dir, exist_ok=True)
        identifier = metadata.get('identifier', 'unknown')
        
        # Handle the case where identifier might be a dictionary
        if isinstance(identifier, dict):
            identifier = str(identifier.get('id', 'unknown'))
        elif identifier is None:
            identifier = 'unknown'
        else:
            identifier = str(identifier)
        
        # Now that identifier is guaranteed to be a string, we can process it
        identifier = "".join(c for c in identifier if c.isalnum() or c in ('-', '_'))
        cover_filename = f"{identifier}{os.path.splitext(cover_item.get_name())[1]}"
        cover_path = os.path.join(covers_dir, cover_filename)
        with open(cover_path, 'wb') as f:
            f.write(cover_item.get_content())
    
    content = [item.get_content() for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
    
    return metadata, cover_path, content

def clean_html(html_string):
    # Remove HTML tags
    soup = BeautifulSoup(html_string, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    return text

def clean_text(text):
    # Remove any remaining HTML entities
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    # Replace multiple spaces, newlines, and tabs with a single space
    text = re.sub(r'\s+', ' ', text)
    # Strip leading and trailing whitespace
    text = text.strip()
    return text

def clean_metadata(metadata):
    cleaned = {}
    for key, value in metadata.items():
        if isinstance(value, str):
            # Clean HTML tags from string values
            cleaned[key] = clean_html(value)
        elif isinstance(value, (int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple)) and len(value) > 0:
            cleaned[key] = clean_html(str(value[0]))
        elif isinstance(value, dict):
            cleaned[key] = clean_html(str(value))
        else:
            cleaned[key] = clean_html(str(value))
    return cleaned

def process_and_upload_book(epub_path):
    print(f"Processing book for user_id: {USER_ID}")
    book_metadata, cover_path, content = extract_book_info(epub_path)

    cleaned_metadata = clean_metadata(book_metadata)
    cleaned_metadata["type"] = "book_metadata"
    cleaned_metadata["user_id"] = USER_ID

    if cover_path:
        cover_filename = os.path.basename(cover_path)
        cleaned_metadata["cover_url"] = f"/covers/{cover_filename}"
    else:
        cleaned_metadata["cover_url"] = "No cover"

    metadata_id = f"metadata_{USER_ID}_{cleaned_metadata.get('identifier', 'unknown')}"
    
    print("DEBUG: Cleaned metadata:")
    for key, value in cleaned_metadata.items():
        print(f"{key}: {value} (type: {type(value)})")

    collection.upsert(
        documents=[str(cleaned_metadata)],
        metadatas=[cleaned_metadata],
        ids=[metadata_id]
    )
    print(f"Book metadata added to ChromaDB with ID: {metadata_id}")

    print("\nProcessing book content...")
    raw_text = "\n".join([BeautifulSoup(doc, 'html.parser').get_text() for doc in content])
    cleaned_text = clean_text(raw_text)
    print(f"Total cleaned text length: {len(cleaned_text)} characters")

    print("\nChunking book content...")
    chunk_size = 1000
    chunk_overlap = 10
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = splitter.split_text(cleaned_text)
    
    print(f"Chunk size: {chunk_size}")
    print(f"Chunk overlap: {chunk_overlap}")
    print(f"Created {len(chunks)} chunks")

    # Print details of the first few chunks
    num_chunks_to_show = 3
    for i, chunk in enumerate(chunks[:num_chunks_to_show]):
        print(f"\nChunk {i+1}:")
        print(f"Length: {len(chunk)} characters")
        print(f"Preview: {chunk[:100]}...")  # Show first 100 characters of the chunk

    print("\nUploading chunks to ChromaDB...")
    for i, chunk in enumerate(chunks):
        chunk_id = f"{USER_ID}_{cleaned_metadata.get('identifier', 'unknown')}_{i}"
        chunk_metadata = {
            "source": epub_path,
            "book_id": cleaned_metadata.get('identifier', 'unknown'),
            "title": cleaned_metadata.get('title', 'Unknown'),
            "author": cleaned_metadata.get('creator', 'Unknown'),
            "language": cleaned_metadata.get('language', 'Unknown'),
            "cover_url": cleaned_metadata["cover_url"],
            "user_id": USER_ID,
            "chunk_index": i
        }
        collection.upsert(
            documents=[chunk],
            metadatas=[chunk_metadata],
            ids=[chunk_id]
        )
        if i % 50 == 0:  # Print progress every 50 chunks
            print(f"Uploaded {i+1}/{len(chunks)} chunks...")

    print(f"\nFinished uploading {len(chunks)} chunks for the book.")

if __name__ == "__main__":
    process_and_upload_book(EPUB_FILE_PATH)
    print("\nDEBUG: Querying all items in the collection")
    all_items = collection.get(include=["metadatas"])
    print(f"Total items: {len(all_items['ids'])}")