# Briefsnap Article Manager

A web interface to manage articles in the Briefsnap News database, including editing content and images with Cloudflare R2 integration.

## Features

- Browse all published articles with image thumbnails
- Filter articles by topic category (TOP_NEWS, BUSINESS, TECHNOLOGY, etc.)
- Search for articles by title within all topics or a specific topic
- View and edit article details:
  - Update article images with URL preview and automatic R2 upload
  - Upload existing images to Cloudflare R2 for better performance
  - Edit article descriptions
  - Edit full article text
- Delete articles from the database
- Cloudflare R2 integration for optimized image hosting
- Simple and intuitive user interface

## Setup

1. Ensure you have all the required dependencies installed:

```bash
pip install -r requirements.txt
```

2. Make sure your Firebase credentials file (`firebase-credentials.json`) is in the correct location as specified in your configuration.

3. **Configure Cloudflare R2 (Optional but Recommended)**:
   
   Set the following environment variables for R2 integration:
   ```bash
   export R2_ACCOUNT_ID="your-r2-account-id"
   export R2_ACCESS_KEY_ID="your-r2-access-key"
   export R2_SECRET_ACCESS_KEY="your-r2-secret-key"
   ```
   
   If these are not set, the application will still work but images will use their original URLs instead of being uploaded to R2.

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
      - Check "Upload image to Cloudflare R2" (recommended) to automatically upload the image to R2
      - Click "Preview Image" to verify the image loads correctly
      - Click "Update Image" to save the changes
   - **Upload Current Image to R2**: If an image is using an external URL, click the "Upload to R2" button next to the edit button to migrate it to R2 hosting
   - **Edit Description**: Click the "Edit" button next to "Description" to expand the description editing form
      - Modify the text as needed
      - Click "Update Description" to save the changes
   - **Edit Full Article**: Click the "Edit" button next to "Full Article" to expand the full article editing form
      - Modify the content as needed
      - Click "Update Full Article" to save the changes
   - **Delete Article**: In the "Danger Zone" section:
      - Type "DELETE" (all caps) in the confirmation field
      - Click "Delete Article" to permanently remove the article from the database

## Cloudflare R2 Integration

The application now automatically uploads article images to Cloudflare R2 with comprehensive optimization. Benefits include:

- **Faster Loading**: Images served from Cloudflare's global CDN with 70% smaller file sizes
- **Better Reliability**: Eliminates broken image links from external sources
- **Automatic Optimization**: WebP conversion, resolution capping (1200x800), and quality optimization
- **Consistent Naming**: Images are renamed with timestamps and article titles
- **Automatic Processing**: New articles automatically upload and optimize images to R2
- **Advanced Caching**: 2-year cache headers for WebP images, 1-year for others

### Image Status Indicators

- **Green "Hosted on R2" badge**: Image is hosted on Cloudflare R2
- **Yellow "External URL" badge**: Image is still using the original external URL
- **"Upload to R2" button**: Available for external images to migrate them to R2

## Notes

- The application accesses your existing Firestore database
- All updates are logged and timestamped
- Deletions are permanent and cannot be undone
- R2 credentials are optional but recommended for optimal performance
- Images uploaded to R2 are automatically optimized and cached for maximum performance
- Use `python check_image_optimization_status.py` to check optimization status
- Use `python migrate_images_to_r2.py` to optimize existing R2 images
- For security reasons, this tool should only be used in a trusted environment 