"""Tests for rubric completeness validation.

Pure unit tests: the validator touches no database and no network, so these run everywhere and
are the fastest place to pin down what "complete enough to grade against" actually means.
"""

from typing import Any

from core.services.questions.rubric_service import (
    MIN_IDEAL_ANSWER_CHARS,
    RubricValidator,
)

VALID_IDEAL_ANSWER = (
    "Subtract net debt from enterprise value: start with enterprise value, subtract total debt, "
    "add back cash and equivalents, and adjust for preferred stock and minority interest to "
    "reach equity value available to common shareholders."
)


def complete_version(**overrides: Any) -> dict[str, Any]:
    """
    Build a version payload that passes validation.

    Args:
        **overrides: Fields to override on the valid default.

    Returns:
        dict[str, Any]: Version content ready to validate.
    """
    version: dict[str, Any] = {
        "prompt": "How do you get from enterprise value to equity value?",
        "ideal_answer": VALID_IDEAL_ANSWER,
        "expected_concepts": [
            {"key": "net_debt", "label": "Net debt adjustment"},
            {"key": "cash", "label": "Treatment of cash"},
            {"key": "preferred", "label": "Preferred stock and minority interest"},
        ],
        "common_mistakes": [{"key": "sign_error", "label": "Reversing the bridge"}],
        "rubric": {"band_thresholds": {"strong": 80, "developing": 55}},
    }
    version.update(overrides)
    return version


class TestValidContent:
    """Content that is complete enough to publish."""

    def test_complete_version_is_valid(self) -> None:
        """A fully specified version passes with no errors and no warnings."""
        result = RubricValidator().validate(version=complete_version())

        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_warnings_do_not_block_publication(self) -> None:
        """A version with quality warnings is still publishable.

        Warnings describe a question that will grade acceptably but could grade better. Blocking
        on them would leave content owners unable to ship anything imperfect.
        """
        result = RubricValidator().validate(
            version=complete_version(
                expected_concepts=[{"key": "net_debt", "label": "Net debt adjustment"}],
                common_mistakes=[],
            )
        )

        assert result.warnings != []
        assert result.is_valid is True


class TestBlockingErrors:
    """Content that must not reach the graded pool."""

    def test_missing_prompt_is_rejected(self) -> None:
        """A version with no prompt cannot be published."""
        result = RubricValidator().validate(version=complete_version(prompt="   "))

        assert result.is_valid is False
        assert any("Prompt is required" in error for error in result.errors)

    def test_missing_ideal_answer_is_rejected(self) -> None:
        """Without a reference answer the grader has nothing to compare against."""
        result = RubricValidator().validate(version=complete_version(ideal_answer=""))

        assert result.is_valid is False
        assert any("Ideal answer is required" in error for error in result.errors)

    def test_short_ideal_answer_is_rejected(self) -> None:
        """A one-line ideal answer is treated as missing, not merely thin."""
        result = RubricValidator().validate(version=complete_version(ideal_answer="Subtract debt."))

        assert result.is_valid is False
        assert any(str(MIN_IDEAL_ANSWER_CHARS) in error for error in result.errors)

    def test_no_expected_concepts_is_rejected(self) -> None:
        """With no expected concepts there is nothing to score coverage against."""
        result = RubricValidator().validate(version=complete_version(expected_concepts=[]))

        assert result.is_valid is False
        assert any("expected concept" in error.lower() for error in result.errors)

    def test_duplicate_concept_keys_are_rejected(self) -> None:
        """Two concepts sharing a key would be indistinguishable in a student's history."""
        result = RubricValidator().validate(
            version=complete_version(
                expected_concepts=[
                    {"key": "net_debt", "label": "Net debt adjustment"},
                    {"key": "net_debt", "label": "Subtracting debt"},
                ]
            )
        )

        assert result.is_valid is False
        assert any("Duplicate" in error for error in result.errors)

    def test_concept_and_mistake_sharing_a_key_is_rejected(self) -> None:
        """One key cannot mean both 'got this right' and 'got this wrong' on one attempt."""
        result = RubricValidator().validate(
            version=complete_version(
                common_mistakes=[{"key": "net_debt", "label": "Forgot the net debt bridge"}]
            )
        )

        assert result.is_valid is False
        assert any("both" in error for error in result.errors)

    def test_concept_without_a_label_is_rejected(self) -> None:
        """A concept the student can never see described is not usable feedback."""
        result = RubricValidator().validate(
            version=complete_version(
                expected_concepts=[
                    {"key": "net_debt", "label": ""},
                    {"key": "cash", "label": "Treatment of cash"},
                ]
            )
        )

        assert result.is_valid is False
        assert any("missing a label" in error for error in result.errors)

    def test_inverted_band_thresholds_are_rejected(self) -> None:
        """Thresholds that do not decrease would leave no Developing band at all."""
        result = RubricValidator().validate(
            version=complete_version(rubric={"band_thresholds": {"strong": 50, "developing": 80}})
        )

        assert result.is_valid is False
        assert any("decrease" in error for error in result.errors)

    def test_out_of_range_threshold_is_rejected(self) -> None:
        """A band threshold outside 0-100 is not a score."""
        result = RubricValidator().validate(
            version=complete_version(rubric={"band_thresholds": {"strong": 140}})
        )

        assert result.is_valid is False

    def test_too_many_concepts_is_rejected(self) -> None:
        """A question testing twenty concepts cannot locate a student's specific gap."""
        result = RubricValidator().validate(
            version=complete_version(
                expected_concepts=[
                    {"key": f"concept_{index}", "label": f"Concept {index}"} for index in range(20)
                ]
            )
        )

        assert result.is_valid is False
        assert any("Too many" in error for error in result.errors)

    def test_every_error_is_reported_at_once(self) -> None:
        """Validation does not stop at the first failure.

        A content owner fixing a question should see the whole list once rather than discovering
        problems one save at a time.
        """
        result = RubricValidator().validate(
            version={"prompt": "", "ideal_answer": "", "expected_concepts": [], "rubric": {}}
        )

        assert len(result.errors) >= 3


class TestMalformedInput:
    """The validator is given stored rows and request payloads, so it must not assume shape."""

    def test_non_list_concepts_are_rejected_not_raised(self) -> None:
        """A malformed concepts field produces an error rather than an exception."""
        result = RubricValidator().validate(version=complete_version(expected_concepts="net_debt"))

        assert result.is_valid is False

    def test_missing_keys_are_treated_as_empty(self) -> None:
        """An entirely empty payload validates to errors rather than raising KeyError."""
        result = RubricValidator().validate(version={})

        assert result.is_valid is False

    def test_non_dict_concept_entry_is_rejected(self) -> None:
        """A bare string where an object is expected is reported, not crashed on."""
        result = RubricValidator().validate(
            version=complete_version(expected_concepts=["net_debt"])
        )

        assert result.is_valid is False
