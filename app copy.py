from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_from_directory, jsonify, current_app
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
from debug_utils import log_exceptions, log_info, log_error, log_debug
import pymdownx

# Helper function to parse questions from markdown
def parse_markdown_questions(content):

    html = markdown.markdown(content, extensions=['markdown.extensions.tables', 'markdown.extensions.extra', 'pymdownx.extra', 'pymdownx.tasklist', 'pymdownx.arithmatex'], extension_configs={'pymdownx.arithmatex': {'generic': True}})
    soup = BeautifulSoup(html, 'html.parser')

    # Split questions using <hr> tags
    questions_html = []
    current_question = []

    for elem in soup.contents:
        if elem.name == 'hr':
            if current_question:
                questions_html.append(current_question)
                current_question = []
        else:
            current_question.append(elem)

    # Add the last question
    if current_question:
        questions_html.append(current_question)

    # Parse each question block
    questions = []

    for q_html in questions_html:
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
        option_idx = 0

        for tag in q_html:
            if tag.name == 'h1':
                continue  # Ignore the heading (Question number)
            elif tag.name == 'p':
                text = tag.get_text().strip()
                if text.lower().startswith('explanation:'):
                    question_dict['explanation'] = text[len('explanation:'):].strip()
                else:
                    question_dict['text'] += text + "\n"
            elif tag.name == 'ul':
                for li in tag.find_all('li'):
                    opt_text = li.get_text().strip()
                    if li.text.startswith('[x]'):
                        question_dict['correct_option'] = options_labels[option_idx]
                        opt_text = opt_text.replace('[x]', '').strip()
                    else:
                        opt_text = opt_text.replace('[ ]', '').strip()

                    key = f'option_{options_labels[option_idx].lower()}'
                    question_dict[key] = opt_text
                    option_idx += 1

        question_dict['text'] = question_dict['text'].strip()
        questions.append(question_dict)
    print(questions)
    return questions


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
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Try to find user by username or email
        user = User.query.filter((User.username == username) | (User.email == username)).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username/email or password.', 'danger')
    return render_template('login.html')

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
    print(f"[DEBUG] user_count: {user_count}, test_count: {test_count}")
    result_count = 0  # Placeholder, update as needed
    return render_template('admin_dashboard.html', user_count=user_count, student_count=student_count, test_count=test_count, result_count=result_count)

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    print(f"[DEBUG] User: {getattr(current_user, 'username', None)}, Role: {getattr(current_user, 'role', None)}, Authenticated: {getattr(current_user, 'is_authenticated', None)}")
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
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
    
    # Find the questions file
    file_path = None
    for dirpath, dirnames, filenames in os.walk(test.foldername):
        if test.filename in filenames:
            file_path = os.path.join(dirpath, test.filename)
            break
    
    questions = ""
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                questions = f.read()
        except Exception as e:
            print(f"Error reading questions file: {e}")
    
    return render_template('admin_edit_questions.html', test=test, questions=questions)

@app.route('/admin/questions/view/<test_id>')
@login_required
def admin_view_questions(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    # Use the direct path to the markdown file
    for dirpath, dirnames, filenames in os.walk(test.foldername):
        if test.filename in filenames:
            file_path = os.path.join(dirpath, test.filename)
            upload_dir = dirpath

    if not file_path:
        print(f"'{test.filename}' not found in '{test.foldername}' or its subfolders.")
    
    # Debug information
    print(f"Looking for file at: {file_path}")
    print(f"Upload directory exists: {os.path.exists(upload_dir)}")
    print(f"File exists: {os.path.exists(file_path)}")
    print(f"Files in directory: {os.listdir(upload_dir) if os.path.exists(upload_dir) else 'Directory not found'}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_markdown = f.read()
            html_content = markdown.markdown(raw_markdown, extensions=['markdown.extensions.tables', 'markdown.extensions.extra', 'pymdownx.extra', 'pymdownx.tasklist', 'pymdownx.arithmatex'], extension_configs={'pymdownx.arithmatex': {'generic': True}})
            
            print("Successfully converted markdown to HTML")
            return render_template('admin_view_questions.html', 
                               test=test, 
                               questions=html_content,
                               raw_markdown=raw_markdown)
            
    except FileNotFoundError:
        error_msg = f"No questions found for this test. Expected file at: {file_path}"
        print(f"File not found: {file_path}")
        return render_template('admin_view_questions.html', 
                           test=test,
                           error=error_msg)
    except Exception as e:
        error_msg = f"Error reading questions: {str(e)}"
        print(error_msg)
        return render_template('admin_view_questions.html',
                           test=test,
                           error=error_msg)
        print(f"Error: {str(e)}")
    
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
    print(f"Current user: {current_user}")
    print(f"Current user ID: {current_user.id if current_user.is_authenticated else 'Not authenticated'}")
    
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
        
        try:
            # Create test directory inside UPLOAD_FOLDER
            test_dir = os.path.join(app.config['UPLOAD_FOLDER'], test_id)
            
            # Check if test directory already exists
            if os.path.exists(test_dir):
                flash(f'A test with ID {test_id} already exists.', 'danger')
                return redirect(url_for('admin_create_test'))
                
            # Create the test directory
            os.makedirs(test_dir, exist_ok=True)
            
            if file.filename.endswith('.md'):
                # Handle MD file upload
                filename = secure_filename(file.filename)
                filepath = os.path.join(test_dir, 'questions.md')
                file.save(filepath)
                
            elif file.filename.endswith('.zip'):
                # Save the zip file temporarily
                temp_zip = os.path.join(test_dir, 'temp.zip')
                file.save(temp_zip)
                
                # Extract the zip file
                with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                    zip_ref.extractall(test_dir)
                
                # Remove the zip file
                os.remove(temp_zip)
                
                # Search for .md files recursively in the extracted contents
                md_files = []
                for root, _, files in os.walk(test_dir):
                    for file in files:
                        if file.lower().endswith('.md'):
                            md_files.append(os.path.join(root, file))
                
                if len(md_files) < 1:
                    shutil.rmtree(test_dir)  # Clean up
                    flash('There is no MD file in the zip folder', 'danger')
                    return redirect(url_for('admin_create_test'))
                elif len(md_files) > 1:
                    shutil.rmtree(test_dir)  # Clean up
                    flash('There are multiple MD files in the zip folder', 'danger')
                    return redirect(url_for('admin_create_test'))

                # Get the path of the markdown file
                md_file_path = md_files[0]
                
                # If the markdown file is not already named questions.md
                if os.path.basename(md_file_path).lower() != 'questions.md':
                    # Check if questions.md already exists (shouldn't happen due to previous check)
                    questions_md_path = os.path.join(test_dir, 'questions.md')
                    if os.path.exists(questions_md_path):
                        os.remove(questions_md_path)
                    # Rename the markdown file to questions.md
                    os.rename(md_file_path, questions_md_path)
                
            # Debug information
            print(f"Current user: {current_user}")
            print(f"Current user ID: {current_user.id}")
            print(f"Is authenticated: {current_user.is_authenticated}")
            
            # Create new test in database
            test = Test(
                test_id=test_id,
                subject=subject,
                foldername= test_dir,
                filename= 'questions.md',   # All tests will have questions.md in their directory
                time_limit=time_limit,
                created_at=datetime.utcnow(),
                created_by=current_user.id  # Use the current user's ID
            )
            
            # Debug the test object before committing
            print(f"Test object before commit: {test}")
            print(f"Test created_by before commit: {test.created_by}")
            db.session.add(test)
            db.session.commit()
            
            flash('Test created successfully!', 'success')
            return redirect(url_for('admin_tests'))
            
        except Exception as e:
            # Clean up test directory if it was created
            if 'test_dir' in locals() and os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)
            if 'test' in locals():
                db.session.rollback()
            flash(f'An error occurred: {str(e)}', 'danger')
            return redirect(url_for('admin_create_test'))
            
    return render_template('admin_create_test.html')

@app.route('/admin/tests/delete/<int:test_id>', methods=['POST'])
@login_required
@log_exceptions
def admin_delete_test(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.get_or_404(test_id)
    # Optionally delete the uploaded file
    try:
        archive_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'archive')
        if not os.path.exists(archive_folder):
            os.makedirs(archive_folder)
        shutil.move(test.foldername, archive_folder)
    except Exception:
        pass
    db.session.delete(test)
    db.session.commit()
    flash('Test deleted.', 'success')
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
    
    # Read and parse the markdown file
    for dirpath, dirnames, filenames in os.walk(test.foldername):
        if test.filename in filenames:
            file_path = os.path.join(dirpath, test.filename)
            upload_dir = dirpath

    print(f"directory path = {dirpath}")
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
        print(f"Error loading test: {str(e)}")
        return redirect(url_for('student_tests'))

@app.route('/student/test/<test_id>/jee', methods=['GET', 'POST'])
@login_required
def student_jee_test(test_id):
    if current_user.role != 'student':
        abort(403)
        
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    # Get questions from session or load from file
    if 'test_questions' not in session or session.get('test_id') != test_id:
        for dirpath, dirnames, filenames in os.walk(test.foldername):
            if test.filename in filenames:
                file_path = os.path.join(dirpath, test.filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            questions = parse_markdown_questions(content)
            session['test_questions'] = questions
            session['test_id'] = test_id
        except Exception as e:
            flash(f'Error loading test: {str(e)}', 'error')
            return redirect(url_for('student_tests'))
    else:
        questions = session['test_questions']
    
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
    
    # Format time taken
    time_taken = str(timedelta(seconds=response.time_taken))
    
    return render_template('student_test_result.html', 
                         test=test, 
                         response=response,
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
    with app.app_context():
        db.create_all()
    
    try:
        app = create_app()
        app.run(debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        app.logger.error(f'Error starting application: {str(e)}', exc_info=True)
        raise 