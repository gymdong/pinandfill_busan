"""Small, explicit environment configuration; no API credentials are needed."""

import os

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app_name: str = "Pin & Fill Busan API"

    @classmethod
    def from_env(cls) -> "Settings":
        # Read only declared settings, never load or dump the complete environment.
        return cls(app_name=os.environ.get("PINANDFILL_APP_NAME", cls().app_name))
