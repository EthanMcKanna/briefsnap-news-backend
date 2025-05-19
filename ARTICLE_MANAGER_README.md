# Briefsnap Article Manager

A web interface to manage articles in the Briefsnap News database, including editing content and images.

## Features

- Browse all published articles with image thumbnails
- Filter articles by topic category (TOP_NEWS, BUSINESS, TECHNOLOGY, etc.)
- Search for articles by title within all topics or a specific topic
- View and edit article details:
  - Update article images with URL preview
  - Edit article descriptions
  - Edit full article text
- Delete articles from the database
- Simple and intuitive user interface

## Setup

1. Ensure you have all the required dependencies installed:

```bash
pip install -r requirements.txt
```

2. Make sure your Firebase credentials file (`firebase-credentials.json`) is in the correct location as specified in your configuration.

## Running the Application

Run the application using the provided script:

```bash
./run_article_manager.py
```

Or with Python directly:

```bash
python run_article_manager.py
```

The application will be available at http://localhost:3000

## Usage

1. **Browse Articles**: The home page displays all articles with their current images.
2. **Filter by Topic**: Click on any topic tab at the top of the page to filter articles by that topic.
3. **Search**: Use the search box in the navigation bar to find specific articles by title.
   - When filtering by topic, searches will be limited to that topic.
   - Click "Clear search" to return to the full article list for the current topic.
4. **Edit Articles**: Click the "Edit Article" button on any article card to go to the detail page.
5. **On the Article Detail Page**:
   - **Edit Image**: Click the "Edit" button next to "Current Image" to expand the image editing form
      - Enter a new image URL
      - Click "Preview Image" to verify the image loads correctly
      - Click "Update Image" to save the changes
   - **Edit Description**: Click the "Edit" button next to "Description" to expand the description editing form
      - Modify the text as needed
      - Click "Update Description" to save the changes
   - **Edit Full Article**: Click the "Edit" button next to "Full Article" to expand the full article editing form
      - Modify the content as needed
      - Click "Update Full Article" to save the changes
   - **Delete Article**: In the "Danger Zone" section:
      - Type "DELETE" (all caps) in the confirmation field
      - Click "Delete Article" to permanently remove the article from the database

## Notes

- The application accesses your existing Firestore database
- All updates are logged and timestamped
- Deletions are permanent and cannot be undone
- For security reasons, this tool should only be used in a trusted environment 