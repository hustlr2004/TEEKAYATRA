from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ListQuery:
    page: int = 1
    page_size: int = 100
    sort: str = "id"
    order: str = "asc"
    q: Optional[str] = None
    role: Optional[str] = None
    block: Optional[str] = None
    district: Optional[str] = None
    status: Optional[str] = None

    @property
    def limit(self) -> int:
        return min(max(self.page_size, 1), 500)

    @property
    def offset(self) -> int:
        return (max(self.page, 1) - 1) * self.limit

    @property
    def descending(self) -> bool:
        return self.order.lower() == "desc"
