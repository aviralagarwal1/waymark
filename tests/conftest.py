"""Run the suite against Postgres when TEST_DATABASE_URL is set; SQLite otherwise.

Tests build their own Settings with a temporary data directory. With
TEST_DATABASE_URL set, every Settings points at that database instead, and the
tables are emptied before each test so tests stay independent. Never point it
at a database whose data matters.
"""
import os

import pytest
from sqlalchemy import create_engine, text

from waymark.models import Base
from waymark.settings import Settings

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def postgres_when_configured(monkeypatch):
    if not TEST_DATABASE_URL:
        yield
        return
    url = Settings(database_url=TEST_DATABASE_URL).db_url
    monkeypatch.setattr(Settings, "db_url", property(lambda self: url))
    engine = create_engine(url, connect_args={"prepare_threshold": None})
    Base.metadata.create_all(engine)
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    engine.dispose()
    yield
