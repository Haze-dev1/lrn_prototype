"""Diagnostic composition.

The diagnostic is 24 questions: three from each of the eight categories. Its job is to produce a
readiness signal a student will believe, which puts two requirements on how it is built.

**It must be decided by the server.** The composition is written to ``session_questions`` when the
session is created, so a refresh resumes the same 24 questions and a client cannot reshuffle to
farm easier ones. Nothing about the selection is re-derived on read.

**It must be deterministic and explainable.** Given the same question bank, one student always
gets the same diagnostic — there is no random draw whose result nobody can reproduce when a
score is disputed. Different students get different sets, because a single fixed diagnostic would
be trivially shareable, but each student's own set is a pure function of their user ID and the
bank.

Difficulty ramps across the whole assessment rather than within each category: the student sees
one easy question from every category, then one medium from every category, then one hard. A
student who is weak in Accounting learns that in the first eight minutes rather than after
struggling through three Accounting questions in a row, and the sitting feels like an assessment
rather than eight separate quizzes.
"""

import hashlib
import uuid
from collections import defaultdict
from typing import Any

from core import logger
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.models.question_model import Question

logging = logger(__name__)

QUESTIONS_PER_CATEGORY = 3
# Enough to hold every gradeable question in a category; the selection narrows from there.
CANDIDATE_LIMIT = 200


class CompositionError(Exception):
    """Raised when the question bank cannot supply a complete diagnostic."""

    def __init__(self, message: str, *, shortfalls: dict[str, int] | None = None) -> None:
        """
        Record why a composition could not be built.

        Args:
            message: Operator-facing description.
            shortfalls: Per-category counts of how many more questions are needed.
        """
        super().__init__(message)
        self.message = message
        self.shortfalls = shortfalls or {}


class DiagnosticComposer:
    """Builds the fixed question order for a diagnostic session."""

    def __init__(self) -> None:
        """Initialise the composer with the CRUD layers it reads from."""
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()

    async def compose(self, *, user_id: uuid.UUID) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Build the ordered question composition for one student's diagnostic.

        Args:
            user_id: The student the diagnostic is for; seeds the per-student selection.

        Returns:
            tuple[list[dict[str, Any]], dict[str, Any]]: Ordered composition rows ready for
            ``CRUDSession.create_with_questions``, and the rationale to store alongside them.

        Raises:
            CompositionError: If any category cannot supply enough gradeable questions. Failing
                here is deliberate — a short diagnostic would silently misreport readiness for
                whichever category came up thin.
        """
        logging.info("Executing DiagnosticComposer.compose")
        categories = await self.CRUDCategory.list_all()
        if not categories:
            raise CompositionError("No categories are configured")

        selected_by_category: dict[str, list[Question]] = {}
        shortfalls: dict[str, int] = {}

        for category in categories:
            candidates = await self.CRUDQuestion.list_selectable(
                category_slug=category.slug, limit=CANDIDATE_LIMIT
            )
            if len(candidates) < QUESTIONS_PER_CATEGORY:
                shortfalls[category.slug] = QUESTIONS_PER_CATEGORY - len(candidates)
                continue
            selected_by_category[category.slug] = self._select(
                candidates=candidates, user_id=user_id
            )

        if shortfalls:
            logging.error(f"Cannot compose a diagnostic; categories are short: {shortfalls}")
            raise CompositionError(
                "The question bank cannot supply a complete diagnostic", shortfalls=shortfalls
            )

        order = self._interleave([category.slug for category in categories], selected_by_category)
        composition = []
        for position, question in enumerate(order):
            version = await self.CRUDQuestionVersion.get_published(question_id=question.id)
            if version is None:
                # list_selectable already filters to questions with a published version, so this
                # means one was superseded between the two reads. Rare, but it would otherwise
                # produce a session referencing a version that cannot grade.
                raise CompositionError(
                    f"Question {question.id} lost its published version during composition"
                )
            composition.append(
                {
                    "position": position,
                    "question_id": question.id,
                    "question_version_id": version.id,
                }
            )

        rationale = {
            "strategy": "diagnostic_v1",
            "questions_per_category": QUESTIONS_PER_CATEGORY,
            "categories": [category.slug for category in categories],
            "ordering": "difficulty_tier_then_category",
            "explanation": (
                f"Three questions from each of the {len(categories)} categories, ordered so "
                f"difficulty rises across the whole assessment rather than within each category."
            ),
        }
        logging.info(f"Composed a {len(composition)}-question diagnostic for user {user_id}")
        return composition, rationale

    def _select(self, *, candidates: list[Question], user_id: uuid.UUID) -> list[Question]:
        """
        Choose three questions from one category, spanning its difficulty range.

        Takes the easiest available, one from the middle, and the hardest available, so every
        category contributes a genuine ramp rather than three questions of the same weight. Ties
        within a difficulty are broken by a hash of the user and question IDs: reproducible for a
        given student, but different between students, so the diagnostic is not one fixed set of
        24 questions that circulates.

        Args:
            candidates: Gradeable questions in this category, at least three.
            user_id: The student, used to seed the tie-break.

        Returns:
            list[Question]: Three questions, easiest first.
        """
        by_difficulty: dict[int, list[Question]] = defaultdict(list)
        for question in candidates:
            by_difficulty[question.difficulty].append(question)

        for questions in by_difficulty.values():
            questions.sort(key=lambda item: self._tie_break(user_id, item.id))

        levels = sorted(by_difficulty)
        # Pick three difficulty levels spanning the range. With one or two distinct levels the
        # same level is drawn from more than once, which is why the pool is consumed as it goes.
        chosen_levels = [levels[0], levels[len(levels) // 2], levels[-1]]

        selected: list[Question] = []
        pools = {level: list(questions) for level, questions in by_difficulty.items()}
        for level in chosen_levels:
            drawn = self._take(pools, preferred=level)
            if drawn is not None:
                selected.append(drawn)

        # A category whose distinct levels could not fill three slots falls back to whatever
        # remains, so a thin-but-sufficient category still yields a full set.
        while len(selected) < QUESTIONS_PER_CATEGORY:
            spare = self._take(pools, preferred=None)
            if spare is None:
                break
            selected.append(spare)

        selected.sort(key=lambda item: (item.difficulty, self._tie_break(user_id, item.id)))
        return selected

    @staticmethod
    def _take(pools: dict[int, list[Question]], *, preferred: int | None) -> Question | None:
        """
        Remove and return a question, preferring one difficulty level.

        Args:
            pools: Remaining questions keyed by difficulty; mutated in place.
            preferred: Difficulty to draw from first, or None to take the lowest available.

        Returns:
            Question | None: The question taken, or None when every pool is empty.
        """
        if preferred is not None and pools.get(preferred):
            return pools[preferred].pop(0)
        for level in sorted(pools):
            if pools[level]:
                return pools[level].pop(0)
        return None

    @staticmethod
    def _interleave(
        category_order: list[str], selected: dict[str, list[Question]]
    ) -> list[Question]:
        """
        Order the selection so difficulty rises across the whole diagnostic.

        Produces one round per difficulty slot: the easiest question from every category, then the
        middle one from every category, then the hardest. Categories keep their display order
        within a round, so the sitting has a predictable rhythm.

        Args:
            category_order: Category slugs in presentation order.
            selected: Three questions per category, easiest first.

        Returns:
            list[Question]: The full ordered composition.
        """
        ordered: list[Question] = []
        for tier in range(QUESTIONS_PER_CATEGORY):
            for slug in category_order:
                questions = selected.get(slug, [])
                if tier < len(questions):
                    ordered.append(questions[tier])
        return ordered

    @staticmethod
    def _tie_break(user_id: uuid.UUID, question_id: uuid.UUID) -> str:
        """
        Produce a stable per-student ordering key for one question.

        A hash rather than a random shuffle, so the same student always composes the same
        diagnostic and a disputed result can be reproduced exactly.

        Args:
            user_id: The student.
            question_id: The question.

        Returns:
            str: Deterministic hex digest used as a sort key.
        """
        return hashlib.sha256(f"{user_id}:{question_id}".encode()).hexdigest()
