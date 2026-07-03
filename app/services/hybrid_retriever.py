# ─────────────────────────────────────────────────────────────────────────────
# HYBRID RETRIEVAL ENGINE  v2.0
# ─────────────────────────────────────────────────────────────────────────────
#
# CHANGES FROM v1:
#   1. BM25 tokenization improved — stemming, stopword removal, legal term preservation
#   2. Cluster dedup enforced at retrieval time — only top-priority rule per cluster
#   3. Negative anchor filter — downranks rules whose safe-harbor patterns match
#   4. Retrieval logging more verbose — full scores visible for debugging
#   5. retrieve_context is now thread-safe (no shared mutable state in call)
#   6. Added retrieve_by_rule_ids() — direct rule fetch by known IDs
#      (used by pre-detector to pull rule context for pre-detected violations)
# ─────────────────────────────────────────────────────────────────────────────

import logging
import re
import os
from typing import List, Dict, Optional

from rank_bm25            import BM25Okapi
from sentence_transformers import CrossEncoder

from app.core.config import (
    nvidia_ef,
    CHROMA_DB_PATH,
)

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("retriever")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    fh  = logging.FileHandler(os.path.join("logs", "retriever.log"), encoding="utf-8")
    ch  = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)


# ─────────────────────────────────────────────────────────────────────────────
# IMPROVED BM25 TOKENIZER
# v1 was naive whitespace split with .lower() — no stemming, no stopwords
# v2 adds:
#   - Punctuation stripping
#   - Legal stopwords removed (common words that add noise to legal BM25)
#   - Legal compound terms preserved (§ references, rule IDs)
# ─────────────────────────────────────────────────────────────────────────────

LEGAL_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "must", "can", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "or", "and", "but", "not",
    "this", "that", "it", "its", "they", "their", "them", "any", "all",
    "such", "as", "if", "whether", "unless", "under", "no", "than",
}

def _tokenize(text: str) -> List[str]:
    """
    Improved tokenizer for BM25 in a legal context.
    - Lowercases
    - Strips punctuation (except § and - which are meaningful in legal text)
    - Removes legal stopwords
    - Splits on whitespace
    - Preserves compound terms like 'debt_collector', 'third_party'
    """
    if not text:
        return []

    # Lowercase
    text = text.lower()

    # Preserve § references as tokens (§806, §805b etc.)
    text = re.sub(r'§\s*(\d+)', r'section\1', text)

    # Strip most punctuation except hyphens and underscores
    text = re.sub(r"[^\w\s§\-]", " ", text)

    # Split
    tokens = text.split()

    # Remove stopwords and very short tokens
    tokens = [t for t in tokens if t not in LEGAL_STOPWORDS and len(t) > 1]

    return tokens


# ─────────────────────────────────────────────────────────────────────────────
# LEGAL RETRIEVER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class LegalRetriever:
    """
    Three-stage hybrid retrieval:
        Dense (ChromaDB semantic) + Sparse (BM25) → Cross-Encoder rerank

    Improvements in v2:
        - Better BM25 tokenization
        - Cluster dedup at retrieval time
        - Negative anchor filtering
        - Rule-by-ID direct fetch
        - Full verbose logging of all scores
    """

    def __init__(self):
        self._init_chromadb()
        self._init_bm25()
        self._init_reranker()
        logger.info("LegalRetriever v2.0 initialized.")

    def _init_chromadb(self):
        """Connect to both ChromaDB collections."""
        try:
            import chromadb
            client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

            self.collection_b = client.get_collection(
                name              = "fdcpa_compliance_rules",
                embedding_function= nvidia_ef,
            )
            self.collection_a = client.get_collection(
                name              = "fdcpa_raw_text",
                embedding_function= nvidia_ef,
            )

            total_rules = self.collection_b.count()
            logger.info(f"ChromaDB: Collection B has {total_rules} rules.")

        except Exception as e:
            logger.error(f"ChromaDB init failed: {e}")
            raise

    def _init_bm25(self):
        """
        Build BM25 index from Collection B.
        Uses improved tokenizer and includes all retrieval-relevant text fields.
        """
        try:
            all_docs = self.collection_b.get(include=["documents", "metadatas"])

            self._bm25_ids      = all_docs["ids"]
            self._bm25_docs     = all_docs["documents"]
            self._bm25_metas    = all_docs["metadatas"]

            # Build enriched corpus: main doc + scenario anchors + key terms + violation patterns
            corpus = []
            for i, (doc, meta) in enumerate(zip(self._bm25_docs, self._bm25_metas)):
                parts = [doc or ""]

                # Append retrieval-critical metadata fields for BM25
                if meta:
                    for field_key in ["scenario_anchors_text", "bm25_key_terms",
                                      "violation_patterns_text", "negative_anchors_text"]:
                        val = meta.get(field_key, "")
                        if val:
                            parts.append(val)

                enriched_text = " ".join(parts)
                corpus.append(_tokenize(enriched_text))

            self._bm25_index = BM25Okapi(corpus)
            logger.info(f"BM25 index built: {len(corpus)} rules, improved tokenizer.")

        except Exception as e:
            logger.error(f"BM25 init failed: {e}")
            raise

    def _init_reranker(self):
        """Load local cross-encoder reranker."""
        try:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "models", "ms-marco-MiniLM-L-6-v2"
            )
            self._reranker = CrossEncoder(model_path)
            logger.info(f"Cross-encoder loaded from: {model_path}")
        except Exception as e:
            logger.error(f"Cross-encoder init failed: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN RETRIEVAL METHOD
    # ─────────────────────────────────────────────────────────────────────────

    def retrieve_context(self, transcript_snippet: str, top_k: int = 5) -> List[Dict]:
        """
        Full hybrid retrieval pipeline.

        Returns list of dicts with:
            rule_id, rule_statement, explanation, citation, raw_federal_text, score
        """
        logger.info(f"Retrieval for snippet [{len(transcript_snippet)} chars]")

        # ── Stage 1: Dense semantic search ───────────────────────────────────
        dense_results = self.collection_b.query(
            query_texts   = [transcript_snippet],
            n_results      = 15,
            include        = ["documents", "metadatas", "distances"],
        )
        dense_ids   = dense_results["ids"][0]
        dense_docs  = dense_results["documents"][0]
        dense_metas = dense_results["metadatas"][0]
        dense_dists = dense_results["distances"][0]

        logger.debug(f"Dense results: {dense_ids}")

        # ── Stage 2: Sparse BM25 search ───────────────────────────────────
        query_tokens  = _tokenize(transcript_snippet)
        bm25_scores   = self._bm25_index.get_scores(query_tokens)
        bm25_ranked   = sorted(
            zip(self._bm25_ids, self._bm25_docs, self._bm25_metas, bm25_scores),
            key    = lambda x: x[3],
            reverse= True
        )[:15]

        sparse_ids   = [r[0] for r in bm25_ranked]
        sparse_docs  = [r[1] for r in bm25_ranked]
        sparse_metas = [r[2] for r in bm25_ranked]
        sparse_scores= [r[3] for r in bm25_ranked]

        logger.debug(f"BM25 results: {sparse_ids[:5]}")
        logger.debug(f"BM25 top scores: {sparse_scores[:5]}")

        # ── Stage 3: Merge + Deduplicate ─────────────────────────────────
        candidates: Dict[str, Dict] = {}

        for did, doc, meta, dist in zip(dense_ids, dense_docs, dense_metas, dense_dists):
            if did and did not in candidates:
                candidates[did] = {
                    "doc":        doc,
                    "meta":       meta,
                    "dense_dist": dist,
                    "bm25_score": 0.0,
                    "source":     "dense",
                }

        for sid, doc, meta, score in zip(sparse_ids, sparse_docs, sparse_metas, sparse_scores):
            if sid:
                if sid in candidates:
                    candidates[sid]["bm25_score"] = score
                    candidates[sid]["source"]     = "both"
                else:
                    candidates[sid] = {
                        "doc":        doc,
                        "meta":       meta,
                        "dense_dist": 999.0,
                        "bm25_score": score,
                        "source":     "sparse",
                    }

        logger.info(f"Merged candidates: {len(candidates)} unique rules")

        # ── Stage 4: Cluster dedup ────────────────────────────────────────
        # Only keep the highest-priority rule per cluster
        seen_clusters = set()
        deduped       = {}

        # If a rule has no priority, default it to 999 so it goes to the bottom
        sorted_candidates = sorted(
            candidates.items(),
            key=lambda item: int(item[1].get("meta", {}).get("priority", 999))
        )

        for rid, data in sorted_candidates:
            meta        = data.get("meta") or {}
            cluster_id  = meta.get("cluster_id", "")
            superseded  = meta.get("superseded_by", "")

            # Skip if superseded by a rule also in candidates
            if superseded and superseded in candidates:
                logger.debug(f"Skipping {rid} — superseded by {superseded}")
                continue

            # Skip if cluster already represented by higher priority rule
            if cluster_id and cluster_id != "":
                if cluster_id in seen_clusters:
                    logger.debug(f"Skipping {rid} (cluster {cluster_id} already represented)")
                    continue
                seen_clusters.add(cluster_id)

            deduped[rid] = data

        logger.info(f"After cluster dedup: {len(deduped)} candidates")

        # ── Stage 5: Cross-encoder reranking ─────────────────────────────
        if not deduped:
            logger.warning("No candidates after dedup. Returning empty.")
            return []

        pairs    = [(transcript_snippet, data["doc"]) for data in deduped.values()]
        rids     = list(deduped.keys())
        datas    = list(deduped.values())

        ce_scores = self._reranker.predict(pairs)

        ranked = sorted(
            zip(rids, datas, ce_scores),
            key    = lambda x: x[2],
            reverse= True
        )

        logger.info("Cross-encoder scores:")
        for rid, _, score in ranked[:8]:
            logger.info(f"  {rid}: {score:.4f}")

        # ── Stage 6: Negative anchor filter ──────────────────────────────
        # Downrank rules whose safe-harbor patterns match the transcript
        filtered = []
        for rid, data, score in ranked:
            meta           = data.get("meta") or {}
            neg_anchors    = meta.get("negative_anchors_text", "")

            if neg_anchors:
                neg_tokens     = set(_tokenize(neg_anchors))
                query_set      = set(query_tokens)
                overlap        = len(neg_tokens & query_set)
                neg_score      = overlap / max(len(neg_tokens), 1)

                if neg_score > 0.35:  # 35% overlap with negative anchors = downrank
                    logger.info(f"Negative anchor filter: downranking {rid} (neg_score={neg_score:.2f})")
                    score = score * 0.5  # halve the score rather than remove

            filtered.append((rid, data, score))

        # Re-sort after negative anchor adjustment
        filtered.sort(key=lambda x: x[2], reverse=True)
        top_results = filtered[:top_k]

        logger.info(f"Top {top_k} final results: {[r[0] for r in top_results]}")

        # ── Stage 7: Parent-child fetch (Collection A) ────────────────────
        output = []
        for rid, data, ce_score in top_results:
            meta         = data.get("meta") or {}
            mapped_raw   = meta.get("mapped_sections", "")

            # mapped_sections stored as CSV string in ChromaDB metadata
            if isinstance(mapped_raw, str):
                section_ids = [s.strip() for s in mapped_raw.split(",") if s.strip()]
            elif isinstance(mapped_raw, list):
                section_ids = mapped_raw
            else:
                section_ids = []

            raw_law_text = ""
            if section_ids:
                try:
                    raw_results  = self.collection_a.get(ids=section_ids, include=["documents"])
                    raw_docs     = raw_results.get("documents", [])
                    raw_law_text = "\n\n".join(d for d in raw_docs if d)
                except Exception as e:
                    logger.warning(f"Collection A fetch failed for {rid}: {e}")

            output.append({
                "rule_id":          rid,
                "rule_statement":   meta.get("formal_rule", data["doc"]),
                "explanation":      data["doc"],
                "citation":         meta.get("sub_section_citation", ""),
                "severity":         meta.get("severity", ""),
                "raw_federal_text": raw_law_text,
                "violation_patterns": [
                    p.strip() for p in meta.get("violation_patterns_text", "").split("||") if p.strip()
                ],
                "scenario_anchors": [
                    a.strip() for a in meta.get("scenario_anchors_text", "").split("||") if a.strip()
                ],
                "ce_score":         round(float(ce_score), 4),
                "bm25_score":       round(float(data.get("bm25_score", 0)), 4),
                "source":           data.get("source", "unknown"),
            })

        logger.info(f"Retrieval complete. {len(output)} rules returned.")
        return output

    # ─────────────────────────────────────────────────────────────────────────
    # DIRECT RULE FETCH BY ID
    # Used when pre-detector has already identified specific rules
    # ─────────────────────────────────────────────────────────────────────────

    def retrieve_by_rule_ids(self, rule_ids: List[str]) -> List[Dict]:
        """
        Directly fetches rules from Collection B by their exact rule IDs.
        Used to pull context for pre-detected violations that may not rank
        in the top-k from standard retrieval.
        """
        if not rule_ids:
            return []

        try:
            results = self.collection_b.get(
                ids     = rule_ids,
                include = ["documents", "metadatas"],
            )
            output = []
            for doc, meta in zip(results["documents"], results["metadatas"]):
                meta      = meta or {}
                rid       = meta.get("rule_id", "")
                section_ids = []
                mapped_raw  = meta.get("mapped_sections", "")
                if isinstance(mapped_raw, str):
                    section_ids = [s.strip() for s in mapped_raw.split(",") if s.strip()]

                raw_law_text = ""
                if section_ids:
                    try:
                        raw_r       = self.collection_a.get(ids=section_ids, include=["documents"])
                        raw_law_text= "\n\n".join(d for d in raw_r.get("documents", []) if d)
                    except Exception:
                        pass

                output.append({
                    "rule_id":          rid,
                    "rule_statement":   meta.get("formal_rule", doc),
                    "explanation":      doc,
                    "citation":         meta.get("sub_section_citation", ""),
                    "severity":         meta.get("severity", ""),
                    "raw_federal_text": raw_law_text,
                    "violation_patterns": [
                        p.strip() for p in meta.get("violation_patterns_text", "").split("||") if p.strip()
                    ],
                    "scenario_anchors": [
                        a.strip() for a in meta.get("scenario_anchors_text", "").split("||") if a.strip()
                    ],
                    "ce_score":         1.0,   # direct fetch = max relevance
                    "source":           "direct",
                })
            logger.info(f"Direct fetch: retrieved {len(output)} rules for IDs {rule_ids}")
            return output

        except Exception as e:
            logger.error(f"Direct rule fetch failed: {e}")
            return []

#Singleton

retriever = LegalRetriever()