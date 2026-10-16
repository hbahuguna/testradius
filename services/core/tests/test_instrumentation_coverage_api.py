import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from testsquad_shared.persistence.models import Project, User
from testsquad_core.persistence.run_models import InstrumentationRun
from testsquad_core.main import (
    get_instrumentation_coverage,
    _instrumentation_coverage_payload,
    _record_instrumentation_run,
)


@pytest.fixture
async def project(session: AsyncSession) -> Project:
    p = Project(name="coverage-project")
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


def _row(**overrides) -> InstrumentationRun:
    row = InstrumentationRun(
        project_id=1,
        status="COMPLETED",
        edge_count=42,
        test_files_expected=52,
        test_files_collectable=31,
        test_files_scheduled=31,
        test_files_instrumented=30,
        coverage_pct=96.8,
        missing_count=1,
        details={"missing_test_files": ["tests/x.py"]},
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def test_payload_no_warning_when_coverage_high():
    payload = _instrumentation_coverage_payload(_row())
    assert payload["coverage_pct"] == 96.8
    assert payload["test_files_instrumented"] == 30
    assert payload["missing_test_files"] == ["tests/x.py"]
    assert payload["low_coverage"] is False
    assert "warning" not in payload


def test_payload_warns_when_coverage_low():
    payload = _instrumentation_coverage_payload(_row(coverage_pct=48.4, missing_count=16))
    assert payload["low_coverage"] is True
    assert "48.4%" in payload["warning"]
    assert "16 test file(s)" in payload["warning"]


@pytest.mark.asyncio
async def test_record_then_get_round_trip(session: AsyncSession, project: Project):
    coverage = {
        "test_files_expected": 52,
        "test_files_collectable": 31,
        "test_files_scheduled": 31,
        "test_files_instrumented": 30,
        "coverage_pct": 96.8,
        "missing_count": 1,
        "missing_test_files": ["tests/x.py"],
    }
    await _record_instrumentation_run(project.id, "COMPLETED", 42, coverage)

    result = await session.execute(
        select(InstrumentationRun).where(InstrumentationRun.project_id == project.id)
    )
    stored = result.scalars().first()
    assert stored is not None
    assert stored.coverage_pct == 96.8 and stored.edge_count == 42

    user = User(id="test-user-id", email="test@testsquad.io", full_name="Test User")
    out = await get_instrumentation_coverage(project.id, session=session, current_user=user)
    assert out["coverage_pct"] == 96.8
    assert out["test_files_instrumented"] == 30
    assert out["low_coverage"] is False


@pytest.mark.asyncio
async def test_record_handles_missing_coverage(session: AsyncSession, project: Project):
    await _record_instrumentation_run(project.id, "ERROR", 0, None)
    result = await session.execute(
        select(InstrumentationRun).where(InstrumentationRun.project_id == project.id)
    )
    stored = result.scalars().first()
    assert stored is not None
    assert stored.status == "ERROR" and stored.coverage_pct == 0.0


@pytest.mark.asyncio
async def test_unreported_run_is_not_flagged_as_low_coverage(
    session: AsyncSession, project: Project,
):
    """Story 11.8: a run whose pipeline reported nothing must not warn.

    Before 11.8 a TS/Playwright run stored all-zero metrics with no way to tell
    them apart from a genuine 0% run, so every such project warned.
    """
    await _record_instrumentation_run(project.id, "COMPLETED", 72, None)

    result = await session.execute(
        select(InstrumentationRun).where(InstrumentationRun.project_id == project.id)
    )
    stored = result.scalars().first()
    assert stored is not None
    # The zero metrics are still stored, but they are now marked as unreported.
    assert stored.coverage_pct == 0.0
    assert stored.details.get("not_reported") is True

    user = User(id="test-user-id", email="test@testsquad.io", full_name="Test User")
    out = await get_instrumentation_coverage(project.id, session=session, current_user=user)
    assert out["not_reported"] is True
    assert out["low_coverage"] is False
    assert "warning" not in out


@pytest.mark.asyncio
async def test_reported_run_is_marked_as_reported(session: AsyncSession, project: Project):
    coverage = {
        "test_files_expected": 10, "test_files_collectable": 10,
        "test_files_scheduled": 10, "test_files_instrumented": 10,
        "coverage_pct": 100.0, "missing_count": 0, "missing_test_files": [],
    }
    await _record_instrumentation_run(project.id, "COMPLETED", 60, coverage)

    result = await session.execute(
        select(InstrumentationRun).where(InstrumentationRun.project_id == project.id)
    )
    stored = result.scalars().first()
    assert stored is not None
    assert stored.details.get("not_reported") is False

    user = User(id="test-user-id", email="test@testsquad.io", full_name="Test User")
    out = await get_instrumentation_coverage(project.id, session=session, current_user=user)
    assert out["not_reported"] is False
    assert out["coverage_pct"] == 100.0


@pytest.mark.asyncio
async def test_get_404_without_runs(session: AsyncSession, project: Project):
    user = User(id="test-user-id", email="test@testsquad.io", full_name="Test User")
    with pytest.raises(HTTPException) as exc:
        await get_instrumentation_coverage(project.id, session=session, current_user=user)
    assert exc.value.status_code == 404
