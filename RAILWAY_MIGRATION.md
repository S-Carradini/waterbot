# WaterBot: AWS → Railway Migration Plan

## Overview

This document details the migration of WaterBot from AWS to Railway. The current deployment uses ~15 AWS services. Railway simplifies this to **3 components**: a service (Docker container), a PostgreSQL database, and a persistent volume.

**Current branch:** `test-railway-deployment`
**Purpose:** Viability test — AWS remains untouched as production.

---

## Current AWS Architecture

| AWS Service | Purpose | Monthly Cost Est. |
|---|---|---|
| ECS Fargate (2 tasks) | Run FastAPI app | ~$70 |
| ECR | Docker image registry | ~$1 |
| RDS PostgreSQL (t3.small, Multi-AZ) | Messages + pgvector RAG | ~$50 |
| DynamoDB (on-demand) | Legacy message storage | ~$5 |
| S3 (3 buckets) | Transcripts, backups, exports | ~$3 |
| ALB | Load balancing | ~$20 |
| CloudFront + CF Function | CDN, HTTPS, Basic Auth | ~$5 |
| Bedrock KB (Claude 3 Sonnet) | RAG knowledge base | ~$10-50 (usage) |
| Secrets Manager (2 secrets) | API keys, DB credentials | ~$1 |
| Lambda (3 functions) | DB init, daily backups | ~$0.10 |
| EventBridge (2 rules) | Schedule Lambda | ~$0 |
| SSM Parameter Store | Track backup timestamps | ~$0 |
| SQS (2 DLQs) | Failed Lambda retries | ~$0 |
| CloudWatch | Logs, metrics | ~$5 |
| VPC + NAT | Networking | ~$35 |
| **Total** | | **~$200-250/month** |

## Target Railway Architecture

| Railway Component | Replaces | Monthly Cost Est. |
|---|---|---|
| Service (Dockerfile) | ECS + ECR + ALB | Usage-based |
| PostgreSQL Plugin | RDS + pgvector | Usage-based |
| Volume | S3 (transcripts) | Included |
| Railway Domain (auto HTTPS) | CloudFront + ACM | Included |
| Railway Variables | Secrets Manager | Included |
| Railway Logs | CloudWatch | Included |
| **Total (Pro plan)** | | **~$20-40/month** |

---

## Service-by-Service Migration Detail

### 1. Compute: ECS Fargate → Railway Service

**Current:** 2 Fargate tasks (2048 CPU, 4096 MiB each) behind ALB with session stickiness.

**Railway:** Single service built from `Dockerfile`. Railway handles:
- Docker build from repo
- Zero-downtime deploys
- HTTPS termination
- Health checks
- Auto-restart on failure

**Changes required:**
- `Dockerfile` CMD must use `$PORT` env var (Railway injects the port)
- `railway.toml` config file

### 2. Database: RDS PostgreSQL → Railway PostgreSQL

**Current:** RDS t3.small, PostgreSQL 15, Multi-AZ, pgvector extension, 20GB storage.

**Railway:** Managed PostgreSQL with `vector` extension enabled.

**Schema to create (from `iac/cdk/lambda/db_init/index.py`):**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_uuid VARCHAR(255),
    msg_id VARCHAR(255),
    user_query TEXT,
    response_content TEXT,
    source JSONB,
    chatbot_type VARCHAR(50) DEFAULT 'waterbot',
    created_at TIMESTAMP DEFAULT NOW(),
    reaction SMALLINT,
    user_comment TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_uuid);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_msgid ON messages(msg_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_uuid, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_chatbot_type ON messages(chatbot_type);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id SERIAL PRIMARY KEY,
    doc_id VARCHAR(255) NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    content_hash VARCHAR(64),
    locale VARCHAR(10) DEFAULT 'en',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_doc ON rag_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_metadata ON rag_chunks USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_rag_locale ON rag_chunks(locale);
```

**Connection:** Railway auto-injects `DATABASE_URL`. The app already supports this env var in `pgvector_store.py`.

### 3. RAG: Bedrock KB → pgvector + OpenAI

**Current:** AWS Bedrock Knowledge Base (`Z2NHZ8JMMQ`) with Claude 3 Sonnet for retrieval-augmented generation.

**Railway:** OpenAI embeddings + pgvector similarity search. This path already exists in the codebase:
- `managers/pgvector_store.py` handles vector storage and cosine similarity search
- `managers/rag_manager.py` falls back to pgvector when `AWS_KB_ID` is not set
- `adapters/openai.py` handles LLM responses

**Action:** Don't set `AWS_KB_ID` env var. Must ingest documents post-deploy:
```bash
railway run python scripts/Add_files_to_db.py          # English
railway run python scripts/Add_files_to_db-spanish.py   # Spanish
```

### 4. Transcripts: S3 → Railway Volume

**Current:** `s3_manager.py` uploads transcripts to S3, returns presigned download URLs.

**Railway:** Persistent volume mounted at `/app/transcripts`. Transcripts saved as local files, served via a new FastAPI endpoint.

**Code changes:**
- `s3_manager.py` gets a `LocalTranscriptManager` fallback
- New endpoint `GET /transcript-file/{filename}` serves files from volume
- `TRANSCRIPT_STORAGE_PATH` env var points to volume mount

### 5. Dropped Services

| Service | Why Dropped |
|---|---|
| DynamoDB | PostgreSQL `messages` table replaces it. Don't set `MESSAGES_TABLE`. |
| S3 backup buckets | Railway PostgreSQL has built-in backups. |
| Lambda (db_init) | Schema created manually or via migration script. |
| Lambda (backups) | Not needed — Railway handles DB backups. |
| EventBridge | No scheduled tasks needed. |
| SSM Parameter Store | No backup timestamps to track. |
| SQS (DLQs) | No Lambda = no DLQs. |
| CloudFront | Railway provides HTTPS domains. |
| ALB | Railway handles routing. |
| VPC + NAT | Not needed — Railway manages networking. |

---

## Environment Variables

### Railway Variables to Set

| Variable | Value | Source |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | From AWS Secrets Manager or `.env` |
| `SESSION_SECRET` | Random UUID | Generate new |
| `TRANSCRIPT_STORAGE_PATH` | `/app/transcripts` | Volume mount path |

### Auto-Injected by Railway

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `PORT` | Port to bind to |
| `RAILWAY_ENVIRONMENT` | Environment name |

### Variables NOT Set (intentional)

| Variable | Effect |
|---|---|
| `AWS_KB_ID` | Forces pgvector RAG instead of Bedrock |
| `MESSAGES_TABLE` | Disables DynamoDB writes |
| `TRANSCRIPT_BUCKET_NAME` | Disables S3 transcript uploads |
| `DB_HOST/DB_NAME/DB_USER/DB_PASSWORD` | `DATABASE_URL` used instead |

---

## Files Changed

### New Files
| File | Purpose |
|---|---|
| `railway.toml` | Railway build/deploy configuration |
| `RAILWAY_MIGRATION.md` | This document |

### Modified Files
| File | Change |
|---|---|
| `Dockerfile` | CMD uses `$PORT` env var |
| `application/main.py` | Add `/transcript-file/{filename}` endpoint |
| `application/managers/s3_manager.py` | Add `LocalTranscriptManager` for volume-based storage |

### Unchanged Files
| File | Why |
|---|---|
| `application/managers/pgvector_store.py` | Already supports `DATABASE_URL` |
| `application/managers/rag_manager.py` | Falls back to pgvector when no `AWS_KB_ID` |
| `application/adapters/openai.py` | Works with `OPENAI_API_KEY` |
| `frontend/*` | Bundled in Docker image, no changes |
| All AWS CDK/Lambda files | AWS untouched |

---

## Deployment Steps

```bash
# 1. Create Railway project
railway init

# 2. Add PostgreSQL
railway add --plugin postgresql

# 3. Add persistent volume for transcripts
railway volume add --mount /app/transcripts

# 4. Set environment variables
railway variables set OPENAI_API_KEY=<key>
railway variables set SESSION_SECRET=$(uuidgen)
railway variables set TRANSCRIPT_STORAGE_PATH=/app/transcripts

# 5. Deploy
railway up

# 6. Get public URL
railway domain

# 7. Connect to DB and create schema
railway connect postgresql
# (run CREATE EXTENSION vector; and CREATE TABLE statements above)

# 8. Ingest RAG documents (optional, for full test)
railway run python scripts/Add_files_to_db.py
railway run python scripts/Add_files_to_db-spanish.py
```

---

## Rollback Plan

Since AWS is untouched, rollback is simply "stop using Railway":
1. `railway down` — stops the Railway service
2. AWS continues serving production at azwaterbot.org
3. Delete Railway project if needed: `railway delete`

---

## What You Lose vs AWS

| Feature | AWS | Railway |
|---|---|---|
| CDN edge caching | CloudFront (global) | No CDN (single region) |
| Multi-AZ database | RDS Multi-AZ | Single instance |
| Bedrock RAG quality | Managed KB + Claude 3 | pgvector + OpenAI |
| Automated daily backups | Lambda + S3 | Railway built-in backups |
| Basic Auth (CloudFront) | CF Function | Must implement in app |
| Auto-scaling | 2-4 ECS tasks | Single container (can add replicas) |

## What You Gain

| Feature | AWS | Railway |
|---|---|---|
| Deploy time | ~5 min (CI/CD pipeline) | ~1 min (`railway up`) |
| Infrastructure code | ~700 lines CDK Python | 10-line `railway.toml` |
| Monthly cost | ~$200-250 | ~$20-40 |
| Operational complexity | 15 services to manage | 3 components |
| Local dev parity | Docker + .env | `railway dev` mirrors prod |
| Logs | CloudWatch (separate UI) | `railway logs` (CLI) |

---

## Test Checklist

- [ ] Railway project created
- [ ] PostgreSQL provisioned with pgvector extension
- [ ] Volume mounted for transcripts
- [ ] Environment variables set
- [ ] Docker image builds and deploys
- [ ] App starts without errors (`railway logs`)
- [ ] Splash screen loads at Railway URL
- [ ] `/chat` page loads
- [ ] Send a message → get a response (requires OpenAI key)
- [ ] Transcript download works (volume storage)
- [ ] Language toggle works
- [ ] Settings and transcript pages accessible
