# Mini CollectIQ: Automated Compliance & Agentic QA Audit Pipeline

Mini CollectIQ is a high-performance, cloud-native Artificial Intelligence microservice designed to eliminate manual QA auditing in the debt collection industry. By combining relational database logic, state-of-the-art Hybrid Retrieval-Augmented Generation (RAG), and deterministic analytics, the system cross-examines debt collector call transcripts against real-time account data and legal compliance policies (FDCPA) to instantly flag legal violations.

---

## 🚀 Core Architectural Features

### 1. Pre-Retrieval Dynamic Intent & Category Routing
To prevent context-window pollution and eliminate LLM hallucinations, the pipeline uses a custom preprocessing routing layer. It scans incoming text transcripts for specific linguistic triggers (e.g., legal threats vs. financial negotiation keywords) and dynamically injects a metadata logical filter (`$or` operators) directly into the vector database queries. The search space is instantly focused down only to relevant rules before mathematical matching even begins.

### 2. High-Dimensional Hybrid Search Engine
* **Dense Semantic Vector Search:** Powered by NVIDIA’s cloud-hosted `nv-embed-v1` model, converting unstructured text into dense 4,096-dimensional vector spaces to capture implicit human nuance and semantic meaning.
* **Sparse Tokenized Keyword Search:** Integrated with the `Rank-BM25` algorithm to handle exact string-matching constraints (e.g., specific regulatory terminology, rule IDs, or account numbers).
* **Unified Fusion Layer:** Merges and deduplicates results from both retrieval streams, providing a bulletproof reference context to the LLM.

### 3. Hardened LLM Synthesis & Guardrails
Utilizing the massive `meta/llama-3.1-70b-instruct` model via NVIDIA’s accelerated GPU infrastructure. The system prompt is heavily guarded to enforce strict deterministic logic: instructions like "allowed" or "authorized" are interpreted as optional rather than mandatory, preventing the system from penalizing compliant agent behavior.

### 4. Deterministic Analytics Engine (Anti-Hallucination Guard)
Rather than relying on the LLM to perform mathematical calculations or guess statistical data, the engine forces the model to return a strictly structured JSON array containing isolated infraction counts and explicit violating phrases. Traditional Python and SQL logic then consume this data to calculate precise error-rate percentages and execute analytics queries.

### 5. Transparent Observability & Logging
Includes a custom debug trace architecture that automatically outputs comprehensive run logs under `/logs`. Every execution tracks the precise Euclidean/Cosine distance scores of vector matches, category routing decisions, the exact structured prompt payload, and the raw API outputs for granular auditing.

---

## 🛠️ Tech Stack & Requirements

* **Runtime Environment:** Python 3.11+ executed within a sandboxed virtual environment (`venv`).
* **Relational Fact Database:** SQLite 3 (for deterministic customer data storage).
* **Vector Database:** ChromaDB (configured with persistent disk vector storage).
* **Inference Platform:** NVIDIA NIM API Ecosystem (`nvidia/nv-embed-v1` & `meta/llama-3.1-70b-instruct`).
* **Keyword Indexing:** `rank-bm25`

---

## 📂 System Architecture

```text
mini_collectiq/
├── core/
│   └── config.py          # Secure environment variables & API key validation
├── databases/
│   ├── collectiq.sqlite   # Structured debtor database
│   └── chromadb/          # 4096-dimensional vector store
├── services/
│   ├── ingestion.py       # Automated metadata unpacking & database builder
│   ├── auditor.py         # Hybrid search execution & LLM synthesis engine
│   └── transcriber.py     # Speech-to-Text audio pipeline (Whisper STT integration)
├── logs/                  # Automated RAG tracing and distance score logs
├── .env                   # Local hardware-protected credential store
└── main.py                # FastAPI microservice routing configuration
```
---

## 🛠️ Getting Started & Installation

1. **Clone the Repository and Navigate to the Directory:**
    ```bash
    git clone <your-repo-url>
    cd mini_collectiq
    ```

2. **Initialize a Sandboxed Virtual Environment:**

    ```bash
    py -3.11 -m venv venv
    .\venv\Scripts\Activate.ps1
    ```

3. **Install Dependencies:**

    ```bash
    pip install chromadb sqlite3 openai python-dotenv rank-bm25
    ```

4. **Configure Your Credentials (.env):**
    Create a .env file in the root directory. Ensure this file is explicitly blacklisted in your .gitignore.

    NVIDIA_API_KEY=nvapi-your-secret-key-here
    SQLITE_DB_PATH=data/collectiq.sqlite
    CHROMA_DB_PATH=data/chromadb
    BM25_INDEX_PATH=data/bm25_index.pkl
    RESET_DB=true

5. **Initialize Ingestion & Run the Audit Engine:**

    ```bash
    python 1_setup_database.py
    python 2_agent_engine.py
    ```

## 🗺️ Product Roadmap

**Phase 1: Asynchronous Audio Pipeline (Whisper STT)**
Integrating an automated ingestion service to intercept raw collector voice recordings (.mp3 or .wav). The system will parse files asynchronously via OpenAI's Whisper model, extract clean text streams, and automatically feed them directly into the pre-retrieval routing layer.

**Phase 2: Unstructured Data Parsing & Semantic Chunking**
Transitioning policy document ingestion to LangChain's document loader utilities. This upgrade will replace the manual rules ingestion with a recursive character splitter utilizing a rolling token overlap to preserve structural legal continuity across multi-page compliance manuals.

**Phase 3: High-Performance FastAPI Implementation**
Exposing the backend services as RESTful JSON endpoints. We will build an asynchronous POST /api/v1/audit endpoint capable of processing streaming text/audio payloads and outputting live Server-Sent Events (SSE) tokens directly to front-end dashboard applications.