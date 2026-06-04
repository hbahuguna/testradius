"""Unit tests for auth.py — JWT validation, demo mode, and user provisioning."""
import pytest
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestAuth:
    """Test authentication and authorization logic."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    def test_demo_mode_returns_mock_user(self, mock_session):
        """DEMO_MODE=true returns demo user without checking token."""
        with patch.dict(os.environ, {"DEMO_MODE": "true"}):
            from testsquad_core.auth import get_current_user
            from fastapi import Request

            mock_request = MagicMock(spec=Request)

            # HTTPBearer with auto_error=False returns None when no header
            result = get_current_user(
                request=mock_request,
                session=mock_session,
                credentials=None,
            )

            # In demo mode, returns a User object
            import asyncio
            user = asyncio.get_event_loop().run_until_complete(result)
            assert user.id == "demo-user-id"
            assert user.email == "demo@testsquad.io"

    def test_no_demo_no_credentials_returns_401(self, mock_session):
        """Without DEMO_MODE and without credentials, returns 401."""
        with patch.dict(os.environ, {"DEMO_MODE": "false"}, clear=True):
            from testsquad_core.auth import get_current_user
            from fastapi import Request

            mock_request = MagicMock(spec=Request)
            import asyncio
            from fastapi import HTTPException

            try:
                asyncio.get_event_loop().run_until_complete(
                    get_current_user(request=mock_request, session=mock_session, credentials=None)
                )
                assert False, "Should have raised HTTPException"
            except HTTPException as e:
                assert e.status_code == 401
                assert "Authorization header required" in e.detail

    def test_demo_mode_true_variant_strings(self, mock_session):
        """Any truthy value enables demo mode."""
        for value in ("true", "1", "yes", "TRUE", "Yes"):
            with patch.dict(os.environ, {"DEMO_MODE": value}):
                from testsquad_core.auth import get_current_user
                from fastapi import Request

                mock_request = MagicMock(spec=Request)
                import asyncio

                user = asyncio.get_event_loop().run_until_complete(
                    get_current_user(request=mock_request, session=mock_session, credentials=None)
                )
                assert user.id == "demo-user-id", f"DEMO_MODE={value} should work"

    def test_false_values_disable_demo_mode(self, mock_session):
        """False values do NOT enable demo mode."""
        for value in ("false", "0", "no", ""):
            with patch.dict(os.environ, {"DEMO_MODE": value}, clear=True):
                from testsquad_core.auth import get_current_user
                from fastapi import Request, HTTPException

                mock_request = MagicMock(spec=Request)
                import asyncio

                try:
                    asyncio.get_event_loop().run_until_complete(
                        get_current_user(request=mock_request, session=mock_session, credentials=None)
                    )
                    assert False, f"DEMO_MODE={value} should NOT enable demo"
                except HTTPException as e:
                    assert e.status_code == 401

    def test_missing_env_var_disables_demo_mode(self, mock_session):
        """When DEMO_MODE is not set, behave normally (require auth)."""
        with patch.dict(os.environ, {}, clear=True):
            from testsquad_core.auth import get_current_user
            from fastapi import Request, HTTPException

            mock_request = MagicMock(spec=Request)
            import asyncio

            try:
                asyncio.get_event_loop().run_until_complete(
                    get_current_user(request=mock_request, session=mock_session, credentials=None)
                )
                assert False, "Should require auth when no DEMO_MODE"
            except HTTPException as e:
                assert e.status_code == 401

    def test_demo_mode_skips_session_query(self, mock_session):
        """In demo mode, the DB session is NOT queried."""
        with patch.dict(os.environ, {"DEMO_MODE": "true"}):
            from testsquad_core.auth import get_current_user
            from fastapi import Request

            mock_request = MagicMock(spec=Request)
            import asyncio

            user = asyncio.get_event_loop().run_until_complete(
                get_current_user(request=mock_request, session=mock_session, credentials=None)
            )
            # Demo user is created without DB query
            mock_session.execute.assert_not_called()
            assert user.id == "demo-user-id"
