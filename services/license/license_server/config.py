import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    stripe_webhook_secret: str
    grace_days: int
    default_device_limit: int
    default_runs_per_period: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("LICENSE_DATABASE_URL", "sqlite:///./license.db"),
            admin_token=os.environ.get("LICENSE_ADMIN_TOKEN", ""),
            stripe_webhook_secret=os.environ.get("LICENSE_STRIPE_WEBHOOK_SECRET", ""),
            grace_days=int(os.environ.get("LICENSE_GRACE_DAYS", "3")),
            default_device_limit=int(os.environ.get("LICENSE_DEVICE_LIMIT", "3")),
            default_runs_per_period=int(os.environ.get("LICENSE_RUNS_PER_PERIOD", "500")),
        )
