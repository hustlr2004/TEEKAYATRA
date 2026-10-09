from __future__ import annotations

from typing import Any, Callable, TypeVar

from fastapi import Depends

from ..database import get_db
from ..services.app_service import AppService

T = TypeVar("T")


class AppServiceRunner:
    def __init__(self, db: Any) -> None:
        self.db = db

    async def run(self, operation: Callable[[AppService], T]) -> T:
        if hasattr(self.db, "run_sync"):
            return await self.db.run_sync(lambda sync_db: operation(AppService(sync_db)))
        return operation(AppService(self.db))


def get_app_service(db: Any = Depends(get_db)) -> AppServiceRunner:
    return AppServiceRunner(db)
