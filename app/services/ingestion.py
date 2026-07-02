import sqlite3
import chromadb
import os
import hashlib
import secrets
import logging
from datetime import datetime
from app.core.config import SQLITE_DB_PATH, CHROMA_DB_PATH, nvidia_ef

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("ingestion")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(f"logs/ingestion_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [Ingestion] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[Ingestion] %(message)s'))

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
# ---------------------------------------------------------

# Hashing Password
def hash_password(password: str) -> str:
    """Generates a secure, salted SHA-256 hash string using PBKDF2."""
    salt = secrets.token_bytes(16) # random salt which is cryptographically secured
    iterations = 100000 # to prevent brute-force attacks

    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)

    return f"{salt.hex()}.{dk.hex()}"


logger.info("1. Initializng SQLite Database")
conn = sqlite3.connect(SQLITE_DB_PATH)
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON;")

# creating QA Auditors Table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS auditors (
        auditor_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, -- STORE THE ENCRYPTED STRING ONLY
        role TEXT NOT NULL DEFAULT 'QA_Reviewer'
    )
''')

# The Agents Table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS agents(
        agent_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department TEXT NOT NULL
    )
''')

# The Debtors Table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS debtors(
        debtor_id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        balance REAL NOT NULL CHECK(balance>=0),
        status TEXT NOT NULL CHECK(status IN ('Active', 'Settlement negotiated', 'Pending Legal Action'))
    )
''')

# Master Call Logs table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS call_logs(
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        debtor_id INTEGER NOT NULL,
        agent_id INTEGER NOT NULL,
        auditor_id INTEGER NOT NULL,

        cloud_audio_uri TEXT UNIQUE,
        transcript TEXT NOT NULL,
        llm_prompt TEXT,

        compliance_passed BOOLEAN NOT NULL CHECK(compliance_passed IN (0,1)),
        ai_performance_score INTEGER NOT NULL CHECK(ai_performance_score BETWEEN 1 AND 10),
        reasoning TEXT,

        violations TEXT,
        verification_notes TEXT,
        retrieved_rules TEXT,
        sql_facts TEXT,

        human_override_score INTEGER CHECK(human_override_score BETWEEN 1 AND 10),

        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (debtor_id) REFERENCES debtors(debtor_id) ON DELETE CASCADE,
        FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE,
        FOREIGN KEY (auditor_id) REFERENCES auditors(auditor_id) ON DELETE CASCADE
    )
''')

if os.getenv("RESET_DB") == "true":
    logger.info("[Reset] Purging existing tables...")
    cursor.execute("DELETE FROM call_logs") # Clear previous logs
    cursor.execute("DELETE FROM debtors")  # Clear previous debtors
    cursor.execute("DELETE FROM agents") # Clear previous agents
    cursor.execute("DELETE FROM auditors")  # Clear previous auditors

# Seeding Auditors with hashed passwords
seed_auditors = [
    ("qa_manager_01", hash_password("SecureManager2026!"), "Admin"),
    ("qa_reviewer02", hash_password("ReviewerPass321!"), "QA_Reviewer")
]
cursor.executemany('INSERT OR IGNORE INTO auditors (username, password_hash, role) VALUES (?, ?, ?)', seed_auditors)

cursor.executemany('INSERT OR IGNORE INTO agents (name, department) VALUES (?, ?)', 
                   [("Agent Michael", "Collections Tier 1"), ("Agent Sarah", "Legal Escalations")])

# Ingesting existing debtor file accounts
debtors_list = [
    # --- THE ORIGINAL 5 (Mapped to physical audio files) ---
    ("ACC-2001", "John Doe", 1200.00, "Active"),
    ("ACC-2002", "Sarah Connor", 850.00, "Active"), 
    ("ACC-2003", "Mike Ross", 450.00, "Active"),
    ("ACC-2004", "Emily Blunt", 2200.00, "Active"),
    ("ACC-2005", "David Rose", 900.00, "Active"),
    
    # --- THE NEW BATCH (Extended for Testing) ---
    ("ACC-2006", "Arthur Shelby", 1450.00, "Pending Legal Action"),
    ("ACC-2007", "Harvey Specter", 12500.00, "Active"),
    ("ACC-2008", "Walter White", 85000.00, "Active"),
    ("ACC-2009", "Peter Parker", 300.00, "Pending Legal Action"),
    ("ACC-2010", "Olivia Pope", 4200.00, "Pending Legal Action"),
    ("ACC-2011", "Jon Snow", 150.00, "Settlement negotiated"),
    ("ACC-2012", "Arya Stark", 3100.00, "Active"),
    ("ACC-2013", "Thomas Shelby", 5000.00, "Pending Legal Action"),
    ("ACC-2014", "Ellen Ripley", 2200.00, "Settlement negotiated"),
    ("ACC-2015", "James Bond", 10500.00, "Active")
]
cursor.executemany('INSERT OR REPLACE INTO debtors (account_number, name, balance, status) VALUES (?, ?, ?, ?)', debtors_list)

conn.commit()

logger.info("\nSuccess! SQLite database is built and seeded.")