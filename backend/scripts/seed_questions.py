"""Command-line entry point for loading the authored question bank.

Kept as a thin wrapper: the logic lives in ``core.services.questions.seed_service`` so it is
testable and reusable, and so this file has nothing in it that could drift out of step.

Run it as a module, not as a file path: ``python scripts/seed_questions.py`` puts ``scripts/``
on ``sys.path`` instead of the application root, and ``core`` is then unimportable.

Usage:
    uv run python -m scripts.seed_questions [--dry-run] [--no-activate] [--file PATH]
"""

import argparse
import asyncio
import sys
from pathlib import Path

from core import logger
from core.database.database import close_database_connection
from core.services.questions.seed_service import QuestionSeeder

logging = logger(__name__)


async def main() -> int:
    """
    Parse arguments and run the question seeder.

    Returns:
        int: Process exit code; 0 on success, 1 when the content failed to load or validate.
    """
    parser = argparse.ArgumentParser(description="Load the authored question bank.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate the content file without writing."
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Publish content but leave questions in draft rather than activating them.",
    )
    parser.add_argument("--file", type=Path, default=None, help="Path to a content JSON file.")
    args = parser.parse_args()

    try:
        summary = await QuestionSeeder(seed_path=args.file).run(
            activate=not args.no_activate, dry_run=args.dry_run
        )
    except (FileNotFoundError, ValueError) as error:
        logging.error(f"Question seed failed: {error}")
        print(f"Seed failed: {error}", file=sys.stderr)
        return 1
    finally:
        await close_database_connection()

    print(
        f"{summary['total']} entries: {summary['created']} created, "
        f"{summary['updated']} updated, {summary['unchanged']} unchanged, "
        f"{summary['activated']} activated"
        + (" (dry run, nothing written)" if summary["dry_run"] else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
