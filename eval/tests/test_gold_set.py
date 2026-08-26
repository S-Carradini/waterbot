"""Tests for the five-column gold set.

The format is deliberately small, so these check the two things that carry it: that a quote can
stand in for a document name, and that "verbatim" still means verbatim.
"""

from __future__ import annotations

import json

import pytest

from eval.gold_set import (
    GoldItem,
    GoldSetError,
    gold_sources_from_quotes,
    load_gold_set,
    resolve_sources,
    validate_gold_set,
)

CORPUS = {
    "cap_factsheet.pdf": "The Central Arizona Project is a 336-mile long system serving Phoenix.",
    "groundwater_act.pdf": "The 1980 Groundwater Management Act created Active Management Areas.",
}


def an_item(**kw) -> GoldItem:
    payload = {
        "id": "q001",
        "question": "What is the Central Arizona Project?",
        "answer": "A 336-mile aqueduct.",
        "source_quote": ("The Central Arizona Project is a 336-mile long system",),
        "should_refuse": False,
        "category": "infrastructure",
    }
    payload.update(kw)
    return GoldItem(**payload)


# --- the quote replaces the filename -------------------------------------
def test_a_quote_finds_its_document():
    assert resolve_sources([an_item()], CORPUS)[0].documents == ("cap_factsheet.pdf",)


def test_a_quote_nobody_can_find_is_reported():
    """The important output: the answer is not supported by the corpus."""
    item = an_item(source_quote=("A sentence that is in no document.",))
    assert resolve_sources([item], CORPUS)[0].found is False


def test_the_gate_map_is_derived_without_a_filename_column():
    mapping = gold_sources_from_quotes([an_item()], CORPUS)
    assert mapping == {"cap_factsheet.pdf": ["q001"]}


def test_a_quote_in_two_documents_is_flagged_not_failed():
    """Duplicate ingests put the same sentence in several files; that is a corpus problem."""
    corpus = dict(CORPUS, copy_of_cap="The Central Arizona Project is a 336-mile long system.")
    assert resolve_sources([an_item()], corpus)[0].ambiguous is True


# --- verbatim still means verbatim ---------------------------------------
@pytest.mark.parametrize(
    "quote",
    [
        "The Central Arizona Project is a 336-mile long system.",     # trailing period
        "The Central Arizona Project is a 336-mile long system...",   # ellipsis
        "the central arizona project is a 336-mile long system",      # case
        "The Central Arizona Project is  a 336-mile   long system",   # spacing
    ],
)
def test_harmless_differences_still_match(quote):
    assert resolve_sources([an_item(source_quote=(quote,))], CORPUS)[0].found


@pytest.mark.parametrize(
    "quote",
    [
        "The CAP is a 336 mile system serving Phoenix.",   # paraphrase
        "The Central Arizona Project is a 500-mile long system",  # wrong number
    ],
)
def test_a_paraphrase_does_not_match(quote):
    """A quote that can drift is not evidence."""
    assert not resolve_sources([an_item(source_quote=(quote,))], CORPUS)[0].found


# --- validation ----------------------------------------------------------
def test_a_good_row_passes():
    assert validate_gold_set([an_item()], CORPUS).clean


def test_an_answerable_question_needs_a_quote():
    report = validate_gold_set([an_item(source_quote=())])
    assert "no source quote - the answer is not backed by anything" in report.errors


def test_a_refused_question_needs_no_quote():
    item = an_item(id="q002", should_refuse=True, source_quote=(), category="out of scope")
    assert validate_gold_set([item]).clean


def test_multi_hop_is_just_more_than_one_quote():
    item = an_item(source_quote=(
        "The Central Arizona Project is a 336-mile long system",
        "The 1980 Groundwater Management Act created Active Management Areas",
    ))
    report = validate_gold_set([item], CORPUS)
    assert report.clean
    assert len(gold_sources_from_quotes([item], CORPUS)) == 2


def test_duplicate_ids_are_caught():
    assert "duplicate id" in validate_gold_set([an_item(), an_item()]).errors


def test_a_missing_answer_is_caught():
    assert "no answer written" in validate_gold_set([an_item(answer="  ")]).errors


def test_categories_are_counted_so_gaps_are_visible():
    items = [an_item(id="q001", category="groundwater"),
             an_item(id="q002", category="drought policy")]
    counts = validate_gold_set(items).category_counts
    assert counts == {"groundwater": 1, "drought policy": 1}


# --- loading -------------------------------------------------------------
def test_a_bare_list_loads(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps([an_item().to_dict()]), encoding="utf-8")
    assert load_gold_set(str(path))[0].id == "q001"


def test_a_wrapped_list_loads(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps({"questions": [an_item().to_dict()]}), encoding="utf-8")
    assert len(load_gold_set(str(path))) == 1


def test_one_quote_may_be_written_as_a_plain_string(tmp_path):
    row = an_item().to_dict()
    row["source_quote"] = "The Central Arizona Project is a 336-mile long system"
    path = tmp_path / "gold.json"
    path.write_text(json.dumps([row]), encoding="utf-8")
    assert load_gold_set(str(path))[0].n_quotes == 1


def test_a_missing_file_says_so():
    with pytest.raises(GoldSetError, match="no gold set"):
        load_gold_set("nowhere.json")
