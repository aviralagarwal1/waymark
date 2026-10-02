from alembic import context
from waymark.database import Database
from waymark.models import Base
from waymark.settings import Settings

config = context.config
target_metadata = Base.metadata
settings = Settings.from_env()

if context.is_offline_mode():
    context.configure(url=settings.db_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    db = Database(settings)
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
