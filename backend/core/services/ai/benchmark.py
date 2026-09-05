"""Grading benchmark harness.

Grading credibility is the product. A student who does not believe the score has no reason to
believe anything else the product tells them, so a change to the model, the prompt, or a rubric
has to be evaluated against evidence rather than impression.

This runs a set of human-labelled answers through the real grading path — the same prompt, the
same provider, the same validation — and reports how often the grader agreed with the human. It
reports agreement per label as well as overall, because a grader can be strong on obviously good
and obviously bad answers while being unable to catch a fluent, confident, wrong one, and a
single aggregate number hides exactly that.

It is deliberately not a pass/fail gate in CI: real model calls cost money and are not perfectly
deterministic. It is a tool to run before a change ships, and to compare against the run before.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import logger
from core.constants.enums import Band
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.services.ai.grading_service import GradingService
from core.services.ai.provider import GradingProvider
from core.services.ai.types import GradeContext, GradingError

logging = logger(__name__)

DEFAULT_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "grading_benchmark.json"
)
# Bands are ordered, so "graded developing instead of strong" is a near miss while
# "graded strong instead of needs_work" is a failure. Distance is what distinguishes them.
_BAND_ORDER: dict[Band, int] = {Band.NEEDS_WORK: 0, Band.DEVELOPING: 1, Band.STRONG: 2}


@dataclass
class BenchmarkCase:
    """One human-labelled answer and the band a reviewer assigned it."""

    id: str
    source_key: str
    label: str
    answer: str
    expected_band: Band
    notes: str = ""


@dataclass
class CaseOutcome:
    """What the grader produced for one benchmark case."""

    case: BenchmarkCase
    score: int | None = None
    actual_band: Band | None = None
    error: str | None = None

    @property
    def agreed(self) -> bool:
        """
        Report whether the grader assigned the human's band.

        Returns:
            bool: True on an exact band match.
        """
        return self.actual_band == self.case.expected_band

    @property
    def band_distance(self) -> int | None:
        """
        Report how far the grader's band was from the human's.

        Returns:
            int | None: 0 on agreement, 1 for an adjacent band, 2 for the opposite end, or None
            when the case failed to grade.
        """
        if self.actual_band is None:
            return None
        return abs(_BAND_ORDER[self.actual_band] - _BAND_ORDER[self.case.expected_band])


@dataclass
class BenchmarkReport:
    """Aggregate results of one benchmark run."""

    provider: str
    model: str
    prompt_version: str
    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def graded(self) -> list[CaseOutcome]:
        """
        Return only the cases that produced a grade.

        Returns:
            list[CaseOutcome]: Outcomes with a band.
        """
        return [outcome for outcome in self.outcomes if outcome.actual_band is not None]

    @property
    def agreement(self) -> float:
        """
        Return the share of graded cases where the grader matched the human.

        Measured over graded cases only, so a provider outage reads as an error count rather than
        quietly depressing the quality number.

        Returns:
            float: Agreement from 0.0 to 1.0, or 0.0 when nothing graded.
        """
        if not self.graded:
            return 0.0
        return sum(outcome.agreed for outcome in self.graded) / len(self.graded)

    @property
    def severe_disagreements(self) -> list[CaseOutcome]:
        """
        Return cases the grader got badly wrong, not merely adjacent.

        A weak answer graded Strong, or a strong answer graded Needs Work, is the failure that
        destroys trust in the product. An adjacent band is a judgement call.

        Returns:
            list[CaseOutcome]: Outcomes two bands away from the human label.
        """
        return [outcome for outcome in self.graded if (outcome.band_distance or 0) >= 2]

    def agreement_by_label(self) -> dict[str, float]:
        """
        Return agreement broken down by the kind of answer.

        Returns:
            dict[str, float]: Agreement per label, for graded cases only.
        """
        by_label: dict[str, list[CaseOutcome]] = {}
        for outcome in self.graded:
            by_label.setdefault(outcome.case.label, []).append(outcome)
        return {
            label: sum(item.agreed for item in items) / len(items)
            for label, items in sorted(by_label.items())
        }

    def as_dict(self) -> dict[str, Any]:
        """
        Render the report as plain data for printing or storing.

        Returns:
            dict[str, Any]: Summary counts, agreement, and per-case results.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "cases": len(self.outcomes),
            "graded": len(self.graded),
            "errors": len(self.outcomes) - len(self.graded),
            "agreement": round(self.agreement, 3),
            "agreement_by_label": {
                label: round(value, 3) for label, value in self.agreement_by_label().items()
            },
            "severe_disagreements": [
                {
                    "id": outcome.case.id,
                    "expected": outcome.case.expected_band.value,
                    "actual": outcome.actual_band.value if outcome.actual_band else None,
                    "score": outcome.score,
                }
                for outcome in self.severe_disagreements
            ],
            "results": [
                {
                    "id": outcome.case.id,
                    "label": outcome.case.label,
                    "expected": outcome.case.expected_band.value,
                    "actual": outcome.actual_band.value if outcome.actual_band else None,
                    "score": outcome.score,
                    "agreed": outcome.agreed,
                    "error": outcome.error,
                }
                for outcome in self.outcomes
            ],
        }


class GradingBenchmark:
    """Runs labelled answers through the real grading path and scores the grader."""

    def __init__(
        self, *, provider: GradingProvider | None = None, path: Path | None = None
    ) -> None:
        """
        Initialise the benchmark against a provider and a case file.

        Args:
            provider: Provider to evaluate. Defaults to the configured one.
            path: Case file. Defaults to the committed benchmark fixtures.
        """
        self.path = path or DEFAULT_BENCHMARK_PATH
        self._service = GradingService(provider=provider)
        self._provider = provider
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()

    def load_cases(self) -> list[BenchmarkCase]:
        """
        Read the labelled cases from disk.

        Returns:
            list[BenchmarkCase]: Cases in file order.

        Raises:
            FileNotFoundError: If the case file does not exist.
            ValueError: If a case names a band that is not a product band.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"Benchmark file not found: {self.path}")

        payload = json.loads(self.path.read_text())
        cases = []
        for raw in payload.get("cases", []):
            try:
                expected = Band(raw["expected_band"])
            except ValueError as error:
                raise ValueError(
                    f"Benchmark case {raw.get('id')} names an unknown band: "
                    f"{raw.get('expected_band')}"
                ) from error
            cases.append(
                BenchmarkCase(
                    id=raw["id"],
                    source_key=raw["source_key"],
                    label=raw["label"],
                    answer=raw["answer"],
                    expected_band=expected,
                    notes=raw.get("notes", ""),
                )
            )
        return cases

    async def run(self, *, cases: list[BenchmarkCase] | None = None) -> BenchmarkReport:
        """
        Grade every case and report agreement with the human labels.

        Grades against the question's currently published rubric, deliberately: the benchmark's
        job is to tell you how the grader behaves *now*, and pinning it to an old version would
        make a rubric regression invisible.

        Nothing is persisted. The benchmark writes no attempts and no grade events, so running it
        cannot pollute a student's evidence or the cost reporting.

        Args:
            cases: Cases to run. Defaults to the committed file.

        Returns:
            BenchmarkReport: Per-case outcomes and aggregate agreement.
        """
        logging.info("Executing GradingBenchmark.run")
        if self._provider is None:
            from core.services.ai.provider import get_grading_provider

            self._provider = get_grading_provider()
            self._service = GradingService(provider=self._provider)

        from core.services.ai.prompts import PROMPT_VERSION

        report = BenchmarkReport(
            provider=self._provider.name,
            model=self._provider.model,
            prompt_version=PROMPT_VERSION,
        )

        for case in cases if cases is not None else self.load_cases():
            report.outcomes.append(await self._run_case(case))

        logging.info(
            f"Benchmark complete: {report.agreement:.0%} agreement over "
            f"{len(report.graded)} graded case(s)"
        )
        return report

    async def _run_case(self, case: BenchmarkCase) -> CaseOutcome:
        """
        Grade one case and compare the result to its human label.

        Args:
            case: The labelled case.

        Returns:
            CaseOutcome: The grade produced, or the reason it could not be produced.
        """
        context = await self._context_for(case)
        if context is None:
            return CaseOutcome(case=case, error=f"No published question for {case.source_key}")

        try:
            call = await self._service._call_provider(context)
            result = self._service._validate(call.content, context)
        except GradingError as error:
            logging.warning(f"Benchmark case {case.id} failed to grade: {error.kind}")
            return CaseOutcome(case=case, error=f"{error.kind}: {error.message}")

        return CaseOutcome(case=case, score=result.score, actual_band=result.band)

    async def _context_for(self, case: BenchmarkCase) -> GradeContext | None:
        """
        Assemble the grading context for a case from the live question bank.

        Args:
            case: The labelled case naming a question by source key.

        Returns:
            GradeContext | None: The context, or None when the question is not published.
        """
        question = await self.CRUDQuestion.get_by_source_key(source_key=case.source_key)
        if question is None:
            return None
        version = await self.CRUDQuestionVersion.get_published(question_id=question.id)
        if version is None:
            return None

        category = await self.CRUDCategory.get_by_slug(slug=question.category_slug)
        return GradeContext(
            question_prompt=version.prompt,
            ideal_answer=version.ideal_answer,
            expected_concepts=list(version.expected_concepts or []),
            common_mistakes=list(version.common_mistakes or []),
            rubric=dict(version.rubric or {}),
            student_answer=case.answer,
            category_name=category.name if category else question.category_slug,
            version_number=version.version,
        )
