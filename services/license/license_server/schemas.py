from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActivationRequest(BaseModel):
    license_key: str
    device_fingerprint: str = Field(min_length=8, max_length=128)


class ActivationResponse(BaseModel):
    activation_token: str
    subscription_status: str
    quota_remaining: int
    grace_until: Optional[datetime] = None
    device_limit: int


class ValidateResponse(BaseModel):
    subscription_status: str
    quota_remaining: int
    grace_until: Optional[datetime] = None


class RunRequest(BaseModel):
    run_id: str = Field(min_length=8, max_length=64)
    metadata: Optional[dict] = None


class RunResponse(BaseModel):
    recorded: bool
    quota_remaining: int


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class LicenseCreate(BaseModel):
    email: Optional[str] = None
    runs_quota: Optional[int] = None
    device_limit: Optional[int] = None


class LicenseOut(BaseModel):
    license_key: str
    email: Optional[str]
    subscription_status: str
    runs_quota: int
    device_limit: int
    current_period_end: Optional[datetime]
    created_at: datetime
