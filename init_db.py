from app import app, db, User
from werkzeug.security import generate_password_hash

def init_db():
    with app.app_context():
        # Create all tables if they don't exist
        db.create_all()
        
        # Check if admin user already exists
        admin = User.query.filter_by(username='admin').first()
        
        if not admin:
            # Create admin user if it doesn't exist
            admin = User(
                username='admin',
                email='admin@example.com',
                password_hash=generate_password_hash('admin123'),
                role='admin',
                name='Admin User'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created with username: admin, password: admin123")
        else:
            print("Admin user already exists. No changes made.")
        
        print("Database initialization complete!")

if __name__ == '__main__':
    init_db()
