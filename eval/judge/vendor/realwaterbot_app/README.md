# Vendored from S-Carradini/realwaterbot

Source: https://github.com/S-Carradini/realwaterbot
Commit: 99e7537a0fee6a35287952ff0e66a03f7e30406b (2026-08-31)
Vendored: 2026-09-09

Why vendored rather than installed as a dependency: RealWaterBot is a separate application, in
a separate repo, with its own `adapters`/`config`/`managers` top-level module names. Those names
collide with this repo's own `application/adapters`, `application/config` if both were ever on
`sys.path` at once in the same process - the same collision problem `eval/judge/generator.py`
already solves for WaterBot's own code, one level up. `eval/judge/realwater_generator.py` isolates
this directory onto `sys.path` only for the duration of one import and scrubs `sys.modules`
afterward so it never leaks into a `WaterBotGenerator` used in the same process.

WHAT IS HERE, AND WHY ONLY THIS. Only the files needed to reproduce RealWaterBot's actual
generation call:

- `adapters/base.py`, `adapters/openai_adapter.py` - `OpenAIAdapter.generate()`, unmodified.
- `config.py` - ONE LINE CHANGED from upstream: `extra = "ignore"` added to `Settings.Config`.
  Upstream default is `extra="forbid"`, which is correct for RealWaterBot's own deployment
  (owns its `.env` exclusively) but breaks immediately here - `eval/judge/cli.py:main()` already
  loads this repo's shared `.env` into `os.environ` for every subcommand, so by the time
  `Settings()` constructs it sees `AWS_*`, `HF_TOKEN`, `PROD_URL`, `REALWATER_DATABASE_URL` and
  more, none of which this model declares. `extra="ignore"` stops that from raising; it changes
  nothing about what `openai_api_key` or `database_url` actually resolve to. Everything else in
  the file, including which two fields are required, is unmodified. Its `Settings` reads
  `OPENAI_API_KEY` from this repo's own `.env` (same key, shared account) and requires
  `DATABASE_URL` to be *present* to construct without raising, but that field is never read by
  anything `realwater_generator.py` calls - retrieval uses this repo's own
  `PgVectorExactRetriever` against `REALWATER_DATABASE_URL` instead, so the same evidence
  numbering the judge panel sees is what was actually retrieved, not a second, divergent
  retrieval done by RealWaterBot's own `PgvectorStore`.
- `prompts/system_prompt_en.md`, `system_prompt_es.md` - the real, deployed system prompt.
  unmodified.

NOT vendored, deliberately: `main.py`, `routers/`, `middleware/`, `managers/memory_manager.py`
(session history - `realwater_generator.py` sends no chat history, matching the same
simplification `WaterBotGenerator` already makes and documents), `services/safety_service.py`
(moderation - also not in WaterBot's own freeze path), `managers/pgvector_store.py` and
`managers/rag_manager.py` (retrieval and prompt-assembly - this repo's own retriever and a small
reimplementation are used instead; see `realwater_generator.py` for exactly what was
reimplemented and why).

STALENESS. This is a snapshot, not a live subtree. If RealWaterBot's system prompt, adapter
call shape, or knowledge-context formatting changes upstream, this directory does not know and
must be re-vendored by hand. There is no CI check for drift. Re-copy from the commit above (or a
newer one, recorded here) if RealWaterBot changes.
