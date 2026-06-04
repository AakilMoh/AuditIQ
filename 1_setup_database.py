import sqlite3
import chromadb
import os

os.makedirs('data', exist_ok=True) # To make sure the data folder exists
print("1. Initializng SQLite Database")
conn = sqlite3.connect('data/collectiq.sqlite')
cursor = conn.cursor()

#Creating the schema
cursor.execute('''CREATE TABLE IF NOT EXISTS debtors (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    balance REAL,
    status TEXT
)''')
cursor.execute("DELETE FROM debtors")  # Clear previous runs

# Ingesting fake accounts
cursor.executemany('''INSERT INTO debtors (name, balance, status) VALUES (?, ?, ?)''', [
    ("Ali Khan", 3200.00, "Active"),
    ("Sara Connor", 450.50, "Settlement negotiated"),
    ("Jane Smith", 8900.00, "Pending Legal Action"),
])
conn.commit()

print("2. Initializing ChromaDB")
chroma_client = chromadb.PersistentClient(path="data/chromadb")
collection = chroma_client.get_or_create_collection(name="compliance_rules")

# Ingesting arbitrary legal policies
rules = [
    "Agents are authorized to offer a 20% discount on balances over $1000.",
    "Under FDCPA rules, agents cannot threaten legal action on accounts marked 'Active'.",
    "Accounts marked 'Settlement Negotiated' cannot be contacted for further payments."
]

collection.add(
    documents=rules,
    ids=["rule1", "rule2", "rule3"],
    metadatas=[{"source": "policy_manual"} for _ in rules]
)

print("\nSuccess! Both databases are built and saved in the /data folder.")