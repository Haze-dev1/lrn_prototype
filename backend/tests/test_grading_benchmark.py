"""Tests for the grading benchmark harness.

These test the *harness*, not grading quality. Quality is measured by running the benchmark
against a real provider and comparing to the previous run; a threshold asserted in CI against a
paid, non-deterministic API would be flaky, expensive, and would fail for reasons unrelated to
the change under review.

What is asserted here: the committed cases are well-formed and reference real questions, the
report's arithmetic is right, and a provider failure is reported as an error rather than being
silently counted as a disagreement.
"""

import json
from typing import Any

import pytest

from core.constants.enums import Band
from core.services.ai.benchmark import (
    BenchmarkCase,
    BenchmarkReport,
    CaseOutcome,
    GradingBenchmark,
)
from core.services.ai.fake_provider import FakeGradingProvider
from core.services.ai.provider import GradingProvider
from core.services.ai.types import GradingError, GradingFailureKind, ProviderCall
from core.services.questions.seed_service import QuestionSeeder
from tests.conftest import requires_database


def case(**overrides: Any) -> BenchmarkCase:
    """
    Build a benchmark case.

    Args:
        **overrides: Fields to override on the default.

    Returns:
        BenchmarkCase: The case.
    """
    fields: dict[str, Any] = {
        "id": "case-1",
        "source_key": "eev-001-bridge",
        "label": "excellent",
        "answer": "Subtract net debt and add back cash.",
        "expected_band": Band.STRONG,
    }
    fields.update(overrides)
    return BenchmarkCase(**fields)


class TestCommittedCases:
    """The benchmark file in the repository."""

    def test_the_case_file_loads(self) -> None:
        """A malformed benchmark file should fail here rather than mid-run."""
        cases = GradingBenchmark().load_cases()

        assert len(cases) >= 10

    def test_every_case_has_a_unique_id(self) -> None:
        """Duplicate IDs would make a report ambiguous about which case regressed."""
        cases = GradingBenchmark().load_cases()

        assert len({item.id for item in cases}) == len(cases)

    def test_every_expected_band_is_a_real_band(self) -> None:
        """Loading coerces to the Band enum, so a typo fails loudly."""
        assert all(isinstance(item.expected_band, Band) for item in GradingBenchmark().load_cases())

    def test_the_cases_cover_every_band(self) -> None:
        """A benchmark of only strong answers cannot detect a grader that never fails anyone."""
        bands = {item.expected_band for item in GradingBenchmark().load_cases()}

        assert bands == {Band.STRONG, Band.DEVELOPING, Band.NEEDS_WORK}

    def test_the_cases_cover_the_hard_answer_types(self) -> None:
        """The PRD names these two explicitly, and they are what a weak grader misses.

        A fluent, confident, wrong answer and a correct answer phrased unusually are the cases
        that separate a grader that understands from one that matches keywords.
        """
        labels = {item.label for item in GradingBenchmark().load_cases()}

        assert "plausible_but_wrong" in labels
        assert "differently_phrased_correct" in labels

    def test_a_bad_band_is_rejected(self, tmp_path) -> None:
        """A typo in a label fails at load, not silently as a disagreement."""
        path = tmp_path / "cases.json"
        path.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "x",
                            "source_key": "eev-001-bridge",
                            "label": "excellent",
                            "answer": "a",
                            "expected_band": "excellent",
                        }
                    ]
                }
            )
        )

        with pytest.raises(ValueError, match="unknown band"):
            GradingBenchmark(path=path).load_cases()

    def test_a_missing_file_is_reported_clearly(self, tmp_path) -> None:
        """A wrong path is an error, not an empty successful run."""
        with pytest.raises(FileNotFoundError):
            GradingBenchmark(path=tmp_path / "absent.json").load_cases()


class TestReportArithmetic:
    """The numbers the report produces."""

    def report(self, outcomes: list[CaseOutcome]) -> BenchmarkReport:
        """
        Build a report around a fixed set of outcomes.

        Args:
            outcomes: The outcomes to summarise.

        Returns:
            BenchmarkReport: The report under test.
        """
        return BenchmarkReport(
            provider="stub", model="stub/1", prompt_version="grade.v1", outcomes=outcomes
        )

    def test_agreement_counts_exact_band_matches(self) -> None:
        """Two of four graded cases agreeing is 50%."""
        report = self.report(
            [
                CaseOutcome(case=case(), actual_band=Band.STRONG),
                CaseOutcome(case=case(), actual_band=Band.STRONG),
                CaseOutcome(case=case(), actual_band=Band.DEVELOPING),
                CaseOutcome(case=case(), actual_band=Band.NEEDS_WORK),
            ]
        )

        assert report.agreement == 0.5

    def test_errors_are_excluded_from_agreement(self) -> None:
        """A provider outage must read as an error count, not as poor grading quality."""
        report = self.report(
            [
                CaseOutcome(case=case(), actual_band=Band.STRONG),
                CaseOutcome(case=case(), error="timeout"),
            ]
        )

        assert report.agreement == 1.0
        assert report.as_dict()["errors"] == 1

    def test_agreement_is_zero_when_nothing_graded(self) -> None:
        """No division by zero when every case failed."""
        assert self.report([CaseOutcome(case=case(), error="timeout")]).agreement == 0.0

    def test_an_adjacent_band_is_not_a_severe_disagreement(self) -> None:
        """Strong versus developing is a judgement call, not a failure."""
        report = self.report([CaseOutcome(case=case(), actual_band=Band.DEVELOPING)])

        assert report.severe_disagreements == []

    def test_two_bands_out_is_a_severe_disagreement(self) -> None:
        """A strong answer graded needs_work is the failure that destroys trust."""
        report = self.report([CaseOutcome(case=case(), actual_band=Band.NEEDS_WORK)])

        assert len(report.severe_disagreements) == 1

    def test_agreement_is_broken_down_by_label(self) -> None:
        """A grader can be strong overall and blind to one specific kind of answer."""
        report = self.report(
            [
                CaseOutcome(case=case(label="excellent"), actual_band=Band.STRONG),
                CaseOutcome(
                    case=case(label="plausible_but_wrong", expected_band=Band.NEEDS_WORK),
                    actual_band=Band.STRONG,
                ),
            ]
        )

        by_label = report.agreement_by_label()
        assert by_label["excellent"] == 1.0
        assert by_label["plausible_but_wrong"] == 0.0

    def test_the_report_serialises(self) -> None:
        """It is printed as JSON by the runner script."""
        report = self.report([CaseOutcome(case=case(), actual_band=Band.STRONG)])

        assert json.loads(json.dumps(report.as_dict()))["agreement"] == 1.0


class FailingProvider(GradingProvider):
    """A provider that always fails, to exercise the error path."""

    name = "failing"

    @property
    def model(self) -> str:
        """
        Return a fixed model identifier.

        Returns:
            str: The failing provider's model name.
        """
        return "failing/none"

    async def complete(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> ProviderCall:
        """
        Always fail.

        Args:
            system_prompt: Ignored.
            user_prompt: Ignored.
            json_schema: Ignored.

        Raises:
            GradingError: Always.
        """
        raise GradingError(GradingFailureKind.TIMEOUT, "provider unavailable")


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestAgainstTheQuestionBank:
    """The harness running against real seeded rubrics."""

    async def test_every_case_references_a_published_question(self) -> None:
        """A benchmark case naming a question that does not exist silently measures nothing."""
        await QuestionSeeder().run()
        benchmark = GradingBenchmark(provider=FakeGradingProvider())

        missing = [
            item.source_key
            for item in benchmark.load_cases()
            if await benchmark._context_for(item) is None
        ]

        assert missing == [], f"benchmark cases reference unpublished questions: {set(missing)}"

    async def test_the_harness_grades_every_case(self) -> None:
        """End to end against the deterministic provider: every case produces a band."""
        await QuestionSeeder().run()

        report = await GradingBenchmark(provider=FakeGradingProvider()).run()

        assert len(report.outcomes) == len(GradingBenchmark().load_cases())
        assert report.graded == report.outcomes
        assert report.as_dict()["errors"] == 0

    async def test_the_harness_discriminates(self) -> None:
        """The benchmark must be able to tell a good answer from an empty one.

        Asserted against the fake provider, which grades by term overlap. This does not measure
        grading quality — it proves the harness is wired to something that actually varies, so a
        real run's numbers mean something.
        """
        await QuestionSeeder().run()
        benchmark = GradingBenchmark(provider=FakeGradingProvider())
        cases = benchmark.load_cases()
        excellent = next(item for item in cases if item.label == "excellent")
        empty = case(source_key=excellent.source_key, answer="I don't know.", label="weak")

        report = await benchmark.run(cases=[excellent, empty])
        scores = [outcome.score for outcome in report.outcomes]

        assert scores[0] is not None and scores[1] is not None
        assert scores[0] > scores[1]

    async def test_a_provider_failure_is_reported_not_counted_as_disagreement(
        self, monkeypatch
    ) -> None:
        """An outage must not look like a grading regression."""
        # Every case exhausts the immediate-retry budget, and the real backoff would make this
        # one test take a minute of wall clock sleeping.
        monkeypatch.setattr("core.services.ai.grading_service.RETRY_BACKOFF_SECONDS", 0.0)
        await QuestionSeeder().run()

        report = await GradingBenchmark(provider=FailingProvider()).run()

        assert report.graded == []
        assert report.as_dict()["errors"] == len(report.outcomes)
        assert all("timeout" in (outcome.error or "") for outcome in report.outcomes)

    async def test_the_benchmark_persists_nothing(self) -> None:
        """Running it must not pollute student evidence or cost reporting."""
        from sqlalchemy import func, select

        from core.database.database import session
        from core.models.attempt_model import Attempt, GradeEvent

        await QuestionSeeder().run()
        await GradingBenchmark(provider=FakeGradingProvider()).run()

        async with session() as db:
            attempts = await db.execute(select(func.count()).select_from(Attempt))
            events = await db.execute(select(func.count()).select_from(GradeEvent))

        assert attempts.scalar_one() == 0
        assert events.scalar_one() == 0
