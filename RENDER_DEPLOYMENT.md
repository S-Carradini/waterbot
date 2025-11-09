# WaterBot Deployment Guide for Render

## Quick Deploy Options

### Option 1: Deploy from Docker Hub (Recommended)

1. **Push your image to Docker Hub:**
   ```bash
   export DOCKER_HUB_USERNAME='your-username'
   export OPENAI_API_KEY='your-openai-api-key'
   ./deploy_to_dockerhub.sh
   ```

2. **In Render Dashboard:**
   - Go to Dashboard → New → Web Service
   - Connect your Docker Hub account (or use public image)
   - Image URL: `your-username/waterbot-backend:latest`
   - Environment Variables:
     ```
     OPENAI_API_KEY=your-openai-api-key
     MESSAGES_TABLE=your-dynamodb-table-name
     TRANSCRIPT_BUCKET_NAME=your-s3-bucket-name
     DB_HOST=your-postgres-host
     DB_USER=your-postgres-user
     DB_PASSWORD=your-postgres-password
     DB_NAME=your-postgres-db-name
     ```
   - Port: `8000`
   - Health Check Path: `/` (or create a `/health` endpoint)

### Option 2: Deploy from GitHub (Build on Render)

1. **Create render.yaml in your repo root:**
   (See render.yaml file)

2. **In Render Dashboard:**
   - Go to Dashboard → New → Blueprint
   - Connect your GitHub repo
   - Render will use render.yaml for configuration

## Environment Variables Required

- `OPENAI_API_KEY` - Required for LLM and embeddings
- `MESSAGES_TABLE` - DynamoDB table name (if using)
- `TRANSCRIPT_BUCKET_NAME` - S3 bucket name (if using)
- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` - PostgreSQL connection (if using)

## RAG Functionality

The RAG vector store is built into the Docker image during build (if OPENAI_API_KEY is provided).

If RAG wasn't loaded during build, you can:
1. SSH into the Render instance
2. Run: `python scripts/Add_files_to_db.py`

## Health Check

Consider adding a `/health` endpoint to your FastAPI app for Render health checks.

