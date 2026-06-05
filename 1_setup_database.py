import sqlite3
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
os.makedirs('data', exist_ok=True) # To make sure the data folder exists

# The cloud Embedding
class NvidiaEmbeddingFunction(EmbeddingFunction):
    def __init__(self):
        self.client = OpenAI(
            base_url = "https://integrate.api.nvidia.com/v1",
            api_key = os.getenv("NVIDIA_API_KEY")
        )
    def __call__(self, input: Documents) -> Embeddings:
        # Sending the raw text to NVIDIA's embedding model
        response = self.client.embeddings.create(
            model="nvidia/nv-embed-v1",
            input=input,
            encoding_format="float"
        )
        return [r.embedding for r in response.data]

nvidia_ef = NvidiaEmbeddingFunction()

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

if os.getenv("RESET_DB") == "true":
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

documents = []
ids = []
metadatas = []

for r in rules:
    documents.append(r["text"])
    ids.append(r["id"])
    
    # everything else goes into metadata
    metadata = {
        "type": r["type"],
        "severity": r["severity"],
        "priority": r["priority"],
        "category": r["category"],
        "action": r["action"]
    }
    metadatas.append(metadata)

collection.add(
    documents=documents,
    ids=ids,
    metadatas=metadatas
)

print("\nSuccess! Both databases are built and saved in the /data folder.")