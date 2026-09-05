"""Rubric completeness validation.

A question enters the graded pool only when its version carries enough material for the grader to
produce a defensible score. The database enforces the floor — a published version must have a
prompt, an ideal answer and at least one expected concept — but the floor is not the standard.
This service is the standard: it explains *why* a version is not publishable, in language a
content owner can act on, and separates hard errors from quality warnings so a marginal question
can still ship when someone decides it should.

Kept out of the controller because publishing, previewing and bulk seeding all need the same
answer, and a rule that lived in one route handler would drift out of step with the other two.
"""

from typing import Any

from core import logger

logging = logger(__name__)

MIN_EXPECTED_CONCEPTS = 1
RECOMMENDED_EXPECTED_CONCEPTS = 3
MIN_IDEAL_ANSWER_CHARS = 80
RECOMMENDED_IDEAL_ANSWER_CHARS = 200
MIN_PROMPT_CHARS = 15
MAX_EXPECTED_CONCEPTS = 12
BAND_ORDER = ("strong", "developing")


class RubricValidationResult:
    """The outcome of validating one question version's grading content."""

    def __init__(self, errors: list[str], warnings: list[str]) -> None:
        """
        Hold the errors and warnings produced by a validation pass.

        Args:
            errors: Conditions that block publication.
            warnings: Quality concerns that do not block publication.
        """
        self.errors = errors
        self.warnings = warnings

    @property
    def is_valid(self) -> bool:
        """
        Report whether the version may be published.

        Warnings deliberately do not block: they describe a question that will grade acceptably
        but could grade better, and blocking on them would leave content owners unable to ship.

        Returns:
            bool: True when no blocking error was found.
        """
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        """
        Render the result in the shape the API returns.

        Returns:
            dict[str, Any]: Keys ``is_valid``, ``errors`` and ``warnings``.
        """
        return {"is_valid": self.is_valid, "errors": self.errors, "warnings": self.warnings}


class RubricValidator:
    """Checks whether a question version is complete enough to grade against."""

    def validate(self, *, version: dict[str, Any]) -> RubricValidationResult:
        """
        Validate a version's grading content for completeness and internal consistency.

        Runs every check rather than stopping at the first failure, so a content owner fixing a
        question sees the whole list once instead of discovering problems one save at a time.

        Args:
            version: Version fields — prompt, ideal_answer, expected_concepts, common_mistakes
                and rubric. Missing keys are treated as empty rather than raising.

        Returns:
            RubricValidationResult: Blocking errors and non-blocking warnings.
        """
        logging.info("Executing RubricValidator.validate")
        errors: list[str] = []
        warnings: list[str] = []

        self._check_prompt(version.get("prompt"), errors)
        self._check_ideal_answer(version.get("ideal_answer"), errors, warnings)
        concept_keys = self._check_concepts(version.get("expected_concepts"), errors, warnings)
        self._check_mistakes(version.get("common_mistakes"), concept_keys, errors, warnings)
        self._check_rubric(version.get("rubric"), errors)

        if errors:
            logging.warning(f"Rubric validation found {len(errors)} blocking error(s)")
        return RubricValidationResult(errors=errors, warnings=warnings)

    def _check_prompt(self, prompt: Any, errors: list[str]) -> None:
        """
        Verify the question prompt exists and is substantial enough to answer.

        Args:
            prompt: Candidate prompt text.
            errors: Accumulator for blocking problems.
        """
        text = prompt.strip() if isinstance(prompt, str) else ""
        if not text:
            errors.append("Prompt is required.")
        elif len(text) < MIN_PROMPT_CHARS:
            errors.append(
                f"Prompt is too short to be a real interview question "
                f"(minimum {MIN_PROMPT_CHARS} characters)."
            )

    def _check_ideal_answer(self, ideal: Any, errors: list[str], warnings: list[str]) -> None:
        """
        Verify the ideal answer gives the grader a usable reference.

        A short ideal answer is the single most common cause of harsh grading: the model has
        nothing to compare a thorough student answer against and penalises detail it cannot
        confirm.

        Args:
            ideal: Candidate ideal answer text.
            errors: Accumulator for blocking problems.
            warnings: Accumulator for quality concerns.
        """
        text = ideal.strip() if isinstance(ideal, str) else ""
        if not text:
            errors.append("Ideal answer is required.")
            return
        if len(text) < MIN_IDEAL_ANSWER_CHARS:
            errors.append(
                f"Ideal answer is too short to grade against "
                f"(minimum {MIN_IDEAL_ANSWER_CHARS} characters)."
            )
        elif len(text) < RECOMMENDED_IDEAL_ANSWER_CHARS:
            warnings.append(
                "Ideal answer is brief. Thorough student answers tend to be marked down when the "
                "reference answer omits detail they correctly include."
            )

    def _check_concepts(self, concepts: Any, errors: list[str], warnings: list[str]) -> set[str]:
        """
        Verify the expected concepts are present, well formed, and uniquely keyed.

        Concept keys are the vocabulary every downstream feature speaks: they are recorded on
        attempts, aggregated into mastery, and grouped in review. A duplicate key would make two
        different ideas indistinguishable in a student's history, permanently.

        Args:
            concepts: Candidate list of concept entries.
            errors: Accumulator for blocking problems.
            warnings: Accumulator for quality concerns.

        Returns:
            set[str]: The concept keys found, for cross-checking against common mistakes.
        """
        if not isinstance(concepts, list):
            errors.append("Expected concepts must be a list.")
            return set()

        if len(concepts) < MIN_EXPECTED_CONCEPTS:
            errors.append("At least one expected concept is required.")
        elif len(concepts) < RECOMMENDED_EXPECTED_CONCEPTS:
            warnings.append(
                f"Only {len(concepts)} expected concept(s). {RECOMMENDED_EXPECTED_CONCEPTS} or "
                f"more give the grader enough signal to separate a partial answer from a strong one."
            )
        if len(concepts) > MAX_EXPECTED_CONCEPTS:
            errors.append(
                f"Too many expected concepts (maximum {MAX_EXPECTED_CONCEPTS}). A question this "
                f"broad should be split so a student's gap can be identified precisely."
            )

        return self._collect_keys(concepts, "Expected concept", errors)

    def _check_mistakes(
        self,
        mistakes: Any,
        concept_keys: set[str],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """
        Verify common mistakes are well formed and do not collide with concept keys.

        A mistake sharing a key with a concept would let the same identifier mean both "the
        student got this right" and "the student got this wrong" in one attempt's record.

        Args:
            mistakes: Candidate list of mistake entries.
            concept_keys: Keys already claimed by expected concepts.
            errors: Accumulator for blocking problems.
            warnings: Accumulator for quality concerns.
        """
        if not isinstance(mistakes, list):
            errors.append("Common mistakes must be a list.")
            return

        if not mistakes:
            warnings.append(
                "No common mistakes listed. Naming the specific errors interviewers see makes "
                "feedback concrete instead of generic."
            )

        mistake_keys = self._collect_keys(mistakes, "Common mistake", errors)
        collisions = sorted(mistake_keys & concept_keys)
        if collisions:
            errors.append(
                f"These keys are used for both an expected concept and a common mistake: "
                f"{', '.join(collisions)}."
            )

    def _collect_keys(self, entries: list[Any], label: str, errors: list[str]) -> set[str]:
        """
        Extract and validate the keys and labels of a list of concept-shaped entries.

        Args:
            entries: Entries to inspect.
            label: Human-readable noun for error messages, e.g. 'Expected concept'.
            errors: Accumulator for blocking problems.

        Returns:
            set[str]: The unique keys found.
        """
        seen: set[str] = set()
        duplicates: set[str] = set()

        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                errors.append(f"{label} {index} must be an object with a key and a label.")
                continue

            key = entry.get("key")
            text = entry.get("label")
            if not isinstance(key, str) or not key.strip():
                errors.append(f"{label} {index} is missing a key.")
                continue
            if not isinstance(text, str) or not text.strip():
                errors.append(f"{label} '{key}' is missing a label.")

            normalised = key.strip().lower()
            if normalised in seen:
                duplicates.add(normalised)
            seen.add(normalised)

        if duplicates:
            errors.append(f"Duplicate {label.lower()} keys: {', '.join(sorted(duplicates))}.")
        return seen

    def _check_rubric(self, rubric: Any, errors: list[str]) -> None:
        """
        Verify the optional rubric object is shaped correctly.

        The rubric is free-form scoring guidance, so almost nothing is required of it. The one
        rule enforced is that band thresholds, when supplied, are ordered: an inverted pair would
        make every answer either Strong or Needs Work with no middle band, which looks like a
        grading bug rather than a content mistake.

        Args:
            rubric: Candidate rubric object.
            errors: Accumulator for blocking problems.
        """
        if rubric is None:
            return
        if not isinstance(rubric, dict):
            errors.append("Rubric must be an object.")
            return

        thresholds = rubric.get("band_thresholds")
        if thresholds is None:
            return
        if not isinstance(thresholds, dict):
            errors.append("Rubric band thresholds must be an object.")
            return

        values: list[int] = []
        for band in BAND_ORDER:
            value = thresholds.get(band)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
                errors.append(
                    f"Rubric band threshold for '{band}' must be an integer from 0 to 100."
                )
                continue
            values.append(value)

        if len(values) == len(BAND_ORDER) and values[0] <= values[1]:
            errors.append(
                "Rubric band thresholds must decrease: the 'strong' threshold has to sit above "
                "the 'developing' threshold."
            )
