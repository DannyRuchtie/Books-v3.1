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
from upload import process_and_upload_book
import asyncio

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
        # Ensure id is a string
        id = id_list[0] if isinstance(id_list, list) else id_list
        # Ensure metadata is a dictionary
        metadata = metadata_list[0] if isinstance(metadata_list, list) else metadata_list
        
        books.append(Book(
            id=id,
            identifier=metadata.get('identifier', 'Unknown'),
            title=metadata.get('title', 'Unknown Title'),
            cover_url=metadata.get('cover_url', 'No cover')
        ))
    
    return books

@app.post("/upload/{user_id}")
async def upload_book(user_id: str, file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.epub'):
        raise HTTPException(status_code=400, detail="File must be an EPUB")

    try:
        # Create a temporary file to store the uploaded EPUB
        with tempfile.NamedTemporaryFile(delete=False, suffix='.epub') as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_file_path = temp_file.name

        book_metadata, cover_path, content = extract_book_info(temp_file_path)
        
        cleaned_metadata = clean_metadata(book_metadata)
        cleaned_metadata["type"] = "book_metadata"
        cleaned_metadata["user_id"] = user_id

        if cover_path:
            cover_filename = os.path.basename(cover_path)
            cleaned_metadata["cover_url"] = f"/covers/{cover_filename}"
        else:
            cleaned_metadata["cover_url"] = "No cover"

        book_id = str(uuid.uuid4())
        metadata_id = f"metadata_{user_id}_{book_id}"

        collection.upsert(
            documents=[str(cleaned_metadata)],
            metadatas=[cleaned_metadata],
            ids=[metadata_id]
        )

        raw_text = "\n".join([BeautifulSoup(doc, 'html.parser').get_text() for doc in content])
        cleaned_text = clean_text(raw_text)

        chunk_size = 1000
        chunk_overlap = 10
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = splitter.split_text(cleaned_text)

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
            collection.upsert(
                documents=[chunk],
                metadatas=[chunk_metadata],
                ids=[chunk_id]
            )

        # Clean up the temporary file
        os.unlink(temp_file_path)

        return {"message": "Book uploaded and processed successfully", "book_id": book_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        model="gpt-4-1106-preview",
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
            model="gpt-4-1106-preview",
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
