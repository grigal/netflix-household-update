"""Configuration management using Pydantic settings."""

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # IMAP Email Configuration
    imap_server: str = Field(..., description="IMAP server address")
    imap_port: int = Field(default=993, description="IMAP server port")
    imap_user: str = Field(..., description="IMAP username")
    imap_pass: SecretStr = Field(..., description="IMAP password")

    # Mailbox Settings
    mailbox_name: str = Field(default="INBOX", description="Mailbox to monitor")
    move_emails_to_mailbox: bool = Field(
        default=True, description="Move processed emails to another folder"
    )
    move_to_mailbox_name: str = Field(
        default="Netflix", description="Destination folder for processed emails"
    )

    # Netflix Credentials
    netflix_user: str = Field(..., description="Netflix account email")
    netflix_pass: SecretStr = Field(..., description="Netflix account password")

    # Application Settings
    polling_time_in_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Polling interval (only used if IMAP IDLE not available)",
    )
    idle_timeout_seconds: int = Field(
        default=300,
        ge=60,
        le=1740,
        description="IMAP IDLE timeout in seconds (default 5 minutes, max 29 minutes per RFC 2177)",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

    # Database
    database_path: Path = Field(
        default=Path("netflix_updater.db"), description="SQLite database path"
    )

    # Netflix Email Detection Constants
    sender_emails: list[str] = Field(
        default=["info@account.netflix.com"],
        description="Authorized Netflix sender addresses",
    )
    netflix_link_patterns: list[str] = Field(
        default=[
            "www.netflix.com/account/update-primary",
            "www.netflix.com/account/set-primary",
        ],
        description="URL patterns to match in Netflix emails",
    )
    button_search_attr_name: str = Field(
        default="data-uia", description="HTML attribute name for confirmation button"
    )
    button_search_attr_value: str = Field(
        default="set-primary-location-action",
        description="HTML attribute value for confirmation button",
    )

    @field_validator("imap_server", "imap_user", "netflix_user")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure required string fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("sender_emails")
    @classmethod
    def validate_sender_emails(cls, v: list[str]) -> list[str]:
        """Ensure at least one authorized sender exists."""
        if not v or len(v) == 0:
            raise ValueError("At least one authorized sender email must be configured")
        # Strip whitespace from all sender emails
        return [email.strip() for email in v if email.strip()]

    @field_validator("database_path")
    @classmethod
    def validate_database_path(cls, v: Path) -> Path:
        """Ensure database directory exists."""
        if v.parent != Path(".") and not v.parent.exists():
            v.parent.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def logging_level(self) -> int:
        """Convert log level string to logging constant."""
        return getattr(logging, self.log_level)

    def get_imap_password(self) -> str:
        """Get IMAP password as plain string."""
        return self.imap_pass.get_secret_value()

    def get_netflix_password(self) -> str:
        """Get Netflix password as plain string."""
        return self.netflix_pass.get_secret_value()


def load_settings() -> Settings:
    """Load and validate settings from environment."""
    try:
        settings = Settings()

        # Log loaded configuration for debugging
        import structlog
        logger = structlog.get_logger(__name__)
        logger.info(
            "configuration_loaded",
            sender_emails=settings.sender_emails,
            netflix_link_patterns=settings.netflix_link_patterns,
            mailbox=settings.mailbox_name,
            move_emails=settings.move_emails_to_mailbox,
        )

        return settings
    except Exception as e:
        print(f"Error loading configuration: {e}")
        print("\nRequired environment variables:")
        print("  - IMAP_SERVER")
        print("  - IMAP_USER")
        print("  - IMAP_PASS")
        print("  - NETFLIX_USER")
        print("  - NETFLIX_PASS")
        print("\nSee .env.example for a template")
        raise SystemExit(1) from e
