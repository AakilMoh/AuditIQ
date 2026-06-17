# Mini CollectIQ: Frontend Development Specification

──────────────────────────────────────────────────────────────
## SECTION 1: CODEBASE SUMMARY
──────────────────────────────────────────────────────────────
- **`app/main.py`**: The FastAPI application entry point. It configures the server, sets up CORS middleware to accept frontend requests, and mounts the API router.
- **`app/core/config.py`**: The centralized configuration module. It loads environment variables, defines paths for local databases (SQLite/ChromaDB), sets model identifiers (Llama 70B, DeepSeek), and initializes global clients for OpenAI, Groq, and Nvidia embeddings.
- **`app/api/v1/router.py`**: The primary API router defining the endpoints. Exposes the core `stream_audit` SSE endpoint which orchestrates file uploads, database lookups, transcription, and the multi-agent AI pipeline in real-time.
- **`app/api/v1/dependencies.py`**: Security dependencies. Contains a placeholder function `verify_api_token` for authenticating requests via an `x-api-key` header (currently hardcoded for future enterprise use).
- **`app/database/connection.py`**: The SQLite database connection manager. Provides a generator dependency (`get_db_connection`) for safely opening and closing local database connections per request.
- **`app/services/orchestrator.py`**: The batch processing engine for audits. Exposes `process_call` to run the full QA pipeline (transcription + AI audit) on a local audio file and explicitly logs the results to the SQLite `call_logs` table.
- **`app/services/auditor.py`**: The multi-agent LLM evaluation engine. Exposes the `run_qa_audit` generator function that queries databases, fetches legal context, streams Llama 3.1 70B's analysis, and uses DeepSeek to verify for hallucinations.
- **`app/services/transcriber.py`**: The audio transcription service. Exposes `transcribe_call`, which uploads audio files to Groq's cloud and returns the text using the Whisper Large v3 model.
- **`app/services/hybrid_retriever.py`**: The legal context search engine. Exposes the `LegalRetriever` class that executes dense (embedding) and sparse (BM25) searches against ChromaDB to find relevant FDCPA compliance rules for a given transcript.
- **`app/services/document_processor.py`**: The offline document ingestion engine. Parses the raw FDCPA PDF and the curated rules JSON, deduplicates semantic overlaps using embeddings, and builds the ChromaDB collections.
- **`app/services/ingestion.py`**: The database initialization script. Creates the SQLite schema (auditors, agents, debtors, call_logs), seeds initial mock data, and ingests base rules into a legacy ChromaDB collection.

──────────────────────────────────────────────────────────────
## SECTION 2: COMPLETE API ENDPOINT SPECIFICATION
──────────────────────────────────────────────────────────────

### ENDPOINT: `[POST] /api/v1/audit/stream`
**PURPOSE:** Uploads an audio file, transcribes it, and runs it through the real-time AI compliance pipeline, returning the results as Server-Sent Events (SSE).

**REQUEST:**
- **Type:** `multipart/form-data`
- **Fields:**
  | Name | Type | Required | Description |
  | :--- | :--- | :--- | :--- |
  | `audio_file` | File | Yes | The audio file (mp3, wav, etc.) to be transcribed and audited. |
  | `debtor_id` | Integer | Yes | The ID of the debtor in the database to cross-reference facts against. |
  | `think_mode` | Boolean | No (Default: False) | Toggles the LLM model. True uses a heavier CoT model (Llama 70B), False uses a faster standard model. |

**RESPONSE:**
- **Type:** Server-Sent Events (SSE) Stream (`text/event-stream`)
- **Event Flow:** The stream emits JSON-encoded strings prefixed with `data: ` followed by two newlines.

| Event Step | Payload Shape | Firing Conditions / Meaning |
| :--- | :--- | :--- |
| `init` | `{"step": "init", "message": string}` | Fires immediately upon receiving the payload. Validates the file. |
| `database` | `{"step": "database", "message": string}` | Fires when querying the SQLite database for debtor info and ChromaDB for legal context. |
| `transcribing` | `{"step": "transcribing", "message": string}` | Fires right before the audio is sent to the Whisper API. |
| `transcript_ready` | `{"step": "transcript_ready", "transcript": string}` | Fires the instant transcription completes. The UI should display the transcript here. |
| `auditing` | `{"step": "auditing", "message": string}` | Fires right before the LLM begins generating its analysis stream. |
| `stream` | `{"step": "stream", "chunk": string}` | Fires continuously as raw tokens arrive from the primary Auditor LLM. These chunks construct the JSON result object. |
| `verifying` | `{"step": "verifying", "message": string}` | Fires after the primary LLM stream finishes, while the secondary Verifier LLM checks for hallucinations. |
| `complete` | `{"step": "complete", "result": Object}` | Fires at the very end of a successful pipeline. Contains the final, parsed audit result. |
| `error` | `{"step": "error", "message": string}` | Fires if a fatal error occurs (e.g., missing debtor, failed transcription, LLM crash). Pipeline terminates. |

**FINAL `complete` RESULT OBJECT SHAPE:**
```json
{
    "compliance_passed": boolean,
    "performance_score": integer,
    "violations_found": [string],
    "reasoning": string,
    "verification_notes": string,
    "retrieved_rules": [string],
    "sql_facts": string,
    "account_name": string,
    "transcript": string
}
```
*Note: If the Verifier catches a hallucination, `compliance_passed` is forced to `false`, `performance_score` is forced to `1`, and `reasoning` is prefixed with `[REJECTED BY VERIFIER]:`.*

**ERRORS:**
- The FastAPI router handles unexpected crashes, but domain errors (e.g., debtor not found, transcription failure) are handled gracefully within the SSE stream by emitting a `{"step": "error", "message": ...}` payload and terminating the connection. HTTP status codes will generally remain 200 OK because the stream was successfully established.

──────────────────────────────────────────────────────────────
## SECTION 3: DATABASE SCHEMA
──────────────────────────────────────────────────────────────

### SQLite Tables

**`auditors`**
- Purpose: Stores login credentials for QA reviewers.
- Fields: `auditor_id` (PK), `username` (Unique), `password_hash`, `role`.
- Usage: Set up by `ingestion.py`. The core API currently does not actively query this for auth, though it is referenced by `call_logs`.

**`agents`**
- Purpose: Stores the debt collection agents being audited.
- Fields: `agent_id` (PK), `name`, `department`.
- Usage: Referenced by `call_logs`.

**`debtors`**
- Purpose: Stores the accounts the agents are calling about. Contains ground truth for cross-referencing.
- Fields: `debtor_id` (PK), `account_number` (Unique), `name`, `balance`, `status`.
- Usage: The `/audit/stream` endpoint queries the `name` based on the provided `debtor_id`. The auditor service queries the `balance` and `status` to construct `sql_facts`.

**`call_logs`**
- Purpose: The master table that saves the final results of every completed audit.
- Fields: `log_id` (PK), `debtor_id` (FK), `agent_id` (FK), `auditor_id` (FK), `cloud_audio_uri`, `transcript`, `llm_prompt`, `compliance_passed`, `ai_performance_score`, `reasoning`, `human_override_score`, `timestamp`.
- Usage: Written to by `orchestrator.py` upon pipeline completion. (Note: The `/audit/stream` endpoint currently returns the result to the UI but does *not* write it to this table itself).

### ChromaDB Collections

**`fdcpa_raw_text`**
- Purpose: Stores the raw, unabridged text of the Federal Debt Collection Practices Act.
- Fields: Chunk text (document), section number metadata.
- Usage: Queried by `hybrid_retriever.py` to fetch the parent context for matched rules.

**`fdcpa_compliance_rules`**
- Purpose: Stores deduplicated, plain-English compliance rules derived from the FDCPA.
- Fields: Rule explanation (document), metadata including severity, rule ID, mapped FDCPA sections, and flattened arrays for searching.
- Usage: Searched by `hybrid_retriever.py` using dense embeddings and BM25 sparse search based on transcript snippets.

──────────────────────────────────────────────────────────────
## SECTION 4: FRONTEND FUNCTIONAL REQUIREMENTS
──────────────────────────────────────────────────────────────

### Screen 1: Dashboard / Home
- **Purpose:** Landing page for the QA Reviewer.
- **Data Source:** None directly yet (backend needs endpoints for aggregates, or rely on static layout for now).
- **Required UI Elements:**
  - Navigation sidebar or header.
  - Prominent "Start New Audit" Call-to-Action.
  - Placeholder metrics (e.g., "Audits Completed Today", "Average Compliance Score").

### Screen 2: New Audit Flow (The Core Experience)
- **Purpose:** Upload an audio file, select the associated debtor, and watch the AI process the call in real-time.
- **Data Source:** POST to `/api/v1/audit/stream`.
- **Required UI Elements:**
  - **File Uploader:** Drag-and-drop or select file input for the audio recording.
  - **Debtor Selection:** A dropdown or input field to provide the required `debtor_id`. (Since there isn't a dedicated GET endpoint for debtors yet, the frontend will need to hardcode the seed IDs [1, 2, 3] or the backend needs an update).
  - **"Think Mode" Toggle:** A switch to enable the heavy Llama 70B model.
  - **Submit Button:** Initiates the audit.
  - **Live Progress Indicator:** A stepped progress bar or vertical timeline that lights up as SSE events (`init`, `database`, `transcribing`, etc.) arrive.
  - **Live Transcript Panel:** A text area that populates when the `transcript_ready` event fires.
  - **Raw Stream Output:** A terminal-like window or pulsing text area that displays the raw `stream` chunks (the raw JSON tokens) as the LLM "thinks".
- **States:** Idle -> Uploading/Connecting -> Streaming -> Complete -> Error.

### Screen 3: Audit Result Detail
- **Purpose:** Display the final `complete` object in a highly readable, structured format.
- **Data Source:** The `result` object from the final SSE event.
- **Required UI Elements:**
  - **Status Banner:** Giant Pass/Fail indicator based on `compliance_passed`.
  - **Score Badge:** Displays the `performance_score` (out of 10).
  - **Account Facts Panel:** Displays the `account_name` and the `sql_facts`.
  - **Violations List:** A highlighted list of rule IDs from `violations_found` (if any).
  - **AI Reasoning Text:** The full `reasoning` string, styled distinctly. If the string starts with `[REJECTED BY VERIFIER]:`, flag it in bright red.
  - **Verifier Notes:** Displays the `verification_notes` explaining why the logic was sound or contradictory.
  - **Retrieved Rules Tags:** A list of tags showing the `retrieved_rules` that provided context.
  - **Full Transcript:** The complete conversation text.

──────────────────────────────────────────────────────────────
## SECTION 5: SSE STREAM UI FLOW SPECIFICATION
──────────────────────────────────────────────────────────────

The UI must handle the SSE stream linearly. State should be managed in a reducer or complex state machine.

| Step Name | UI Action & Display Updates | Append vs Replace |
| :--- | :--- | :--- |
| `init` | Highlight step 1 on progress timeline. Display message: "Initializing and validating file." | Replace status text. |
| `database` | Highlight step 2. Display message: "Cross-referencing debtor records." | Replace status text. |
| `transcribing` | Highlight step 3. Show loading spinner on the Transcript Panel. Display message: "Extracting audio." | Replace status text. |
| `transcript_ready` | Hide spinner. Render the full `transcript` string into the Transcript Panel. | Replace Transcript Panel content. |
| `auditing` | Highlight step 4. Open the LLM "Thinking" window. Display message: "AI Auditor analyzing against FDCPA law." | Replace status text. |
| `stream` | Rapidly print incoming `chunk` strings into the "Thinking" window to visualize the model generating the JSON response. | **Append** to "Thinking" window. |
| `verifying` | Highlight step 5. Pause the "Thinking" window. Display message: "Secondary AI verifying logic for hallucinations." | Replace status text. |
| `complete` | Highlight step 6 (Success). Hide the "Thinking" window. Transition the screen to the "Audit Result Detail" view using the provided `result` payload. | **Replace** view entirely with Result Screen. |
| `error` | Abort pipeline. Highlight error state in red. Display the `message` to the user. Show a "Try Again" button. | Replace status text, halt progress. |

──────────────────────────────────────────────────────────────
## SECTION 6: FRONTEND DESIGN REQUIREMENTS
──────────────────────────────────────────────────────────────

### Tone and Visual Direction
- **Vibe:** Professional, authoritative, compliance-focused B2B dashboard.
- **Palette:** Dark navy or slate gray backgrounds (implies security/seriousness). Crisp white cards for data. Strict semantic colors for status:
  - Success/Passed: Muted emerald or forest green.
  - Warnings/Flags: Amber or mustard yellow.
  - Critical/Violations: Crimson red.
- **Typography:** Sans-serif, highly legible fonts (e.g., Inter, Roboto). Data points should use monospaced fonts (e.g., Fira Code, JetBrains Mono) for a technical feel.

### Layout Structure
- **App Shell:** Persistent left sidebar for navigation (Dashboard, New Audit, History).
- **Content Area:** The New Audit flow should be the primary full-page focus.
- **Result View:** Upon completion, the result should slide in or fade in as a full-page structured report.

### Component Priority List
1. **`AuditStatusBanner`:** (Highest Priority) Reusable banner that takes a boolean `passed` and integer `score` and renders a massive, clear status (e.g., Green "COMPLIANT 10/10" vs Red "VIOLATION DETECTED 1/10").
2. **`LiveProgressTimeline`:** A vertical, multi-step indicator tracking the SSE steps.
3. **`TranscriptViewer`:** A scrollable text panel for the conversation.
4. **`ReasoningCard`:** A distinct panel for the LLM's explanation, capable of parsing and highlighting the `[REJECTED BY VERIFIER]:` prefix.
5. **`FactComparisonBox`:** A side-by-side display showing the `sql_facts` next to the transcript context.

### Severity Visual Treatment
*(Note: The result object does not explicitly return severity levels for individual violations in the current implementation, only the IDs in `violations_found`. The design must handle the boolean `compliance_passed` and the integer score).*

- **Pass (`compliance_passed: true`):** Green shield icon, green borders.
- **Fail (`compliance_passed: false`):** Red alert icon, heavy red borders around the `violations_found` and `reasoning` sections.
- **Hallucination Caught (Score = 1, `[REJECTED...]` in reasoning):** Flashing or highly visible yellow/red warning indicating the Verifier intervened. The `verification_notes` must be prominently displayed.