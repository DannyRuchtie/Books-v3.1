from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from typing import List
import chromadb
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
import tempfile
import shutil
import zipfile
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
import uuid
import magic  # You'll need to install this: pip install python-magic
import json
import io
import chardet
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ChromaDB setup
CHROMA_PATH = os.path.join("chroma_db")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

# OpenAI client setup
client = AsyncOpenAI()

class Book(BaseModel):
    id: str
    identifier: str
    title: str
    cover_url: str

class Question(BaseModel):
    user_id: str
    book_id: str
    query: str

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    user_id: str
    book_id: str
    messages: List[Message]

    @validator('messages')
    def last_message_must_be_user(cls, v):
        if not v or v[-1].role != "user":
            raise ValueError("The last message must be from the user")
        return v

def get_user_id(user_id: str):
    # In a real application, you'd validate the user_id here
    return user_id

@app.get("/books/{user_id}", response_model=List[Book])
async def list_books(user_id: str = Depends(get_user_id)):
    results = collection.query(
        query_texts=[""],
        where={"$and": [{"type": "book_metadata"}, {"user_id": user_id}]},
        include=["metadatas"]
    )
    
    print("DEBUG: Query results structure:")
    print(f"IDs: {results['ids']}")
    print(f"Metadatas: {results['metadatas']}")

    books = []
    for id_list, metadata_list in zip(results['ids'], results['metadatas']):
        # Process each book in the results
        for i in range(len(id_list)):
            book_id = str(id_list[i])
            metadata = metadata_list[i]
            books.append(Book(
                id=book_id,
                identifier=metadata.get('identifier', 'Unknown'),
                title=metadata.get('title', 'Unknown Title'),
                cover_url=metadata.get('cover_url', 'No cover')
            ))
    
    print(f"DEBUG: Processed {len(books)} books")
    for book in books:
        print(f"Book: {book.title}")

    return books

def extract_book_info(epub_path):
    logger.debug(f"Starting to extract book info from {epub_path}")
    book = epub.read_epub(epub_path, options={'ignore_ncx': True})
    
    # Initialize metadata dictionary
    metadata = {}
    
    # Safely extract metadata
    try:
        for namespace in book.metadata:
            for name, values in book.metadata[namespace].items():
                if values:
                    metadata[name] = values[0][0]
        logger.debug(f"Extracted metadata: {metadata}")
    except Exception as e:
        logger.error(f"Error extracting metadata: {str(e)}")
    
    # Extract cover
    cover_path = None
    try:
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                if 'cover' in item.get_name().lower() or 'cover' in item.id.lower():
                    covers_dir = "covers"
                    os.makedirs(covers_dir, exist_ok=True)
                    logger.debug(f"Created covers directory: {covers_dir}")
                    
                    identifier = metadata.get('identifier', 'unknown')
                    logger.debug(f"Book identifier: {identifier}")
                    
                    # Handle the case where identifier might be a dictionary
                    if isinstance(identifier, dict):
                        identifier = str(identifier.get('id', 'unknown'))
                    elif identifier is None:
                        identifier = 'unknown'
                    else:
                        identifier = str(identifier)
                    
                    # Now that identifier is guaranteed to be a string, we can process it
                    identifier = "".join(c for c in identifier if c.isalnum() or c in ('-', '_'))
                    cover_filename = f"{identifier}{os.path.splitext(item.get_name())[1]}"
                    cover_path = os.path.join(covers_dir, cover_filename)
                    logger.debug(f"Attempting to save cover image to: {cover_path}")
                    
                    with open(cover_path, 'wb') as f:
                        f.write(item.get_content())
                    logger.debug(f"Cover image saved successfully")
                    break
        if not cover_path:
            logger.warning("No cover image found in the EPUB file")
    except Exception as e:
        logger.error(f"Error extracting cover image: {str(e)}")
    
    # Extract content
    content = []
    try:
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content.append(item.get_content().decode('utf-8'))
        logger.debug(f"Extracted {len(content)} content items")
    except Exception as e:
        logger.error(f"Error extracting content: {str(e)}")
    
    return metadata, cover_path, content

def clean_html(html_string):
    soup = BeautifulSoup(html_string, 'html.parser')
    return soup.get_text()

def clean_text(text):
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text

def clean_metadata(metadata):
    cleaned = {}
    for key, value in metadata.items():
        if key is not None and value is not None:
            if isinstance(value, list) and len(value) > 0:
                cleaned[str(key)] = str(value[0][0])  # Convert to string
            else:
                cleaned[str(key)] = str(value)  # Convert all values to strings
    return cleaned

@app.post("/upload/{user_id}")
async def upload_book(user_id: str, file: UploadFile = File(...)):
    temp_file_path = None
    try:
        # Read the file content
        content = await file.read()
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        print(f"Temporary file created: {temp_file_path}")

        # Check if it's a valid ZIP file
        if zipfile.is_zipfile(temp_file_path):
            with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                epub_files = [f for f in zip_ref.namelist() if f.lower().endswith('.epub')]
                if epub_files:
                    # Extract the first EPUB file found
                    epub_path = zip_ref.extract(epub_files[0], path=os.path.dirname(temp_file_path))
                    os.unlink(temp_file_path)  # Remove the original zip file
                    temp_file_path = epub_path  # Update the path to the extracted EPUB
                    print(f"Extracted EPUB file: {temp_file_path}")

        # Process the EPUB file
        book_metadata, cover_path, content = extract_book_info(temp_file_path)
        
        print("Debug: Raw metadata:", book_metadata)  # Debug print

        cleaned_metadata = clean_metadata(book_metadata)
        cleaned_metadata["type"] = "book_metadata"
        cleaned_metadata["user_id"] = user_id

        if cover_path:
            cover_filename = os.path.basename(cover_path)
            cleaned_metadata["cover_url"] = f"/covers/{cover_filename}"
        else:
            cleaned_metadata["cover_url"] = "No cover"

        # Truncate description if it's too long
        if "description" in cleaned_metadata:
            cleaned_metadata["description"] = cleaned_metadata["description"][:1000]  # Limit to 1000 characters

        book_id = str(uuid.uuid4())
        metadata_id = f"metadata_{user_id}_{book_id}"

        print("Debug: Cleaned metadata:", cleaned_metadata)  # Debug print

        # Process and store the book content
        print("Starting content chunking...")
        raw_text = "\n".join([clean_html(doc) for doc in content])
        cleaned_text = clean_text(raw_text)

        print(f"Total text length: {len(cleaned_text)} characters")

        chunk_size = 1000
        chunk_overlap = 10
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = splitter.split_text(cleaned_text)

        print(f"Number of chunks created: {len(chunks)}")

        for i, chunk in enumerate(chunks):
            chunk_id = f"{user_id}_{book_id}_{i}"
            chunk_metadata = {
                "source": file.filename,
                "book_id": book_id,
                "title": cleaned_metadata.get('title', 'Unknown'),
                "author": cleaned_metadata.get('creator', 'Unknown'),
                "language": cleaned_metadata.get('language', 'Unknown'),
                "cover_url": cleaned_metadata["cover_url"],
                "user_id": user_id,
                "chunk_index": i
            }
            print(f"Upserting chunk {i+1}/{len(chunks)}, length: {len(chunk)} characters")
            collection.upsert(
                documents=[chunk],
                metadatas=[chunk_metadata],
                ids=[chunk_id]
            )

        print("Chunking and upserting complete")

        # Store the book metadata
        collection.upsert(
            documents=[json.dumps(cleaned_metadata)],  # Convert to JSON string
            metadatas=[cleaned_metadata],
            ids=[metadata_id]
        )

        return {"message": "Book uploaded and processed successfully", "book_id": book_id}

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        print(f"Error type: {type(e)}")
        print(f"Error args: {e.args}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
            print(f"Temporary file deleted: {temp_file_path}")

@app.post("/ask")
async def ask_question(question: Question):
    # First, retrieve the book metadata
    book_metadata = collection.get(
        ids=[question.book_id],
        where={"user_id": question.user_id}
    )
    
    if not book_metadata['metadatas']:
        raise HTTPException(status_code=404, detail="Book not found")
    
    book_description = book_metadata['metadatas'][0].get('description', 'No description available')
    
    # Query for relevant content
    results = collection.query(
        query_texts=[question.query],
        where={"$and": [{"user_id": question.user_id}, {"book_id": question.book_id}]},
        n_results=10
    )

    system_prompt = f"""
    You are a helpful assistant. You answer questions about a specific book. 
    Only use the knowledge I'm providing you. Use your internal knowledge only if you're absolutely sure it's about this book and don't make things up. 
    If you don't know the answer, just say something like: I don't know.
    --------------------
    Book Description:
    {book_description}
    --------------------
    Relevant Content:
    {str(results['documents'])}
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question.query}
    ]
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    
    return {"answer": response.choices[0].message.content}

@app.post("/chat")
async def chat(request: ChatRequest):
    # Retrieve book metadata
    book_metadata = collection.get(
        ids=[request.book_id],
        where={"user_id": request.user_id}
    )
    
    if not book_metadata['metadatas']:
        raise HTTPException(status_code=404, detail="Book not found")
    
    book_description = book_metadata['metadatas'][0].get('description', 'No description available')
    
    # Query for relevant content based on the last user message
    last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    results = collection.query(
        query_texts=[last_user_message],
        where={"$and": [{"user_id": request.user_id}, {"book_id": request.book_id}]},
        n_results=5
    )

    system_prompt = f"""
    You are a helpful assistant. You answer questions about a specific book. 
    Only use the knowledge I'm providing you. Use your internal knowledge only if you're absolutely sure it's about this book and don't make things up. 
    If you don't know the answer, just say something like: I don't know.
    --------------------
    Book Description:
    {book_description}
    --------------------
    Relevant Content:
    {str(results['documents'])}
    """
    
    messages = [{"role": "system", "content": system_prompt}] + [m.dict() for m in request.messages]
    
    async def event_generator():
        stream = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield f"data: {chunk.choices[0].delta.content}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Serve static files from the 'covers' directory
covers_dir = os.path.join(os.path.dirname(__file__), "covers")
app.mount("/covers", StaticFiles(directory=covers_dir), name="covers")

@app.delete("/books/{book_id}")
async def delete_book(book_id: str, user_id: str = Depends(get_user_id)):
    try:
        # Query to find the book
        results = collection.query(
            query_texts=[""],
            where={"$and": [{"type": "book_metadata"}, {"user_id": user_id}]},
            ids=[book_id],
            include=["metadatas"]
        )

        # Check if the book exists and belongs to the user
        if not results['ids']:
            raise HTTPException(status_code=404, detail="Book not found or does not belong to the user")

        # Delete the book
        collection.delete(ids=[book_id])

        # Delete associated chunks (if any)
        chunk_results = collection.query(
            query_texts=[""],
            where={"$and": [{"type": "book_chunk"}, {"book_id": book_id}]},
            include=["metadatas"]
        )
        if chunk_results['ids']:
            collection.delete(ids=chunk_results['ids'])

        return {"message": "Book and associated chunks deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
