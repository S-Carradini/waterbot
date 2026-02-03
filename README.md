# WaterBot - RAG-Powered Chatbot for Arizona Water Information

WaterBot is a Retrieval-Augmented Generation (RAG) chatbot that provides information about water in Arizona. It features a modern React frontend and a FastAPI backend with PostgreSQL (pgvector) for vector storage, supporting both OpenAI and Claude (AWS Bedrock) LLM adapters.

## Features

- **RAG-Powered Responses**: Answers questions using retrieval-augmented generation from a knowledge base
- **Multi-Language Support**: English and Spanish
- **Voice Transcription**: Real-time speech-to-text via browser Web Speech API
- **Conversation History**: Maintains session-based chat history
- **Source Citations**: Provides source references for answers
- **Modern UI**: React-based frontend with responsive design
- **Multiple LLM Support**: OpenAI GPT and AWS Bedrock Claude adapters

## Architecture

### Tech Stack

**Frontend:**
- React + Vite
- Framer Motion for animations
- Tailwind CSS
- Web Speech API for voice transcription

**Backend:**
- FastAPI (Python)
- PostgreSQL (pgvector) for RAG vector storage
- PostgreSQL for message logging
- DynamoDB for ratings
- S3 for transcript storage

**LLM Adapters:**
- OpenAI GPT models
- AWS Bedrock Claude models

### System Architecture Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        A[Web Browser] --> B[FastAPI Application]
        A --> C[WebSocket Connection]
    end
    
    subgraph "Application Layer"
        B --> D[Session Middleware]
        D --> E[Memory Manager]
        D --> F[Chat API Endpoints]
        C --> G[Transcribe Handler]
        G --> F
    end
    
    subgraph "RAG Pipeline"
        F --> H[Language Detection]
        H --> I{Language?}
        I --> RAG[RAG Manager]
        RAG --> L[Vector Search]
        L --> M[Document Retrieval]
    end
    
    subgraph "LLM Layer"
        M --> N[LLM Adapter]
        N --> O{Adapter Type}
        O -->|OpenAI| P[OpenAI API]
        O -->|Claude| Q[AWS Bedrock]
    end
    
    subgraph "Storage Layer"
        E --> R[In-Memory<br/>Sessions]
        F --> S[PostgreSQL<br/>Messages]
        F --> T[DynamoDB<br/>Ratings]
        F --> U[S3<br/>Transcripts]
        RAG --> V[PostgreSQL<br/>pgvector rag_chunks]
    end
    
    style F fill:#e1f5ff
    style L fill:#fff4e1
    style N fill:#e8f5e9
    style V fill:#f3e5f5
```

### RAG Pipeline Detailed Flow

```mermaid
flowchart TD
    Start([User Query]) --> SafetyCheck[Safety Checks<br/>Moderation & Intent]
    SafetyCheck -->|Fail| Reject[Reject Response]
    SafetyCheck -->|Pass| AddToMemory[Add User Message<br/>to Session Memory]
    AddToMemory --> DetectLang[Detect Language<br/>langdetect]
    DetectLang --> PgVec[pgvector rag_chunks<br/>locale en/es]
    
    PgVec --> EmbedQuery[Embed User Query<br/>OpenAI Embeddings]
    
    EmbedQuery --> VectorSearch[Vector Similarity Search<br/>pgvector]
    VectorSearch --> RetrieveDocs[Retrieve Top K Documents<br/>k=4]
    RetrieveDocs --> ParseSources[Parse Source Metadata<br/>Extract URLs & Descriptions]
    ParseSources --> FormatKB[Format Knowledge Base<br/>Concatenate Document Content]
    
    FormatKB --> BuildPrompt[Build LLM Prompt<br/>System Prompt + KB + Chat History]
    BuildPrompt --> LLMCall[Call LLM<br/>OpenAI/Claude]
    LLMCall --> GenerateResponse[Generate Response]
    
    GenerateResponse --> StoreResponse[Store Response<br/>Memory + Database]
    StoreResponse --> ReturnResponse[Return Response<br/>with Sources]
    
    ReturnResponse --> End([End])
    Reject --> End
    
    style SafetyCheck fill:#ffebee
    style VectorSearch fill:#fff4e1
    style LLMCall fill:#e8f5e9
    style StoreResponse fill:#e1f5ff
```

## Request/Response Flow

### Chat API Request Flow

```mermaid
sequenceDiagram
    participant User
    participant FastAPI
    participant MemoryManager
    participant RAGManager
    participant LLMAdapter
    participant PostgreSQL
    
    User->>FastAPI: POST /chat_api<br/>(user_query)
    FastAPI->>FastAPI: Extract Session UUID<br/>(Cookie/State)
    FastAPI->>MemoryManager: create_session(session_uuid)
    FastAPI->>LLMAdapter: safety_checks(user_query)
    LLMAdapter-->>FastAPI: moderation_result, intent_result
    
    alt Safety Check Failed
        FastAPI->>User: Reject Response
    else Safety Check Passed
        FastAPI->>MemoryManager: add_message_to_session<br/>(user_query)
        FastAPI->>FastAPI: detect_language(user_query)
        
        alt English
            FastAPI->>RAGManager: ann_search(user_query, locale)
        else Spanish
        end
        
        RAGManager->>RAGManager: similarity_search(user_query, k=4, locale)
        RAGManager->>RAGManager: parse_source(metadata)
        RAGManager-->>FastAPI: {documents, sources}
        
        FastAPI->>RAGManager: knowledge_to_string(docs)
        RAGManager-->>FastAPI: formatted_kb_string
        
        FastAPI->>MemoryManager: get_session_history_all()
        MemoryManager-->>FastAPI: chat_history
        
        FastAPI->>LLMAdapter: get_llm_body(kb_data, chat_history)
        LLMAdapter->>LLMAdapter: build_prompt(system + kb + history)
        LLMAdapter-->>FastAPI: llm_payload
        
        FastAPI->>LLMAdapter: generate_response(llm_payload)
        LLMAdapter->>LLMAdapter: Call OpenAI/Bedrock API
        LLMAdapter-->>FastAPI: response_content
        
        FastAPI->>MemoryManager: add_message_to_session<br/>(response + sources)
        FastAPI->>MemoryManager: increment_message_count()
        FastAPI->>PostgreSQL: log_message()<br/>(Background Task)
        FastAPI->>User: Return Response + Sources
    end
```

## Component Interactions

### Component Interaction Diagram

```mermaid
graph LR
    subgraph "Core Components"
        A[FastAPI App] --> B[MemoryManager]
        A --> C[RAGManager]
        A --> D[LLMAdapter]
        A --> E[DynamoDBManager]
        A --> F[S3Manager]
    end
    
    subgraph "MemoryManager"
        B --> B1[Session Storage]
        B --> B2[Message Counts]
        B --> B3[Chat History]
    end
    
    subgraph "RAGManager"
        C --> C1[Vector Search]
        C --> C2[Source Parsing]
        C --> C3[Knowledge Formatting]
        C1 --> C4[pgvector<br/>rag_chunks]
    end
    
    subgraph "LLMAdapter"
        D --> D1[OpenAIAdapter]
        D --> D2[BedrockClaudeAdapter]
        D1 --> D3[OpenAI API]
        D2 --> D4[AWS Bedrock]
    end
    
    subgraph "Storage"
        E --> E1[DynamoDB<br/>Ratings]
        F --> F1[S3<br/>Transcripts]
        A --> G[PostgreSQL<br/>Messages]
    end
    
    style A fill:#e1f5ff
    style C fill:#fff4e1
    style D fill:#e8f5e9
    style B fill:#f3e5f5
```

## Data Flow

### Data Flow Through the System

```mermaid
flowchart LR
    subgraph "Input"
        A[User Query<br/>Text/Voice]
        B[Session UUID<br/>Cookie]
    end
    
    subgraph "Processing"
        C[Language Detection]
        D[Vector Embedding]
        E[Similarity Search]
        F[Document Retrieval]
        G[LLM Generation]
    end
    
    subgraph "Storage"
        H[PostgreSQL<br/>pgvector rag_chunks]
        I[MemoryManager<br/>Session State]
        J[PostgreSQL<br/>Message Log]
        K[DynamoDB<br/>Ratings]
        L[S3<br/>Transcripts]
    end
    
    subgraph "Output"
        M[Response Text]
        N[Source Citations]
        O[Message ID]
    end
    
    A --> C
    B --> I
    C --> D
    D --> E
    E --> H
    H --> F
    F --> G
    G --> M
    F --> N
    G --> I
    I --> J
    I --> K
    A --> L
    I --> O
    
    style H fill:#f3e5f5
    style G fill:#e8f5e9
    style I fill:#e1f5ff
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (optional, for containerized deployment)

### Backend Setup

1. **Install dependencies:**
```bash
cd application
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. **Configure environment variables:**
Create a `.env` file in the `application/` directory:

```bash
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key

# AWS Configuration
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_REGION=us-west-2

# Database Configuration (messages + RAG). Use either DATABASE_URL or DB_*.
# DATABASE_URL=postgresql://user:password@host:5432/dbname
DB_HOST=your_db_host
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=your_db_name

# AWS Services
MESSAGES_TABLE=your_dynamodb_table
TRANSCRIPT_BUCKET_NAME=your_s3_bucket
```

3. **Run the backend:**
```bash
fastapi dev main.py
# or
uvicorn main:app --reload
```

### Frontend Setup

1. **Install dependencies:**
```bash
cd frontend
npm install
```

2. **Run development server:**
```bash
npm run dev
```

3. **Build for production:**
```bash
npm run build
```

### Docker Deployment

```bash
# Build and run
./docker_build.sh
./docker_run.sh
```

## API Endpoints

### Chat Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat_api` | POST | Main chat endpoint for WaterBot |
| `/riverbot_chat_api` | POST | Chat endpoint for RiverBot persona |
| `/chat_sources_api` | POST | Get sources for previous response |
| `/chat_actionItems_api` | POST | Get action items from previous response |
| `/chat_detailed_api` | POST | Get detailed response for previous query |

### Other Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/waterbot` | GET | WaterBot HTML interface |
| `/riverbot` | GET | RiverBot HTML interface |
| `/transcribe` | WebSocket | Voice transcription endpoint |
| `/session-transcript` | POST | Download session transcript |
| `/submit_rating_api` | POST | Submit rating for a message |

## Configuration

### LLM Adapter Selection

In `application/main.py`, configure the adapter:

```python
ADAPTERS = {
    "claude.haiku": BedrockClaudeAdapter("anthropic.claude-3-haiku-20240307-v1:0"),
    "claude.sonnet": BedrockClaudeAdapter("anthropic.claude-3-sonnet-20240229-v1:0"),
    "openai-gpt4": OpenAIAdapter("gpt-4"),
}

llm_adapter = ADAPTERS["openai-gpt4"]  # or "claude.haiku"
```

### RAG / pgvector Configuration

RAG uses PostgreSQL with the pgvector extension. Set either `DATABASE_URL` (e.g. `postgresql://user:password@host:5432/dbname`) or `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` (same as for messages). The `rag_chunks` table is created by the db_init Lambda. Ingest with `application/scripts/Add_files_to_db.py` and `Add_files_to_db-spanish.py`. If migrating from an existing ChromaDB install, use `application/scripts/migrate_chroma_to_pgvector.py` once (requires `pip install chromadb` temporarily).

### RAG Parameters

- **Top K Documents**: Default is 4 (configurable in `ann_search` method)
- **Chunk Size**: 1500 characters with 150 overlap (when adding documents)
- **Embedding Model**: OpenAI `text-embedding-ada-002` (via OpenAIEmbeddings)

## RAG Pipeline Components

### 1. RAGManager
- **Purpose**: Wraps the vector store and manages RAG operations
- **Key Methods**:
  - `ann_search(query, locale)`: Performs vector similarity search (pgvector)
  - `knowledge_to_string()`: Formats retrieved documents for LLM
  - `parse_source()`: Extracts and formats source metadata

### 2. MemoryManager
- **Purpose**: Manages conversation sessions and history
- **Key Methods**:
  - `create_session()`: Creates new conversation session
  - `add_message_to_session()`: Stores messages with sources
  - `get_session_history_all()`: Retrieves full conversation history

### 3. LLM Adapters
- **OpenAIAdapter**: Uses OpenAI GPT models
- **BedrockClaudeAdapter**: Uses AWS Bedrock Claude models
- Both implement:
  - `get_llm_body()`: Builds prompt with knowledge base
  - `generate_response()`: Calls LLM API
  - `safety_checks()`: Validates user input

## Troubleshooting

### RAG Pipeline Not Working

1. **Check PostgreSQL**: Ensure `DATABASE_URL` or `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` are set and the db_init Lambda has created the `rag_chunks` table and pgvector extension.
2. **Check Embeddings**: Verify embeddings are being generated (OpenAI or Bedrock).
3. **Check Documents**: Verify documents exist in `rag_chunks` (run ingestion scripts or, for one-time migration from ChromaDB, `application/scripts/migrate_chroma_to_pgvector.py`).

### Common Issues

- **RAG not available (503)**: Configure PostgreSQL with pgvector and ensure rag_chunks is populated.
- **Empty search results**: Run Add_files_to_db.py and Add_files_to_db-spanish.py with DB_* and OPENAI_API_KEY set.
- **Embedding rate limits**: Check OpenAI API rate limits if using OpenAI embeddings.

## Project Structure

```
waterbot/
├── application/          # FastAPI backend
│   ├── main.py          # FastAPI application
│   ├── managers/        # rag_manager, pgvector_store, vector_store, memory, dynamodb, s3
│   ├── adapters/        # LLM adapters (OpenAI, Claude)
│   └── templates/       # HTML templates
├── frontend/            # React frontend
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── services/    # API services
│   │   └── assets/      # Static assets
│   └── public/          # Public assets
├── iac/                 # Infrastructure as Code
│   ├── cdk/            # AWS CDK stacks
│   └── terraform/      # Terraform configs
└── scripts/            # Deployment scripts
```

## Deployment

### AWS Deployment

1. **Set environment variables:**
```bash
export OPENAI_API_KEY="sk-..."
export SECRET_HEADER_KEY="your-secret-header"
export BASIC_AUTH_SECRET=$(echo -n "username:password" | base64)
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-west-2"
```

2. **Deploy infrastructure:**
```bash
./scripts/setup_aws_infrastructure.sh dev
```

3. **Deploy application:**
```bash
./scripts/deploy_to_aws.sh dev latest
```

### Frontend on Vercel

Set environment variable:
- `VITE_API_BASE_URL` = your backend URL

Backend must allow CORS for your Vercel domain.

## Troubleshooting

### RAG Pipeline Issues

1. **Check PostgreSQL**: Ensure DB_* are set and `rag_chunks` table exists (db_init Lambda).
2. **Verify Embeddings**: Test that embeddings are being generated.
3. **Check Documents**: Verify documents exist in `rag_chunks` (run ingestion or migration script).

### Frontend Issues

- **CSS not updating**: Clear Vite cache with `rm -rf frontend/node_modules/.vite`
- **Voice transcription not working**: Check browser permissions for microphone access

## License

See LICENSE file for details.
