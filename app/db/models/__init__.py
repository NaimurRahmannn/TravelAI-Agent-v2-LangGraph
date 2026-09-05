"""Database model package for future application tables.

This package intentionally remains lightweight during Phase A so later phases can
add concrete domain models without requiring a larger refactor.
"""

from app.db.base import Base

__all__ = ["Base"]
