import os
import logging
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from testsquad_shared.persistence.db import get_session
from testsquad_shared.persistence.models import User

import httpx

logger = logging.getLogger("testsquad")

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else None

security = HTTPBearer(auto_error=False)

_jwks_cache = None


def _make_demo_user():
    return User(
        id="demo-user-id",
        email="demo@testsquad.io",
        full_name="Demo User",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=demo"
    )


async def get_jwks():
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    if not JWKS_URL:
        logger.warning("SUPABASE_URL not configured — JWKS unavailable")
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    except Exception as e:
        logger.warning("Failed to fetch JWKS: %s", e)
        return None
    return _jwks_cache


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    demo_mode = os.getenv("DEMO_MODE", "").lower() in ("true", "1", "yes")
    if demo_mode:
        # Ensure demo user exists in DB to satisfy foreign key constraints
        result = await session.execute(select(User).where(User.id == "demo-user-id"))
        user = result.scalar_one_or_none()
        if not user:
            user = _make_demo_user()
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )

    token = credentials.credentials

    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")

        if alg == "ES256":
            jwks = await get_jwks()
            if not jwks:
                raise Exception("JWKS not available for ES256 verification")
            payload = jwt.decode(token, jwks, algorithms=["ES256"], options={"verify_aud": False})
        else:
            payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})

        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Auth token validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            id=user_id,
            email=email,
            full_name=payload.get("user_metadata", {}).get("full_name") or payload.get("user_metadata", {}).get("name"),
            avatar_url=payload.get("user_metadata", {}).get("avatar_url") or payload.get("user_metadata", {}).get("picture"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user
