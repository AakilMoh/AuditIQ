<div align="center">

# AuditIQ
### AI-Powered FDCPA Compliance Auditing Engine

*Automated multi-agent call analysis for debt collection agencies*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)


</div>

---

AuditIQ is a production-ready AI compliance auditing system that ingests debt collection call recordings, transcribes them, and runs them through a multi-stage pipeline: deterministic pre-detection, hybrid legal retrieval, multi-agent LLM audit, and rubric-based prompt grading, to produce a structured compliance verdict and downloadable PDF report.

Built to reduce manual QA overhead for debt collection agencies operating under the Fair Debt Collection Practices Act (FDCPA).

---

## Table of Contents

- [Why AuditIQ](#why-auditiq)
- [Architecture](#architecture)
- [Pipeline Stages](#pipeline-stages)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Evaluation & Results](#evaluation--results)
- [Design Decisions](#design-decisions)
- [Roadmap](#roadmap)

---

## Why AuditIQ

Manual QA of debt collection calls is slow, expensive, and inconsistent. A single agency may handle thousands of calls per day, each one a potential (Fair Debt Collection Practices Act) liability if the agent missteps. Traditional keyword-based tools miss nuanced violations. Generic LLMs hallucinate legal citations.

AuditIQ solves this with a layered approach:

- **Deterministic pre-detection** catches obvious violations (arrest threats, profanity, third-party disclosure) before the LLM is even invoked; no hallucination risk on clear-cut cases
- **Hybrid RAG** ensures the LLM reasons against the actual federal statute, not its training data alone
- **Speaker segmentation** ensures the debtor's threats and emotional language never pollute the agent's compliance evaluation
- **A second LLM grades the first** on a rubric, catching reasoning errors and providing prompt improvement suggestions for continuous improvement

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      React 19 Frontend                          │
│   Dashboard · New Audit (SSE stream) · History · Result View    │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼────────────────────────────────────────┐
│                   FastAPI Backend                               │
│                                                                 │
│  ┌─ /audit/stream  ──────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  Audio Upload → Whisper STT → Speaker Segmenter           │  │
│  │       ↓                                                   │  │
│  │  Pre-Detector (regex, Python) — AGENT text only           │  │
│  │       ↓                                                   │  │
│  │  Hybrid Retriever (Dense + BM25 + Cross-Encoder)          │  │
│  │       ↓             + Direct fetch for pre-detected rules │  │
│  │  Agent 1 — Primary Auditor LLM (Llama 3.1 70B, streamed)  │  │
│  │       ↓                                                   │  │
│  │  Violation ID Normalizer                                  │  │
│  │       ↓                                                   │  │
│  │  Agent 2 — Prompt Grader (DeepSeek V4 Pro, rubric-based)  │  │
│  │       ↓                                                   │  │
│  │  Final Result → SSE complete event                        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Data Layer  ─────────────────────────────────────────────┐  │
│  │  SQLite (debtors, agents, call_logs)                      │  │
│  │  ChromaDB Collection A — raw FDCPA statute text           │  │
│  │  ChromaDB Collection B — enriched compliance rules        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  External Services                              │
│  NVIDIA NIM (Llama 70B · DeepSeek V4 Pro · nv-embed-v1)         │
│  Groq Cloud (Whisper Large v3)                                  │
│  Local (MiniLM-L-6-v2 cross-encoder reranker)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages

Each audit passes through eight sequential stages, streamed to the frontend via Server-Sent Events:

| Stage | Component | What happens |
|---|---|---|
| **A** | SQL Lookup | Fetches true account balance and status from SQLite for fact cross-referencing |
| **B** | Speaker Segmenter | Splits flat Whisper transcript into `[AGENT]` / `[DEBTOR]` turns using linguistic pattern scoring |
| **C** | Pre-Detector | Runs 10 categories of FDCPA regex checks on **agent speech only** — debtor threats never trigger violations |
| **D** | Hybrid Retriever | Dense (NVIDIA nv-embed-v1) + BM25 sparse + cross-encoder rerank, merged with direct fetch of pre-detected rule law |
| **E** | Agent 1 (Auditor) | Llama 3.1 70B or DeepSeek V4 Pro streams a structured JSON verdict against the enriched prompt |
| **F** | Normalizer | Violation IDs validated against `rules_core.json`, citation-style strings dropped, pre-detected IDs force-merged |
| **G** | Agent 2 (Grader) | DeepSeek V4 Pro grades Agent 1 on a 10-point rubric: Mini-Miranda handling, pre-detection coverage, legal grounding, ID accuracy, score calibration |
| **H** | Result Assembly | Final payload built with pre_detection, grade_report, speaker_segmentation metadata |

### Speaker Segmentation

One of the more subtle engineering challenges: Whisper returns flat text with no speaker labels. A debt collection call has two speakers with completely different vocabularies, roles, and legal relevance. The segmenter classifies each sentence using weighted pattern scoring:

- `AGENT_STRONG` patterns fire on institutional language ("our records show", "this is an attempt to collect a debt")
- `DEBTOR_STRONG` patterns fire on reactive language ("I already paid this", "stop calling me")
- `AGENT_THREATENING_DEBTOR` vs `DEBTOR_THREATENING_AGENT` patterns handle the critical threat-direction disambiguation: "I'll get my lawyer" scores as DEBTOR, "we will garnish your wages" scores as AGENT

Only agent speech feeds the pre-detector. FDCPA regulates the collector, not the consumer.

### Rules Knowledge Base

The `rules_core.json` file is the heart of Collection B. Each rule is enriched with five retrieval-critical fields beyond the raw statute:

```json
{
  "id": "RULE_TIME_OF_CALL",
  "rule": "A debt collector shall assume convenient time is after 8am and before 9pm local time.",
  "explanation": "Plain English summary...",
  "scenario_anchors": ["I called her at 6am", "He answered at 10pm..."],
  "violation_patterns": ["Collector contacted consumer before 8am local time..."],
  "key_terms": [["inconvenient time", "early morning"], ["local time", "their timezone"]],
  "negative_anchors": ["Consumer authorized contact at 7am..."],
  "cluster_id": "...",
  "priority": 1
}
```

This enrichment was generated via a dual-persona LLM prompt (FDCPA Attorney + Retrieval Engineer), validated by a verifier LLM, and quality-checked by `patch_rules.py` which detects generic filler and re-enriches incomplete rules.

### Hybrid Retrieval

Three-stage retrieval pipeline for high recall and high precision:

1. **Dense search** — ChromaDB cosine similarity against enriched embedding text (explanation + violation_patterns + scenario_anchors concatenated)
2. **BM25 sparse search** — legal-stopword-filtered tokenizer, corpus built from all retrieval metadata fields
3. **Cross-encoder reranking** — local `ms-marco-MiniLM-L-6-v2` reranks merged candidates
4. **Direct fetch** — pre-detected violation rules pulled directly by ID, merged into results, so the LLM always has the law for flagged violations regardless of semantic rank

Cluster deduplication prevents near-duplicate rules from consuming multiple slots. Negative anchor filtering downranks rules where safe-harbor patterns match the transcript.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn | Async HTTP server, SSE streaming |
| Frontend | React 19, Vite 8 | SPA dashboard |
| STT | Groq Whisper Large v3 | Audio transcription |
| LLM (Primary) | Llama 3.1 70B via NVIDIA NIM | Main audit agent |
| LLM (Grader) | DeepSeek V4 Pro via NVIDIA NIM | Rubric-based prompt grader |
| Embedding | NVIDIA nv-embed-v1 (4096-dim) | Dense semantic search |
| Reranker | MiniLM-L-6-v2 (local) | Cross-encoder reranking |
| Sparse Search | rank-bm25 (BM25Okapi) | Keyword matching |
| Vector DB | ChromaDB (persistent) | Dual-collection rule storage |
| Relational DB | SQLite 3 | Debtors, agents, call logs |
| PDF Reports | ReportLab Platypus | Stakeholder-ready audit reports |

---

## Project Structure

```
AuditIQ/
├── app/
│   ├── main.py                    # FastAPI bootstrap + CORS
│   ├── core/
│   │   ├── config.py              # Global clients, model constants, embedding fn
│   │   └── schemas.py             # Pydantic request/response models
│   ├── database/
│   │   └── connection.py          # SQLite connection generator (FastAPI dep)
│   ├── services/
│   │   ├── auditor.py             # Multi-agent pipeline (8 stages, SSE generator)
│   │   ├── speaker_segmenter.py   # Agent/debtor turn attribution
│   │   ├── pre_detector.py        # Deterministic FDCPA violation detection
│   │   ├── hybrid_retriever.py    # Dense + BM25 + cross-encoder retrieval
│   │   ├── pdf_reporter.py        # ReportLab PDF report generator
│   │   ├── transcriber.py         # Groq Whisper integration
│   │   ├── document_processor.py  # ChromaDB ingestion (offline)
│   │   └── ingestion.py           # SQLite schema + seed data
│   └── api/v1/
│       ├── router.py              # Mounts all endpoint modules
│       ├── dependencies.py        # Auth placeholder
│       └── endpoints/
│           ├── audit.py           # /stream · /save · /report/preview · /report/{id}
│           ├── debtors.py         # /debtors (list + detail)
│           ├── agents.py          # /agents (list + detail)
│           ├── logs.py            # /logs (paginated + stats + override)
│           └── health.py          # /health liveness check
├── frontend/src/
│   └── AuditIQ.jsx                # Complete SPA (Dashboard, Audit, History, Result)
├── data/
│   ├── fdcpa_rules.pdf            # Raw FDCPA federal law document
│   └── rules_core.json            # Enriched compliance rules (115 rules)
├── enrich_rules.py                # Offline: LLM-powered rule enrichment
├── expand_rules.py                # Offline: Auto-extract rules from PDF
├── patch_rules.py                 # Offline: Quality validation + repair
├── generate_eval_audio.py         # TTS audio generator for eval cases
└── test_client.py                 # SSE stream test client
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys: NVIDIA NIM, Groq

### Backend Setup

```bash
# Clone and install
git clone https://github.com/yourusername/auditiq.git
cd auditiq
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — add NVIDIA_API_KEY and GROQ_API_KEY

# Initialize database and ingest knowledge base
python -m app.services.ingestion
python -m app.services.document_processor

# Start server
uvicorn app.main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

### Environment Variables

```env
NVIDIA_API_KEY=nvapi-...
GROQ_API_KEY=gsk_...
SQLITE_DB_PATH=databases/collectiq.sqlite
CHROMA_DB_PATH=databases/chromadb
PRIMARY_AUDITOR_MODEL=meta/llama-3.1-70b-instruct
VERIFIER_MODEL=deepseek-ai/deepseek-v4-pro
RESET_DB=false
```

> ⚠️ Set `RESET_DB=false` in production. `true` wipes and reseeds the database on next import of `ingestion.py`.

---

## API Reference

### Core Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/audit/stream` | SSE streaming audit — accepts `audio_file`, `debtor_id`, `think_mode` |
| `POST` | `/api/v1/audit/save` | Persists completed audit to `call_logs` |
| `POST` | `/api/v1/audit/report/preview` | Generates PDF from result payload, streams as download |
| `GET` | `/api/v1/audit/report/{log_id}` | Regenerates PDF from saved call log |
| `GET` | `/api/v1/debtors` | Lists all debtor accounts (optional `?status=` filter) |
| `GET` | `/api/v1/logs` | Paginated audit history (optional `?compliance_passed=` filter) |
| `GET` | `/api/v1/logs/stats/summary` | Aggregate metrics for dashboard |
| `PATCH` | `/api/v1/logs/{log_id}/override` | Human QA reviewer score override |
| `GET` | `/api/v1/health` | Liveness check |

### SSE Event Sequence

```
init → database → database → database → transcribing → transcript_ready
     → auditing → stream (×N tokens) → verifying → complete | error
```

### Complete Result Payload

```json
{
  "compliance_passed": false,
  "performance_score": 2,
  "violations_found": ["RULE_FALSE_LEGAL_STATUS", "RULE_HARASSMENT_OR_ABUSE"],
  "reasoning": "...",
  "verification_notes": "...",
  "retrieved_rules": ["RULE_FALSE_LEGAL_STATUS", "RULE_TIME_OF_CALL"],
  "sql_facts": "True Balance: $850.00, Account Status: Active.",
  "account_name": "Sarah Connor",
  "transcript": "...",
  "formatted_transcript": "[AGENT] Hello...\n[DEBTOR] I don't owe...",
  "pre_detection": {
    "mini_miranda_detected": false,
    "confirmed_violations": [{"rule_id": "RULE_FALSE_LEGAL_STATUS", "citation": "§ 807(5)", "confidence": "high"}],
    "suspicious_patterns": [],
    "risk_score": 7
  },
  "grade_report": {
    "mini_miranda_handling": 2,
    "pre_detection_coverage": 3,
    "legal_grounding": 2,
    "violation_id_accuracy": 2,
    "score_calibration": 1,
    "total_grade": 9,
    "prompt_improvement_suggestion": "..."
  },
  "speaker_segmentation": {
    "confidence": 0.84,
    "agent_turns": 6,
    "debtor_turns": 4
  }
}
```

---

## Evaluation & Results

Five evaluation cases covering the primary violation categories under FDCPA:

| Case | Scenario | Expected | Result | Grader Score |
|---|---|---|---|---|
| Case 1 | Compliant call — professional, Mini-Miranda present | PASS | ✅ PASS 10/10 | 9/10 |
| Case 2 | Arrest threat — agent threatens police involvement | FAIL | ✅ FAIL 1/10 | 10/10 |
| Case 3 | Third-party disclosure — debt revealed to roommate | FAIL | ✅ FAIL 1/10 | 9/10 |
| Case 4 | False balance + harassment | FAIL | ✅ FAIL 1/10 | 8/10 |
| Case 5 | No Mini-Miranda | FAIL | ✅ FAIL 2/10 | 9/10 |

The grader's `prompt_improvement_suggestion` field is logged for every run and used to iteratively refine the audit prompt between eval cycles.

---

## Design Decisions

**Why two LLMs instead of one?**
The primary auditor (Llama 70B) is optimized for depth of reasoning and structured JSON output. Using it for self-evaluation creates a confirmation bias loop, it tends to defend its own reasoning. A separate grader model (DeepSeek V4 Pro) with an explicit rubric catches coverage gaps, miscalibrated scores, and hallucinated citations that the auditor would never self-report.

**Why a pre-detection layer before the LLM?**
Three reasons. First, LLMs are probabilistic — a regex that matches "I will have you arrested" is 100% accurate, an LLM evaluating the same phrase might be 97% accurate. For federal compliance, 3% error rate on clear-cut violations is unacceptable. Second, pre-detected violations are force-merged into the violation ID list and their corresponding law is directly fetched, the LLM cannot miss them due to retrieval ranking. Third, the pre-detector provides ground truth that the grader uses to evaluate LLM coverage.

**Why speaker segmentation before pre-detection?**
FDCPA regulates the collector, not the consumer. A debtor saying "I'll sue you" or "stop calling me, this is harassment" would without segmentation fire pre-detector patterns for legal threats and harassment. This would pollute the audit with debtor speech. The segmenter runs first so the pre-detector only ever sees agent turns.

**Why hybrid retrieval over pure semantic search?**
Dense embeddings capture semantic similarity well ("stop calling me" ≈ "cease communication") but struggle with legal terminology gaps and exact section references. BM25 catches exact legal terms ("§ 806", "debt collector") that embeddings dilute. The cross-encoder reranker resolves disagreements between the two. The combination yields meaningfully higher recall than either alone on legal compliance content.

**Why SQLite over PostgreSQL?**
This is a deliberate prototype-stage choice. The system runs on a single QA workstation. SQLite provides zero-config, file-based storage that runs without infrastructure. The schema is designed to migrate cleanly to PostgreSQL when multi-user or concurrent write requirements emerge.

---

## Roadmap

- [ ] Automated eval framework — regression suite across all cases per prompt change
- [ ] PostgreSQL migration + async SQLAlchemy
- [ ] Proper authentication (JWT, role-based: Admin / QA Reviewer)
- [ ] `/debug/retrieval` endpoint — expose all retrieval scores for diagnostics
- [ ] LangGraph agentic pipeline — multi-step reasoning with tool use
- [ ] Batch processing mode — folder of audio files → overnight audit run
- [ ] Dashboard metrics API — live compliance rate, average score, trend charts
- [ ] Multi-agency deployment — tenant isolation, per-agency rule customization

---

## Author

Built by **Aakil** — AI Engineer with a background in BI/data intelligence.

This project was built to demonstrate production-ready RAG pipeline design, multi-agent LLM orchestration, and applied NLP for legal compliance that combines ML engineering depth with domain-specific prompt craft.

---

<div align="center">
<sub>AuditIQ is a compliance auditing tool. It does not constitute legal advice. Always consult qualified legal counsel for FDCPA compliance decisions.</sub>
</div>
