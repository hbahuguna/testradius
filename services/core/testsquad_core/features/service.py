import logging
from datetime import datetime
from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from testsquad_shared.persistence.models import FeatureFlag, Project

logger = logging.getLogger(__name__)


async def _ensure_project(project_id: int, session: AsyncSession):
    result = await session.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        project = Project(id=project_id, name=f"Project-{project_id}")
        session.add(project)
        await session.commit()


async def is_feature_enabled(
    project_id: int, flag_name: str, session: AsyncSession
) -> bool:
    with session.no_autoflush:
        result = await session.execute(
            select(FeatureFlag).where(
                FeatureFlag.project_id == project_id,
                FeatureFlag.flag_name == flag_name,
            )
        )
    flag = result.scalar_one_or_none()
    return flag.enabled if flag else False


async def get_project_features(
    project_id: int, session: AsyncSession
) -> Dict[str, bool]:
    with session.no_autoflush:
        result = await session.execute(
            select(FeatureFlag).where(FeatureFlag.project_id == project_id)
        )
    flags = result.scalars().all()
    return {f.flag_name: f.enabled for f in flags}


async def set_project_features(
    project_id: int, features: Dict[str, bool], session: AsyncSession
):
    await _ensure_project(project_id, session)
    with session.no_autoflush:
        for name, enabled in features.items():
            result = await session.execute(
                select(FeatureFlag).where(
                    FeatureFlag.project_id == project_id,
                    FeatureFlag.flag_name == name,
                )
            )
            flag = result.scalar_one_or_none()
            if flag:
                flag.enabled = enabled
                flag.updated_at = datetime.utcnow()
            else:
                flag = FeatureFlag(
                    project_id=project_id, flag_name=name, enabled=enabled
                )
                session.add(flag)
    await session.commit()
