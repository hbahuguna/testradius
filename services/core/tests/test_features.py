import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from testsquad_shared.persistence.models import FeatureFlag, Project
from testsquad_core.features.service import (
    is_feature_enabled,
    get_project_features,
    set_project_features,
)


@pytest.fixture
async def project(session: AsyncSession) -> Project:
    p = Project(name="test-project")
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


def test_feature_flag_model():
    flag = FeatureFlag(project_id=1, flag_name="test_mapping", enabled=True)
    assert flag.flag_name == "test_mapping"
    assert flag.enabled is True
    assert flag.project_id == 1
    assert flag.id is None


def test_feature_flag_default_enabled():
    flag = FeatureFlag(project_id=2, flag_name="brain_sync")
    assert flag.enabled is False


@pytest.mark.asyncio
async def test_is_feature_enabled_default_false(session: AsyncSession):
    result = await is_feature_enabled(999, "nonexistent", session)
    assert result is False


@pytest.mark.asyncio
async def test_is_feature_enabled_true(session: AsyncSession, project: Project):
    flag = FeatureFlag(project_id=project.id, flag_name="brain_sync", enabled=True)
    session.add(flag)
    await session.commit()

    result = await is_feature_enabled(project.id, "brain_sync", session)
    assert result is True


@pytest.mark.asyncio
async def test_get_project_features_empty(session: AsyncSession, project: Project):
    features = await get_project_features(project.id, session)
    assert features == {}


@pytest.mark.asyncio
async def test_get_project_features(session: AsyncSession, project: Project):
    session.add_all([
        FeatureFlag(project_id=project.id, flag_name="brain_sync", enabled=True),
        FeatureFlag(project_id=project.id, flag_name="test_mapping", enabled=False),
    ])
    await session.commit()

    features = await get_project_features(project.id, session)
    assert features == {"brain_sync": True, "test_mapping": False}


@pytest.mark.asyncio
async def test_set_project_features_upsert(session: AsyncSession, project: Project):
    await set_project_features(
        project.id, {"brain_sync": True, "test_mapping": False}, session
    )

    result = await session.execute(
        select(FeatureFlag).where(FeatureFlag.project_id == project.id)
    )
    flags = {(f.flag_name, f.enabled) for f in result.scalars().all()}
    assert ("brain_sync", True) in flags
    assert ("test_mapping", False) in flags


@pytest.mark.asyncio
async def test_set_project_features_update_existing(
    session: AsyncSession, project: Project
):
    session.add(FeatureFlag(project_id=project.id, flag_name="brain_sync", enabled=False))
    await session.commit()

    await set_project_features(project.id, {"brain_sync": True}, session)

    result = await is_feature_enabled(project.id, "brain_sync", session)
    assert result is True
