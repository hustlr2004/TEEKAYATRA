from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.seed import seed_demo_data
from app.services.gamification import village_leaderboard


@contextmanager
def query_counter(engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def main() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with Session(testing_session_local.kw["bind"]) as db:
        seed_demo_data(db, reset=True)
        with query_counter(engine) as statements:
            rows = village_leaderboard(db)
        query_count = len(statements)
    if query_count > 5:
        raise SystemExit("Potential N+1 query pattern: village_leaderboard used %s SQL statements" % query_count)
    print("N+1 check passed: village_leaderboard used %s SQL statements for %s villages" % (query_count, len(rows)))


if __name__ == "__main__":
    main()
