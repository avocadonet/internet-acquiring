"""Configuration settings for outbox_engine module."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OutboxConfig(BaseSettings):
    """Outbox engine configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    poll_interval_seconds: float = Field(
        default=1.0,
        validation_alias="OUTBOX_POLL_INTERVAL_SECONDS",
        ge=0.1,
        description="Polling loop interval in seconds when no tasks are ready",
    )
    batch_size: int = Field(
        default=10,
        validation_alias="OUTBOX_BATCH_SIZE",
        ge=1,
        le=500,
        description="Maximum number of tasks to lock and acquire per poll batch",
    )
    lease_seconds: int = Field(
        default=60,
        validation_alias="OUTBOX_LEASE_SECONDS",
        ge=5,
        description="Duration in seconds of the distributed lease lock (locked_until)",
    )
    max_retries: int = Field(
        default=5,
        validation_alias="OUTBOX_MAX_RETRIES",
        ge=1,
        description="Default maximum retry attempts for transient errors",
    )
    max_concurrent_tasks: int = Field(
        default=20,
        validation_alias="OUTBOX_MAX_CONCURRENT_TASKS",
        ge=1,
        description="Maximum concurrent asynchronous tasks handled by the worker",
    )