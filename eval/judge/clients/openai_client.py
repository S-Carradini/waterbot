"""Real OpenAI judge adapter.

Deliberately thinner than ``application.adapters.openai.OpenAIAdapter``, which
also constructs ``OpenAIEmbeddings`` in its ``__init__``. The refusal judge
never embeds anything, so building an embeddings client to run it would mean
requiring more configuration than the measurement needs, and would charge for a
capability it does not use.

The ``openai`` import is deferred to construction time on purpose: this module
must be importable in environments without the SDK installed, so that the
experiment's fake path, its statistics, and its tests all run with no provider
dependency at all.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# Snapshot-pinned by default per CLAUDE.md invariant 6: model ids are pinned
# snapshot strings, never aliases. An alias silently repoints under you, which
# would turn a judge-stability measurement into a model-migration measurement.
DEFAULT_JUDGE_MODEL = "gpt-4.1-2025-04-14"

# The alias the existing harness uses (eval/generation_metrics.py:41). Recorded
# so a run can state which concrete snapshot an alias resolved to at the time.
HARNESS_ALIAS = "gpt-4.1"


class OpenAIJudgeClient:
    """Judge adapter backed by the real API.

    Satisfies ``JudgeAdapter``: exposes ``model_id`` and ``client``, which is
    all ``judge_hallucination`` reads.
    """

    def __init__(self, model_id: str = DEFAULT_JUDGE_MODEL, api_key: Optional[str] = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The 'openai' package is not installed, so the live judge cannot run. "
                "Install it (pip install openai) or use --client fake."
            ) from exc

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set, so the live judge cannot run. "
                "Set it, or use --client fake."
            )

        self.model_id = model_id
        self.client: Any = OpenAI(api_key=key)
