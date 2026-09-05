"""Persistence models.

Every model module must be imported here so ``Base.metadata`` is fully populated before Alembic
autogenerates a migration. A model that is not imported here is silently missing from the schema
Alembic compares against, and its table simply never gets created.
"""

from core.models.attempt_model import Attempt, GradeEvent, GradeFlag
from core.models.auth_model import RefreshToken
from core.models.billing_model import BillingEvent, Subscription, UserEntitlement
from core.models.category_model import Category
from core.models.question_model import Question, QuestionVersion
from core.models.session_model import Session, SessionQuestion
from core.models.skill_score_model import SkillScore
from core.models.user_model import Profile, User

__all__ = [
    "Attempt",
    "BillingEvent",
    "Category",
    "GradeEvent",
    "GradeFlag",
    "Profile",
    "Question",
    "RefreshToken",
    "QuestionVersion",
    "Session",
    "SessionQuestion",
    "SkillScore",
    "Subscription",
    "User",
    "UserEntitlement",
]
