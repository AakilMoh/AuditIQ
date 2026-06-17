import sqlite3
from app.core.config import SQLITE_DB_PATH

print("Connecting to SQLite")
conn = sqlite3.connect(SQLITE_DB_PATH)
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON;")

# Statuses must strictly match: 'Active', 'Settlement negotiated', or 'Pending Legal Action'
eval_debtors = [
    ("ACC-2001", "John Doe", 1200.00, "Active"),
    ("ACC-2002", "Sarah Connor", 850.00, "Active"), # Spelled with an 'h' avoid clashing with the existing 'Sara Connor'
    ("ACC-2003", "Mike Ross", 450.00, "Active"),
    ("ACC-2004", "Emily Blunt", 2200.00, "Active"),
    ("ACC-2005", "David Rose", 900.00, "Active")
]

try:
    # INSERT OR IGNORE keeps your script safe even if you run it multiple times
    cursor.executemany('''
        INSERT OR IGNORE INTO debtors (account_number, name, balance, status) 
        VALUES (?, ?, ?, ?)
    ''', eval_debtors)
    
    conn.commit()
    print("Evaluation profiles successfully injected into your production table!")
    
    # Quick sanity check printout
    cursor.execute("SELECT debtor_id, name, balance, status FROM debtors WHERE account_number LIKE 'ACC-20%'")
    print("\n--- Current Eval Accounts Active ---")
    for row in cursor.fetchall():
        print(f"ID: {row[0]} | Name: {row[1]} | Balance: ${row[2]} | Status: {row[3]}")

except Exception as e:
    print(f"Ingestion Failed: {e}")
finally:
    conn.close()