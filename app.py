import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import PyPDF2
import docx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
import numpy as np
import google.generativeai as genai
from gtts import gTTS
import pygame
from mutagen.mp3 import MP3
import json
from datetime import datetime
from googletrans import Translator, LANGUAGES
import pandas as pd
import csv
import re

app = Flask(__name__)
app.secret_key = 'research_paper_manager_secret_key_2025'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configure Gemini AI with error handling
try:
    GEMINI_API_KEY = 'AIzaSyCDtMEOvDtjjAN4d9QfPv9fXSxG6xtP7_o'  # Replace with actual key
    if GEMINI_API_KEY and GEMINI_API_KEY != 'YOUR_GEMINI_API_KEY_HERE':
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-2.0-flash')
        GEMINI_AVAILABLE = True
    else:
        GEMINI_AVAILABLE = False
except Exception as e:
    print(f"Gemini configuration failed: {e}")
    GEMINI_AVAILABLE = False

# Initialize translator
translator = Translator()

# Supported languages for translation
SUPPORTED_LANGUAGES = {
    'en': 'English',
    'es': 'Spanish', 'fr': 'French', 'de': 'German', 'it': 'Italian',
    'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese', 'ko': 'Korean',
    'zh-cn': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
}

# Custom template filter for JSON parsing
@app.template_filter('fromjson')
def fromjson_filter(value):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return []

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
            return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"

def extract_text_from_docx(file_path):
    try:
        doc = docx.Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        return f"Error extracting text from DOCX: {str(e)}"

def translate_text(text, target_lang='en'):
    """Translate text to target language"""
    try:
        if target_lang == 'en':
            return text
        translation = translator.translate(text, dest=target_lang)
        return translation.text
    except Exception as e:
        print(f"Translation error: {e}")
        return f"Translation failed: {str(e)}"

def generate_summary(content, query):
    """Generate summary using multiple fallback methods"""
    try:
        # Simple summary extraction
        sentences = re.split(r'[.!?]+', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        if not sentences:
            return "No meaningful text content found.", None
        
        # Extract key sections
        summary_parts = []
        if len(sentences) > 3:
            summary_parts.append("Introduction: " + " ".join(sentences[:3]))
        
        # Look for key sections
        for sentence in sentences:
            if len(sentence) > 50 and any(keyword in sentence.lower() for keyword in 
                                        ['method', 'result', 'conclusion', 'finding']):
                summary_parts.append(sentence)
                if len(summary_parts) >= 5:
                    break
        
        summary = ". ".join(summary_parts[:5]) + "."
        return summary, None
    except Exception as e:
        return None, f"Summary Error: {str(e)}"

def get_db_connection():
    conn = sqlite3.connect('research_papers.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    # Create tables
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content TEXT,
            summary TEXT,
            authors TEXT,
            publication_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS citations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL,
            citation_text TEXT NOT NULL,
            format_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (paper_id) REFERENCES papers (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            cluster_name TEXT NOT NULL,
            paper_ids TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create dummy authors data
    conn.execute('''
        CREATE TABLE IF NOT EXISTS authors_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_name TEXT NOT NULL,
            paper_title TEXT NOT NULL,
            citations INTEGER DEFAULT 0,
            publication_year INTEGER,
            journal_name TEXT
        )
    ''')
    
    # Insert dummy authors data if empty
    dummy_authors = [
        ('Dr. Smith Johnson', 'Machine Learning Advances', 45, 2023, 'Journal of AI Research'),
        ('Dr. Smith Johnson', 'Neural Networks Review', 32, 2022, 'Neural Computing'),
        ('Dr. Sarah Chen', 'Data Mining Techniques', 28, 2023, 'Data Science Journal'),
        ('Dr. Sarah Chen', 'Big Data Analytics', 35, 2022, 'IEEE Transactions'),
        ('Dr. Robert Brown', 'Computer Vision Applications', 41, 2023, 'CVPR'),
        ('Dr. Robert Brown', 'Image Processing Methods', 29, 2022, 'IEEE IP'),
        ('Dr. Maria Garcia', 'Natural Language Processing', 38, 2023, 'ACL'),
        ('Dr. Maria Garcia', 'Text Mining Approaches', 26, 2022, 'Computational Linguistics'),
        ('Dr. James Wilson', 'Robotics and AI', 33, 2023, 'Robotics Journal'),
        ('Dr. James Wilson', 'Autonomous Systems', 27, 2022, 'IEEE Robotics')
    ]
    
    for author in dummy_authors:
        conn.execute('''
            INSERT OR IGNORE INTO authors_data (author_name, paper_title, citations, publication_year, journal_name)
            VALUES (?, ?, ?, ?, ?)
        ''', author)
    
    # Create admin user if not exists
    admin_exists = conn.execute('SELECT * FROM users WHERE username = ?', ('admin',)).fetchone()
    if not admin_exists:
        conn.execute('''
            INSERT INTO users (username, password, email, role)
            VALUES (?, ?, ?, ?)
        ''', ('admin', 'admin123', 'admin@research.com', 'admin'))
        print("Admin user created: username='admin', password='admin123'")
    
    conn.commit()
    conn.close()

def play_audio(filename):
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    except Exception as e:
        print(f"Error playing audio: {e}")

def calculate_h_index(citations_list):
    """Calculate h-index from citations list"""
    citations_list.sort(reverse=True)
    h_index = 0
    for i, citations in enumerate(citations_list):
        if citations >= i + 1:
            h_index = i + 1
        else:
            break
    return h_index

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                           (username, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f'Login successful! Welcome {user["username"]}', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        
        # Check if username is 'admin'
        if username.lower() == 'admin':
            flash('Username "admin" is reserved. Please choose a different username.', 'error')
            return render_template('register.html')
        
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
                        (username, password, email))
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists', 'error')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    paper_count = conn.execute('SELECT COUNT(*) FROM papers WHERE user_id = ?', 
                              (session['user_id'],)).fetchone()[0]
    cluster_count = conn.execute('SELECT COUNT(*) FROM clusters WHERE user_id = ?', 
                                (session['user_id'],)).fetchone()[0]
    citation_count = conn.execute('''SELECT COUNT(*) FROM citations c 
                                   JOIN papers p ON c.paper_id = p.id 
                                   WHERE p.user_id = ?''', 
                                (session['user_id'],)).fetchone()[0]
    analysis_count = conn.execute('SELECT COUNT(*) FROM papers WHERE user_id = ? AND summary IS NOT NULL', 
                                 (session['user_id'],)).fetchone()[0]
    
    recent_papers = conn.execute('SELECT * FROM papers WHERE user_id = ? ORDER BY created_at DESC LIMIT 5', 
                                (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('dashboard.html', 
                          paper_count=paper_count, 
                          cluster_count=cluster_count,
                          citation_count=citation_count,
                          analysis_count=analysis_count,
                          recent_papers=recent_papers)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot upload papers', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Check if paper with same name already exists for this user
            conn = get_db_connection()
            existing_paper = conn.execute('SELECT * FROM papers WHERE user_id = ? AND filename = ?', 
                                        (session['user_id'], filename)).fetchone()
            if existing_paper:
                flash('A paper with this name has already been uploaded!', 'error')
                conn.close()
                return redirect(request.url)
            
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Extract text based on file type
            if filename.lower().endswith('.pdf'):
                content = extract_text_from_pdf(file_path)
            elif filename.lower().endswith(('.doc', '.docx')):
                content = extract_text_from_docx(file_path)
            else:
                content = "Unsupported file format"
            
            # Store in database
            conn.execute('''
                INSERT INTO papers (user_id, title, filename, file_path, content)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], filename, filename, file_path, content))
            conn.commit()
            conn.close()
            
            flash('File uploaded successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid file type. Please upload PDF or DOC/DOCX files.', 'error')
    
    return render_template('upload.html')

@app.route('/search_papers', methods=['GET', 'POST'])
def search_papers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot search user papers', 'error')
        return redirect(url_for('admin_dashboard'))
    
    search_results = []
    search_query = ""
    
    if request.method == 'POST':
        search_query = request.form.get('search_query', '')
        if search_query:
            conn = get_db_connection()
            search_results = conn.execute('''
                SELECT * FROM papers 
                WHERE user_id = ? AND title LIKE ? 
                ORDER BY created_at DESC
            ''', (session['user_id'], f'%{search_query}%')).fetchall()
            conn.close()
    
    return render_template('search_papers.html', 
                         search_results=search_results, 
                         search_query=search_query)

@app.route('/summary', methods=['GET', 'POST'])
def summary():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot generate summaries', 'error')
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    papers = conn.execute('SELECT * FROM papers WHERE user_id = ?', 
                         (session['user_id'],)).fetchall()
    conn.close()
    
    summary_result = None
    audio_file = None
    selected_language = 'en'
    
    if request.method == 'POST':
        paper_id = request.form['paper_id']
        query = request.form['query']
        selected_language = request.form.get('language', 'en')
        
        conn = get_db_connection()
        paper = conn.execute('SELECT * FROM papers WHERE id = ? AND user_id = ?', 
                            (paper_id, session['user_id'])).fetchone()
        conn.close()
        
        if paper and paper['content']:
            try:
                original_summary, error = generate_summary(paper['content'], query)
                
                if original_summary:
                    summary_result = original_summary
                    
                    # Translate if needed
                    if selected_language != 'en':
                        translated = translate_text(original_summary, selected_language)
                        if "Translation failed" not in translated:
                            summary_result = translated
                    
                    # Update database
                    conn = get_db_connection()
                    conn.execute('UPDATE papers SET summary = ? WHERE id = ?', 
                                (original_summary, paper_id))
                    conn.commit()
                    conn.close()
                    
                    # Generate audio
                    try:
                        tts = gTTS(text=summary_result[:500], lang=selected_language)
                        audio_filename = f"summary_{paper_id}_{selected_language}.mp3"
                        audio_path = os.path.join('static', audio_filename)
                        tts.save(audio_path)
                        audio_file = audio_filename
                    except Exception as e:
                        print(f"Audio error: {e}")
                        
            except Exception as e:
                summary_result = f"Error: {str(e)}"
    
    return render_template('summary.html', 
                         papers=papers, 
                         summary=summary_result, 
                         audio_file=audio_file,
                         languages=SUPPORTED_LANGUAGES,
                         selected_language=selected_language)

@app.route('/clustering')
def clustering():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot use clustering', 'error')
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    papers = conn.execute('SELECT * FROM papers WHERE user_id = ?', 
                         (session['user_id'],)).fetchall()
    clusters = conn.execute('SELECT * FROM clusters WHERE user_id = ?', 
                           (session['user_id'],)).fetchall()
    conn.close()
    
    # Perform clustering if we have papers
    clustered_papers = {}
    if papers:
        # Extract text content from papers that have content
        documents = []
        valid_paper_indices = []
        
        for i, paper in enumerate(papers):
            if paper['content'] and len(paper['content']) > 100:
                documents.append(paper['content'])
                valid_paper_indices.append(i)
        
        if len(documents) > 1:
            try:
                # Create TF-IDF vectors
                vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
                tfidf_matrix = vectorizer.fit_transform(documents)
                
                # Perform K-means clustering
                n_clusters = min(5, len(documents))
                kmeans = KMeans(n_clusters=n_clusters, random_state=42)
                clusters_result = kmeans.fit_predict(tfidf_matrix)
                
                # Group papers by cluster
                for idx, cluster_id in enumerate(clusters_result):
                    paper_index = valid_paper_indices[idx]
                    if cluster_id not in clustered_papers:
                        clustered_papers[cluster_id] = []
                    clustered_papers[cluster_id].append(papers[paper_index])
            except Exception as e:
                print(f"Clustering error: {e}")
                # If clustering fails, put all papers in one cluster
                if documents:
                    clustered_papers[0] = [papers[i] for i in valid_paper_indices]
        elif len(documents) == 1:
            # Only one paper with content
            clustered_papers[0] = [papers[valid_paper_indices[0]]]
    
    return render_template('clustering.html', clusters=clustered_papers, db_clusters=clusters)

@app.route('/save_cluster', methods=['POST'])
def save_cluster():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    cluster_name = request.json.get('cluster_name')
    paper_ids = request.json.get('paper_ids', [])
    
    conn = get_db_connection()
    conn.execute('INSERT INTO clusters (user_id, cluster_name, paper_ids) VALUES (?, ?, ?)',
                (session['user_id'], cluster_name, json.dumps(paper_ids)))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Cluster saved successfully'})

@app.route('/citations', methods=['GET', 'POST'])
def citations():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot generate citations', 'error')
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    papers = conn.execute('SELECT * FROM papers WHERE user_id = ?', 
                         (session['user_id'],)).fetchall()
    
    citations_list = []
    for paper in papers:
        paper_citations = conn.execute('SELECT * FROM citations WHERE paper_id = ?', 
                                      (paper['id'],)).fetchall()
        citations_list.extend(paper_citations)
    
    conn.close()
    
    if request.method == 'POST':
        paper_id = request.form['paper_id']
        format_type = request.form['format_type']
        
        conn = get_db_connection()
        paper = conn.execute('SELECT * FROM papers WHERE id = ? AND user_id = ?', 
                            (paper_id, session['user_id'])).fetchone()
        
        if paper:
            # Generate citation based on format
            if format_type == 'APA':
                citation = f"Author. ({datetime.now().year}). {paper['title']}. [PDF]"
            elif format_type == 'MLA':
                citation = f"Author. \"{paper['title']}\". {datetime.now().year}. PDF."
            elif format_type == 'Chicago':
                citation = f"Author. {datetime.now().year}. \"{paper['title']}\". PDF."
            else:
                citation = f"Author. ({datetime.now().year}). {paper['title']}."
            
            # Save citation to database
            conn.execute('INSERT INTO citations (paper_id, citation_text, format_type) VALUES (?, ?, ?)',
                        (paper_id, citation, format_type))
            conn.commit()
        
        conn.close()
        flash('Citation generated successfully!', 'success')
        return redirect(url_for('citations'))
    
    return render_template('citations.html', papers=papers, citations=citations_list)

@app.route('/plagiarism')
def plagiarism():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot check plagiarism', 'error')
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    papers = conn.execute('SELECT * FROM papers WHERE user_id = ?', 
                         (session['user_id'],)).fetchall()
    conn.close()
    
    similarity_data = None
    paper_titles = []
    
    if len(papers) > 1:
        documents = []
        for paper in papers:
            if paper['content'] and len(paper['content']) > 100:
                documents.append(paper['content'])
                paper_titles.append(paper['title'])
        
        if len(documents) > 1:
            try:
                vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
                tfidf_matrix = vectorizer.fit_transform(documents)
                similarity_matrix = cosine_similarity(tfidf_matrix, tfidf_matrix)
                
                # Convert to percentage and create detailed data
                similarity_data = []
                for i in range(len(paper_titles)):
                    for j in range(i+1, len(paper_titles)):
                        similarity_percent = round(similarity_matrix[i][j] * 100, 2)
                        similarity_data.append({
                            'paper1': paper_titles[i],
                            'paper2': paper_titles[j],
                            'similarity': similarity_percent,
                            'status': 'High' if similarity_percent > 70 else 
                                     'Medium' if similarity_percent > 30 else 'Low'
                        })
                
            except Exception as e:
                print(f"Similarity error: {e}")
    
    return render_template('plagiarism.html', 
                          papers=papers, 
                          similarity_data=similarity_data,
                          has_data=similarity_data is not None and len(similarity_data) > 0)

@app.route('/author_metrics', methods=['GET', 'POST'])
def author_metrics():
    author_data = None
    h_index = 0
    total_citations = 0
    paper_count = 0
    
    if request.method == 'POST':
        author_name = request.form.get('author_name', '').strip()
        if author_name:
            conn = get_db_connection()
            author_data = conn.execute('''
                SELECT * FROM authors_data 
                WHERE author_name LIKE ? 
                ORDER BY citations DESC
            ''', (f'%{author_name}%',)).fetchall()
            conn.close()
            
            if author_data:
                citations_list = [paper['citations'] for paper in author_data]
                h_index = calculate_h_index(citations_list)
                total_citations = sum(citations_list)
                paper_count = len(author_data)
    
    return render_template('author_metrics.html',
                         author_data=author_data,
                         h_index=h_index,
                         total_citations=total_citations,
                         paper_count=paper_count)

@app.route('/metrics')
def metrics():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('role') == 'admin':
        flash('Admins cannot view user metrics', 'error')
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    papers = conn.execute('SELECT * FROM papers WHERE user_id = ?', 
                         (session['user_id'],)).fetchall()
    
    # Calculate basic metrics
    total_papers = len(papers)
    
    # Calculate average paper length
    total_length = 0
    for paper in papers:
        if paper['content']:
            total_length += len(paper['content'])
    avg_length = total_length / total_papers if total_papers > 0 else 0
    
    # Get citation count
    citation_count = conn.execute('SELECT COUNT(*) FROM citations c JOIN papers p ON c.paper_id = p.id WHERE p.user_id = ?', 
                                (session['user_id'],)).fetchone()[0]
    
    # Calculate h-index (simplified)
    citations_per_paper = []
    for paper in papers:
        paper_citations = conn.execute('SELECT COUNT(*) FROM citations WHERE paper_id = ?', 
                                      (paper['id'],)).fetchone()[0]
        citations_per_paper.append(paper_citations)
    
    citations_per_paper.sort(reverse=True)
    h_index = 0
    for i, count in enumerate(citations_per_paper):
        if count >= i + 1:
            h_index = i + 1
        else:
            break
    
    conn.close()
    
    metrics_data = {
        'total_papers': total_papers,
        'avg_paper_length': round(avg_length),
        'total_citations': citation_count,
        'h_index': h_index,
        'papers_with_citations': sum(1 for count in citations_per_paper if count > 0)
    }
    
    return render_template('metrics.html', metrics=metrics_data)

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Admin access required', 'error')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get statistics
    total_users = conn.execute('SELECT COUNT(*) FROM users WHERE role = "user"').fetchone()[0]
    total_papers = conn.execute('SELECT COUNT(*) FROM papers').fetchone()[0]
    total_citations = conn.execute('SELECT COUNT(*) FROM citations').fetchone()[0]
    total_clusters = conn.execute('SELECT COUNT(*) FROM clusters').fetchone()[0]
    
    # Get recent activity
    recent_papers = conn.execute('''
        SELECT p.*, u.username 
        FROM papers p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    recent_users = conn.execute('''
        SELECT * FROM users 
        WHERE role = "user" 
        ORDER BY created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin_dashboard.html',
                         total_users=total_users,
                         total_papers=total_papers,
                         total_citations=total_citations,
                         total_clusters=total_clusters,
                         recent_papers=recent_papers,
                         recent_users=recent_users)

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users WHERE role = "user"').fetchall()
    conn.close()
    
    return render_template('admin_users.html', users=users)

@app.route('/admin/papers')
def admin_papers():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    papers = conn.execute('''
        SELECT p.*, u.username 
        FROM papers p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC
    ''').fetchall()
    conn.close()
    
    return render_template('admin_papers.html', papers=papers)

@app.route('/admin/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    flash('User deleted successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_paper/<int:paper_id>')
def delete_paper(paper_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    conn.execute('DELETE FROM papers WHERE id = ?', (paper_id,))
    conn.commit()
    conn.close()
    
    flash('Paper deleted successfully', 'success')
    return redirect(url_for('admin_papers'))

@app.route('/translate_summary', methods=['POST'])
def translate_summary():
    """API endpoint to translate existing summary"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    data = request.get_json()
    summary_text = data.get('summary_text')
    target_language = data.get('target_language', 'en')
    
    if not summary_text:
        return jsonify({'success': False, 'message': 'No summary text provided'})
    
    try:
        translated_summary = translate_text(summary_text, target_language)
        return jsonify({
            'success': True, 
            'translated_summary': translated_summary,
            'target_language': SUPPORTED_LANGUAGES.get(target_language, 'Unknown')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Translation failed: {str(e)}'})

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    init_db()
    print("=" * 50)
    print("Research Paper Manager Started Successfully!")
    print("Admin Login: username='admin', password='admin123'")
    print("Register new users or login with admin credentials")
    print("=" * 50)
    app.run(debug=True)