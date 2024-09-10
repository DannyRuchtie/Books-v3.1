console.log('app.js loaded');

let currentUserId = '1'; // Replace with actual user ID or method to get it
let currentBookId = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM fully loaded');
    fetchBooks(currentUserId);

    // Add event listeners for chat interface
    document.getElementById('closeChatBtn').addEventListener('click', closeChatInterface);
    document.getElementById('sendMessageBtn').addEventListener('click', sendMessage);
    document.getElementById('userMessage').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});

async function fetchBooks(userId) {
    console.log('Fetching books for user:', userId);
    try {
        const response = await fetch(`/books/${userId}?t=${Date.now()}`); // Cache busting
        if (!response.ok) {
            throw new Error('Failed to fetch books');
        }
        const books = await response.json();
        console.log('Fetched books:', books);
        displayBooks(books);
    } catch (error) {
        console.error('Error fetching books:', error);
        document.getElementById('bookGrid').innerHTML = '<p>Error loading books. Please try again later.</p>';
    }
}

function displayBooks(books) {
    console.log('Displaying books:', books);
    const bookGrid = document.getElementById('bookGrid');
    console.log('Book grid element:', bookGrid);
    bookGrid.innerHTML = ''; // Clear existing content

    if (books.length === 0) {
        bookGrid.innerHTML = '<p>No books found for this user.</p>';
        return;
    }

    books.forEach(book => {
        const bookElement = createBookElement(book);
        bookGrid.appendChild(bookElement);
        console.log('Added book to grid:', book.title);
    });
}

function createBookElement(book) {
    const bookItem = document.createElement('div');
    bookItem.className = 'book-item';
    bookItem.addEventListener('click', () => openChatInterface(book));

    const coverImg = document.createElement('img');
    coverImg.src = book.cover_url;
    coverImg.alt = `${book.title} cover`;
    coverImg.className = 'book-cover';

    const titleElement = document.createElement('div');
    titleElement.textContent = book.title;
    titleElement.className = 'book-title';

    const authorElement = document.createElement('div');
    authorElement.textContent = book.creator;
    authorElement.className = 'book-author';

    bookItem.appendChild(coverImg);
    bookItem.appendChild(titleElement);
    bookItem.appendChild(authorElement);

    return bookItem;
}

function openChatInterface(book) {
    currentBookId = book.id;
    document.getElementById('chatBookTitle').textContent = book.title;
    document.getElementById('chatInterface').classList.remove('hidden');
    document.getElementById('chatMessages').innerHTML = '';
    document.getElementById('userMessage').value = '';
}

function closeChatInterface() {
    document.getElementById('chatInterface').classList.add('hidden');
    currentBookId = null;
}

async function sendMessage() {
    const userMessageInput = document.getElementById('userMessage');
    const userMessage = userMessageInput.value.trim();
    if (userMessage === '') return;

    addMessageToChat('user', userMessage);
    userMessageInput.value = '';

    const chatMessages = document.getElementById('chatMessages');
    const assistantMessage = document.createElement('div');
    assistantMessage.className = 'message assistant';
    chatMessages.appendChild(assistantMessage);

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: currentUserId,
                book_id: currentBookId,
                messages: [{ role: 'user', content: userMessage }]
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to send message');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantResponse = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const content = line.slice(6);
                    if (content === '[DONE]') {
                        break;
                    }
                    assistantResponse += content;
                    assistantMessage.textContent = assistantResponse;
                }
            }
        }
    } catch (error) {
        console.error('Error sending message:', error);
        assistantMessage.textContent = 'Error: Failed to get response';
    }

    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addMessageToChat(role, content) {
    const chatMessages = document.getElementById('chatMessages');
    const messageElement = document.createElement('div');
    messageElement.className = `message ${role}`;
    messageElement.textContent = content;
    chatMessages.appendChild(messageElement);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function uploadBook(bookData) {
    // Your upload logic here
    const response = await fetch('/upload', {
        method: 'POST',
        body: JSON.stringify(bookData),
        headers: {
            'Content-Type': 'application/json',
        },
    });

    if (response.ok) {
        // Refresh the book list after successful upload
        fetchBooks(currentUserId);
    } else {
        console.error('Failed to upload book');
    }
}

