"""Tests for validating what a grading model returns.

The model is untrusted. These tests pin what the server will and will not record against a
student: a score it cannot verify, a concept key the rubric never declared, or a band that
contradicts its own score must never reach the evidence that mastery is computed from.
"""

import json

import pytest

from core.constants.enums import Band
from core.services.ai.grading_service import GradingService, derive_band, extract_json_object
from core.services.ai.types import GradeContext, GradingError, GradingFailureKind

VALID_OUTPUT = {
    "score": 72,
    "band": "developing",
    "feedback": "You covered the net debt bridge but did not address cash equivalents.",
    "concepts_hit": ["net_debt"],
    "concepts_missed": ["cash"],
    "mistake_flags": [],
}


def context(**overrides: object) -> GradeContext:
    """
    Build a grading context with a complete rubric.

    Args:
        **overrides: Fields to override on the default.

    Returns:
        GradeContext: The context under test.
    """
    fields: dict[str, object] = {
        "question_prompt": "How do you bridge enterprise value to equity value?",
        "ideal_answer": "Subtract net debt: total debt less cash and equivalents.",
        "expected_concepts": [
            {"key": "net_debt", "label": "Net debt adjustment"},
            {"key": "cash", "label": "Treatment of cash"},
        ],
        "common_mistakes": [{"key": "sign_error", "label": "Reversing the bridge"}],
        "rubric": {"band_thresholds": {"strong": 80, "developing": 55}},
        "student_answer": "Subtract total debt and add back cash.",
        "category_name": "Enterprise & Equity Value",
        "version_number": 3,
    }
    fields.update(overrides)
    return GradeContext(**fields)  # type: ignore[arg-type]


def validate(output: object, **context_overrides: object):
    """
    Run the grading service's validation over a candidate model response.

    Args:
        output: The response to validate, serialised to JSON first.
        **context_overrides: Fields to override on the default context.

    Returns:
        GradeResult: The validated grade.
    """
    return GradingService()._validate(json.dumps(output), context(**context_overrides))


class TestWellFormedOutput:
    """A response the server is willing to record."""

    def test_a_valid_response_is_accepted(self) -> None:
        """The straightforward case produces a usable grade."""
        result = validate(VALID_OUTPUT)

        assert result.score == 72
        assert result.band == Band.DEVELOPING
        assert result.concepts_hit == ["net_debt"]
        assert result.concepts_missed == ["cash"]

    def test_feedback_is_trimmed(self) -> None:
        """Leading and trailing whitespace never reaches the interface."""
        result = validate({**VALID_OUTPUT, "feedback": "  Good coverage.  "})

        assert result.feedback == "Good coverage."

    def test_a_clean_response_records_no_quality_note(self) -> None:
        """Nothing is flagged when the model behaved."""
        result = validate(VALID_OUTPUT)

        assert result.band_disagreed is False
        assert result.dropped_keys == []


class TestMalformedOutput:
    """Responses that must be rejected rather than recorded."""

    def test_non_json_content_is_rejected(self) -> None:
        """A model that answers in prose produces a retryable schema failure."""
        with pytest.raises(GradingError) as caught:
            GradingService()._validate("Here is my assessment: the answer was good.", context())

        assert caught.value.kind == GradingFailureKind.INVALID_SCHEMA

    def test_a_json_array_is_rejected(self) -> None:
        """Valid JSON of the wrong kind is still not a grade."""
        with pytest.raises(GradingError) as caught:
            GradingService()._validate("[1, 2, 3]", context())

        assert caught.value.kind == GradingFailureKind.INVALID_SCHEMA

    def test_a_missing_score_is_rejected(self) -> None:
        """Every required field must be present."""
        payload = {key: value for key, value in VALID_OUTPUT.items() if key != "score"}

        with pytest.raises(GradingError) as caught:
            validate(payload)

        assert caught.value.kind == GradingFailureKind.INVALID_VALUES

    @pytest.mark.parametrize("score", [-1, 101, 1000])
    def test_an_out_of_range_score_is_rejected(self, score: int) -> None:
        """A score outside 0-100 is not a score, and must not reach the database."""
        with pytest.raises(GradingError):
            validate({**VALID_OUTPUT, "score": score})

    def test_a_non_integer_score_is_rejected(self) -> None:
        """A string where a number belongs is a malfunctioning model."""
        with pytest.raises(GradingError):
            validate({**VALID_OUTPUT, "score": "eighty"})

    def test_empty_feedback_is_rejected(self) -> None:
        """A grade with nothing to say is not a usable grade."""
        with pytest.raises(GradingError):
            validate({**VALID_OUTPUT, "feedback": ""})

    def test_a_grading_error_never_carries_a_score(self) -> None:
        """The failure path produces an exception, not a zero.

        This is the unit-level expression of "a grading failure never becomes a score of 0".
        """
        with pytest.raises(GradingError) as caught:
            GradingService()._validate("not json", context())

        assert not hasattr(caught.value, "score")


class TestWrappedJson:
    """Models routinely return the right object inside the wrong packaging."""

    def test_a_markdown_fenced_object_is_accepted(self) -> None:
        """A fenced response is a formatting quirk, not a grading failure.

        Discarding it would throw away a perfectly good grade and make quality depend on how
        obedient a particular model is about formatting.
        """
        result = GradingService()._validate(f"```json\n{json.dumps(VALID_OUTPUT)}\n```", context())

        assert result.score == 72

    def test_a_bare_fence_without_a_language_tag_is_accepted(self) -> None:
        """The language tag is optional in the wild."""
        result = GradingService()._validate(f"```\n{json.dumps(VALID_OUTPUT)}\n```", context())

        assert result.score == 72

    def test_surrounding_commentary_is_ignored(self) -> None:
        """Preamble and closing remarks are common and harmless."""
        result = GradingService()._validate(
            f"Here is my assessment:\n{json.dumps(VALID_OUTPUT)}\nLet me know if you need more.",
            context(),
        )

        assert result.score == 72

    def test_malformed_json_is_still_rejected(self) -> None:
        """Extraction locates the object; it must never repair a broken one.

        A model that returns truncated or invalid JSON has failed, and that has to surface as a
        failure rather than being papered over into a grade nobody can trust.
        """
        with pytest.raises(GradingError) as caught:
            GradingService()._validate('```json\n{"score": 72, "band":\n```', context())

        assert caught.value.kind == GradingFailureKind.INVALID_SCHEMA

    def test_a_truncated_object_is_rejected(self) -> None:
        """The real failure mode when a verbose model hits the output cap."""
        truncated = json.dumps(VALID_OUTPUT)[:60]

        with pytest.raises(GradingError):
            GradingService()._validate(truncated, context())

    def test_extraction_leaves_a_bare_object_untouched(self) -> None:
        """The common case must not be altered on its way through."""
        payload = json.dumps(VALID_OUTPUT)

        assert extract_json_object(payload) == payload

    def test_extraction_returns_the_input_when_no_object_is_present(self) -> None:
        """Prose with no object at all falls through to the parser, which rejects it."""
        assert extract_json_object("no json here") == "no json here"


class TestKeyReconciliation:
    """Concept keys feed mastery, so an invented one corrupts a student's history."""

    def test_undeclared_concept_keys_are_dropped(self) -> None:
        """A key the rubric never declared cannot be recorded against a student.

        Left in, ``net_debt_bridge`` would become a second concept alongside ``net_debt`` and
        silently fork the student's mastery history into two unrelated tracks.
        """
        result = validate({**VALID_OUTPUT, "concepts_hit": ["net_debt", "net_debt_bridge"]})

        assert result.concepts_hit == ["net_debt"]
        assert result.dropped_keys == ["net_debt_bridge"]

    def test_undeclared_mistake_keys_are_dropped(self) -> None:
        """The same rule applies to mistake flags."""
        result = validate({**VALID_OUTPUT, "mistake_flags": ["sign_error", "invented"]})

        assert result.mistake_flags == ["sign_error"]
        assert "invented" in result.dropped_keys

    def test_keys_are_matched_case_and_separator_insensitively(self) -> None:
        """A model returning 'Net Debt' identified the right concept.

        Dropping it would understate the student for a formatting difference.
        """
        result = validate({**VALID_OUTPUT, "concepts_hit": ["Net Debt"], "concepts_missed": []})

        assert result.concepts_hit == ["net_debt"]
        assert result.dropped_keys == []

    def test_an_unrecognised_key_is_dropped_not_coerced(self) -> None:
        """A near-miss is not snapped to the closest declared key.

        Recording the wrong concept against a student is worse than recording none: it produces
        confident, wrong feedback and moves a mastery score that should not have moved.
        """
        result = validate({**VALID_OUTPUT, "concepts_hit": ["net_debtt"], "concepts_missed": []})

        assert result.concepts_hit == []
        assert result.dropped_keys == ["net_debtt"]

    def test_duplicate_keys_are_collapsed(self) -> None:
        """One concept counted twice would double its weight in aggregation."""
        result = validate(
            {**VALID_OUTPUT, "concepts_hit": ["net_debt", "net_debt"], "concepts_missed": []}
        )

        assert result.concepts_hit == ["net_debt"]

    def test_a_concept_cannot_be_both_hit_and_missed(self) -> None:
        """When a model claims both, the conservative reading wins."""
        result = validate(
            {**VALID_OUTPUT, "concepts_hit": ["net_debt"], "concepts_missed": ["net_debt"]}
        )

        assert result.concepts_hit == []
        assert result.concepts_missed == ["net_debt"]

    def test_a_question_with_no_declared_keys_drops_everything(self) -> None:
        """Nothing can be credited against a rubric that declares nothing."""
        result = validate(VALID_OUTPUT, expected_concepts=[])

        assert result.concepts_hit == []
        assert result.concepts_missed == []


class TestBandDerivation:
    """The band is derived from the score, never taken from the model."""

    def test_the_band_is_derived_from_the_score(self) -> None:
        """A model claiming 'strong' for a score of 40 does not get to say so.

        A score and a band that contradict each other cannot be resolved after the fact, and
        would render as an incoherent grade panel.
        """
        result = validate({**VALID_OUTPUT, "score": 40, "band": "strong"})

        assert result.band == Band.NEEDS_WORK
        assert result.band_disagreed is True

    def test_agreement_is_not_flagged(self) -> None:
        """No quality note when the model's band matches the derived one."""
        result = validate({**VALID_OUTPUT, "score": 90, "band": "strong"})

        assert result.band == Band.STRONG
        assert result.band_disagreed is False

    def test_display_casing_is_treated_as_agreement(self) -> None:
        """'Needs Work' and 'needs_work' are the same claim."""
        result = validate({**VALID_OUTPUT, "score": 20, "band": "Needs Work"})

        assert result.band == Band.NEEDS_WORK
        assert result.band_disagreed is False

    def test_rubric_thresholds_override_the_default(self) -> None:
        """A question graded on a harder curve produces a lower band for the same score."""
        result = validate(
            {**VALID_OUTPUT, "score": 82},
            rubric={"band_thresholds": {"strong": 90, "developing": 60}},
        )

        assert result.band == Band.DEVELOPING

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (100, Band.STRONG),
            (80, Band.STRONG),
            (79, Band.DEVELOPING),
            (55, Band.DEVELOPING),
            (54, Band.NEEDS_WORK),
            (0, Band.NEEDS_WORK),
        ],
    )
    def test_default_band_boundaries(self, score: int, expected: Band) -> None:
        """The default floors are inclusive at the boundary."""
        assert derive_band(score, {"strong": 80, "developing": 55}) == expected


class TestBandThresholdResolution:
    """A rubric must not be able to produce a nonsensical curve."""

    def test_a_missing_rubric_uses_the_product_default(self) -> None:
        """A question with no thresholds still bands consistently."""
        assert context(rubric={}).band_thresholds() == {"strong": 80, "developing": 55}

    def test_a_malformed_thresholds_block_is_ignored(self) -> None:
        """A string where an object belongs falls back rather than crashing a grade."""
        assert context(rubric={"band_thresholds": "high"}).band_thresholds() == {
            "strong": 80,
            "developing": 55,
        }

    def test_an_out_of_range_threshold_is_ignored(self) -> None:
        """Only the bad value falls back; a valid sibling is kept."""
        resolved = context(
            rubric={"band_thresholds": {"strong": 500, "developing": 60}}
        ).band_thresholds()

        assert resolved == {"strong": 80, "developing": 60}

    def test_a_boolean_threshold_is_ignored(self) -> None:
        """True is an int in Python; it is not a score."""
        resolved = context(rubric={"band_thresholds": {"strong": True}}).band_thresholds()

        assert resolved["strong"] == 80
