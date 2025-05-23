from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_from_directory, jsonify, current_app
from urllib.parse import urlparse, urljoin

def is_safe_url(target):
    """Ensure the target URL is safe to redirect to (prevents open redirects)."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import zipfile
import shutil
from datetime import datetime, timedelta
import re
import markdown
from bs4 import BeautifulSoup
from debug_utils import log_exceptions, log_info, log_error, log_debug # Ensure all are imported
import pymdownx

# Helper function to parse a single question block from markdown
def parse_single_question_block(question_block_md):
    question_dict = {
        'text': '',
        'option_a': '',
        'option_b': '',
        'option_c': '',
        'option_d': '',
        'correct_option': '',
        'explanation': ''
    }
    options_labels = ['A', 'B', 'C', 'D']
    option_index = 0

    # Convert markdown to HTML
    # Using pymdownx.extra for better table/definition list support if needed, 
    # and pymdownx.tasklist for checkbox parsing.
    html_content = markdown.markdown(
        question_block_md, 
        extensions=['pymdownx.tasklist', 'markdown.extensions.extra']
    )
    soup = BeautifulSoup(html_content, 'html.parser')

    # Extract question text (typically in <p> tags not part of options or explanation)
    # and explanation
    paragraphs = soup.find_all('p')
    question_text_parts = []
    for p in paragraphs:
        p_text = p.get_text(separator=' ', strip=True)
        if p_text.lower().startswith('explanation:'):
            question_dict['explanation'] = p_text[len('explanation:'):].strip()
        elif not p.find_parent('li'): # Avoid text within list items if any <p> are there
             # Check if it's part of a tasklist item (though options are usually not in <p>)
            is_option_related = False
            parent_li = p.find_parent('li', class_='task-list-item')
            if parent_li:
                 is_option_related = True
            
            if not is_option_related and not question_dict['explanation']: # if explanation is already found, this is likely not it
                 question_text_parts.append(p_text)

    if question_text_parts:
        question_dict['text'] = "\n".join(question_text_parts).strip()
    elif soup.body and soup.body.contents: # Fallback if question text is not in <p>
        # Try to get the first text node or non-list/non-explanation content
        first_content = soup.body.contents[0]
        if isinstance(first_content, str):
             question_dict['text'] = first_content.strip()
        elif hasattr(first_content, 'get_text'):
             temp_text = first_content.get_text(strip=True)
             if not temp_text.lower().startswith('explanation:') and not first_content.name == 'ul':
                 question_dict['text'] = temp_text


    # Extract options from <li> elements (task list items)
    list_items = soup.find_all('li', class_='task-list-item')
    if not list_items: # Fallback if specific class is not used but it's a list
        list_items = soup.find_all('li')

    for li in list_items:
        if option_index < len(options_labels):
            checkbox = li.find('input', type='checkbox')
            option_text = ""
            # Get text, excluding the checkbox itself if it was rendered with text
            for content_part in li.contents:
                if isinstance(content_part, str):
                    option_text += content_part.strip()
                elif hasattr(content_part, 'get_text'):
                    # Avoid adding checkbox tag text if any, though usually not an issue
                    if not (hasattr(content_part, 'name') and content_part.name == 'input' and content_part.get('type') == 'checkbox'):
                        option_text += " " + content_part.get_text(strip=True)
            option_text = option_text.strip()
            
            # If parsing gives empty string from complex HTML, try direct text of li
            if not option_text and li.get_text(strip=True):
                 option_text = " ".join(li.get_text(strip=True).split()) # Normalize spaces

            # Clean up option text if it starts with '[ ]' or '[x]' due to non-standard markdown rendering
            option_text = re.sub(r'^\[[xX\s]\]\s*', '', option_text).strip()

            key = f'option_{options_labels[option_index].lower()}'
            question_dict[key] = option_text
            
            if checkbox and checkbox.has_attr('checked'):
                question_dict['correct_option'] = options_labels[option_index]
            
            option_index += 1
        else:
            log_debug(f"Found more than 4 options for a question block: {question_block_md}")
            break 
            
    # If question text is still empty, try to find text not in ul/ol/li
    if not question_dict['text']:
        all_text = soup.get_text(separator='\n', strip=True)
        potential_text = []
        in_options_or_explanation = False
        for line in all_text.split('\n'):
            line_stripped = line.strip()
            if any(opt_text == line_stripped for opt_key, opt_text in question_dict.items() if opt_key.startswith('option_') and opt_text):
                in_options_or_explanation = True
                continue
            if question_dict['explanation'] and question_dict['explanation'] in line_stripped:
                in_options_or_explanation = True
                continue
            if line_stripped and not (line_stripped.startswith('- [') or line_stripped.lower().startswith('explanation:')):
                 potential_text.append(line_stripped)
            
        # Take the longest continuous block of text not part of options/explanation
        if potential_text:
             # Heuristic: Question text is usually before options.
             # This part might need more robust logic based on actual markdown structure.
             first_option_text = question_dict.get('option_a', '')
             candidate_text_joined = " ".join(potential_text)
             if first_option_text and first_option_text in candidate_text_joined:
                 question_dict['text'] = candidate_text_joined.split(first_option_text)[0].strip()
             else:
                 question_dict['text'] = candidate_text_joined # Fallback

    # Final cleanup of text if it's just the filename (edge case for bad markdown)
    if question_dict['text'].endswith(".md"):
        question_dict['text'] = "" # Or some placeholder like "Error: Could not parse question text"

    return question_dict

# Main helper function to parse a string containing multiple questions
def parse_markdown_questions(content):
    # First, split the content into individual questions
    question_blocks = content.split('---')
    questions = []
    
    for block_md in question_blocks:
        if not block_md.strip():
            continue
        
        # Parse each block using the new single block parser
        question_data = parse_single_question_block(block_md)
        questions.append(question_data)
    
    return questions

# Helper function to find the question file path
def get_question_file_path(base_folder, filename):
    """
    Finds the full path to a file within a base folder and its subdirectories.
    Returns the full path if found, otherwise None.
    """
    if not base_folder or not filename:
        log_error("get_question_file_path: base_folder or filename is missing.")
        return None
    
    # Ensure base_folder exists to prevent os.walk from erroring on non-existent paths
    if not os.path.exists(base_folder):
        log_error(f"get_question_file_path: Base folder '{base_folder}' does not exist.")
        return None

    for dirpath, _, filenames in os.walk(base_folder):
        if filename in filenames:
            return os.path.join(dirpath, filename)
    
    log_info(f"get_question_file_path: File '{filename}' not found in '{base_folder}'.")
    return None


# Main app Configuration
app = Flask(__name__, static_url_path='/static')
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads/questions'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['EXPLAIN_TEMPLATE_LOADING'] = True

# Initialize logger when app starts
log_info("Application started")

# Enable debug toolbar if installed
try:
    from flask_debugtoolbar import DebugToolbarExtension
    app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = False
    toolbar = DebugToolbarExtension(app)
except ImportError:
    pass  # Debug toolbar not installed, continue without it

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# Models
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String, nullable=False)
    option_a = db.Column(db.String, nullable=False)
    option_b = db.Column(db.String, nullable=False)
    option_c = db.Column(db.String, nullable=False)
    option_d = db.Column(db.String, nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)  # 'A', 'B', 'C', or 'D'

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=True)

class Response(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    selected_option = db.Column(db.String(1), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)

    student = db.relationship('Student', backref=db.backref('responses', lazy=True))
    question = db.relationship('Question', backref=db.backref('responses', lazy=True))

# User model for authentication
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)  # Making email optional
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='student')  # 'admin' or 'student'
    name = db.Column(db.String(100), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)



@app.route('/')
def index():
    return redirect(url_for('login'))



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to appropriate dashboard
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('student_dashboard'))
    
    next_page = request.args.get('next')
            
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        # Try to find user by username or email
        user = User.query.filter((User.username == username) | (User.email == username)).first()
        
        if user and user.check_password(password):
            login_user(user, remember=remember)
            flash('Logged in successfully!', 'success')
            
            # Safe URL validation
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    # Pass next_page to the template to maintain it in the login form
    return render_template('login.html', next=next_page)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    #Will be future scope. Not now
    flash('Contact Team Eso Kichu Kori.', 'info')
    return redirect(url_for('login'))


## Dasboards ##

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    user_count = User.query.count()
    student_count = User.query.filter((User.role == 'student') | (User.role == 'user')).count()
    test_count = Test.query.count()
    log_debug(f"user_count: {user_count}, test_count: {test_count}")
    result_count = 0  # Placeholder, update as needed
    return render_template('admin_dashboard.html', user_count=user_count, student_count=student_count, test_count=test_count, result_count=result_count)

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    log_debug(f"Student Dashboard - User: {getattr(current_user, 'username', None)}, "
              f"Role: {getattr(current_user, 'role', None)}, "
              f"Authenticated: {getattr(current_user, 'is_authenticated', None)}")
    
    if not current_user.is_authenticated:
        log_debug("User not authenticated, redirecting to login")
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('login'))
        
    if current_user.role != 'student':
        log_debug(f"Access denied - User role is {current_user.role}, expected student")
        flash('Access denied. Student access only.', 'danger')
        return redirect(url_for('login'))
        
    log_debug("Rendering student dashboard")
    return render_template('student_dashboard.html')

@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        abort(403)
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@login_required
def admin_add_user():
    if current_user.role != 'admin':
        abort(403)
    if request.method == 'POST':
        name = request.form.get('name')
        username = request.form.get('username')
        email = request.form.get('email', None)  # Make email optional
        password = request.form.get('password')
        role = request.form.get('role')
        
        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already taken. Please choose a different one.', 'danger')
            return redirect(url_for('admin_add_user'))
            
        # Check if email is provided and not already in use
        if email and User.query.filter_by(email=email).first():
            flash('Email already registered. Please use a different email or leave it blank.', 'danger')
            return redirect(url_for('admin_add_user'))
            
        user = User(username=username, email=email, name=name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin_add_user.html')

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        # Get form data
        username = request.form.get('username')
        email = request.form.get('email', None)  # Make email optional
        
        # Check if username is being changed and if it's already taken
        if username != user.username and User.query.filter_by(username=username).first():
            flash('Username already taken. Please choose a different one.', 'danger')
            return redirect(url_for('admin_edit_user', user_id=user_id))
            
        # Check if email is being changed and if it's already in use (if provided)
        if email and email != user.email and User.query.filter_by(email=email).first():
            flash('Email already in use. Please use a different email or leave it blank.', 'danger')
            return redirect(url_for('admin_edit_user', user_id=user_id))
        
        # Update user data
        user.name = request.form.get('name')
        user.username = username
        user.email = email if email else None
        user.role = request.form.get('role')
        
        # Update password if provided
        password = request.form.get('password')
        if password:
            user.set_password(password)
            
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin_edit_user.html', user=user)

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete yourself.', 'danger')
        return redirect(url_for('admin_users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('admin_users'))



@app.route('/admin/questions/edit/<test_id>')
@login_required
def admin_questions_edit(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    file_path = get_question_file_path(test.foldername, test.filename)
    
    questions_content = ""
    if file_path:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                questions_content = f.read()
        except Exception as e:
            log_error(f"Error reading questions file '{file_path}': {e}")
            flash(f"Error reading question file for test {test.test_id}.", "danger")
    else:
        log_error(f"Question file not found for test ID {test.test_id} in folder {test.foldername}")
        flash(f"Question file not found for test {test.test_id}.", "danger")
        # questions_content remains ""
    
    return render_template('admin_edit_questions.html', test=test, questions=questions_content)

@app.route('/admin/questions/view/<test_id>')
@login_required
def admin_view_questions(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    file_path = get_question_file_path(test.foldername, test.filename)
    
    if not file_path:
        log_error(f"Question file '{test.filename}' not found in '{test.foldername}' for test ID {test.test_id}.")
        flash(f"Question file not found for test {test.test_id}.", "danger")
        return render_template('admin_view_questions.html', test=test, error=f"Question file not found.")

    log_debug(f"Looking for file at: {file_path}")
    # upload_dir can be derived from file_path if needed: os.path.dirname(file_path)
    # log_debug(f"Upload directory exists: {os.path.exists(os.path.dirname(file_path))}")
    log_debug(f"File exists: {os.path.exists(file_path)}")
    # log_debug(f"Files in directory: {os.listdir(os.path.dirname(file_path)) if os.path.exists(os.path.dirname(file_path)) else 'Directory not found'}")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_markdown = f.read()
            html_content = markdown.markdown(raw_markdown, extensions=['markdown.extensions.tables', 'markdown.extensions.extra', 'pymdownx.extra', 'pymdownx.tasklist', 'pymdownx.arithmatex'], extension_configs={'pymdownx.arithmatex': {'generic': True}})
            
            log_info("Successfully converted markdown to HTML")
            return render_template('admin_view_questions.html', 
                               test=test, 
                               questions=html_content,
                               raw_markdown=raw_markdown)
            
    except FileNotFoundError:
        error_msg = f"No questions found for this test. Expected file at: {file_path}"
        log_error(f"File not found: {file_path}")
        return render_template('admin_view_questions.html', 
                           test=test,
                           error=error_msg)
    except Exception as e:
        error_msg = f"Error reading questions: {str(e)}"
        log_error(error_msg)
        # The following print seems to be a leftover or mistake, as it's after a return.
        # If it were reachable, it would be: log_error(f"Error: {str(e)}")
        return render_template('admin_view_questions.html',
                           test=test,
                           error=error_msg)
        # print(f"Error: {str(e)}") # This line is unreachable
    
    return render_template('admin_view_questions.html', 
                         test=test, 
                         questions=markdown_content)





class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    test_id = db.Column(db.String(50), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    foldername = db.Column(db.String(200), nullable=False)  # uploaded folder name
    filename = db.Column(db.String(200), nullable=False)  # uploaded Markdown filename
    time_limit = db.Column(db.Integer, default=60)  # Time limit in minutes
    
    # Relationship with User who created the test
    creator = db.relationship('User', backref=db.backref('tests_created', lazy=True))

class StudentResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey('test.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    time_taken = db.Column(db.Integer, nullable=False)  # in seconds
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('User', backref=db.backref('test_responses', lazy=True))
    test = db.relationship('Test', backref=db.backref('responses', lazy=True))

@app.route('/admin/tests')
@login_required
def admin_tests():
    if current_user.role != 'admin':
        abort(403)
    tests = Test.query.order_by(Test.created_at.desc()).all()
    return render_template('admin_tests.html', tests=tests)

@app.route('/admin/tests/create', methods=['GET', 'POST'])
@login_required
def admin_create_test():
    if current_user.role != 'admin':
        abort(403)
    
    # Debug information
    log_debug(f"Current user: {current_user}")
    log_debug(f"Current user ID: {current_user.id if current_user.is_authenticated else 'Not authenticated'}")
    
    if request.method == 'POST':
        subject = request.form.get('subject')
        test_id = request.form.get('test_id')
        time_limit = int(request.form.get('time_limit', 60))
        file = request.files.get('file')
        
        if not all([subject, test_id, file]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('admin_create_test'))
            
        if not (file.filename.endswith('.md') or file.filename.endswith('.zip')):
            flash('Please upload a Markdown (.md) or ZIP file containing Markdown.', 'danger')
            return redirect(url_for('admin_create_test'))
        
        test_dir = None # Initialize test_dir to ensure it's available in finally/except
        try:
            # Create test directory inside UPLOAD_FOLDER
            test_dir = os.path.join(app.config['UPLOAD_FOLDER'], test_id)
            log_info(f"Attempting to create test directory: {test_dir}")

            if os.path.exists(test_dir):
                flash(f'A test with ID {test_id} already exists. Please choose a different Test ID.', 'danger')
                log_warn(f"Test directory {test_dir} already exists.")
                return redirect(url_for('admin_create_test'))
                
            os.makedirs(test_dir, exist_ok=True)
            log_info(f"Successfully created test directory: {test_dir}")
            
            original_filename = secure_filename(file.filename)

            if original_filename.endswith('.md'):
                filepath = os.path.join(test_dir, 'questions.md')
                log_info(f"Saving uploaded MD file to: {filepath}")
                file.save(filepath)
                log_info(f"Successfully saved MD file: {filepath}")
                
            elif original_filename.endswith('.zip'):
                temp_zip_path = os.path.join(test_dir, original_filename)
                log_info(f"Saving uploaded ZIP file to: {temp_zip_path}")
                file.save(temp_zip_path)
                log_info(f"Successfully saved ZIP file: {temp_zip_path}")
                
                log_info(f"Attempting to extract ZIP file: {temp_zip_path}")
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    zip_ref.extractall(test_dir)
                log_info(f"Successfully extracted ZIP file to: {test_dir}")
                
                log_info(f"Attempting to remove temporary ZIP file: {temp_zip_path}")
                os.remove(temp_zip_path)
                log_info(f"Successfully removed temporary ZIP file: {temp_zip_path}")
                
                md_files = []
                for root, _, files_in_zip in os.walk(test_dir):
                    for file_iter in files_in_zip:
                        if file.lower().endswith('.md'):
                            md_files.append(os.path.join(root, file))
                
                log_debug(f"Found MD files after extraction: {md_files}")

                if not md_files:
                    flash('No Markdown (.md) file found in the uploaded ZIP archive.', 'danger')
                    log_error("No MD file found in ZIP archive.")
                    # Cleanup is handled by the broader except block
                    raise ValueError("No MD file in ZIP") # Trigger cleanup
                elif len(md_files) > 1:
                    flash('Multiple Markdown (.md) files found in the ZIP archive. Please ensure only one is present.', 'danger')
                    log_error("Multiple MD files found in ZIP archive.")
                    raise ValueError("Multiple MD files in ZIP") # Trigger cleanup

                extracted_md_path = md_files[0]
                target_md_path = os.path.join(test_dir, 'questions.md')

                if extracted_md_path.lower() != target_md_path.lower():
                    log_info(f"Renaming extracted MD file '{extracted_md_path}' to '{target_md_path}'")
                    if os.path.exists(target_md_path):
                         # This case should ideally not be hit if temp_zip_path is unique enough
                         # or if the ZIP doesn't contain 'questions.md' directly when another .md is also present.
                        log_warn(f"Target file '{target_md_path}' already exists. Overwriting.")
                        os.remove(target_md_path) 
                    os.rename(extracted_md_path, target_md_path)
                    log_info("Successfully renamed MD file.")
            
            # Debug information - these are fine as debug
            log_debug(f"Current user for test creation: {current_user}")
            log_debug(f"Current user ID for test creation: {current_user.id}")
            log_debug(f"Is authenticated for test creation: {current_user.is_authenticated}")
            
            # Create new test in database
            new_test = Test(
                test_id=test_id,
                subject=subject,
                foldername=test_dir, # Storing the absolute path or path relative to app.config['UPLOAD_FOLDER']
                filename='questions.md',
                time_limit=time_limit,
                created_at=datetime.utcnow(),
                created_by=current_user.id
            )
            
            log_debug(f"Test object before commit: {new_test}")
            db.session.add(new_test)
            db.session.commit()
            log_info(f"Successfully committed new test {test_id} to database.")
            
            flash('Test created successfully!', 'success')
            return redirect(url_for('admin_tests'))

        except (IOError, OSError) as e:
            log_error(f"File system error during test creation for {test_id}: {e}", exc_info=True)
            flash(f'A file system error occurred: {e.strerror}. Please check logs and permissions.', 'danger')
            db.session.rollback() # Rollback if any DB operation was attempted before this error
        except zipfile.BadZipFile as e:
            log_error(f"Bad ZIP file uploaded for test {test_id}: {e}", exc_info=True)
            flash('The uploaded ZIP file is invalid or corrupted. Please upload a valid ZIP file.', 'danger')
            db.session.rollback()
        except FileNotFoundError as e: # Should be caught by IOError/OSError but good for explicitness if direct calls are made
            log_error(f"File not found during test creation for {test_id}: {e}", exc_info=True)
            flash(f'A required file was not found: {e.filename}. Please try again.', 'danger')
            db.session.rollback()
        except ValueError as e: # For custom errors like "No MD file in ZIP"
            log_error(f"Validation error during test creation for {test_id}: {str(e)}", exc_info=True)
            # The flash message is already set for these specific ValueErrors
            if not any(m.category == 'danger' for m in get_flashed_messages(with_categories=True)): # Avoid double flashing
                flash(str(e), 'danger')
            db.session.rollback()
        except Exception as e: # General fallback
            log_error(f"An unexpected error occurred during test creation for {test_id}: {e}", exc_info=True)
            flash('An unexpected error occurred. Please check the logs and try again.', 'danger')
            db.session.rollback() # Ensure rollback for any other error
        finally:
            # Cleanup: if test_dir was created but test creation failed (e.g. DB error or other exception)
            # Check if 'new_test' was committed. If not, and dir exists, remove it.
            # This logic needs to be careful. If commit succeeded but redirect failed, we don't want to delete.
            # A simple way: if an exception occurred AND the directory exists, clean up.
            # The 'except' blocks above now handle rollback.
            # If an error occurred and test_dir is set and exists:
            if test_dir and os.path.exists(test_dir) and 'new_test' in locals() and not db.session.object_session(new_test):
                # This condition means new_test was not successfully committed or added to session for commit
                # Or more simply, if any exception occurred and test_dir exists, and we are about to redirect to create_test again
                # For now, the existing shutil.rmtree in the broad exception is fine if specific ones also trigger it.
                # Let's refine: if an exception occurred, and 'test_dir' exists, attempt cleanup
                # The 'new_test.id is None' check implies it wasn't committed.
                if 'e' in locals() and test_dir and os.path.exists(test_dir):
                     # Check if the test was actually committed by trying to fetch it
                    test_committed = Test.query.filter_by(test_id=test_id).first()
                    if not test_committed:
                        log_info(f"Cleaning up directory {test_dir} due to error in test creation.")
                        shutil.rmtree(test_dir, ignore_errors=True) # ignore_errors is fine for cleanup
                    else:
                        log_info(f"Directory {test_dir} not cleaned up as test was found in DB (possibly error after commit).")
            # This redirect should only happen if an error was caught and not handled by returning redirect elsewhere
            if 'e' in locals(): # If any exception was caught
                 return redirect(url_for('admin_create_test'))

    return render_template('admin_create_test.html')

@app.route('/admin/tests/delete/<int:test_id>', methods=['POST'])
@login_required
@log_exceptions # This decorator already logs exceptions generally
def admin_delete_test(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.get_or_404(test_id)
    
    archive_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], 'archive')
    if not os.path.exists(archive_folder_path):
        try:
            os.makedirs(archive_folder_path)
            log_info(f"Created archive folder: {archive_folder_path}")
        except (IOError, OSError) as e:
            log_error(f"Could not create archive folder {archive_folder_path}: {e}", exc_info=True)
            flash(f"Warning: Could not create archive folder. Test folder {test.foldername} may not be archived.", "warning")
            # Proceed with deletion even if archive folder creation fails

    if os.path.exists(test.foldername): # Check if folder exists before trying to move
        try:
            log_info(f"Attempting to archive test folder {test.foldername} to {archive_folder_path}")
            shutil.move(test.foldername, archive_folder_path)
            log_info(f"Successfully archived test folder {test.foldername}")
        except (IOError, OSError) as e:
            log_error(f"Failed to archive test folder {test.foldername}: {e}", exc_info=True)
            flash(f"Warning: Failed to archive test folder {test.foldername}. It may need manual cleanup. The test will still be deleted from the database.", "warning")
        except Exception as e: # Catch any other exception during move
            log_error(f"An unexpected error occurred while archiving {test.foldername}: {e}", exc_info=True)
            flash(f"Warning: An unexpected error occurred while archiving test folder {test.foldername}. The test will still be deleted.", "warning")
    else:
        log_warn(f"Test folder {test.foldername} not found for archiving. Proceeding with DB deletion.")

    try:
        db.session.delete(test)
        db.session.commit()
        log_info(f"Successfully deleted test {test.test_id} from database.")
        flash('Test deleted successfully. Associated folder has been archived (if found and possible).', 'success')
    except Exception as e:
        log_error(f"Error deleting test {test.test_id} from database: {e}", exc_info=True)
        db.session.rollback()
        flash('Error deleting test from database. Please check logs.', 'danger')

    return redirect(url_for('admin_tests'))
    return redirect(url_for('admin_tests'))


## Student Routes ##
@app.route('/student/tests')
@login_required
def student_tests():
    if current_user.role != 'student':
        abort(403)
    tests = Test.query.order_by(Test.created_at.desc()).all()
    return render_template('student_tests.html', tests=tests)

@app.route('/student/results')
@login_required
def student_results():
    if current_user.role != 'student':
        abort(403)
    return render_template('student_results.html')

@app.route('/student/test/<test_id>/start', methods=['GET'])
@login_required
def student_start_test(test_id):
    if current_user.role != 'student':
        abort(403)
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    file_path = get_question_file_path(test.foldername, test.filename)

    if not file_path:
        log_error(f"Question file not found for test ID {test.test_id} in folder {test.foldername}")
        flash(f'Error loading test: Question file not found for test {test.test_id}.', 'danger')
        return redirect(url_for('student_tests'))

    log_debug(f"Found question file at: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        questions = parse_markdown_questions(content)
        
        # Store questions in session for the test
        session['test_questions'] = questions
        session['test_id'] = test_id
        
        return render_template('student_test_start.html', 
                             test=test, 
                             questions=questions,
                             time_limit=test.time_limit)
    except Exception as e:
        flash(f'Error loading test: {str(e)}', 'error')
        log_error(f"Error loading test: {str(e)}")
        return redirect(url_for('student_tests'))

@app.route('/student/test/<test_id>/jee', methods=['GET', 'POST'])
@login_required
def student_jee_test(test_id):
    if current_user.role != 'student':
        abort(403)
        
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    # Get questions from session or load from file
    if 'test_questions' not in session or session.get('test_id') != test_id:
        file_path = get_question_file_path(test.foldername, test.filename)
        if not file_path:
            log_error(f"Question file not found for test ID {test.test_id} in folder {test.foldername} (student_jee_test).")
            flash(f'Error loading test: Question file not found for test {test.test_id}.', 'danger')
            return redirect(url_for('student_tests'))
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            questions = parse_markdown_questions(content)
            session['test_questions'] = questions
            session['test_id'] = test_id
            log_debug(f"Loaded questions from file for test {test_id}")
        except Exception as e:
            log_error(f"Error loading test questions from file '{file_path}': {str(e)}")
            flash(f'Error loading test: {str(e)}', 'danger')
            return redirect(url_for('student_tests'))
    else:
        questions = session['test_questions']
        log_debug(f"Loaded questions from session for test {test_id}")
    
    num_questions = len(questions)
    
    # Initialize test state if not exists or if it's a different test
    if 'test_state' not in session or session.get('test_state', {}).get('test_id') != test_id:
        session['test_state'] = {
            'test_id': test_id,
            'current': 0,
            'answers': [None] * num_questions,
            'review': [False] * num_questions,
            'visited': [False] * num_questions,
            'start_time': int(datetime.utcnow().timestamp()),
            'time_limit': test.time_limit * 60  # Convert minutes to seconds
        }
    
    state = session['test_state']
    
    # Handle form submission
    if request.method == 'POST':
        action = request.form.get('action')
        q_idx = int(request.form.get('q_idx', 0))
        selected = request.form.get('selected')
        
        # Save answer if selected
        if selected is not None:
            state['answers'][q_idx] = selected
        
        state['visited'][q_idx] = True
        
        # Handle different actions
        if action == 'mark_review':
            state['review'][q_idx] = True
        elif action == 'save_next':
            state['review'][q_idx] = False
            if q_idx < num_questions - 1:
                state['current'] = q_idx + 1
        elif action == 'clear':
            state['answers'][q_idx] = None
            state['review'][q_idx] = False
        elif action == 'goto':
            goto_idx = int(request.form.get('goto_idx', q_idx))
            if 0 <= goto_idx < num_questions:
                state['current'] = goto_idx
        elif action == 'submit':
            # Calculate score
            score = 0
            for i, q in enumerate(questions):
                if state['answers'][i] and q['correct_option'] == state['answers'][i]:
                    score += 1
            
            # Save results to database
            try:
                student_response = StudentResponse(
                    student_id=current_user.id,
                    test_id=test.id,
                    score=score,
                    total_questions=num_questions,
                    time_taken=int(datetime.utcnow().timestamp()) - state['start_time']
                )
                db.session.add(student_response)
                db.session.commit()
                
                # Clear test state
                session.pop('test_state', None)
                session.pop('test_questions', None)
                
                flash(f'Test submitted! Your score: {score}/{num_questions}', 'success')
                return redirect(url_for('student_test_result', test_id=test.id, response_id=student_response.id))
            except Exception as e:
                db.session.rollback()
                flash('Error saving your test results. Please try again.', 'error')
        
        # Save updated state
        session['test_state'] = state
    
    # Calculate remaining time
    elapsed = int(datetime.utcnow().timestamp()) - state['start_time']
    remaining = max(0, state['time_limit'] - elapsed)
    
    # If time's up, auto-submit
    if remaining <= 0:
        flash('Time\'s up! Your test has been auto-submitted.', 'warning')
        return redirect(url_for('student_tests'))
    
    q_idx = state['current']
    
    return render_template(
        'student_jee_test.html', 
        test=test, 
        questions=questions, 
        q_idx=q_idx, 
        state=state,
        remaining_time=remaining,
        enumerate=enumerate, 
        len=len
    )

@app.route('/student/test/<int:test_id>/result/<int:response_id>')
@login_required
def student_test_result(test_id, response_id):
    if current_user.role != 'student' or (current_user.role == 'student' and current_user.id != StudentResponse.query.get(response_id).student_id):
        abort(403)
    
    response = StudentResponse.query.get_or_404(response_id)
    test = Test.query.get_or_404(test_id)
    
    # Get questions from the test file
    questions = []
    file_path = get_question_file_path(test.foldername, test.filename)
    
    if file_path:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            questions = parse_markdown_questions(content)
        except Exception as e:
            log_error(f"Error loading questions from file '{file_path}' for test result: {e}")
            # Not flashing here as it's a results page, but logging the error.
            # The page will show "no questions" or an empty list.
    else:
        log_error(f"Question file not found for test ID {test.id} in folder {test.foldername} (student_test_result).")
        # questions list remains empty

    # Format time taken
    time_taken = str(timedelta(seconds=response.time_taken))
    
    return render_template('student_test_result.html', 
                         test=test, 
                         response=response,
                         questions=questions,
                         time_taken=time_taken,
                         percentage=round((response.score / response.total_questions) * 100, 2))

def create_app():
    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Configure logging
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('app.log')
        ]
    )
    
    # Log configuration
    app.logger.info('Application startup')
    app.logger.info(f'Database URI: {app.config["SQLALCHEMY_DATABASE_URI"]}')
    app.logger.info(f'Upload folder: {os.path.abspath(app.config["UPLOAD_FOLDER"])}')
    
    return app



if __name__ == '__main__':
    # The db.create_all() call has been removed from here.
    # Database initialization should be handled by Flask-Migrate (flask db upgrade)
    # or by running the init_db.py script.
    
    try:
        # app = create_app() # create_app() is already called before this block
        app.run(debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        # Use the already configured app.logger if available, otherwise default to log_error
        if hasattr(app, 'logger') and app.logger:
            app.logger.error(f'Error starting application: {str(e)}', exc_info=True)
        else:
            log_error(f'Error starting application: {str(e)}', exc_info=True)
        raise