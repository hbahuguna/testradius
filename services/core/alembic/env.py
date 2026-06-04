import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlmodel import SQLModel

from alembic import context

# add your model's MetaData object here
# for 'autogenerate' support
# Add the project root to sys.path so we can find testsquad_shared and local packages
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared')))
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..')))

from testsquad_shared.persistence.models import Project, Repository, Scan, StyleCapsule, FeatureFlag
from testsquad_core.persistence.run_models import Run, RunResult
import sqlmodel
target_metadata = SQLModel.metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def get_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("postgresql+asyncpg://", "postgresql://")
    
    ini_url = config.get_main_option("sqlalchemy.url")
    if not ini_url or "driver://" in ini_url:
        raise ValueError(
            "DATABASE_URL environment variable is not set and alembic.ini contains the default placeholder. "
            "Please set DATABASE_URL (e.g., export DATABASE_URL=postgresql+asyncpg://user:pass@localhost/db)"
        )
    return ini_url

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
