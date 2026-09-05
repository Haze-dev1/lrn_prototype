"""Core application package.

Re-exports the shared logger helper so modules can use the Eigi-standard
``from core import logger`` import.
"""

from commons.logger import logger

__all__ = ["logger"]
