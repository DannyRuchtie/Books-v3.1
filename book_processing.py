import ebooklib
from ebooklib import epub
import os
import logging
from bs4 import BeautifulSoup
from chromadb import PersistentClient
from langchain_text_splitters import RecursiveCharacterTextSplitter
from PIL import Image
import io
import shutil
import zipfile
import tempfile

# Set up logging to write to a file
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=os.path.join(log_dir, 'book_processing.log'),
    filemode='a'
)
logger = logging.getLogger(__name__)

# Add a stream handler to also print logs to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ChromaDB setup
CHROMA_PATH = os.path.join("chroma_db")
chroma_client = PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="books")

def process_book(temp_file_path, user_id, book_id, filename):
    try:
        logger.info(f"Starting to process book: {filename}")
        
        # Check if the file is a ZIP archive
        if zipfile.is_zipfile(temp_file_path):
            logger.info("File is a ZIP archive. Extracting...")
            with tempfile.TemporaryDirectory() as tmpdirname:
                with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdirname)
                
                # Look for .epub file in the extracted contents
                epub_files = [f for f in os.listdir(tmpdirname) if f.endswith('.epub')]
                if not epub_files:
                    raise ValueError("No .epub file found in the ZIP archive")
                
                epub_path = os.path.join(tmpdirname, epub_files[0])
                book = epub.read_epub(epub_path)
        else:
            # If it's not a ZIP file, assume it's an EPUB and process directly
            book = epub.read_epub(temp_file_path)
        
        # Extract book metadata
        logger.info("Extracting book metadata...")
        title = book.get_metadata('DC', 'title')[0][0]
        creator = book.get_metadata('DC', 'creator')[0][0] if book.get_metadata('DC', 'creator') else "Unknown"
        identifier = book.get_metadata('DC', 'identifier')[0][0] if book.get_metadata('DC', 'identifier') else "Unknown"
        description = book.get_metadata('DC', 'description')[0][0] if book.get_metadata('DC', 'description') else "No description available"
        
        logger.info(f"Extracted metadata - Title: {title}, Creator: {creator}, Identifier: {identifier}")

        # Generate cover image
        logger.info("Generating cover image...")
        cover_url = generate_cover_image(book, book_id)
        logger.info(f"Cover image generated: {cover_url}")
        
        # Add book metadata to ChromaDB
        logger.info("Adding book metadata to ChromaDB...")
        collection.add(
            ids=[book_id],
            metadatas=[{
                "user_id": user_id,
                "type": "book_metadata",
                "title": title,
                "creator": creator,
                "identifier": identifier,
                "description": description,
                "cover_url": cover_url,
                "filename": filename
            }],
            documents=[f"Book: {title} by {creator}. {description}"]
        )
        
        logger.info("Added book metadata to ChromaDB")

        # Extract and chunk content
        logger.info("Extracting content from EPUB...")
        content = extract_epub_content(book)
        logger.info("Chunking content...")
        chunks = chunk_content(content)
        
        logger.info(f"Extracted and chunked content. Total chunks: {len(chunks)}")

        # Add chunks to ChromaDB
        logger.info("Adding chunks to ChromaDB...")
        for i, chunk in enumerate(chunks):
            collection.add(
                ids=[f"{book_id}_chunk_{i}"],
                metadatas=[{
                    "user_id": user_id,
                    "book_id": book_id,
                    "type": "book_content",
                    "chunk_index": i
                }],
                documents=[chunk]
            )
            if i % 100 == 0:  # Log progress every 100 chunks
                logger.info(f"Added {i+1} chunks to ChromaDB")
        
        logger.info(f"Added all {len(chunks)} chunks to ChromaDB")
        
        logger.info(f"Book processed successfully: {title}")
    except Exception as e:
        logger.error(f"Error processing book: {str(e)}")
        raise
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Removed temporary file: {temp_file_path}")

def generate_cover_image(book, book_id):
    logger.info("Generating cover image")
    covers_dir = os.path.join(os.path.dirname(__file__), "covers")
    os.makedirs(covers_dir, exist_ok=True)
    cover_path = os.path.join(covers_dir, f"{book_id}.jpg")
    
    # Debug: Print information about all items in the EPUB
    for item in book.get_items():
        logger.debug(f"Item: {item.get_name()}, Type: {item.get_type()}, Media Type: {getattr(item, 'media_type', 'N/A')}")
    
    # Try to find the cover image in the EPUB
    for item in book.get_items():
        if hasattr(item, 'media_type') and item.media_type and item.media_type.startswith('image/'):
            if 'cover' in item.get_name().lower():
                with open(cover_path, 'wb') as f:
                    f.write(item.content)
                logger.info(f"Cover image extracted from EPUB: {cover_path}")
                return f"/covers/{book_id}.jpg"
    
    # If no cover found, use a default image
    default_cover_path = os.path.join(os.path.dirname(__file__), "static", "default_cover.jpg")
    if os.path.exists(default_cover_path):
        shutil.copy(default_cover_path, cover_path)
        logger.info(f"Using default cover image: {cover_path}")
    else:
        # If default cover doesn't exist, generate a simple placeholder
        Image.new('RGB', (100, 150), color = (73, 109, 137)).save(cover_path)
        logger.info(f"Generated placeholder cover image: {cover_path}")
    
    return f"/covers/{book_id}.jpg"

def extract_epub_content(book):
    logger.info("Extracting content from EPUB")
    content = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT or (hasattr(item, 'media_type') and item.media_type in ['application/xhtml+xml', 'text/html']):
            try:
                if isinstance(item.get_content(), str):
                    text = item.get_content()
                else:
                    text = item.get_content().decode('utf-8', errors='ignore')
                soup = BeautifulSoup(text, 'html.parser')
                content.append(soup.get_text())
            except Exception as e:
                logger.warning(f"Error processing item {item.get_name()}: {str(e)}")
    
    if not content:
        logger.warning("No content extracted from EPUB. Trying alternative method.")
        for item in book.get_items():
            if isinstance(item, ebooklib.epub.EpubHtml):
                try:
                    soup = BeautifulSoup(item.content, 'html.parser')
                    content.append(soup.get_text())
                except Exception as e:
                    logger.warning(f"Error processing EpubHtml item: {str(e)}")
    
    return ' '.join(content)

def chunk_content(content):
    logger.info("Chunking content")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )
    return text_splitter.split_text(content)