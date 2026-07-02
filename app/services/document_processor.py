import os
import json
import logging
import re
from datetime import datetime
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity 
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
#Deduplication and clustering logic
SEVERITY_RANK = {"critical":0, "high":1, "medium":2, "low":3}

def get_legal_embedding(rule):
    """Embeds ONLY the legal core to find semantic overlaps."""
    text = f"{rule.get('explanation', '')} {rule.get('rule', '')} {' '.join(rule.get('violation_patterns', []))}"
    # Using nvidia_ef to get the embedding vector directly
    return nvidia_ef([text])[0]

def cluster_and_prioritize_rules(rules):
    logger.info("Initializing Offline Semantic Deduplication Matrix")

    # 1. Generate Embeddings
    embeddings = [get_legal_embedding(r) for r in rules]
    sim_matrix = cosine_similarity(embeddings)
    
    # 2. Cluster over 0.88 Threshold
    THRESHOLD = 0.835 # I have updated after a analysis through check_threshold.py script to find the optmial value that seperates from false positives
    cluster_counter = 0

    for i in range(len(rules)):
        for j in range(i + 1, len(rules)):
            if sim_matrix[i][j] > THRESHOLD:
                ci = rules[i].get('cluster_id')
                cj = rules[j].get('cluster_id')

                if ci and cj and ci != cj:
                    # Merge logic (simplify by pushing to lower ID)
                    for r in rules:
                        if r.get('cluster_id') == cj:
                            r['cluster_id'] = ci
                elif ci:
                    rules[j]['cluster_id'] = ci
                elif cj:
                    rules[i]['cluster_id'] = cj
                else:
                    cid = f"cluster_{cluster_counter:03d}"
                    cluster_counter += 1
                    rules[i]['cluster_id'] = cid
                    rules[j]['cluster_id'] = cid

    # 3. Assign Priority Within Clusters
    cluster_groups = {}
    for rule in rules:
        cid = rule.get('cluster_id')
        if cid:
            if cid not in cluster_groups:
                cluster_groups[cid] = []
            cluster_groups[cid].append(rule)
        else:
            # Standalone rule
            rule['priority'] = 1
            rule['superseded_by'] = ""

    for cid, cluster_rules in cluster_groups.items():
        # Sort by: Specificity (anchors count), then Severity, then Section Num
        def sort_key(r):
            specificity = -len(r.get('scenario_anchors', []))
            sev = SEVERITY_RANK.get(r.get('severity', 'medium'), 2)
            try:
                section_num = int(re.sub(r'\D', '', r.get('mapped_sections', ['0'])[0]))
            except ValueError:
                section_num = 999
            return (specificity, sev, section_num)

        sorted_rules = sorted(cluster_rules, key=sort_key)
        
        for i, r in enumerate(sorted_rules):
            r['priority'] = i + 1
            if i > 0:
                r['superseded_by'] = sorted_rules[0]['id']
            else:
                r['superseded_by'] = ""
                
    logger.info(f"Clustered {len(rules)} rules into {cluster_counter} semantic groups.")
    return rules

#Main Ingestion

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

    # Apply Offline Clustering
    rules_data = cluster_and_prioritize_rules(rules_data)
    
    def build_embedding_text(rule: dict) -> str:
        parts = []

        parts.append(rule.get("explanation", ""))

        vp = rule.get("violation_patterns", [])
        if vp:
            parts.append("Violation patterns: " + " | ".join(vp[:5]))
        
        sa = rule.get("scenario_anchors", [])
        if sa:
            parts.append("Real-world examples: " + " | ".join(sa[:6]))
        
        return " ".join(parts)

    rule_texts = [build_embedding_text(rule) for rule in rules_data]

    rule_ids = [rule["id"] for rule in rules_data]
    rule_metadatas = []

    for rule in rules_data:
        flat_key_terms = " ".join([f"{pair[0]} {pair[1]}" for pair in rule.get("key_terms", [])]) #flattening as ChromaDB metadata does not accept Python arrays

        rule_metadatas.append({
            "severity": rule.get("severity", "medium"),
            "type": rule.get("type", "compliance_rule"),
            "mapped_sections": ",".join(rule.get("mapped_sections", [])),
            "sub_section_citation": rule.get("sub_section_citation", ""),
            "cluster_id": rule.get("cluster_id", ""),
            "priority": rule.get("priority", 1),
            "superseded_by": rule.get("superseded_by", ""),
            
            #FLATTENED ARRAYS FOR CHROMADB
            "scenario_anchors_text": " || ".join(rule.get("scenario_anchors", [])),
            "bm25_key_terms": flat_key_terms,
            "negative_anchors_text": " || ".join(rule.get("negative_anchors", [])),
            "violation_patterns_text": " || ".join(rule.get("violation_patterns", [])),
            
            #THE EXACT LAW
            "formal_rule": rule.get("rule", "")
        })

    collection_b.add(documents=rule_texts, metadatas=rule_metadatas, ids=rule_ids)
    logger.info(f"Collection B Built: {len(rules_data)} optimized compliance rules clustered and ingested.")
    logger.info(f"\n{'='*50}\nDUAL-INDEX INGESTION COMPLETE\n{'='*50}")

if __name__ == "__main__":
    ingest_dual_index_architecture()