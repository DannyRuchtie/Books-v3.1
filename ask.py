import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import chromadb
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize the OpenAI client
client = OpenAI()

# setting the environment

CHROMA_PATH = r"chroma_db"

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = chroma_client.get_or_create_collection(name="books")


print("Welcome to the book assistant. Type 'exit' to quit at any time.")

while True:
    user_query = input("\nQ:")
    
    if user_query.lower() == 'exit':
        break
    
    # Move the collection query inside the loop
    results = collection.query(
        query_texts=[user_query],
        n_results=10  
    )

    # Print the 10 query results
    print("\nQuery Results:")
    for i, doc in enumerate(results['documents'][0], 1):
        print(f"{i}. {doc[:100]}...")  # Print first 100 characters of each result

    # Update the system prompt with new results
    system_prompt = """
    You are a helpful assistant. You answer questions about books. 
    But you only answer based on knowledge I'm providing you. Only use your internal knowledge if you are absolutly sure if its about this book and don't make things up. 
    If you don't know the answer, just say something like: I don't know.
    --------------------
    The data:
    """+str(results['documents'])+"""
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )
    
    assistant_response = response.choices[0].message.content
    print("\nAssistant:", assistant_response)

print("Thank you for using the book assistant. Goodbye!")