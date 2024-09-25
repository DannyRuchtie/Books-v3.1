console.log('app.js loaded');

let currentUserId = null;
let accessToken = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM fully loaded');

    // Add event listeners for chat interface
    document.getElementById('chatBackdrop').addEventListener('click', closeChatInterface);
    document.getElementById('sendMessageBtn').addEventListener('click', sendMessage);
    document.getElementById('userMessage').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Add drag-and-drop functionality to the entire document
    document.body.addEventListener('dragover', (e) => {
        e.preventDefault(); // Prevent default behavior (Prevent file from being opened)
        document.body.classList.add('hover');
    });

    document.body.addEventListener('dragleave', () => {
        document.body.classList.remove('hover');
    });

    document.body.addEventListener('drop', (e) => {
        e.preventDefault();
        document.body.classList.remove('hover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadFile(files[0]); // Upload the first file
        }
    });

    // Add login form submission handler
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        await login(username, password);
    });

    // Check for stored token on page load
    const storedToken = localStorage.getItem('accessToken');
    if (storedToken) {
        accessToken = storedToken;
        // Verify token and fetch user info
        fetch('/users/me', {
            headers: {
                'Authorization': `Bearer ${accessToken}`,
            },
        })
        .then(response => response.json())
        .then(userData => {
            currentUserId = userData.username;
            updateUIForLoggedInUser(userData);
            fetchBooks();
        })
        .catch(error => {
            console.error('Error verifying stored token:', error);
            // Clear invalid token
            localStorage.removeItem('accessToken');
        });
    }
});

async function login(username, password) {
    try {
        const response = await fetch('/token', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
        });

        if (!response.ok) {
            throw new Error('Login failed');
        }

        const data = await response.json();
        accessToken = data.access_token;
        localStorage.setItem('accessToken', accessToken);

        // Fetch user info
        const userResponse = await fetch('/users/me', {
            headers: {
                'Authorization': `Bearer ${accessToken}`,
            },
        });

        if (!userResponse.ok) {
            throw new Error('Failed to fetch user info');
        }

        const userData = await userResponse.json();
        currentUserId = userData.username;

        // Update UI to show logged-in state
        updateUIForLoggedInUser(userData);

        // Fetch books for the logged-in user
        fetchBooks();
    } catch (error) {
        console.error('Login error:', error);
        // Show error message to user
    }
}

function updateUIForLoggedInUser(userData) {
    document.getElementById('loginSection').style.display = 'none';
    document.getElementById('bookSection').style.display = 'block';
    // You can add more UI updates here, like showing the user's name
}

async function uploadFile(file) {
    // Check if the file is an EPUB based on the extension
    const isEpub = file.type === 'application/epub+zip' || 
                   file.type === 'application/zip' || 
                   file.name.endsWith('.epub');

    if (!isEpub) {
        alert('Please upload a valid EPUB file.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`/upload`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
            },
            body: formData,
        });

        if (!response.ok) {
            throw new Error('Failed to upload file');
        }

        const result = await response.json();
        console.log('Upload successful:', result);
        
        // Refresh the book list after upload
        fetchBooks(); // Ensure this is called after a successful upload
    } catch (error) {
        console.error('Error uploading file:', error);
    }
}

async function fetchBooks() {
    console.log('Fetching books for user:', currentUserId);
    try {
        // Add a cache-busting parameter to the URL
        const response = await fetch(`/books?t=${Date.now()}`, {
            headers: {
                'Authorization': `Bearer ${accessToken}`,
            },
        }); // Cache busting
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
    console.log('Book object:', book);  // Add this line to log the book object

    const bookItem = document.createElement('div');
    bookItem.className = 'book-item';
    
    // Try different ways to access the book_id
    if (book.data && book.data.book_id) {
        bookItem.dataset.bookId = book.data.book_id;
    } else if (book.id) {
        bookItem.dataset.bookId = book.id;
    } else {
        console.warn('Could not find book_id for:', book.title);
    }
    
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

    console.log('Created book element:', bookItem.outerHTML);  // Add this line to log the created element

    return bookItem;
}

function openChatInterface(book) {
    currentBookId = book.id;
    document.getElementById('chatBookTitle').textContent = book.title;
    document.getElementById('chatBookAuthor').textContent = book.creator; // Set the author here
    document.getElementById('chatCoverImage').src = book.cover_url; // Set the cover image here
    document.getElementById('chatBackdrop').classList.remove('hidden');
    document.getElementById('chatInterface').classList.remove('hidden');
    document.getElementById('chatMessages').innerHTML = '';
    document.getElementById('userMessage').value = '';

    // Make the chat interface draggable
    makeDraggable(document.getElementById('chatHeader'), document.getElementById('chatInterface'));
}

function makeDraggable(header, chatInterface) {
    let isDragging = false;
    let initialMouseX, initialMouseY;
    let initialTransformX = 0; // Initial transform X position
    let initialTransformY = 0; // Initial transform Y position

    header.addEventListener('mousedown', (e) => {
        isDragging = true;

        // Store the initial mouse position
        initialMouseX = e.clientX;
        initialMouseY = e.clientY;

        // Get the current transform values
        const computedStyle = window.getComputedStyle(chatInterface);
        const matrix = new DOMMatrix(computedStyle.transform);
        initialTransformX = matrix.m41; // Current translateX
        initialTransformY = matrix.m42; // Current translateY

        document.body.style.cursor = 'grabbing'; // Change cursor to grabbing
    });

    document.addEventListener('mousemove', (e) => {
        if (isDragging) {
            // Calculate the difference in mouse position
            const deltaX = e.clientX - initialMouseX;
            const deltaY = e.clientY - initialMouseY;

            // Update the transform property to move the chat interface
            chatInterface.style.transform = `translate(${initialTransformX + deltaX}px, ${initialTransformY + deltaY}px)`;
        }
    });

    document.addEventListener('mouseup', () => {
        isDragging = false;
        document.body.style.cursor = 'default'; // Reset cursor
    });

    // Prevent text selection while dragging
    header.addEventListener('dragstart', (e) => e.preventDefault());
}

function closeChatInterface() {
    document.getElementById('chatInterface').classList.add('hidden');
    document.getElementById('chatBackdrop').classList.add('hidden');
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
                'Authorization': `Bearer ${accessToken}`,
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

