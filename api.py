print("Starting api.py")
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
from rq import Queue
from redis import Redis
from fastapi.responses import FileResponse
import tempfile
import shutil
import pathlib
from pathlib import Path

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

# Redis and RQ setup
redis_conn = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'))
q = Queue('default', connection=redis_conn)

# OpenAI client setup
client = AsyncOpenAI()

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve the index.html file
@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

class Book(BaseModel):
    id: str
    identifier: str
    title: str
    creator: str
    cover_url: str
    description: str

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
    
    books = []
    for id_list, metadata_list in zip(results['ids'], results['metadatas']):
        for i in range(len(id_list)):
            book_id = str(id_list[i])
            metadata = metadata_list[i]
            books.append(Book(
                id=book_id,
                identifier=metadata.get('identifier', 'Unknown'),
                title=metadata.get('title', 'Unknown Title'),
                creator=metadata.get('creator', 'Unknown Author'),
                cover_url=metadata.get('cover_url', '/static/default_cover.jpg'),
                description=metadata.get('description', 'No description available')
            ))
    
    return books

from book_processing import process_book

@app.post("/upload/{user_id}")
async def upload_file(user_id: str, file: UploadFile = File(...)):
    try:
        # Create a directory for temporary files if it doesn't exist
        temp_dir = os.path.join(os.getcwd(), "temp_uploads")
        os.makedirs(temp_dir, exist_ok=True)

        # Save the file with a unique name
        file_extension = os.path.splitext(file.filename)[1]
        temp_file_name = f"{uuid.uuid4()}{file_extension}"
        temp_file_path = os.path.join(temp_dir, temp_file_name)

        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        book_id = str(uuid.uuid4())
        
        # Enqueue the book processing task
        job = q.enqueue(process_book, temp_file_path, user_id, book_id, file.filename)
        
        return {"message": "File uploaded successfully and queued for processing", "book_id": book_id, "job_id": job.id}
    except Exception as e:
        logger.error(f"Error processing upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing upload: {str(e)}")

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
os.makedirs(covers_dir, exist_ok=True)
app.mount("/covers", StaticFiles(directory=covers_dir), name="covers")

@app.delete("/books/{book_id}")
async def delete_book(book_id: str, user_id: str = Depends(get_user_id)):
    try:
        # Query to find the book
        results = collection.get(
            ids=[book_id],
            where={"$and": [{"type": "book_metadata"}, {"user_id": user_id}]}
        )

        # Check if the book exists and belongs to the user
        if not results['ids']:
            raise HTTPException(status_code=404, detail="Book not found or does not belong to the user")

        # Delete the book metadata
        collection.delete(ids=[book_id])

        # Delete associated chunks (if any)
        chunk_results = collection.get(
            where={"$and": [{"book_id": book_id}, {"user_id": user_id}]}
        )
        if chunk_results['ids']:
            collection.delete(ids=chunk_results['ids'])

        return {"message": "Book and associated chunks deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.get("/books/{user_id}")
async def get_books(user_id: str):
    try:
        CHROMA_PATH = os.path.join("chroma_db")
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_collection(name="books")

        # Query for book metadata entries for the specific user
        results = collection.query(
            query_texts=["book_metadata"],
            where={"user_id": user_id, "type": "book_metadata"},
            include=["metadatas"]
        )

        books = []
        for metadata in results['metadatas']:
            books.append({
                "title": metadata.get('title', 'Unknown Title'),
                "author": metadata.get('creator', 'Unknown Author'),
                "cover_url": metadata.get('cover_url', '/static/default_cover.jpg')
            })

        return books
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

