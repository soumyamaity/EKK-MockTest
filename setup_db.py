from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    # Drop all existing tables
    db.drop_all()
    
    # Create new tables
    db.create_all()
    
    # Create admin user if not exists
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin'),
            role='admin',
            name='Admin'
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin user created successfully")
    else:
        print("Admin user already exists")

    # Create default student user if not exists
    student = User.query.filter_by(username='student1').first()
    if not student:
        student = User(
            username='student',
            password_hash=generate_password_hash('student'),
            role='student',
            name='Student One'
        )
        db.session.add(student)
        db.session.commit()
        print("Student user created successfully")
    else:
        print("Student user already exists")
