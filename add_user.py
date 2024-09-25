from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, User
from passlib.context import CryptContext

# Database connection
SQLALCHEMY_DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_user(username: str, email: str, full_name: str, password: str, is_admin: bool = False):
    db = SessionLocal()
    hashed_password = pwd_context.hash(password)
    db_user = User(username=username, email=email, full_name=full_name, hashed_password=hashed_password, is_admin=is_admin)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    db.close()
    print(f"User {username} created successfully. Admin status: {is_admin}")

if __name__ == "__main__":
    username = input("Enter username: ")
    email = input("Enter email: ")
    full_name = input("Enter full name: ")
    password = input("Enter password: ")
    is_admin_input = input("Is this user an admin? (y/n): ").lower()
    is_admin = is_admin_input == 'y'
    create_user(username, email, full_name, password, is_admin)