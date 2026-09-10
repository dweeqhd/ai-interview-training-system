from collections.abc import Generator

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    columns = {item["name"] for item in inspect(engine).get_columns("interview_answers")}
    if "asr_transcript" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE interview_answers ADD COLUMN asr_transcript TEXT"
            )
            connection.exec_driver_sql(
                "UPDATE interview_answers SET asr_transcript = transcript "
                "WHERE transcript IS NOT NULL"
            )


def get_db() -> Generator[Session, None, None]:
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
