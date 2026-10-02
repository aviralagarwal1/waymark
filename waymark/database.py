from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from waymark.models import Base
from waymark.settings import Settings

# Any constant works; it only has to be the same in every process that creates tables.
SCHEMA_LOCK = 5_172_025


class Database:
    def __init__(self, settings: Settings):
        url = settings.db_url
        self.dialect = "sqlite" if url.startswith("sqlite") else "postgresql"
        if url.startswith("sqlite:///"):
            path = url.removeprefix("sqlite:///")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        if self.dialect == "sqlite":
            options = {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if url.endswith(":memory:"):
                from sqlalchemy.pool import StaticPool
                options["poolclass"] = StaticPool
        else:
            # Neon's pooler hands one server connection to many clients, so
            # server-side prepared statements are off; pre-ping replaces
            # connections the pooler or an idle compute closed.
            options = {"connect_args": {"prepare_threshold": None}, "pool_pre_ping": True, "pool_recycle": 300}
        self.engine = create_engine(url, **options)
        if self.dialect == "sqlite":
            @event.listens_for(self.engine, "connect")
            def sqlite_setup(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=30000")
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        # The initial Alembic revision uses this same metadata. Future schema changes
        # require migrations; create_all only creates missing initial tables.
        # The API and the worker both start here, often at the same moment.
        if self.dialect == "postgresql":
            with self.engine.begin() as connection:
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK})
                Base.metadata.create_all(connection)
            return
        try:
            Base.metadata.create_all(self.engine)
        except OperationalError as exc:
            # SQLite has no advisory lock: if the other process created a table
            # between the existence check and the CREATE, check again.
            if "already exists" not in str(exc):
                raise
            Base.metadata.create_all(self.engine)


def init_db(settings=None):
    db = Database(settings or Settings.from_env())
    db.initialize()
    return db
