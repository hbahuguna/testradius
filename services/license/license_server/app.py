import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import Base, License, generate_license_key, utcnow
from .schemas import (
    ActivationRequest,
    ActivationResponse,
    ErrorResponse,
    LicenseCreate,
    LicenseOut,
    RunRequest,
    RunResponse,
    ValidateResponse,
)
from .service import (
    activate,
    record_run,
    validate as validate_activation,
)

openapi_tags = [
    {"name": "activations", "description": "Device activation for TIA agent licenses"},
    {"name": "validate", "description": "Daily license validation with offline grace"},
    {"name": "runs", "description": "Metering of completed TIA runs"},
    {"name": "webhooks", "description": "Stripe subscription webhooks"},
    {"name": "admin", "description": "License administration (token protected)"},
]


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    app = FastAPI(title="TIA License Server", version="1.0.0", openapi_tags=openapi_tags)
    app.state.settings = settings
    app.state.SessionLocal = SessionLocal

    def get_db():
        db: Session = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def get_settings() -> Settings:
        return settings

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post(
        "/v1/activations",
        response_model=ActivationResponse,
        responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
        tags=["activations"],
    )
    def post_activation(
        body: ActivationRequest,
        db: Session = Depends(get_db),
        cfg: Settings = Depends(get_settings),
    ):
        result = activate(db, cfg, body.license_key, body.device_fingerprint)
        if result is None:
            raise HTTPException(status_code=404, detail="Unknown license key or device limit reached")
        activation, decision, token = result
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.message)
        return ActivationResponse(
            activation_token=token,
            subscription_status=decision.status,
            quota_remaining=decision.quota_remaining,
            grace_until=decision.grace_until,
            device_limit=activation.license.device_limit if activation.license else 0,
        )

    @app.get(
        "/v1/validate",
        response_model=ValidateResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
        tags=["validate"],
    )
    def get_validate(
        authorization: str = Header(...),
        db: Session = Depends(get_db),
        cfg: Settings = Depends(get_settings),
    ):
        token = _extract_bearer(authorization)
        result = validate_activation(db, cfg, token)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid activation token")
        _, decision = result
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.message)
        return ValidateResponse(
            subscription_status=decision.status,
            quota_remaining=decision.quota_remaining,
            grace_until=decision.grace_until,
        )

    @app.post(
        "/v1/runs",
        response_model=RunResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
        tags=["runs"],
    )
    def post_run(
        body: RunRequest,
        authorization: str = Header(...),
        db: Session = Depends(get_db),
        cfg: Settings = Depends(get_settings),
    ):
        token = _extract_bearer(authorization)
        recorded, decision, error = record_run(db, cfg, token, body.run_id, body.metadata)
        if error == "invalid_token":
            raise HTTPException(status_code=401, detail="Invalid activation token")
        if error in ("blocked", "quota_exceeded"):
            raise HTTPException(status_code=403, detail=decision.message if decision else "Blocked")
        return RunResponse(recorded=recorded, quota_remaining=decision.quota_remaining)

    @app.post("/v1/webhooks/stripe", tags=["webhooks"])
    async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        cfg = request.app.state.settings
        if cfg.stripe_webhook_secret:
            _verify_stripe_signature(payload, sig, cfg.stripe_webhook_secret)
        event = json.loads(payload)
        _apply_stripe_event(db, event)
        return {"received": True}

    @app.post(
        "/v1/admin/licenses",
        response_model=LicenseOut,
        status_code=201,
        tags=["admin"],
    )
    def create_license(
        body: LicenseCreate,
        authorization: str = Header(...),
        db: Session = Depends(get_db),
        cfg: Settings = Depends(get_settings),
    ):
        _require_admin(authorization, cfg)
        license = License(
            license_key=generate_license_key(),
            email=body.email,
            subscription_status="active",
            runs_quota=body.runs_quota or cfg.default_runs_per_period,
            device_limit=body.device_limit or cfg.default_device_limit,
            created_at=utcnow(),
        )
        db.add(license)
        db.commit()
        db.refresh(license)
        return _license_out(license)

    @app.get("/v1/admin/licenses", response_model=list[LicenseOut], tags=["admin"])
    def list_licenses(
        authorization: str = Header(...),
        db: Session = Depends(get_db),
        cfg: Settings = Depends(get_settings),
    ):
        _require_admin(authorization, cfg)
        return [_license_out(l) for l in db.execute(select(License)).scalars().all()]

    return app


def _license_out(license: License) -> LicenseOut:
    return LicenseOut(
        license_key=license.license_key,
        email=license.email,
        subscription_status=license.subscription_status,
        runs_quota=license.runs_quota,
        device_limit=license.device_limit,
        current_period_end=license.current_period_end,
        created_at=license.created_at,
    )


def _extract_bearer(header: str) -> str:
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return header.strip()


def _require_admin(authorization: str, cfg: Settings) -> None:
    if not cfg.admin_token:
        raise HTTPException(status_code=503, detail="Admin API disabled (LICENSE_ADMIN_TOKEN not set)")
    token = _extract_bearer(authorization)
    if token != cfg.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")


def _verify_stripe_signature(payload: bytes, header: str, secret: str) -> None:
    import hashlib
    import hmac
    import time

    elements = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
    timestamp = elements.get("t", "")
    signature = elements.get("v1", "")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Malformed Stripe signature header")
    if abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(status_code=400, detail="Stripe signature timestamp out of tolerance")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")


def _apply_stripe_event(db: Session, event: dict) -> None:
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub_id = obj.get("id")
        license = db.execute(
            select(License).where(License.stripe_subscription_id == sub_id)
        ).scalar_one_or_none()
        if license is None:
            return
        license.subscription_status = obj.get("status", license.subscription_status)
        license.current_period_start = _ts(obj.get("current_period_start"))
        license.current_period_end = _ts(obj.get("current_period_end"))
        db.commit()
    elif event_type == "customer.created":
        pass


def _ts(value: Optional[int]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


app = create_app()
