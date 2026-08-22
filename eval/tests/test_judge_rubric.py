"""
Tests for rubric loading, validation, and applicability.

The rubric is the judge's definition of quality. A malformed one produces
scores that look fine and mean nothing, so the loader is expected to refuse
rather than cope. These tests pin both the refusals and the applicability
rules that the prompt builder and the aggregator must agree on.

No API access. Run with:  pytest eval/tests/ -v
"""
import os
import sys
import textwrap

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from eval.judge.rubric import (  # noqa: E402
    DEFAULT_RUBRIC_PATH,
    Dimension,
    Rubric,
    RubricError,
    load_rubric,
    render_for_prompt,
)

VALID_YAML = """
version: "9.9.9-test"
status: "TEST"
scale:
  levels: [1, 2, 3, 4]
categories: [general_policy, temporal_realtime, out_of_scope_negative]
dimensions:
  - name: grounding
    question: "Supported by evidence?"
    applies_to: answerable
    requires_evidence: true
    anchors:
      4: "fully supported"
      3: "mostly supported"
      2: "one unsupported claim"
      1: "central claims unsupported"
  - name: refusal_appropriateness
    question: "Right decision to answer or decline?"
    applies_to: all
    anchors:
      4: "correct and well executed"
      3: "correct but poorly executed"
      2: "partially wrong"
      1: "wrong, confidently"
failure_modes:
  - name: entity_substitution
    description: "wrong entity"
"""


def write_rubric(tmp_path, text):
    p = tmp_path / "r.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return str(p)


class TestShippedRubric:
    """The rubric that actually ships must satisfy its own design rules."""

    def test_loads(self):
        r = load_rubric()
        assert r.version
        assert len(r.dimensions) == 5

    def test_expected_dimensions_present(self):
        names = load_rubric().dimension_names
        for expected in ("grounding", "correctness", "refusal_appropriateness",
                         "citation_validity", "temporal_integrity"):
            assert expected in names

    def test_every_dimension_has_all_four_anchors(self):
        for d in load_rubric().dimensions:
            assert sorted(d.anchors) == [1, 2, 3, 4], d.name
            for level, text in d.anchors.items():
                assert len(text.strip()) > 20, f"{d.name} level {level} anchor is too thin"

    def test_refusal_is_scored_on_every_category(self):
        """Two-sided refusal scoring is the point; a one-sided version would
        make a system that refuses everything look perfect."""
        r = load_rubric()
        d = r.get("refusal_appropriateness")
        assert d.applies_to == "all"
        for cat in r.categories:
            assert d.applies(cat), cat

    def test_negatives_score_only_refusal(self):
        r = load_rubric()
        assert r.applicable_names("out_of_scope_negative") == ["refusal_appropriateness"]

    def test_temporal_dimension_is_narrow(self):
        r = load_rubric()
        d = r.get("temporal_integrity")
        assert d.applies("temporal_realtime")
        assert not d.applies("general_policy")

    def test_declares_itself_unpiloted(self):
        """Until humans pilot it, callers must be able to detect that."""
        assert load_rubric().is_piloted is False

    def test_failure_modes_present_and_named(self):
        fms = load_rubric().failure_modes
        assert len(fms) >= 5
        names = [f.name for f in fms]
        assert "entity_substitution" in names
        assert len(names) == len(set(names))


class TestApplicability:
    def test_all_applies_everywhere(self):
        d = Dimension("x", "q?", "all", {1: "a", 2: "b", 3: "c", 4: "d"})
        assert d.applies("general_policy") and d.applies("out_of_scope_negative")

    def test_answerable_excludes_negatives(self):
        d = Dimension("x", "q?", "answerable", {1: "a", 2: "b", 3: "c", 4: "d"})
        assert d.applies("general_policy")
        assert not d.applies("out_of_scope_negative")

    def test_explicit_category_list(self):
        d = Dimension("x", "q?", ["temporal_realtime"], {1: "a", 2: "b", 3: "c", 4: "d"})
        assert d.applies("temporal_realtime")
        assert not d.applies("multi_hop")

    def test_citations_required_dimension_skipped_without_citations(self):
        """Scoring citation validity on an uncited answer would invent a number."""
        d = Dimension("cv", "q?", "answerable", {1: "a", 2: "b", 3: "c", 4: "d"},
                      requires_citations=True)
        assert d.applies("general_policy", has_citations=True)
        assert not d.applies("general_policy", has_citations=False)

    def test_has_citations_ignored_when_not_required(self):
        d = Dimension("g", "q?", "answerable", {1: "a", 2: "b", 3: "c", 4: "d"})
        assert d.applies("general_policy", has_citations=False)

    def test_bad_applies_to_raises_at_use(self):
        d = Dimension("x", "q?", 42, {1: "a", 2: "b", 3: "c", 4: "d"})
        with pytest.raises(RubricError, match="unusable applies_to"):
            d.applies("general_policy")


class TestValidation:
    def test_valid_rubric_loads(self, tmp_path):
        r = load_rubric(write_rubric(tmp_path, VALID_YAML))
        assert r.version == "9.9.9-test"
        assert len(r.dimensions) == 2

    def test_missing_file(self, tmp_path):
        with pytest.raises(RubricError, match="not found"):
            load_rubric(str(tmp_path / "nope.yaml"))

    def test_missing_version_rejected(self, tmp_path):
        bad = VALID_YAML.replace('version: "9.9.9-test"', "")
        with pytest.raises(RubricError, match="missing 'version'"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_no_dimensions_rejected(self, tmp_path):
        y = 'version: "1"\nstatus: "t"\ndimensions: []\n'
        with pytest.raises(RubricError, match="no dimensions"):
            load_rubric(write_rubric(tmp_path, y))

    def test_missing_anchor_rejected(self, tmp_path):
        bad = VALID_YAML.replace('      2: "one unsupported claim"\n', "")
        with pytest.raises(RubricError, match=r"missing anchors for level\(s\) \[2\]"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_empty_anchor_rejected(self, tmp_path):
        bad = VALID_YAML.replace('      3: "mostly supported"', '      3: ""')
        with pytest.raises(RubricError, match="anchor 3 is empty"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_anchor_outside_range_rejected(self, tmp_path):
        bad = VALID_YAML.replace('      1: "central claims unsupported"',
                                 '      1: "x"\n      5: "extra"')
        with pytest.raises(RubricError, match="outside 1-4"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_odd_scale_rejected(self, tmp_path):
        """The even scale is deliberate; an odd one gives judges a safe middle."""
        bad = VALID_YAML.replace("levels: [1, 2, 3, 4]", "levels: [1, 2, 3, 4, 5]")
        with pytest.raises(RubricError, match="deliberate design choice"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_duplicate_dimension_rejected(self, tmp_path):
        # Insert a second 'grounding' into the dimensions list, before the
        # failure_modes key, keeping YAML indentation intact.
        dupe = (
            '  - name: grounding\n'
            '    question: "dupe"\n'
            '    applies_to: all\n'
            '    anchors:\n'
            '      4: "a"\n      3: "b"\n      2: "c"\n      1: "d"\n'
        )
        bad = VALID_YAML.replace("failure_modes:", dupe + "failure_modes:")
        with pytest.raises(RubricError, match="duplicate dimension"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_unknown_applies_to_string_rejected(self, tmp_path):
        bad = VALID_YAML.replace("applies_to: answerable", "applies_to: sometimes")
        with pytest.raises(RubricError, match="must be 'all', 'answerable'"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_applies_to_unknown_category_rejected(self, tmp_path):
        """A typo'd category would silently make a dimension never score."""
        bad = VALID_YAML.replace("applies_to: answerable", "applies_to: [tempora_realtime]")
        with pytest.raises(RubricError, match="not declared"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_missing_question_rejected(self, tmp_path):
        bad = VALID_YAML.replace('    question: "Supported by evidence?"\n', "")
        with pytest.raises(RubricError, match="missing 'question'"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_duplicate_failure_mode_rejected(self, tmp_path):
        bad = VALID_YAML + '  - name: entity_substitution\n    description: "dupe"\n'
        with pytest.raises(RubricError, match="duplicate failure_mode"):
            load_rubric(write_rubric(tmp_path, bad))

    def test_missing_failure_mode_name_rejected(self, tmp_path):
        bad = VALID_YAML + '  - description: "nameless"\n'
        with pytest.raises(RubricError, match="missing 'name'"):
            load_rubric(write_rubric(tmp_path, bad))


class TestRendering:
    def test_renders_all_anchors_verbatim(self):
        r = load_rubric()
        text = render_for_prompt(r, ["grounding"])
        d = r.get("grounding")
        for level in (1, 2, 3, 4):
            assert d.anchor(level) in text, f"anchor {level} was not reproduced verbatim"

    def test_renders_highest_level_first(self):
        r = load_rubric()
        text = render_for_prompt(r, ["grounding"])
        assert text.index("4 = ") < text.index("1 = ")

    def test_subset_rendering_excludes_others(self):
        text = render_for_prompt(load_rubric(), ["grounding"])
        assert "grounding" in text
        assert "temporal_integrity" not in text

    def test_default_renders_every_dimension(self):
        r = load_rubric()
        text = render_for_prompt(r)
        for name in r.dimension_names:
            assert name in text

    def test_get_unknown_dimension_raises(self):
        with pytest.raises(KeyError):
            load_rubric().get("no_such_dimension")
