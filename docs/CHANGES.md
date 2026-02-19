# WaterBot — Changes Summary

## Why RAG Was Not Working

`ann_search()` in `bedrock_kb.py` was calling `RetrieveAndGenerate` (retrieve + generate a full answer), then `main.py` fed that answer back into the LLM again as context — the model was paraphrasing a paraphrase. Sources were also silently dropped when `url=""`.

**Fixes:** Switched to the `Retrieve` API (raw chunks only) so the LLM sees real source material. Updated `memory_manager.py` to show sources even when no URL is available.

---

## What Changed

**RAG backend** — Removed Railway PostgreSQL; AWS Bedrock Knowledge Base (`Z2NHZ8JMMQ`, us-west-2) now handles RAG. RDS still stores chat messages.

**Prod CI/CD** — New `.github/workflows/deploy-waterbot-prod.yaml`: pushes to `S-Carradini/waterbot` main auto-deploy to ECS (us-east-1) + invalidate CloudFront. Required two OIDC trust policy fixes on `GitHubActionsECSRole` (GitHub uses `environment:` sub claim, not `ref:` when a job has an environment set) and adding `cloudfront:CreateInvalidation` permission.

**Bug fixes:**
1. `main.py` — `msgID` always stale (double `increment_message_count`)
2. `main.py` — `NameError` crash on safety-check path (`data` undefined)
3. `memory_manager.py` — sources not displayed when URL is empty
4. `openai.py` — blocking LLM call stalling the async event loop
5. `InputWrapper.jsx` — unreachable cleanup block in `useEffect`
6. `main.py` — stale variable names `RAG_POSTGRES_ENABLED` / `_rag_pg_connect()`

**Dead code removed:** `adapters/claude.py`, AWS Transcribe endpoint + imports, `/transcribe` vite proxy.
