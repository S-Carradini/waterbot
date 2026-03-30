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

## License

See LICENSE file for details.
