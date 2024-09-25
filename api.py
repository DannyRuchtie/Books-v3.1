print("Starting api.py")
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import chromadb
import os
from dotenv import load_dotenv
import logging
import openai
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import User as DBUser, get_db  # Make sure this import is correct

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
openai.api_key = os.getenv("OPENAI_API_KEY")

# Security configurations
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# User model
class User(BaseModel):
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None

class UserInDB(User):
    hashed_password: str

# Token model
class Token(BaseModel):
    access_token: str
    token_type: str

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_user(db: Session, username: str):
    print("Querying user:", username)
    user = db.query(DBUser).filter(DBUser.username == username).first()
    print("Query result:", user)
    return user

def authenticate_user(db: Session, username: str, password: str):
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire, "sub": str(data["user_id"])})  # Use user_id instead of username
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"user_id": user.id},  # Use user.id instead of user.username
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

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

@app.get("/books", response_model=List[Book])
async def list_books(current_user: User = Depends(get_current_active_user)):
    user_id = current_user.username
    logger.info(f"Fetching books for user: {user_id}")
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
async def delete_book(book_id: str, current_user: User = Depends(get_current_active_user)):
    user_id = current_user.username
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
async def chat(request: ChatRequest, current_user: User = Depends(get_current_active_user)):
    user_id = current_user.username
    # Retrieve book metadata
    book_metadata = collection.get(
        ids=[request.book_id],
        where={"user_id": user_id}
    )
    
    if not book_metadata['metadatas']:
        raise HTTPException(status_code=404, detail="Book not found")
    
    book_title = book_metadata['metadatas'][0].get('title', 'Unknown Title')
    book_description = book_metadata['metadatas'][0].get('description', 'No description available')
    
    # Query for relevant content based on the last user message
    last_user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    results = collection.query(
        query_texts=[last_user_message],
        where={"$and": [{"user_id": user_id}, {"book_id": request.book_id}]},
        n_results=10
    )

    system_prompt = f"""

You are an expert on the book titled "{book_title}". Answer the user's questions using only the information provided below. Do not use any outside knowledge. If the answer is not in the provided content, respond with "That information is not available in the book."

**Book Description:**
{book_description}

**Relevant Content:**
{str(results['documents'])}

**Example Question and Answer:**

- **Question:** "Where did Tony Fadell work before Apple?"
- **Answer:** "Tony Fadell worked at General Magic before joining Apple."

Use this format to answer the user's questions.
    """
    
    messages = [{"role": "system", "content": system_prompt}] + [m.dict() for m in request.messages]
    
    async def event_generator():
        # Use the asynchronous version of the API call
        stream = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",  # or another valid model ID
            messages=messages,
            stream=True,
            temperature=0.2
        )
        async for chunk in stream:  # This should work now
            if chunk.get("choices") and chunk["choices"][0].get("delta"):
                content = chunk["choices"][0]["delta"].get("content")
                if content is not None:
                    yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Serve static files from the 'covers' directory
covers_dir = os.path.join(os.path.dirname(__file__), "covers")
os.makedirs(covers_dir, exist_ok=True)
app.mount("/covers", StaticFiles(directory=covers_dir), name="covers")

# Mount the ico directory
app.mount("/ico", StaticFiles(directory="ico"), name="ico")

class UserCreate(BaseModel):
    username: str
    email: str
    full_name: str
    password: str

@app.post("/register", response_model=User)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = get_user(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = pwd_context.hash(user.password)
    db_user = User(username=user.username, email=user.email, full_name=user.full_name, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

print("Imported User model:", DBUser)
print("User.__module__:", DBUser.__module__)

