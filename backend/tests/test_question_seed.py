"""Tests for loading the authored question bank.

The property under test is idempotency that preserves history: re-running the seed must not
create versions, because version history exists to explain past grades and would become noise if
every deploy appended an identical row.

The real content file is also loaded here, so a malformed or incomplete question committed to
`seeds/questions.json` fails CI rather than a deployment.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from core.constants.enums import QuestionStatus, QuestionVersionStatus
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.services.questions.rubric_service import RubricValidator
from core.services.questions.seed_service import DEFAULT_SEED_PATH, QuestionSeeder
from tests.conftest import requires_database

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]

VALID_IDEAL_ANSWER = (
    "Subtract net debt from enterprise value: start with enterprise value, subtract total debt, "
    "add back cash and equivalents, and adjust for preferred stock and minority interest to "
    "reach equity value available to common shareholders."
)


def seed_entry(**overrides: Any) -> dict[str, Any]:
    """
    Build one valid seed entry.

    Args:
        **overrides: Fields to override on the valid default.

    Returns:
        dict[str, Any]: A seed entry that passes validation.
    """
    entry: dict[str, Any] = {
        "source_key": "test-001",
        "category_slug": "valuation",
        "subcategory": "Comps",
        "difficulty": 3,
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
    entry.update(overrides)
    return entry


def write_seed(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    """
    Write a temporary seed file.

    Args:
        tmp_path: Pytest temporary directory.
        entries: Entries to write.

    Returns:
        Path: Path to the written file.
    """
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"questions": entries}))
    return path


class TestSeeding:
    """Loading content into an empty bank."""

    async def test_seeding_creates_an_active_published_question(self, tmp_path: Path) -> None:
        """One entry becomes one active question with one published version."""
        path = write_seed(tmp_path, [seed_entry()])

        summary = await QuestionSeeder(seed_path=path).run()

        assert summary["created"] == 1
        question = await CRUDQuestion().get_by_source_key(source_key="test-001")
        assert question is not None
        assert question.status == QuestionStatus.ACTIVE

        published = await CRUDQuestionVersion().get_published(question_id=question.id)
        assert published is not None
        assert published.prompt == seed_entry()["prompt"]

    async def test_no_activate_leaves_the_question_in_draft(self, tmp_path: Path) -> None:
        """Content can be loaded without putting it in front of students."""
        path = write_seed(tmp_path, [seed_entry()])

        await QuestionSeeder(seed_path=path).run(activate=False)

        question = await CRUDQuestion().get_by_source_key(source_key="test-001")
        assert question is not None
        assert question.status == QuestionStatus.DRAFT

    async def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        """A dry run validates and reports without touching the database."""
        path = write_seed(tmp_path, [seed_entry()])

        summary = await QuestionSeeder(seed_path=path).run(dry_run=True)

        assert summary["dry_run"] is True
        assert summary["created"] == 0
        assert await CRUDQuestion().get_by_source_key(source_key="test-001") is None


class TestIdempotency:
    """Re-running the seed must preserve version history."""

    async def test_rerunning_unchanged_content_creates_no_version(self, tmp_path: Path) -> None:
        """The second run reports the entry unchanged and adds nothing.

        Without content-hash comparison every deploy would publish an identical version, and the
        history that explains past grades would fill with noise.
        """
        path = write_seed(tmp_path, [seed_entry()])
        await QuestionSeeder(seed_path=path).run()

        summary = await QuestionSeeder(seed_path=path).run()

        assert summary["unchanged"] == 1
        assert summary["created"] == 0
        question = await CRUDQuestion().get_by_source_key(source_key="test-001")
        assert question is not None
        versions = await CRUDQuestionVersion().list_for_question(question_id=question.id)
        assert len(versions) == 1

    async def test_reordering_json_keys_is_not_a_content_change(self, tmp_path: Path) -> None:
        """Field order in the file must not look like an edit.

        The hash is taken over canonical sorted JSON, so reformatting the content file cannot
        churn every question's version history.
        """
        path = write_seed(tmp_path, [seed_entry()])
        await QuestionSeeder(seed_path=path).run()

        entry = seed_entry()
        reordered = {key: entry[key] for key in reversed(list(entry))}
        summary = await QuestionSeeder(seed_path=write_seed(tmp_path, [reordered])).run()

        assert summary["unchanged"] == 1

    async def test_changed_content_publishes_a_new_version_and_supersedes_the_old(
        self, tmp_path: Path
    ) -> None:
        """An edited prompt creates version 2 and supersedes version 1, preserving both."""
        path = write_seed(tmp_path, [seed_entry()])
        await QuestionSeeder(seed_path=path).run()

        edited = seed_entry(prompt="How exactly do you bridge enterprise value to equity value?")
        summary = await QuestionSeeder(seed_path=write_seed(tmp_path, [edited])).run()

        assert summary["updated"] == 1
        question = await CRUDQuestion().get_by_source_key(source_key="test-001")
        assert question is not None

        versions = await CRUDQuestionVersion().list_for_question(question_id=question.id)
        assert len(versions) == 2
        assert {version.status for version in versions} == {
            QuestionVersionStatus.PUBLISHED,
            QuestionVersionStatus.SUPERSEDED,
        }

        published = await CRUDQuestionVersion().get_published(question_id=question.id)
        assert published is not None
        assert published.prompt == edited["prompt"]

    async def test_taxonomy_changes_do_not_create_a_version(self, tmp_path: Path) -> None:
        """Recategorising is not a rubric change, so it must not touch version history."""
        path = write_seed(tmp_path, [seed_entry()])
        await QuestionSeeder(seed_path=path).run()

        moved = seed_entry(category_slug="dcf", difficulty=5)
        await QuestionSeeder(seed_path=write_seed(tmp_path, [moved])).run()

        question = await CRUDQuestion().get_by_source_key(source_key="test-001")
        assert question is not None
        assert question.category_slug == "dcf"
        assert question.difficulty == 5

        versions = await CRUDQuestionVersion().list_for_question(question_id=question.id)
        assert len(versions) == 1

    async def test_seeding_does_not_duplicate_on_repeat(self, tmp_path: Path) -> None:
        """Three runs produce one question, not three."""
        path = write_seed(tmp_path, [seed_entry()])
        for _ in range(3):
            await QuestionSeeder(seed_path=path).run()

        questions = await CRUDQuestion().list_for_admin(limit=100)

        assert len([item for item in questions if item.source_key == "test-001"]) == 1


class TestSeedValidation:
    """Bad content must fail loudly before anything is written."""

    async def test_invalid_content_aborts_the_whole_run(self, tmp_path: Path) -> None:
        """A single broken entry fails the run; a half-seeded bank is worse than none."""
        path = write_seed(
            tmp_path, [seed_entry(), seed_entry(source_key="test-002", expected_concepts=[])]
        )

        with pytest.raises(ValueError, match="failed rubric validation"):
            await QuestionSeeder(seed_path=path).run()

        assert await CRUDQuestion().get_by_source_key(source_key="test-001") is None

    async def test_duplicate_source_keys_are_rejected(self, tmp_path: Path) -> None:
        """Two entries claiming one key would make the upsert ambiguous and lose a question."""
        path = write_seed(tmp_path, [seed_entry(), seed_entry()])

        with pytest.raises(ValueError, match="Duplicate source keys"):
            await QuestionSeeder(seed_path=path).run()

    async def test_a_missing_source_key_is_rejected(self, tmp_path: Path) -> None:
        """Without a key the entry could never be matched on a later run."""
        entry = seed_entry()
        del entry["source_key"]
        path = write_seed(tmp_path, [entry])

        with pytest.raises(ValueError, match="source_key"):
            await QuestionSeeder(seed_path=path).run()

    async def test_an_unknown_category_is_rejected_before_writing(self, tmp_path: Path) -> None:
        """A typo in a category slug fails up front rather than midway through the bank."""
        path = write_seed(tmp_path, [seed_entry(category_slug="not-a-category")])

        with pytest.raises(ValueError, match="categories that do not exist"):
            await QuestionSeeder(seed_path=path).run()

        assert await CRUDQuestion().get_by_source_key(source_key="test-001") is None

    async def test_a_missing_file_is_reported_clearly(self, tmp_path: Path) -> None:
        """A wrong path is a clear error, not an empty successful run."""
        with pytest.raises(FileNotFoundError):
            await QuestionSeeder(seed_path=tmp_path / "absent.json").run()


class TestShippedContent:
    """The question bank actually committed to the repository."""

    def test_the_shipped_seed_file_exists_and_parses(self) -> None:
        """The default content file is present and is valid JSON."""
        assert DEFAULT_SEED_PATH.exists()
        payload = json.loads(DEFAULT_SEED_PATH.read_text())
        assert payload["questions"]

    def test_every_shipped_question_passes_rubric_validation(self) -> None:
        """No question in the repository can enter the graded pool incomplete.

        This is the check that stops a content edit shipping a question that would degrade every
        grade produced from it.
        """
        seeder = QuestionSeeder()
        validator = RubricValidator()

        failures = [
            f"{entry['source_key']}: {'; '.join(validator.validate(version=seeder._content(entry)).errors)}"
            for entry in seeder._load()
            if not validator.validate(version=seeder._content(entry)).is_valid
        ]

        assert failures == [], f"invalid shipped questions: {failures}"

    def test_the_shipped_bank_can_compose_a_diagnostic(self) -> None:
        """Every category has at least the three questions a diagnostic draws from it.

        Asserted against the content file rather than the database, so the guarantee holds before
        anything is deployed.
        """
        from collections import Counter

        from core.controllers.admin_question_controller import (
            DIAGNOSTIC_QUESTIONS_PER_CATEGORY,
        )

        counts = Counter(entry["category_slug"] for entry in QuestionSeeder()._load())
        thin = {
            slug: count
            for slug, count in counts.items()
            if count < DIAGNOSTIC_QUESTIONS_PER_CATEGORY
        }

        assert len(counts) == 8, f"expected all eight categories, got {sorted(counts)}"
        assert thin == {}, f"categories with too few questions: {thin}"

    async def test_the_shipped_bank_seeds_and_is_diagnostic_ready(self) -> None:
        """Loading the real content file leaves the bank able to compose a diagnostic."""
        from core.controllers.admin_question_controller import AdminQuestionController

        summary = await QuestionSeeder().run()
        coverage = await AdminQuestionController().coverage()

        assert summary["created"] == summary["total"]
        assert coverage["diagnostic_ready"] is True
        assert coverage["total_selectable"] == summary["total"]
