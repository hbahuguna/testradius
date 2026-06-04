import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from testsquad_shared.persistence.db import DATABASE_URL
from testsquad_shared.persistence.models import Project, StyleCapsule, Repository, Scan
from testsquad_core.persistence.run_models import Run, RunResult

@pytest.fixture
async def engine():
    from testsquad_shared.persistence import db
    engine = create_async_engine(DATABASE_URL)
    db._engine = engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        from testsquad_core.main import app, get_session, get_current_user
        from testsquad_shared.persistence.models import User
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: User(
            id="test-user-id", email="test@testsquad.io", full_name="Test User"
        )
        yield session
        app.dependency_overrides.clear()
