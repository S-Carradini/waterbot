# WaterBot - RAG-Powered Chatbot for Arizona Water Information

WaterBot is a Retrieval-Augmented Generation (RAG) chatbot that provides information about water in Arizona. It features a modern React frontend and a FastAPI backend with ChromaDB for vector storage, supporting both OpenAI and Claude (AWS Bedrock) LLM adapters.

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
- ChromaDB for vector storage
- PostgreSQL for message logging
- DynamoDB for ratings
- S3 for transcript storage

**LLM Adapters:**
- OpenAI GPT models
- AWS Bedrock Claude models

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

# Database Configuration
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

### RAG Parameters

- **Top K Documents**: Default is 4 (configurable in `ann_search` method)
- **Chunk Size**: 1500 characters with 150 overlap
- **Embedding Model**: OpenAI `text-embedding-ada-002`

## Project Structure

```
waterbot/
├── application/          # FastAPI backend
│   ├── main.py          # FastAPI application
│   ├── managers/        # Database and storage managers
│   ├── adapters/        # LLM adapters (OpenAI, Claude)
│   ├── docs/           # ChromaDB vector storage
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

1. **Check ChromaDB Collection**: Ensure collection name matches when documents were added
2. **Verify Embeddings**: Test that embeddings are being generated
3. **Check Documents**: Verify documents exist in ChromaDB

### Frontend Issues

- **CSS not updating**: Clear Vite cache with `rm -rf frontend/node_modules/.vite`
- **Voice transcription not working**: Check browser permissions for microphone access

## License

See LICENSE file for details.
