"""RealWaterBot's own generation call, reached through `RealWaterGenerator`.

No network. `_adapter` is injected directly - the same pattern `WaterBotGenerator` would use if
it had a test - so `generate()` is exercised without constructing the real vendored
`OpenAIAdapter` or calling out to OpenAI.

The one thing worth a real (still network-free) exercise is `_isolated_import`: that a
`RealWaterGenerator` in the same process as a `WaterBotGenerator` neither clobbers nor inherits
the other's `adapters`/`config` modules. Constructing the vendored `OpenAIAdapter` only builds an
`openai.OpenAI` client object - it does not contact the network - so this can run with fake
credentials.
"""
from __future__ import annotations

import sys

import pytest

from eval.judge.realwater_generator import RealWaterGenerator, strip_citations
from eval.judge.schemas import Passage


def a_passage(evidence_id=1, doc="Buyer_Advisory.pdf", text="Buyers should review the contract."):
    return Passage(
        evidence_id=evidence_id, canonical_doc_id=doc, chunk_id=f"chunk{evidence_id}",
        text=text, retrieval_rank=evidence_id - 1, retrieval_score=0.9,
    )


class FakeAdapter:
    """Stands in for the vendored `OpenAIAdapter`. Captures what it was called with."""

    def __init__(self, response_text='The buyer should review the ADRE report. [Source 1]'):
        self.calls = []
        self._response_text = response_text

    async def generate(self, messages, temperature=0.0):
        self.calls.append({"messages": messages, "temperature": temperature})
        return self._response_text


def a_generator(**kwargs):
    fake = FakeAdapter(**{k: v for k, v in kwargs.items() if k == "response_text"})
    gen = RealWaterGenerator(
        model_id="gpt-4.1", temperature=0.0, locale=kwargs.get("locale", "en"), _adapter=fake)
    return gen, fake


# ---------------------------------------------------------------------------
# strip_citations - copied from realwaterbot's rag_manager.py; pinned here so upstream drift
# in this repo's own copy is caught even though the source it was copied from cannot be.
# ---------------------------------------------------------------------------
def test_strip_citations_removes_a_single_source_marker():
    assert strip_citations("The answer is X. [Source 1]") == "The answer is X."


def test_strip_citations_removes_a_multi_source_marker():
    assert strip_citations("X and Y. [Sources 1, 2]") == "X and Y."


def test_strip_citations_collapses_the_double_space_the_marker_leaves_behind():
    assert strip_citations("X. [Source 1] The next sentence.") == "X. The next sentence."


def test_strip_citations_is_a_no_op_on_text_without_markers():
    assert strip_citations("Nothing to strip here.") == "Nothing to strip here."


# ---------------------------------------------------------------------------
# Message shape
# ---------------------------------------------------------------------------
def test_messages_carry_the_real_system_prompt_and_the_question_only():
    gen, fake = a_generator()
    gen.generate("What is an AMA?", [a_passage()])
    messages = fake.calls[0]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "What is an AMA?"}
    # The real, deployed prompt - not a stand-in. If this string moves, the vendored file moved.
    assert "Real Water Bot" in messages[0]["content"]


def test_no_chat_history_is_sent():
    """Matches the same simplification WaterBotGenerator already makes and documents."""
    gen, fake = a_generator()
    gen.generate("q", [a_passage()])
    roles = [m["role"] for m in fake.calls[0]["messages"]]
    assert roles == ["system", "user"]


def test_passages_render_as_numbered_source_blocks_in_the_system_prompt():
    gen, fake = a_generator()
    passages = [a_passage(evidence_id=1, doc="Doc_A.pdf", text="Passage A text."),
                a_passage(evidence_id=2, doc="Doc_B.pdf", text="Passage B text.")]
    gen.generate("q", passages)
    system = fake.calls[0]["messages"][0]["content"]
    assert "[Source 1: Doc_A.pdf]\nPassage A text." in system
    assert "[Source 2: Doc_B.pdf]\nPassage B text." in system
    assert "KNOWLEDGE BASE CONTEXT" in system


def test_no_passages_means_no_knowledge_block():
    gen, fake = a_generator()
    gen.generate("q", [])
    system = fake.calls[0]["messages"][0]["content"]
    assert "KNOWLEDGE BASE CONTEXT" not in system


def test_temperature_is_passed_through():
    fake = FakeAdapter()
    gen = RealWaterGenerator(temperature=0.0, _adapter=fake)
    gen.generate("q", [a_passage()])
    assert fake.calls[0]["temperature"] == 0.0


def test_spanish_locale_loads_the_spanish_prompt():
    import os

    from eval.judge.realwater_generator import _VENDOR_DIR

    gen, fake = a_generator(locale="es")
    gen.generate("q", [a_passage()])
    system = fake.calls[0]["messages"][0]["content"]
    with open(os.path.join(_VENDOR_DIR, "prompts", "system_prompt_es.md"), encoding="utf-8") as fh:
        assert fh.read() in system


# ---------------------------------------------------------------------------
# generate() end to end (fake adapter)
# ---------------------------------------------------------------------------
def test_generate_strips_citation_markers_from_the_answer():
    gen, fake = a_generator(response_text="Review the ADRE report. [Source 1]")
    result = gen.generate("q", [a_passage()])
    assert result.answer == "Review the ADRE report."


def test_generate_returns_the_passage_doc_ids_as_citations():
    gen, fake = a_generator()
    passages = [a_passage(evidence_id=1, doc="Doc_A.pdf"), a_passage(evidence_id=2, doc="Doc_B.pdf")]
    result = gen.generate("q", passages)
    assert result.citations == ["Doc_A.pdf", "Doc_B.pdf"]


def test_generate_does_not_invent_a_cost():
    """Same reasoning as WaterBotGenerator: the price table is assumed, never verified."""
    gen, fake = a_generator()
    result = gen.generate("q", [a_passage()])
    assert result.cost_usd == 0.0


def test_generate_records_a_positive_latency():
    gen, fake = a_generator()
    result = gen.generate("q", [a_passage()])
    assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# Import isolation - the reason this is a separate module from generator.py's own tests
# ---------------------------------------------------------------------------
def test_isolated_import_does_not_permanently_add_the_vendor_dir_to_sys_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-construction-only")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    from eval.judge.realwater_generator import _VENDOR_DIR, _isolated_import

    assert _VENDOR_DIR not in sys.path
    with _isolated_import(_VENDOR_DIR) as OpenAIAdapter:
        assert _VENDOR_DIR in sys.path
        assert OpenAIAdapter.__module__ == "adapters.openai_adapter"
    assert _VENDOR_DIR not in sys.path


def test_isolated_import_restores_whatever_adapters_module_was_there_before(monkeypatch):
    """If something in this process (e.g. WaterBotGenerator) already populated `adapters` /
    `config`, a RealWaterGenerator built afterward must not leave those permanently swapped."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-construction-only")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    from eval.judge.realwater_generator import _VENDOR_DIR, _isolated_import

    sentinel = object()
    monkeypatch.setitem(sys.modules, "adapters", sentinel)
    monkeypatch.setitem(sys.modules, "config", sentinel)

    with _isolated_import(_VENDOR_DIR) as OpenAIAdapter:
        # During the import, the sentinel must NOT be what the vendored code sees.
        assert sys.modules["adapters"] is not sentinel
        OpenAIAdapter(model_id="gpt-4.1")  # constructs the OpenAI() client; no network call

    # Restored exactly, for whatever ran next in this process (e.g. a real WaterBotGenerator).
    assert sys.modules["adapters"] is sentinel
    assert sys.modules["config"] is sentinel


def test_real_construction_without_an_injected_adapter_uses_the_vendored_class(monkeypatch):
    """No `_adapter` passed - exercises the real `__post_init__` path once, still no network."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-construction-only")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    gen = RealWaterGenerator(model_id="gpt-4.1", temperature=0.0)
    assert type(gen._adapter).__module__ == "adapters.openai_adapter"
    assert type(gen._adapter).__name__ == "OpenAIAdapter"
    # Scrubbed again once construction finished - nothing left registered under the bare name.
    assert "adapters.openai_adapter" not in sys.modules
