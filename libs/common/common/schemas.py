from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Pagination:
    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Page size"),
        offset: int = Query(0, ge=0, description="Items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset
