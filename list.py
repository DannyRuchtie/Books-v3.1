import chromadb
import os
import uuid

# Setting the environment
CHROMA_PATH = os.path.join("chroma_db")

# Initialize ChromaDB client
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

# Function to generate a default user_id (same as in upload.py)
def generate_default_user_id():
    return str(uuid.uuid4())

def get_all_books_info(user_id=None):
    if user_id is None:
        user_id = generate_default_user_id()
        print(f"No user_id provided. Using default: {user_id}")

    # Query for all metadata entries for the specified user
    results = collection.query(
        query_texts=[""],
        where={"$and": [{"type": "book_metadata"}, {"user_id": str(user_id)}]},
        include=["metadatas", "documents"]
    )

    books_info = []
    for id, metadata_list in zip(results['ids'], results['metadatas']):
        # Ensure metadata is a dictionary
        metadata = metadata_list[0] if metadata_list else {}
        
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
    # For development/testing, use a default user_id
    default_user_id = generate_default_user_id()
    print(f"Using default user_id for testing: {default_user_id}")
    
    # In a real application, you would get the user_id from authentication
    # For now, we'll use the default one
    books = get_all_books_info(default_user_id)
    
    print(f"Found {len(books)} books for user {default_user_id}:")
    for book in books:
        print(f"Database ID: {book['id']}")
        print(f"Title: {book['title']}")
        print(f"Book Identifier (e.g., ISBN): {book['identifier']}")
        print(f"Cover URL: {book['cover_url']}")
        print("---")

    if not books:
        print("No books found for this user.")

    print("\nTo test with books, run upload.py first, then use the user_id it generates here.")