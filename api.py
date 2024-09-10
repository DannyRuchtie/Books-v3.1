print("Starting api.py")
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import chromadb
import os
from dotenv import load_dotenv
import logging
import openai
from openai import OpenAI
import asyncio

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
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

# OpenAI setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    user_id: str
    book_id: str
    messages: List[ChatMessage]

def get_user_id(user_id: str):
    # In a real application, you'd validate the user_id here
    return user_id

@app.get("/books/{user_id}", response_model=List[Book])
async def list_books(user_id: str = Depends(get_user_id)):
    # Query the database each time this endpoint is called
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

@app.post("/chat")
async def chat(request: ChatRequest):
    # Retrieve book metadata
    book_metadata = collection.get(
        ids=[request.book_id],
        where={"user_id": request.user_id}
    )
    
    if not book_metadata['metadatas']:
        raise HTTPException(status_code=404, detail="Book not found")
    
    book_title = book_metadata['metadatas'][0].get('title', 'Unknown Title')
    book_description = book_metadata['metadatas'][0].get('description', 'No description available')
    
    # Query for relevant content based on the last user message
    last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    results = collection.query(
        query_texts=[last_user_message],
        where={"$and": [{"user_id": request.user_id}, {"book_id": request.book_id}]},
        n_results=5
    )

    system_prompt = f"""
    You are a helpful book expert. You answer questions about a specific book. 
    Use the knowledge I'm providing you. Use your internal knowledge only if you're  sure it's about this book and make it clear that you are not using info from the book and don't make things up. 
    If you don't know the answer, just say something like: I don't know.
    --------------------
    Book title:
    {book_title}
    Book Description:
    {book_description}
    --------------------
    Relevant Content:
    {str(results['documents'])}
    """
    
    messages = [{"role": "system", "content": system_prompt}] + [m.dict() for m in request.messages]
    
    async def event_generator():
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield f"data: {chunk.choices[0].delta.content}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Serve static files from the 'covers' directory
covers_dir = os.path.join(os.path.dirname(__file__), "covers")
os.makedirs(covers_dir, exist_ok=True)
app.mount("/covers", StaticFiles(directory=covers_dir), name="covers")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

