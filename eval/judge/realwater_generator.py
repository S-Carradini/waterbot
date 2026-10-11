"""The RealWaterBot system under test, behind the `freeze.Generator` protocol.

Companion to `generator.py`'s `WaterBotGenerator`. Until 2026-09-09 no such class existed, so
any freeze run with `--corpus realwater` still called WaterBot's own generator - it answered
using passages retrieved from RealWaterBot's database, but with WaterBot's system prompt and
WaterBot's OpenAI call shape. That measured "WaterBot's chat logic given RealWaterBot's corpus,"
not RealWaterBot's own chatbot, and would have made any WaterBot-vs-RealWater comparison in the
paper compare one generator against itself. See decisions.md for the entry this closes.

WHY A SEPARATE MODULE, NOT A BRANCH INSIDE `WaterBotGenerator`. RealWaterBot is vendored code
(`eval/judge/vendor/realwaterbot_app/`, see its README for exactly what and why) with its own
`adapters`/`config` top-level module names, identical in name to this repo's own
`application/adapters`, `application/config`. Importing both into the same Python process risks
one silently shadowing the other in `sys.modules`. `_isolated_import` below prepends the vendored
directory to `sys.path`, imports what is needed, then removes both the path entry and every
module name it introduced - so a `WaterBotGenerator` and a `RealWaterGenerator` can coexist in one
process (e.g. one script freezing both corpora back to back) without either seeing the other's
`adapters` or `config`.

WHAT IS REPRODUCED FROM PRODUCTION, AND WHAT IS NOT.
  - The real system prompt (`vendor/realwaterbot_app/prompts/system_prompt_en.md`), unmodified.
  - The real `OpenAIAdapter.generate()` call, unmodified, reading the SAME `OPENAI_API_KEY` this
    repo already uses (shared account, matching env var name - see the vendor README).
  - `strip_citations()` and the knowledge-context template are REIMPLEMENTED here, copied by hand
    from `managers/rag_manager.py` at the vendored commit, rather than importing that module -
    importing it would pull in `managers.pgvector_store` and `mappings.knowledge_sources`, which
    this generator does not use (see below). If RealWaterBot's prompt template changes upstream,
    this copy will silently drift; there is no test that would catch it.
  - Retrieval is NOT RealWaterBot's own `PgvectorStore`. This repo's own `PgVectorExactRetriever`
    (`corpus_retriever.py`) retrieves the passages, against `REALWATER_DATABASE_URL`, exactly as
    it does for every other corpus - because the freezer's whole contract is that the judge sees
    the SAME passages the generator saw, and evidence numbering has to come from one place.
  - Chat history and the safety-moderation check are both skipped, matching the same
    simplification `WaterBotGenerator` already makes for WaterBot: one question, no prior turns,
    no moderation call. A single-turn eval question has no prior turns to send regardless.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, List, Sequence

from eval.judge.freeze import Generation
from eval.judge.schemas import Passage

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "realwaterbot_app")

# Copied verbatim from realwaterbot's managers/rag_manager.py (vendored commit, see the vendor
# README) rather than imported, so this module does not have to pull in PgvectorStore or
# knowledge_sources - see the module docstring.
_CITATION_RE = re.compile(r'\s*\[\s*Sources?\b[^\]]*\]', re.IGNORECASE)


def strip_citations(text: str) -> str:
    """Remove inline "[Source N]" markers, exactly as production does before showing a user."""
    cleaned = _CITATION_RE.sub('', text)
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    cleaned = re.sub(r' +([.,!?;:])', r'\1', cleaned)
    return cleaned.strip()


@contextmanager
def _isolated_import(vendor_dir: str) -> Iterator[Any]:
    """Import the vendored `OpenAIAdapter` without leaking `adapters`/`config` into `sys.modules`.

    Saves whatever WaterBot's own `application/` may already have registered under these names,
    swaps in the vendored copies for the duration of the import, then restores exactly what was
    there before - so this can run before or after a `WaterBotGenerator` in the same process with
    neither one seeing the other's modules.
    """
    names = ("adapters", "adapters.base", "adapters.openai_adapter", "config")
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)

    path_inserted = vendor_dir not in sys.path
    if path_inserted:
        sys.path.insert(0, vendor_dir)
    try:
        from adapters.openai_adapter import OpenAIAdapter  # vendored, not this repo's own

        yield OpenAIAdapter
    finally:
        if path_inserted:
            try:
                sys.path.remove(vendor_dir)
            except ValueError:
                pass
        for name in names:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]


@dataclass
class RealWaterGenerator:
    """Calls RealWaterBot's real generation call for one question and its retrieved passages."""

    model_id: str = "gpt-4.1"
    temperature: float = 0.0
    locale: str = "en"
    _adapter: Any = None  # settable directly in tests - see test_realwater_generator.py

    def __post_init__(self) -> None:
        if self._adapter is None:
            with _isolated_import(_VENDOR_DIR) as OpenAIAdapter:
                self._adapter = OpenAIAdapter(model_id=self.model_id)

    def _system_prompt(self) -> str:
        path = os.path.join(_VENDOR_DIR, "prompts", f"system_prompt_{self.locale}.md")
        if not os.path.exists(path):
            path = os.path.join(_VENDOR_DIR, "prompts", "system_prompt_en.md")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def _knowledge_block(self, passages: Sequence[Passage]) -> str:
        """`[Source i: doc]\\ncontent` per passage - RAGManager._chunks_to_text's exact shape,
        renumbered 1..n in retrieval order to match what that function does, but built from THIS
        repo's `Passage` objects (which already carry the evidence_id the judge will cite) rather
        than RealWaterBot's own chunk dicts."""
        if not passages:
            return ""
        blocks = [f"[Source {p.evidence_id}: {p.canonical_doc_id}]\n{p.text}" for p in passages]
        return "\n\n".join(blocks)

    def _messages(self, question: str, passages: Sequence[Passage]) -> List[dict]:
        system_prompt = self._system_prompt()
        knowledge_text = self._knowledge_block(passages)
        full_system = system_prompt
        if knowledge_text:
            full_system += (
                "\n\n--- KNOWLEDGE BASE CONTEXT ---\n"
                "Use the following information to answer the user's question. "
                "Do not include inline citation markers like \"[Source 1]\" in "
                "your answer - sources are shown to the user separately.\n\n"
                f"{knowledge_text}\n"
                "--- END CONTEXT ---"
            )
        return [
            {"role": "system", "content": full_system},
            {"role": "user", "content": question},
        ]

    def generate(self, question: str, passages: Sequence[Passage]) -> Generation:
        started = time.perf_counter()
        messages = self._messages(question, passages)

        async def _run() -> str:
            return await self._adapter.generate(messages, temperature=self.temperature)

        answer = strip_citations(asyncio.run(_run()) or "")
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # Cost left at 0.0, not invented - same reasoning as WaterBotGenerator: this project's
        # price table is assumed, never verified, and a fabricated per-response cost would
        # propagate into the run manifest as though it were measured.
        return Generation(
            answer=answer,
            citations=[p.canonical_doc_id for p in passages],
            latency_ms=elapsed_ms,
            cost_usd=0.0,
        )
