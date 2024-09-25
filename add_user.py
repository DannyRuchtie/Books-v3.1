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

def create_user(username: str, email: str, full_name: str, password: str):
    db = SessionLocal()
    hashed_password = pwd_context.hash(password)
    db_user = User(username=username, email=email, full_name=full_name, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    db.close()
    print(f"User {username} created successfully.")

if __name__ == "__main__":
    username = input("Enter username: ")
    email = input("Enter email: ")
    full_name = input("Enter full name: ")
    password = input("Enter password: ")
    create_user(username, email, full_name, password)