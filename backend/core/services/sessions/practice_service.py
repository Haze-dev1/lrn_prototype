"""Adaptive practice composition.

Practice selects which questions a student sees next. The PRD is explicit that V1 must be
deterministic and explainable, with no ML, and this module takes that literally: every question's
priority is a weighted sum of four named signals, and the session stores a sentence saying which
of them drove the selection.

That constraint is a product requirement, not a shortcut. The interface tells a student
*"Valuation is your weakest category, and 2 previous misses are due for review"* — a claim the
product can only make if the selection genuinely worked that way. A model whose output could not
be attributed to specific reasons would make that sentence a decoration.

The four signals:

- **Review due** — a question previously answered poorly, whose spacing interval has elapsed.
  Weighted highest, because a known gap the student has already met is the most valuable thing
  they can spend ten minutes on.
- **Weakness** — the category's mastery score, inverted. A category with no evidence counts as
  moderately weak rather than as a gap, since "not measured" and "measured badly" are different
  claims.
- **Novelty** — never attempted. Keeps a set from being entirely revision, and is what makes
  practice feel like progress rather than a treadmill.
- **Difficulty fit** — how close a question sits to the level the student is currently working at
  in that category. A question far above them teaches nothing; one far below wastes the slot.

Ties are broken by a hash of the user and question IDs, so a student's set is reproducible and two
students with identical histories still get different questions.
"""

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core import logger
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.skill_score_crud import CRUDSkillScore
from core.models.question_model import Question

logging = logger(__name__)

#: The set sizes the product offers.
PRACTICE_SET_SIZES = (5, 10, 20)

# A score at or below this counts as a miss worth revisiting. Set at the boundary of the
# "developing" band: an answer that was merely adequate is still a gap worth closing.
REVIEW_SCORE_THRESHOLD = 65

# Spacing before a missed question becomes eligible again, indexed by how many times the student
# has already answered it. Roughly doubling then tripling, per the PRD. The last value repeats for
# any further attempts: a question missed four times is a content or comprehension problem that
# more frequent repetition will not fix.
REVIEW_INTERVALS_DAYS = (2, 7, 21)

# A question answered well is not shown again for this long regardless of anything else, so a
# student is not re-tested on something they have just demonstrated.
RECENTLY_PASSED_COOLDOWN_DAYS = 21

# Signal weights. Deliberately far apart rather than finely tuned: the ordering between signals is
# the product decision, and pretending to precision here would invite tuning noise into something
# that has to stay explainable.
WEIGHT_REVIEW_DUE = 100.0
WEIGHT_WEAKNESS = 60.0
WEIGHT_NOVELTY = 25.0
WEIGHT_DIFFICULTY_FIT = 15.0

# Assumed mastery for a category with no graded evidence. Mid-range on purpose: an unmeasured
# category should be sampled, but must not outrank a category measured as genuinely weak.
UNMEASURED_MASTERY = 55

# No more than this share of a set comes from one category, unless the student asked for that
# category. A 20-question set that is entirely Valuation is technically the correct answer to
# "what is weakest" and a poor practice session.
MAX_CATEGORY_SHARE = 0.4

# The same cap applied to difficulty. Without it a set is flat: difficulty fit is the only signal
# that separates otherwise-equal candidates, so a student with no history gets five questions all
# at the level nearest their assumed mastery. That is defensible ranking and a worse session — a
# set with no range gives a student no sense of where their ceiling is.
MAX_DIFFICULTY_SHARE = 0.4

CANDIDATE_LIMIT = 500


@dataclass(frozen=True)
class QuestionHistory:
    """What a student has done with one question."""

    attempt_count: int
    latest_score: int
    latest_graded_at: datetime

    def is_due_for_review(self, *, now: datetime) -> bool:
        """
        Report whether a previously missed question has become eligible again.

        Args:
            now: Reference time.

        Returns:
            bool: True when the answer was weak and its spacing interval has elapsed.
        """
        if self.latest_score > REVIEW_SCORE_THRESHOLD:
            return False
        index = min(self.attempt_count - 1, len(REVIEW_INTERVALS_DAYS) - 1)
        interval = REVIEW_INTERVALS_DAYS[max(index, 0)]
        return self.days_since(now) >= interval

    def is_in_cooldown(self, *, now: datetime) -> bool:
        """
        Report whether a well-answered question is still too recent to repeat.

        Args:
            now: Reference time.

        Returns:
            bool: True when the student demonstrated this recently.
        """
        return (
            self.latest_score > REVIEW_SCORE_THRESHOLD
            and self.days_since(now) < RECENTLY_PASSED_COOLDOWN_DAYS
        )

    def days_since(self, now: datetime) -> float:
        """
        Return how many days have passed since this question was last graded.

        Args:
            now: Reference time.

        Returns:
            float: Age in days, never negative.
        """
        return max((now - self.latest_graded_at).total_seconds() / 86400.0, 0.0)


@dataclass
class Scored:
    """One candidate question and why it was ranked where it was."""

    question: Question
    priority: float
    reasons: list[str]


class PracticeComposeError(Exception):
    """Raised when no practice set can be built."""

    def __init__(self, message: str, *, available: int = 0) -> None:
        """
        Record why a practice set could not be composed.

        Args:
            message: Operator-facing description.
            available: How many questions were actually available.
        """
        super().__init__(message)
        self.message = message
        self.available = available


class PracticeComposer:
    """Selects and orders the questions for one practice session."""

    def __init__(self) -> None:
        """Initialise the composer with the CRUD layers it reads from."""
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDSkillScore = CRUDSkillScore()

    async def compose(
        self,
        *,
        user_id: uuid.UUID,
        size: int,
        category_slug: str | None = None,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Build the ordered question composition for one practice session.

        Args:
            user_id: The student practising.
            size: Requested set size; one of ``PRACTICE_SET_SIZES``.
            category_slug: Restrict to one category when the student asked for it.
            now: Reference time, injectable so spacing behaviour is testable.

        Returns:
            tuple[list[dict[str, Any]], dict[str, Any]]: Composition rows ready for
            ``CRUDSession.create_with_questions``, and the rationale stored alongside them.

        Raises:
            PracticeComposeError: If the bank has no eligible questions at all.
        """
        logging.info("Executing PracticeComposer.compose")
        reference = now or datetime.now(UTC)

        candidates = await self.CRUDQuestion.list_selectable(
            category_slug=category_slug, limit=CANDIDATE_LIMIT
        )
        if not candidates:
            raise PracticeComposeError(
                "No gradeable questions are available for practice", available=0
            )

        history = {
            question_id: QuestionHistory(count, score, graded_at)
            for question_id, count, score, graded_at in await self.CRUDAttempt.list_question_history(
                user_id=user_id
            )
        }
        mastery = {
            score.category_slug: score.score
            for score in await self.CRUDSkillScore.list_for_user(user_id=user_id)
        }

        scored = [
            self._score(
                question=question,
                history=history.get(question.id),
                mastery=mastery.get(question.category_slug, UNMEASURED_MASTERY),
                user_id=user_id,
                now=reference,
            )
            for question in candidates
        ]
        selected = self._take(scored, size=size, restricted=category_slug is not None)
        if not selected:
            raise PracticeComposeError(
                "Every available question was recently answered well", available=len(candidates)
            )

        # Ordered easiest first so a session opens with something answerable. A set that starts
        # with its hardest question is one a tired student abandons at the first prompt.
        selected.sort(
            key=lambda item: (item.question.difficulty, self._tie_break(user_id, item.question.id))
        )

        composition = []
        for position, item in enumerate(selected):
            version = await self.CRUDQuestionVersion.get_published(question_id=item.question.id)
            if version is None:
                continue
            composition.append(
                {
                    "position": position,
                    "question_id": item.question.id,
                    "question_version_id": version.id,
                }
            )

        rationale = self._rationale(
            selected=selected,
            mastery=mastery,
            category_slug=category_slug,
            categories={c.slug: c.name for c in await self.CRUDCategory.list_all()},
        )
        logging.info(f"Composed a {len(composition)}-question practice set for user {user_id}")
        return composition, rationale

    def _score(
        self,
        *,
        question: Question,
        history: QuestionHistory | None,
        mastery: int,
        user_id: uuid.UUID,
        now: datetime,
    ) -> Scored:
        """
        Rank one candidate question and record the reasons behind its rank.

        The reasons are not decoration: they are what the interface turns into a sentence a
        student reads, so every contribution to the priority adds its own label.

        Args:
            question: The candidate.
            history: The student's history with it, if any.
            mastery: The student's mastery in its category, 0-100.
            user_id: The student, for the deterministic tie-break.
            now: Reference time.

        Returns:
            Scored: The question, its priority, and its reasons.
        """
        priority = 0.0
        reasons: list[str] = []

        if history is None:
            priority += WEIGHT_NOVELTY
            reasons.append("new")
        elif history.is_due_for_review(now=now):
            priority += WEIGHT_REVIEW_DUE
            reasons.append("review_due")
        elif history.is_in_cooldown(now=now):
            # Answered well and recently. Excluded rather than merely deprioritised: re-testing
            # something a student has just demonstrated is the clearest way to waste their time.
            return Scored(question=question, priority=float("-inf"), reasons=["recently_passed"])

        # Weakness scales linearly with the gap below full mastery, so a category at 30
        # outranks one at 60 by twice as much rather than by a threshold step.
        weakness = (100 - mastery) / 100
        priority += WEIGHT_WEAKNESS * weakness
        if mastery <= REVIEW_SCORE_THRESHOLD:
            reasons.append("weak_category")

        priority += WEIGHT_DIFFICULTY_FIT * self._difficulty_fit(question.difficulty, mastery)
        return Scored(question=question, priority=priority, reasons=reasons)

    @staticmethod
    def _difficulty_fit(difficulty: int, mastery: int) -> float:
        """
        Score how well a question's difficulty matches where the student currently is.

        Maps mastery onto the 1-5 difficulty scale and prefers questions near that point. A
        student at 20 in a category is not helped by a level-5 judgement question, and a student
        at 90 learns nothing from a definition.

        Args:
            difficulty: The question's difficulty, 1-5.
            mastery: The student's mastery in its category, 0-100.

        Returns:
            float: Fit from 0.0 (furthest) to 1.0 (exact match).
        """
        target = 1 + (mastery / 100) * 4
        return max(0.0, 1.0 - abs(difficulty - target) / 4)

    def _take(self, scored: list[Scored], *, size: int, restricted: bool) -> list[Scored]:
        """
        Take the highest-priority questions, capping how much one category may contribute.

        Without the cap, a student with one badly weak category would get a set entirely from it —
        which is the literally correct answer to "what is weakest" and a poor practice session,
        because a single sitting on one topic produces fatigue rather than coverage. The cap is
        lifted when the student explicitly asked for one category.

        Args:
            scored: Every candidate, scored.
            size: Requested set size.
            restricted: Whether the student asked for a single category.

        Returns:
            list[Scored]: The chosen questions, highest priority first.
        """
        eligible = [item for item in scored if item.priority != float("-inf")]
        eligible.sort(key=lambda item: (-item.priority, item.question.id.hex))

        if restricted:
            # The category cap is lifted, but the difficulty cap is not: a student practising one
            # category still deserves a range within it.
            return self._spread_by_difficulty(eligible, size=size)

        category_cap = max(1, int(size * MAX_CATEGORY_SHARE))
        difficulty_cap = max(1, int(size * MAX_DIFFICULTY_SHARE))
        taken: list[Scored] = []
        per_category: dict[str, int] = defaultdict(int)
        per_difficulty: dict[int, int] = defaultdict(int)
        overflow: list[Scored] = []

        for item in eligible:
            if len(taken) == size:
                break
            slug = item.question.category_slug
            level = item.question.difficulty
            if per_category[slug] < category_cap and per_difficulty[level] < difficulty_cap:
                taken.append(item)
                per_category[slug] += 1
                per_difficulty[level] += 1
            else:
                overflow.append(item)

        # A thin bank may not have enough breadth to fill the set within the caps. Falling back to
        # the overflow keeps the promise of "10 questions" rather than silently returning six.
        for item in overflow:
            if len(taken) == size:
                break
            taken.append(item)
        return taken

    @staticmethod
    def _spread_by_difficulty(eligible: list[Scored], *, size: int) -> list[Scored]:
        """
        Take the highest-priority questions while keeping a range of difficulties.

        Args:
            eligible: Candidates, already ordered by priority.
            size: Requested set size.

        Returns:
            list[Scored]: The chosen questions.
        """
        cap = max(1, int(size * MAX_DIFFICULTY_SHARE))
        taken: list[Scored] = []
        per_difficulty: dict[int, int] = defaultdict(int)
        overflow: list[Scored] = []

        for item in eligible:
            if len(taken) == size:
                break
            level = item.question.difficulty
            if per_difficulty[level] < cap:
                taken.append(item)
                per_difficulty[level] += 1
            else:
                overflow.append(item)

        for item in overflow:
            if len(taken) == size:
                break
            taken.append(item)
        return taken

    def _rationale(
        self,
        *,
        selected: list[Scored],
        mastery: dict[str, int],
        category_slug: str | None,
        categories: dict[str, str],
    ) -> dict[str, Any]:
        """
        Build the stored explanation of why this set was chosen.

        Written once, at selection time, and stored on the session. The alternative — deriving the
        explanation when the page renders — would make it drift: a student's mastery moves as they
        practise, so a sentence recomputed later would describe a state that no longer produced
        this set.

        Args:
            selected: The chosen questions with their reasons.
            mastery: Category mastery scores.
            category_slug: The category the student asked for, if any.
            categories: Slug to display-name mapping.

        Returns:
            dict[str, Any]: Counts, the driving category, and a human-readable sentence.
        """
        review_due = sum(1 for item in selected if "review_due" in item.reasons)
        new_questions = sum(1 for item in selected if "new" in item.reasons)
        weakest_slug = min(mastery, key=lambda slug: mastery[slug]) if mastery else None

        if category_slug:
            focus = categories.get(category_slug, category_slug)
        elif weakest_slug:
            focus = categories.get(weakest_slug, weakest_slug)
        else:
            focus = ""

        clauses = []
        if category_slug:
            clauses.append(f"You asked to practise {focus}")
        elif weakest_slug is not None:
            clauses.append(f"{focus} is currently your weakest category at {mastery[weakest_slug]}")
        else:
            clauses.append("You have no graded evidence yet, so this set samples broadly")

        if review_due:
            clauses.append(
                f"{review_due} previous {'miss is' if review_due == 1 else 'misses are'} "
                f"due for review"
            )
        if new_questions:
            clauses.append(
                f"{new_questions} {'question is' if new_questions == 1 else 'questions are'} "
                f"new to you"
            )

        return {
            "strategy": "practice_v1",
            "requested_category": category_slug,
            "focus_category": category_slug or weakest_slug,
            "review_due_count": review_due,
            "new_count": new_questions,
            "weak_category_count": sum(1 for item in selected if "weak_category" in item.reasons),
            "explanation": f"{', and '.join(clauses)}.",
        }

    @staticmethod
    def _tie_break(user_id: uuid.UUID, question_id: uuid.UUID) -> str:
        """
        Produce a stable per-student ordering key for one question.

        Args:
            user_id: The student.
            question_id: The question.

        Returns:
            str: Deterministic hex digest used as a sort key.
        """
        return hashlib.sha256(f"{user_id}:{question_id}".encode()).hexdigest()
