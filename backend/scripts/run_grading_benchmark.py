"""Run the grading benchmark against the configured provider.

Run this before changing the grading model, the prompt, or a rubric, and compare the result to
the run before. A change that lowers agreement is a regression however good it looked in
isolation.

Uses whatever ``GRADING_PROVIDER`` is set to. Against ``groq`` this makes one real, billable
model call per case; against ``fake`` it makes none, which validates the harness but says nothing
about grading quality.

Run it as a module, not as a file path, or ``core`` will not be importable:

    uv run python -m scripts.run_grading_benchmark [--json] [--file PATH]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from core import logger
from core.database.database import close_database_connection
from core.services.ai.benchmark import BenchmarkReport, GradingBenchmark

logging = logger(__name__)


def render(report: BenchmarkReport) -> str:
    """
    Format a benchmark report for a terminal.

    Args:
        report: The completed report.

    Returns:
        str: Human-readable summary.
    """
    summary = report.as_dict()
    lines = [
        f"provider   {summary['provider']}",
        f"model      {summary['model']}",
        f"prompt     {summary['prompt_version']}",
        f"cases      {summary['graded']} graded, {summary['errors']} error(s)",
        f"agreement  {summary['agreement']:.0%}",
        "",
        "By answer type:",
    ]
    lines += [f"  {label:28} {value:.0%}" for label, value in summary["agreement_by_label"].items()]

    if summary["severe_disagreements"]:
        lines += ["", "Severe disagreements (two bands out):"]
        lines += [
            f"  {item['id']:32} expected {item['expected']:<12} got {item['actual']} "
            f"(score {item['score']})"
            for item in summary["severe_disagreements"]
        ]

    disagreed = [row for row in summary["results"] if not row["agreed"] and row["actual"]]
    if disagreed:
        lines += ["", "All disagreements:"]
        lines += [
            f"  {row['id']:32} expected {row['expected']:<12} got {row['actual']} "
            f"(score {row['score']})"
            for row in disagreed
        ]

    errors = [row for row in summary["results"] if row["error"]]
    if errors:
        lines += ["", "Errors:"]
        lines += [f"  {row['id']:32} {row['error']}" for row in errors]

    return "\n".join(lines)


async def main() -> int:
    """
    Run the benchmark and print its report.

    Returns:
        int: 0 when every case graded, 1 when any case failed to produce a grade.
    """
    parser = argparse.ArgumentParser(description="Run the grading benchmark.")
    parser.add_argument("--json", action="store_true", help="Emit the raw report as JSON.")
    parser.add_argument("--file", type=Path, default=None, help="Path to a benchmark case file.")
    args = parser.parse_args()

    try:
        report = await GradingBenchmark(path=args.file).run()
    except (FileNotFoundError, ValueError) as error:
        logging.error(f"Benchmark failed: {error}")
        print(f"Benchmark failed: {error}", file=sys.stderr)
        return 1
    finally:
        await close_database_connection()

    print(json.dumps(report.as_dict(), indent=2) if args.json else render(report))
    # A non-zero exit means the harness could not evaluate the grader, not that the grader scored
    # badly. Quality is a judgement to make against the previous run, not a threshold to encode.
    return 1 if len(report.graded) < len(report.outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
