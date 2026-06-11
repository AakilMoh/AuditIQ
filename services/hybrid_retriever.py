import logging
from typing import List, Dict
import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from core.config import CHROMA_DB_PATH, nvidia_ef

logger = logging.getLogger("hybrid_retriever")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('\n[Retriever] %(message)s'))
if not logger.handlers:
    logger.addHandler(console_handler)
# ---------------------------------------------------------

class LegalRetriever:
    def __init__(self):
        logger.info("Initializing Hybrid Legal Retriever")
        self.chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        
        #Connecting to both Collections
        self.collection_a = self.chroma_client.get_collection(name="fdcpa_raw_text", embedding_function=nvidia_ef)
        self.collection_b = self.chroma_client.get_collection(name="fdcpa_compliance_rules", embedding_function=nvidia_ef)

        #Initializing the Reranker (Cross-Encoder)
        logger.info("Loading Cross-Encoder Reranker")
        #self.reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        # New Local Offline Version:
        self.reranker = CrossEncoder('./models/ms-marco-MiniLM-L-6-v2')

        #Initializing BM25 (Sparse Search)
        logger.info("Building BM25 Sparse Index")
        all_rules = self.collection_b.get()
        self.corpus_docs = all_rules['documents']
        self.corpus_ids = all_rules['ids']
        self.corpus_metadatas = all_rules['metadatas']
        
        tokenized_corpus = [doc.lower().split(" ") for doc in self.corpus_docs]
        self.bm25 = BM25Okapi(tokenized_corpus)
        logger.info("Hybrid Retriever Ready.")
    
    def retrieve_context(self, transcript_snippet: str, top_k: int = 3) -> List[Dict]:
        """
        Executes Dense + Sparse retrieval, reranks results, and fetches parent text.
        """
        logger.info(f"Retrieving context for snippet: '{transcript_snippet}'")

        # --- DENSE SEARCH ---
        dense_results = self.collection_b.query(
            query_texts=[transcript_snippet],
            n_results=5
        )
        dense_docs = dense_results.get('documents', [[]])[0]
        dense_ids = dense_results.get('ids', [[]])[0]

        # --- SPARSE SEARCH ---
        tokenized_query = transcript_snippet.lower().split(" ")
        bm25_scores = self.bm25.get_scores(tokenized_query)
        
        top_bm25_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:5]
        sparse_docs = [self.corpus_docs[i] for i in top_bm25_indices]
        sparse_ids = [self.corpus_ids[i] for i in top_bm25_indices]

        # --- COMBINING & DEDUPLICATING ---
        combined_pool = {}
        for doc, doc_id in zip(dense_docs, dense_ids):
            combined_pool[doc_id] = doc
        for doc, doc_id in zip(sparse_docs, sparse_ids):
            combined_pool[doc_id] = doc

        unique_docs = list(combined_pool.values())
        unique_ids = list(combined_pool.keys())

        # --- CROSS-ENCODER RERANKING ---
        pairs = [[transcript_snippet, doc] for doc in unique_docs]
        rerank_scores = self.reranker.predict(pairs)

        ranked_results = sorted(zip(unique_ids, unique_docs, rerank_scores), key=lambda x: x[2], reverse=True)
        top_results = ranked_results[:top_k]

        # --- PARENT-CHILD FETCHING ---
        final_context = []
        for rule_id, rule_text, score in top_results:
            rule_index = self.corpus_ids.index(rule_id)
            metadata = self.corpus_metadatas[rule_index]
            
            # Fetch the raw FDCPA parent section using our mapped sections
            parent_ids = metadata.get("mapped_sections", "").split(",")
            parent_data = self.collection_a.get(ids=parent_ids)
            parent_texts = parent_data.get('documents', ["No legal text found."])

            final_context.append({
                "rule_id": rule_id,
                "rule_statement": rule_text,
                "explanation": metadata.get("explanation", ""),
                "citation": metadata.get("sub_section_citation", ""),
                "raw_federal_text": "\n".join(parent_texts)
            })

        return final_context
    
# Quick Test Block
if __name__ == "__main__":
    retriever = LegalRetriever()
    
    test_query = "If you don't pay this $500 balance right now, I will have the police arrest you."
    print(f"\n[Test Query]: {test_query}\n")
    
    results = retriever.retrieve_context(test_query)
    
    for i, res in enumerate(results):
        print(f"--- Top Match {i+1} ---")
        print(f"Rule ID: {res['rule_id']}")
        print(f"Citation: {res['citation']}")
        print(f"Explanation: {res['explanation']}")
        print(f"Federal Law Snippet: {res['raw_federal_text'][:200]}...\n")