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

def extract_book_info(epub_path):
    book = epub.read_epub(epub_path)
    
    # Initialize metadata dictionary
    metadata = {}
    
    # Safely extract metadata
    try:
        for namespace in book.metadata:
            for name, values in book.metadata[namespace].items():
                if values:
                    metadata[name] = values[0][0]
    except Exception as e:
        print(f"Error extracting metadata: {str(e)}")
    
    # Extract cover
    cover_path = None
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        _, extension = os.path.splitext(item.file_name)
        cover_path = f'temp_cover{extension}'
        with open(cover_path, 'wb') as f:
            f.write(item.content)
        break
    
    # Extract content
    content = ""
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content += item.get_content().decode('utf-8')
    
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
    try:
        # Create a temporary file to store the uploaded content
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_file_path = temp_file.name

        # Determine the file type
        file_type = magic.from_file(temp_file_path, mime=True)
        print(f"Detected file type: {file_type}")  # Debug print

        if file_type == 'application/epub+zip':
            # It's an EPUB file
            epub_path = temp_file_path
        elif file_type == 'application/zip':
            # It's a ZIP file, try to extract EPUB
            with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                epub_files = [f for f in zip_ref.namelist() if f.lower().endswith('.epub')]
                if not epub_files:
                    raise HTTPException(status_code=400, detail="ZIP file does not contain an EPUB")
                epub_path = os.path.join(os.path.dirname(temp_file_path), epub_files[0])
                zip_ref.extract(epub_files[0], os.path.dirname(temp_file_path))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")

        # Process the EPUB file
        book_metadata, cover_path, content = extract_book_info(epub_path)
        
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

        print("Debug: Cleaned metadata:", cleaned_metadata)  # Debug print

        collection.upsert(
            documents=[str(cleaned_metadata)],
            metadatas=[cleaned_metadata],
            ids=[metadata_id]
        )

        raw_text = "\n".join([clean_html(doc) for doc in content])
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

        # Clean up temporary files
        if 'temp_file_path' in locals():
            os.unlink(temp_file_path)
        if 'epub_path' in locals() and epub_path != temp_file_path:
            os.unlink(epub_path)

        return {"message": "Book uploaded and processed successfully", "book_id": book_id}

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        print(f"Error type: {type(e)}")
        print(f"Error args: {e.args}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

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

@app.post("/upload_epub")
async def upload_epub(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        
        print(f"Uploaded file: {file.filename}, Size: {len(contents)} bytes")

        # Check if it's a valid ZIP file
        if not zipfile.is_zipfile(io.BytesIO(contents)):
            raise ValueError("The file is not a valid ZIP file")

        # Check if it has the correct EPUB structure
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            file_list = zf.namelist()
            
            # Check for mimetype file
            if 'mimetype' not in file_list:
                raise ValueError("Missing 'mimetype' file in EPUB")
            
            # Check mimetype content
            mimetype_content = zf.read('mimetype').decode('utf-8').strip()
            if mimetype_content != 'application/epub+zip':
                raise ValueError(f"Incorrect mimetype: {mimetype_content}")
            
            # Check for container.xml
            if 'META-INF/container.xml' not in file_list:
                raise ValueError("Missing 'META-INF/container.xml' in EPUB")

        # If we've made it here, it's likely a valid EPUB
        print("File appears to be a valid EPUB")

        # Your existing EPUB processing code here
        ...

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

    return {"message": "File processed successfully"}
