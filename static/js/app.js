console.log('app.js loaded');

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM fully loaded');
    const userId = '1'; // Replace with actual user ID or method to get it
    fetchBooks(userId);
});

async function fetchBooks(userId) {
    console.log('Fetching books for user:', userId);
    try {
        const response = await fetch(`/books/${userId}`);
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

    const coverImg = document.createElement('img');
    coverImg.src = book.cover_url;
    coverImg.alt = `${book.title} cover`;
    coverImg.className = 'book-cover';

    const titleElement = document.createElement('div');
    titleElement.textContent = book.title;
    titleElement.className = 'book-title';

    const authorElement = document.createElement('div');
    authorElement.textContent = book.creator; // Changed from book.author to book.creator
    authorElement.className = 'book-author';

    bookItem.appendChild(coverImg);
    bookItem.appendChild(titleElement);
    bookItem.appendChild(authorElement);

    return bookItem;
}

