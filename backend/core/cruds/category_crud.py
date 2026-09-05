"""Database access for skill categories."""

from sqlalchemy import select

from core import logger
from core.database.database import session
from core.models.category_model import Category

logging = logger(__name__)


class CRUDCategory:
    """Database access layer for the skill category reference table."""

    async def list_all(self) -> list[Category]:
        """
        Read every category in display order.

        Returns:
            list[Category]: All categories, ordered for presentation.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDCategory.list_all")
            async with session() as db:
                result = await db.execute(select(Category).order_by(Category.display_order))
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDCategory.list_all: {error}")
            raise error

    async def get_by_slug(self, *, slug: str) -> Category | None:
        """
        Read one category by its slug.

        Args:
            slug: Category slug, for example 'valuation'.

        Returns:
            Category | None: The category if it exists, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDCategory.get_by_slug")
            async with session() as db:
                category = await db.get(Category, slug)
            if not category:
                logging.warning(f"No category found with slug: {slug}")
            return category
        except Exception as error:
            logging.error(f"Error in CRUDCategory.get_by_slug: {error}")
            raise error
