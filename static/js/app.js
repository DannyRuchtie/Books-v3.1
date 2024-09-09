document.addEventListener('DOMContentLoaded', () => {
    const userId = '79c8d98e-b923-48f4-b2bd-0feeb4285419'; // Replace with actual user ID or method to get it
    fetchBooks(userId);
});

async function fetchBooks(userId) {
    try {
        const response = await fetch(`/books/${userId}`);
        if (!response.ok) {
            throw new Error('Failed to fetch books');
        }
        const books = await response.json();
        displayBooks(books);
    } catch (error) {
        console.error('Error fetching books:', error);
        document.getElementById('bookGrid').innerHTML = '<p>Error loading books. Please try again later.</p>';
    }
}

function displayBooks(books) {
    const bookGrid = document.getElementById('bookGrid');
    bookGrid.innerHTML = ''; // Clear existing content

    if (books.length === 0) {
        bookGrid.innerHTML = '<p>No books found for this user.</p>';
        return;
    }

    books.forEach(book => {
        const bookElement = createBookElement(book);
        bookGrid.appendChild(bookElement);
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
    authorElement.textContent = book.author;
    authorElement.className = 'book-author';

    bookItem.appendChild(coverImg);
    bookItem.appendChild(titleElement);
    bookItem.appendChild(authorElement);

    return bookItem;
}
