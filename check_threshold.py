import os
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import chromadb
from app.core.config import CHROMA_DB_PATH

def analyze_chroma_similarities():
    print("🔍 Connecting to ChromaDB Vault...")
    
    # 1. Connect to the DB
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    
    try:
        collection = client.get_collection(name="fdcpa_compliance_rules")
    except Exception as e:
        print(f"❌ Collection not found: {e}")
        return

    print("📦 Fetching embeddings and metadata from Collection B...")
    
    # 2. Pull all rules, including the raw mathematical embeddings Chroma created
    data = collection.get(include=["documents", "metadatas", "embeddings"])
    
    docs = data["documents"]
    ids = data["ids"]
    embeddings = data["embeddings"]
    
    if embeddings is None or len(embeddings) == 0:
        print("⚠️ No embeddings found in the database. Ensure nvidia_ef embedded them properly.")
        return
        
    print(f"✅ Fetched {len(docs)} rules. Calculating the Cosine Similarity Matrix...")
    
    # 3. Calculate mathematical overlap between every single rule
    sim_matrix = cosine_similarity(embeddings)
    
    # 4. Extract pairs (excluding comparing a rule to itself)
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            score = sim_matrix[i][j]
            pairs.append({
                "score": score,
                "id_a": ids[i],
                "id_b": ids[j],
                "text_a": docs[i][:100].replace('\n', ' '), # Just grab the first 100 chars
                "text_b": docs[j][:100].replace('\n', ' ')
            })
            
    # 5. Sort by highest similarity
    pairs.sort(key=lambda x: x["score"], reverse=True)
    
    print("\n" + "="*90)
    print("🏆 TOP 15 MOST SIMILAR RULE PAIRS IN YOUR DATABASE")
    print("="*90)
    
    for i, pair in enumerate(pairs[:15], 1):
        print(f"Rank #{i} | Similarity Score: {pair['score']:.4f}")
        print(f"  [Rule A] {pair['id_a']:<35} -> {pair['text_a']}...")
        print(f"  [Rule B] {pair['id_b']:<35} -> {pair['text_b']}...")
        print("-" * 90)
        
    # 6. Print statistical distribution to help pick the threshold
    scores = [p["score"] for p in pairs]
    print("\n📈 OVERALL SCORE DISTRIBUTION:")
    print(f"Absolute Max Similarity (Excluding 100% duplicates): {np.max(scores):.4f}")
    print(f"Top 1% of pairs score above:  {np.percentile(scores, 99):.4f}")
    print(f"Top 5% of pairs score above:  {np.percentile(scores, 95):.4f}")
    print(f"Average Similarity overall:   {np.mean(scores):.4f}")
    print("="*90)

if __name__ == "__main__":
    analyze_chroma_similarities()