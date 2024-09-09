import os
import zipfile
import tempfile
import logging
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import chromadb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from PIL import Image
import io

logger = logging.getLogger(__name__)

def get_chroma_client():
    CHROMA_PATH = os.path.join("chroma_db")
    return chromadb.PersistentClient(path=CHROMA_PATH)

def extract_cover_image(zip_ref, opf_content, book_id):
    try:
        root = ET.fromstring(opf_content)
        ns = {'opf': 'http://www.idpf.org/2007/opf'}

        # Find the cover image item
        cover_id = root.find(".//opf:meta[@name='cover']", ns)
        if cover_id is not None:
            cover_id = cover_id.get('content')
            cover_item = root.find(f".//opf:item[@id='{cover_id}']", ns)
        else:
            cover_item = root.find(".//opf:item[contains(@id, 'cover') or contains(@href, 'cover')]", ns)

        if cover_item is not None:
            cover_path = cover_item.get('href')
            with zip_ref.open(cover_path) as cover_file:
                cover_data = cover_file.read()

            # Save the cover image
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
            # Find the OPF file
            opf_file = next((f for f in zip_ref.namelist() if f.endswith('.opf')), None)
            if not opf_file:
                raise ValueError("No OPF file found in the EPUB")
            
            # Read the OPF file
            with zip_ref.open(opf_file) as opf:
                opf_content = opf.read()
                content_root = ET.fromstring(opf_content)
            
            # Extract metadata
            ns = {'dc': 'http://purl.org/dc/elements/1.1/', 'opf': 'http://www.idpf.org/2007/opf'}
            title = content_root.find('.//dc:title', ns).text if content_root.find('.//dc:title', ns) is not None else "Unknown Title"
            creator = content_root.find('.//dc:creator', ns).text if content_root.find('.//dc:creator', ns) is not None else "Unknown Author"
            identifier = content_root.find('.//dc:identifier', ns).text if content_root.find('.//dc:identifier', ns) is not None else "Unknown Identifier"
            description = content_root.find('.//dc:description', ns).text if content_root.find('.//dc:description', ns) is not None else "No description available"
            
            logger.info(f"Extracted metadata - Title: {title}, Creator: {creator}, Identifier: {identifier}")
            
            # Extract cover image
            cover_url = extract_cover_image(zip_ref, opf_content, book_id)
            if not cover_url:
                cover_url = "/covers/default.jpg"  # Provide a default cover image
            
            # Extract content
            book_content = ""
            for item in content_root.findall('.//opf:item[@media-type="application/xhtml+xml"]', ns):
                html_path = item.get('href')
                try:
                    html_content = zip_ref.read(os.path.join(os.path.dirname(opf_file), html_path)).decode('utf-8')
                    soup = BeautifulSoup(html_content, 'html.parser')
                    book_content += soup.get_text() + "\n"
                except Exception as e:
                    logger.error(f"Error processing file {html_path}: {str(e)}")
        
        logger.info("Content extracted, starting chunking process...")
        
        # Chunk the content
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        chunks = text_splitter.split_text(book_content)
        
        logger.info(f"Chunking complete. Total chunks: {len(chunks)}")
        
        # Add book metadata and chunks to ChromaDB
        logger.info("Adding book metadata and chunks to ChromaDB...")
        chroma_client = get_chroma_client()
        collection = chroma_client.get_or_create_collection(name="books")
        
        # Add book metadata
        collection.add(
            documents=[book_content[:1000]],  # Adding first 1000 characters as a summary
            metadatas=[{
                "type": "book_metadata",
                "user_id": user_id,
                "book_id": book_id,
                "title": title,
                "creator": creator,
                "identifier": identifier,
                "cover_url": cover_url,
                "description": description
            }],
            ids=[book_id]
        )
        
        # Add book chunks
        for i, chunk in enumerate(chunks):
            chunk_id = f"{book_id}_chunk_{i}"
            collection.add(
                documents=[chunk],
                metadatas=[{
                    "type": "book_chunk",
                    "user_id": user_id,
                    "book_id": book_id,
                    "title": title,
                    "creator": creator,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }],
                ids=[chunk_id]
            )
        
        logger.info(f"Added book metadata and {len(chunks)} chunks to ChromaDB")

        return {"status": "success", "message": f"Book '{title}' processed successfully", "chunks_added": len(chunks)}

    except Exception as e:
        logger.error(f"Error processing book: {str(e)}")
        raise
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Removed temporary file: {temp_file_path}")