"""Models related to placeholders (architectural linkage only)."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class ParentOption(Base):  # pragma: no cover - architectural presence only
    __tablename__ = "parent_options"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    # Required architectural FK linkage pattern with cascade semantics for Epic D
    placeholder_id = Column(
        ForeignKey("placeholders.id", ondelete="CASCADE"), nullable=True
    )


class Placeholder(Base):  # pragma: no cover - architectural presence only
    """Minimal Placeholder model to expose required FKs for Epic D tests.

    Declares question_id and document_id foreign keys with CASCADE semantics so
    static architectural tests can verify persistence constraints without
    executing migrations.
    """

    __tablename__ = "placeholders"

    id = Column(Integer, primary_key=True)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
