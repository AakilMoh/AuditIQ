import sqlite3
from app.core.config import SQLITE_DB_PATH

def get_db_connection():
    """Yields a database connection and ensures it closes after the request."""
    conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()