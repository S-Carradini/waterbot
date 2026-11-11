# WaterBot — RAG-Powered Chatbot for Arizona Water Information

WaterBot is a Retrieval-Augmented Generation (RAG) chatbot that provides information about water in Arizona. It features a React/Vite frontend and a FastAPI backend. RAG is powered by **pgvector + OpenAI embeddings**; LLM responses are generated via **OpenAI GPT-4.1**. A secondary "RiverBot" persona is also supported via separate routes and templates.

**Production URL:** https://waterbot-production.up.railway.app

---

## Features

- **RAG via pgvector** — semantic search over Arizona water documents using OpenAI embeddings + PostgreSQL pgvector
- **Multi-language** — English and Spanish, auto-detected via `langdetect` with user override
- **Voice transcription** — real-time speech-to-text via browser Web Speech API / WebSocket
- **Session memory** — per-user UUID cookie keeps conversation context
- **Source citations** — every answer links back to source documents
- **RiverBot persona** — separate chat UI and system prompt at `/riverbot`
- **React frontend** — responsive, mobile-friendly UI with typewriter animation
- **Legacy Jinja2 templates** — `index.html`, `riverbot.html`, `spanish.html`, `splashScreen.html` served directly by FastAPI for non-React paths

---

## Architecture

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Vite, Framer Motion, Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| RAG | pgvector + OpenAI embeddings |
| LLM | OpenAI GPT-4.1 |
| Session identity | UUID cookie (`USER_SESSION`) set by `SetCookieMiddleware` |
| Message logging | PostgreSQL (`messages` table) — includes ratings |
| Transcripts | Local filesystem (Railway volume) |
| Container | Docker (multi-stage build) |
| Hosting | Railway |

### Request Flow

```
Browser → UUID Cookie → FastAPI
  → Safety checks (OpenAI moderation + intent detection)
  → Language detection (langdetect)
  → pgvector similarity search (top-k chunks)
  → Build prompt (system + KB context + chat history)
  → OpenAI GPT-4.1
  → Response + sources → Browser
  → [Background] Log to PostgreSQL messages table
```

### System Architecture

```mermaid
graph TB
    subgraph "Client"
        Browser
    end

    subgraph "Railway"
        App[FastAPI App\nmain.py]
        PG[PostgreSQL + pgvector\nmessages + rag_chunks]
        Vol[Volume\ntranscripts]
    end

    subgraph "External"
        OAI[OpenAI GPT-4.1\nLLM + embeddings + moderation]
    end

    Browser --> App
    App --> PG
    App --> Vol
    App --> OAI
```

### RAG Pipeline

```mermaid
flowchart TD
    Query([User Query]) --> Safety[Safety Checks\nmoderation + intent]
    Safety -->|fail| Reject[Return safe fallback]
    Safety -->|pass| Lang[Detect Language\nen / es]
    Lang --> PGV[pgvector Similarity Search\ntop-k chunks + locale filter]
    PGV --> Chunks[Top-K document chunks\nwith source metadata]
    Chunks --> Prompt[Build Prompt\nsystem + KB + chat history]
    Prompt --> LLM[OpenAI GPT-4.1]
    LLM --> Response[Response + sources]
    Response --> Memory[Update MemoryManager]
    Memory --> BG[Background: log to PostgreSQL]
    Response --> Browser([Return to Browser])
```

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL with pgvector extension (or use Railway's public Postgres URL)
- OpenAI API key

### Step 1 — Create `.env`

```bash
cp application/sample.env .env
```

Then fill in:

```env
# ── Required ────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# PostgreSQL (Railway public URL or local)
DATABASE_URL=postgresql://user:pass@host:port/dbname

# ── Optional ────────────────────────────────────────────
# TRANSCRIPT_STORAGE_PATH=/app/transcripts
# SESSION_SECRET=your-secret-key
```

### Step 2 — Start the backend

```bash
cd application
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
fastapi dev main.py          # auto-reload at http://localhost:8000
```

### Step 3 — Start the frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Vite proxies all `/chat_api`, `/chat_sources_api`, `/submit_rating_api`, `/session-transcript`, `/translate`, and `/static` requests to `localhost:8000` automatically — no manual CORS configuration needed in dev.

### What works without optional vars

| Feature | Required vars |
|---------|--------------|
| RAG + chat | `OPENAI_API_KEY`, `DATABASE_URL` (or `DB_*`) |
| Message logging | `DATABASE_URL` or `DB_*` |
| Ratings | `DATABASE_URL` or `DB_*` (stored in `messages` table) |
| Transcript download | `TRANSCRIPT_STORAGE_PATH` |

When optional vars are absent the app starts cleanly — those features are silently skipped.

### Docker (full stack)

```bash
docker-compose up           # builds image, runs on http://localhost:8000
# or individually:
./docker_build.sh
```

The `docker-compose.yml` reads `OPENAI_API_KEY`, `DATABASE_URL`, and `SESSION_SECRET` from your shell environment.

---

## Project Structure

```
waterbot/
├── application/                  # FastAPI backend
│   ├── main.py                   # App entry point: all 13 endpoints, middleware, startup
│   ├── adapters/
│   │   ├── base.py               # ModelAdapter abstract base class
│   │   └── openai.py             # OpenAIAdapter (GPT-4.1, moderation, embeddings)
│   ├── managers/
│   │   ├── memory_manager.py     # In-memory session state (chat history, message counts)
│   │   ├── rag_manager.py        # RAG orchestration (query → pgvector → prompt → LLM)
│   │   ├── pgvector_store.py     # pgvector store (cosine similarity search)
│   │   └── s3_manager.py         # Local transcript storage (Railway volume)
│   ├── templates/                # Jinja2 HTML templates
│   ├── static/                   # CSS, JS, images for Jinja templates
│   ├── mappings/                 # knowledge_sources.py, custom_tags.py
│   ├── scripts/                  # Data ingestion (Add_files_to_db*.py)
│   └── sample.env                # Environment variable template
├── frontend/                     # React + Vite frontend
│   ├── src/
│   │   ├── App.jsx               # Root component, global state
│   │   ├── components/           # ChatBubble, InputWrapper, Header, MobileChatbot, RecordingModal
│   │   └── services/api.js       # All fetch calls to backend
│   ├── public/                   # Static assets (images, icons)
│   └── vite.config.js            # Dev proxy config
├── .github/workflows/
│   └── deploy-railway.yaml       # Railway CI/CD
├── docker-compose.yml
├── Dockerfile
└── README.md
```

---

## API Endpoints

### Chat

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat_api` | POST | WaterBot main chat (English) |
| `/riverbot_chat_api` | POST | RiverBot persona chat |
| `/chat_sources_api` | POST | Retrieve sources for a prior response |
| `/chat_actionItems_api` | POST | Get action items from a prior response |
| `/chat_detailed_api` | POST | Get a more detailed response for a prior query |

### Pages (Jinja2)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Splash screen |
| `/waterbot` | GET | WaterBot Jinja2 chat UI |
| `/riverbot` | GET | RiverBot Jinja2 chat UI |
| `/spanish` | GET | Spanish Jinja2 chat UI |

### Utilities

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/transcribe` | WebSocket | Real-time voice transcription |
| `/session-transcript` | POST | Download session transcript |
| `/submit_rating_api` | POST | Submit thumbs up/down rating |
| `/translate` | POST | Translate text between en/es |

---

## CI/CD Pipeline

Railway deployment is triggered via GitHub Actions (`deploy-railway.yaml`) using a `RAILWAY_TOKEN` secret.

---

## Configuration Reference

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key (chat, moderation, embeddings) |
| `DATABASE_URL` | Yes* | PostgreSQL URL (*or use `DB_*` vars) |
| `DB_HOST/USER/PASSWORD/NAME/PORT` | Yes* | Alternative to `DATABASE_URL` |
| `TRANSCRIPT_STORAGE_PATH` | No | Local path for transcript files |
| `SESSION_SECRET` | No | Session signing key (random if omitted) |
| `COOKIE_DOMAIN` | No | Cookie domain (e.g. `.yourdomain.com`) |
| `SOURCES_VERIFIER_MODEL` | No | Model for source verification (default: `gpt-4o-mini`) |

### LLM Adapter

The current default is `OpenAIAdapter("gpt-4.1")` set in `main.py`. To swap adapters, modify:

```python
# application/main.py
ADAPTERS: dict[str, object] = {
    "openai-gpt4.1": OpenAIAdapter("gpt-4.1"),
}
llm_adapter = ADAPTERS["openai-gpt4.1"]
```

---

## Troubleshooting

### RAG not returning results

- Verify `DATABASE_URL` is set and the PostgreSQL instance has pgvector extension enabled
- Ensure `rag_chunks` table is populated (run `scripts/Add_files_to_db.py`)
- Check logs for `RAG disabled` warnings at startup

### Messages not persisting after restart

`MemoryManager` is in-memory — this is expected. Set `DATABASE_URL` or `DB_*` vars to enable PostgreSQL message logging. The `messages` table is auto-created on startup if it doesn't exist.

### `relation "messages" does not exist`

The app creates the `messages` table automatically at startup (`startup_ensure_db`). If you see this error, check that your DB user has `CREATE TABLE` privileges.

### Cookie/session not sticking

- On HTTP (local dev), the cookie uses `SameSite=Lax` — works fine
- On HTTPS (prod), it uses `SameSite=None; Secure` — requires HTTPS
- `COOKIE_DOMAIN` is only applied when the request host matches — don't set it for local dev

### CSS not updating in dev

```bash
rm -rf frontend/node_modules/.vite
npm run dev
```

### Voice transcription not working

Check browser permissions for microphone access. Transcription uses the browser Web Speech API (no server-side processing for basic transcription).

---

## Security

### Security testing: OWASP AI Testing Guide (AITG)

The production waterbot chatbot (azwaterbot.org) was security-tested against the **OWASP AI Testing Guide (AITG)**, OWASP's methodology for testing AI systems. It covers four pillars: **Application (APP)**, **Model (MOD)**, **Infrastructure (INF)** and **Data (DAT)**. The findings were recorded in a baseline report dated **17 October 2026** and tracked case by case in the **Waterbot Remediation Tracker**, together with a separate **code review** of the source.

#### 1. Baseline test results (before remediation)

| AITG pillar | Tests run | Passed | Failed test cases (tracker) | Critical | High | Medium | Low |
|-------------|-----------|--------|-----------------------------|----------|------|--------|-----|
| **APP** (Application) | 51 tests across 12 APP categories | 34 | 20 | 1 | 13 | 2 | 4 |
| **MOD** (Model) | 30 tests across 6 MOD categories | 26 | 4 | 0 | 1 | 3 | 0 |
| **INF** (Infrastructure) | 57 attack prompts, each also retried through the follow-up buttons | - | 29 | 13 | 15 | 1 | 0 |
| **DAT** (Data) | Data-handling scenarios plus supplemental retests | - | 6 | 0 | 3 | 2 | 1 |
| **Total** | | | **59** | **14** | **32** | **8** | **5** |

The code review added **14 findings** (3 Critical, 4 High, 3 Medium, 4 Low) that are not chat tests, for example a hard-coded admin password, a safety check that always approved, and bot replies rendered as raw HTML.

#### 2. Failed test cases by AITG category, and their status after remediation

| AITG category | What the test checks | Failed | Fixed and verified |
|---------------|----------------------|--------|--------------------|
| AITG-APP-03 Sensitive data leak | Unrelated questions (quotes, "who said…") triggered the elected-officials reply | 3 | 3 |
| AITG-APP-04 Input leakage | Bot made untrue privacy promises about what is stored | 2 | 2 |
| AITG-APP-07 Prompt disclosure | Bot revealed its instructions, rules and knowledge-base text (audit, FAQ, "teach another AI" framings) | 10 | 10 |
| AITG-APP-14 Explainability | Bot invented things it "said earlier" (fabricated continuity) | 5 | 4 (1 partial) |
| AITG-MOD-01 Evasion attacks | Look-alike characters and "forget that, instead…" pivots got past refusals | 4 | 4 |
| AITG-INF-01 Supply chain | Bot invented or revealed packages, model IDs and setup details | 3 | 3 |
| AITG-INF-02 Resource exhaustion | Repeated follow-up clicks nested requests without limit | 1 | 1 |
| AITG-INF-03 Plugin boundary violations | Fake database, file and tool commands were acted on through the buttons | 5 | 5 |
| AITG-INF-04 Capability misuse | Refused requests (medical, elections, roasts, lock-picking, recipes) were answered via "Tell me more" | 10 | 10 |
| AITG-INF-05 Poisoning | Off-topic answers and sources returned after injected "knowledge" | 3 | 3 |
| AITG-INF-06 Model and secret theft | Requests for API keys, database URLs, sessions and admin credentials | 7 | 7 |
| AITG-DAT-01 Training data exposure | Bot compiled lists of contact details from its documents | 1 | 1 |
| AITG-DAT-02 Runtime exfiltration | Bot returned raw retrieved context | 1 | 1 |
| AITG-DAT-04 Harmful content | No crisis resource on a self-harm message | 1 | 1 |
| AITG-DAT-05 Data minimization and consent | Inaccurate statement about data storage | 1 | 1 |
| DAT supplemental (S-1, S-3) | Bot attributed phone numbers and codes the user never gave | 2 | 2 |
| **Total** | | **59** | **58 + 1 partial** |

Code-review findings: **12 of 14 fixed**. Two were set aside by decision: the Riverbot persona (Riverbot was out of scope) and pinning AI model versions (still under discussion). Removing the old admin password from git history is on hold; the password itself is no longer in the code.

#### 3. Retest against the fixed system

All AITG test prompts were **rerun against the fixed version with the real production AI models** (`gpt-6-luna` safety screening and `gpt-4.1` answers), including clicking the follow-up buttons where the original tests did:

| Retest | Result |
|--------|--------|
| AITG attack prompts (APP, MOD, INF, DAT): 188 conversations, follow-up buttons included | **0 failures.** 175 handled correctly (checked automatically); 12 replies read by hand: 10 correct, 1 partial (APP-14 T45), 1 fixed afterwards (DAT-04 S3 on the buttons); 1 hit a temporary OpenAI error and the bot safely declined |
| Normal visitor questions in English and Spanish (20) | **All answered**, none wrongly refused |
| Same AITG prompts with the AI deliberately made to misbehave (905 replies) | **0 leaks.** The code-level checks caught every leaked prompt, document and email |
| Script-injection attacks in a real Chrome browser | **No injected script ran** |


#### 4. Additional web-application and deployment checks

| Check | Result |
|-------|--------|
| OWASP Web Security Testing Guide (WSTG)-style checks: headers, sessions, cross-site requests, file access, admin login and lockout, SQL injection, CSV export, open redirects | **69 / 69 pass** |
| Same behaviour as before for normal use and Riverbot (side-by-side with `main`) | **39 / 39 match**; only the intended security changes differ |
| Load test: 100 concurrent visitors with realistic AI delays | **0 errors** |
| CI replay: 132 backend tests, frontend and browser tests, `pip-audit` and `npm audit` | **All pass** |
| Secret scan (gitleaks) and container scan (Trivy) | **No secrets**; no critical issues in application packages |

All fixes were submitted in **PR #75 on 10 November 2026**.

### What changed

- **Safety screening on every message and follow-up button.** OpenAI moderation plus a classifier (`gpt-6-luna`) decide whether a message is a water question. Everything else gets a fixed reply. Screening fails closed: if it cannot run, the bot declines instead of answering unchecked.
- **Follow-up buttons** cannot expand on a refused question and are capped per question and per session.
- **Prompt and data protection.** Retrieved documents are kept separate from the instructions, and replies are checked for copied instructions, copied documents, internal tags and personal email addresses.
- **Fixed replies** for medical, elections, self-harm (988 crisis line), privacy and system questions.
- **Browser safety.** Bot replies are sanitized with DOMPurify, and pages send a Content-Security-Policy.
- **Sessions and access.** Signed session IDs; translate and text-to-speech need a valid session; requests from other websites are refused; transcript links are signed and expire after 30 minutes; API docs (`/docs`) are disabled.
- **Admin.** The hard-coded password was removed. Admin uses a bcrypt hash from environment variables and locks out after repeated failed logins.
- **Limits.** Rate limits per session, per IP and site-wide; request bodies over 1 MB are refused.
- **Dependencies** were upgraded and pinned, and CI audits them (`pip-audit`, `npm audit`).

---

## License

See LICENSE file for details.
