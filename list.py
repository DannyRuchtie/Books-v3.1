import chromadb
import os

# Setting the environment
CHROMA_PATH = os.path.join("chroma_db")

# Initialize ChromaDB client
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

def get_all_books_info():
    # Query for all metadata entries
    results = collection.get(
        where={"type": "book_metadata"},
        include=["metadatas"]
    )

    books_info = []
    for id, metadata in zip(results['ids'], results['metadatas']):
        title = metadata.get('title', 'Unknown Title')
        cover_path = metadata.get('cover_path', 'No cover')
        identifier = metadata.get('identifier', 'Unknown')
        
        # Convert local file path to URL (you may need to adjust this based on your server setup)
        cover_url = f"/covers/{os.path.basename(cover_path)}" if cover_path != 'No cover' else None
        
        books_info.append({
            'id': id,  # This is the database key
            'identifier': identifier,  # This is the book's ISBN or other identifier
            'title': title,
            'cover_url': cover_url
        })

    return books_info

if __name__ == "__main__":
    books = get_all_books_info()
    print(f"Found {len(books)} books:")
    for book in books:
        print(f"Database ID: {book['id']}")
        print(f"Title: {book['title']}")
        print(f"Book Identifier (e.g., ISBN): {book['identifier']}")
        print(f"Cover URL: {book['cover_url']}")
        print("---")