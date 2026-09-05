"""Skill category reference data.

Categories are a table rather than an enum because the product displays a human-readable name and
a fixed ordering for each one, and because mastery scores and questions both reference them. The
eight V1 categories are seeded by migration.
"""

from sqlalchemy import CheckConstraint, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    """A top-level technical skill area a student is scored on."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("slug = lower(slug)", name="ck_categories_slug_lowercase"),
        CheckConstraint("display_order > 0", name="ck_categories_display_order_positive"),
    )

    # The slug is the primary key: it is stable, human-readable in logs and API payloads, and
    # saves a join whenever a question or skill score only needs to name its category.
    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, unique=True)
