from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
from datetime import datetime, timezone

from newsaggregator.storage.firebase_storage import FirebaseStorage
from newsaggregator.config.settings import FIRESTORE_ARTICLES_COLLECTION, RSS_FEEDS
from newsaggregator.utils.r2_storage import r2_storage

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize Firebase connection
FirebaseStorage.initialize()

@app.route('/')
def index():
    """Display list of articles from Firestore"""
    # Get topic filter from query string
    topic_filter = request.args.get('topic', '')
    
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return render_template('index.html', articles=[], topics=get_topics(), active_topic='')
    
    # Get articles from Firestore, ordered by timestamp descending
    articles_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION)
    
    # Apply topic filter if specified
    if topic_filter:
        articles_ref = articles_ref.where('topic', '==', topic_filter)
    
    articles = articles_ref.order_by('timestamp', direction='DESCENDING').limit(50).stream()
    
    # Convert to list of dictionaries with IDs
    articles_list = []
    for article in articles:
        article_data = article.to_dict()
        article_data['doc_id'] = article.id
        articles_list.append(article_data)
    
    return render_template('index.html', articles=articles_list, topics=get_topics(), active_topic=topic_filter)

def get_topics():
    """Get list of available topics from RSS feeds and add additional ones"""
    # Start with topics from RSS_FEEDS
    topics = list(RSS_FEEDS.keys())
    
    # Add additional topics that might not be in RSS_FEEDS
    additional_topics = ['NATION', 'ENTERTAINMENT', 'SPORTS', 'SCIENCE', 'HEALTH']
    
    # Combine and remove duplicates
    all_topics = set(topics + additional_topics)
    
    return sorted(all_topics)

@app.route('/article/<doc_id>')
def view_article(doc_id):
    """View a single article with edit form"""
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return redirect(url_for('index'))
    
    # Get article from Firestore
    article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
    article = article_ref.get()
    
    if not article.exists:
        flash("Article not found", "error")
        return redirect(url_for('index'))
    
    article_data = article.to_dict()
    article_data['doc_id'] = article.id
    
    return render_template('article.html', article=article_data)

@app.route('/update_image/<doc_id>', methods=['POST'])
def update_image(doc_id):
    """Update article image URL"""
    img_url = request.form.get('img_url')
    upload_to_r2_flag = request.form.get('upload_to_r2') == 'on'
    
    if not img_url:
        flash("Image URL cannot be empty", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    try:
        # Get article data for title
        article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
        article = article_ref.get()
        if not article.exists:
            flash("Article not found", "error")
            return redirect(url_for('view_article', doc_id=doc_id))
        
        article_data = article.to_dict()
        article_title = article_data.get('title', '')
        
        final_url = img_url
        
        # If user wants to upload to R2, do that first
        if upload_to_r2_flag:
            try:
                r2_url = r2_storage.upload_image_from_url(img_url, article_title)
                if r2_url:
                    final_url = r2_url
                    flash(f"Image uploaded to R2 successfully: {r2_url}", "success")
                else:
                    flash("Failed to upload image to R2, using original URL", "warning")
            except Exception as e:
                flash(f"Error uploading to R2: {e}, using original URL", "warning")
        
        # Update the article document
        article_ref.update({
            'img_url': final_url,
            'updated_at': datetime.now(timezone.utc)
        })
        
        if not upload_to_r2_flag:
        flash("Image updated successfully", "success")
            
    except Exception as e:
        flash(f"Error updating image: {e}", "error")
    
    return redirect(url_for('view_article', doc_id=doc_id))

@app.route('/upload_to_r2/<doc_id>', methods=['POST'])
def upload_to_r2(doc_id):
    """Upload current article image to R2 and update the URL"""
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    try:
        # Get current article data
        article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
        article = article_ref.get()
        if not article.exists:
            flash("Article not found", "error")
            return redirect(url_for('view_article', doc_id=doc_id))
        
        article_data = article.to_dict()
        current_img_url = article_data.get('img_url')
        article_title = article_data.get('title', '')
        
        if not current_img_url:
            flash("No image URL to upload", "error")
            return redirect(url_for('view_article', doc_id=doc_id))
        
        # Check if image is already on R2
        if current_img_url.startswith(f"https://{r2_storage.client.__dict__.get('_endpoint', {}).get('host', '')}/") or \
           'images.briefsnap.com' in current_img_url:
            flash("Image is already hosted on R2", "info")
            return redirect(url_for('view_article', doc_id=doc_id))
        
        # Upload to R2
        r2_url = r2_storage.upload_image_from_url(current_img_url, article_title)
        if r2_url:
            # Update the article document
            article_ref.update({
                'img_url': r2_url,
                'updated_at': datetime.now(timezone.utc)
            })
            flash(f"Image uploaded to R2 successfully: {r2_url}", "success")
        else:
            flash("Failed to upload image to R2", "error")
            
    except Exception as e:
        flash(f"Error uploading to R2: {e}", "error")
    
    return redirect(url_for('view_article', doc_id=doc_id))

@app.route('/check_r2_status')
def check_r2_status():
    """Check R2 connection status"""
    try:
        status = r2_storage.check_r2_connection()
        return jsonify({
            'status': 'connected' if status else 'disconnected',
            'message': 'R2 connection successful' if status else 'R2 connection failed'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error checking R2 status: {e}'
        })

@app.route('/update_description/<doc_id>', methods=['POST'])
def update_description(doc_id):
    """Update article description"""
    description = request.form.get('description')
    
    if not description:
        flash("Description cannot be empty", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    try:
        # Update the article document
        article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
        article_ref.update({
            'description': description,
            'updated_at': datetime.now(timezone.utc)
        })
        
        flash("Description updated successfully", "success")
    except Exception as e:
        flash(f"Error updating description: {e}", "error")
    
    return redirect(url_for('view_article', doc_id=doc_id))

@app.route('/update_full_article/<doc_id>', methods=['POST'])
def update_full_article(doc_id):
    """Update full article text"""
    full_article = request.form.get('full_article')
    
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    try:
        # Update the article document
        article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
        article_ref.update({
            'full_article': full_article,
            'updated_at': datetime.now(timezone.utc)
        })
        
        flash("Full article updated successfully", "success")
    except Exception as e:
        flash(f"Error updating full article: {e}", "error")
    
    return redirect(url_for('view_article', doc_id=doc_id))

@app.route('/delete_article/<doc_id>', methods=['POST'])
def delete_article(doc_id):
    """Delete an article from Firestore"""
    confirmation = request.form.get('confirmation')
    
    if confirmation != 'DELETE':
        flash("Confirmation text does not match. Article was not deleted.", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return redirect(url_for('view_article', doc_id=doc_id))
    
    try:
        # Get article data for logging
        article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
        article = article_ref.get()
        if article.exists:
            article_data = article.to_dict()
            title = article_data.get('title', 'Unknown title')
            
            # Delete the article
            article_ref.delete()
            
            flash(f"Article '{title}' deleted successfully", "success")
            return redirect(url_for('index'))
        else:
            flash("Article not found", "error")
            return redirect(url_for('index'))
    except Exception as e:
        flash(f"Error deleting article: {e}", "error")
    
    return redirect(url_for('view_article', doc_id=doc_id))

@app.route('/search', methods=['GET'])
def search_articles():
    """Search for articles by title"""
    query = request.args.get('query', '').strip()
    topic_filter = request.args.get('topic', '')
    
    if not query:
        return redirect(url_for('index', topic=topic_filter))
    
    db = FirebaseStorage.get_db()
    if not db:
        flash("Could not connect to Firestore", "error")
        return render_template('index.html', articles=[], topics=get_topics(), active_topic='')
    
    # Get articles from Firestore
    articles_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION)
    
    # Apply topic filter if specified
    if topic_filter:
        articles_ref = articles_ref.where('topic', '==', topic_filter)
    
    # Since Firestore doesn't have a LIKE operator, we'll fetch and filter in Python
    articles = articles_ref.order_by('timestamp', direction='DESCENDING').limit(100).stream()
    
    # Filter articles that contain the query in the title
    articles_list = []
    for article in articles:
        article_data = article.to_dict()
        if query.lower() in article_data.get('title', '').lower():
            article_data['doc_id'] = article.id
            articles_list.append(article_data)
    
    return render_template('index.html', articles=articles_list, query=query, topics=get_topics(), active_topic=topic_filter)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000) 