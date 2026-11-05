from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Entity(ORMModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Message(BaseModel):
    message: str
