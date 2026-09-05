"""Seed the eight V1 skill categories.

Categories are reference data the schema depends on — questions and skill scores both hold a
foreign key to them — so they are seeded by migration rather than by an application bootstrap
step. Kept in its own revision so the schema change and the data it requires stay separately
reviewable and separately reversible.

Revision ID: ddcf577347e2b
Revises: ddcf577347e2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ddcf577347e2b"
down_revision: str | None = "ddcf577347e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Taxonomy for investment banking and private equity technical recruiting. Ordering runs from
# foundational to applied, which is also the order the diagnostic presents them in.
CATEGORIES: list[dict[str, object]] = [
    {
        "slug": "accounting",
        "name": "Accounting",
        "description": "The three statements, how they link, and how transactions flow through them.",
        "display_order": 1,
    },
    {
        "slug": "enterprise-equity-value",
        "name": "Enterprise & Equity Value",
        "description": "The bridge between enterprise and equity value, and which metrics pair with which.",
        "display_order": 2,
    },
    {
        "slug": "valuation",
        "name": "Valuation (Comps & Precedents)",
        "description": "Trading comparables, precedent transactions, and when each is the right lens.",
        "display_order": 3,
    },
    {
        "slug": "dcf",
        "name": "DCF",
        "description": "Free cash flow, discount rates, terminal value, and DCF sensitivity.",
        "display_order": 4,
    },
    {
        "slug": "ma-merger-modelling",
        "name": "M&A / Merger Modelling",
        "description": "Deal structuring, accretion and dilution, synergies, and purchase accounting.",
        "display_order": 5,
    },
    {
        "slug": "lbo-private-equity",
        "name": "LBO & Private Equity",
        "description": "Leveraged buyout mechanics, returns drivers, debt structures, and exits.",
        "display_order": 6,
    },
    {
        "slug": "financial-statement-analysis",
        "name": "Financial Statement Analysis",
        "description": "Reading company performance: margins, working capital, leverage, and quality of earnings.",
        "display_order": 7,
    },
    {
        "slug": "markets-deals-judgment",
        "name": "Markets, Deals & Judgment",
        "description": "Market awareness, deal rationale, and the commercial judgment interviews probe for.",
        "display_order": 8,
    },
]


def upgrade() -> None:
    """Insert the eight V1 categories.

    Idempotent on slug so re-running against a partially seeded database is safe; an existing
    row keeps whatever copy edits it has received rather than being silently overwritten.
    """
    categories_table = sa.table(
        "categories",
        sa.column("slug", sa.Text),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("display_order", sa.SmallInteger),
    )
    statement = sa.dialects.postgresql.insert(categories_table).values(CATEGORIES)
    op.execute(statement.on_conflict_do_nothing(index_elements=["slug"]))


def downgrade() -> None:
    """Remove the seeded categories.

    Fails loudly if questions or skill scores still reference them, because the foreign keys use
    RESTRICT. That is intended: silently deleting a category would orphan graded evidence.
    """
    op.execute(
        sa.text("DELETE FROM categories WHERE slug = ANY(:slugs)").bindparams(
            sa.bindparam("slugs", [row["slug"] for row in CATEGORIES])
        )
    )
