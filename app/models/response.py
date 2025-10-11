"""ORM model for Response with uniqueness over (response_set_id, question_id)."""

from __future__ import annotations

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer, Boolean, JSON, Numeric, Text, UniqueConstraint


Base = declarative_base()


class Response(Base):  # type: ignore[valid-type]
    __tablename__ = "response"
    __table_args__ = (
        UniqueConstraint("response_set_id", "question_id", name="uq_response_set_question"),
    )

    response_id = Column(String, primary_key=True)
    response_set_id = Column(String, nullable=False)
    question_id = Column(String, nullable=False)
    option_id = Column(String, nullable=True)
    state_version = Column(Integer, nullable=True)
    value_bool = Column(Boolean, nullable=True)
    value_json = Column(JSON, nullable=True)
    value_number = Column(Numeric, nullable=True)
    value_text = Column(Text, nullable=True)


__all__ = ["Response", "Base"]

