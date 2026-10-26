import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 - registers all tables on Base.metadata
from alembic import context
from app.database.sql import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Only the database URL is needed for migrations, so JWT_SECRET etc. need not be set.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://driftradar:driftradar@localhost:5432/driftradar"
)


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
