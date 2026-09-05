"""Deterministic local grading provider.

Used in tests and in development so the whole grading path — prompt construction, provider call,
schema validation, key reconciliation, persistence, audit — can be exercised without a network
call, an API key, or a bill. It is selected by ``GRADING_PROVIDER=fake``, which is the default,
so a developer who has cloned the repository and run ``make up`` gets working grading.

It grades by term overlap between the answer and each concept's key and label. That is not
intelligent, but it is deterministic and it *discriminates*: a blank answer scores zero, a
thorough one scores high, and a partial one lands in between. A fake that returned a constant
score would let a broken score-handling path pass every test.

It reads the concept keys back out of the prompt rather than being handed them directly. That is
deliberate: a fake that took a privileged side channel would not be exercising the same interface
as the real provider, and a prompt-construction bug that hid the concepts from a real model would
sail past every test.
"""

import json
import re
import time
from decimal import Decimal
from typing import Any

from core import logger
from core.services.ai.provider import GradingProvider
from core.services.ai.types import ProviderCall

logging = logger(__name__)

# Matches the "- key: label" lines emitted by prompts._render_entries, and the bare "- key"
# form used when a label is absent. The key group deliberately excludes ":" — a character class
# containing it matches greedily through the separator, yielding "net_debt:" instead of
# "net_debt", and every key then fails to reconcile against the rubric and is dropped.
_ENTRY_LINE = re.compile(r"^- ([^:\s]+)(?::[ ]?(.*))?$", re.MULTILINE)
_CONCEPTS_BLOCK = re.compile(
    r"EXPECTED CONCEPTS \(report these keys only\):\n(.*?)(?:\n\n|\Z)", re.DOTALL
)
_MISTAKES_BLOCK = re.compile(
    r"COMMON MISTAKES \(report these keys only\):\n(.*?)(?:\n\n|\Z)", re.DOTALL
)
_FENCE = re.compile(r"^(STUDENT_SUBMISSION_[0-9A-F]+)$", re.MULTILINE)
_BANDS = re.compile(r"score >= (\d+) is strong; score >= (\d+) is developing")
_WORD = re.compile(r"[a-z0-9]+")

# Words that carry no discriminating signal, so a student writing "the of and" scores nothing.
_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "or", "to", "in", "is", "it", "for", "on", "by", "with", "as"}
)
# Fraction of a concept's terms an answer must contain to be credited with it.
_HIT_THRESHOLD = 0.5


class FakeGradingProvider(GradingProvider):
    """Grades by term overlap, with no network call."""

    name = "fake"

    @property
    def model(self) -> str:
        """
        Return a model identifier that cannot be mistaken for a real one.

        Returns:
            str: The fake model name recorded on grade events.
        """
        return "fake/deterministic-overlap-v1"

    async def complete(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> ProviderCall:
        """
        Produce a deterministic grade for the answer in the prompt.

        Args:
            system_prompt: Ignored; accepted to match the provider interface.
            user_prompt: The rubric and the fenced student answer.
            json_schema: Ignored; the output is constructed to satisfy it by construction.

        Returns:
            ProviderCall: JSON content matching the grade schema, with synthetic accounting.
        """
        started = time.perf_counter()
        concepts = _entries(_CONCEPTS_BLOCK, user_prompt)
        mistakes = _entries(_MISTAKES_BLOCK, user_prompt)
        answer_terms = _terms(_fenced_answer(user_prompt))

        hit = [key for key, label in concepts if _covers(answer_terms, key, label)]
        missed = [key for key, _ in concepts if key not in hit]
        score = round(100 * len(hit) / len(concepts)) if concepts else 0

        strong, developing = _band_floors(user_prompt)
        band = (
            "strong" if score >= strong else "developing" if score >= developing else "needs_work"
        )

        content = json.dumps(
            {
                "score": score,
                "band": band,
                "feedback": _feedback(hit, missed, concepts),
                "concepts_hit": hit,
                "concepts_missed": missed,
                # Reported only when the answer is weak enough that a listed mistake is a
                # plausible reading of it, so the mistake path is exercised without every
                # answer triggering every flag.
                "mistake_flags": [key for key, _ in mistakes][:1] if score < developing else [],
            }
        )
        return ProviderCall(
            content=content,
            provider=self.name,
            model=self.model,
            model_version=self.model,
            request_id=None,
            input_tokens=len(user_prompt) // 4,
            output_tokens=len(content) // 4,
            cost=Decimal("0"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response={"fake": True},
        )


def _entries(block: re.Pattern[str], prompt: str) -> list[tuple[str, str]]:
    """
    Extract ``(key, label)`` pairs from a labelled section of the prompt.

    Args:
        block: Pattern isolating the section.
        prompt: The full user prompt.

    Returns:
        list[tuple[str, str]]: Entries in the order they appear.
    """
    match = block.search(prompt)
    if not match:
        return []
    return [(key, (label or "").strip()) for key, label in _ENTRY_LINE.findall(match.group(1))]


def _fenced_answer(prompt: str) -> str:
    """
    Extract the student's answer from between the two fence lines.

    Returns an empty string when the fence is missing or unpaired, which grades as a zero rather
    than falling back to the whole prompt — treating the rubric as the student's answer would
    score every malformed prompt as perfect.

    Args:
        prompt: The full user prompt.

    Returns:
        str: The fenced answer, or an empty string.
    """
    fences = _FENCE.findall(prompt)
    if len(fences) < 1:
        return ""
    fence = fences[0]
    parts = prompt.split(f"\n{fence}\n")
    return parts[1].rsplit(f"\n{fence}", 1)[0] if len(parts) > 1 else ""


def _terms(text: str) -> set[str]:
    """
    Reduce text to a set of significant lowercase terms.

    Args:
        text: Text to tokenise.

    Returns:
        set[str]: Terms with stopwords and single characters removed.
    """
    return {
        word for word in _WORD.findall(text.lower()) if len(word) > 1 and word not in _STOPWORDS
    }


def _covers(answer_terms: set[str], key: str, label: str) -> bool:
    """
    Report whether an answer plausibly demonstrates a concept.

    Args:
        answer_terms: Significant terms from the student's answer.
        key: The concept key.
        label: The concept's human-readable label.

    Returns:
        bool: True when enough of the concept's terms appear in the answer.
    """
    concept_terms = _terms(f"{key.replace('_', ' ')} {label}")
    if not concept_terms:
        return False
    overlap = len(concept_terms & answer_terms) / len(concept_terms)
    return overlap >= _HIT_THRESHOLD


def _band_floors(prompt: str) -> tuple[int, int]:
    """
    Read the band floors the prompt declared.

    Args:
        prompt: The full user prompt.

    Returns:
        tuple[int, int]: The strong and developing floors, defaulting to 80 and 55.
    """
    match = _BANDS.search(prompt)
    return (int(match.group(1)), int(match.group(2))) if match else (80, 55)


def _feedback(hit: list[str], missed: list[str], concepts: list[tuple[str, str]]) -> str:
    """
    Build feedback naming what the answer covered and what it did not.

    Args:
        hit: Concept keys credited.
        missed: Concept keys not credited.
        concepts: All declared concepts, for their labels.

    Returns:
        str: Feedback text, never empty, since the schema requires it.
    """
    labels = dict(concepts)
    if not concepts:
        return "This question has no expected concepts recorded, so no coverage could be assessed."

    covered = ", ".join(labels[key] or key for key in hit[:3])
    gaps = ", ".join(labels[key] or key for key in missed[:3])
    if not hit:
        return f"This answer did not cover the expected ground. Start with {gaps}."
    if not missed:
        return f"This answer covered the expected ground, including {covered}."
    return f"Good coverage of {covered}. The answer did not address {gaps}."
