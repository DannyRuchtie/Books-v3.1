import chromadb
import os

# Setting the environment
CHROMA_PATH = os.path.join("chroma_db")
USER_ID = "79c8d98e-b923-48f4-b2bd-0feeb4285419"  # Hard-coded user_id

# Initialize ChromaDB client
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")



def get_all_books_info():
    # print(f"Querying books for user_id: {USER_ID}")
    
    # Query for all metadata entries for the specified user
    results = collection.query(
        query_texts=[""],
        where={"$and": [{"type": "book_metadata"}, {"user_id": USER_ID}]},
        include=["metadatas"]
    )
    
    # print(f"DEBUG: Query results: {results}")

    books_info = []
    for id, metadata in zip(results['ids'], results['metadatas']):
        # Ensure metadata is a dictionary
        metadata = metadata[0] if metadata else {}
        
        # print(f"\nDEBUG: Processing book with ID: {id}")
        # print(f"DEBUG: Metadata: {metadata}")
        
        title = metadata.get('title', 'Unknown Title')
        cover_url = metadata.get('cover_url', 'No cover')
        identifier = metadata.get('identifier', 'Unknown')
        
        books_info.append({
            'id': id,
            'identifier': identifier,
            'title': title,
            'cover_url': cover_url
        })

    return books_info

if __name__ == "__main__":
    # print("\nDEBUG: Querying all items in the collection")
    all_items = collection.get(include=["metadatas"])
    # print(f"Total items: {len(all_items['ids'])}")
    # for id, metadata in zip(all_items['ids'], all_items['metadatas']):
    #     print(f"ID: {id}")
    #     # print(f"Metadata: {metadata}")
    #     print("---")

    books = get_all_books_info()
    
    # print(f"\nFound {len(books)} books for user {USER_ID}:")
    for book in books:
        print(f"Database ID: {book['id']}")
        print(f"Title: {book['title']}")
        print(f"Book Identifier (e.g., ISBN): {book['identifier']}")
        print(f"Cover URL: {book['cover_url']}")
        print("---")

    if not books:
        print("No books found for this user.")