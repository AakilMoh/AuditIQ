import os
import json
import logging
import re
from datetime import datetime
import chromadb
from langchain_community.document_loaders import PyPDFLoader
from app.core.config import CHROMA_DB_PATH, nvidia_ef

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("doc_processor")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(f"logs/doc_processor_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [DocProcessor] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('\n[DocProcessor] %(message)s'))

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
# ---------------------------------------------------------

def ingest_dual_index_architecture():
    pdf_path = "data/fdcpa_rules.pdf"
    json_path = "data/rules_core.json"

    if not os.path.exists(pdf_path) or not os.path.exists(json_path):
        logger.error("Missing data files! Ensure both the PDF and JSON are in the /data folder.")
        return

    logger.info("Initializing ChromaDB Persistent Client")
    chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    # Building the Collection A - Raw Legal Text via Regex

    collection_a_name = "fdcpa_raw_text"

    try:
        chroma_client.delete_collection(name=collection_a_name)
        logger.info(f"Purged old '{collection_a_name}' collection.")
    except Exception:
        pass

    collection_a = chroma_client.get_or_create_collection(
        name=collection_a_name,
        embedding_function=nvidia_ef
    )

    logger.info("Loading Federal PDF via LangChain")
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    #combining all pages into one massive string
    full_text = "\n".join([doc.page_content for doc in documents])

    # CUSTOM LEGAL PARSER: Split on section headers (eg: § 805)
    # The (?=...) lookahead ensures the section symbol stays with the chunk
    logger.info("Parsing legally by FDCPA Section headers")
    raw_sections = re.split(r"(?=§\s*8\d{2}\.)", full_text)

    legal_chunks = []
    for section_text in raw_sections:
        section_text = section_text.strip()
        if not section_text:
            continue
        
        #Extracting the exact section number
        match = re.search(r"§\s*(8\d{2})\.", section_text)
        if match:
            section_num = match.group(1)
            legal_chunks.append({
                "id": f"FDCPA_{section_num}",
                "content": section_text,
                "metadata": {
                    "source": "FDCPA",
                    "section": section_num,
                    "type": "legal_text"
                }
            })

    #Embed and storing Collection A
    collection_a.add(
        documents=[chunk["content"] for chunk in legal_chunks],
        metadatas=[chunk["metadata"] for chunk in legal_chunks],
        ids=[chunk["id"] for chunk in legal_chunks]
    )
    logger.info(f"Collection A Built: {len(legal_chunks)} exact legal sections mapped.")

    # Building the Collection B - Normalized Compliance Rules
    collection_b_name = "fdcpa_compliance_rules"

    try:
        chroma_client.delete_collection(name=collection_b_name)
        logger.info(f"Purged old '{collection_b_name}' collection.")
    except Exception:
        pass

    collection_b = chroma_client.get_or_create_collection(
        name=collection_b_name,
        embedding_function=nvidia_ef
    )

    logger.info("Loading Curated rules_core JSON file")
    with open(json_path, "r", encoding="utf-8") as file:
        rules_data = json.load(file)
    
    rule_texts = [rule["rule"] for rule in rules_data]
    rule_ids = [rule["id"] for rule in rules_data]

    # We convert the list of mapped sections into a comma-separated string 
    # because ChromaDB metadata doesn't accept Python lists.

    rule_metadatas = [
        {
            "severity": rule["severity"],
            "type": rule["type"],
            "mapped_sections": ",".join(rule["mapped_sections"]),
            "sub_section_citation": rule.get("sub_section_citation", ""),
            "explanation": rule.get("explanation", "") 
        } 
        for rule in rules_data
    ]

    collection_b.add(documents=rule_texts, metadatas=rule_metadatas, ids=rule_ids)
    logger.info(f"Collection B Built: {len(rules_data)} optimized compliance rules done.")

    logger.info(f"\n{'='*50}\nDUAL-INDEX INGESTION COMPLETE\n{'='*50}")

if __name__ == "__main__":
    ingest_dual_index_architecture()