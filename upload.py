from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import shutil
import logging
import zipfile
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import chromadb
from PIL import Image
import io
from langchain_text_splitters import RecursiveCharacterTextSplitter
import html  # Add this import at the top of your file

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def extract_cover_image(zip_ref, opf_content, book_id):
    try:
        root = ET.fromstring(opf_content)
        ns = {'opf': 'http://www.idpf.org/2007/opf'}

        cover_id = root.find(".//opf:meta[@name='cover']", ns)
        if cover_id is not None:
            cover_id = cover_id.get('content')
            cover_item = root.find(f".//opf:item[@id='{cover_id}']", ns)
        else:
            cover_item = root.find(".//opf:item[contains(@id, 'cover') or contains(@href, 'cover')]", ns)

        if cover_item is not None:
            cover_path = cover_item.get('href')
            logger.info(f"Found cover path: {cover_path}")
            
            # Try to find the cover file in the EPUB
            try:
                with zip_ref.open(cover_path) as cover_file:
                    cover_data = cover_file.read()
            except KeyError:
                # If the direct path fails, try to find the file in the EPUB
                for file_name in zip_ref.namelist():
                    if file_name.endswith(cover_path.split('/')[-1]):
                        with zip_ref.open(file_name) as cover_file:
                            cover_data = cover_file.read()
                        break
                else:
                    raise Exception("Cover file not found in EPUB")

            cover_filename = f"{book_id}.jpg"
            cover_path = os.path.join("covers", cover_filename)
            os.makedirs(os.path.dirname(cover_path), exist_ok=True)

            with Image.open(io.BytesIO(cover_data)) as img:
                img = img.convert('RGB')
                img.save(cover_path, 'JPEG')

            logger.info(f"Extracted cover image: {cover_path}")
            return f"/covers/{cover_filename}"
        else:
            logger.warning("No cover image found in EPUB")
            return None
    except Exception as e:
        logger.error(f"Error extracting cover image: {str(e)}")
        return None

def process_book(temp_file_path, user_id, book_id, filename):
    try:
        logger.info(f"Starting to process book: {filename}")
        
        with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
            opf_file = next((f for f in zip_ref.namelist() if f.endswith('.opf')), None)
            if not opf_file:
                raise ValueError("No OPF file found in the EPUB")
            
            logger.info(f"Found OPF file: {opf_file}")
            with zip_ref.open(opf_file) as opf:
                opf_content = opf.read()
                content_root = ET.fromstring(opf_content)
            
            ns = {'dc': 'http://purl.org/dc/elements/1.1/', 'opf': 'http://www.idpf.org/2007/opf'}
            title = content_root.find('.//dc:title', ns).text if content_root.find('.//dc:title', ns) is not None else "Unknown Title"
            creator = content_root.find('.//dc:creator', ns).text if content_root.find('.//dc:creator', ns) is not None else "Unknown Author"
            identifier = content_root.find('.//dc:identifier', ns).text if content_root.find('.//dc:identifier', ns) is not None else "Unknown Identifier"
            description = content_root.find('.//dc:description', ns).text if content_root.find('.//dc:description', ns) is not None else "No description available"
            
            logger.info(f"Extracted metadata - Title: {title}, Creator: {creator}, Identifier: {identifier}")
            
            cover_url = extract_cover_image(zip_ref, opf_content, book_id)
            if not cover_url:
                cover_url = "/covers/default.jpg"
            
            book_content = ""
            for item in content_root.findall('.//opf:item[@media-type="application/xhtml+xml"]', ns):
                html_path = item.get('href')
                try:
                    html_content = zip_ref.read(os.path.join(os.path.dirname(opf_file), html_path)).decode('utf-8')
                    soup = BeautifulSoup(html_content, 'html.parser')
                    book_content += soup.get_text() + "\n"
                except Exception as e:
                    logger.error(f"Error processing file {html_path}: {str(e)}")
        
        logger.info(f"Extracted book content. Length: {len(book_content)} characters")
        logger.info("Starting chunking process...")
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        chunks = text_splitter.split_text(book_content)
        
        logger.info(f"Chunking complete. Total chunks: {len(chunks)}")
        
        logger.info("Adding book metadata and chunks to ChromaDB...")
        
        collection.add(
            documents=[book_content[:1000]],  # This might need to include the full description
            metadatas=[{
                "type": "book_metadata",
                "user_id": user_id,
                "book_id": book_id,
                "title": title,
                "creator": creator,
                "identifier": identifier,
                "cover_url": cover_url,
                "description": description  # Make sure this line is present
            }],
            ids=[book_id]
        )
        
        # Add chunks in batches
        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i+batch_size]
            batch_ids = [f"{book_id}_chunk_{j}" for j in range(i, i+len(batch_chunks))]
            batch_metadatas = [{
                "type": "book_chunk",
                "user_id": user_id,
                "book_id": book_id,
                "title": title,
                "creator": creator,
                "chunk_index": j,
                "total_chunks": len(chunks)
            } for j in range(i, i+len(batch_chunks))]
            
            collection.add(
                documents=batch_chunks,
                metadatas=batch_metadatas,
                ids=batch_ids
            )
            logger.info(f"Added batch of {len(batch_chunks)} chunks to ChromaDB")
        
        logger.info(f"Added book metadata and {len(chunks)} chunks to ChromaDB")
        return {"status": "success", "message": f"Book '{title}' processed successfully", "chunks_added": len(chunks)}

    except Exception as e:
        logger.error(f"Error processing book: {str(e)}")
        raise
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Removed temporary file: {temp_file_path}")

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

        logger.info(f"File saved temporarily at: {temp_file_path}")

        book_id = str(uuid.uuid4())
        
        # Process the book immediately
        result = process_book(temp_file_path, user_id, book_id, file.filename)
        
        return {"message": "File uploaded and processed successfully", "book_id": book_id, "result": result}
    except Exception as e:
        logger.error(f"Error processing upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing upload: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)