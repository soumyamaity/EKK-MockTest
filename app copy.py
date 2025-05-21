from flask import Flask, render_template, request, redirect, url_for, flash, abort, session, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
import markdown
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import re
import zipfile
import tempfile
import shutil

# Helper function to parse questions from markdown
def parse_markdown_questions(content):
    questions = []
    # Split by question blocks (assuming questions are separated by ---)
    blocks = re.split(r'\n---+\n', content)
    
    for block in blocks:
        if not block.strip():
            continue
            
        question = {}
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        # Extract question text (lines starting with Q: or first line)
        question_text = []
        options = {}
        correct_option = None
        
        for line in lines:
            if line.lower().startswith('q:'):
                question_text.append(line[2:].strip())
            elif line.lower().startswith(('a:', 'b:', 'c:', 'd:')):
                option = line[0].upper()
                options[option] = line[2:].strip()
            elif line.lower().startswith('answer:'):
                correct_option = line.split(':', 1)[1].strip().upper()
            else:
                question_text.append(line)
        
        if question_text and options and correct_option in options:
            questions.append({
                'text': '\n'.join(question_text),
                'option_a': options.get('A', ''),
                'option_b': options.get('B', ''),
                'option_c': options.get('C', ''),
                'option_d': options.get('D', ''),
                'correct_option': correct_option
            })
    
    return questions

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['UPLOAD_FOLDER'] = 'uploads/questions'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['EXPLAIN_TEMPLATE_LOADING'] = True

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

class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    test_id = db.Column(db.String(50), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    filename = db.Column(db.String(200), nullable=False)  # uploaded Markdown filename
    time_limit = db.Column(db.Integer, default=60)  # Time limit in minutes
    admin = db.relationship('User', backref=db.backref('tests', lazy=True))

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
    student_count = User.query.filter((User.role == 'student')).count()
    test_count = Test.query.count()
    #print(f"[DEBUG] user_count: {user_count}, test_count: {test_count}")
    result_count = 0  # Placeholder, update as needed
    #user_count purposefully kept as, user_count = student_count (do not change)
    return render_template('admin_dashboard.html', user_count=user_count - student_count, test_count=test_count, result_count=result_count)

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    print(f"[DEBUG] User: {getattr(current_user, 'username', None)}, Role: {getattr(current_user, 'role', None)}, Authenticated: {getattr(current_user, 'is_authenticated', None)}")
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    return render_template('student_dashboard.html')


#admin routes #

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
    return render_template('admin_edit_questions.html', test=test)

@app.route('/admin/questions/view/<test_id>')
@login_required
def admin_view_questions(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    # Read and render the markdown file
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], test.test_id, 'questions.md')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        # Convert markdown to HTML
        html_content = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
    except FileNotFoundError:
        html_content = "<div class='alert alert-warning'>No questions found for this test.</div>"
    
    return render_template('admin_view_questions.html', 
                         test=test, 
                         questions=html_content)


@app.route('/admin/test')
@login_required
def redirect_to_tests():
    """Redirect /admin/test to /admin/tests"""
    return redirect(url_for('admin_tests'))

@app.route('/admin/route')
@login_required
def redirect_to_dashboard():
    """Redirect /admin/route to /admin/dashboard"""
    if current_user.role != 'admin':
        abort(403)
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/test')
@login_required
def redirect_to_tests():
    """Redirect /admin/test to /admin/tests"""
    return redirect(url_for('admin_tests'))

@app.route('/admin/route')
@login_required
def redirect_to_dashboard():
    """Re@app.route('/admin/tests/create', methods=['GET', 'POST'])
@login_required
def admin_create_test():
    if current_user.role != 'admin':
        abort(403)
    
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
            # Create base uploads directory if it doesn't exist
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            # Create test-specific directory
            test_dir = os.path.join(app.config['UPLOAD_FOLDER'], test_id)
            
            # Check if test directory already exists
            if os.path.exists(test_dir):
                flash('Test ID already exists.', 'danger')
                return redirect(url_for('admin_create_test'))
                
            os.makedirs(test_dir)
            
            # Save the uploaded file
            filename = secure_filename(file.filename)
            filepath = os.path.join(test_dir, filename)
            file.save(filepath)
            
            md_file = None
            is_zip = filename.endswith('.zip')
            
            # Handle ZIP file
            if is_zip:
                # Extract ZIP contents
                with zipfile.ZipFile(filepath, 'r') as zip_ref:
                    zip_ref.extractall(test_dir)
                
                # Find the first .md file in the extracted contents
                for root, _, files in os.walk(test_dir):
                    for f in files:
                        if f.endswith('.md'):
                            md_file = f
                            break
                    if md_file:
                        break
                
                if not md_file:
                    shutil.rmtree(test_dir)  # Clean up if no MD file found
                    flash('ZIP file must contain at least one .md file.', 'danger')
                    return redirect(url_for('admin_create_test'))
                
                # Remove the original zip file after extraction
                os.remove(filepath)
            else:
                md_file = filename
            
            # Create test record
            test = Test(
                subject=subject, 
                test_id=test_id, 
                created_by=current_user.id, 
                filename=md_file,
                time_limit=time_limit
            )
            db.session.add(test)
            db.session.commit()
            
            flash('Test created and question paper uploaded successfully!', 'success')
            return redirect(url_for('admin_tests'))
            
        except Exception as e:
            # Clean up in case of error
            if 'test_dir' in locals() and os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)
            flash(f'Error processing file: {str(e)}', 'error')
            return redirect(url_for('admin_create_test'))
            
    return render_template('admin_create_test.html')
  flash(f'Error processing file: {str(e)}', 'error')
            return redirect(url_for('admin_create_test'))
            
    return render_template('admin_create_test.html')

@app.route('/admin/tests/delete/<int:test_id>', methods=['POST'])
@login_required
def admin_delete_test(test_id):
    if current_user.role != 'admin':
        abort(403)
    test = Test.query.get_or_404(test_id)
    # Optionally delete the uploaded file
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], test.filename))
    excepes #eption:
        pass
    db.session.delete(test)
    db.session.commit()
    flash('Test deleted.', 'success')
    return redirect(url_for('admin_tests'))



# Student Routes #

@app.route('/student/tests')
@login_required
def student_tests():
    if current_user.role != 'student':
        abort(403)
    tests = Test.query.order_by(Test.created_at.desc()).all()
    return render_template('student_tests.html', tests=tests)

@app.route('/student/test/<test_id>/start', methods=['GET'])
@login_required
def student_start_test(test_id):
    if current_user.role != 'student':
        abort(403)
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    # Read and parse the markdown file
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], test.filename)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        questions = parse_markdown_questions(content)
        
        # Store questions in session for the test
        session['test_questions'] = questions
        session['test_id'] = test_id
        
        return render_template('student_test_start.html', 
                             test=test, 
                             questions=questions,
            zz                 time_limit=test.time_limit)
    except Exception as e:
        flash(f'Error loading test: {str(e)}', 'error')
        return redirect(url_for('student_tests'))

@app.route('/student/test/<test_id>/jee', methods=['GET', 'POST'])
@login_required
def student_jee_test(test_id):
    if current_user.role != 'student':
        abort(403)
        
    test = Test.query.filter_by(test_id=test_id).first_or_404()
    
    # Get questions from session or load from file
    if 'test_questions' not in session or session.get('test_id') != test_id:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], test.filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
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


@app.route('/student/results')
@login_required
def student_results():
    if current_user.role != 'student':
        abort(403)
    return render_template('student_results.html')

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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    try:
        app = create_app()
        app.run(debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        app.logger.error(f'Error starting application: {str(e)}', exc_info=True)
        raise 
        app.run(debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        app.logger.error(f'Error starting application: {str(e)}', exc_info=True)
        raise 