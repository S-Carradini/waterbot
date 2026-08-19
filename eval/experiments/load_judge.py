"""Import the real refusal judge without dragging in the pipeline it lives beside.

WHY THIS IS NOT JUST AN IMPORT
------------------------------
``eval/generation_metrics.py`` holds the judge under measurement, but at module
scope it also imports ragas, datasets, the pgvector store, the RAG manager and
the production OpenAI adapter - and calls ``sys.exit(1)`` if ragas is missing.
None of that is reachable from ``judge_hallucination`` itself, which only
formats a prompt and posts one chat completion.

Two ways to get the function, and only one of them is honest:

* Copy the judge into the experiment. Rejected. The moment the original is
  edited, the experiment silently measures a stale duplicate, and milestone 1's
  whole point is to characterise the judge that is actually in the harness.

* Import the real module with stand-ins for the heavy dependencies. Taken. The
  stubs satisfy import statements the judge never executes, and are removed
  again afterwards.

To keep the second option from degrading into the first by accident, the loader
verifies that what it got really did come from ``eval/generation_metrics.py``,
and returns a hash of the function's source so every artifact can record which
judge text produced it.
"""

from __future__ import annotations

import hashlib
import inspect
import sys
import types
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Tuple

# Modules that eval/generation_metrics.py imports at module scope but that
# judge_hallucination never touches. Each maps to the attribute names the
# import statements bind, so `from x import y` succeeds.
_STUBBED_MODULES: Dict[str, List[str]] = {
    "datasets": ["Dataset"],
    "ragas": ["evaluate"],
    "ragas.metrics": [
        "faithfulness",
        "answer_correctness",
        "context_precision",
        "context_recall",
    ],
    "managers": [],
    "managers.pgvector_store": ["PgVectorStore"],
    "managers.rag_manager": ["RAGManager"],
    "adapters": [],
    "adapters.openai": ["OpenAIAdapter"],
}


class _Unavailable:
    """Placeholder that fails loudly if the judge ever actually uses it.

    A silent ``None`` here would let a future edit to the judge reach a stubbed
    dependency and produce nonsense. This raises instead.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            f"{self._name} is a stub installed by eval.experiments.load_judge and "
            "was actually called. The judge now depends on the full pipeline, so "
            "this loader is no longer valid - import the module normally instead."
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<stub {self._name}>"


@contextmanager
def _stubbed_imports() -> Iterator[None]:
    """Install stubs for absent heavy dependencies, then remove exactly those."""
    installed: List[str] = []
    for module_name, attributes in _STUBBED_MODULES.items():
        if module_name in sys.modules:
            continue
        try:
            __import__(module_name)
            continue  # the real thing is available; never shadow it
        except Exception:  # noqa: BLE001 - any import failure means we stub it
            pass
        module = types.ModuleType(module_name)
        for attribute in attributes:
            setattr(module, attribute, _Unavailable(f"{module_name}.{attribute}"))
        sys.modules[module_name] = module
        installed.append(module_name)
    try:
        yield
    finally:
        for module_name in installed:
            sys.modules.pop(module_name, None)


def load_refusal_judge() -> Tuple[Callable[..., Any], str]:
    """Return ``(judge_hallucination, source_sha256)`` from the real module.

    The hash covers the function's source text only, so unrelated edits
    elsewhere in ``generation_metrics.py`` do not spuriously invalidate the
    provenance of a completed run, while any change to the judge itself does.
    """
    with _stubbed_imports():
        try:
            from eval.generation_metrics import judge_hallucination
        except SystemExit as exc:  # the module exits if ragas import fails
            raise RuntimeError(
                "eval.generation_metrics called sys.exit during import "
                f"(code {exc.code}); the dependency stubs are out of date."
            ) from exc

    source_file = inspect.getsourcefile(judge_hallucination) or ""
    if not source_file.replace("\\", "/").endswith("eval/generation_metrics.py"):
        raise RuntimeError(
            "judge_hallucination did not come from eval/generation_metrics.py "
            f"but from {source_file!r}. Refusing to measure an unknown judge."
        )

    source = inspect.getsource(judge_hallucination)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return judge_hallucination, digest
