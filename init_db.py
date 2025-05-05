from app import app, db
from models import User, UnfilteredPost, Mood, Poll, Comment, Notification, InviteCode

def init_db():
    with app.app_context():
        try:
            # Drop all tables
            db.drop_all()
            print("Dropped all tables successfully")
            
            # Create all tables
            db.create_all()
            print("Created all tables successfully")
            
            # Create a test user
            test_user = User(
                username='test_user',
                email='test@example.com'
            )
            test_user.set_password('password123')
            db.session.add(test_user)
            db.session.commit()
            print("Created test user successfully")
            
        except Exception as e:
            print(f"Error initializing database: {str(e)}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    init_db()
    print("Database initialization completed!") 