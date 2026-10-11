"""The system under test, behind the `freeze.Generator` protocol.

Wraps the application's own OpenAI adapter so the frozen answers are produced by the SAME code
path production uses, not a reimplementation. A freeze whose generator differs from the deployed
system measures the freezer, not the system.

One detail is load-bearing and easy to get wrong. `get_llm_body()` has no `user_query` parameter:
it builds messages as `[system_prompt(kb_data)] + chat_history`, so the question reaches the
model ONLY through `chat_history`. Production supplies the real session history, which already
contains the user turn. Passing an empty history sends the model a system prompt and no question
at all - a bug that was live in `eval/generation_metrics.py` and made every generation metric
score an answer to nothing. The shape below mirrors production.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from eval.judge.freeze import Generation
from eval.judge.schemas import Passage

# `application/` is a top-level package root, not a subpackage of the repo, so `adapters.openai`
# only imports once it is on the path. Done here rather than pushed onto the caller so the CLI
# runs from the repo root with no PYTHONPATH ceremony.
_APPLICATION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "application")
if os.path.isdir(_APPLICATION) and _APPLICATION not in sys.path:
    sys.path.insert(0, _APPLICATION)


@dataclass
class WaterBotGenerator:
    """Calls the real application pipeline for one question and its retrieved passages."""

    model_id: str = "gpt-4.1"
    temperature: float = 0.0
    endpoint_type: str = "default"
    _adapter: Any = None

    def __post_init__(self) -> None:
        if self._adapter is None:
            from adapters.openai import OpenAIAdapter

            self._adapter = OpenAIAdapter(model_id=self.model_id)

    def _kb_data(self, passages: Sequence[Passage]) -> str:
        """Render the passages the judge will also see.

        Built here rather than by calling `RAGManager.knowledge_to_string` on a fresh search,
        because the freeze has already retrieved and the judge must be shown the SAME passages
        the generator saw. Re-searching would break that guarantee for the sake of formatting.
        """
        blocks = []
        for p in passages:
            blocks.append(f"[{p.evidence_id}] Source: {p.canonical_doc_id}\n{p.text}")
        return "\n\n".join(blocks)

    def generate(self, question: str, passages: Sequence[Passage]) -> Generation:
        started = time.perf_counter()

        async def _run() -> str:
            body = await self._adapter.get_llm_body(
                chat_history=[{"role": "user", "content": question}],
                kb_data=self._kb_data(passages),
                temperature=self.temperature,
                endpoint_type=self.endpoint_type,
            )
            return await self._adapter.generate_response(body)

        answer = asyncio.run(_run())
        answer = (answer or "").replace("<br>", "\n").replace("</p><p>", "\n\n")
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        usage = getattr(self._adapter, "last_usage", None) or {}
        # Cost is left at 0.0 rather than invented. This project's price table is assumed, never
        # verified, and a fabricated per-response cost would propagate into the run manifest as
        # though it were measured. Token counts are recorded by the caller instead.
        return Generation(
            answer=answer,
            citations=[p.canonical_doc_id for p in passages],
            latency_ms=elapsed_ms,
            cost_usd=0.0,
        )

    @property
    def last_usage(self) -> dict:
        return getattr(self._adapter, "last_usage", None) or {}
