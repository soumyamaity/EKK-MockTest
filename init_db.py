from app import db, app, User, Test

def init_db():
    with app.app_context():
        db.create_all()
        # Create initial admin user if not exists
        admin = User.query.filter_by(email='admin').first()
        if not admin:
            admin = User(email='admin', name='Admin', role='admin')
            admin.set_password('admin, Password')
            db.session.add(admin)
            db.session.commit()
        print("Database tables created and initial admin user set.")

if __name__ == "__main__":
    init_db() 