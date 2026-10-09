from __future__ import annotations

from sqlalchemy.orm import Session


class Repository:
    def __init__(self, db: Session) -> None:
        self.db = db
