import sqlite3
import chromadb
import os
import hashlib
import secrets
import logging
from datetime import datetime
from core.config import SQLITE_DB_PATH, CHROMA_DB_PATH, nvidia_ef

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
        llm_prompt TEXT NOT NULL,

        compliance_passed BOOLEAN NOT NULL CHECK(compliance_passed IN (0,1)),
        ai_performance_score INTEGER NOT NULL CHECK(ai_performance_score BETWEEN 1 AND 10),
        reasoning TEXT,

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

# Ingesting fake accounts
cursor.executemany('INSERT OR IGNORE INTO debtors (account_number, name, balance, status) VALUES (?, ?, ?, ?)', [
    ("ACC-1001", "Ali Khan", 3200.00, "Active"),
    ("ACC-1002", "Sara Connor", 450.50, "Settlement negotiated"),
    ("ACC-1003", "Jane Smith", 8900.00, "Pending Legal Action"),
])

conn.commit()

logger.info("2. Initializing ChromaDB")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_or_create_collection(
    name="compliance_rules",
    embedding_function=nvidia_ef
)

# Ingesting arbitrary legal policies
rules = [
    {
        "id": "Rule1",
        "text": "Agents are authorized to offer a 20% discount on balances over $1000.",
        "type": "payment_policy",
        "severity": "medium",
        "priority": 2,
        "category": "financial_offer",
        "action": "allow"
    },
    {
        "id": "Rule2",
        "text": "Under FDCPA rules, agents must NOT threaten legal action on accounts marked 'Active'.",
        "type": "legal_constraint",
        "severity": "high",
        "priority": 5,
        "category": "legal_compliance",
        "action": "deny"
    },
    {
        "id": "Rule3",
        "text": "Accounts marked 'Settlement Negotiated' must not be contacted for further payments.",
        "type": "contact_policy",
        "severity": "high",
        "priority": 5,
        "category": "communication_restriction",
        "action": "deny"
    },
    {
        "id": "Rule4",
        "text": "Accounts marked 'Pending Legal Action' may be informed about legal review status but no immediate threats or coercion are allowed.",
        "type": "communication_guideline",
        "severity": "high",
        "priority": 4,
        "category": "legal_status_handling",
        "action": "conditional"
    },
    {
        "id": "Rule5",
        "text": "Agents must not imply legal action unless explicitly authorized in policy.",
        "type": "legal_authorization",
        "severity": "high",
        "priority": 5,
        "category": "legal_compliance",
        "action": "deny"
    },
    {
        "id": "Rule6",
        "text": "Agents are allowed to discuss account balances and payment options for all account statuses.",
        "type": "communication_guideline",
        "severity": "low",
        "priority": 1,
        "category": "general_information",
        "action": "allow"
    }
]

def build_metadata(rule):
    return{
        "type": rule.get("type"),
        "severity": rule.get("severity"),
        "priority": rule.get("priority"),
        "category": rule.get("category"),
        "action": rule.get("action")
    }

try:
    collection.delete(ids=[r["id"] for r in rules])
except Exception:
    pass

collection.add(
    documents=[r["text"] for r in rules],
    ids=[r["id"] for r in rules],
    metadatas=[build_metadata(r) for r in rules]
)

logger.info("\nSuccess! Both databases are built and saved in the /data folder.")